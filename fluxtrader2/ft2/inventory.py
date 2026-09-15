"""P0 integrity report over the ingested parquet files. Writes output/inventory.md.

Per slice and symbol: rows, first, last. Then the checks that decide whether the data can be
trusted for the horizons the plan studies:
  * candles: interior gaps (missing bars strictly between first and last) per interval;
  * candles: 5m vs 1m consistency — a 5m bar must equal the aggregate of its five 1m bars
    (open=first, high=max, low=min, close=last, volume=sum). A mismatch rate above rounding
    means bars were written before they closed (partial bars) or the two feeds disagree;
  * snapshots: local-clock minus exchange-clock skew (p50/p95) where event_time exists;
  * trades: share of windows at the poller's cap (right-censored windows);
  * archive metrics (5m) and depth (~30 s): step cadence, missing days, interior gaps, and for
    depth the rows with a missing level; archive funding vs the collector's funding_rates where
    they overlap (same timestamp → same rate?).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import data

STEP = {"candles_1m": "1min", "candles_5m": "5min", "candles_15m": "15min", "candles_1h": "1h"}


def _extent_table(slice_: str) -> pd.DataFrame:
    tcol, _ = data.SLICES[slice_]
    df = data.load(slice_, columns=["symbol", tcol])
    g = df.groupby("symbol", observed=True)[tcol]
    return pd.DataFrame({"rows": g.size(), "first": g.min(), "last": g.max()})


def _candle_gaps(slice_: str) -> pd.DataFrame:
    df = data.load(slice_, columns=["symbol", "open_time"])
    step = pd.Timedelta(STEP[slice_])
    out = {}
    for sym, s in df.groupby("symbol", observed=True)["open_time"]:
        d = s.sort_values().diff().dropna()
        gaps = d[d > step]
        out[sym] = {"gaps": int(len(gaps)), "missing_bars": int(((gaps / step) - 1).sum()),
                    "largest_gap": str(gaps.max()) if len(gaps) else "-"}
    return pd.DataFrame(out).T


def _partial_bar_check() -> pd.DataFrame:
    """Per symbol and month: share of 5m bars whose OHLCV disagrees with their 1m aggregate."""
    c1 = data.load("candles_1m", columns=["symbol", "open_time", "open", "high", "low", "close", "volume"])
    c5 = data.load("candles_5m", columns=["symbol", "open_time", "open", "high", "low", "close", "volume"])
    c1["bucket"] = c1["open_time"].dt.floor("5min")
    agg = (c1.sort_values(["symbol", "open_time"])
             .groupby(["symbol", "bucket"], observed=True)
             .agg(n=("open", "size"), open=("open", "first"), high=("high", "max"),
                  low=("low", "min"), close=("close", "last"), volume=("volume", "sum"))
             .reset_index().rename(columns={"bucket": "open_time"}))
    m = c5.merge(agg, on=["symbol", "open_time"], how="inner", suffixes=("", "_1m"))
    m = m[m["n"] == 5]
    tol = 1e-9
    bad_px = ((np.abs(m["open"] - m["open_1m"]) > tol * m["open"]) |
              (np.abs(m["high"] - m["high_1m"]) > tol * m["high"]) |
              (np.abs(m["low"] - m["low_1m"]) > tol * m["low"]) |
              (np.abs(m["close"] - m["close_1m"]) > tol * m["close"]))
    bad_vol = np.abs(m["volume"] - m["volume_1m"]) > 1e-6 * np.maximum(m["volume"], 1)
    m["bad"] = bad_px | bad_vol
    m["month"] = m["open_time"].dt.to_period("M").astype(str)
    r = m.groupby(["symbol", "month"], observed=True)["bad"].agg(["size", "mean"])
    r.columns = ["bars_compared", "mismatch_share"]
    return r[r["mismatch_share"] > 0.001]  # only months worth looking at


def _clock_skew() -> pd.DataFrame:
    df = data.load("snapshots", columns=["symbol", "ts", "event_time"]).dropna(subset=["event_time"])
    df["skew_ms"] = (df["ts"] - df["event_time"]).dt.total_seconds() * 1000
    g = df.groupby("symbol", observed=True)["skew_ms"]
    return pd.DataFrame({"rows_with_event_time": g.size(), "p50_ms": g.quantile(0.5).round(0),
                         "p95_ms": g.quantile(0.95).round(0)})


def _trade_censoring() -> pd.DataFrame:
    df = data.load("trades", columns=["symbol", "trade_count"])
    cap = int(df["trade_count"].max())
    g = df.groupby("symbol", observed=True)["trade_count"]
    return pd.DataFrame({"windows": g.size(), "cap": cap, "share_at_cap": (g.apply(lambda s: (s >= cap).mean())).round(4)})


def _archive_cadence(slice_: str, expected: str) -> pd.DataFrame:
    """Per symbol: rows, days present, days missing inside [first, last], median step, gaps > 2×step."""
    df = data.load(slice_, columns=["symbol", "ts"])
    step = pd.Timedelta(expected)
    out = {}
    for sym, s in df.groupby("symbol", observed=True)["ts"]:
        s = s.sort_values()
        days = s.dt.floor("D").drop_duplicates()
        span_days = (days.max() - days.min()).days + 1
        d = s.diff().dropna()
        gaps = d[d > 2 * step]
        out[sym] = {"rows": int(len(s)), "first": s.min(), "last": s.max(),
                    "days": int(len(days)), "days_missing": int(span_days - len(days)),
                    "median_step": str(d.median()), "gaps>2step": int(len(gaps)),
                    "largest_gap": str(gaps.max()) if len(gaps) else "-"}
    return pd.DataFrame(out).T


def _depth_completeness() -> pd.DataFrame:
    """Per symbol: rows missing a core (±1..5 %) level, rows carrying the ±0.2 % bands (2026-01-15 →), rows/day."""
    core = [data._depth_col(k, p) for p in data.DEPTH_CORE for k in ("qty", "usd")]
    fine = [data._depth_col(k, p) for p in data.DEPTH_FINE for k in ("qty", "usd")]
    out = {}
    for sym in sorted(p.stem for p in (data.PROC / "depth").glob("*.parquet")):
        df = data.load("depth", symbols=[sym])
        has_fine = df[fine].notna().all(axis=1)
        out[sym] = {"rows": int(len(df)), "incomplete_core_rows": int(df[core].isna().any(axis=1).sum()),
                    "rows_with_02pct": int(has_fine.sum()),
                    "first_02pct": str(df.loc[has_fine, "ts"].min())[:10] if has_fine.any() else "-",
                    "rows_per_day_median": float(df.groupby(df["ts"].dt.floor("D")).size().median())}
    return pd.DataFrame(out).T


def _funding_crosscheck() -> pd.DataFrame:
    """Archive funding vs the collector's funding_rates at the same (symbol, funding timestamp)."""
    a = data.load("funding_archive")
    c = data.load("funding", columns=["symbol", "ts", "last_funding_rate"]).dropna()
    # the collector samples the *upcoming* rate per minute; the row at the funding minute holds the settled rate
    c["ts"] = c["ts"].dt.floor("min")
    m = a.merge(c, on=["symbol", "ts"], how="left")
    m["matched"] = m["last_funding_rate"].notna()
    m["same"] = m["matched"] & (np.abs(m["last_funding_rate"] - m["rate"]) < 1e-8)
    g = m.groupby("symbol", observed=True)
    return pd.DataFrame({"archive_rows": g.size(), "overlap_rows": g["matched"].sum(),
                         "same_rate_share": (g["same"].sum() / g["matched"].sum().clip(lower=1)).round(4),
                         "interval_h": g["interval_h"].agg(lambda s: ",".join(map(str, sorted(s.unique()))))})


