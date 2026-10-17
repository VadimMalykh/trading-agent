"""R48 unit tests for `scripts/r48_pre.py` on test_p8_mech's made-up world: a run on irregular planted phases whose flag pays only in the up
phases comes back CONFIRMED (both primary rows clear with their signs, the validity lines hold, the described tables are written); the same
world with the flag paying in every phase comes back NOT CONFIRMED with nothing clearing."""
import importlib.util
from pathlib import Path

import pandas as pd

from ft2 import backtest as bt

from test_p3 import Planted, EDGE, HOLD
from test_p8_mech import _world, PAIRS, START

READ = Path(__file__).resolve().parents[1] / "scripts" / "r48_pre.py"


def _module():
    spec = importlib.util.spec_from_file_location("r48_pre", READ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(tmp_path, dependent, name):
    fc = _world(tmp_path, dependent)
    bt.run(Planted(), PAIRS, ["F1"], execs=("taker", "maker"), draws=3, name=name)
    fc.to_parquet(f"output/backtest/{name}/forecast.parquet", index=False)
    m = _module()
    s = m.read(name, days=4, min_shift=4, name=f"{name}_pre", known_at_draws=8, start=pd.Timestamp(START, tz="UTC"),
               end=pd.Timestamp("2024-01-01", tz="UTC"), expect_params=None, expect_folds=["F1"], registration=None, ref_daily=None,
               facts={"hedged": EDGE / 2, "ic": 0.2}, hold=HOLD, latency=1)
    return m, s


def test_a_planted_state_dependence_is_confirmed_and_the_validity_lines_hold(tmp_path):
    m, s = _run(tmp_path, True, "r48_dep")
    v = s["validity"]
    assert v["pass"] and v["1_meta"]["folds_ok"] and v["1_meta"]["params_ok"] and v["2_state"] == "no reference" and v["3_pass"] and v["4_pass"] and v["5_pass"]
    assert v["4_names"]["min_at_a_decision"] == 6 and v["5_counts"]["trades_taker"] > 100 and v["5_counts"]["trades_maker"] > 100 and v["5_counts"]["runs_7d"] >= 8
    res = {r["row"]: r for r in s["results"]}
    assert res["hedged"]["kind"] == "primary" and res["hedged"]["D"] > EDGE / 3 and res["hedged"]["p"] <= 0.05 and res["hedged"]["verdict"] == "CLEARS", res["hedged"]
    assert res["ic"]["kind"] == "primary" and res["ic"]["D"] > 0.2 and res["ic"]["p"] <= 0.05 and res["ic"]["verdict"] == "CLEARS", res["ic"]
    assert res["net"]["kind"] == "described" and res["hedged_maker"]["kind"] == "described" and res["hedged_maker"]["D"] > EDGE / 3
    assert s["family"]["p_family"] <= 0.05 and s["confirmed"] and s["verdict"] == "CONFIRMED ON THE PRE-HISTORY"
    out = Path("output/backtest/r48_dep_pre")
    for f in ("pre.md", "pre.json", "shifts.parquet", "by_year.csv", "by_state.csv", "known_at.csv"):
        assert (out / f).exists(), f
    sh = pd.read_parquet(out / "shifts.parquet")
    assert len(sh) == s["shifts"] >= 200 and {"hedged", "ic", "net", "hedged_maker"} <= set(sh.columns)
    by = pd.read_csv(out / "by_state.csv")
    assert len(by) == 4 and set(by["state"]) == {1, -1}
    assert s["unconditional"][0]["exec"] == "taker" and s["unconditional"][0]["shuffle_draws"] == 3 and s["unconditional"][0]["trades"] == v["5_counts"]["trades_taker"]
    md = (out / "pre.md").read_text()
    assert "Validity: PASS" in md and "CONFIRMED ON THE PRE-HISTORY" in md and "NOT a gate" in md


def test_a_world_with_nothing_state_dependent_is_not_confirmed(tmp_path):
    m, s = _run(tmp_path, False, "r48_indep")
    res = {r["row"]: r for r in s["results"]}
    for r in ("hedged", "ic"):
        assert res[r]["p"] > 0.05 and res[r]["verdict"] != "CLEARS", res[r]
    assert not s["confirmed"] and s["verdict"] == "NOT CONFIRMED" and s["family"]["p_family"] > 0.05
