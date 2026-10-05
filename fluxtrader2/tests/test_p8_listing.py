"""ft2 listing (P8, R28): the launch list from announcements and first files, the entry an hour after the first bar and what
makes a launch eligible, the label as the harness pays a long, the benchmark of the block's members, the moving-block
bootstrap over weeks and the gate — synthetic data, no network."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import horizon, listing

D = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
BAR = pd.Timedelta("5min")


def test_the_launch_list_takes_a_contract_that_begins_in_the_month_of_its_announcement_or_the_next():
    bn = pd.DataFrame({"kind": ["perp_launch"] * 6 + ["spot_list", "perp_launch"],
                       "symbol": ["AAA", "AAA", "BBB", "CCC", "DDD", "EEE", "FFF", ""],
                       "release": [D("2023-06-10"), D("2023-06-20"), D("2023-07-31 23:00"), D("2023-06-01"), D("2023-04-30"), D("2024-09-01"), D("2023-06-01"), D("2023-06-02")],
                       "id": range(8)})
    first = pd.DataFrame({"symbol": ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT", "FFFUSDT", "AAAUSDT_230630"],
                          "first_month": ["2023-06", "2023-08", "2023-09", "2023-05", "2024-09", "2023-06", "2023-06"]})
    L = listing.launch_list(bn, first, D("2023-05-01"), D("2024-09-01"))
    assert L["contract"].tolist() == ["AAAUSDT", "BBBUSDT"]            # CCC began three months later: not the same event; DDD and EEE were announced outside the folds; FFF is a spot listing
    assert L["release"].tolist() == [D("2023-06-10"), D("2023-07-31 23:00")] and L["id"].tolist() == [0, 2]     # the earliest announcement of a contract; the next month counts


def _market(n=400, cols=("NEW", "M1", "M2", "M3", "BTCUSDT"), seed=0, born=None):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-06-05 00:05", periods=n, freq="5min", tz="UTC", name="t")
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, len(cols))), axis=0)), index=idx, columns=list(cols))
    dv = pd.DataFrame(1e6, index=idx, columns=list(cols))
    for c, i in (born or {}).items():
        close.iloc[:i, close.columns.get_loc(c)] = np.nan
        dv.iloc[:i, dv.columns.get_loc(c)] = np.nan
    return bt.Market(close, close * 1.001, close * 0.999, dv)


def _costs(M, seed=1):
    rng = np.random.default_rng(seed)
    n, k = M.close.shape
    rate = np.where(np.arange(n)[:, None] % 48 == 0, rng.normal(1.0, 3.0, (n, k)), 0.0)                       # a funding event every four hours, bps
    one = np.ones((1, k))
    return bt.Costs(pd.DatetimeIndex([M.index[0].floor("D")]), one * 1.5, one * 0, one, np.cumsum(rate, axis=0), np.cumsum(rate * M.close.ffill().bfill().to_numpy(), axis=0))


def test_the_entry_is_an_hour_after_the_first_bar_and_the_calendar_cuts_what_the_folds_cannot_hold():
    M = _market(born={"NEW": 100, "M1": 300, "M2": 100})
    L = pd.DataFrame({"contract": ["NEW", "M1", "M2", "M3", "GONE"],
                      "release": [M.index[100] - pd.Timedelta("35min"), M.index[300] - pd.Timedelta("35min"), M.index[100] + pd.Timedelta("3h"), M.index[0], M.index[0]]})
    E = listing.entries(M, L, end=M.index[-1] + BAR, first_block=M.index[50], longest=200).set_index("contract")
    assert E.loc["NEW", "t0"] == M.index[100] - BAR and E.loc["NEW", "row"] == 111 and E.loc["NEW", "t"] == E.loc["NEW", "t0"] + pd.Timedelta("60min")     # the index is a bar's close
    assert E.loc["NEW", "eligible"] and E.loc["NEW", "why"] == ""
    assert E.loc["M1", "t0_ok"] and E.loc["M1", "why"] == "the 30-day exit is not before the end"                # 311 + 1 + 200 is beyond the market
    assert not E.loc["M2", "t0_ok"] and E.loc["M2", "why"] == "t0 outside the release's window"                  # it traded three hours before its announcement
    assert E.loc["M3", "why"] == E.loc["GONE", "why"] == "no first bar in the market" and E.loc["GONE", "row"] == -1   # bars from the first row on: the beginning is not seen; no bars at all
    early = listing.entries(M, L.iloc[:1], end=M.index[-1] + BAR, first_block=M.index[150], longest=200)
    assert early["why"].iloc[0] == "before F1's first scored instant"
    exact = listing.entries(M, L.iloc[:1], end=M.index[111 + 1 + 200], first_block=M.index[50], longest=200)
    assert exact["why"].iloc[0] == "the 30-day exit is not before the end"                                       # an exit bar AT the end is not before it


def test_the_label_is_horizons_and_the_harness_pays_a_long_the_same():
    M = _market()
    C = _costs(M)
    rows, hold = np.array([5, 120, 250, 395, -1]), 40
    lab = listing.label_at(M.close.to_numpy(), C.fundval, rows, hold)
    full = horizon.labels(M, C, hold, bt.LATENCY)[1].to_numpy()
    assert np.allclose(lab[:3], full[rows[:3]], rtol=0, atol=1e-9) and np.isnan(lab[3:]).all()                   # beyond the market, or no row: no label
    dec = pd.DataFrame({"t": M.index[rows[:3]], "symbol": "NEW", "side": 1, "hold": hold, "size": 1.0, "fold": "F1", "accepted": True})
    f = bt.price(dec, M, C, "taker", 5.0, 2.0)
    assert np.allclose((f["gross_bps"] + f["funding_bps"]).to_numpy(), lab[:3, 0], rtol=0, atol=1e-9) and (f["funding_bps"] != 0).any()


def test_the_benchmark_is_the_mean_of_the_blocks_members_that_have_a_label():
    cols = pd.Index(["NEW", "M1", "M2", "M3", "BTCUSDT"])
    mem = pd.DataFrame({"block": [D("2023-06-01")] * 2 + [D("2023-07-01")] * 3, "symbol": ["M1", "M2", "M1", "M3", "NEW"]})
    mask = listing.member_mask(mem, cols, [D("2023-06-15"), D("2023-07-01"), D("2023-08-20")])
    assert mask.tolist() == [[False, True, True, False, False], [True, True, False, True, False], [True, True, False, True, False]]   # the last block begun at or before t
    A = np.array([[10.0, 2.0, 4.0, 99.0, 7.0], [10.0, 6.0, 99.0, np.nan, 7.0], [10.0, np.nan, 99.0, np.nan, 7.0]])
    a, b, nb = listing.excess(A, np.zeros(3, dtype=int), mask)
    assert a.tolist() == [10.0, 10.0, 10.0] and b[:2].tolist() == [3.0, 6.0] and nb.tolist() == [2, 1, 0] and np.isnan(b[2])   # a launch is not its own benchmark; a member without a price is left out


def test_weeks_begin_on_monday_and_keep_the_empty_ones():
    wk, W = listing.weeks(pd.DatetimeIndex([D("2023-06-11 23:55"), D("2023-06-12 00:00"), D("2023-06-18 12:00"), D("2023-07-03")]))   # a Sunday, the Monday after, that week's Sunday, three weeks on
    assert wk.tolist() == [0, 1, 1, 4] and W == 5


def test_the_bootstrap_knows_noise_from_a_drift_and_weeks_that_move_together():
    rng = np.random.default_rng(3)
    W, per = 60, 2
    wk = np.repeat(np.arange(W), per)
    noise = rng.normal(0, 1000, (W * per, 4))
    r0 = listing.bootstrap(noise, wk, W, draws=2000)
    assert np.allclose(r0["m"], noise.mean(0)) and (np.abs(r0["u"]) < 3).all() and r0["p_fw"] > 0.05
    assert np.all(np.abs(r0["se"] / r0["se_plain"] - 1) < 0.35)                                                  # independent launches: the block bootstrap agrees with the plain se
    r1 = listing.bootstrap(noise - 600, wk, W, draws=2000)
    assert (r1["u"] < -4).all() and r1["p_fw"] < 0.01                                                            # a drift of 0.6 sd on 120 launches is seen at every hold
    common = np.repeat(rng.normal(0, 1000, (W // 6, 1)), 6 * per, axis=0) + rng.normal(0, 100, (W * per, 4))     # six-week regimes: every launch of a regime moves together
    r2 = listing.bootstrap(common, wk, W, draws=2000)
    assert np.all(r2["se"] > 2.0 * r2["se_plain"]) and np.all(r2["se_week"] > 1.2 * r2["se_plain"])              # the plain se would call this noise a finding
    holes = noise.copy()
    holes[:10, 3] = np.nan
    assert listing.bootstrap(holes, wk, W, draws=500)["n"].tolist() == [120, 120, 120, 110]                      # a missing label is not a zero


def test_the_gate():
    v = listing.verdict
    assert v(-900, 300, -3.0, 0.01, -1000, -800, -700) == "CLEARS"
    assert v(-900, 300, -3.0, 0.06, -1000, -800, -700) == "NOT DETECTABLE"                                       # the family-wise p
    assert v(-900, 300, -3.0, 0.01, -2000, +100, -700) == "NOT DETECTABLE"                                       # one fold of the other sign
    assert v(-900, 300, -3.0, 0.01, -1000, -800, +50) == "NOT DETECTABLE"                                        # six launches made it
    assert v(-900, 300, -3.0, 0.01, -1000, -800, -30) == "NOT DETECTABLE"                                        # … or the rest is under the bar
    assert v(-500, 300, -1.7, 0.20, -500, -500, -500) == "NOT DETECTABLE" and v(40, 300, 0.1, 0.9, 40, 40, 40) == "NOT DETECTABLE"
    assert v(10, 15, 0.7, 0.6, 10, 10, 10) == "CLOSED"                                                           # 10 + 1.96·15 < 46
    assert listing.trimmed(np.array([-9000.0, -50, -40, -30, 1, 2, 3, 20000, 30000, np.nan, 40000]), k=3) == np.mean([-30.0, 1, 2, 3])


def test_the_fingerprint_passes_what_came_back_and_fails_a_changed_name():
    spec = importlib.util.spec_from_file_location("r28_fingerprint", Path(__file__).parents[1] / "scripts" / "r28_fingerprint.py")
    fp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fp)
    old = pd.DataFrame({"slice": ["candles_5m_archive", "candles_5m_archive", "funding_archive"], "symbol": ["A", "B", "A"], "rows": [10, 20, 3], "first": [D("2023-01-01")] * 3,
                        "last": [D("2023-02-01")] * 3, "sum_close": [1.5, 2.5, np.nan], "sum_volume": [10.0, 20.0, np.nan], "sum_rate": [np.nan, np.nan, 0.001]})
    new = pd.concat([old, old.iloc[:1].assign(symbol="NEWUSDT")], ignore_index=True)
    r = fp.compare(old, new)
    assert r["status"] == "PASS" and r["new_names"] == 1 and r["names_missing_after"] == 0
    assert fp.compare(old, new.assign(rows=lambda x: x["rows"].where(x["symbol"] != "B", 21)))["status"] == "FAIL"
    assert fp.compare(old, new[new["symbol"] != "B"])["status"] == "FAIL"
    assert fp.compare(old, new.assign(sum_close=lambda x: x["sum_close"] * (1 + 1e-9)))["status"] == "FAIL"
    grown = new.copy()                                                                                           # A's klines now begin a month earlier: more rows, other sums
    grown.loc[0, ["rows", "first", "sum_close", "sum_volume"]] = [15, D("2022-12-01"), 2.0, 14.0]
    assert fp.compare(old, grown)["status"] == "FAIL"
    ext = fp.extended(old, grown)
    assert ext[["slice", "symbol"]].values.tolist() == [["candles_5m_archive", "A"]] and ext["first"].iloc[0] == D("2023-01-01")
    r = fp.compare(old, grown, old.iloc[:1])                                                                     # on its old extent A is what it was
    assert r["status"] == "PASS" and r["names_compared_on_their_old_extent"] == 1 and r["new_names"] == 1
    assert fp.compare(old, grown, old.iloc[:1].assign(rows=9))["status"] == "FAIL"                               # … unless an old row is gone
    assert len(fp.extended(old, grown.assign(rows=lambda x: x["rows"].where(x.index != 0, 5)))) == 0             # fewer rows is never an extension


# ---- R29: the sold position, its stop, its costs, its hedge -----------------------------------------------------------------------
def test_the_stop_buys_back_at_the_bar_after_the_first_close_at_the_level():
    c = np.array([100.0, 100, 150, 189.9, np.nan, 190, 400, 120, 110, 100, 100, 100])
    assert listing.stop_exit(c, 1, hold=8, level=1.9) == (6, True)                   # the close of 190 at row 5 is the trigger; a missing close is none; the exit is the next bar, whatever it is
    assert listing.stop_exit(c, 1, hold=4, level=1.9) == (5, False)                  # the trigger bar is the full-hold exit itself: the hold ends there, not stopped
    assert listing.stop_exit(c, 1, hold=5, level=1.9) == (6, True)                   # the trigger is the last bar before the exit: the exit is the full hold's bar
    assert listing.stop_exit(c, 6, hold=5, level=1.9) == (11, False) and listing.stop_exit(c, 1, hold=8, level=np.inf) == (9, False)
    assert listing.stop_exit(c, 0, hold=3, level=1.5) == (3, True)                   # the entry bar itself never triggers: row 2's 150 does


def test_a_leg_on_the_entry_day_is_twice_that_days_row_or_the_first_row_after():
    days = pd.date_range("2024-10-01", periods=4, freq="D", tz="UTC")
    leg = np.array([[np.nan, 5.0], [np.nan, 6.0], [8.0, 7.0], [9.0, 7.5]])
    out = listing.entry_day_legs(leg, days, [days[0], days[1]], np.array([0, 1]), 2.0)
    assert out[0, 0] == 16.0 and out[1, 1] == 12.0                                   # no row on the first day: twice the first row after; a row that day: twice it
    assert np.isnan(out[1, 0]) and out[2, 0] == 8.0 and out[0, 1] == 5.0             # nothing else is touched
    assert np.isnan(listing.entry_day_legs(leg[:2], days[:2], [days[0]], np.array([0]), 2.0)[0, 0])   # a contract with no row at all stays unpriced


def test_the_sold_trade_is_the_harness_fill_with_its_stop_and_a_hedge_that_pays_its_costs():
    n = 80
    idx = pd.date_range("2024-10-01 00:05", periods=n, freq="5min", tz="UTC", name="t")
    close = pd.DataFrame({"NEW": 100.0, "UP": 100.0, "M1": 50.0, "M2": 20.0}, index=idx)
    close.loc[idx[30:], "NEW"] = 80.0                                                 # NEW falls 20 %: a sold position earns 2,000
    close.loc[idx[20:], "UP"] = 250.0                                                 # UP more than doubles at row 20: stopped at row 21
    close.loc[idx[40:], "M1"] = 55.0                                                  # the members: +10 % and flat → a hedge of +500 on NEW's bars
    M = bt.Market(close, close, close, close * 0 + 1e6)
    z = np.zeros((n, 4))
    fund = z.copy()
    fund[35:, 0] = 2.0                                                                # NEW: one payment of 2 bps at row 35 — the seller receives it, on the value (80)
    C = bt.Costs(pd.DatetimeIndex([idx[0].floor("D")]), np.array([[3.0, 4.0, 1.0, np.nan]]), z[:1], z[:1] + 1, fund, fund * close.to_numpy())
    E = pd.DataFrame({"contract": ["NEW", "UP"], "row": [9, 9], "fold": "F3"})
    mask = np.array([[True, False, True, True], [False, False, True, True]])          # NEW's mask wrongly holds NEW itself: never its own hedge
    T = listing.sold_trades(M, C, E, mask, taker_bps=5.0, hold=60, level=1.9)
    a, b = T.iloc[0], T.iloc[1]
    assert (a["e"], a["x"], bool(a["stopped"])) == (10, 70, False) and (b["e"], b["x"], bool(b["stopped"])) == (10, 21, True)
    assert np.isclose(a["gross"], 2000.0) and np.isclose(a["funding"], 2.0 * 80 / 100) and np.isclose(a["fee"], 5 + 5 * 0.8)
    assert np.isclose(a["leg_entry"], 6.0) and np.isclose(a["spread_impact"], 6.0 + 6.0 * 0.8)      # the entry day is the only day here: both legs at twice the row
    assert np.isclose(a["own"], 2000 + 1.6 - 9 - 10.8)
    assert a["n_b"] == 1 and np.isclose(a["hedge_gain"], 1000.0) and np.isclose(a["hedge_cost"], (5 + 1) + (5 + 1) * 1.1)   # M2 has no cost row: left out of the hedge; M1 +10 %
    assert np.isclose(a["H"], a["own"] + 1000.0 - 12.6)
    assert np.isclose(b["gross"], -15000.0) and np.isclose(b["fee"], 5 + 5 * 2.5) and np.isclose(b["hedge_gain"], 0.0)       # the stop cannot undo the jump it saw: −150 % of the size
    heavy = listing.sold_trades(M, C, E, mask, taker_bps=5.0, entry_mult=4.0, other_mult=2.0, hold=60, level=1.9).iloc[0]
    assert np.isclose(heavy["leg_entry"], 12.0) and np.isclose(heavy["hedge_cost"], (5 + 2) + (5 + 2) * 1.1) and heavy["H"] < a["H"]
    late = listing.sold_trades(M, C, E.iloc[:1], mask[:1], taker_bps=5.0, hold=40, level=1.9, shift=25).iloc[0]
    assert (late["e"], late["x"]) == (35, 75) and np.isclose(late["gross"], 0.0)                     # entered after the fall: nothing left


def test_the_confirmation_gate_and_its_noise():
    v = listing.verdict_confirm
    assert v(400, 150, 300) == "CONFIRMED" and v(400, 150, -5) == "NOT CONFIRMED" and v(250, 150, 200) == "NOT CONFIRMED"
    assert v(-400, 150, -500) == "CLOSED" and v(-200, 150, -300) == "NOT CONFIRMED"
    rng = np.random.default_rng(5)
    t = pd.DatetimeIndex(pd.Timestamp("2024-09-02", tz="UTC") + pd.to_timedelta(np.sort(rng.integers(0, 60 * 7, 200)), unit="D"))
    h = rng.normal(300, 2000, 200)
    r = listing.noise(h, t)
    assert r["n"] == 200 and np.isclose(r["M"], h.mean()) and r["se"] == max(r["se_bootstrap"], r["se_week"]) and np.isclose(r["u"], r["M"] / r["se"])
    assert 0.6 < r["se"] / r["se_plain"] < 1.6
