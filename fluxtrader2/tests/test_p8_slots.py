"""R46 unit tests for `scripts/r46_slots.py` on test_p3's made-up bars: slot 1 reproduces the run's saved taker fills exactly; a planted
drift that starts right after the execution bar is lost bar by bar as the entry slides down the hour (slot k earns EDGE × (HOLD − k + 1) /
HOLD gross), so the curve falls, the verdict is "nothing to write", and both described cuts are written."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import backtest as bt

from test_p3 import PAIRS, Planted, EDGE, HOLD, _synth

READ = Path(__file__).resolve().parents[1] / "scripts" / "r46_slots.py"


def _module():
    spec = importlib.util.spec_from_file_location("r46_slots", READ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_slot_one_is_the_run_and_a_later_entry_loses_the_planted_drift_bar_by_bar(tmp_path):
    _synth(tmp_path, days=80)
    bt.run(Planted(), PAIRS, ["F1"], execs=("taker",), draws=1, name="r46_test")
    m = _module()
    s = m.read("r46_test", slots=HOLD, name="r46_test_slots")
    v = s["validity"]
    assert v["pass"] and v["1_pass"] and v["1_matched"] == v["1_saved_trades"] and v["1_same_times"] and max(v["1_max_abs_diff"].values()) <= 1e-6
    sl = pd.read_csv("output/backtest/r46_test_slots/slots.csv").set_index("slot")
    assert sl.loc[1, "d_gross_bps"] == 0.0 and sl.loc[1, "trades"] == v["1_saved_trades"]
    for k in range(2, HOLD + 1):
        want = -EDGE * (k - 1) / HOLD
        got, se = sl.loc[k, "d_gross_bps"], sl.loc[k, "d_gross_bps_se"]
        assert abs(got - want) <= max(3 * se, 2.0), (k, got, want, se)
    assert sl.loc[HOLD, "d_gross_bps"] < sl.loc[2, "d_gross_bps"] < 0
    assert not s["worth"] and s["verdict"].startswith("NOTHING TO WRITE") and s["best_slot"]["slot"] == 2
    cuts = pd.read_csv("output/backtest/r46_test_slots/cuts.csv")
    assert set(cuts["cut"]) == {"reversal", "settlement"} and {"with", "against"} <= set(cuts["group"]) and {"before", "at/after"} <= set(cuts["group"])
    assert s["settlement_hours"] > 0 and (cuts[cuts["cut"] == "reversal"]["trades"].sum() <= v["1_saved_trades"] * HOLD)
    md = Path("output/backtest/r46_test_slots/slots.md").read_text()
    assert "Validity: PASS" in md and "NOTHING TO WRITE" in md and "Cut (a)" in md and "Cut (b)" in md
