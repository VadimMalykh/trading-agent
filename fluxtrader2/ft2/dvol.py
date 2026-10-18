"""P8 (R54, PLAN §9 #7) — Deribit's implied volatility index (DVOL) as a data source: `ft2 dvol fetch|ingest|inventory`.

source     Deribit's public, keyless JSON-RPC endpoint `public/get_volatility_index_data` (currency, start/end in ms, resolution
           "1D"): daily candles [ts, open, high, low, close] of the 30-day implied volatility index in annualised %, the day in
           UTC (ts at 00:00). BTC and ETH from 2021-03-24; SOL from 2022-05-04 (its series stops in 2022-11 — inventoried, not
           read by the audit unless it covers the folds). The endpoint serves up to ~1,000 rows a call; the fetch asks in
           200-day windows, paced, and retries on a throttle.
raw        data/raw/external/deribit/dvol_<CUR>_1D_<YYYYMMDD>.json — a dated copy per fetch: {"currency", "fetched", "rows"}.
parquet    data/dvol.parquet: (currency, day) → open, high, low, close. The value KNOWN AT 00:00 UTC of day d is `open` (the
           candle's open equals the previous candle's close); a registration reads `open` and nothing else of the row.
inventory  output/dvol_inventory.md and a DATA.md row: per currency the extent, the gaps, the range, the per-fold cover of the
           scored days.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, folds

RAW = data.RAW / "external" / "deribit"
PARQUET = data.PROC / "dvol.parquet"
OUT = Path("output/dvol_inventory.md")
URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
CURRENCIES = ("BTC", "ETH", "SOL")
START = "2021-01-01"
WINDOW_DAYS = 200
PAUSE = 0.6
UA = {"User-Agent": "fluxtrader2-research/1.0"}
DAY_MS = 86_400_000


def _get(u: str, timeout: int = 60, retries: int = 6) -> dict:
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout) as r:
                j = json.loads(r.read())
            if "result" in j:
                return j["result"]
            last = j.get("error")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:   # noqa: PERF203
            last = e
        time.sleep(PAUSE * 2 ** i)
    raise RuntimeError(f"deribit: {u} failed after {retries} tries: {last}")


def fetch(currencies=CURRENCIES, start: str = START, end: str | None = None, today: pd.Timestamp | None = None) -> dict:
    RAW.mkdir(parents=True, exist_ok=True)
    today = today or pd.Timestamp.now("UTC").floor("D")
    a = pd.Timestamp(start, tz="UTC")
    b = pd.Timestamp(end, tz="UTC") if end else today
    report = {}
    for cur in currencies:
        rows, s = [], a
        while s < b:
            e = min(s + pd.Timedelta(days=WINDOW_DAYS), b)
            res = _get(f"{URL}?currency={cur}&start_timestamp={int(s.timestamp() * 1000)}&end_timestamp={int(e.timestamp() * 1000) - 1}&resolution=1D")
            rows += [list(map(float, r)) for r in res.get("data", [])]
            s = e
            time.sleep(PAUSE)
        dest = RAW / f"dvol_{cur}_1D_{today:%Y%m%d}.json"
        dest.write_text(json.dumps({"currency": cur, "fetched": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC", "start": str(a), "end": str(b), "rows": rows}))
        report[cur] = {"rows": len(rows), "file": str(dest)}
        print(f"dvol fetch {cur}: {len(rows)} rows → {dest}", flush=True)
    return report


def latest_raw(cur: str) -> Path | None:
    files = sorted(RAW.glob(f"dvol_{cur}_1D_*.json"))
    return files[-1] if files else None


def ingest(currencies=CURRENCIES) -> dict:
    parts, report = [], {}
    for cur in currencies:
        f = latest_raw(cur)
        if f is None:
            report[cur] = "no raw file"
            continue
        rows = json.loads(f.read_text())["rows"]
        d = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
        d["ts"] = pd.to_datetime(d["ts"].astype("int64"), unit="ms", utc=True)
        off = int((d["ts"] != d["ts"].dt.floor("D")).sum())
        d = d[d["ts"] == d["ts"].dt.floor("D")]
        d = d.drop_duplicates("ts", keep="last").sort_values("ts")
        parts.append(pd.DataFrame({"currency": cur, "day": d["ts"].to_numpy(), "open": d["open"].to_numpy(), "high": d["high"].to_numpy(),
                                   "low": d["low"].to_numpy(), "close": d["close"].to_numpy()}))
        report[cur] = {"rows": int(len(d)), "rows_off_midnight_dropped": off, "first": str(d["ts"].min().date()) if len(d) else None,
                       "last": str(d["ts"].max().date()) if len(d) else None, "raw": f.name}
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["currency", "day", "open", "high", "low", "close"])
    PARQUET.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(PARQUET, index=False)
    print(f"dvol ingest: {len(out)} rows → {PARQUET}", flush=True)
    return report


def load(path: Path | str = PARQUET) -> pd.DataFrame:
    d = pd.read_parquet(path)
    d["day"] = pd.DatetimeIndex(d["day"]).tz_convert("UTC") if pd.DatetimeIndex(d["day"]).tz is not None else pd.DatetimeIndex(d["day"]).tz_localize("UTC")
    return d


def inventory(fold_names=("F1", "F2"), path: Path | str = PARQUET) -> str:
    d = load(path)
    lines = ["# DVOL — Deribit's implied volatility index, daily (`ft2 dvol`)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {PARQUET}\n",
             "\nThe value known at 00:00 UTC of a day is the candle's `open` (equal to the previous close); the folds' cover counts the scored days of each fold that have a row.\n"]
    rows = []
    for cur, g in d.groupby("currency"):
        days = pd.DatetimeIndex(g["day"])
        full = pd.date_range(days.min(), days.max(), freq="D")
        gaps = full.difference(days)
        r = {"currency": cur, "first": str(days.min().date()), "last": str(days.max().date()), "days": len(days), "missing_days_inside": len(gaps),
             "open_min": float(g["open"].min()), "open_max": float(g["open"].max()), "open_median": float(g["open"].median()),
             "open_eq_prev_close": float((g["open"].to_numpy()[1:] == g["close"].to_numpy()[:-1]).mean()) if len(g) > 1 else np.nan}
        for f in [*fold_names, "F3", "F4", "F5"]:
            a, b = folds.bounds(f)
            sd = pd.date_range(a.floor("D"), b - pd.Timedelta(1, "ns"), freq="D")
            r[f"cover_{f}"] = float(sd.isin(days).mean())
        rows.append(r)
    tab = pd.DataFrame(rows)
    lines += ["\n## Per currency\n", tab.round(4).to_markdown(index=False), "\n"]
    row = ("| **DVOL** (Deribit's 30-day implied volatility index, daily; R54, §9 #7) | `ft2 dvol fetch` from `public/get_volatility_index_data`, raw `data/raw/external/deribit/` | "
           + "; ".join(f"{r['currency']} {r['first']} → {r['last']} ({r['days']} days, {r['missing_days_inside']} missing inside; F1 {r['cover_F1']:.0%}, F2 {r['cover_F2']:.0%})" for r in rows)
           + " | `data/dvol.parquet` (currency, day) → open, high, low, close; the value known at 00:00 UTC is `open` |")
    lines += ["\n## DATA.md row\n", "\n" + row + "\n"]
    txt = "\n".join(lines)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(txt)
    return txt


def main(action: str, currencies=None, start: str = START) -> None:
    cur = tuple(currencies) if currencies else CURRENCIES
    if action == "fetch":
        print(json.dumps(fetch(cur, start), indent=1))
    elif action == "ingest":
        print(json.dumps(ingest(cur), indent=1))
    elif action == "inventory":
        print(inventory())
    else:
        sys.exit(f"dvol: unknown action {action}")
