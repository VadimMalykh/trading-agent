"""X8b — the `flow` feature group, checked without a database.

Run inside the trainer image (nothing on the host):
    docker compose --profile ml run --rm ml_trainer python tests/test_flow_features.py

What it asserts:
  1. FEATURE_GROUPS=legacy,flow resolves to 23 columns whose first 19 are LEGACY_FEATURE_COLS
     (the serving contract), and `flow` never reorders the other groups.
  2. With the knob OFF, `_align_with_age` returns ages 1000x too small on pandas 3 (the
     defect config.ALIGN_AGE_FIX documents); with it ON, minutes.
  3. `flow_features` (knob on) as-of joins the ratio rows onto the candle grid (a bar sees the latest
     bucket at or before its open time, never a later one), log-transforms them, zeroes
     the bars older than the staleness cap and the bars before the first row, and sets
     has_flow accordingly; a non-positive ratio is absent, not a NaN or -inf.
  4. An empty ratio frame gives all-zero columns and has_flow = 0 — a 19-column checkpoint
     served on a pair the collector has no ratios for must not raise.
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from data import features  # noqa: E402


def test_groups():
    names, cols = features.resolve_feature_groups("legacy,flow")
    assert names == ["legacy", "flow"], names
    assert len(cols) == 23, len(cols)
    assert cols[:19] == features.LEGACY_FEATURE_COLS
    assert cols[19:] == features.FLOW_COLS == ["ls_global", "ls_top", "taker_ratio", "has_flow"]
    names2, cols2 = features.resolve_feature_groups("flow,market,legacy")
    assert names2 == ["legacy", "market", "flow"], names2
    assert cols2[:19] == features.LEGACY_FEATURE_COLS and cols2[-4:] == features.FLOW_COLS
    assert features.ALL_FEATURE_COLS[:30] == (features.LEGACY_FEATURE_COLS
                                              + features.OWN_PAIR_MULTISCALE_COLS
                                              + features.MARKET_CONTEXT_COLS)
    assert features.ALL_FEATURE_COLS[30:] == features.FLOW_COLS
    print("PASS groups: legacy,flow -> 23 columns, legacy prefix intact")


def test_legacy_ages_are_not_minutes():
    """Pins the defect config.ALIGN_AGE_FIX exists for: with the knob OFF (the default and
    every banked checkpoint), pandas 3's microsecond indexes make the legacy arithmetic
    return ages 1000x too small, so a 5-minute-old row reads as 0.005 minutes and no
    staleness cap can fire. If pandas ever returns nanosecond indexes again this test
    fails, which is the signal that the legacy branch has silently changed behaviour."""
    features.ALIGN_AGE_FIX = False
    grid = pd.date_range("2026-08-01 00:00", periods=3, freq="5min", tz="UTC")
    src = pd.DataFrame({"v": [1.0]}, index=pd.to_datetime(["2026-08-01 00:00"], utc=True))
    _, age = features._align_with_age(src, grid)
    unit = np.datetime_data(grid.dtype.base if hasattr(grid.dtype, "base") else grid.dtype)[0] \
        if False else str(grid.dtype)
    assert "us" in unit, unit
    assert abs(age[1] - 0.005) < 1e-9 and abs(age[2] - 0.010) < 1e-9, age.tolist()
    assert not features._stale_mask(age, 5.0)[2], "legacy: a 10-minute-old row is not stale"
    features.ALIGN_AGE_FIX = True
    _, age = features._align_with_age(src, grid)
    assert abs(age[1] - 5.0) < 1e-9 and abs(age[2] - 10.0) < 1e-9, age.tolist()
    assert features._stale_mask(age, 5.0)[2], "fixed: a 10-minute-old row is stale at a 5-min cap"
    print("PASS legacy pin: ALIGN_AGE_FIX off -> ages/1000 (caps never fire); on -> minutes")


def test_alignment():
    features.ALIGN_AGE_FIX = True
    grid = pd.date_range("2026-08-01 00:00", periods=12, freq="5min", tz="UTC")
    # ratio buckets at 00:05, 00:10 (missing 00:15), then a gap until 00:45
    ratios = pd.DataFrame({
        "ts": pd.to_datetime(["2026-08-01 00:05", "2026-08-01 00:10", "2026-08-01 00:45"], utc=True),
        "top_long_short_ratio": [2.0, 4.0, 0.5],
        "global_long_short_ratio": [1.0, 0.0, 3.0],      # 0.0 at 00:10 -> absent for that series
        "taker_buy_sell_ratio": [np.e, np.nan, 1.0],    # NaN at 00:10 -> absent
    })
    out = features.flow_features(ratios, grid, max_age_min=20.0)
    assert list(out.columns) == features.FLOW_COLS
    # 00:00 has no row at or before it -> zeros, has_flow 0
    assert out.iloc[0].tolist() == [0.0, 0.0, 0.0, 0.0], out.iloc[0].tolist()
    # 00:05 sees the 00:05 row: log(1)=0, log(2), log(e)=1
    r = out.loc[grid[1]]
    assert abs(r["ls_global"] - 0.0) < 1e-12 and abs(r["ls_top"] - np.log(2.0)) < 1e-12 \
        and abs(r["taker_ratio"] - 1.0) < 1e-12 and r["has_flow"] == 1.0, r.tolist()
    # 00:10 sees the 00:10 row: top log(4); global 0.0 -> absent -> 0; taker NaN -> 0
    r = out.loc[grid[2]]
    assert abs(r["ls_top"] - np.log(4.0)) < 1e-12 and r["ls_global"] == 0.0 \
        and r["taker_ratio"] == 0.0 and r["has_flow"] == 1.0, r.tolist()
    # 00:15..00:30 forward-fill the 00:10 row within the 20-minute cap (age 5..20)
    for i in (3, 4, 5, 6):
        assert out.iloc[i]["has_flow"] == 1.0 and abs(out.iloc[i]["ls_top"] - np.log(4.0)) < 1e-12, i
    # 00:35, 00:40: age 25, 30 > cap -> stale -> zeros
    for i in (7, 8):
        assert out.iloc[i].tolist() == [0.0, 0.0, 0.0, 0.0], (i, out.iloc[i].tolist())
    # 00:45 sees its own row: top log(0.5) < 0, global log 3, taker 0
    r = out.loc[grid[9]]
    assert abs(r["ls_top"] - np.log(0.5)) < 1e-12 and abs(r["ls_global"] - np.log(3.0)) < 1e-12 \
        and r["taker_ratio"] == 0.0 and r["has_flow"] == 1.0, r.tolist()
    # never a lookahead: the 00:40 bar must not see the 00:45 row
    assert out.iloc[8]["has_flow"] == 0.0
    assert np.isfinite(out.to_numpy()).all()
    print("PASS alignment: as-of join, log transform, staleness cap, absent ratios")


def test_empty():
    grid = pd.date_range("2026-08-01", periods=5, freq="5min", tz="UTC")
    out = features.flow_features(pd.DataFrame(), grid, max_age_min=480.0)
    assert (out.to_numpy() == 0.0).all() and list(out.columns) == features.FLOW_COLS
    out = features.flow_features(None, grid, max_age_min=480.0)
    assert (out.to_numpy() == 0.0).all()
    print("PASS empty: no ratios -> zeros, has_flow 0")


def test_archive_flow_shift(tmp_dir="/tmp"):
    """db._archive_flow re-labels the two ACCOUNT ratios +5 min (the archive's bucket-start
    label -> the collector's bucket-end label; verified identical to 0.03 % at p99 on
    2026-09-24) and leaves the taker ratio alone; db.load_open_interest shifts only under
    ARCHIVE_OI_SHIFT_MIN. The constant is duplicated in m3/archiveoi.py (which runs without
    the DB drivers) and the two must stay equal."""
    import importlib
    from data import db
    from m3 import archiveoi
    assert db.ARCHIVE_FLOW_ACCOUNT_SHIFT_MIN == archiveoi.ARCHIVE_FLOW_ACCOUNT_SHIFT_MIN == 5.0
    ts = pd.to_datetime(["2026-08-01 00:00", "2026-08-01 00:05"], utc=True)
    df = pd.DataFrame({"symbol": ["BTCUSDT"] * 2, "ts": ts, "open_interest": [100.0, 101.0],
                       "top_ls_count": [2.0, 2.1], "global_ls": [1.5, 1.6],
                       "taker_ratio": [0.9, 1.1]})
    path = os.path.join(tmp_dir, "archive_shift_test.parquet")
    df.to_parquet(path)
    db.ARCHIVE_OI = path
    db._archive_flow_cache = None
    db._archive_oi_cache = None
    flow = db._archive_flow()
    # account ratios at 00:05 / 00:10; taker at 00:00 / 00:05 -> outer join gives 3 rows
    assert len(flow) == 3, flow
    r = flow.set_index("ts")
    t0, t5, t10 = (pd.Timestamp(x, tz="UTC") for x in ("2026-08-01 00:00", "2026-08-01 00:05", "2026-08-01 00:10"))
    assert np.isnan(r.loc[t0, "top_long_short_ratio"]) and r.loc[t0, "taker_buy_sell_ratio"] == 0.9
    assert r.loc[t5, "top_long_short_ratio"] == 2.0 and r.loc[t5, "global_long_short_ratio"] == 1.5 \
        and r.loc[t5, "taker_buy_sell_ratio"] == 1.1
    assert r.loc[t10, "top_long_short_ratio"] == 2.1 and np.isnan(r.loc[t10, "taker_buy_sell_ratio"])
    # open interest: unshifted by default
    assert db.ARCHIVE_OI_SHIFT_MIN == 0.0
    oi = db._archive_oi()
    assert list(oi["ts"]) == list(ts)
    db.ARCHIVE_OI_SHIFT_MIN = 5.0
    db._archive_oi_cache = None
    oi = db._archive_oi()
    assert list(oi["ts"]) == [t5, t10]
    db.ARCHIVE_OI_SHIFT_MIN = 0.0
    db._archive_oi_cache = None
    db._archive_flow_cache = None
    os.remove(path)
    print("PASS archive shift: account ratios +5 min, taker unshifted, OI only under the knob")


if __name__ == "__main__":
    test_groups()
    test_archive_flow_shift()
    test_legacy_ages_are_not_minutes()
    test_alignment()
    test_empty()
    print("PASS test_flow_features")
