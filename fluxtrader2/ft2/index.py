"""P8 (B3) — the US stock index as information for the screener (PLAN §9 #7). `ft2 index fetch|ingest|inventory`.

Two index CFDs that trade round the clock on weekdays — the S&P 500 (US500) and the Nasdaq 100 (US100) — as one-minute
bars, from two keyless public sources measured 2026-10-01 (DATA.md "index_1m"):

histdata   THE SOURCE OF THE PARQUET. HistData.com's generic ASCII one-minute bars, SPXUSD and NSXUSD, from 2010: one zip a
           year for past years, one a month for the current year (the current month is not offered). Timestamps are
           Eastern Standard Time WITHOUT daylight saving (a fixed UTC−5, converted here); bid quotes; the volume column is
           always 0 and is not kept; a minute without a tick is absent (no padding); each zip carries a status report of
           the tick gaps over 60 s. Fetched by the site's form: GET the referer page with a cookie jar, read the `tk`
           token, POST get.php. About 4.5 MB a year.
dukascopy  Dukascopy's datafeed: daily one-minute candle files (BID), USA500.IDX/USD and USATECH.IDX/USD, from 2011-09.
           Bulk fetching is throttled hard (2026-10-01: a few files a minute, then 503s and dropped connections for an
           hour from each address that tried) — so it is NOT the bulk source; what was fetched serves as a cross-check of
           HistData in the inventory, and its hourly tick files, published within the hour after the hour closes
           (the 06h file was up at 07:37 UTC), are a candidate live feed. Files: LZMA, 24-byte big-endian records
           (seconds since the day's start, open, close, low, high × 1000, volume); 1,440 rows a day, a minute without a
           trade repeats the last close with zero volume (dropped). The URL's month is ZERO-based.
yahoo      Yahoo's chart endpoint for the front E-mini future (ES=F): hourly bars two years deep, about ten minutes
           behind — a cross-check in the inventory and the other candidate live feed. Not a source.

raw        data/raw/external/histdata/<PAIR>/DAT_ASCII_<PAIR>_M1_<yyyy|yyyymm>.zip (+ .ok once it parsed);
           data/raw/external/dukascopy/<INSTR>/<yyyy>/<MM>/<dd>/BID_candles_min_1.bi5 (+ .ok | .404)
parquet    data/index_1m.parquet: (symbol, ts) → open, high, low, close; symbol US500 | US100; ts = the minute's open, UTC
           data/index_1m_dukascopy.parquet: the same from the Dukascopy days fetched, with volume (the cross-check)
"""
from __future__ import annotations

import http.cookiejar
import io
import json
import lzma
import random
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import data

SYMBOLS = ("US100", "US500")
HIST_PAIRS = {"US500": "SPXUSD", "US100": "NSXUSD"}
HIST_ROOT = data.RAW / "external" / "histdata"
HIST_PAGE = "https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/"
HIST_POST = "https://www.histdata.com/get.php"
EST = pd.Timedelta("5h")                 # the files' clock: EST without daylight saving = UTC − 5, all year
OUT = data.PROC / "index_1m.parquet"

INSTRUMENTS = {"US500": "USA500IDXUSD", "US100": "USATECHIDXUSD"}
DL = "https://datafeed.dukascopy.com/datafeed"
ROOT = data.RAW / "external" / "dukascopy"
OUT_DUKA = data.PROC / "index_1m_dukascopy.parquet"
SCALE = 1000.0
ROWS = 1440
RECORD = struct.Struct(">5if")
WORKERS = 3
RETRIES = 8                              # 3, 6, 12, 24, 48, 60, 60, 60 s (+ jitter)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

YAHOO = data.RAW / "external" / "yahoo"
REPORT = Path("output/index_inventory.md")
START = "2020-05-01"                     # FP's first day (folds.py): every fold, F0's warm-up included


# ---- HistData --------------------------------------------------------------------------------------------------------
def hist_periods(start: str = START, today: date | None = None) -> list[str]:
    """What to ask for: a year for each past year from `start`'s, a month for each complete month of the current year."""
    today = today or datetime.now(timezone.utc).date()
    y0 = date.fromisoformat(start).year
    return [str(y) for y in range(y0, today.year)] + [f"{today.year}{m:02d}" for m in range(1, today.month)]


def hist_path(sym: str, period: str) -> Path:
    pair = HIST_PAIRS[sym]
    return HIST_ROOT / pair / f"DAT_ASCII_{pair}_M1_{period}.zip"


