"""R47 unit tests for `scripts/r47_mech.py` on made-up bars: a world whose basket trends up and down in planted phases, whose names
disperse more and co-move less in the up phases, and whose per-name flag pays only there, comes back through the read as all three
mechanism rows CLEARING with their registered signs (the family p small, the planted feature flagged in the ceiling family, known-at and
the record lines passing); the same world with nothing state-dependent reads as nothing clearing."""
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import backtest as bt

from test_p3 import Planted, EDGE, HOLD

READ = Path(__file__).resolve().parents[1] / "scripts" / "r47_mech.py"
PAIRS = [f"{c}USDT" for c in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")]
PHASES = [(38, 1), (14, -1), (30, 1), (22, -1), (46, 1), (18, -1), (34, 1), (26, -1), (32, 1), (20, -1)]
# ^ days, the basket's direction — 280 days, 10 phases of IRREGULAR length: a periodic state realigns with itself under the circular
#   shifts (the null then reads any periodic cut as chance, as it should), so the planted world must not be periodic
COMMON = 0.5                                                     # bps a 5m bar of common drift (144 a day against a basket noise of ≈ 30): the state is unmistakable
START = "2023-03-20"


def _module():
    spec = importlib.util.spec_from_file_location("r47_mech", READ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _world(tmp_path, dependent: bool, seed: int = 3):
    """Random-walk pairs on a common square-wave drift. `dependent`: the flag's EDGE is paid in the up phases only, the names' own noise
    is larger there (sd 7 vs 3) and a common shock (sd 10) hits every name in the down phases; otherwise the flag pays everywhere, the noise is
    5 everywhere and there is no common shock. Flags sit on the hour (the forecast grid). Returns the synthetic forecast cells."""
    os.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    rng = np.random.default_rng(seed)
    days = sum(d for d, _ in PHASES)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=days * 288, freq="5min")
    phase = np.concatenate([np.full(d * 288, s, dtype=float) for d, s in PHASES])
    on_hour = np.asarray(t5.minute == 0)
    sd = np.where(phase > 0, 7.0, 3.0) if dependent else np.full(len(t5), 5.0)
    common = rng.normal(0, 10.0, len(t5)) * (phase < 0) if dependent else np.zeros(len(t5))
    c5, fund, cost, fc = [], [], [], []
    for i, sym in enumerate(PAIRS):
        sig = rng.choice([-1.0, 0.0, 1.0], len(t5), p=[0.2, 0.6, 0.2]) * on_hour
        pays = sig * ((phase > 0) if dependent else 1.0)
        drift = np.zeros(len(t5))
        for k in range(2, HOLD + 2):
            drift[k:] += pays[:-k] * EDGE / HOLD
        px = 100 * (i + 1) * np.exp(np.cumsum(rng.normal(0, 1.0, len(t5)) * sd + common + COMMON * phase + drift) / 1e4)
        vol = np.where(sig > 0, 20.0, np.where(sig < 0, 5.0, rng.uniform(9, 11, len(t5))))
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - pd.Timedelta("5min"), "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": vol}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0], periods=days * 3, freq="8h"), "rate": 0.0, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=days + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
        fc.append(pd.DataFrame({"t": t5[on_hour], "symbol": sym, "group": i % 4, "f_bps": sig[on_hour] * EDGE + rng.normal(0, 3.0, on_hour.sum()),
                                "sigma_h": sd[on_hour] * np.sqrt(HOLD), "f_ref_bps": np.nan}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)
    # the ceiling's daily IC file: three features on both bets; `f_state` carries +0.3 in the up phases only
    day = pd.date_range(t5[0].floor("D"), periods=days, freq="D")
    ph_day = np.array([PHASES_SIGN(d) for d in range(days)])
    rows = []
    for bet in ("relative", "directional"):
        for f in ("f_state", "f_noise1", "f_noise2"):
            ic = rng.normal(0, 0.05, days) + (0.3 * (ph_day > 0) if (f == "f_state" and dependent) else 0.0)
            rows.append(pd.DataFrame({"bet": bet, "horizon": "1d", "feature": f, "day": day, "ic": ic}))
    Path("output/ceiling").mkdir(parents=True, exist_ok=True)
    pd.concat(rows).to_parquet("output/ceiling/ic_daily.parquet", index=False)
    return pd.concat(fc, ignore_index=True)


def PHASES_SIGN(d: int) -> int:
    k = 0
    for n, s in PHASES:
        k += n
        if d < k:
            return s
    return PHASES[-1][1]


def _run(tmp_path, dependent, name):
    fc = _world(tmp_path, dependent)
    bt.run(Planted(), PAIRS, ["F1"], execs=("taker",), draws=1, name=name)
    fc.to_parquet(f"output/backtest/{name}/forecast.parquet", index=False)
    m = _module()
    s = m.read([name], PAIRS, pd.Timestamp(START, tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC"), days=4, min_shift=4, name=f"{name}_mech",
               known_at_draws=8, record_ic={}, by_state_ref=None, set_a=[name], ceiling_file=Path("output/ceiling/ic_daily.parquet"),
               rho_days=6, hold=HOLD, latency=1, grid_min=(260, 250))
    return m, s


def test_planted_mechanisms_clear_with_their_signs_and_the_validity_lines_hold(tmp_path):
    m, s = _run(tmp_path, True, "r47_dep")
    v = s["validity"]
    assert v["pass"] and v["1_record"][0]["reproduced"] == "no record" and v["2_reference"] == "no reference" and v["3_pass"] and v["4_pass"] and v["5_pass"]
    assert v["1_record"][0]["cells"] > 10000 and v["1_record"][0]["ic"] > 0.2          # the flag's forecast is real on the whole sample
    res = {r["row"]: r for r in s["results"]}
    assert res["ic"]["D"] > 0.2 and res["ic"]["p"] <= 0.05 and res["ic"]["verdict"] == "CLEARS", res["ic"]
    assert res["disp"]["D"] > 0 and res["disp"]["p"] <= 0.05 and res["disp"]["verdict"] == "CLEARS", res["disp"]
    # the correlation is a slow series and its null on ten episodes is wide (a step series realigns with itself under many shifts — the
    # "unit is the episode" fact of decision Y (ix)): the planted contrast (0.17 against 0.74) is read with its sign, inside a wide null
    assert res["rho"]["D"] < -0.3 and res["rho"]["mean_dn"] - res["rho"]["mean_up"] > 0.4 and res["rho"]["p"] < 0.15, res["rho"]
    assert res["rho"]["verdict"] in ("CLEARS", "NOT DETECTABLE"), res["rho"]
    assert res["zdisp"]["kind"] == "described" and res["absm"]["kind"] == "described"
    assert s["family"]["p_family"] <= 0.05 and s["reading"] == "THE MARKET'S AND THE FORECAST'S"
    fam = s["features"]["families"]
    assert fam["relative"]["top"] == "f_state" and fam["relative"]["members"] == 3 and fam["relative"]["p_family"] < 0.15     # a step IC series: the same wide null
    fr = pd.read_csv("output/backtest/r47_dep_mech/features.csv")
    assert fr[(fr["bet"] == "relative") & (fr["feature"] == "f_state")]["D"].item() > 0.15 and (fr[fr["feature"] != "f_state"]["D"].abs() < 0.03).all()
    out = Path("output/backtest/r47_dep_mech")
    for f in ("mech.md", "mech.json", "shifts.parquet", "daily.parquet", "features.csv", "by_state.csv", "known_at.csv", "shifts_relative.parquet"):
        assert (out / f).exists(), f
    sh = pd.read_parquet(out / "shifts.parquet")
    assert len(sh) == s["shifts"] >= 200 and {"ic", "disp", "rho", "zdisp", "absm"} <= set(sh.columns)
    d = pd.read_parquet(out / "daily.parquet")
    assert (d["state"] != 0).mean() > 0.9 and d["rho"].notna().sum() >= 250
    by = pd.read_csv(out / "by_state.csv")
    assert {"by_fold", "side_state"} == set(by["table"]) and len(by[by["table"] == "side_state"]) == 4
    md = (out / "mech.md").read_text()
    assert "Validity: PASS" in md and "THE MARKET'S AND THE FORECAST'S" in md and "f_state" in md


def test_the_cells_are_cut_at_the_run_s_own_panel_end(tmp_path):
    """A run whose last fold ends inside the panel labelled no cell in its last `latency + hold` bars: the cells read here stop there too."""
    fc = _world(tmp_path, True)
    bt.run(Planted(), PAIRS, ["F1"], execs=("taker",), draws=1, name="r47_cut")
    fc.to_parquet("output/backtest/r47_cut/forecast.parquet", index=False)
    meta = json.loads(Path("output/backtest/r47_cut/meta.json").read_text())
    meta["folds"] = ["F0"]                                            # F0 ends 2023-05-01, inside the world (2023-03-20 → 2024-12)
    Path("output/backtest/r47_cut/meta.json").write_text(json.dumps(meta))
    m = _module()
    from ft2 import ceiling, folds
    P = ceiling.panel(PAIRS, pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp(START, tz="UTC"))
    o, _ = m.forecast_cells("r47_cut", P, HOLD, 1)
    end = folds.bounds("F0")[1]
    assert pd.DatetimeIndex(o["t"]).max() <= end - pd.Timedelta(minutes=5 * (HOLD + 1)) and (pd.DatetimeIndex(o["t"]) < end).all()
    want = fc[(fc["t"] <= end - pd.Timedelta(minutes=5 * (HOLD + 1))) & (fc["t"] >= folds.bounds("F0")[0])]
    assert len(o) == len(want) > 1000, (len(o), len(want))


def test_a_world_with_nothing_state_dependent_reads_as_nothing_clearing(tmp_path):
    m, s = _run(tmp_path, False, "r47_indep")
    res = {r["row"]: r for r in s["results"]}
    for r in ("ic", "disp", "rho"):
        assert res[r]["p"] > 0.05 and res[r]["verdict"] != "CLEARS", res[r]
    assert abs(res["ic"]["D"]) < 0.1 and s["reading"] == "NOT DETECTABLE AT THIS POWER"
    assert s["features"]["families"]["relative"]["p_family"] > 0.05
