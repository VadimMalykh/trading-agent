"""P8 (B3) — the US stock index as information for the screener (PLAN §9 #7). `ft2 index fetch|ingest|inventory`.

source   Dukascopy's public datafeed (no key): the daily one-minute candle files, BID side, of two index CFDs that trade
         round the clock on weekdays — USA500.IDX/USD (the S&P 500) and USATECH.IDX/USD (the Nasdaq 100). Measured
         2026-10-01 (DATA.md "index_1m"): minute data from 2011-09; a break 21:00–22:00 UTC each weekday; nothing on
         Saturday; the week opens Sunday 22:00 UTC; the server answers 503 or drops the connection often, so every file
         is fetched with retries and a few workers.
url      https://datafeed.dukascopy.com/datafeed/<INSTR>/<yyyy>/<MM>/<dd>/BID_candles_min_1.bi5 — MM is the month
         ZERO-based (January = 00)
file     LZMA; 24-byte big-endian records: seconds since the day's start, open, close, low, high (all × 1000), volume
         (a float, the feed's own unit)
padded   a day's file always has 1,440 rows: a minute without a trade repeats the last close with zero volume (the daily
         break, the weekend). Those are dropped at ingest, so a row of the parquet is a traded minute.
raw      data/raw/external/dukascopy/<INSTR>/<yyyy>/<MM>/<dd>/BID_candles_min_1.bi5, with `.ok` beside it once it decoded
         to 1,440 monotone rows, or `.404` when the feed has no file for that day (then nothing is retried)
parquet  data/index_1m.parquet: (symbol, ts) → open, high, low, close, volume; symbol US500 | US100; ts = the minute's
         open, UTC
live     the same feed publishes an hour's tick file within the hour after the hour closes (2026-10-01: the 06h file
         was up at 07:37 UTC). Yahoo's chart endpoint for the ES future answers about ten minutes behind. Which one the
         serve host reads is decided when a feature is registered, not here.
"""
from __future__ import annotations

import json
import lzma
import random
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import data

DL = "https://datafeed.dukascopy.com/datafeed"
INSTRUMENTS = {"US500": "USA500IDXUSD", "US100": "USATECHIDXUSD"}
ROOT = data.RAW / "external" / "dukascopy"
OUT = data.PROC / "index_1m.parquet"
REPORT = Path("output/index_inventory.md")
YAHOO = data.RAW / "external" / "yahoo"
SCALE = 1000.0
ROWS = 1440
RECORD = struct.Struct(">5if")
WORKERS = 3          # the feed throttles: three in flight keeps the share of 503s tolerable (measured 2026-10-01)
RETRIES = 8          # 3, 6, 12, 24, 48, 60, 60, 60 s (+ jitter): a few minutes of refusal absorbed
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
START = "2020-05-01"  # FP's first day (folds.py): every fold, F0's warm-up included


def path(instr: str, d: date) -> Path:
    return ROOT / instr / f"{d.year:04d}" / f"{d.month - 1:02d}" / f"{d.day:02d}" / "BID_candles_min_1.bi5"


def url(instr: str, d: date) -> str:
    return f"{DL}/{instr}/{d.year:04d}/{d.month - 1:02d}/{d.day:02d}/BID_candles_min_1.bi5"


def decode(body: bytes, day: date) -> pd.DataFrame:
    """One day's file → the 1,440 rows, prices in index points, ts = the minute's open (UTC). Raises if it is not what a
    day's file is (so a 503 page or a truncated download never gets an `.ok`)."""
    raw = lzma.decompress(body)
    if len(raw) != ROWS * RECORD.size:
        raise ValueError(f"{len(raw)} bytes, not {ROWS} records")
    rec = np.frombuffer(raw, dtype=np.dtype([("sec", ">i4"), ("open", ">i4"), ("close", ">i4"), ("low", ">i4"), ("high", ">i4"), ("vol", ">f4")]))
    sec = rec["sec"].astype(np.int64)
    if not (sec == np.arange(0, ROWS * 60, 60)).all():
        raise ValueError("the minutes are not 0, 60, … 86340")
    t0 = pd.Timestamp(day, tz="UTC")
    return pd.DataFrame({"ts": t0 + pd.to_timedelta(sec, unit="s"), "open": rec["open"] / SCALE, "high": rec["high"] / SCALE,
                         "low": rec["low"] / SCALE, "close": rec["close"] / SCALE, "volume": rec["vol"].astype(np.float64)})


