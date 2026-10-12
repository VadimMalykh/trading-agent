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
    assert F.ALL_FEATURE_COLS[-4:] == F.DEPTH_COLS
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
