"""BOOK_WAVE2_PLAN §D1 — book dynamics (F6's list) through B1's gate.

The eleven served scalars are levels; this module builds the twelve registered *flow* columns
from the ~8.6 s snapshot stream onto the 5m grid and hands them to `bookaudit.score`
unchanged — direction and percentile map fitted on half 1, every number from half 2,
day-clustered, drift subtracted, DIRECTIONAL / VOL-PROXY measured apart — and evaluates §4.1
exactly as B1 did.

Windows end at the bar's OPEN and use only snapshots at or before it (the B0 convention: the
grid value at `ts` is the last snapshot at or before `ts`, never a later one). A window with
fewer than two snapshots, or a bar whose `has_book` is 0, is masked (`has_dyn_<W>` = 0).

Everything here is fixed by §D1 before any real bar is read.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import bookaudit
from .bookprep import _csv

BOOK_DIR = os.environ.get("M3_EXPORT_DIR", "output/book_era2")
WINDOWS = (1, 5, 15)
MIN_NS = 60 * 1_000_000_000
BPS = 1e4
MIN_SNAPS = 2

FEATURES = ["ofi_1", "ofi_5", "ofi_15", "dflow_5", "dimb_1", "dimb_5", "dimb_15",
            "imb_mean_5", "imb_sd_5", "spread_max_5", "micro_mean_5", "micro_mean_15"]
WINDOW_OF = {f: int(f.rsplit("_", 1)[1]) for f in FEATURES}
MASK_OF = {f: f"has_dyn_{w}" for f, w in WINDOW_OF.items()}


def _window_stats(snap: pd.DataFrame, grid_ts: np.ndarray, w_min: int) -> dict[str, np.ndarray]:
    """Per grid bar: the registered statistics over the snapshots in (ts − W, ts], one pair."""
    t = snap["ts"].to_numpy(np.int64)
    bid_near = snap["bid_depth_near"].to_numpy(np.float64)
    ask_near = snap["ask_depth_near"].to_numpy(np.float64)
    bid_vol = snap["bid_volume"].to_numpy(np.float64)
    ask_vol = snap["ask_volume"].to_numpy(np.float64)
    imb = snap["imbalance"].to_numpy(np.float64)
    mid = snap["mid"].to_numpy(np.float64)
    spread_bps = snap["spread"].to_numpy(np.float64) / mid * BPS
    micro = (snap["microprice"].to_numpy(np.float64) - mid) / mid
    d_near = np.diff(bid_near - ask_near, prepend=np.nan)
    d_vol = np.diff(bid_vol - ask_vol, prepend=np.nan)
    sum_near = bid_near + ask_near
    sum_vol = bid_vol + ask_vol

    hi = np.searchsorted(t, grid_ts, side="right")          # snapshots at or before the open
    lo = np.searchsorted(t, grid_ts - w_min * MIN_NS, side="right")
    n = hi - lo
    out = {k: np.full(grid_ts.size, np.nan) for k in
           ("ofi", "dflow", "dimb", "imb_mean", "imb_sd", "spread_max", "micro_mean")}
    out["n"] = n.astype(np.float64)
    for i in range(grid_ts.size):
        a, b = lo[i], hi[i]
        if b - a < MIN_SNAPS:
            continue
        # the first difference inside the window is between its first two snapshots
        dn = d_near[a + 1:b]
        dv = d_vol[a + 1:b]
        mean_near = sum_near[a:b].mean()
        mean_vol = sum_vol[a:b].mean()
        out["ofi"][i] = dn.sum() / mean_near if mean_near > 0 else np.nan
        out["dflow"][i] = dv.sum() / mean_vol if mean_vol > 0 else np.nan
        out["dimb"][i] = imb[b - 1] - imb[a]
        out["imb_mean"][i] = imb[a:b].mean()
        out["imb_sd"][i] = imb[a:b].std(ddof=1)
        out["spread_max"][i] = spread_bps[a:b].max()
        out["micro_mean"][i] = micro[a:b].mean()
    return out


def add_dynamics(grid: pd.DataFrame, snaps: pd.DataFrame) -> pd.DataFrame:
    """The twelve registered columns and their masks, joined onto B0's 5m grid."""
    out = grid.copy()
    for f in FEATURES:
        out[f] = np.nan
    for w in WINDOWS:
        out[f"has_dyn_{w}"] = 0
    snaps = snaps.sort_values(["symbol", "ts"], kind="mergesort")
    for pair, g in out.groupby("pair", observed=True, sort=False):
        s = snaps[snaps["symbol"] == pair]
        if s.empty:
            continue
        s = s.assign(ts=pd.DatetimeIndex(s["ts"]).asi8)
        idx = g.index.to_numpy()
        gts = g["ts"].to_numpy(np.int64)
        has_book = g["has_book"].to_numpy() == 1
        for w in WINDOWS:
            st = _window_stats(s, gts, w)
            ok = has_book & (st["n"] >= MIN_SNAPS)
            out.loc[idx, f"has_dyn_{w}"] = ok.astype(int)
            for f in FEATURES:
                if WINDOW_OF[f] != w:
                    continue
                key = f.rsplit("_", 1)[0]
                v = st[key]
                v = np.where(ok, v, 0.0)          # bookaudit's convention: masked rows carry 0
                out.loc[idx, f] = v
    return out


