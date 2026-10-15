"""X8c identity follow-up, 2026-10-15 (run: ./scripts/m3.sh m3/archivebook_diag.py) (descriptive, no bar): is the 5-9 % median miss clock jitter or a
definitional difference?  (1) median |rel diff| by |dt| bucket of the nearest match; (2) an
offset scan of the archive clock; (3) the band's own relative change between the collector's
consecutive rows (~10 s) and the archive's (30 s); (4) the signed median ratio collector/archive."""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/workspace/train")
from data.db import depth_stale_mask
from data.features import DEPTH_SERVED_PAIRS
from m3.archivebook import to_collector_columns

c = pd.read_csv("output/archive/collector_depth_20261015.csv")
c["ts"] = pd.to_datetime(c["ts"], utc=True)
lo, hi = c["ts"].min(), c["ts"].max()
tol = pd.Timedelta(seconds=15)
print(f"{'pair':<13}{'n':>7} | self-change median: coll~10s  arch 30s | |dt| buckets (median rel, bid): "
      f"0-2  2-5  5-10  10-15 | best offset s (median rel @ tol 5s) | median coll/arch bid ask")
for s in sorted(DEPTH_SERVED_PAIRS):
    a = pd.read_parquet(f"output/archive/bookdepth/{s}.parquet")
    a["ts"] = pd.to_datetime(a["ts"], utc=True)
    a = a[(a["ts"] >= lo - tol) & (a["ts"] <= hi + tol)].sort_values("ts").reset_index(drop=True)
    a = to_collector_columns(a)
    a = a[~depth_stale_mask(a)].reset_index(drop=True)
    g = c[c["symbol"] == s].sort_values("ts").reset_index(drop=True)
    g = g[~depth_stale_mask(g)].reset_index(drop=True)
    g = g[(g["bid_reach_bps"] >= 20) & (g["ask_reach_bps"] >= 20) & (g["bid_band_0_2"] > 0) & (g["ask_band_0_2"] > 0)]
    # (3) self-variability
    gd = g["ts"].diff().dt.total_seconds()
    gr = (g["bid_band_0_2"].diff().abs() / g["bid_band_0_2"].shift())
    self_c = gr[(gd >= 5) & (gd <= 15)].median()
    ad = a["ts"].diff().dt.total_seconds()
    ar = (a["bid_band_0_2"].diff().abs() / a["bid_band_0_2"].shift())
    self_a = ar[(ad >= 25) & (ad <= 35)].median()
    # (1) by |dt|
    gg = g[["ts", "bid_band_0_2", "ask_band_0_2"]].rename(columns={"bid_band_0_2": "c_bid", "ask_band_0_2": "c_ask"})
    gg["cts"] = gg["ts"]
    m = pd.merge_asof(a[["ts", "bid_band_0_2", "ask_band_0_2"]], gg, on="ts", direction="nearest", tolerance=tol).dropna(subset=["c_bid"])
    m["adt"] = (m["ts"] - m["cts"]).dt.total_seconds().abs()
    m["rel"] = (m["bid_band_0_2"] - m["c_bid"]).abs() / m["c_bid"]
    b = [m.loc[(m["adt"] >= x0) & (m["adt"] < x1), "rel"].median() for x0, x1 in ((0, 2), (2, 5), (5, 10), (10, 15.01))]
    # (2) offset scan
    best = None
    for off in range(-30, 31, 2):
        aa = a[["ts", "bid_band_0_2"]].copy()
        aa["ts"] = aa["ts"] + pd.Timedelta(seconds=off)
        mm = pd.merge_asof(aa, gg[["ts", "c_bid"]], on="ts", direction="nearest", tolerance=pd.Timedelta(seconds=5)).dropna()
        med = ((mm["bid_band_0_2"] - mm["c_bid"]).abs() / mm["c_bid"]).median()
        if best is None or med < best[1]:
            best = (off, med)
    # (4) signed ratio
    rb = (m["c_bid"] / m["bid_band_0_2"]).median()
    ra = (m["c_ask"] / m["ask_band_0_2"]).median()
    print(f"{s:<13}{len(m):>7} | {self_c:>8.2%} {self_a:>8.2%} | "
          f"{b[0]:>6.2%} {b[1]:>6.2%} {b[2]:>6.2%} {b[3]:>6.2%} | {best[0]:>+4d} ({best[1]:.2%}) | {rb:.3f} {ra:.3f}")
