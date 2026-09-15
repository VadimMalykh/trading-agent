"""Raw exports → typed, sorted, de-duplicated parquet; and loading them.

Layout (relative to the fluxtrader2/ working directory):
  data/raw/<slice>.csv.gz   what scripts/export.sh wrote, kept forever
  data/<slice>.parquet      what ingest() wrote; everything downstream reads only these
"""
from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd

RAW = Path("data/raw")
PROC = Path("data")

# slice -> (time column, key columns)
SLICES: dict[str, tuple[str, list[str]]] = {
    "candles_1m": ("open_time", ["symbol", "open_time"]),
    "candles_5m": ("open_time", ["symbol", "open_time"]),
    "candles_15m": ("open_time", ["symbol", "open_time"]),
    "candles_1h": ("open_time", ["symbol", "open_time"]),
    "snapshots": ("ts", ["symbol", "ts"]),
    "trades": ("window_start", ["symbol", "window_start"]),
    "funding": ("ts", ["symbol", "ts"]),
    "oi": ("ts", ["symbol", "ts"]),
    "lsr": ("ts", ["symbol", "period", "ts"]),
    # archive-derived (ingested by ingest_metrics / ingest_depth, same key convention)
    "metrics": ("ts", ["symbol", "ts"]),
}
TIME_COLS = {"open_time", "close_time", "ts", "event_time", "transaction_time",
             "window_start", "next_funding_time"}


def ingest(slice_: str) -> dict:
    """Read data/raw/<slice>.csv.gz, type it, sort by key, drop duplicate keys, write parquet.

    Returns a small dict of what happened (rows in, duplicates dropped, rows out)."""
    tcol, key = SLICES[slice_]
    src, dst = RAW / f"{slice_}.csv.gz", PROC / f"{slice_}.parquet"
    if not src.exists():
        raise FileNotFoundError(src)
    parts = []
    for chunk in pd.read_csv(src, chunksize=2_000_000, low_memory=False):
        for c in chunk.columns:
            if c in TIME_COLS:
                chunk[c] = pd.to_datetime(chunk[c], utc=True, format="ISO8601")
        parts.append(chunk)
    df = pd.concat(parts, ignore_index=True)
    n_in = len(df)
    df = df.sort_values(key, kind="mergesort").drop_duplicates(key, keep="last").reset_index(drop=True)
    df["symbol"] = df["symbol"].astype("category")
    PROC.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dst, index=False)
    return {"slice": slice_, "rows_in": n_in, "dups_dropped": n_in - len(df),
            "rows_out": len(df), "first": df[tcol].min(), "last": df[tcol].max(), "file": str(dst)}


def load(slice_: str, columns: list[str] | None = None, symbols: list[str] | None = None) -> pd.DataFrame:
    df = pd.read_parquet(PROC / f"{slice_}.parquet", columns=columns)
    if symbols is not None:
        df = df[df["symbol"].isin(symbols)].reset_index(drop=True)
    return df


def available() -> list[str]:
    return sorted(p.stem for p in PROC.glob("*.parquet"))


# ---- Binance public archive (data/raw/external/binance/<kind>/<symbol>/*.zip) -----------------
EXT = RAW / "external" / "binance"

METRICS_COLS = {
    "create_time": "ts", "sum_open_interest": "oi", "sum_open_interest_value": "oi_value",
    "count_toptrader_long_short_ratio": "top_ls_count", "sum_toptrader_long_short_ratio": "top_ls_sum",
    "count_long_short_ratio": "global_ls", "sum_taker_long_short_vol_ratio": "taker_ratio",
}


def _read_zips(kind: str, symbol: str, **read_csv_kw) -> pd.DataFrame:
    files = sorted((EXT / kind / symbol).glob("*.zip"))
    files = [f for f in files if f.with_suffix(".zip.ok").exists()]
    if not files:
        return pd.DataFrame()
    return pd.concat((pd.read_csv(f, **read_csv_kw) for f in files), ignore_index=True)


def ingest_metrics(symbols: list[str]) -> dict:
    """archive metrics (5m) → data/metrics.parquet: (symbol, ts) → oi, oi_value, top_ls_*, global_ls, taker_ratio."""
    parts = []
    for sym in symbols:
        df = _read_zips("metrics", sym)
        if df.empty:
            continue
        df = df.rename(columns=METRICS_COLS)[["symbol", "ts", *[c for c in METRICS_COLS.values() if c != "ts"]]]
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    n_in = len(df)
    df = df.sort_values(["symbol", "ts"], kind="mergesort").drop_duplicates(["symbol", "ts"], keep="last").reset_index(drop=True)
    df["symbol"] = df["symbol"].astype("category")
    df.to_parquet(PROC / "metrics.parquet", index=False)
    return {"slice": "metrics", "rows_in": n_in, "dups_dropped": n_in - len(df), "rows_out": len(df),
            "first": df["ts"].min(), "last": df["ts"].max(), "file": str(PROC / "metrics.parquet")}