def build() -> pd.DataFrame:
    g = bookaudit.build("5m")
    if "has_book" not in g.columns:
        raise SystemExit("book_era_5m.parquet has no has_book column — rebuild B0")
    snaps = _csv("snapshots", ["ts"], export_dir=BOOK_DIR)
    return add_dynamics(g, snaps)


def report() -> int:
    print("=" * 100)
    print("BOOK_WAVE2_PLAN §D1 — BOOK DYNAMICS (F6) THROUGH B1's GATE (§4.1)")
    print("=" * 100)
    df = build()
    t = pd.to_datetime(df["ts"], unit="ns", utc=True)
    print(f"grid: {len(df):,} 5m rows x {df['pair'].nunique()} pairs, {t.min():%Y-%m-%d} .. {t.max():%Y-%m-%d}")
    for w in WINDOWS:
        print(f"  has_dyn_{w}: {df[f'has_dyn_{w}'].mean():.1%} of rows")
    old_f, old_m = bookaudit.FEATURES, bookaudit.MASK_OF
    bookaudit.FEATURES, bookaudit.MASK_OF = FEATURES, MASK_OF
    try:
        tbl, diag, cut = bookaudit.score(df)
    finally:
        bookaudit.FEATURES, bookaudit.MASK_OF = old_f, old_m
    print(f"halves split at {pd.Timestamp(cut, unit='ns', tz='UTC'):%Y-%m-%d %H:%M} UTC")
    cls = bookaudit.classify(diag)
    print("\n--- direction vs magnitude on half 2 (rho_h1 fixed the sign) ---")
    print(cls.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    print("\n--- bps per trade on half 2, top-cov slices; excess = minus the period's own drift ---")
    show = tbl[tbl["cov"].isin([0.02, 0.05])][["feature", "h", "cov", "n", "bps_h2", "bps_h1", "all_bps",
                                                "excess_bps", "excess_lo95", "excess_hi95", "clusters"]]
    print(show.to_string(index=False, float_format=lambda v: f"{v:+.2f}"))
    out_dir = os.path.join(BOOK_DIR)
    tbl.to_csv(os.path.join(out_dir, "d1_bps_table.csv"), index=False)
    cls.to_csv(os.path.join(out_dir, "d1_classification.csv"), index=False)
    g = bookaudit.gate(tbl, diag)
    n_cells = int(((tbl["cov"] == bookaudit.GATE_COVERAGE) & (tbl["h"] <= bookaudit.GATE_MAX_HORIZON)).sum())
    print("\n" + "=" * 100)
    print(f"THE GATE — §4.1 verbatim, the max over {n_cells} cells (12 features x h ≤ 60m at cov 5%)")
    print("=" * 100)
    print(f"  status: {g['status']}; {g['why']}")
    if g.get("shown"):
        print(f"  {g['shown']}")
    print(f"\n  ==> {'PASS — one registration (B3d) becomes admissible after B3c' if g['pass'] else 'FAIL — book dynamics on the scalar snapshots close here'}")
    return 0