def _get(u: str, timeout: int = 60) -> tuple[int, bytes]:
    """(status, body): 200 with the body, 404 with nothing; a 5xx or a dropped connection is retried RETRIES times, then raised."""
    last = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, b""
            last = e
        except Exception as e:  # noqa: BLE001 — URLError, ConnectionResetError, timeout, IncompleteRead
            last = e
        time.sleep(min(3 * 2 ** attempt, 60) + random.uniform(0, 2))
    raise RuntimeError(f"{u}: {last!r}")


def _fetch_one(instr: str, d: date) -> str:
    dest = path(instr, d)
    if dest.with_suffix(".bi5.ok").exists() or dest.with_suffix(".bi5.404").exists():
        return "skip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        status, body = _get(url(instr, d))
    except Exception as e:  # noqa: BLE001
        print(f"  err {instr} {d}: {e!r}", file=sys.stderr, flush=True)
        return "err"
    if status == 404:
        dest.with_suffix(".bi5.404").touch()
        return "404"
    try:
        decode(body, d)
    except Exception as e:  # noqa: BLE001
        print(f"  bad {instr} {d}: {e!r}", file=sys.stderr, flush=True)
        return "bad"
    tmp = dest.with_suffix(".bi5.part")
    tmp.write_bytes(body)
    tmp.replace(dest)
    dest.with_suffix(".bi5.ok").touch()
    return "ok"


def fetch(start: str = START, end: str | None = None, symbols: list[str] | None = None, workers: int = WORKERS) -> dict:
    """Every day of [start, end] for the instruments; resumable (`.ok` / `.404` are never fetched again). `end` defaults
    to yesterday (UTC): the current day's file is still being written."""
    a = date.fromisoformat(start)
    b = date.fromisoformat(end) if end else (datetime.now(timezone.utc).date() - timedelta(days=1))
    days = [a + timedelta(days=i) for i in range((b - a).days + 1)]
    counts: dict[str, dict[str, int]] = {}
    for sym in symbols or list(INSTRUMENTS):
        instr = INSTRUMENTS[sym]
        c = {"ok": 0, "skip": 0, "404": 0, "bad": 0, "err": 0}
        t0 = time.time()
        with ThreadPoolExecutor(workers) as ex:
            for i, r in enumerate(ex.map(lambda d: _fetch_one(instr, d), days), 1):
                c[r] += 1
                if i % 100 == 0 or i == len(days):
                    print(f"{sym}: {i}/{len(days)} days  {c}  {time.time() - t0:.0f}s", flush=True)
        counts[sym] = c
    print(f"fetched: {json.dumps(counts)}", flush=True)
    return counts


def ingest(symbols: list[str] | None = None) -> dict:
    """Every `.ok` file → data/index_1m.parquet, the padded minutes dropped."""
    parts, n_in = [], 0
    for sym in symbols or list(INSTRUMENTS):
        for f in sorted((ROOT / INSTRUMENTS[sym]).glob("*/*/*/BID_candles_min_1.bi5")):
            if not f.with_suffix(".bi5.ok").exists():
                continue
            y, m0, d = (int(x) for x in f.parts[-4:-1])
            df = decode(f.read_bytes(), date(y, m0 + 1, d))
            n_in += len(df)
            df = df[~((df["volume"] == 0) & (df["open"] == df["close"]) & (df["high"] == df["low"]))]
            parts.append(df.assign(symbol=sym))
    if not parts:
        raise SystemExit("index ingest: no fetched day — run `ft2 index fetch` first")
    out = pd.concat(parts, ignore_index=True)
    out["symbol"] = pd.Categorical(out["symbol"], categories=sorted(INSTRUMENTS))
    out = out.sort_values(["symbol", "ts"]).drop_duplicates(["symbol", "ts"])[["symbol", "ts", "open", "high", "low", "close", "volume"]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)
    r = {"slice": "index_1m", "rows_in": n_in, "dups_dropped": n_in - len(out), "rows_out": len(out), "first": out["ts"].min(), "last": out["ts"].max(), "file": str(OUT)}
    print(f"{r['slice']:<15} rows_in={r['rows_in']:>11,} padded+dups={r['dups_dropped']:>9,} rows_out={r['rows_out']:>11,}  {r['first']} .. {r['last']}", flush=True)
    return r


def load() -> pd.DataFrame:
    return pd.read_parquet(OUT)


