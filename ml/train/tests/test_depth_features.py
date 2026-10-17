"""X8c (NEXT_TRAINING_PLAN §2 X8c) — the four `depth` columns, the masks, the stale rule and the
served-pair gate, on made-up band rows. Runs under pytest in `ml_trainer`."""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data import db  # noqa: E402
from data import features as F  # noqa: E402


def _grid(n: int = 600) -> pd.Index:
    return pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")


def _bands(grid: pd.Index, bid: np.ndarray, ask: np.ndarray, reach: float = 100.0,
           offset_s: int = -30) -> pd.DataFrame:
    """One band row 30 s before each grid bar (fresh), with the given sums and reach."""
    ts = grid + pd.Timedelta(seconds=offset_s)
    return pd.DataFrame({"ts": ts, "bid_band_0_2": bid, "ask_band_0_2": ask,
                         "bid_reach_bps": reach, "ask_reach_bps": reach})


def test_layout_and_group():
    groups, cols = F.resolve_feature_groups("legacy,depth")
    assert groups == ["legacy", "depth"] and len(cols) == 23
    assert cols[:19] == F.LEGACY_FEATURE_COLS and cols[19:] == F.DEPTH_COLS
    assert F.ALL_FEATURE_COLS[34:38] == F.DEPTH_COLS and F.ALL_FEATURE_COLS[-4:] == F.DEPTH1_COLS
    assert "BTCUSDT" not in F.DEPTH_SERVED_PAIRS and "ETHUSDT" not in F.DEPTH_SERVED_PAIRS
    assert len(F.DEPTH_SERVED_PAIRS) == 10


def test_columns_on_a_served_pair():
    g = _grid()
    n = len(g)
    bid = np.full(n, 300.0)
    ask = np.full(n, 100.0)
    bid[300:] = 100.0            # imbalance flips from +0.5 to 0 at bar 300
    out = F.depth_features(_bands(g, bid, ask), g, 5.0, served=True, bars_1h=12, bars_1d=288)
    assert list(out.columns) == F.DEPTH_COLS
    assert (out["has_depth"] == 1).all()
    assert abs(out["depth_imb_0_2"].iloc[10] - 0.5) < 1e-12
    assert abs(out["depth_imb_0_2"].iloc[400]) < 1e-12
    # the 1h delta: 0 inside each regime, −0.5 for the twelve bars after the flip
    assert abs(out["depth_imb_0_2_d1h"].iloc[100]) < 1e-12
    assert abs(out["depth_imb_0_2_d1h"].iloc[305] + 0.5) < 1e-12
    assert abs(out["depth_imb_0_2_d1h"].iloc[320]) < 1e-12
    # relative depth: log(400) − median over the trailing day; 0 until half a day exists, then
    # 0 while flat, and log(200/400) right after the total halves (the median is still 400)
    assert abs(out["depth_rel_0_2"].iloc[100]) < 1e-12
    assert abs(out["depth_rel_0_2"].iloc[250]) < 1e-12
    assert abs(out["depth_rel_0_2"].iloc[301] - np.log(200.0 / 400.0)) < 1e-9


def test_masks():
    g = _grid(100)
    n = len(g)
    bid = np.full(n, 300.0)
    ask = np.full(n, 100.0)
    # a pair that is not served: all zero whatever the data
    out = F.depth_features(_bands(g, bid, ask), g, 5.0, served=False, bars_1h=12, bars_1d=288)
    assert (out[F.DEPTH_COLS] == 0).all().all()
    # reach under the band's width on some rows -> masked there
    b = _bands(g, bid, ask)
    b.loc[10:19, "bid_reach_bps"] = 15.0
    out = F.depth_features(b, g, 5.0, served=True, bars_1h=12, bars_1d=288)
    assert (out["has_depth"].iloc[10:20] == 0).all() and (out["depth_imb_0_2"].iloc[10:20] == 0).all()
    assert out["has_depth"].iloc[9] == 1 and out["has_depth"].iloc[20] == 1
    # the 1h delta is 0 when the earlier bar was masked
    assert out["depth_imb_0_2_d1h"].iloc[25] == 0.0
    # an empty source -> all zero; a non-positive total -> masked
    out = F.depth_features(pd.DataFrame(), g, 5.0, served=True, bars_1h=12, bars_1d=288)
    assert (out[F.DEPTH_COLS] == 0).all().all()
    b = _bands(g, np.zeros(n), np.zeros(n))
    out = F.depth_features(b, g, 5.0, served=True, bars_1h=12, bars_1d=288)
    assert (out["has_depth"] == 0).all()