def hist_fetch_one(sym: str, period: str, opener=None) -> str:
    dest = hist_path(sym, period)
    if dest.with_suffix(".zip.ok").exists():
        return "skip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    pair = HIST_PAIRS[sym]
    year, month = period[:4], (str(int(period[4:])) if len(period) == 6 else None)
    referer = HIST_PAGE + f"{pair.lower()}/{year}" + (f"/{month}" if month else "")
    opener = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    last = None
    for attempt in range(4):
        try:
            with opener.open(referer, timeout=60) as r:
                page = r.read().decode("utf-8", "replace")
            m = re.search(r'id="tk"\s+value="([0-9a-f]+)"', page)
            if not m:
                raise RuntimeError("no token on the page (the period may not be offered)")
            form = urllib.parse.urlencode({"tk": m.group(1), "date": year, "datemonth": period, "platform": "ASCII", "timeframe": "M1", "fxpair": pair}).encode()
            req = urllib.request.Request(HIST_POST, data=form, headers={"Referer": referer, "Origin": "https://www.histdata.com", "Content-Type": "application/x-www-form-urlencoded"})
            with opener.open(req, timeout=300) as r:
                body = r.read()
            hist_read(body, sym)                                   # it parses, or it is not kept
            tmp = dest.with_suffix(".zip.part")
            tmp.write_bytes(body)
            tmp.replace(dest)
            dest.with_suffix(".zip.ok").touch()
            return "ok"
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (attempt + 1))
    print(f"  err {sym} {period}: {last!r}", file=sys.stderr, flush=True)
    return "err"


