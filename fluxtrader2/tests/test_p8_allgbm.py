"""R87 unit tests for `ft2/allgbm.py` on made-up bars: a planted NON-LINEAR lean (the next day follows |x − 0.5| of one extra feature's
rank — the extremes rise, the middle falls) comes back through the held-out boosted trees and is missed by the ridge on the same matrix;
no fit ever trains on the scored name group or on a label that ends inside the scored block; the ranks keep an absent value absent; the
verdict names the four outcomes; a source without a cell voids the read."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import allgbm as ag, backtest as bt, ceiling

NAMES = [f"{c}{c}{c}USDT" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"] + [f"Z{c}{c}USDT" for c in "ABCDEFGHIJKLMN"]          # 40 members
DAYS, START = 400, "2023-02-01"                      # F0's tail → F1 → the first weeks of F2 (both folds scored)
SD, KICK = 5.0, 8.0                                          # bps a bar; the planted kick, bps a bar over the day's last hour (12 bars)


def _world(tmp_path, seed=3):
    """Forty random-walk names. One slow extra feature x per name (a new value every day, known at the day's first bar); in the day's LAST
    hour the name moves +KICK bps a bar if x is in the outer 30 % of [0, 1] and −KICK × 3/7 otherwise (zero on average): a U-shaped
    lean with no linear part, invisible to every trailing return before it lands."""
    os.chdir(tmp_path)
    for d in ("data", "output/logs"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")
    n = len(t5)
    c5, fund, cost_wide, xs = [], [], [], {}
    dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 8, freq="D")
    for i, sym in enumerate(NAMES):
        xd = rng.uniform(0, 1, DAYS + 1)
        x = xd[np.arange(n) // 288]                                               # the day's value, known from the day's first bar
        last_hour = (np.arange(n) % 288) >= 276                                   # the kick lands in the day's LAST hour only: no trailing return sees it coming
        drift = np.where(last_hour, np.where(np.abs(x - 0.5) > 0.35, KICK, -KICK * 3 / 7), 0.0)
        px = 100 * (i + 1) * np.exp(np.cumsum(rng.normal(0, SD, n) + drift) / 1e4)
        xs[sym] = pd.Series(x, index=t5)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - ceiling.BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0].floor("D"), periods=DAYS * 3 + 3, freq="8h"), "rate": 1e-4, "interval_h": 8}))
        cost_wide.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 3.0, f"imp_{bt.NOTIONAL}": 1.0, f"maker_adv_{bt.MAKER_H}": np.nan, f"maker_fill_{bt.MAKER_H}": np.nan}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.DataFrame({"symbol": "XXXUSDT", "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}).to_parquet("data/cost_daily.parquet", index=False)
    pd.concat(cost_wide).to_parquet("data/cost_daily_wide.parquet", index=False)
    blocks = pd.date_range(pd.Timestamp("2023-05-03", tz="UTC"), t5[-1], freq="30D")
    pd.DataFrame([{"block": b, "symbol": s, "liq_musd": 10.0 + i, "vol_pct": 5.0, "play": 1.0, "age_days": 400 + i} for b in blocks for i, s in enumerate(NAMES)]).to_csv("members.csv", index=False)
    X = pd.DataFrame(xs)

    def src_x(M, grid, names):
        sparse = X.reindex(index=grid, columns=names).copy()
        sparse.iloc[:, ::3] = np.nan                                              # a thin source: a third of the names have no value
        return {"x_u": X.reindex(index=grid, columns=names), "x_sparse": sparse}
    return "members.csv", {"candles": ag.src_candles, "extra": src_x}


def test_the_ranks_keep_an_absent_value_absent_and_the_verdict_names_the_four_outcomes():
    X = np.array([[1.0, 5.0, np.nan, 3.0, 2.0, 9.0], [1.0, np.nan, np.nan, np.nan, 2.0, 3.0]])
    cell = np.ones_like(X, dtype=bool)
    cell[0, 5] = False
    r = ag.rank_rows(X, cell, min_n=4)
    assert np.isnan(r[0, 2]) and np.isnan(r[0, 5]) and np.allclose(r[0, [0, 4, 3, 1]], [0.125, 0.375, 0.625, 0.875]) and np.isnan(r[1]).all()       # three present < 4
    z = ag.centre(np.array([[1.0, 2.0, 3.0, np.nan, 6.0, 0.0]]), np.array([[True, True, True, True, True, False]]), min_n=4)
    assert np.allclose(z[0, [0, 1, 2, 4]], [-2.0, -1.0, 0.0, 3.0]) and np.isnan(z[0, 3]) and np.isnan(z[0, 5])
    assert ag.verdict(0.03, 0.005, 6.0, True) == "CLEARS" and ag.verdict(0.012, 0.004, 3.0, True) == "REAL UNDER THE TAKER BAR"
    assert ag.verdict(0.012, 0.004, 3.0, False) == "NOT DETECTABLE" and ag.verdict(0.03, 0.02, 1.5, True) == "NOT DETECTABLE"
    assert ag.verdict(-0.006, 0.005, -1.2, False) == "CLOSED" and ag.verdict(float("nan"), 0.1, 0.0, True) == "NOT DETECTABLE"
    assert ag.PARAMS["n_estimators"] == 300 and ag.PARAMS["random_state"] == 87 and (ag.BAR_TAKER, ag.BAR_MAKER, ag.T_BAR) == (0.0214, 0.0059, 2.0)


def test_no_fit_trains_on_the_scored_group_or_on_a_label_that_ends_inside_the_block():
    grid = pd.date_range("2023-05-03", periods=24 * 100, freq="h", tz="UTC")
    starts = pd.date_range("2023-05-03", periods=4, freq="30D", tz="UTC")
    block = np.searchsorted(starts.asi8, grid.asi8, side="right") - 1
    t_end = grid + pd.Timedelta(minutes=5 * 289)
    grp = np.arange(8) % ag.GROUPS
    ok = np.ones((len(grid), 8), dtype=bool)
    plan = list(ag.fits(block, t_end.asi8, starts.asi8, grp, ok, ok))
    assert len(plan) == 3 * ag.GROUPS and {b for b, *_ in plan} == {1, 2, 3}
    for b, g, tr, te in plan:
        assert not tr[:, grp == g].any() and not te[:, grp != g].any() and te[block == b][:, grp == g].all() and not te[block != b].any()
        rows = tr.any(1)
        assert (t_end[rows] < starts[b]).all() and tr[t_end < starts[b]][:, grp != g].all()                 # every earlier bar of the other groups, none later
        assert grid[rows].max() == starts[b] - pd.Timedelta(minutes=5 * 289) - pd.Timedelta(hours=1) + pd.Timedelta(minutes=55) or (starts[b] - grid[rows].max()) > pd.Timedelta(hours=24)


def test_a_planted_u_shaped_lean_is_found_held_out_by_the_trees_and_missed_by_the_ridge(tmp_path, monkeypatch):
    members, sources = _world(tmp_path)
    monkeypatch.setitem(ag.PARAMS, "min_child_samples", 200)                      # the made-up world is a tenth of the real one
    md = ag.run("t87", members=members, jobs=2, sources=sources)
    v = json.loads(Path("output/allgbm/t87/validity.json").read_text())
    assert v["status"] == "PASS" and v["registration"] == "R87" and v["features"] == 16 and v["names"] == 40 and v["groups"] == [10, 10, 10, 10]
    assert v["train_cells_of_the_scored_group"] == 0 and v["train_cells_with_label_ending_in_or_after_the_block"] == 0 and v["max_abs_d_causal"] == 0.0
    assert v["sources_without_a_cell"] == [] and v["fits"] >= 4 * ag.GROUPS and v["verdict"] == "CLEARS"
    tab = pd.read_csv("output/allgbm/t87/models.csv").set_index("model")
    g, r = tab.loc["gbm (the gate)"], tab.loc["ridge, the same matrix"]
    assert g["ic"] > ag.BAR_TAKER and g["t"] > 4 and bool(g["folds_positive"]) and g["tenths_bps_a_leg"] > 0, dict(g)
    assert abs(r["ic"]) < g["ic"] / 3 and r["verdict"] == "described", dict(r)                              # a U has no linear part
    assert tab.loc["gbm, candles only", "ic"] < g["ic"] / 3 and tab.loc["gbm, without the candles", "ic"] > g["ic"] / 2
    imp = pd.read_csv("output/allgbm/t87/importance.csv").set_index("feature")
    assert imp["gain_share"].idxmax() in ("x_u", "x_sparse") and imp.loc[["x_u", "x_sparse"], "gain_share"].sum() > 0.5
    cov = pd.read_csv("output/allgbm/t87/cover.csv").set_index("feature")
    assert 0.6 < cov.loc["x_sparse", "cover"] < 0.7 and cov.loc["x_u", "cover"] > 0.99
    fc = pd.read_parquet("output/allgbm/t87/forecast.parquet")
    assert fc["t"].min() >= pd.Timestamp("2023-06-02", tz="UTC") and "## The gate — **CLEARS**" in md                    # the first block has no model

    def src_empty(M, grid, names):
        return {"nothing": pd.DataFrame(np.nan, index=grid, columns=names)}
    with pytest.raises(SystemExit):
        ag.run("t87_void", members=members, jobs=1, sources={**sources, "missing": src_empty})
    assert json.loads(Path("output/allgbm/t87_void/validity.json").read_text())["sources_without_a_cell"] == ["missing"]
    assert "VOID" in Path("output/allgbm/t87_void/read.md").read_text()
