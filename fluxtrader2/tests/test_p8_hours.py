"""R49 unit tests for `scripts/r49_hours.py` on made-up bars: a world whose per-name flag pays only when raised at the settlement hours
(23, 07, 15 UTC) comes back through the read with C_settle clearing and those three cells cleared on the seen half, then CONFIRMED on a
confirmation half of the same cells; the same world with the flag paying at every hour reads NOTHING TO CONFIRM; a seen half that clears
against a confirmation half whose forecast is noise reads NOT CONFIRMED."""
import importlib.util
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import backtest as bt

from test_p3 import Planted, EDGE, HOLD
from test_p8_mech import PAIRS, START

READ = Path(__file__).resolve().parents[1] / "scripts" / "r49_hours.py"
DAYS = 280
SETTLE = (23, 7, 15)


def _module():
    spec = importlib.util.spec_from_file_location("r49_hours", READ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _world(tmp_path, pay_hours, seed: int = 3, base: float = 0.5):
    """Random-walk pairs, no common drift; a per-name flag on every hour whose EDGE is paid in full when raised at `pay_hours` and at `base`
    of it at the other hours (None: in full everywhere). Returns the synthetic forecast cells (the forecast carries the flag at every hour —
    only the label knows the hour)."""
    os.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")
    on_hour = np.asarray(t5.minute == 0)
    pays_hour = on_hour * (1.0 if pay_hours is None else np.where(np.isin(np.asarray(t5.hour), list(pay_hours)), 1.0, base))
    c5, fund, cost, fc = [], [], [], []
    for i, sym in enumerate(PAIRS):
        sig = rng.choice([-1.0, 0.0, 1.0], len(t5), p=[0.2, 0.6, 0.2]) * on_hour
        pays = sig * pays_hour
        drift = np.zeros(len(t5))
        for k in range(2, HOLD + 2):
            drift[k:] += pays[:-k] * EDGE / HOLD
        px = 100 * (i + 1) * np.exp(np.cumsum(rng.normal(0, 5.0, len(t5)) + drift) / 1e4)
        vol = np.where(sig > 0, 20.0, np.where(sig < 0, 5.0, rng.uniform(9, 11, len(t5))))
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - pd.Timedelta("5min"), "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": vol}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0], periods=DAYS * 3, freq="8h"), "rate": 0.0, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
        fc.append(pd.DataFrame({"t": t5[on_hour], "symbol": sym, "group": i % 4, "f_bps": sig[on_hour] * EDGE + rng.normal(0, 3.0, on_hour.sum()),
                                "sigma_h": 5.0 * np.sqrt(HOLD), "f_ref_bps": np.nan}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)
    return pd.concat(fc, ignore_index=True)


def _pre_run(seen: str, pre: str, fc: pd.DataFrame):
    """A confirmation-half run directory: the seen run's meta and the given forecast cells, no fills."""
    d = Path(f"output/backtest/{pre}")
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(f"output/backtest/{seen}/meta.json", d / "meta.json")
    fc.to_parquet(d / "forecast.parquet", index=False)


def _read(m, seen, pre, name, draws=300):
    panel = (PAIRS, pd.Timestamp(START, tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC"))
    return m.read([seen], pre, seen_panel=panel, pre_panel=panel, draws=draws, name=name, record_ic={}, seen_fills=[f"{seen}/fills_taker.parquet"],
                  pre_fills=[], state_daily=None, hold=HOLD, latency=1, min_days={"seen": 200, "pre": 200})


def test_a_planted_time_of_day_clears_on_the_seen_half_and_is_confirmed(tmp_path):
    fc = _world(tmp_path, SETTLE)
    bt.run(Planted(), PAIRS, ["F1"], execs=("taker",), draws=1, name="r49_seen")
    fc.to_parquet("output/backtest/r49_seen/forecast.parquet", index=False)
    _pre_run("r49_seen", "r49_pre", fc)
    m = _module()
    s = _read(m, "r49_seen", "r49_pre", "r49_dep")
    v = s["validity"]
    assert v["pass"] and v["1_record"][0]["reproduced"] == "no record" and v["2_pass"] and v["3_pass"] and v["5_pass"], v
    assert v["2_grid"]["seen"]["days_with_24_hours"] >= v["2_grid"]["seen"]["days"] - 1 >= 200 and v["2_grid"]["seen"]["on_the_hour"]   # the world's last day is partial
    se = s["seen"]
    assert se["settle"]["D"] > 0.1 and se["settle"]["p_two_sided"] <= 0.05, se["settle"]
    assert se["p_family"] <= 0.05 and set(SETTLE) <= set(se["cleared"]), (se["p_family"], se["cleared"])
    ic, z = np.array(se["ic_h"]), np.array(se["z"])
    assert ic[list(SETTLE)].min() > np.delete(ic, list(SETTLE)).max() and (z[list(SETTLE)] > 0).all()
    assert all(z[h] < 0 for h in se["cleared"] if h not in SETTLE)                                 # a cell cleared beside the planted three is the mean's other side
    c = s["confirmation"]
    assert c["settle"]["verdict"] == "CLEARS" and c["family"]["verdict"] == "CLEARS" and c["family"]["members"] == len(se["cleared"])
    assert all(r["verdict"] == "CLEARS" and r["sign"] == 1 for r in c["cells"] if r["hour"] in SETTLE)
    assert all(r["sign"] == -1 for r in c["cells"] if r["hour"] not in SETTLE)
    assert s["confirmed"] and s["verdict"] == "CONFIRMED"
    out = Path("output/backtest/r49_dep")
    for f in ("hours.md", "hours.json", "seen.json", "by_hour.csv", "money_by_hour.csv", "sessions.csv", "by_hour_state.csv", "per_run_by_hour.csv",
              "perms_seen.parquet", "perms_pre.parquet"):
        assert (out / f).exists(), f
    seen_json = json.loads((out / "seen.json").read_text())
    assert seen_json["cleared"] == se["cleared"] and "settle" in seen_json                       # the seen half on disk, written first
    by = pd.read_csv(out / "by_hour.csv")
    assert len(by) == 48 and set(by["half"]) == {"seen", "pre"} and by[by["half"] == "seen"]["cleared_seen"].sum() == len(se["cleared"])
    perms = pd.read_parquet(out / "perms_seen.parquet")
    assert len(perms) == 300 and {"D_0", "D_23", "settle", "fam"} <= set(perms.columns)
    money = pd.read_csv(out / "money_by_hour.csv")
    assert len(money[money["half"] == "seen"]) == 24 and money[money["half"] == "seen"]["trades"].sum() > 100
    assert "hedged_net" in s["money"]["seen"] and s["money"]["pre"] == {}
    md = (out / "hours.md").read_text()
    assert "Validity: PASS" in md and "CONFIRMED" in md and "C_settle" in md and "NOTHING TO CONFIRM" not in md


def test_a_world_paying_at_every_hour_reads_nothing_to_confirm(tmp_path):
    fc = _world(tmp_path, None)
    bt.run(Planted(), PAIRS, ["F1"], execs=("taker",), draws=1, name="r49_seen")
    fc.to_parquet("output/backtest/r49_seen/forecast.parquet", index=False)
    _pre_run("r49_seen", "r49_pre", fc)
    m = _module()
    s = _read(m, "r49_seen", "r49_pre", "r49_indep")
    se = s["seen"]
    assert se["ic_all"] > 0.3                                                                      # the flag's forecast is real at every hour
    assert se["settle"]["p_two_sided"] > 0.05 and abs(se["settle"]["D"]) < se["settle"]["mde"], se["settle"]
    assert se["p_family"] > 0.05 and se["cleared"] == []
    assert s["verdict"] == "NOTHING TO CONFIRM" and not s["confirmed"]
    assert s["confirmation"]["family"]["verdict"] == "NONE CLEARED ON THE SEEN HALF" and s["confirmation"]["settle"]["verdict"] != "CLEARS"


def test_a_seen_clear_against_a_noise_confirmation_half_is_not_confirmed(tmp_path):
    fc = _world(tmp_path, SETTLE)
    bt.run(Planted(), PAIRS, ["F1"], execs=("taker",), draws=1, name="r49_seen")
    fc.to_parquet("output/backtest/r49_seen/forecast.parquet", index=False)
    noise = fc.copy()
    noise["f_bps"] = np.random.default_rng(7).normal(0, 3.0, len(noise))
    _pre_run("r49_seen", "r49_pre", noise)
    m = _module()
    s = _read(m, "r49_seen", "r49_pre", "r49_noise")
    assert s["seen"]["p_family"] <= 0.05 and set(SETTLE) <= set(s["seen"]["cleared"])
    c = s["confirmation"]
    assert c["settle"]["verdict"] != "CLEARS" and c["family"]["verdict"] == "NOT CONFIRMED" and c["family"]["p"] > 0.05
    assert s["verdict"] == "NOT CONFIRMED" and not s["confirmed"]
    assert abs(s["pre"]["ic_all"]) < 0.05
