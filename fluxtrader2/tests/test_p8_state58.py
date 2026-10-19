"""R58 unit tests for `scripts/r58_state.py` on made-up bars: R45's planted world (a basket trending in planted phases, a per-name flag
that pays only in the up phases) with a planted DVOL series and planted index minutes beside — the planted state S90 CLEARS by the
gate's three lines (family-wise p, the worse half ≤ 0, the better half's lower bound > 0) and the four unrelated states do not; the
known-at check passes on every state; a DVOL series present on under half the span makes DVOL and PREM NOT READABLE and leaves them
out of the family; the world whose flag pays in every phase reads NOTHING CLEARS."""
import importlib.util
import os
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import backtest as bt

from test_p3 import Planted, HOLD
from test_p8_state import PAIRS, COMMON, SD

READ = Path(__file__).resolve().parents[1] / "scripts" / "r58_state.py"
PARAMS = dict(s90_days=5, v_days=2, v_ref_days=10, dvol_ref_days=10, dvol_min_days=4, prem_days=2, prem_symbol=PAIRS[0], index="US100")
EDGE = 90.0        # R45's world at three times its edge and twice its length: the family-wise bar of five members needs a null that decorrelates
PHASES = [(26, 1), (20, -1), (20, 1), (36, -1), (18, 1), (24, -1), (22, 1), (30, -1), (20, 1), (24, -1)]     # 240 days, 9 changes, 10 runs


def _state_world(tmp_path, dependent: bool, seed: int = 3, start="2023-03-20", edge: float = EDGE):
    """R45's planted world (`test_p8_state._state_world`) with the flag's edge a parameter."""
    os.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    rng = np.random.default_rng(seed)
    days = sum(d for d, _ in PHASES)
    t5 = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 288, freq="5min")
    phase = np.concatenate([np.full(d * 288, s, dtype=float) for d, s in PHASES])
    c5, fund, cost = [], [], []
    for i, sym in enumerate(PAIRS):
        sig = rng.choice([-1.0, 0.0, 1.0], len(t5), p=[0.015, 0.97, 0.015])
        pays = sig * ((phase > 0) if dependent else 1.0)
        drift = np.zeros(len(t5))
        for k in range(2, HOLD + 2):
            drift[k:] += pays[:-k] * edge / HOLD
        px = 100 * (i + 1) * np.exp(np.cumsum(rng.normal(0, SD, len(t5)) + COMMON * phase + drift) / 1e4)
        vol = np.where(sig > 0, 20.0, np.where(sig < 0, 5.0, rng.uniform(9, 11, len(t5))))
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - pd.Timedelta("5min"), "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": vol}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0], periods=days * 3, freq="8h"), "rate": 0.0, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=days + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)
    return pd.Timestamp(start, tz="UTC")


def _module():
    spec = importlib.util.spec_from_file_location("r58_state", READ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _plant_dvol_and_index(start: pd.Timestamp, from_frac: float = 0.0):
    """DVOL's open a 3-day square wave (10 / 25 %), present from `from_frac` of the span; US100 minutes on weekdays only."""
    days = sum(d for d, _ in PHASES)
    dd = pd.date_range(start, periods=days, freq="D")
    o = np.where((np.arange(days) // 3) % 2 == 0, 10.0, 25.0)
    dv = pd.DataFrame({"currency": "BTC", "day": dd, "open": o, "high": o + 1, "low": o - 1, "close": o})
    dv = dv.iloc[int(from_frac * days):]
    dv.to_parquet("data/dvol.parquet", index=False)
    ts = pd.date_range(start, periods=days * 1440, freq="1min")
    wk = ts.dayofweek < 5
    px = 100 + np.cumsum(np.random.default_rng(1).normal(0, 0.01, len(ts)))
    ix = pd.DataFrame({"symbol": "US100", "ts": ts[wk], "open": px[wk], "high": px[wk], "low": px[wk], "close": px[wk]})
    ix.to_parquet("data/index_1m.parquet", index=False)
    return dv


def _read(m, start, name, dv=None):
    return m.read({"A": (name, None, None)}, PAIRS, start, pd.Timestamp("2024-01-01", tz="UTC"), min_shift=5, name=f"{name}_state58",
                  known_at_draws=8, dv=dv, **PARAMS)


def test_the_planted_state_clears_by_the_three_lines_and_the_unrelated_states_do_not(tmp_path):
    start = _state_world(tmp_path, dependent=True)
    _plant_dvol_and_index(start)
    bt.run(Planted(), PAIRS, ["F1"], execs=("taker",), draws=1, name="r58_dep")
    m = _module()
    s = _read(m, start, "r58_dep")
    v = s["validity"]
    assert v["pass"] and v["1_pass"] and v["1_record"][0]["reproduced"] == "no record" and v["3_pass"], v
    assert all(v["2_readable"].values()), v["2_readable"]
    assert set(s["members"]) == {f"A/{st}" for st in m.STATES}
    res = {r["state"]: r for r in s["results"]}
    s90 = res["S90"]
    assert s90["verdict"] == "CLEARS" and s90["p_family"] <= 0.05 and s90["D"] > EDGE / 2, s90
    assert s90["worse_net"] <= 0 < s90["better_lo"] and s90["better"] == "+1", s90
    for st in ("V90", "DVOL", "PREM", "SESSION"):
        assert res[st]["verdict"] != "CLEARS", res[st]
    assert s["licensed"]["A"]["state"] == "S90" and s["verdict"].startswith("CLEARS: A at S90")
    ep = {(r["series"], r["scope"]): r for r in v["4_episodes"]}
    assert ep[("S90", "span")]["runs_7d"] == 10 and ep[("SESSION", "span")]["episodes_daily"] >= 20
    out = Path("output/backtest/r58_dep_state58")
    for f in ("state.md", "state.json", "shifts.parquet", "by_state.csv", "halfyears.csv", "episodes.csv"):
        assert (out / f).exists(), f
    sh = pd.read_parquet(out / "shifts.parquet")
    assert len(sh) == s["shifts"] * len(m.STATES) and set(sh["state"]) == set(m.STATES)
    md = (out / "state.md").read_text()
    assert "VERDICT: CLEARS: A at S90" in md and "Validity: PASS" in md


def test_a_state_on_under_half_the_span_leaves_the_family_and_a_flat_world_clears_nothing(tmp_path):
    start = _state_world(tmp_path, dependent=False)
    _plant_dvol_and_index(start, from_frac=0.8)        # F1's trades are the span's last 65 %: the DVOL series then covers a third of them
    bt.run(Planted(), PAIRS, ["F1"], execs=("taker",), draws=1, name="r58_indep")
    m = _module()
    s = _read(m, start, "r58_indep")
    v = s["validity"]
    assert v["pass"] and v["3_pass"]
    assert not v["2_readable"]["A/DVOL"] and not v["2_readable"]["A/PREM"] and v["2_cover"]["A/DVOL"] < 0.5
    assert set(s["members"]) == {"A/S90", "A/V90", "A/SESSION"}
    res = {r["state"]: r for r in s["results"]}
    assert res["DVOL"]["verdict"] == "NOT READABLE" and res["PREM"]["verdict"] == "NOT READABLE"
    assert abs(res["S90"]["D"]) < EDGE / 3 and res["S90"]["verdict"] != "CLEARS", res["S90"]
    assert s["verdict"] == "NOTHING CLEARS"
