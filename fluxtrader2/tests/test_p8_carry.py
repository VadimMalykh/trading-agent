"""AA5 unit tests for `scripts/aa5_carry.py` on made-up series: a day's funding is the sum of that day's settlements as the harness
cumulates them; the top quartile is picked from the days BEFORE the block only (point-in-time); the money of one name is the hand
arithmetic (funding − two perp legs − two spot legs − the premium's move); the annualisation. No real data."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import backtest as bt

READ = Path(__file__).resolve().parents[1] / "scripts" / "aa5_carry.py"
D = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
NAMES = ["AAUSDT", "BBUSDT", "CCUSDT", "DDUSDT"]


def _module():
    spec = importlib.util.spec_from_file_location("aa5_carry", READ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _costs(m, days, rates: dict[str, float], jump: dict[str, tuple[pd.Timestamp, float]] | None = None, tl=2.0):
    """Three settlements a day (00:00, 08:00, 16:00) at `rates[name]` bps each; `jump[name] = (from_day, bps)` raises the rate from a day on."""
    idx = m.cost_index(days)
    cum = np.zeros((len(idx), len(NAMES)))
    for j, s in enumerate(NAMES):
        ev = pd.date_range(days[0], days[-1] + pd.Timedelta(days=1), freq="8h", tz="UTC", inclusive="left")
        r = np.full(len(ev), rates[s])
        if jump and s in jump:
            r[ev >= jump[s][0]] = jump[s][1]
        pos = np.searchsorted(ev.as_unit("ns").asi8, idx.as_unit("ns").asi8, "right")
        cum[:, j] = np.concatenate([[0.0], np.cumsum(r)])[pos]
    cdays = pd.date_range(days[0], days[-1], freq="D", tz="UTC")
    one = np.ones((len(cdays), len(NAMES)))
    return bt.Costs(cdays, one * tl, one * 0, one, cum, None)


def test_a_days_funding_is_the_sum_of_its_settlements_and_the_annualisation():
    m = _module()
    days = m.day_grid(D("2023-05-01"), D("2023-07-30"))
    C = _costs(m, days, {"AAUSDT": 1.0, "BBUSDT": -0.5, "CCUSDT": 3.0, "DDUSDT": 0.0})
    F = m.daily_funding(C, days, pd.Index(NAMES))
    assert F.shape == (len(days), 4) and np.allclose(F["AAUSDT"], 3.0) and np.allclose(F["BBUSDT"], -1.5) and np.allclose(F["CCUSDT"], 9.0)
    M = m.membership(days, pd.Index(NAMES), None)
    tab = m.by_group(F, M, {"all": np.ones(len(days), bool)}, "t")
    r = tab.iloc[0]
    assert abs(r["mean_bps_day"] - (3.0 - 1.5 + 9.0 + 0.0) / 4) < 1e-9 and abs(r["mean_pct_yr"] - r["mean_bps_day"] * 365 / 100) < 1e-9
    assert abs(r["share_days_negative"] - 0.25) < 1e-9 and r["names"] == 4
    # membership by blocks: a name is counted only inside its blocks
    blocks = pd.DataFrame({"block": [D("2023-05-01"), D("2023-05-31")], "symbol": ["AAUSDT", "BBUSDT"]})
    Mb = m.membership(days, pd.Index(NAMES), blocks)
    assert Mb.loc[D("2023-05-15"), "AAUSDT"] and not Mb.loc[D("2023-05-31"), "AAUSDT"] and Mb.loc[D("2023-06-15"), "BBUSDT"] and not Mb.loc[D("2023-05-15"), "BBUSDT"]
    assert not Mb["CCUSDT"].any()


def test_the_top_quartile_is_picked_from_the_days_before_the_block_only():
    m = _module()
    days = m.day_grid(D("2023-04-01"), D("2023-07-30"))
    # DD pays nothing until 2023-05-31 and 20 bps a settlement from then on; CC always pays 3
    C = _costs(m, days, {"AAUSDT": 1.0, "BBUSDT": 0.5, "CCUSDT": 3.0, "DDUSDT": 0.0}, jump={"DDUSDT": (D("2023-05-31"), 20.0)})
    F = m.daily_funding(C, days, pd.Index(NAMES))
    M = m.membership(days, pd.Index(NAMES), None)
    starts = m.block_starts(days, D("2023-05-01"))
    assert list(starts[:3]) == [D("2023-05-01"), D("2023-05-31"), D("2023-06-30")]
    sets = m.top_sets(F, M, starts)
    assert sets[D("2023-05-01")] == ["CCUSDT"] and sets[D("2023-05-31")] == ["CCUSDT"]        # DD's jump starts ON 05-31: not in the trailing window
    assert sets[D("2023-06-30")] == ["DDUSDT"]                                                   # a block later it is the name paying the most
    pers = m.persistence(F, M, sets, m.fold_of_day(days, ["F1"]))
    r = pers.set_index("block").loc[D("2023-05-31")]
    assert abs(r["trailing_top_pct_yr"] - 9.0 * 3.65) < 1e-9 and abs(r["next_top_pct_yr"] - 9.0 * 3.65) < 1e-9 and r["next_all_pct_yr"] > r["next_top_pct_yr"]   # DD's 60 a day lifts the universe above CC


def test_the_money_of_one_name_is_the_hand_arithmetic():
    m = _module()
    days = m.day_grid(D("2023-04-01"), D("2023-07-30"))
    C = _costs(m, days, {"AAUSDT": 1.0, "BBUSDT": 0.5, "CCUSDT": 3.0, "DDUSDT": 0.0}, tl=2.0)
    F = m.daily_funding(C, days, pd.Index(NAMES))
    TL = m.taker_leg_daily(C, days, pd.Index(NAMES))
    P = pd.DataFrame(np.nan, index=days, columns=NAMES)
    P["CCUSDT"] = np.linspace(10.0, 40.0, len(days))                                             # the premium rises 30 bps over the span: the short loses it
    fold_of = m.fold_of_day(days, ["F1"])
    b1, b2 = D("2023-05-01"), D("2023-05-31")
    mb = m.money(F, TL, P, {b1: ["CCUSDT"], b2: ["CCUSDT", "AAUSDT"]}, fold_of)
    r1 = mb[(mb["block"] == b1) & (mb["symbol"] == "CCUSDT")].iloc[0]
    assert r1["entered"] and not r1["left"] and abs(r1["funding_bps"] - 30 * 9.0) < 1e-9 and abs(r1["perp_cost_bps"] - (5 + 2)) < 1e-9 and abs(r1["spot_cost_bps"] - (10 + 2)) < 1e-9
    dp = -(P.loc[D("2023-05-30"), "CCUSDT"] - P.loc[D("2023-04-30"), "CCUSDT"])
    assert abs(r1["dprem_bps"] - dp) < 1e-9 and r1["premium_held"] and abs(r1["net_bps"] - (270 - 7 - 12 + dp)) < 1e-9
    r2 = mb[(mb["block"] == b2) & (mb["symbol"] == "CCUSDT")].iloc[0]
    assert not r2["entered"] and r2["left"] and abs(r2["perp_cost_bps"] - 7) < 1e-9                  # kept across the blocks: the exit leg only
    a2 = mb[(mb["block"] == b2) & (mb["symbol"] == "AAUSDT")].iloc[0]
    assert a2["entered"] and a2["left"] and abs(a2["perp_cost_bps"] - 14) < 1e-9 and abs(a2["spot_cost_bps"] - 24) < 1e-9 and not a2["premium_held"] and abs(a2["net_bps"] - (90 - 14 - 24)) < 1e-9
    s = m.money_summary(mb, "fold")
    allrow = s[s["fold"] == "all"].iloc[0]
    assert allrow["blocks"] == 2 and abs(allrow["net_pct_yr_both_legs_capital"] - allrow["net_bps_block"] * 365 / 30 / 200) < 1e-9 and abs(allrow["turnover"] - 0.75) < 1e-9
