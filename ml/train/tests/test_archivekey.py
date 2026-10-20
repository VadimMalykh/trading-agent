"""BOOK_WAVE2_PLAN §K1 — the archive key's construction, on made-up series, before any real bar.

Runs directly: `./scripts/m3.sh tests/test_archivekey.py` (the analysis image has no pytest).
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from m3 import archivekey as A  # noqa: E402
from m3 import bookregime, sidetable  # noqa: E402

NS = 1_000_000_000
BAR = 5 * 60 * NS
T0 = pd.Timestamp("2025-03-01 00:00", tz="UTC").value


def _grid(pair: str, n: int) -> pd.DataFrame:
    return pd.DataFrame({"pair": pair, "ts": T0 + np.arange(n) * BAR})


def test_oi_alignment_equals_sidetable():
    """a_oi_chg on a synthetic OI series equals sidetable.add_open_interest's oi_chg on the
    same grid: asof backward, the 8 h cap, the change on the ALIGNED level, zero where stale."""
    rng = np.random.default_rng(1)
    grid = pd.concat([_grid("AUSDT", 400), _grid("BUSDT", 400)], ignore_index=True)
    rows = []
    for p in ("AUSDT", "BUSDT"):
        # polls at irregular times: some bars see the same reading twice, one gap > 8 h
        t = T0 + np.sort(rng.choice(np.arange(0, 400 * BAR, 60 * NS), 150, replace=False))
        t = t[(t < T0 + 100 * BAR) | (t > T0 + 220 * BAR)]
        rows.append(pd.DataFrame({"pair": p, "ts": t, "open_interest": 1e6 + rng.normal(0, 1e4, len(t)).cumsum()}))
    src = pd.concat(rows, ignore_index=True).sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)
    mine = A.oi_change(grid, src)
    saved = sidetable.load_oi
    try:
        sidetable.load_oi = lambda export_dir=None: src
        theirs = sidetable.add_open_interest(grid)
    finally:
        sidetable.load_oi = saved
    assert np.allclose(mine["a_oi_chg"].to_numpy(), theirs["oi_chg"].to_numpy(), atol=0, rtol=0)
    assert (mine["has_a_oi"].to_numpy() == theirs["has_oi"].to_numpy()).all()
    assert mine["has_a_oi"].sum() < len(mine)            # the gap exercised the cap
    assert (mine["a_oi_chg"] != 0).sum() > 50             # and the change is not trivially zero


def test_composite_equals_hand_computation():
    rng = np.random.default_rng(2)
    n = 60
    tab = pd.concat([_grid(p, n) for p in ("AUSDT", "BUSDT", "CUSDT")], ignore_index=True)
    for c in ("trade_count", "trade_vol", "oi_chg"):
        tab[c] = rng.normal(size=len(tab))
    obs = A.observables(tab)
    # by hand: within-pair percentile rank, mean across pairs per ts, mean of three, negated
    hand = tab[["pair", "ts"]].copy()
    for c in ("trade_count", "trade_vol", "oi_chg"):
        hand[c] = tab.groupby("pair")[c].rank(pct=True).to_numpy()
    mkt = hand.groupby("ts")[["trade_count", "trade_vol", "oi_chg"]].mean()
    comp = -mkt.mean(axis=1)
    got = obs.drop_duplicates("ts").set_index("ts")[A.KEY].reindex(comp.index)
    assert np.allclose(got.to_numpy(), comp.to_numpy())
    # the key is market-wide: the same number on every pair at a timestamp
    assert (obs.groupby("ts")[A.KEY].nunique() == 1).all()
    # four ingredients would be a different key — refused
    bad = tab.copy()
    bad["spread_bps"] = 1.0
    try:
        A.observables(bad)
        raise AssertionError("a table with a spread must be refused")
    except SystemExit:
        pass


def test_causal_rank_uses_only_the_past():
    n = 3000
    tab = pd.concat([_grid(p, n) for p in ("AUSDT", "BUSDT")], ignore_index=True)
    rng = np.random.default_rng(3)
    for c in ("trade_count", "trade_vol", "oi_chg"):
        tab[c] = rng.normal(size=len(tab))
    w = 1000
    a = A.causal_observables(tab, window=w)
    # a change in the FUTURE leaves the past's values untouched
    tab2 = tab.copy()
    tab2.loc[tab2["ts"] > T0 + 2000 * BAR, "trade_count"] += 100.0
    b = A.causal_observables(tab2, window=w)
    past = a["ts"] <= T0 + 2000 * BAR
    assert np.allclose(a.loc[past, A.KEY_CAUSAL].to_numpy(), b.loc[past, A.KEY_CAUSAL].to_numpy(), equal_nan=True)
    assert a[A.KEY_CAUSAL].isna().sum() > 0                  # the warm-up is NaN, not zero
    assert a[A.KEY_CAUSAL].notna().sum() > 2 * (n - w)


def test_parse_klines_header_and_units():
    raw = (b"open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
           b"1727740800000,63309.00,63491.10,63260.10,63315.20,2172.993,1727741099999,137707559.88830,25815,1290.666,81799370.70190,0\n"
           b"1727741100000,63315.30,63383.00,63275.40,63317.00,757.703,1727741399999,47970000.0,9000,400.0,25000000.0,0\n")
    df = A.parse_klines(raw, "BTCUSDT")
    assert list(df.columns) == ["symbol", "ts", "count", "volume"]
    assert df["ts"].iloc[0] == pd.Timestamp("2024-10-01 00:00", tz="UTC")
    assert df["ts"].iloc[1] - df["ts"].iloc[0] == pd.Timedelta(minutes=5)
    assert df["count"].tolist() == [25815, 9000]
    # microsecond stamps are detected by magnitude
    raw_us = raw.replace(b"1727740800000,", b"1727740800000000,").replace(b"1727741100000,", b"1727741100000000,")
    df2 = A.parse_klines(raw_us, "BTCUSDT")
    assert df2["ts"].iloc[0] == df["ts"].iloc[0]
    # a headerless file parses the same
    df3 = A.parse_klines(raw.split(b"\n", 1)[1], "BTCUSDT")
    assert df3["count"].tolist() == [25815, 9000]


def test_rung_and_bookregime_candidates():
    assert A.rung(pd.Series([1 / 3, 2 / 3, 1.0, 4 / 3, 5 / 3])).tolist() == [1, 2, 3, 4, 5]
    assert set(A.INGREDIENTS.values()) < set(bookregime.CANDIDATES)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