def run(out: Path = Path("output/inventory.md")) -> str:
    md = ["# Inventory — measured from data/*.parquet\n", f"generated {pd.Timestamp.utcnow():%Y-%m-%d %H:%M} UTC\n"]
    have = data.available()
    for s in have:
        if s in ("metrics", "depth"):
            continue  # reported with their cadence below
        md += [f"\n## {s}\n", _extent_table(s).to_markdown(), "\n"]
        if s in STEP:
            md += [f"\n### {s}: interior gaps\n", _candle_gaps(s).to_markdown(), "\n"]
    if "metrics" in have:
        md += ["\n## metrics (archive, 5m): extent and cadence\n", _archive_cadence("metrics", "5min").to_markdown(), "\n"]
    if "depth" in have:
        md += ["\n## depth (archive bookDepth, ~30 s): extent and cadence\n", _archive_cadence("depth", "30s").to_markdown(), "\n",
               "\n### depth: completeness (all ten levels present?)\n", _depth_completeness().to_markdown(), "\n"]
    if {"funding_archive", "funding"} <= set(have):
        md += ["\n## funding: archive vs collector at the same funding timestamp\n", _funding_crosscheck().to_markdown(), "\n"]
    if {"candles_1m", "candles_5m"} <= set(have):
        r = _partial_bar_check()
        md += ["\n## 5m vs 1m consistency (symbol-months with >0.1% mismatching bars)\n",
               r.to_markdown() if len(r) else "_none — every 5m bar equals its 1m aggregate_", "\n"]
    if "snapshots" in have:
        md += ["\n## snapshots: local minus exchange clock\n", _clock_skew().to_markdown(), "\n"]
    if "trades" in have:
        md += ["\n## trades: windows at the poller cap (right-censored)\n", _trade_censoring().to_markdown(), "\n"]
    text = "\n".join(md)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return text
