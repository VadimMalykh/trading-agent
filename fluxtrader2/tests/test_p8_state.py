"""R45 unit tests for `scripts/r45_state.py` on made-up bars: a world whose basket trends up and down in planted phases, and whose
per-name flag pays only in the up phases, comes back through the harness and the read as a state dependence that CLEARS (the
episode count the planted one, the known-at check passing, the record check reporting "no record"); the same world with the flag
paying in every phase reads as no dependence."""
import importlib.util
import os
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import backtest as bt

from test_p3 import Planted, EDGE, HOLD

READ = Path(__file__).resolve().parents[1] / "scripts" / "r45_state.py"
PAIRS = [f"{c}USDT" for c in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")]   # six: the basket needs MIN_PAIRS (5) present
PHASES = [(26, 1), (20, -1), (20, 1), (36, -1), (18, 1)]        # days, the basket's direction — 120 days, 4 changes
COMMON = 3.0                                                     # bps a 5m bar of common drift (864 a day): the state is unmistakable
SD = 5.0


def _module():
    spec = importlib.util.spec_from_file_location("r45_state", READ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _state_world(tmp_path, dependent: bool, seed: int = 3, start="2023-03-20"):
    """Random-walk pairs on a common square-wave drift. The volume flag's EDGE (over HOLD bars after the execution bar) is paid in
    the up phases only (`dependent`) or in every phase."""
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
            drift[k:] += pays[:-k] * EDGE / HOLD
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


def _read(m, start, name):
    return m.read({"A": [name]}, PAIRS, start, pd.Timestamp("2024-01-01", tz="UTC"), days=5, s30_days=2, vol_days=2, vol_ref_days=10,
                  min_shift=5, name=f"{name}_state", known_at_draws=8, record={})


def test_a_planted_state_dependence_clears_and_the_validity_lines_hold(tmp_path):
    start = _state_world(tmp_path, dependent=True)
    bt.run(Planted(), PAIRS, ["F1"], execs=("taker",), draws=1, name="r45_dep")
    m = _module()
    s = _read(m, start, "r45_dep")
    v = s["validity"]
    assert v["pass"] and v["1_pass"] and v["1_record"][0]["reproduced"] == "no record" and v["3_pass"] and v["2_cover_S90"]["A"] >= 0.95
    ep = {(r["series"], r["scope"]): r["episodes"] for r in v["5_episodes"]}
    assert ep[("S90", "span")] == 4, ep                                   # the planted phase changes, counted on the 5-day sign
    res = {(r["state"], r["row"]): r for r in s["results"]}
    net, hed = res[("S90", "net")], res[("S90", "hedged")]
    assert net["D"] > EDGE / 2 and net["p"] <= 0.05 and net["verdict"] == "CLEARS", net
    assert hed["D"] > EDGE / 2 and hed["p"] <= 0.05, hed                  # the flag's drift is the name's own, not the market's
    assert s["families"]["S90/net"]["p_family"] <= 0.05 and s["verdict"]["net"] == "CLEARS on the net"
    assert s["shifts"] >= 100 and net["n_up"] > 0 and net["n_dn"] > 0
    out = Path("output/backtest/r45_dep_state")
    assert (out / "state.md").exists() and (out / "shifts.parquet").exists() and (out / "by_state.csv").exists() and (out / "episodes.csv").exists()
    sh = pd.read_parquet(out / "shifts.parquet")
    assert len(sh) == s["shifts"] * 3 and set(sh["state"]) == {"S90", "S30", "V30"}
    md = (out / "state.md").read_text()
    assert "CLEARS on the net" in md and "Validity: PASS" in md


def test_a_flag_that_pays_in_every_phase_reads_as_no_dependence(tmp_path):
    start = _state_world(tmp_path, dependent=False)
    bt.run(Planted(), PAIRS, ["F1"], execs=("taker",), draws=1, name="r45_indep")
    m = _module()
    s = _read(m, start, "r45_indep")
    res = {(r["state"], r["row"]): r for r in s["results"]}
    net = res[("S90", "net")]
    assert abs(net["D"]) < EDGE / 3 and net["p"] > 0.05 and net["verdict"] != "CLEARS", net
    assert s["verdict"]["net"] == "NOT CLEAR on the net"
