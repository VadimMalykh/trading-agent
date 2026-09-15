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
    # archive-derived (ingest_metrics / ingest_depth / ingest_funding_archive; same key convention)
    "metrics": ("ts", ["symbol", "ts"]),
    "depth": ("ts", ["symbol", "ts"]),              # data/depth/<symbol>.parquet, one file per pair
    "funding_archive": ("ts", ["symbol", "ts"]),
    "tape": ("ts", ["symbol", "ts"]),               # data/tape/<symbol>.parquet, per-minute (ft2 tape, P1)
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
    """A slice is either data/<slice>.parquet or a directory data/<slice>/<symbol>.parquet (large
    slices are written per pair so that one pair can be loaded without reading the others)."""
    d = PROC / slice_
    if d.is_dir():
        files = sorted(d.glob("*.parquet"))
        if symbols is not None:
            files = [f for f in files if f.stem in symbols]
        df = pd.concat((pd.read_parquet(f, columns=columns) for f in files), ignore_index=True)
        df["symbol"] = df["symbol"].astype(str).astype("category")
        return df
    df = pd.read_parquet(PROC / f"{slice_}.parquet", columns=columns)
    if symbols is not None:
        df = df[df["symbol"].isin(symbols)].reset_index(drop=True)
    return df


def available() -> list[str]:
    files = {p.stem for p in PROC.glob("*.parquet")}
    dirs = {p.name for p in PROC.iterdir() if p.is_dir() and p.name in SLICES and any(p.glob("*.parquet"))}
    return sorted(files | dirs)


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


DEPTH_LEVELS = [-5.0, -4.0, -3.0, -2.0, -1.0, -0.2, 0.2, 1.0, 2.0, 3.0, 4.0, 5.0]   # per cent from mid; negative = bid side
DEPTH_CORE = [p for p in DEPTH_LEVELS if abs(p) >= 1]     # present from 2023-01-01
DEPTH_FINE = [p for p in DEPTH_LEVELS if abs(p) < 1]      # ±0.2 %: the archive added them on 2026-01-15


def _depth_col(kind: str, pct: float) -> str:
    return f"{kind}_{'m' if pct < 0 else 'p'}{str(abs(pct)).replace('.', '').rstrip('0') or '0'}"   # 1.0 → p1, 0.2 → p02


def ingest_depth(symbols: list[str]) -> dict:
    """archive bookDepth → data/depth/<symbol>.parquet, wide: (symbol, ts) → qty_m5..qty_p5, usd_m5..usd_p5.

    The archive file is long (one row per timestamp × level): `timestamp, percentage, depth,
    notional` where `percentage` is ±1..±5 (per cent from mid, negative = bids; ±0.2 added by
    the archive from 2026-01-15), `depth` the cumulative base quantity resting within that band
    and `notional` its USDT value, sampled roughly every 30 s. There is no best bid/ask in it.
    Timestamps are pivoted to one row with twelve qty and twelve usd columns (qty_m5 … qty_m02,
    qty_p02 … qty_p5; the 02 ones NaN before 2026-01-15); a timestamp missing a core level keeps
    NaN there (counted as incomplete). ~3.9M rows × 24 float64 per long pair, ~750 MB each."""
    out_dir = PROC / "depth"
    out_dir.mkdir(parents=True, exist_ok=True)
    totals = {"rows_in": 0, "rows_out": 0, "dups_dropped": 0, "incomplete": 0}
    first, last = None, None
    for sym in symbols:
        files = sorted((EXT / "bookDepth" / sym).glob("*.zip"))
        files = [f for f in files if f.with_suffix(".zip.ok").exists()]
        if not files:
            continue
        parts = []
        for f in files:
            d = pd.read_csv(f, dtype={"percentage": "float64", "depth": "float64", "notional": "float64"})
            parts.append(d)
        long = pd.concat(parts, ignore_index=True)
        n_in = len(long)
        long["ts"] = pd.to_datetime(long["timestamp"], utc=True)
        long = long.drop_duplicates(["ts", "percentage"], keep="last")
        wide = long.pivot(index="ts", columns="percentage", values=["depth", "notional"])
        cols = {}
        for pct in DEPTH_LEVELS:
            cols[_depth_col("qty", pct)] = wide[("depth", pct)] if ("depth", pct) in wide else float("nan")
            cols[_depth_col("usd", pct)] = wide[("notional", pct)] if ("notional", pct) in wide else float("nan")
        df = pd.DataFrame(cols, index=wide.index).sort_index().reset_index()
        df.insert(0, "symbol", sym)
        df["symbol"] = df["symbol"].astype("category")
        core_cols = [_depth_col(k, p) for p in DEPTH_CORE for k in ("qty", "usd")]
        incomplete = int(df[core_cols].isna().any(axis=1).sum())
        df.to_parquet(out_dir / f"{sym}.parquet", index=False)
        totals["rows_in"] += n_in
        totals["rows_out"] += len(df)
        totals["dups_dropped"] += n_in - len(long)
        totals["incomplete"] += incomplete
        first = df["ts"].min() if first is None else min(first, df["ts"].min())
        last = df["ts"].max() if last is None else max(last, df["ts"].max())
        print(f"  depth {sym:<13} files={len(files):>5} rows={len(df):>10,} incomplete={incomplete:>6} "
              f"{df['ts'].min():%Y-%m-%d} .. {df['ts'].max():%Y-%m-%d}", flush=True)
        del long, wide, df, parts
    return {"slice": "depth", **totals, "first": first, "last": last, "file": str(out_dir)}


def ingest_funding_archive(symbols: list[str]) -> dict:
    """archive monthly fundingRate → data/funding_archive.parquet: (symbol, ts) → rate, interval_h.

    `calc_time` is the funding timestamp in ms; `funding_interval_hours` is 8 (or 4 on some
    pairs/periods); `last_funding_rate` the settled rate. Independent of the collector's
    funding_rates table, which it overlaps from 2022-08 — the inventory compares the two."""
    parts = []
    for sym in symbols:
        df = _read_zips("fundingRate", sym)
        if df.empty:
            continue
        # calc_time is sometimes 1 ms past the funding second (…:00.001); round to the second
        df = pd.DataFrame({"symbol": sym, "ts": pd.to_datetime(df["calc_time"], unit="ms", utc=True).dt.round("s"),
                           "rate": df["last_funding_rate"].astype(float),
                           "interval_h": df["funding_interval_hours"].astype("int16")})
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    n_in = len(df)
    df = df.sort_values(["symbol", "ts"], kind="mergesort").drop_duplicates(["symbol", "ts"], keep="last").reset_index(drop=True)
    df["symbol"] = df["symbol"].astype("category")
    df.to_parquet(PROC / "funding_archive.parquet", index=False)
    return {"slice": "funding_archive", "rows_in": n_in, "dups_dropped": n_in - len(df), "rows_out": len(df),
            "first": df["ts"].min(), "last": df["ts"].max(), "file": str(PROC / "funding_archive.parquet")}
