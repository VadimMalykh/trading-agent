"""BOOK_WAVE2_PLAN §L1 — the band maths on a made-up ladder, before any real row is read.

Runs under pytest in `ml_trainer`, or directly: `./scripts/m3.sh tests/test_ladderspan.py`.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from m3 import ladderspan as L  # noqa: E402


def _book(n: int = 3) -> pd.DataFrame:
    """Bids one bp apart from 100.0, asks one bp apart from 100.01, qty = level + 1."""
    rows = []
    for r in range(n):
        rec = {"symbol": "XUSDT", "ts": pd.Timestamp("2026-08-06", tz="UTC") + pd.Timedelta(seconds=30 * r),
               "event_time": pd.NaT, "transaction_time": pd.NaT}
        for i in range(100):
            rec[f"b{i}p"] = 100.0 * (1 - 0.0001 * i)
            rec[f"b{i}q"] = i + 1.0
            rec[f"a{i}p"] = 100.01 * (1 + 0.0001 * i)
            rec[f"a{i}q"] = i + 1.0
        rows.append(rec)
    return pd.DataFrame(rows)


def test_band_sum_and_reach():
    a = L.arrays(_book())
    assert abs(a["mid"][0] - 100.005) < 1e-9
    # mid-referenced ±0.2 %: edge 99.80499 -> levels 0..19 -> 1+..+20 = 210, and the ladder reaches
    tot, reach = L.band_sum(a, 0.002, "bid", "mid")
    assert tot[0] == 210 and reach[0]
    # best-referenced: edge 99.8 -> levels 0..20 -> 231 (the boundary level is inside)
    tot, reach = L.band_sum(a, 0.002, "bid", "best")
    assert tot[0] == 231 and reach[0]
    # ±1 %: the whole ladder is inside (5050) but the deepest bid (99.01) is above the edge -> no reach
    tot, reach = L.band_sum(a, 0.01, "bid", "mid")
    assert tot[0] == 5050 and not reach[0]
    tot, reach = L.band_sum(a, 0.002, "ask", "mid")
    assert reach[0]


def test_absent_levels_are_no_liquidity():
    b = _book()
    for i in range(10, 100):
        b[f"b{i}p"] = np.nan
        b[f"b{i}q"] = np.nan
    a = L.arrays(b)
    tot, reach = L.band_sum(a, 0.002, "bid", "mid")
    assert tot[0] == 55 and not reach[0]
    lo, _ = L.deepest(a, 100)
    assert abs(lo[0] - 100.0 * (1 - 0.0009)) < 1e-9


def test_span_table_and_estimates():
    b = _book()
    st = L.span_table(b, L.arrays(b)).iloc[0]
    assert st["L100 reach ±0.2% both"] == "100.0%"
    assert st["L100 reach ±1.0% both"] == "0.0%"
    assert st["L20 reach ±0.2% both"] == "0.0%"
    assert st["levels to 20 bps (est.)"] == 21


def test_identity_verdicts(monkeypatch=None):
    b = _book()
    a = L.arrays(b)
    arch = pd.DataFrame({"symbol": "XUSDT", "ts": b["ts"] + pd.Timedelta(seconds=3),
                         "d_bid_0.2": 210.0, "d_ask_0.2": L.band_sum(a, 0.002, "ask", "mid")[0],
                         "d_bid_1": 5050.0, "d_ask_1": 5050.0})
    old = L.MIN_MATCHED
    L.MIN_MATCHED = 1
    try:
        tab = L.identity(b, a, arch, "ts")
    finally:
        L.MIN_MATCHED = old
    assert (tab[(tab.band == "±0.2%") & (tab.ref == "mid")]["verdict"] == "IDENTICAL").all()
    assert (tab[(tab.band == "±0.2%") & (tab.ref == "best") & (tab.side == "bid")]["verdict"] == "DIFFERENT").all()
    assert (tab[tab.band == "±1.0%"]["verdict"] == "UNREACHABLE").all()
    # a row 20 s away from the only ladder row is outside the 15 s tolerance and is not matched
    b1 = _book(1)
    a1 = L.arrays(b1)
    far = pd.DataFrame({"symbol": "XUSDT", "ts": b1["ts"] + pd.Timedelta(seconds=20),
                        "d_bid_0.2": 210.0, "d_ask_0.2": 210.0, "d_bid_1": 5050.0, "d_ask_1": 5050.0})
    L.MIN_MATCHED = 1
    try:
        tab2 = L.identity(b1, a1, far, "ts")
    finally:
        L.MIN_MATCHED = old
    assert (tab2["matched"] == 0).all()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
