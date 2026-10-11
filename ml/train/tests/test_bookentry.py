"""BOOK_WAVE2_PLAN §E1 — the entry-timing walk on a made-up 1m grid, before any real bar is read.

Runs under pytest in `ml_trainer`, or directly: `./scripts/m3.sh tests/test_bookentry.py`.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from m3 import bookentry as E  # noqa: E402

MIN = E.MIN_NS
T0 = pd.Timestamp("2026-08-01 00:00", tz="UTC").value   # a 5m bar open


def _grid(n_min: int = 600, book_from: int = 0, imb_agree_at: int | None = None,
          micro_agree_at: int | None = None) -> E.Grid:
    """Closes 100 + minute/100 (strictly rising), imbalance −1 everywhere except +1 from minute
    `imb_agree_at` (minutes counted from T0 + 5 min, the decision time), same for micro."""
    ts = T0 + np.arange(n_min) * MIN
    close = 100.0 + np.arange(n_min) / 100.0
    imb = -np.ones(n_min)
    mic = -np.ones(n_min) * 1e-5
    dec = 5                                   # decision minute index (T0 + 5 min)
    if imb_agree_at is not None:
        imb[dec + imb_agree_at:] = 1.0
    if micro_agree_at is not None:
        mic[dec + micro_agree_at:] = 1e-5
    has = np.zeros(n_min, dtype=np.int64)
    has[book_from:] = 1
    return E.Grid(pd.DataFrame({"pair": "XUSDT", "ts": ts, "close": close, "imbalance": imb,
                                "micro_mid": mic, "has_book": has}))


def _inc(side: float = 1.0) -> pd.DataFrame:
    """One incumbent trade decided at the close of the 5m bar opening at T0."""
    e = 100.0 + 4 / 100.0                     # close of the 1m bar opening at T0 + 4 min
    x = 100.0 + 244 / 100.0                   # close of the 1m bar opening at T0 + 244 min
    return pd.DataFrame({"seed": ["s1"], "pair": ["XUSDT"], "entry_ts": [T0],
                         "exit_ts": [T0 + 240 * MIN], "side": [side], "fwd_ret": [x / e - 1.0],
                         "size": [1.0], "signed_ret": [side * (x / e - 1.0)]})


def test_acceptance_and_null():
    g = _grid()
    inc = _inc()
    ok, msg = E.check_acceptance(inc, g)
    assert ok, msg
    null = E.walk_arm(inc, g, "fixed", 0)
    ok, msg = E.check_null(null, inc)
    assert ok, msg
    assert null["exit_ts"].iloc[0] == inc["exit_ts"].iloc[0]


def test_fixed_delay_enters_at_K():
    g = _grid()
    out = E.walk_arm(_inc(), g, "fixed", 15)
    e = 100.0 + (5 + 15 - 1) / 100.0          # close of the bar opening at T0 + 5 + 14 min
    x = 100.0 + (5 + 15 - 1 + 240) / 100.0
    assert abs(out["fwd_ret"].iloc[0] - (x / e - 1.0)) < 1e-12
    assert out["delay_min"].iloc[0] == 15 and not out["at_cap"].iloc[0] and not out["fallback"].iloc[0]
    assert out["exit_ts"].iloc[0] == T0 + (240 + 15) * MIN


def test_book_arm_takes_first_agreeing_minute():
    g = _grid(imb_agree_at=7)
    out = E.walk_arm(_inc(side=1.0), g, "imb", 15)
    assert out["delay_min"].iloc[0] == 7 and not out["at_cap"].iloc[0]
    e = 100.0 + (5 + 7 - 1) / 100.0
    x = 100.0 + (5 + 7 - 1 + 240) / 100.0
    assert abs(out["fwd_ret"].iloc[0] - (x / e - 1.0)) < 1e-12
    # a short is the mirror: the book leans −1 from the start, so minute 1
    out = E.walk_arm(_inc(side=-1.0), g, "imb", 15)
    assert out["delay_min"].iloc[0] == 1
    # never agrees within K -> the cap
    out = E.walk_arm(_inc(side=1.0), _grid(imb_agree_at=30), "imb", 15)
    assert out["delay_min"].iloc[0] == 15 and out["at_cap"].iloc[0]
    # both: imbalance agrees at 7, micro at 9 -> 9
    out = E.walk_arm(_inc(side=1.0), _grid(imb_agree_at=7, micro_agree_at=9), "both", 15)
    assert out["delay_min"].iloc[0] == 9
    out = E.walk_arm(_inc(side=1.0), _grid(imb_agree_at=7, micro_agree_at=9), "micro", 15)
    assert out["delay_min"].iloc[0] == 9


def test_no_book_is_a_fallback_and_a_missing_minute_is_skipped():
    inc = _inc()
    out = E.walk_arm(inc, _grid(book_from=1000), "imb", 15)        # no book anywhere
    assert out["fallback"].iloc[0] and out["fwd_ret"].iloc[0] == inc["fwd_ret"].iloc[0]
    # book appears at minute 5+10: minutes 1..9 cannot agree, minute 10 agrees (imbalance +1 from there)
    g = _grid(book_from=5 + 10, imb_agree_at=10)
    out = E.walk_arm(inc, g, "imb", 15)
    assert out["delay_min"].iloc[0] == 10 and not out["fallback"].iloc[0]


def test_coin_is_seeded_and_bounded():
    g = _grid()
    inc = pd.concat([_inc()] * 50, ignore_index=True)
    a = E.walk_arm(inc, g, "coin", 15, rng=np.random.default_rng(E.COIN_SEED))
    b = E.walk_arm(inc, g, "coin", 15, rng=np.random.default_rng(E.COIN_SEED))
    assert (a["delay_min"] == b["delay_min"]).all()
    assert a["delay_min"].between(1, 15).all() and a["delay_min"].nunique() > 3


def test_overlap_count():
    t = pd.DataFrame({"seed": ["s1", "s1"], "pair": ["XUSDT", "XUSDT"],
                      "entry_ts": [T0, T0 + 240 * MIN], "exit_ts": [T0 + 250 * MIN, T0 + 480 * MIN]})
    assert E.overlaps(t) == 1                 # first exit (T0+250) lands after the next decision (T0+245)
    t["exit_ts"] = [T0 + 245 * MIN, T0 + 480 * MIN]
    assert E.overlaps(t) == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