def test_stale_rule():
    cols = [f"{s}_band_{t}" for t in db.DEPTH_BAND_TAGS for s in ("bid", "ask")]
    rows = pd.DataFrame(np.arange(5 * 12, dtype=float).reshape(5, 12), columns=cols)
    rows.loc[2, [c for c in cols if c.startswith("ask")]] = rows.loc[1, [c for c in cols if c.startswith("ask")]].to_numpy()
    rows.loc[4, [c for c in cols if c.startswith("bid")]] = rows.loc[3, [c for c in cols if c.startswith("bid")]].to_numpy()
    m = db.depth_stale_mask(rows)
    assert m.tolist() == [False, False, True, False, True]
    # a change on one of the six values keeps the row
    rows.loc[2, "ask_band_5"] += 1.0
    assert db.depth_stale_mask(rows).tolist() == [False, False, False, False, True]


def test_archive_reduce_rule_matches():
    from m3 import archivebook as A
    ts = pd.date_range("2026-08-06", periods=40, freq="30s", tz="UTC")
    df = pd.DataFrame({"ts": ts})
    for a in A.BAND_TAGS:
        for side in ("bid", "ask"):
            df[f"d_{side}_{a}"] = np.arange(40, dtype=float) + (1 if side == "ask" else 0)
    # freeze the ask side on rows 10..19 -> rows 11..19 stale
    for a in A.BAND_TAGS:
        df.loc[10:19, f"d_ask_{a}"] = df.loc[10, f"d_ask_{a}"]
    red, st = A.reduce_pair(df)
    assert st["stale"] == 9
    assert "bid_band_0_2" in red.columns and "d_bid_0.2" not in red.columns
    # one row per 5-minute grid point, each the last fresh row at or before it
    assert red["ts"].is_monotonic_increasing and len(red) == st["kept"]
    assert all((t.second in (0, 30)) for t in red["ts"])


def test_archive_reduce_on_fetched_parquets(tmp_path=None):
    """`reduce` over per-pair parquets as `fetch` writes them: each carries a `symbol` column
    (the first real run on 2026-10-15 died inserting a second one), and the output is one
    sha8-named parquet with one row per pair per grid point."""
    import pathlib
    import tempfile
    from m3 import archivebook as A
    tmp_path = pathlib.Path(tmp_path or tempfile.mkdtemp())
    ts = pd.date_range("2026-08-06", periods=40, freq="30s", tz="UTC")
    for sym in ("AAAUSDT", "BBBUSDT"):
        df = pd.DataFrame({"symbol": sym, "ts": ts})
        for a in A.BAND_TAGS:
            for side in ("bid", "ask"):
                df[f"d_{side}_{a}"] = np.arange(40, dtype=float) + (1 if side == "ask" else 0)
        df.to_parquet(tmp_path / f"{sym}.parquet", index=False)
    out = A.reduce(["AAAUSDT", "BBBUSDT"], in_dir=str(tmp_path), out=str(tmp_path / "r.parquet"))
    red = pd.read_parquet(out)
    assert os.path.basename(out).startswith("r_") and len(os.path.basename(out)) == len("r_12345678.parquet")
    assert list(red.columns[:2]) == ["symbol", "ts"] and list(red.columns).count("symbol") == 1
    assert set(red["symbol"]) == {"AAAUSDT", "BBBUSDT"}
    assert not red.duplicated(subset=["symbol", "ts"]).any()


