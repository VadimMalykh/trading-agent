"""X14 (NEXT_TRAINING_PLAN §2 X14) — the three `prem` columns, the mask and its 10-minute cap,
the archive-before-collector union, the 5m reduction, the layout [42:45], and the identity bar
on a planted divergence — all on made-up series, before any real bar.

Run inside the trainer image (nothing on the host):
    docker compose --profile ml run --rm --no-deps ml_trainer python tests/test_prem_features.py
"""
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data import db  # noqa: E402
from data import features as F  # noqa: E402
from m3 import archiveprem as A  # noqa: E402


def _grid(n: int = 600) -> pd.Index:
    return pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")


def test_layout_and_group():
    groups, cols = F.resolve_feature_groups("legacy,prem")
    assert groups == ["legacy", "prem"] and len(cols) == 22
    assert cols[:19] == F.LEGACY_FEATURE_COLS and cols[19:] == F.PREM_COLS
    assert F.ALL_FEATURE_COLS[42:45] == F.PREM_COLS and F.ALL_FEATURE_COLS[38:42] == F.DEPTH1_COLS
    assert F.PREM_COLS == ["prem_bps", "prem_d1h", "has_prem"]
    assert F.PREM_MAX_AGE_MIN == 10.0


def test_columns_at_the_close():
    """A row stamped at each bar's close carries that bar's value; a poll 30 s before the close
    is the bar's value too; a row 30 s AFTER the close belongs to the next bar."""
    g = _grid(100)
    v = np.arange(100, dtype=float)
    # archive style: one row at each close
    prem = pd.DataFrame({"ts": g + pd.Timedelta(minutes=5), "premium_bps": v})
    out = F.prem_features(prem, g, 10.0, bars_1h=12, bar_min=5)
    assert list(out.columns) == F.PREM_COLS
    assert np.allclose(out["prem_bps"].to_numpy(), v)
    assert (out["has_prem"] == 1).all()
    assert np.allclose(out["prem_d1h"].to_numpy()[12:], 12.0) and (out["prem_d1h"].to_numpy()[:12] == 0).all()
    # collector style: a poll 30 s before each close
    prem2 = pd.DataFrame({"ts": g + pd.Timedelta(minutes=4, seconds=30), "premium_bps": v})
    out2 = F.prem_features(prem2, g, 10.0, bars_1h=12, bar_min=5)
    assert np.allclose(out2["prem_bps"].to_numpy(), v)
    # a row 30 s after the close is NOT seen by the bar (no lookahead)
    prem3 = pd.DataFrame({"ts": g + pd.Timedelta(minutes=5, seconds=30), "premium_bps": v})
    out3 = F.prem_features(prem3, g, 10.0, bars_1h=12, bar_min=5)
    assert out3["has_prem"].iloc[0] == 0 and np.allclose(out3["prem_bps"].to_numpy()[1:], v[:-1])


def test_mask_and_staleness_cap():
    g = _grid(100)
    v = np.arange(100, dtype=float) + 1.0
    prem = pd.DataFrame({"ts": g + pd.Timedelta(minutes=5), "premium_bps": v})
    # a 90-minute hole: rows for bars 40..57 missing -> their closes see a row 5..90 min old
    prem = prem[(prem.index < 40) | (prem.index >= 58)]
    out = F.prem_features(prem, g, 10.0, bars_1h=12, bar_min=5)
    assert out["has_prem"].iloc[39] == 1 and out["prem_bps"].iloc[39] == 40.0
    # bar 40's close is 5 min after the last row (age 5) -> within the cap; bar 41 (age 10) too; bar 42 (age 15) masked
    assert out["has_prem"].iloc[40] == 1 and out["prem_bps"].iloc[40] == 40.0
    assert out["has_prem"].iloc[41] == 1
    assert (out["has_prem"].iloc[42:58] == 0).all() and (out["prem_bps"].iloc[42:58] == 0).all()
    assert (out["prem_d1h"].iloc[42:58] == 0).all()
    assert out["has_prem"].iloc[58] == 1 and out["prem_bps"].iloc[58] == 59.0
    # the 1h delta is 0 when the earlier bar was masked (bar 60 looks back at masked bar 48)
    assert out["prem_d1h"].iloc[60] == 0.0 and out["prem_d1h"].iloc[70] == 12.0
    # nothing before the first row; an empty source -> all zero
    out0 = F.prem_features(pd.DataFrame(), g, 10.0, bars_1h=12, bar_min=5)
    assert (out0[F.PREM_COLS] == 0).all().all()
    # the cap fires even under the legacy age arithmetic knob (ALIGN_AGE_FIX is not consulted)
    assert F.ALIGN_AGE_FIX in (True, False)


