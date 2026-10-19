"""R43 unit tests for `horizon.run_mom` on made-up bars: a planted momentum (a name's drift regime that lasts months) comes back through
R22's frame at 14 and 28 days with the registered sign and clears the gate, the week's move is a reference row; the validity block is
written first; a name without funding events is dropped and listed, too many of them void the run before any number of the family; the
signals are causal and the gap is the signal's window plus the longest hold plus one; the verdict names the opposite sign and is one-sided
on CLOSED."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt, ceiling, horizon as hz

NAMES = [f"{c}{c}{c}USDT" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"] + [f"Z{c}{c}USDT" for c in "ABCD"]          # 30 members
DAYS, START, REGIME = 400, "2023-02-01", 150                 # F0's tail → F1 → the first weeks of F2; drift regimes of 150 days (> the 113-day gap)
DRIFT, SD = 0.2, 5.0                                         # bps a bar; over 28 days ±1,600 of drift against ≈ 450 of noise


def _world(tmp_path, no_funding=(), zero_rate=(), seed=7, drift=DRIFT):
    """Thirty random-walk names; each name's drift is ±DRIFT bps a bar with a sign drawn per 150-day regime — the trailing month's return
    says which regime the name is in, and the regime says how the next weeks go: momentum, planted. Every name is a member of every
    block; names in `no_funding` have no funding events at all."""
    os.chdir(tmp_path)
    for d in ("data", "output/logs"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")
    n = len(t5)
    c5, fund, cost_wide = [], [], []
    for i, sym in enumerate(NAMES):
        signs = rng.choice([-1.0, 1.0], n // (REGIME * 288) + 2)
        d = drift * signs[np.arange(n) // (REGIME * 288)]
        px = 100 * (i + 1) * np.exp(np.cumsum(rng.normal(0, SD, n) + d) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - ceiling.BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        if sym not in no_funding:
            ft = pd.date_range(t5[0].floor("D"), periods=DAYS * 3 + 3, freq="8h")
            fund.append(pd.DataFrame({"symbol": sym, "ts": ft, "rate": 0.0 if sym in zero_rate else 1e-4, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 8, freq="D")
        cost_wide.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 3.0, f"imp_{bt.NOTIONAL}": 1.0, f"maker_adv_{bt.MAKER_H}": np.nan, f"maker_fill_{bt.MAKER_H}": np.nan}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 8, freq="D")
    pd.DataFrame({"symbol": "XXXUSDT", "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}).to_parquet("data/cost_daily.parquet", index=False)
    pd.concat(cost_wide).to_parquet("data/cost_daily_wide.parquet", index=False)
    blocks = pd.date_range(pd.Timestamp("2023-05-03", tz="UTC"), t5[-1], freq="30D")
    mem = pd.DataFrame([{"block": b, "symbol": s, "liq_musd": 10.0 + i, "vol_pct": 5.0, "play": 1.0, "age_days": 400 + i} for b in blocks for i, s in enumerate(NAMES)])
    mem.to_csv("members.csv", index=False)
    return "members.csv"


def test_the_gap_the_signals_and_the_verdict():
    assert hz.mom_gap_days((4032, 8064)) == 84 + 28 + 1 == 113 and hz.mom_gap_days((4032,)) == 99
    close = pd.DataFrame({"A": np.arange(1.0, 21.0), "B": 2.0 ** np.arange(20)})
    s = hz.mom_signals(close, {"m3": 3})["m3"]
    assert s["A"].iloc[:3].isna().all() and abs(s["A"].iloc[3] - (4.0 / 1.0 - 1.0)) < 1e-12 and abs(s["B"].iloc[10] - 7.0) < 1e-12       # closes at or before t only
    r = {"m_c": 30.0, "u": 3.0, "se": 10.0, "p_family": 0.01, "folds_same_sign": True, "after_same_sign": True}
    assert hz.mom_verdict(r) == "CLEARS" and hz.mom_verdict({**r, "m_c": -30.0, "u": -3.0}) == "CLEARS WITH THE OPPOSITE SIGN"
    assert hz.mom_verdict({**r, "m_c": -5.0, "u": -1.0, "se": 2.0}) == "CLOSED"                      # the upper bound −1.08 is under the cost: one-sided
    assert hz.mom_verdict({**r, "m_c": 5.0, "u": 0.5, "se": 10.0}) == "NOT DETECTABLE" and hz.mom_verdict({**r, "p_family": 0.2}) == "NOT DETECTABLE"
    assert hz.mom_verdict({**r, "m_c": -60.0, "u": -3.0, "se": 20.0}) == "CLEARS WITH THE OPPOSITE SIGN"   # named before CLOSED


def test_a_planted_momentum_clears_at_two_and_four_weeks_with_the_registered_sign(tmp_path):
    members = _world(tmp_path)
    md = hz.run_mom(NAMES, jobs=1, members=members)
    v = json.loads(Path("output/horizon/mom_screen/validity.json").read_text())
    assert v["status"] == "PASS" and v["registration"] == "R43" and v["cost_bps"] == 17.6 and v["names"] == v["members"] == 30 and v["members_without_bars"] == []
    assert v["whole_days"] and v["gap_days"] == 113 and v["shifts"] == v["shifts_expected"] == v["days"] - 2 * 113 + 1 >= 20
    assert v["max_abs_d_causal"] == 0.0 and v["max_abs_d_label_ref"] <= 1e-9 and v["names_dropped_under_funding_cover"] == [] and v["blocks"] >= 9
    assert v["signal_windows_bars"] == {"mom_4w": 8064, "mom_12w": 24192, "mom_1w": 2016} and v["unit"] == "actual" and v["charged"] == "value"
    tab = pd.read_csv("output/horizon/mom_screen/signals.csv").set_index(["signal", "hold"])
    for h in (4032, 8064):
        g = tab.loc[("mom_4w", h)]
        assert bool(g["family"]) and g["m_c"] > 17.6 and g["u"] >= 2 and g["p_family"] <= 0.05 and g["verdict"] == "CLEARS", (h, dict(g))
        assert g["m_F1"] > 0 and bool(g["folds_same_sign"]) and g["m_after_first_week"] > 0 and bool(g["after_same_sign"])
        assert g["m_top_tenth"] > 0 > g["m_bottom_tenth"] and np.isfinite(g["m_winsorised"]) and 14 < g["rt_extreme_tenths"] < 16     # the proxy's 15
        assert np.isfinite(g["funding_part"]) and g["funding_part"] != 0.0                                                             # funding inside the label
        assert tab.loc[("mom_12w", h), "m_c"] > 0 and bool(tab.loc[("mom_12w", h), "family"])
    assert (tab.loc["mom_1w"]["verdict"] == "reference").all() and (tab.loc["mom_1w"]["family"] == False).all()                       # noqa: E712
    assert tab.loc[("mom_4w", 288), "verdict"] == "reference" and tab.loc[("mom_4w", 2016), "verdict"] == "reference"
    assert "## Validity — read first: **PASS**" in md and "clear**" in md
    for f_ in ("horizon.md", "signals.csv", "tenths.csv", "shifts.parquet", "validity.json"):
        assert Path(f"output/horizon/mom_screen/{f_}").exists()
    sh = pd.read_parquet("output/horizon/mom_screen/shifts.parquet")
    assert set(sh["signal"]) == {"mom_4w", "mom_12w", "mom_1w"} and sh["shift"].max() == v["days"] - 113 and sh["shift"].min() == 0
    tenths = pd.read_csv("output/horizon/mom_screen/tenths.csv")
    assert set(tenths["tenth"]) == set(range(1, 11))


def test_a_name_without_funding_is_dropped_and_too_many_void_the_run(tmp_path):
    members = _world(tmp_path, no_funding=NAMES[:1], zero_rate=NAMES[1:3])
    hz.run_mom(NAMES, jobs=1, members=members)
    v = json.loads(Path("output/horizon/mom_screen/validity.json").read_text())
    assert v["status"] == "PASS" and v["names_dropped_under_funding_cover"] == NAMES[:1] and 0 < v["dropped_share"] < 0.05
    assert v["funding_cover_by_name"][NAMES[1]] == 1.0 and v["funding_cover_by_name"][NAMES[2]] == 1.0           # a settled rate of 0 is an event (BNB)
    assert v["funding_cover_by_name"][NAMES[0]] == 0.0 and v["names_without_labelled_cells"] == []
    members = _world(tmp_path, no_funding=NAMES[:4])
    with pytest.raises(SystemExit) as e:
        hz.run_mom(NAMES, jobs=1, members=members, name="mom_void")
    assert e.value.code == 2
    v = json.loads(Path("output/horizon/mom_void/validity.json").read_text())
    assert v["status"] == "FAIL" and v["names_dropped_under_funding_cover"] == NAMES[:4] and v["dropped_share"] > 0.10
    assert "VOID" in Path("output/horizon/mom_void/horizon.md").read_text() and not Path("output/horizon/mom_void/signals.csv").exists()


def test_r57_the_weekly_preset_reads_the_week_at_a_week_with_the_sign_negative_and_guards_the_confirmation_folds(tmp_path):
    """R57: the same frame with one signal (the week's move) at one hold (a week), the gap 7 + 7 + 1 = 15 days, the registered sign
    NEGATIVE — on the planted momentum world the row CLEARS WITH THE OPPOSITE SIGN; the confirmation folds refuse a read without a
    registration before anything is computed; the verdict is one-sided on the registered side."""
    members = _world(tmp_path)
    with pytest.raises(SystemExit):
        hz.run_mom(NAMES, hz.REV_HOLDS, hz.REV_REFS, jobs=1, members=members, fold_names=("F3", "F4"), family=hz.REV_FAMILY, described={},
                   window_days=hz.REV_WINDOW_DAYS, sign=hz.REV_SIGN, name="rev1w_guard")
    assert not Path("output/horizon/rev1w_guard/validity.json").exists()
    md = hz.run_mom(NAMES, hz.REV_HOLDS, hz.REV_REFS, jobs=1, members=members, family=hz.REV_FAMILY, described={}, window_days=hz.REV_WINDOW_DAYS,
                    sign=hz.REV_SIGN, name="rev1w_t", strategy="horizon --rev1w")
    v = json.loads(Path("output/horizon/rev1w_t/validity.json").read_text())
    assert v["status"] == "PASS" and v["sign"] == -1.0 and v["gap_days"] == 15 and v["window_days"] == 7 and v["after_ref_bars"] == 288
    assert v["shifts"] == v["shifts_expected"] == v["days"] - 2 * 15 + 1 and v["signal_windows_bars"] == {"mom_1w": 2016} and v["holds"] == [2016] and v["refs"] == [288]
    tab = pd.read_csv("output/horizon/rev1w_t/signals.csv").set_index(["signal", "hold"])
    assert len(tab) == 2 and bool(tab.loc[("mom_1w", 2016), "family"]) and tab.loc[("mom_1w", 288), "verdict"] == "reference"
    g = tab.loc[("mom_1w", 2016)]
    assert g["m_c"] > 17.6 and abs(g["u"]) >= 2 and g["verdict"] == "CLEARS WITH THE OPPOSITE SIGN", dict(g)       # the planted momentum, read against a reversal's sign
    assert g["p_family"] == g["p_single"]                                                                             # a family of one
    assert "the registered sign NEGATIVE (reversal)" in md and "`ft2 horizon --rev1w`" in md
    sh = pd.read_parquet("output/horizon/rev1w_t/shifts.parquet")
    assert set(sh["signal"]) == {"mom_1w"} and sh["shift"].max() == v["days"] - 15
    # the verdict on the registered side
    base = {"u": -3.0, "p_family": 0.01, "folds_same_sign": True, "after_same_sign": True, "se": 10.0}
    assert hz.mom_verdict({**base, "m_c": -60.0}, sign=-1.0) == "CLEARS" and hz.mom_verdict({**base, "m_c": 60.0, "u": 3.0}, sign=-1.0) == "CLEARS WITH THE OPPOSITE SIGN"
    assert hz.mom_verdict({**base, "m_c": 10.0, "u": 1.0}, sign=-1.0) == "CLOSED" and hz.mom_verdict({**base, "m_c": -10.0, "u": -1.0}, sign=-1.0) == "NOT DETECTABLE"
