"""R59 unit tests: `rules.TrendFallV90` — its V90 is R58's series exactly (the same three lines on the same panel); its decisions are R8's
at the bars in its state and nothing else, and the two states together are R8 wherever V90 is defined; the read script's gate on
planted numbers; the calm half priced through the script equals the harness's own pricing of the same decisions."""
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt, ceiling, folds, rules

from test_p8_state58 import PAIRS

DAYS, BLOCK = 240, 20          # the vol regime: 20-day blocks at a 5m sd of 4 and 12 bps in turn


def _vol_world(tmp_path, seed: int = 5, start="2023-03-20"):
    """Random-walk pairs whose common noise alternates between a calm and a volatile 20-day block: R8's trigger fires in both,
    and V90 (short windows) sorts the blocks."""
    os.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=DAYS * 288, freq="5min")
    sd = np.where((np.arange(DAYS * 288) // (BLOCK * 288)) % 2 == 0, 4.0, 12.0)
    common = rng.normal(0, 1, len(t5)) * sd
    c5, fund, cost = [], [], []
    for i, sym in enumerate(PAIRS):
        px = 100 * (i + 1) * np.exp(np.cumsum(common + rng.normal(0, 2.0, len(t5))) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - pd.Timedelta("5min"), "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0], periods=DAYS * 3, freq="8h"), "rate": 0.0, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)
    return pd.Timestamp(start, tz="UTC")

R58 = Path(__file__).resolve().parents[1] / "scripts" / "r58_state.py"
R59 = Path(__file__).resolve().parents[1] / "scripts" / "r59_read.py"
V = dict(v_days=2, v_ref_days=10)


def _module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_v90_is_r58s_series_exactly_and_the_gate_splits_r8_by_it(tmp_path):
    start = _vol_world(tmp_path)
    end = pd.Timestamp("2024-01-01", tz="UTC")
    P = ceiling.panel(PAIRS, end, start)
    r58 = _module(R58)
    S = r58.states(P, None, None, s90_days=5, prem_symbol=PAIRS[0], **V)
    M = bt.market(PAIRS, end, start)
    v = rules.TrendFallV90.v90(M.close, **V)
    assert v.index.equals(S.index) and np.array_equal(v.to_numpy(), S["V90"].to_numpy())
    assert set(np.unique(v)) >= {1, -1} and (v != 0).mean() > 0.9
    a, b = folds.bounds("F1")
    base = rules.TrendFall(fall=0.5, trend_days=2).decide(M, a, b)
    vol = rules.TrendFallV90(state=-1, fall=0.5, trend_days=2, **V).decide(M, a, b)
    calm = rules.TrendFallV90(state=+1, fall=0.5, trend_days=2, **V).decide(M, a, b)
    assert len(base) > 20 and len(vol) > 0 and len(calm) > 0
    assert (v.reindex(pd.DatetimeIndex(vol["t"])) == -1).all() and (v.reindex(pd.DatetimeIndex(calm["t"])) == 1).all()
    key = lambda d: set(zip(d["t"], d["symbol"]))        # noqa: E731
    defined = base[v.reindex(pd.DatetimeIndex(base["t"])).to_numpy() != 0]
    assert key(vol) | key(calm) == key(defined) and not (key(vol) & key(calm))
    assert rules.STRATEGIES["trendfall4h_v90"] is rules.TrendFallV90 and bt.get_strategy("trendfall4h_v90", {"state": 1}).state == 1


def test_the_gate_on_planted_numbers():
    m = _module(R59)
    p = {"p_shuffle": 0.01, "p_flip": 0.02, "shuffle_draws": 200, "flip_draws": 200}
    row = {"net": 80.0, "net_lo": 20.0, "net_hi": 140.0, "trades": 500, "net_mde": 84.0}
    assert m.verdict(row, {"F3": 90.0, "F4": 70.0}, p)[0] == "CONFIRMED"
    assert m.verdict(row, {"F3": 150.0, "F4": -20.0}, p)[0] == "NOT DETECTABLE"
    assert m.verdict(row, {"F3": 90.0, "F4": 70.0}, {**p, "p_flip": 0.08})[0] == "NOT DETECTABLE"
    assert m.verdict({**row, "net_lo": -5.0}, {"F3": 90.0, "F4": 70.0}, p)[0] == "NOT DETECTABLE"
    assert m.verdict({"net": -60.0, "net_lo": -120.0, "net_hi": -3.0, "trades": 500, "net_mde": 84.0}, {"F3": -50.0, "F4": -70.0}, {**p, "p_flip": 0.9})[0] == "REFUTED"
    nul = pd.DataFrame({"kind": ["shuffle"] * 4 + ["flip"] * 4, "draw": [1, 2, 3, 4] * 2, "exec": "taker", "trades": 1, "net": [1.0, 2.0, 3.0, 4.0, 10.0, -1.0, 0.0, 5.0]})
    q = m.null_p(nul, 2.5)
    assert q["p_shuffle"] == 3 / 5 and q["p_flip"] == 3 / 5 and q["shuffle_draws"] == 4 and m.null_p(nul, 6.0)["p_flip"] == 2 / 5


def test_the_calm_half_through_the_script_equals_the_harness_and_the_report_reads_the_gate(tmp_path, monkeypatch):
    start = _vol_world(tmp_path)
    out = tmp_path / "output" / "backtest"
    monkeypatch.setattr(bt, "OUT", out)
    monkeypatch.setattr(bt, "READS", out / "confirmation_reads.csv")
    # the "gated" run on F1 (an exploration fold: no registration needed in the test) with a small, fully-defined V90
    g = bt.run(rules.TrendFallV90(state=-1, fall=0.5, trend_days=2, **V), PAIRS, ["F1"], execs=("taker", "maker"), draws=3, name="gated")
    m = _module(R59)
    monkeypatch.setattr(m, "OUT", out)
    monkeypatch.setattr(m, "FOLDS", ["F1"])
    monkeypatch.setattr(m, "GATED", "gated")
    res = m.calm(out / "gated", out / "r59_calm", fold_names=["F1"])
    # the same decisions priced by the harness's own run
    h = bt.run(rules.TrendFallV90(state=+1, fall=0.5, trend_days=2, **V), PAIRS, ["F1"], execs=("taker",), draws=1, name="calm_h")
    hr = h["results"]
    a = hr[(hr["exec"] == "taker") & (hr["scope"] == "all")].iloc[0]
    c = res[res["scope"] == "all"].iloc[0]
    assert c["trades"] == a["trades"] and abs(c["net"] - a["net"]) < 1e-9 and abs(c["net_lo"] - a["net_lo"]) < 1e-9
    assert json.loads((out / "r59_calm" / "meta.json").read_text())["role"] == "described"
    j = m.report(out / "gated", out / "r59_calm", out / "r59")
    assert j["verdict"] in ("CONFIRMED", "NOT DETECTABLE", "REFUTED") and j["calm"]["all"]["trades"] == int(c["trades"])
    assert abs(j["gated"]["all"]["net"] - float(g["results"].query("exec == 'taker' and scope == 'all'")["net"].iloc[0])) < 1e-9
    md = (out / "r59" / "r59.md").read_text()
    assert "VERDICT:" in md and "calm half" in md and "By calendar half-year" in md
    assert len(j["gated"]["halfyears"]) >= 1 and all(r["trades"] > 0 for r in j["gated"]["halfyears"])