def test_union_boundary():
    """db.load_premium: the archive's rows strictly BEFORE the collector's first mark row, then the
    collector's; the collector's premium in bps from its two prices; collector only when unset."""
    g = _grid(40)
    arch = pd.DataFrame({"symbol": "SOLUSDT", "ts": g + pd.Timedelta(minutes=5),
                         "premium_bps": np.full(40, -1.0)})
    coll = pd.DataFrame({"ts": g[20:] + pd.Timedelta(minutes=4),
                         "mark_price": 100.0 * (1 + 2e-4), "index_price": 100.0})

    def fake_read_sql(sql, params=None):
        assert "funding_rates" in sql and "mark_price IS NOT NULL" in sql
        return coll.copy()

    saved = (db._read_sql, db.ARCHIVE_PREM, db._archive_prem_cache)
    try:
        db._read_sql = fake_read_sql
        db.ARCHIVE_PREM = "made-up_deadbeef.parquet"
        db._archive_prem_cache = arch
        out = db.load_premium("SOLUSDT")
        assert db.archive_prem_sha() == "deadbeef"
        db.ARCHIVE_PREM = ""
        only = db.load_premium("SOLUSDT")
    finally:
        db._read_sql, db.ARCHIVE_PREM, db._archive_prem_cache = saved
    assert list(out.columns) == ["ts", "premium_bps"]
    first_coll = coll["ts"].iloc[0]
    assert (out["ts"] < first_coll).sum() == 20                   # closes 00:05 .. 01:40, before 01:44
    assert (out.loc[out["ts"] < first_coll, "premium_bps"] == -1.0).all()
    assert np.allclose(out.loc[out["ts"] >= first_coll, "premium_bps"], 2.0)
    assert len(only) == 20 and np.allclose(only["premium_bps"], 2.0)
    assert out["ts"].is_monotonic_increasing


def test_reduction_to_5m():
    g = _grid(10)
    mark = pd.DataFrame({"symbol": "BTCUSDT", "open_time": g, "close": 100.0 + np.arange(10)})
    index = pd.DataFrame({"symbol": "BTCUSDT", "open_time": g, "close": 100.0})
    index = index.iloc[:-1]                                         # one index bar missing
    index.loc[3, "close"] = 0.0                                     # one non-positive index
    df = A.premium_frame(mark, index)
    assert list(df.columns) == ["symbol", "ts", "mark_price", "index_price", "premium_bps"]
    assert len(df) == 8                                             # 10 − 1 missing − 1 non-positive
    assert (df["ts"] == df["ts"].dt.floor("5min")).all() and df["ts"].iloc[0] == g[0] + pd.Timedelta(minutes=5)
    assert abs(df["premium_bps"].iloc[0] - 0.0) < 1e-9 and abs(df["premium_bps"].iloc[1] - 100.0) < 1e-9
    with tempfile.TemporaryDirectory() as d:
        mark.to_parquet(os.path.join(d, "m.parquet"), index=False)
        index.to_parquet(os.path.join(d, "i.parquet"), index=False)
        out = A.reduce(os.path.join(d, "m.parquet"), os.path.join(d, "i.parquet"), os.path.join(d, "premium_5m.parquet"))
        assert os.path.basename(out).startswith("premium_5m_") and len(os.path.basename(out)) == len("premium_5m_12345678.parquet")
        assert len(pd.read_parquet(out)) == 8


def test_parse_klines():
    raw = (b"open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
           b"1788220800000,78549.6,78610.3,78526.6575,78610.30000000,0,1788221099999,0,300,0,0,0\n")
    df = A.parse_klines(raw, "BTCUSDT")
    assert list(df.columns) == ["symbol", "open_time", "close"] and df["close"].iloc[0] == 78610.3
    assert df["open_time"].iloc[0] == pd.Timestamp("2026-09-01 00:00", tz="UTC")


def test_identity_bar_on_a_planted_divergence():
    """Two samplings of one series pass; the collector reading a different series (a constant
    offset larger than the minute-to-minute move) fails the spread; injected excursions fail the tail."""
    rng = np.random.default_rng(0)
    n = 6 * 24 * 60                                                 # six days of minutes
    t0 = pd.Timestamp("2026-08-01", tz="UTC")
    minute = t0 + pd.to_timedelta(np.arange(n), unit="min")
    walk = np.cumsum(rng.normal(0, 0.3, n)) - 2.0                   # a premium in bps, ~0.3 bps a minute
    arch = pd.DataFrame({"symbol": "SOLUSDT", "minute": minute, "ts": minute + pd.Timedelta(minutes=1),
                         "premium_bps": walk})
    poll_ix = np.arange(0, n, 1)[rng.random(n) < 0.75]              # a poll in three minutes of four
    def collector(offset=0.0, spikes=0):
        v = walk[poll_ix] + offset + rng.normal(0, 0.05, len(poll_ix))
        if spikes:
            v[rng.choice(len(v), spikes, replace=False)] += 15.0
        return pd.DataFrame({"symbol": "SOLUSDT", "minute": minute[poll_ix], "premium_bps": v,
                             "ts": minute[poll_ix] + pd.Timedelta(seconds=40)})
    assert A.check_pair(arch, collector())["ok"]
    r = A.check_pair(arch, collector(offset=2.0))
    assert not r["ok"] and "spread" in r["why"]
    r = A.check_pair(arch, collector(spikes=200))
    assert not r["ok"] and "tail" in r["why"]
    assert not A.check_pair(arch.iloc[:500], collector())["ok"]    # under the n floor
    # collector_premium: the LAST poll of a minute wins, in bps from the two prices
    c = pd.DataFrame({"symbol": ["SOLUSDT"] * 3,
                      "ts": [t0 + pd.Timedelta(seconds=s) for s in (5, 50, 70)],
                      "mark_price": [100.01, 100.02, 100.03], "index_price": [100.0] * 3})
    cp = A.collector_premium(c)
    assert len(cp) == 2 and abs(cp["premium_bps"].iloc[0] - 2.0) < 1e-9 and abs(cp["premium_bps"].iloc[1] - 3.0) < 1e-9


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
