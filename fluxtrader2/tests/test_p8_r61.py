"""R61 unit tests (`scripts/r61_shape.py`) on the planted world of the R60 tests with the FOUND sign planted (a name bid up on Coinbase
against its month outperforms its peers the next day): the rank means fall from rank 1 to rank 8 and sum to zero, the unit is positive
at every bar and at the daily bar with one observation a day, the triggers keep fewer days as θ rises, the verdict follows the named
bar; validity voids the run on an R60 screen that does not match and passes on one that does."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import cb_ext as cx, ceiling
from test_p8_cb_ext import LIQ, PAIRS, _world

_spec = importlib.util.spec_from_file_location("r61_shape", Path(__file__).resolve().parents[1] / "scripts" / "r61_shape.py")
r61 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r61)


def _r60_outputs(D, F, tmp_path, scale: float = 1.0):
    r60 = tmp_path / "output" / "ceiling_coinbase"
    r60.mkdir(parents=True, exist_ok=True)
    sc, _ = ceiling.ic_screen(D, {cx.DEV: F[cx.DEV]}, set())
    sc.assign(ic=sc["ic"] * scale, t=sc["t"] * scale).to_parquet(r60 / "screen.parquet", index=False)
    pd.DataFrame([{"bet": "relative", "horizon": "1d", "maker_rt": 7.0, "taker_rt": 12.0}]).to_parquet(r60 / "move_vs_cost.parquet", index=False)
    return r60


def test_the_shape_of_a_planted_continuation(tmp_path):
    _world(tmp_path, fast=-0.8)                                                      # the found sign: bid up → outperforms
    D, F, U, G = r61.frame(PAIRS, LIQ, "data/coinbase_1h.parquet")
    L = r61.labels(D, F, LIQ)
    assert L["full"].sum() > 1000 and float(L["rel"][L["full"]].sum(axis=1).abs().max()) < 1e-9
    br = r61.by_rank(L, "dev")
    assert br["mean"].iloc[0] > 20 and br["mean"].iloc[-1] < -20 and br["mean"].is_monotonic_decreasing
    assert abs(br["mean"].sum()) < 1e-6 and br["top_minus_bottom"].iloc[0] > 40 and br["linear_spread"].iloc[0] > 40
    bb = r61.by_bucket(L)
    assert abs(bb["share"].sum() - 1) < 1e-9 and bb["mean"].iloc[4] > 20 > -20 > bb["mean"].iloc[1] and np.isfinite(bb["mean"]).all()
    u = r61.unit_series(L)
    every = r61.unit_stats(u, 7.0, 12.0, daily=False)
    assert every["gross"] > 40 and every["net_maker"] == every["gross"] - 14 and every["net_taker"] == every["gross"] - 24 and every["u"] > 4
    ud = u[(u.index.hour == 0) & (u.index.minute == 5)]
    assert len(ud) == len(np.unique(L["day"]))                                      # one observation a day
    daily = r61.unit_stats(ud, 7.0, 12.0, daily=True)
    assert daily["gross"] > 40 and daily["days"] == ud["spread"].notna().sum() and daily["gross_F1"] > 40 and np.isnan(daily["gross_F2"])
    tr = r61.triggers(ud, 7.0, 12.0)
    top = tr[tr["trigger"] == "top"]
    assert top["days"].is_monotonic_decreasing and (tr["named"].sum() == 2) and top["days"].iloc[0] <= len(ud)
    v, why = r61.decide(daily | {"gross_F2": 1.0}, tr.assign(gross_F2=1.0))
    assert v == "WORTH A RULE" and "unconditional" in why
    v, why = r61.decide(daily, tr)                                                   # F2 absent in this world: no both-folds claim
    assert v == "CLOSED IN MONEY"
    v, _ = r61.decide({"net_maker": 3.0, "u": 0.4, "gross_F1": 1, "gross_F2": 1}, tr.assign(net_maker=20.0, u=1.5, days=150, gross_F1=1.0, gross_F2=1.0))
    assert v == "WORTH A RULE"


def test_run_voids_on_a_mismatching_r60_screen_and_passes_on_a_matching_one(tmp_path):
    _world(tmp_path, fast=-0.8)
    D, F, U, G = r61.frame(PAIRS, LIQ, "data/coinbase_1h.parquet")
    r60 = _r60_outputs(D, F, tmp_path, scale=1.01)
    with pytest.raises(SystemExit) as e:
        r61.run(PAIRS, LIQ, "data/coinbase_1h.parquet", r60=r60)
    assert e.value.code == 2
    v = json.loads(Path("output/r61/r61.json").read_text())
    assert v["status"] == "FAIL" and v["reproduction"]["status"] == "FAIL" and v["known_at"]["status"] == "PASS" and v["centred"]["status"] == "PASS"
    assert not Path("output/r61/unit.parquet").exists() and "VOID" in Path("output/r61_shape.md").read_text()
    _r60_outputs(D, F, tmp_path)
    md = r61.run(PAIRS, LIQ, "data/coinbase_1h.parquet", r60=r60)
    v = json.loads(Path("output/r61/r61.json").read_text())
    assert v["status"] == "PASS" and v["reproduction"]["max_abs_diff"]["ic"] == 0 and v["result"]["verdict"] == "CLOSED IN MONEY"      # no F2 in this world
    assert v["result"]["daily"]["gross"] > 40 and v["result"]["maker_rt"] == 7.0
    assert "## What it decides (AV2)" in md and "## Triggers at the daily bar" in md
    for f_ in ("by_rank", "by_bucket", "unit", "daily", "triggers"):
        assert Path(f"output/r61/{f_}.parquet").exists()