def test_series_identity_bar(tmp_path=None):
    """X8c′ prerequisite 1′: two samplings of one series pass (the archive stamped 15 s late, matched
    at δ*); a scaled source fails the centre; a source with injected excursions fails the tail."""
    import pathlib
    import tempfile
    from m3 import archivebook as A
    tmp_path = pathlib.Path(tmp_path or tempfile.mkdtemp())
    rng = np.random.default_rng(0)
    n = 24 * 3600  # one second grid, one day (2,880 archive rows, the n floor is 2,000)
    t0 = pd.Timestamp("2026-10-12 03:00", tz="UTC")
    # a random walk in log depth, ~2 % a second, both sides
    walk = {side: np.exp(np.cumsum(rng.normal(0, 0.02, n)) + 8.0) for side in ("bid", "ask")}
    sec = t0 + pd.to_timedelta(np.arange(n), unit="s")
    coll_ix = np.arange(0, n, 10)                    # the collector every 10 s, on time
    arch_ix = np.arange(0, n - 15, 30)               # the archive every 30 s, stamped 15 s late
    def collector(scale=1.0):
        g = pd.DataFrame({"symbol": "SOLUSDT", "ts": sec[coll_ix]})
        for side in ("bid", "ask"):
            g[f"{side}_band_0_2"] = walk[side][coll_ix] * scale
            for t in ("1", "2", "3", "4", "5"):
                g[f"{side}_band_{t}"] = walk[side][coll_ix] * scale * 3
            g[f"{side}_reach_bps"] = 100.0
        return g
    def archive(spikes=0):
        a = pd.DataFrame({"symbol": "SOLUSDT", "ts": sec[arch_ix] + pd.Timedelta(seconds=15)})
        for side in ("bid", "ask"):
            v = walk[side][arch_ix].copy()
            if spikes:
                v[rng.choice(len(v), spikes, replace=False)] *= 4.0
            a[f"d_{side}_0.2"] = v
            for t in ("1", "2", "3", "4", "5"):
                a[f"d_{side}_{t}"] = v * 3
        return a
    def run(g, a):
        d = tmp_path / f"case_{rng.integers(1 << 30)}"
        d.mkdir()
        a.to_parquet(d / "SOLUSDT.parquet", index=False)
        g.to_csv(d / "collector.csv", index=False)
        return A.check_series(str(d / "collector.csv"), in_dir=str(d), pairs=["SOLUSDT"])
    assert run(collector(), archive()) == 0
    assert run(collector(scale=1.05), archive()) == 2
    assert run(collector(), archive(spikes=60)) == 2
    # X8c″: the same bar on the ±1 % band (3× the walk on both sides above, spikes included)
    def run1(g, a):
        d = tmp_path / f"case1_{rng.integers(1 << 30)}"
        d.mkdir()
        a.to_parquet(d / "SOLUSDT.parquet", index=False)
        g.to_csv(d / "collector.csv", index=False)
        return A.check_series(str(d / "collector.csv"), in_dir=str(d), pairs=["SOLUSDT"], band="1")
    assert run1(collector(), archive()) == 0
    assert run1(collector(scale=1.05), archive()) == 2
    assert run1(collector(), archive(spikes=60)) == 2


