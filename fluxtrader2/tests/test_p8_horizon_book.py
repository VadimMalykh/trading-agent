"""R35 unit tests for `horizon.run_book` on made-up bars and a made-up book: a slow book level planted to predict the next weeks comes
back through R22's frame at 3 and 7 days with the registered sign, clearing the gate, while the within-month part is a reference row;
the validity block is written first and a changed depth file (md5) voids the run before any number of the family; the verdict names
the opposite sign; `_tenths` keeps its registered behaviour and takes a smaller cell floor for the one-universe rows."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt, ceiling, horizon as hz
from ft2.book_ext import DM, LVL, RAW

TWELVE = [f"{c}{c}{c}USDT" for c in "ABCDEFGHIJ"]
NEW = [f"{c}{c}{c}USDT" for c in "KLMNOPQRST"]
DAYS, START, BLOCK = 140, "2023-03-25", 40                  # F0's tail → F1; drift blocks of 40 days (longer than the null's 38-day gap)


def _world(tmp_path, drift: float = 1.0, sign: float = -1.0, seed: int = 21):
    """Twenty random-walk names with a drift of ±`drift` bps a bar whose sign is drawn per name per 40-day block. The book's imbalance at
    a bar is `sign` × the sign of the drift in force 30 days later (plus noise), so its trailing-30-day mean is the sign of the coming
    month's drift: a slow level that predicts the next week, with the registered sign when `sign` is −1."""
    os.chdir(tmp_path)
    for d in ("data/depth", "output/logs"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")
    n, ahead = len(t5), 30 * 288
    c5, fund, cost, cost_wide = [], [], [], []
    for i, sym in enumerate([*TWELVE, *NEW]):
        signs = rng.choice([-1.0, 1.0], (n + ahead) // (BLOCK * 288) + 2)
        d = drift * signs[np.arange(n + ahead) // (BLOCK * 288)]
        px = 100 * (i + 1) * np.exp(np.cumsum(rng.normal(0, 6.0, n) + d[:n]) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - ceiling.BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        imb = np.clip(sign * np.sign(d[ahead:ahead + n]) * 0.4 + rng.normal(0, 0.05, n), -0.95, 0.95)
        ts = t5 - pd.Timedelta("1min")                                             # one sample a bar, strictly before the bar's close
        pd.DataFrame({"symbol": sym, "ts": ts, "usd_m1": 1e6 * (1 + imb), "usd_p1": 1e6 * (1 - imb), "usd_m5": 5e6, "usd_p5": 5e6}).to_parquet(f"data/depth/{sym}.parquet", index=False)
        ft = pd.date_range(t5[0].floor("D"), periods=DAYS * 3 + 3, freq="8h")
        fund.append(pd.DataFrame({"symbol": sym, "ts": ft, "rate": 1e-4, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 8, freq="D")
        if sym in TWELVE:
            cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
        else:
            cost_wide.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 3.0, f"imp_{bt.NOTIONAL}": 1.0, f"maker_adv_{bt.MAKER_H}": np.nan, f"maker_fill_{bt.MAKER_H}": np.nan}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)
    pd.concat(cost_wide).to_parquet("data/cost_daily_wide.parquet", index=False)


def test_tenths_keeps_its_floor_and_takes_a_smaller_one_for_a_single_universe():
    rng = np.random.default_rng(0)
    S = rng.normal(size=(48, 10))
    Y = S * 100 + rng.normal(0, 1, (48, 10))                                   # the top tenth earns ~+100 more than the bottom
    assert np.isnan(hz._tenths(S, Y)).all()                                     # ten cells are under MIN_CELLS = 20
    m = hz._tenths(S, Y, min_cells=8)
    assert m.shape == (2,) and (m > 100).all()                                   # k = max(round(1.0), 1) = 1 a side, halved: (top − bottom) / 2 ≈ +150
    r = {"m_c": -30.0, "u": -3.0, "se": 10.0, "p_family": 0.01, "folds_same_sign": True, "after_same_sign": True}
    assert hz.book_verdict(r) == "CLEARS" and hz.book_verdict({**r, "m_c": 30.0, "u": 3.0}) == "CLEARS WITH THE OPPOSITE SIGN"
    assert hz.book_verdict({**r, "m_c": -5.0, "u": -1.0, "se": 2.0}) == "CLOSED" and hz.book_verdict({**r, "u": -1.0}) == "NOT DETECTABLE"


def test_a_planted_slow_book_clears_at_a_week_with_the_registered_sign(tmp_path):
    _world(tmp_path)
    md = hz.run_book([*TWELVE, *NEW], jobs=1, twelve=TWELVE, md5_file=Path("none.txt"))
    v = json.loads(Path("output/horizon/book_both/validity.json").read_text())
    assert v["status"] == "PASS" and v["names"] == 20 and v["whole_days"] and v["shifts"] == v["shifts_expected"] == v["days"] - 2 * 38 + 1 >= 20
    assert v["max_abs_d_frames"] == 0.0 and v["max_abs_d_label_288"] <= 1e-9 and v["names_under_funding_cover"] == [] and v["depth_md5_vs_r34"] == {}
    tab = pd.read_csv("output/horizon/book_both/signals.csv").set_index(["signal", "hold"])
    for h in (864, 2016):
        g = tab.loc[(LVL, h)]
        assert bool(g["family"]) and g["m_c"] < -15 and g["u"] <= -2 and g["p_family"] <= 0.05 and g["verdict"] == "CLEARS", (h, dict(g))
        assert g["m_F1"] < 0 and bool(g["folds_same_sign"]) and g["m_after_first"] < 0 and bool(g["after_same_sign"])
        assert np.isfinite(g["m_twelve"]) and np.isfinite(g["m_new"]) and 10 < g["rt_extreme_tenths"] < 16   # the tape's 12 and the proxy's 15 mixed
        assert np.isfinite(g["funding_part"]) and g["funding_part"] != 0.0                                   # funding is inside the label
    assert tab.loc[(LVL, 288), "verdict"] == "reference" and (tab.loc[DM]["verdict"] == "reference").all() and (tab.loc[DM]["family"] == False).all()  # noqa: E712
    assert "## Validity — read first: **PASS**" in md and "clear**" in md
    for f_ in ("horizon.md", "signals.csv", "tenths.csv", "shifts.parquet"):
        assert Path(f"output/horizon/book_both/{f_}").exists()
    sh = pd.read_parquet("output/horizon/book_both/shifts.parquet")
    assert set(sh["signal"]) == {LVL, RAW, DM} and sh["shift"].max() == v["days"] - 38 and sh["shift"].min() == 0


def test_a_changed_depth_file_voids_the_run_before_any_number_of_the_family(tmp_path):
    _world(tmp_path)
    Path("output/logs/md5.txt").write_text(f"{'0' * 32}  data/depth/{TWELVE[0]}.parquet\n")
    with pytest.raises(SystemExit) as e:
        hz.run_book([*TWELVE, *NEW], jobs=1, twelve=TWELVE, md5_file=Path("output/logs/md5.txt"))
    assert e.value.code == 2
    v = json.loads(Path("output/horizon/book_both/validity.json").read_text())
    assert v["status"] == "FAIL" and v["depth_md5_vs_r34"] == {TWELVE[0].replace("USDT", "USDT"): "DIFFERENT"}
    assert "VOID" in Path("output/horizon/book_both/horizon.md").read_text() and not Path("output/horizon/book_both/signals.csv").exists()
