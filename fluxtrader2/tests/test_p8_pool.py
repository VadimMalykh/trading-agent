"""R42's pooled row (`ft2/pool.py`): a pool of one run re-prices its saved decisions to the run's own numbers exactly; a pool of two runs
holds the union's trades over the union's scored days, a flip null of the asked size with a p in (0, 1], the halves on a date, and the
files; two holds or two strategies are refused."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt, pool

from test_p3 import PAIRS, Planted, _synth


def test_a_pool_of_one_run_is_the_run_and_a_pool_of_two_is_their_union(tmp_path):
    _synth(tmp_path, days=80)
    r1 = bt.run(Planted(), PAIRS, fold_names=["F1"], execs=("taker",), draws=2, name="p1")
    r2 = bt.run(Planted(), PAIRS[:2], fold_names=["F1"], execs=("taker",), draws=2, name="p2")
    own = r1["results"]
    own = own[(own["exec"] == "taker") & (own["scope"] == "all")].iloc[0]
    pool.pool(["p1"], draws=5, name="pool1")
    s = json.loads(Path("output/backtest/pool1/summary.json").read_text())
    assert s["pooled"]["trades"] == int(own["trades"]) and abs(s["pooled"]["net"] - float(own["net"])) < 1e-9 and abs(s["pooled"]["net_lo"] - float(own["net_lo"])) < 1e-9
    assert s["runs_table"][0]["d_net_vs_run"] == pytest.approx(0.0, abs=1e-9) and s["runs_table"][0]["d_trades_vs_run"] == 0
    assert s["flip"]["draws"] == 5 and 0 < s["flip"]["p"] <= 1 and s["unit"] == "actual" and s["charged"] == "value"

    md = pool.pool(["p1", "p2"], draws=6, name="pool12", split="2023-05-20")
    s = json.loads(Path("output/backtest/pool12/summary.json").read_text())
    n1, n2 = (int(r["results"].query("exec == 'taker' and scope == 'all'")["trades"].iloc[0]) for r in (r1, r2))
    assert s["pooled"]["trades"] == n1 + n2 and s["folds"] == ["F1"] and set(s["pairs"]) == set(PAIRS)
    assert all(abs(r["d_net_vs_run"]) < 1e-9 for r in s["runs_table"])             # net does not depend on the basket; the re-pricing is the harness's
    assert len(s["halves"]) == 4 and {h["half"].split()[0] for h in s["halves"]} == {"before", "from"}
    assert sum(h["trades"] for h in s["halves"] if h["run"] == "p1") == n1
    fl = pd.read_parquet("output/backtest/pool12/flip_null.parquet")
    assert len(fl) == 6 and fl["net"].notna().all() and s["flip"]["null_sd"] >= 0 and 0 < s["flip"]["p"] <= 1
    fu = pd.read_parquet("output/backtest/pool12/pooled_fills.parquet")
    assert len(fu.dropna(subset=["net_bps"])) == n1 + n2
    assert "## Pooled" in md and "flip p" in md and Path("output/backtest/pool12/runs.csv").exists()


def test_two_holds_or_two_strategies_are_refused(tmp_path):
    _synth(tmp_path, days=80)
    bt.run(Planted(), PAIRS, fold_names=["F1"], execs=("taker",), draws=1, name="h12")
    bt.run(Planted(hold=6), PAIRS, fold_names=["F1"], execs=("taker",), draws=1, name="h6")
    with pytest.raises(SystemExit):
        pool.pool(["h12", "h6"], draws=1, name="bad")
    bt.run(bt.get_strategy("coin", {"hold": 12}), PAIRS, fold_names=["F1"], execs=("taker",), draws=1, name="coin12")
    with pytest.raises(SystemExit):
        pool.pool(["h12", "coin12"], draws=1, name="bad2")
