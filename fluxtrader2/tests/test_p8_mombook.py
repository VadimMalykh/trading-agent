"""R44 unit tests for `mombook` and `scripts/r44_read.py` on made-up bars: the planted drift regimes of test_p8_horizon_mom's world
come back through the harness as a book that makes money (whole units, the hourly grid, the block's members only, k the tenth of the
members present — 3 of 30, 2 of 20 in a thinned block), its decisions carry the audit's own signal, and the read script's validity
lines, clipped row and gate pass; without a drift the book pays its costs and the flip null is not beaten."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import audit, backtest as bt
from ft2.horizon import mom_signals

from test_p8_horizon_mom import NAMES, _world

READ = Path(__file__).resolve().parents[1] / "scripts" / "r44_read.py"
THIN_BLOCK, THINNED = "2023-08-01", NAMES[20:]                     # ten names out of one block: n = 20 there, k = 2
DELIST_DAY = "2023-10-15"


def _read_module():
    spec = importlib.util.spec_from_file_location("r44_read", READ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _not_a_member_in_cost_daily():
    """The world's `cost_daily` dummy row is XXXUSDT, a member name: here every member must be on the proxy (validity (3))."""
    c = pd.read_parquet("data/cost_daily.parquet")
    c.assign(symbol="DUMMYUSDT").to_parquet("data/cost_daily.parquet", index=False)


def test_a_planted_momentum_makes_money_as_a_book_and_the_read_passes(tmp_path):
    members = _world(tmp_path)
    _not_a_member_in_cost_daily()
    m = pd.read_csv(members)
    m = m[~((pd.to_datetime(m["block"], utc=True) == pd.Timestamp(THIN_BLOCK, tz="UTC")) & m["symbol"].isin(THINNED))]
    assert len(m) == 30 * 11 - 10, len(m)                                        # eleven blocks of 30 in the world's 2023-05 → 2024-03, one thinned
    m.to_csv(members, index=False)
    s = audit.MomBook(members=members)                             # the registered parameters: hold 8064, window 24192, tenth 0.10, min_cells 20
    assert s.params() == {"hold": 8064, "window": 24192, "tenth": 0.1, "min_cells": 20, "grid": 12, "members": members}
    r0 = bt.run(s, NAMES, ["F1"], draws=1, execs=("taker",), name="r44_test_pre")
    d0 = r0["decisions"]
    day = pd.Timestamp(DELIST_DAY, tz="UTC")
    held = d0[d0["accepted"] & (d0["t"] < day) & (d0["t"] >= day - pd.Timedelta(days=20))]
    delisted = held["symbol"].iloc[0]                                 # a name with a position open on the delisting day
    c = pd.read_parquet("data/candles_5m.parquet")                   # delisted mid-F1: its bars end, the trade open then is unpriced by the harness
    c[~((c["symbol"] == delisted) & (c["open_time"] >= day))].to_parquet("data/candles_5m.parquet", index=False)
    r = bt.run(s, NAMES, ["F1"], draws=20, execs=("taker",), name="r44_test_28d")
    dec, t = r["decisions"], pd.DatetimeIndex(r["decisions"]["t"])
    assert len(dec) > 500 and (t.minute == 0).all() and set(dec["symbol"]) <= set(NAMES)
    thin = (t >= pd.Timestamp(THIN_BLOCK, tz="UTC")) & (t < pd.Timestamp("2023-08-31", tz="UTC"))
    assert not set(dec.loc[thin, "symbol"]) & set(THINNED)
    per_bar = dec.groupby("t")["side"].agg(longs=lambda x: int((x > 0).sum()), shorts=lambda x: int((x < 0).sum()))
    k = pd.Series(np.where((per_bar.index >= pd.Timestamp(THIN_BLOCK, tz="UTC")) & (per_bar.index < pd.Timestamp("2023-08-31", tz="UTC")), 2, 3), index=per_bar.index)
    assert (per_bar["longs"] == k).all() and (per_bar["shorts"] == k).all()
    assert audit.book_check("r44_test_28d", members=members)["status"] == "PASS"
    # the decisions carry the audit's signal, and the i-th highest and i-th lowest are one group
    M = bt.market(NAMES, bt.folds.bounds("F1")[1])
    S = mom_signals(M.close, {"mom": 24192})["mom"]
    assert np.nanmax(np.abs(dec["signal"].to_numpy() - S.to_numpy()[M.index.get_indexer(dec["t"]), M.columns.get_indexer(dec["symbol"])])) <= 1e-9
    g = dec.groupby("group")["side"].agg(["size", "sum"])
    assert (g["size"] == 2).all() and (g["sum"] == 0).all()
    res = r["results"].query("exec == 'taker'").set_index("scope")
    assert res.loc["all", "trades"] >= 50 and res.loc["all", "net"] > 0 and res.loc["all", "hedged_net"] > 0, res.loc["all"]
    assert r["floor"].set_index("exec").loc["taker", "flip_p"] <= 0.05
    # the read script
    rr = _read_module()
    rr.MIN_FOLD_TRADES = 50                                           # the world's 30 names give ≈ 60 trades a fold; the registration's 100 is for 60 members
    v, _ = rr.read("r44_test_28d", M)
    assert v["validity_status"] == "PASS", v["validity"]
    assert v["bars_k_wrong"] == 0 and v["k_min"] == 2 and v["k_max"] == 3 and v["n_min"] == 20 and v["n_max"] == 30 and v["unpriced_beyond_last_bar"] > 0
    assert v["unpriced_other"] == 0 and v["settled"]["delisted_added"] == len(v["delisted"]) >= 1 and {d["symbol"] for d in v["delisted"]} == {delisted}
    assert v["settled"]["mean"] != v["all"]["net"] and np.isfinite(v["settled"]["lo"])
    assert v["max_abs_d_clip_inf"] <= 1e-9 and abs(v["flip"]["p"] - v["flip_p_report"]) < 5e-4 and v["flip"]["draws"] == 20
    assert all(v["gate"].values()) and v["verdict"].startswith("PASS") and v["clipped"]["mean"] > 0 and v["clipped"]["share_clipped"] >= 0.0
    text = rr.md(v, None)
    assert "VERDICT: PASS" in text and "## Validity — read first: **PASS**" in text
    # a run under the registration reads as stage 2
    meta = json.loads(Path("output/backtest/r44_test_28d/meta.json").read_text())
    meta["registration"] = "R44"
    Path("output/backtest/r44_test_28d/meta.json").write_text(json.dumps(meta))
    v2, _ = rr.read("r44_test_28d", M)
    assert v2["verdict"] == "CONFIRMED" and "(vi) net > 0 with the delisted settled" in v2["gate"] and "(vi)" not in str(list(v["gate"]))
    assert "The settled row" in rr.md(v2, None)


def test_without_a_drift_the_book_pays_its_costs(tmp_path):
    members = _world(tmp_path, drift=0.0, seed=11)
    _not_a_member_in_cost_daily()
    s = audit.MomBook(members=members)
    r = bt.run(s, NAMES, ["F1"], draws=20, execs=("taker",), name="r44_test_noise")
    a = r["results"].query("exec == 'taker'").set_index("scope").loc["all"]
    assert abs(a["gross"]) < 3 * a["net_se"] and abs(a["net"] + 15.0) < 3 * a["net_se"], a            # 2 × (5 fee + 1.5 spread + 1 impact)
    assert r["floor"].set_index("exec").loc["taker", "flip_p"] > 0.05
