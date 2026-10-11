"""BOOK_WAVE2_PLAN §D1 — the window statistics on made-up snapshots, before any real bar is read.

Runs under pytest in `ml_trainer`, or directly: `./scripts/m3.sh tests/test_bookdyn.py`.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from m3 import bookdyn as D  # noqa: E402

T0 = pd.Timestamp("2026-08-01 00:00", tz="UTC")
NS = D.MIN_NS


def _snaps(step_s: int = 10, minutes: int = 30) -> pd.DataFrame:
    """One pair, a snapshot every `step_s` seconds: near-depth imbalance ramps up, imbalance
    rises linearly, spread spikes once at minute 3."""
    n = minutes * 60 // step_s
    ts = T0 + pd.to_timedelta(np.arange(n) * step_s, unit="s")
    k = np.arange(n, dtype=float)
    return pd.DataFrame({"symbol": "XUSDT", "ts": ts, "mid": 100.0,
                         "spread": np.where(k == 18, 0.5, 0.01),          # minute 3 spike (18 x 10 s)
                         "microprice": 100.0 + 0.001 * k,
                         "imbalance": 0.01 * k,
                         "bid_volume": 1000.0 + 10.0 * k, "ask_volume": 1000.0,
                         "bid_depth_near": 100.0 + 1.0 * k, "ask_depth_near": 100.0})


def _grid(minutes=(5, 10, 15)) -> pd.DataFrame:
    return pd.DataFrame({"pair": "XUSDT", "ts": [(T0 + pd.Timedelta(minutes=m)).value for m in minutes],
                         "has_book": 1, "fwd_ret_5": 0.0})


def test_windows_use_snapshots_at_or_before_the_open():
    out = D.add_dynamics(_grid(), _snaps())
    r = out.iloc[0]                                           # bar opening at T0 + 5 min
    # 1-min window (T0+4, T0+5]: snapshots at 250, 260, ..., 300 s -> 6 rows, k = 25..30
    assert r["has_dyn_1"] == 1
    # near OFI: Σ Δ(bid_near − ask_near) over 5 differences = 5, mean sum = 200 + mean(k)=27.5 -> 227.5
    assert abs(r["ofi_1"] - 5.0 / (200.0 + 27.5)) < 1e-12
    assert abs(r["dimb_1"] - (0.30 - 0.25)) < 1e-12
    # 5-min window (T0, T0+5]: k = 1..30 -> dimb = 0.30 − 0.01 = 0.29, imb_mean = 0.155
    assert abs(r["dimb_5"] - 0.29) < 1e-12
    assert abs(r["imb_mean_5"] - 0.155) < 1e-12
    assert abs(r["spread_max_5"] - 0.5 / 100.0 * 1e4) < 1e-9          # the minute-3 spike, 50 bps
    assert abs(r["micro_mean_5"] - np.mean(0.001 * np.arange(1, 31)) / 100.0) < 1e-12
    assert abs(r["dflow_5"] - 10.0 * 29 / (2000.0 + 10.0 * 15.5)) < 1e-12
    # 15-min window at T0+5 has only 5 min of data (k = 1..30): still ≥ 2 snapshots -> unmasked
    assert r["has_dyn_15"] == 1
    # nothing after the open leaks in: the bar at T0+10 must not see the T0+10..15 ramp
    r2 = out.iloc[1]
    assert abs(r2["dimb_5"] - (0.60 - 0.31)) < 1e-12


def test_masks():
    g = _grid()
    g.loc[1, "has_book"] = 0
    out = D.add_dynamics(g, _snaps())
    assert out.iloc[1]["has_dyn_5"] == 0 and out.iloc[1]["ofi_5"] == 0.0
    # a window with a single snapshot is masked
    sparse = _snaps(step_s=120)
    out = D.add_dynamics(_grid(), sparse)
    assert out.iloc[0]["has_dyn_1"] == 0 and out.iloc[0]["has_dyn_5"] == 1


def test_registered_list_is_twelve():
    assert len(D.FEATURES) == 12 and set(D.MASK_OF.values()) == {"has_dyn_1", "has_dyn_5", "has_dyn_15"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