def yahoo_hourly(symbol: str = "ES=F", rng: str = "2y", fetch_live: bool = True) -> pd.DataFrame | None:
    """Yahoo's chart endpoint, hourly bars of the front E-mini future (ten minutes behind, two years deep), saved under
    data/raw/external/yahoo/ once a day; None when it cannot be fetched. A cross-check of the CFD, not a source."""
    YAHOO.mkdir(parents=True, exist_ok=True)
    f = YAHOO / f"{symbol.replace('=', '')}_1h_{datetime.now(timezone.utc):%Y-%m-%d}.json"
    if not f.exists():
        if not fetch_live:
            return None
        try:
            u = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1h&range={rng}"
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
                f.write_bytes(r.read())
        except Exception as e:  # noqa: BLE001
            print(f"yahoo: {e!r}", file=sys.stderr, flush=True)
            return None
    j = json.loads(f.read_text())["chart"]["result"][0]
    q = j["indicators"]["quote"][0]
    return pd.DataFrame({"ts": pd.to_datetime(j["timestamp"], unit="s", utc=True), "close": q["close"]}).dropna()


def inventory(out: Path = REPORT, fetch_live: bool = True) -> str:
    """What was fetched and what it holds: extent, the hours the CFD trades (traded minutes by weekday × UTC hour), the
    gaps inside trading hours, and the hourly returns against Yahoo's front future (described). → output/index_inventory.md"""
    x = load()
    md = [f"# The US index CFDs as fetched (`ft2 index inventory`)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {OUT} · a row is a traded minute\n"]
    rows = []
    for sym in sorted(INSTRUMENTS):
        instr = ROOT / INSTRUMENTS[sym]
        oks, n404 = len(list(instr.glob("*/*/*/*.ok"))), len(list(instr.glob("*/*/*/*.404")))
        g = x[x["symbol"] == sym]
        rows.append({"symbol": sym, "instrument": INSTRUMENTS[sym], "days_fetched": oks, "days_absent_404": n404, "rows": len(g),
                     "first": g["ts"].min(), "last": g["ts"].max(), "traded_min_per_fetched_day": len(g) / max(oks, 1),
                     "min_close": g["close"].min(), "max_close": g["close"].max()})
    md += ["\n## Extent\n", pd.DataFrame(rows).round(1).to_markdown(index=False), "\n"]
    g = x[x["symbol"] == "US500"].copy()
    g["wd"], g["hour"], g["day"] = g["ts"].dt.dayofweek, g["ts"].dt.hour, g["ts"].dt.floor("D")
    days_per_wd = g.groupby("wd")["day"].nunique()
    hours = (g.groupby(["wd", "hour"]).size() / days_per_wd).unstack("hour").reindex(index=range(7), columns=range(24)).fillna(0).round(0)
    hours.index = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    md += ["\n## The hours — traded minutes per hour, by weekday (US500; 60 = every minute traded, 0 = closed)\n", hours.to_markdown(), "\n"]
    # gaps: on the weekday grid outside the break and the weekend, a run of missing minutes longer than GAP
    GAP = pd.Timedelta("30min")
    t = g["ts"].sort_values()
    d = t.diff()
    big = pd.DataFrame({"from": t.shift(1)[d > GAP], "to": t[d > GAP], "gap": d[d > GAP]})
    big = big[~((big["from"].dt.hour == 20) | ((big["from"].dt.dayofweek >= 4) & (big["to"].dt.dayofweek == 6)))]   # not the break, not the weekend
    md += [f"\n## Gaps inside trading hours (US500): runs of more than {GAP} without a traded minute, the daily break and the weekend excluded\n",
           f"\n{len(big)} gaps; by year: {big.groupby(big['from'].dt.year).size().to_dict()}; the twenty longest:\n",
           big.sort_values("gap", ascending=False).head(20).to_markdown(index=False), "\n"]
    y = yahoo_hourly(fetch_live=fetch_live)
    if y is not None and len(y) > 100:
        h = g.set_index("ts")["close"].resample("1h").last().dropna()
        both = pd.concat([h.rename("cfd"), y.set_index("ts")["close"].rename("es")], axis=1).dropna()
        r = np.log(both).diff().dropna()
        dd = np.log(both.resample("1D").last().dropna()).diff().dropna()
        md += ["\n## Against Yahoo's front E-mini future (ES=F, hourly, the last two years; described)\n",
               f"\n{len(both):,} common hours; correlation of hourly log returns {r['cfd'].corr(r['es']):.4f}, of daily {dd['cfd'].corr(dd['es']):.4f}; "
               f"the CFD's level ÷ the future's: median {float((both['cfd'] / both['es']).median()):.4f} (the basis, and the cash–future gap).\n"]
    else:
        md += ["\n## Against Yahoo's front E-mini future: not fetched\n"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md))
    return "\n".join(md)


def main(action: str, start: str | None = None, end: str | None = None, symbols: list[str] | None = None, workers: int | None = None) -> None:
    if action == "fetch":
        fetch(start or START, end, symbols, workers or WORKERS)
    elif action == "ingest":
        ingest(symbols)
    elif action == "inventory":
        print(inventory())
    else:
        raise SystemExit(f"index: unknown action {action}")
