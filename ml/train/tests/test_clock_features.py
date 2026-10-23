"""X19 (NEXT_TRAINING_PLAN §2 X19) — the five `clock` columns: the layout [45:50], the values
at the bar's close, the funding phase, the weekend flag, a tail grid equal to the full grid on
the shared bars (serving = training), bounded and NaN-free — on made-up grids, before any run.

Run inside the trainer image (nothing on the host):
    docker compose --profile ml run --rm --no-deps ml_trainer python tests/test_clock_features.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data import features as F  # noqa: E402


def test_layout_and_group():
    groups, cols = F.resolve_feature_groups("legacy,clock")
    assert groups == ["legacy", "clock"] and len(cols) == 24
    assert cols[:19] == F.LEGACY_FEATURE_COLS and cols[19:] == F.CLOCK_COLS
    assert F.CLOCK_COLS == ["tod_sin", "tod_cos", "fund_sin", "fund_cos", "is_weekend"]
    # append-only: every earlier group keeps its slots
    assert F.ALL_FEATURE_COLS[42:45] == F.PREM_COLS and F.ALL_FEATURE_COLS[38:42] == F.DEPTH1_COLS
    assert F.ALL_FEATURE_COLS[45:50] == F.CLOCK_COLS and len(F.ALL_FEATURE_COLS) == 50
    assert F._GROUP_ORDER[-1] == "clock"


def test_values_at_the_close():
    """An open of 23:55 closes at 00:00: phase 0 on both clocks. 03:55 → 04:00: a sixth of a
    day, half a funding period (fund_cos −1). 07:55 → 08:00: a third of a day, a settlement
    again. 11:55 → 12:00: half a day, half a period."""
    g = pd.DatetimeIndex(["2026-01-07 23:55", "2026-01-08 03:55", "2026-01-08 07:55",
                          "2026-01-08 11:55"], tz="UTC")  # Wed → Thu
    out = F.clock_features(g, 5)
    np.testing.assert_allclose(out["tod_sin"].to_numpy(), [0.0, np.sin(np.pi / 3), np.sin(2 * np.pi / 3), 0.0], atol=1e-12)
    np.testing.assert_allclose(out["tod_cos"].to_numpy(), [1.0, 0.5, -0.5, -1.0], atol=1e-12)
    np.testing.assert_allclose(out["fund_sin"].to_numpy(), [0.0, 0.0, 0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(out["fund_cos"].to_numpy(), [1.0, -1.0, 1.0, -1.0], atol=1e-12)
    assert (out["is_weekend"] == 0).all()
    # the index is the grid's own (open times), not the close
    assert out.index.equals(g)


def test_weekend_flag_at_the_close():
    """Friday 23:55 opens a bar that closes Saturday 00:00 → weekend; Sunday 23:55 closes
    Monday 00:00 → not. Saturday noon → weekend."""
    g = pd.DatetimeIndex(["2026-01-09 23:55", "2026-01-10 12:00", "2026-01-11 23:55",
                          "2026-01-11 23:50"], tz="UTC")  # Fri, Sat, Sun, Sun
    out = F.clock_features(g, 5)
    assert out["is_weekend"].tolist() == [1.0, 1.0, 0.0, 1.0]


def test_naive_and_aware_grids_agree_and_15m_bar():
    g_aware = pd.date_range("2026-03-01", periods=300, freq="5min", tz="UTC")
    g_naive = g_aware.tz_localize(None)
    a = F.clock_features(g_aware, 5)
    b = F.clock_features(g_naive, 5)
    np.testing.assert_allclose(a.to_numpy(), b.to_numpy(), atol=1e-12)
    # a 15m bar's close is open + 15
    c = F.clock_features(pd.DatetimeIndex(["2026-03-01 07:45"], tz="UTC"), 15)
    np.testing.assert_allclose(c[["fund_sin", "fund_cos"]].to_numpy(), [[0.0, 1.0]], atol=1e-12)


def test_tail_equals_full_bounded_no_nan():
    """Serving builds the frame on a tail of the grid; the clock on the shared bars must be
    identical to the full frame's — a pure function of each bar's own stamp."""
    full = pd.date_range("2026-02-01", periods=4000, freq="5min", tz="UTC")
    tail = full[-500:]
    a = F.clock_features(full, 5).iloc[-500:]
    b = F.clock_features(tail, 5)
    np.testing.assert_allclose(a.to_numpy(), b.to_numpy(), atol=0)
    v = F.clock_features(full, 5).to_numpy()
    assert np.isfinite(v).all() and v.min() >= -1.0 and v.max() <= 1.0
    # every column varies (constant nowhere), and both clocks have the expected period
    assert (F.clock_features(full, 5).std() > 0.1).all()
    out = F.clock_features(full, 5)
    np.testing.assert_allclose(out["fund_sin"].to_numpy()[96:], out["fund_sin"].to_numpy()[:-96], atol=1e-12)   # 8 h = 96 bars
    np.testing.assert_allclose(out["tod_sin"].to_numpy()[288:], out["tod_sin"].to_numpy()[:-288], atol=1e-12)   # 24 h = 288 bars


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("ALL GREEN")