def test_snapshot_without_band_columns_is_archive_only():
    """X8c′'s first launch (20261015T161402Z) died on the pinned 20260913T050118Z snapshot, which
    predates migration 20261012000001: the collector SQL named a column the table does not have.
    On such a snapshot the collector's part is empty and the archive supplies every row."""
    g = _grid(20)
    arch = pd.DataFrame({"symbol": "SOLUSDT", "ts": g,
                         **{c: 1.0 for c in db.DEPTH_COLLECTOR_COLS}})
    calls = []

    def fake_read_sql(sql, params=None):
        calls.append(sql)
        assert "information_schema" in sql, "the collector SQL must not run without the columns"
        return pd.DataFrame()  # no bid_band_0_2 column in this snapshot

    saved = (db._read_sql, db._depth_bands_in_db, db.ARCHIVE_DEPTH, db._archive_depth_cache)
    try:
        db._read_sql = fake_read_sql
        db._depth_bands_in_db = None
        db.ARCHIVE_DEPTH = "made-up.parquet"
        db._archive_depth_cache = arch
        out = db.load_depth_bands("SOLUSDT")
        out2 = db.load_depth_bands("DOGEUSDT")
    finally:
        db._read_sql, db._depth_bands_in_db, db.ARCHIVE_DEPTH, db._archive_depth_cache = saved
    assert len(calls) == 1                      # the schema check once per process, no band SQL
    assert len(out) == 20 and out["ts"].iloc[0] == g[0] and out["ts"].iloc[-1] == g[-1]
    assert (out["bid_reach_bps"] == db.DEPTH_REACH_UNBOUNDED).all()
    assert "symbol" not in out.columns
    assert out2.empty


def test_band1_group_layout_and_columns():
    """X8c″: the `depth1` group — four columns on the ±1 % band, appended after `depth`, seven
    served pairs, a 100-bps reach floor; the ±0.2 % group is untouched."""
    groups, cols = F.resolve_feature_groups("legacy,depth1")
    assert groups == ["legacy", "depth1"] and len(cols) == 23
    assert cols[:19] == F.LEGACY_FEATURE_COLS and cols[19:] == F.DEPTH1_COLS
    assert F.ALL_FEATURE_COLS[34:38] == F.DEPTH_COLS and F.ALL_FEATURE_COLS[38:42] == F.DEPTH1_COLS
    assert F.DEPTH1_SERVED_PAIRS == frozenset(["SOLUSDT", "DOGEUSDT", "WLDUSDT", "ADAUSDT",
                                               "AVAXUSDT", "LINKUSDT", "XRPUSDT"])
    for p in ("BTCUSDT", "ETHUSDT", "ZECUSDT", "HYPEUSDT", "1000PEPEUSDT"):
        assert p not in F.DEPTH1_SERVED_PAIRS
    g = _grid(600)
    n = len(g)
    bid = np.full(n, 300.0)
    ask = np.full(n, 100.0)
    bid[300:] = 100.0
    b = pd.DataFrame({"ts": g + pd.Timedelta(seconds=-30), "bid_band_1": bid, "ask_band_1": ask,
                      "bid_band_0_2": np.nan, "ask_band_0_2": np.nan,      # the archive before 2026-01-15
                      "bid_reach_bps": 200.0, "ask_reach_bps": 200.0})
    out = F.depth_features(b, g, 5.0, served=True, bars_1h=12, bars_1d=288, tag="1")
    assert list(out.columns) == F.DEPTH1_COLS
    assert (out["has_depth_1"] == 1).all()
    assert abs(out["depth_imb_1"].iloc[10] - 0.5) < 1e-12 and abs(out["depth_imb_1"].iloc[400]) < 1e-12
    assert abs(out["depth_imb_1_d1h"].iloc[305] + 0.5) < 1e-12
    assert abs(out["depth_rel_1"].iloc[301] - np.log(200.0 / 400.0)) < 1e-9
    # the ±0.2 % group on the same rows is all zero — the band is NaN (X8c′'s fact)
    out02 = F.depth_features(b, g, 5.0, served=True, bars_1h=12, bars_1d=288)
    assert (out02[F.DEPTH_COLS] == 0).all().all()
    # the reach floor is the band's own: 50 bps reaches ±0.2 % and not ±1 %
    b.loc[10:19, "bid_reach_bps"] = 50.0
    out = F.depth_features(b, g, 5.0, served=True, bars_1h=12, bars_1d=288, tag="1")
    assert (out["has_depth_1"].iloc[10:20] == 0).all() and out["has_depth_1"].iloc[9] == 1
    # not served -> zero
    out = F.depth_features(b, g, 5.0, served=False, bars_1h=12, bars_1d=288, tag="1")
    assert (out[F.DEPTH1_COLS] == 0).all().all()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
