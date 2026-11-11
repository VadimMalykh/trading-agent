"""R86 unit tests for `horizon.run_mom` with the volatility preset (`ft2 horizon --vol`) on made-up bars: names in a WILD regime (a larger
5m sd) drift down against the calm ones — the planted lottery effect comes back through R43's frame at 14 and 28 days with the registered
sign NEGATIVE and clears; the signals are causal (closes at or before t), the gap is 29 + 28 + 1 = 58 days; the same world read with the
sign POSITIVE is named "with the opposite sign"."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import backtest as bt, ceiling, horizon as hz

NAMES = [f"{c}{c}{c}USDT" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"] + [f"Z{c}{c}USDT" for c in "ABCD"]          # 30 members
DAYS, START, REGIME = 400, "2023-02-01", 150                 # drift regimes of 150 days (> the 58-day gap)
DRIFT, SD_CALM, SD_WILD = 0.25, 4.0, 10.0                    # bps a bar


def _world(tmp_path, seed=11):
    """Thirty names; per 150-day regime a name is WILD (sd 10 bps a bar, drift −0.25) or CALM (sd 4, drift +0.25): the trailing month's
    volatility says which, and the regime says how the next weeks go."""
    os.chdir(tmp_path)
    for d in ("data", "output/logs"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")
    n = len(t5)
    c5, fund, cost_wide = [], [], []
    dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 8, freq="D")
    for i, sym in enumerate(NAMES):
        wild = rng.choice([0.0, 1.0], n // (REGIME * 288) + 2)[np.arange(n) // (REGIME * 288)]
        px = 100 * (i + 1) * np.exp(np.cumsum(rng.normal(0, 1.0, n) * np.where(wild > 0, SD_WILD, SD_CALM) + np.where(wild > 0, -DRIFT, DRIFT)) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - ceiling.BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0].floor("D"), periods=DAYS * 3 + 3, freq="8h"), "rate": 1e-4, "interval_h": 8}))
        cost_wide.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 3.0, f"imp_{bt.NOTIONAL}": 1.0, f"maker_adv_{bt.MAKER_H}": np.nan, f"maker_fill_{bt.MAKER_H}": np.nan}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.DataFrame({"symbol": "XXXUSDT", "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}).to_parquet("data/cost_daily.parquet", index=False)
    pd.concat(cost_wide).to_parquet("data/cost_daily_wide.parquet", index=False)
    blocks = pd.date_range(pd.Timestamp("2023-05-03", tz="UTC"), t5[-1], freq="30D")
    pd.DataFrame([{"block": b, "symbol": s, "liq_musd": 10.0 + i, "vol_pct": 5.0, "play": 1.0, "age_days": 400 + i} for b in blocks for i, s in enumerate(NAMES)]).to_csv("members.csv", index=False)
    return "members.csv"


def _run(members, **kw):
    return hz.run_mom(NAMES, jobs=1, members=members, family=hz.VOL_FAMILY, described=hz.VOL_DESCRIBED, window_days=hz.VOL_WINDOW_DAYS,
                      strategy="horizon --vol", signal_fn=hz.vol_signals, what="trailing volatility", **kw)


def test_the_volatility_signals_read_closes_at_or_before_t_only_and_the_gap_is_58_days():
    assert hz.mom_gap_days((4032, 8064), hz.VOL_WINDOW_DAYS) == 29 + 28 + 1 == 58 and hz.VOL_SIGN == -1.0 and hz.VOL_REG == "R86"
    assert hz.VOL_FAMILY == {"vol_4w": 8064, "maxd_4w": 8064} and hz.VOL_DESCRIBED == {"vol_1w": 2016}
    rng = np.random.default_rng(0)
    close = pd.DataFrame({"A": 100 * np.exp(np.cumsum(rng.normal(0, 1e-3, 3000)))})
    close.iloc[2500:, 0] *= 1.5                                                    # one +50 % step at bar 2,500
    w = {"vol_x": 1000, "maxd_x": 1000}
    s = hz.vol_signals(close, w)
    cut = hz.vol_signals(close.iloc[:2400], w)
    for k in w:
        assert s[k]["A"].iloc[:799].isna().all() and s[k]["A"].iloc[1100:2400].equals(cut[k]["A"].iloc[1100:2400])      # ≥ 80 % of the window; nothing after t read
    r = np.log(close["A"]).diff()
    assert abs(s["vol_x"]["A"].iloc[2300] - r.iloc[1301:2301].std()) < 1e-12
    assert s["maxd_x"]["A"].iloc[2499] < 0.2 < 0.45 < s["maxd_x"]["A"].iloc[2500] and s["maxd_x"]["A"].iloc[2999] > 0.45       # the step enters at its own bar and stays the window


def test_a_planted_lottery_effect_clears_negative_and_the_positive_reading_names_the_opposite_sign(tmp_path):
    members = _world(tmp_path)
    md = _run(members, name=hz.VOL_NAME, sign=hz.VOL_SIGN, registration=hz.VOL_REG)
    v = json.loads(Path("output/horizon/vol_screen/validity.json").read_text())
    assert v["status"] == "PASS" and v["registration"] == "R86" and v["sign"] == -1.0 and v["cost_bps"] == 17.6 and v["names"] == v["members"] == 30
    assert v["gap_days"] == 58 and v["shifts"] == v["shifts_expected"] == v["days"] - 2 * 58 + 1 >= 20 and v["max_abs_d_causal"] == 0.0 and v["max_abs_d_label_ref"] <= 1e-9
    assert v["signal_windows_bars"] == {"vol_4w": 8064, "maxd_4w": 8064, "vol_1w": 2016} and v["names_dropped_under_funding_cover"] == []
    tab = pd.read_csv("output/horizon/vol_screen/signals.csv").set_index(["signal", "hold"])
    for h in (4032, 8064):
        g = tab.loc[("vol_4w", h)]
        assert bool(g["family"]) and g["m_c"] < -17.6 and g["u"] <= -2 and g["p_family"] <= 0.05 and g["verdict"] == "CLEARS", (h, dict(g))
        assert g["m_F1"] < 0 and bool(g["folds_same_sign"]) and g["m_after_first_week"] < 0 and g["m_top_tenth"] < 0 < g["m_bottom_tenth"]
        assert bool(tab.loc[("maxd_4w", h), "family"]) and tab.loc[("maxd_4w", h), "m_c"] < 0
    assert (tab.loc["vol_1w"]["verdict"] == "reference").all() and tab.loc[("vol_4w", 288), "verdict"] == "reference"
    assert "trailing volatility" in md and "the registered sign NEGATIVE" in md and "## Validity — read first: **PASS**" in md
    _run(members, name="vol_pos", sign=1.0)
    pos = pd.read_csv("output/horizon/vol_pos/signals.csv").set_index(["signal", "hold"])
    assert pos.loc[("vol_4w", 8064), "verdict"] == "CLEARS WITH THE OPPOSITE SIGN"