def hist_fetch(start: str = START, symbols=SYMBOLS) -> dict:
    """Every period for the pairs, one request at a time, two seconds apart; resumable."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    counts = {}
    for sym in symbols:
        c = {"ok": 0, "skip": 0, "err": 0}
        for p in hist_periods(start):
            r = hist_fetch_one(sym, p, opener)
            c[r] += 1
            print(f"histdata {sym} {p}: {r}", flush=True)
            if r != "skip":
                time.sleep(2)
        counts[sym] = c
    print(f"fetched: {json.dumps(counts)}", flush=True)
    return counts


def hist_read(body: bytes, sym: str) -> pd.DataFrame:
    """One zip → rows (symbol, ts UTC, open, high, low, close). Raises when the zip or its csv is not what the site serves."""
    z = zipfile.ZipFile(io.BytesIO(body))
    csv = [n for n in z.namelist() if n.endswith(".csv")]
    if len(csv) != 1:
        raise ValueError(f"{len(csv)} csv in the zip")
    df = pd.read_csv(z.open(csv[0]), sep=";", header=None, names=["t", "open", "high", "low", "close", "volume"], dtype={"t": str})
    if not len(df):
        raise ValueError("an empty csv")
    ts = pd.to_datetime(df["t"], format="%Y%m%d %H%M%S", utc=True) + EST
    if not ((df["high"] >= df[["open", "close"]].max(axis=1)) & (df["low"] <= df[["open", "close"]].min(axis=1))).all():
        raise ValueError("a bar whose high or low does not hold its open and close")
    out = pd.DataFrame({"symbol": sym, "ts": ts, "open": df["open"], "high": df["high"], "low": df["low"], "close": df["close"]})
    back = int((ts.diff() < pd.Timedelta(0)).sum())              # the clock jumping back: the feed repeats an hour at a daylight-saving change
    out = out.sort_values("ts", kind="stable")                   # (NSXUSD 2020-10-25 19:00–19:59 EST twice); the later pass is kept
    dups = int(out["ts"].duplicated().sum())
    out = out.drop_duplicates("ts", keep="last").reset_index(drop=True)
    out.attrs = {"backwards": back, "dup_minutes": dups}
    return out


def hist_status(sym: str, period: str) -> str:
    """The status report shipped in the zip (the tick gaps over 60 s), as text."""
    z = zipfile.ZipFile(hist_path(sym, period))
    return z.read([n for n in z.namelist() if n.endswith(".txt")][0]).decode("utf-8", "replace")


def ingest(symbols=SYMBOLS) -> dict:
    """Every `.ok` HistData zip → data/index_1m.parquet."""
    parts, n_in = [], 0
    for sym in symbols:
        for f in sorted((HIST_ROOT / HIST_PAIRS[sym]).glob("*.zip")):
            if f.with_suffix(".zip.ok").exists():
                df = hist_read(f.read_bytes(), sym)
                n_in += len(df) + df.attrs["dup_minutes"]
                if df.attrs["backwards"]:
                    print(f"  {f.name}: the clock jumps back {df.attrs['backwards']} time(s), {df.attrs['dup_minutes']} minutes twice — the later pass kept", flush=True)
                parts.append(df)
    if not parts:
        raise SystemExit("index ingest: no fetched zip — run `ft2 index fetch` first")
    out = pd.concat(parts, ignore_index=True)
    out["symbol"] = pd.Categorical(out["symbol"], categories=sorted(SYMBOLS))
    out = out.sort_values(["symbol", "ts"]).drop_duplicates(["symbol", "ts"]).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)
    r = {"slice": "index_1m", "rows_in": n_in, "dups_dropped": n_in - len(out), "rows_out": len(out), "first": out["ts"].min(), "last": out["ts"].max(), "file": str(OUT)}
    print(f"{r['slice']:<15} rows_in={r['rows_in']:>11,} dups={r['dups_dropped']:>6,} rows_out={r['rows_out']:>11,}  {r['first']} .. {r['last']}", flush=True)
    return r


def load() -> pd.DataFrame:
    return pd.read_parquet(OUT)


# ---- Dukascopy -------------------------------------------------------------------------------------------------------
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


def duka_fetch(start: str = START, end: str | None = None, symbols=SYMBOLS, workers: int = WORKERS) -> dict:
    """Every day of [start, end] for the instruments; resumable. Slow: the feed throttles (the module docstring)."""
    a = date.fromisoformat(start)
    b = date.fromisoformat(end) if end else (datetime.now(timezone.utc).date() - timedelta(days=1))
    days = [a + timedelta(days=i) for i in range((b - a).days + 1)]
    counts: dict[str, dict[str, int]] = {}
    for sym in symbols:
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


def duka_ingest(symbols=SYMBOLS) -> dict:
    """Every `.ok` Dukascopy day → data/index_1m_dukascopy.parquet, the padded minutes dropped."""
    parts, n_in = [], 0
    for sym in symbols:
        for f in sorted((ROOT / INSTRUMENTS[sym]).glob("*/*/*/BID_candles_min_1.bi5")):
            if not f.with_suffix(".bi5.ok").exists():
                continue
            y, m0, d = (int(x) for x in f.parts[-4:-1])
            df = decode(f.read_bytes(), date(y, m0 + 1, d))
            n_in += len(df)
            df = df[~((df["volume"] == 0) & (df["open"] == df["close"]) & (df["high"] == df["low"]))]
            parts.append(df.assign(symbol=sym))
    if not parts:
        raise SystemExit("index ingest --source dukascopy: no fetched day")
    out = pd.concat(parts, ignore_index=True)
    out["symbol"] = pd.Categorical(out["symbol"], categories=sorted(SYMBOLS))
    out = out.sort_values(["symbol", "ts"]).drop_duplicates(["symbol", "ts"])[["symbol", "ts", "open", "high", "low", "close", "volume"]]
    OUT_DUKA.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_DUKA, index=False)
    r = {"slice": "index_1m_dukascopy", "rows_in": n_in, "dups_dropped": n_in - len(out), "rows_out": len(out), "first": out["ts"].min(), "last": out["ts"].max(), "file": str(OUT_DUKA)}
    print(f"{r['slice']:<15} rows_in={r['rows_in']:>11,} padded+dups={r['dups_dropped']:>9,} rows_out={r['rows_out']:>11,}  {r['first']} .. {r['last']}", flush=True)
    return r


# ---- Yahoo -----------------------------------------------------------------------------------------------------------
def yahoo_hourly(symbol: str = "ES=F", rng: str = "2y", fetch_live: bool = True) -> pd.DataFrame | None:
    """Yahoo's chart endpoint, hourly bars of the front E-mini future, saved under data/raw/external/yahoo/ once a day;
    None when it cannot be fetched. A cross-check, not a source."""
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


# ---- the inventory ---------------------------------------------------------------------------------------------------
def _hours(g: pd.DataFrame) -> pd.DataFrame:
    g = g.assign(wd=g["ts"].dt.dayofweek, hour=g["ts"].dt.hour, day=g["ts"].dt.floor("D"))
    per = g.groupby("wd")["day"].nunique()
    h = (g.groupby(["wd", "hour"]).size() / per).unstack("hour").reindex(index=range(7), columns=range(24)).fillna(0).round(0)
    h.index = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return h


def _gaps(g: pd.DataFrame, gap: pd.Timedelta) -> pd.DataFrame:
    """Runs longer than `gap` without a traded minute, the daily break (from 21:xx UTC) and the weekend (into Sunday) excluded."""
    t = g["ts"].sort_values().reset_index(drop=True)
    d = t.diff()
    big = pd.DataFrame({"from": t.shift(1)[d > gap], "to": t[d > gap], "gap": d[d > gap]})
    return big[~((big["from"].dt.hour == 21) | ((big["from"].dt.dayofweek >= 4) & (big["to"].dt.dayofweek == 6)))]


def inventory(out: Path = REPORT, fetch_live: bool = True) -> str:
    """What the parquet holds: extent, the hours the CFD trades (traded minutes by weekday × UTC hour), the gaps inside
    trading hours, and — described — the minutes against Dukascopy's days and the hours against Yahoo's front future."""
    x = load()
    md = [f"# The US index CFDs as fetched (`ft2 index inventory`)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {OUT} · a row is a traded minute; "
          "HistData's EST clock converted to UTC (+5 h, all year)\n"]
    rows = []
    for sym in sorted(SYMBOLS):
        g = x[x["symbol"] == sym]
        zips = sorted(p.name for p in (HIST_ROOT / HIST_PAIRS[sym]).glob("*.zip") if p.with_suffix(".zip.ok").exists())
        days = g["ts"].dt.floor("D").nunique()
        rows.append({"symbol": sym, "pair": HIST_PAIRS[sym], "zips": len(zips), "rows": len(g), "days": days, "first": g["ts"].min(), "last": g["ts"].max(),
                     "minutes_per_day": len(g) / max(days, 1), "min_close": g["close"].min(), "max_close": g["close"].max()})
    md += ["\n## Extent\n", pd.DataFrame(rows).round(1).to_markdown(index=False), "\n"]
    monthly = x.groupby([x["symbol"], x["ts"].dt.to_period("M")], observed=True).size().unstack(0)
    md += ["\n## Rows by month\n", monthly.to_markdown(), "\n"]
    GAP = pd.Timedelta("30min")
    for sym in sorted(SYMBOLS):
        g = x[x["symbol"] == sym]
        md += [f"\n## {sym}: traded minutes per hour, by weekday (60 = every minute, 0 = closed)\n", _hours(g).to_markdown(), "\n"]
        big = _gaps(g, GAP)
        md += [f"\n## {sym}: gaps inside trading hours — runs of more than {GAP} without a traded minute, the daily break and the weekend excluded\n",
               f"\n{len(big)} gaps; by year: {big.groupby(big['from'].dt.year).size().to_dict()}; the fifteen longest:\n",
               big.sort_values("gap", ascending=False).head(15).to_markdown(index=False), "\n"]
    if OUT_DUKA.exists():
        dk = pd.read_parquet(OUT_DUKA)
        for sym in sorted(SYMBOLS):
            a, b = x[x["symbol"] == sym].set_index("ts")["close"], dk[dk["symbol"] == sym].set_index("ts")["close"]
            both = pd.concat([a.rename("hist"), b.rename("duka")], axis=1)
            common = both.dropna()
            if len(common) < 100:
                md += [f"\n## {sym} against Dukascopy: fewer than 100 common minutes\n"]
                continue
            r = np.log(common).diff().dropna()
            lvl = (common["hist"] / common["duka"] - 1) * 1e4
            span = both.loc[common.index.min():common.index.max()]
            md += [f"\n## {sym} against Dukascopy's days ({common.index.min():%Y-%m-%d} → {common.index.max():%Y-%m-%d}; described)\n",
                   f"\n{len(common):,} common minutes; within that span HistData has {span['hist'].notna().sum():,} traded minutes and Dukascopy {span['duka'].notna().sum():,}; "
                   f"correlation of minute log returns {r['hist'].corr(r['duka']):.4f}; the level's difference HistData − Dukascopy, bps: median {lvl.median():+.1f}, "
                   f"5th–95th {lvl.quantile(0.05):+.1f} … {lvl.quantile(0.95):+.1f}.\n"]
    y = yahoo_hourly(fetch_live=fetch_live)
    if y is not None and len(y) > 100:
        g = x[x["symbol"] == "US500"]
        h = g.set_index("ts")["close"].resample("1h").last().dropna()
        both = pd.concat([h.rename("cfd"), y.set_index("ts")["close"].rename("es")], axis=1).dropna()
        r = np.log(both).diff().dropna()
        dd = np.log(both.resample("1D").last().dropna()).diff().dropna()
        md += ["\n## US500 against Yahoo's front E-mini future (ES=F, hourly, the last two years; described)\n",
               f"\n{len(both):,} common hours; correlation of hourly log returns {r['cfd'].corr(r['es']):.4f}, of daily {dd['cfd'].corr(dd['es']):.4f}; "
               f"the CFD's level ÷ the future's: median {float((both['cfd'] / both['es']).median()):.4f} (the basis).\n"]
    else:
        md += ["\n## US500 against Yahoo's front E-mini future: not fetched\n"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md))
    return "\n".join(md)


def main(action: str, source: str = "histdata", start: str | None = None, end: str | None = None, symbols=None, workers: int | None = None) -> None:
    symbols = tuple(symbols) if symbols else SYMBOLS
    if action == "fetch":
        (hist_fetch(start or START, symbols) if source == "histdata" else duka_fetch(start or START, end, symbols, workers or WORKERS))
    elif action == "ingest":
        (ingest(symbols) if source == "histdata" else duka_ingest(symbols))
    elif action == "inventory":
        print(inventory())
    else:
        raise SystemExit(f"index: unknown action {action}")
