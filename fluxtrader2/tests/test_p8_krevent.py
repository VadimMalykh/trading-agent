"""R70 (`ft2/krevent.py`) on planted bars, no network: the decision bar closes at t0 + 60 min and the position enters one bar later; an
event the market cannot hold is dropped and counted; the bar B_i from the name's own cost row with the 7-day fallback and R28's 46; the
gate's sign; a planted pump-and-give-back is found NEGATIVE with the run-up row showing the pump, the split rows apart, the label identity
with `horizon.labels` and the harness, validity (2) and (7) read, the fingerprint check's void."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt
from ft2 import krevent, krlist, listing, universe

D = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
BAR = pd.Timedelta("5min")
EV = ["EV1USDT", "EV2USDT", "EV3USDT", "EV4USDT", "EV5USDT", "EV6USDT", "EV7USDT", "EV8USDT"]
MEM = ["M1USDT", "M2USDT", "M3USDT", "M4USDT", "M5USDT"]


def _market(weeks=16, seed=0, pump=0.08, giveback=-0.04):
    """Sixteen weeks of 5m bars; the eight event names pump over the day before their t0 and give it back over the day after."""
    rng = np.random.default_rng(seed)
    n = weeks * 7 * 288
    idx = pd.date_range("2023-06-05 00:05", periods=n, freq="5min", tz="UTC", name="t")
    cols = [*EV, *MEM, "BTCUSDT"]
    r = rng.normal(0, 0.002, (n, len(cols)))
    t0s = [idx[0].floor("D") + pd.Timedelta(days=4 + 9 * k, hours=7) for k in range(len(EV))]        # every ninth day at 07:00 UTC
    for j, t0 in enumerate(t0s):
        if t0 + pd.Timedelta(days=2) > idx[-1]:                                                                # a short market: the later events lie beyond it
            continue
        i0 = idx.get_loc(t0)
        r[i0 - 288:i0, j] += pump / 288                                                              # the day before t0
        r[i0 + 13:i0 + 13 + 288, j] += giveback / 288                                                # the day after the entry (row + latency)
    close = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=cols)
    dv = pd.DataFrame(1e6, index=idx, columns=cols)
    return bt.Market(close, close * 1.001, close * 0.999, dv), t0s


def _costs(M, days=None, legs=None):
    n, k = M.close.shape
    days = pd.DatetimeIndex(days) if days is not None else pd.date_range(M.index[0].floor("D"), M.index[-1].floor("D"), freq="D")      # a cost row every day
    leg = np.full((len(days), k), 6.5) if legs is None else legs
    one = np.ones((len(days), k))
    rate = np.where(np.arange(n)[:, None] % 96 == 0, 0.5, 0.0) * np.ones((1, k))
    return bt.Costs(days, leg, one * 0, one, np.cumsum(rate, axis=0), np.cumsum(rate * M.close.to_numpy(), axis=0))


def _events(t0s, path):
    L = pd.DataFrame({"venue": ["bithumb"] * 6 + ["upbit"] * 2, "market": [f"KRW-{s[:3]}" for s in EV], "symbol": EV, "base": [s[:3] for s in EV], "mult": 1.0,
                      "t0": t0s, "ts_known": [t + pd.Timedelta("1h") for t in t0s], "fold": ["F1"] * 4 + ["F2"] * 4, "perp_first": D("2022-01-01"), "perp_first_source": "archive 5m", "perp_age_days": 500,
                      "first_korean": [True] * 6 + [False] * 2, "other_venue_t0": pd.NaT, "member_at_t0": [True, False] * 4})
    L.to_csv(path, index=False)
    return L


def test_the_entry_is_the_bar_after_the_hour_and_the_calendar_cuts_what_the_market_cannot_hold():
    M, t0s = _market(weeks=4)
    L = pd.DataFrame({"symbol": ["EV1USDT", "EV2USDT", "EV3USDT", "GONEUSDT", "EV4USDT"], "t0": [t0s[0], t0s[1], t0s[2], t0s[0], D("2023-06-04 20:00")]})
    E = krevent.entries(M, L, end=M.index[-1] + BAR, first_block=M.index[0], longest=2016).set_index("symbol")
    assert E.loc["EV1USDT", "t"] == t0s[0] + pd.Timedelta("60min") and M.index[E.loc["EV1USDT", "row"]] == E.loc["EV1USDT", "t"] and E.loc["EV1USDT", "eligible"]
    assert M.index[E.loc["EV1USDT", "row"] + bt.LATENCY] == t0s[0] + pd.Timedelta("65min")                                 # entered 65 minutes after the venue's first bar
    assert E.loc["EV3USDT", "why"] == "the 7-day exit is not before the end" and E.loc["GONEUSDT", "why"] == "no bars of the name in the market"
    assert E.loc["EV4USDT", "why"] == "the decision bar is not in the market"                                              # t0 + 60 min is before the market's first bar
    early = krevent.entries(M, L.iloc[:1], end=M.index[-1] + BAR, first_block=t0s[0] + pd.Timedelta("2h"), longest=2016)
    assert early["why"].iloc[0] == "before F1's first member block"
    M2 = bt.Market(M.close.copy(), M.high, M.low, M.dv)
    M2.close.iloc[M.index.get_loc(t0s[1] + pd.Timedelta("65min")), 1] = np.nan
    assert krevent.entries(M2, L.iloc[1:2], end=M.index[-1] + BAR, first_block=M.index[0], longest=288)["why"].iloc[0] == "no close at the decision or entry bar"


def test_the_bar_is_the_names_own_doubled_round_trip_with_the_fallback_and_r28s_constant():
    M, t0s = _market(weeks=2)
    days = pd.date_range("2023-06-01", "2023-06-20", freq="D", tz="UTC")
    legs = np.full((len(days), M.close.shape[1]), 6.5)
    legs[days.get_loc(D("2023-06-09")), 0] = 10.0                                                                      # EV1 on its entry day: 2 × 2 × (5 + 10) = 60
    legs[days.get_loc(D("2023-06-07")):days.get_loc(D("2023-06-09")) + 1, 1] = np.nan                                  # EV2 has no row that day nor the two before …
    legs[days.get_loc(D("2023-06-06")), 1] = 8.0                                                                       # … its last within 7 days: 2 × 2 × 13 = 52
    legs[:, 2] = np.nan                                                                                                # EV3 never: R28's 46
    legs[days.get_loc(D("2023-06-01")), 2] = 7.0                                                                       # a row 8 days before is too old
    C = _costs(M, days, legs)
    t = pd.DatetimeIndex([D("2023-06-09 08:00")] * 3)
    b = krevent.bars_per_event(C, np.array([0, 1, 2]), t)
    assert b["B_i"].tolist() == [60.0, 52.0, 46.0] and b["B_source"].tolist() == ["own day", "within 7 d", "R28's 46"]
    assert b["cost_day"].tolist()[:2] == [D("2023-06-09"), D("2023-06-06")]


def test_the_gate_reads_the_negative_sign_and_records_the_opposite_one():
    v = krevent.hold_verdict
    assert v(-300, 100, -3.0, 0.01, -350, -250, -280, 50) == "CLEARS"
    assert v(+300, 100, +3.0, 0.01, +350, +250, +280, 50) == "CLEARS WITH THE OPPOSITE SIGN"
    assert v(-300, 100, -3.0, 0.06, -350, -250, -280, 50) == "NOT DETECTABLE"                                           # the family-wise p
    assert v(-300, 100, -3.0, 0.01, -600, +20, -280, 50) == "NOT DETECTABLE"                                            # one fold of the other sign
    assert v(-300, 100, -3.0, 0.01, -350, -250, -30, 50) == "NOT DETECTABLE"                                            # six events made it
    assert v(-150, 100, -1.5, 0.3, -150, -150, -150, 50) == "NOT DETECTABLE" and v(5, 10, 0.5, 0.8, 5, 5, 5, 50) == "under the bar"
    fam = pd.DataFrame({"hold": ["1d", "3d", "7d"], "u": [-2.5, -3.1, -1.0], "verdict": ["CLEARS", "CLEARS", "NOT DETECTABLE"]})
    assert krevent.family_verdict(fam) == ("CLEARS", "3d")
    fam["verdict"] = ["under the bar"] * 3
    assert krevent.family_verdict(fam) == ("CLOSED", None)
    fam["verdict"] = ["under the bar", "NOT DETECTABLE", "under the bar"]
    assert krevent.family_verdict(fam) == ("NOT DETECTABLE", None)
    fam["verdict"] = ["NOT DETECTABLE", "CLEARS WITH THE OPPOSITE SIGN", "NOT DETECTABLE"]
    assert krevent.family_verdict(fam) == ("CLEARS WITH THE OPPOSITE SIGN", "3d")


def _plant(tmp_path, monkeypatch, M, t0s, C):
    monkeypatch.chdir(tmp_path)
    lst = tmp_path / "krlistings_f12.csv"
    L = _events(t0s, lst)
    monkeypatch.setattr(krevent, "OUT", tmp_path / "output" / "listing")
    monkeypatch.setattr(krevent, "LIST", lst)
    monkeypatch.setattr(krevent, "LIST_MD5", hashlib.md5(lst.read_bytes()).hexdigest())
    monkeypatch.setattr(krevent, "LIST_ROWS", len(L))
    monkeypatch.setattr(krevent, "FP_BEFORE", tmp_path / "output" / "listing" / "fp_before.csv")
    monkeypatch.setattr(krevent, "FP_CHECK", tmp_path / "output" / "listing" / "fp_check.json")
    monkeypatch.setattr(krevent, "HL_AUDIT", tmp_path / "none.json")
    monkeypatch.setattr(krevent, "MIN_ELIGIBLE", 5)
    monkeypatch.setattr(krevent, "MIN_MEMBERS", 3)
    monkeypatch.setattr(krevent, "DRAWS", 2000)
    monkeypatch.setattr(listing, "window", lambda folds: (M.index[0], M.index[-1] + BAR))
    mem = pd.DataFrame({"block": [M.index[0].floor("D")] * len(MEM), "symbol": MEM})
    monkeypatch.setattr(universe, "members", lambda path=None, hindsight=None: mem)
    monkeypatch.setattr(universe, "screen_symbols", lambda path=None: MEM)
    monkeypatch.setattr(bt, "market", lambda syms, end, start=None, needs=(): M)
    monkeypatch.setattr(bt, "load_costs", lambda index, cols, end, cost_mult=1.0, close=None: C)
    today = L.assign(why="eligible")
    monkeypatch.setattr(krlist, "events", lambda write=True: today)
    (tmp_path / "output" / "listing").mkdir(parents=True)
    (tmp_path / "output" / "listing" / "fp_before.csv").write_text("symbol,rows\n")
    return L, today


def test_a_planted_give_back_is_found_negative_with_the_pump_in_the_run_up_row_and_the_splits_apart(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    L, today = _plant(tmp_path, monkeypatch, M, t0s, C)
    text = krevent.run("t")
    out = tmp_path / "output" / "listing" / "t"
    V = json.loads((out / "validity.json").read_text())
    assert V["status"] == "PASS" and V["2_rederived"]["status"] == "PASS" and V["7_t_equals_ts_known"] and V["3_eligible"] == 8 and V["3_own_cost_row_share"] == 1.0
    assert max(max(v) for v in V["6_identity_max_abs_diff"].values()) <= 1e-9                                            # the label is horizon's and the harness's
    fam = pd.read_csv(out / "holds.csv").set_index("hold")
    assert fam.loc["1d", "M"] < -300 and fam.loc["1d", "verdict"] == "CLEARS" and fam.loc["1d", "B"] == pytest.approx(2 * 2 * (5 + 6.5))     # the planted −4 % over the day after the entry, against flat members
    assert fam.loc["7d", "M"] < 0 and fam.loc["7d", "se"] > fam.loc["1d", "se"]                                           # the give-back stays in the longer holds; their noise grows
    ru = pd.read_csv(out / "runup.csv").set_index("group")
    assert ru.loc["all", "median"] > 600 and ru.loc["all", "share_ge_500"] == 1.0                                        # the planted +8 % over the day before t0
    assert set(ru.index) >= {"first_korean = first listing", "first_korean = second venue", "venue = bithumb", "venue = upbit", "member_at_t0 = member at t0"}
    sp = pd.read_csv(out / "splits.csv")
    assert sp[(sp["split"] == "first_korean") & (sp["hold"] == "1d")].set_index("group")["n"].to_dict() == {"first listing": 6, "second venue": 2}
    assert sp[(sp["split"] == "venue") & (sp["hold"] == "1d")].set_index("group")["n"].to_dict() == {"bithumb": 6, "upbit": 2}
    E = pd.read_csv(out / "events.csv")
    assert (pd.to_datetime(E["t"], utc=True) == pd.to_datetime(E["ts_known"], utc=True)).all() and (E["B_source"] == "own day").all()
    assert "Verdict: CLEARS" in text and "the candidate hold 1d" in text and "Hyperliquid" in text
    meta = json.loads((out / "meta.json").read_text())
    assert meta["seed"] == 70 and meta["holds"] == [288, 864, 2016] and meta["verdict"] == "CLEARS"


def test_a_frozen_t0_the_parquets_no_longer_give_voids_the_run_and_an_unregistered_list_too(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    L, today = _plant(tmp_path, monkeypatch, M, t0s, C)
    moved = today.copy()
    moved.loc[0, "t0"] = moved.loc[0, "t0"] + pd.Timedelta("1h")
    monkeypatch.setattr(krlist, "events", lambda write=True: moved)
    text = krevent.run("v")
    V = json.loads((tmp_path / "output" / "listing" / "v" / "validity.json").read_text())
    assert "**VOID" in text and V["status"] == "FAIL" and V["2_rederived"]["bad"][0]["why"] == "t0 differs"
    monkeypatch.setattr(krlist, "events", lambda write=True: today)
    monkeypatch.setattr(krevent, "LIST_MD5", "0" * 32)
    assert "**VOID" in krevent.run("w")


def test_the_fingerprint_check_writes_its_verdict_and_fails_on_a_changed_name(tmp_path, monkeypatch):
    monkeypatch.setattr(krevent, "FP_BEFORE", tmp_path / "fp_before.csv")
    monkeypatch.setattr(krevent, "FP_CHECK", tmp_path / "fp_check.json")
    monkeypatch.setattr(krevent, "OUT", tmp_path)
    before = pd.DataFrame({"symbol": ["A", "B"], "rows": [10, 20], "first": [D("2023-01-01")] * 2, "last": [D("2023-02-01")] * 2, "sum_close": [1.5, 2.5], "sum_volume": [10.0, 20.0]})
    before.to_csv(krevent.FP_BEFORE, index=False)
    (tmp_path / "r70").mkdir()
    (tmp_path / "r70" / "validity.json").write_text(json.dumps({"status": "PASS"}))
    monkeypatch.setattr(krlist, "fingerprint", lambda extent=None: before.copy())
    r = krevent.check()
    assert r["status"] == "PASS" and json.loads(krevent.FP_CHECK.read_text())["pass"] and json.loads((tmp_path / "r70" / "validity.json").read_text())["1_fingerprint_after"] == "PASS"
    monkeypatch.setattr(krlist, "fingerprint", lambda extent=None: before.assign(rows=[10, 21]))                     # one row more on B: a changed name
    r = krevent.check()
    assert r["status"] == "FAIL" and r["changed"][0]["symbol"] == "B"
    with pytest.raises(SystemExit):
        krevent.main("check")


# ---- R71: the confirmation read — R29's path on the frozen F3+F4 list, 1 day, no stop, once --------------------------------------------
def _events34(t0s, path, described=("EV2USDT",)):
    """Eight rows plus a twin of EV1 (Upbit the same hour) → 9 rows; EV2 stands for one of the twelve (described, never a cell)."""
    L = _events(t0s, path)
    twin = L.iloc[[0]].assign(venue="upbit", market="KRW-EV1b", first_korean=False)
    L = pd.concat([L, twin], ignore_index=True)
    L["fold"] = ["F3"] * 4 + ["F4"] * 4 + ["F3"]
    L.to_csv(path, index=False)
    return L


def test_a_twin_is_one_position_and_a_name_of_the_twelve_is_not_a_cell(tmp_path):
    M, t0s = _market(weeks=2)
    L = _events34(t0s, tmp_path / "f34.csv")
    cl, twins, desc = krevent.cells(L, described=("EV2USDT",))
    assert len(cl) == 7 and len(twins) == 1 and len(desc) == 1
    assert twins.iloc[0]["venue"] == "upbit" and twins.iloc[0]["symbol"] == "EV1USDT" and cl[cl["symbol"] == "EV1USDT"]["venue"].tolist() == ["bithumb"]      # the Bithumb row kept
    assert desc.iloc[0]["symbol"] == "EV2USDT" and "EV2USDT" not in set(cl["symbol"])


def _plant34(tmp_path, monkeypatch, M, t0s, C, r70_status="PASS"):
    monkeypatch.chdir(tmp_path)
    lst = tmp_path / "krlistings_f34.csv"
    L = _events34(t0s, lst)
    (tmp_path / "output" / "listing").mkdir(parents=True)
    monkeypatch.setattr(krevent, "OUT", tmp_path / "output" / "listing")
    monkeypatch.setattr(krevent, "LIST34", lst)
    monkeypatch.setattr(krevent, "LIST34_MD5", hashlib.md5(lst.read_bytes()).hexdigest())
    monkeypatch.setattr(krevent, "LIST34_ROWS", len(L))
    monkeypatch.setattr(krevent, "DESCRIBED", ("EV2USDT",))
    monkeypatch.setattr(krevent, "R70_CHECK", tmp_path / "output" / "listing" / "r71_r70_check.json")
    krevent.R70_CHECK.write_text(json.dumps({"status": r70_status}))
    for tag in ("c", "d", "e"):
        (tmp_path / "output" / "listing" / f"{tag}_fingerprint_before.csv").write_text("symbol,rows\n")     # the fingerprint files carry the run's name
    monkeypatch.setattr(krevent, "MIN_CONFIRM", 5)
    monkeypatch.setattr(krevent, "MIN_MEMBERS", 3)
    monkeypatch.setattr(krevent, "DRAWS", 2000)
    monkeypatch.setattr(listing, "window", lambda folds: (M.index[0], M.index[-1] + BAR))
    mem = pd.DataFrame({"block": [M.index[0].floor("D")] * len(MEM), "symbol": MEM})
    monkeypatch.setattr(universe, "members", lambda path=None, hindsight=None: mem)
    monkeypatch.setattr(universe, "screen_symbols", lambda path=None: MEM)
    monkeypatch.setattr(bt, "market", lambda syms, end, start=None, needs=(): M)
    monkeypatch.setattr(bt, "load_costs", lambda index, cols, end, cost_mult=1.0, close=None: C)
    monkeypatch.setattr(krlist, "events", lambda write=True: L.assign(why="eligible"))
    plan = tmp_path / "PLAN.md"
    plan.write_text("### R71 — the confirmation (registered)\n")
    monkeypatch.setattr(bt, "PLAN", plan)
    monkeypatch.setattr(bt, "READS", tmp_path / "output" / "backtest" / "confirmation_reads.csv")
    return L


def test_a_planted_give_back_confirms_with_the_hedge_paid_the_entry_day_doubled_and_the_guard_before_the_market(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    L = _plant34(tmp_path, monkeypatch, M, t0s, C)
    loaded = []
    real_market = bt.market
    def market(syms, end, start=None, needs=()):
        loaded.append(pd.read_csv(bt.READS)["registration"].tolist())              # the ledger holds the guard rows when the market is asked for
        return real_market(syms, end, start, needs)
    monkeypatch.setattr(bt, "market", market)
    text = krevent.confirm("R71", "c")
    out = tmp_path / "output" / "listing" / "c"
    assert loaded == [["R71", "R71"]] and pd.read_csv(bt.READS)["fold"].tolist() == ["F3", "F4"]
    V = json.loads((out / "validity.json").read_text())
    assert V["status"] == "PASS" and V["2_cells"] == 7 and len(V["2_twins_dropped"]) == 1 and len(V["2_described_not_cells"]) == 1 and V["4_eligible"] == 7 and V["5_H_share"] == 1.0
    assert max(v for v in V["6_identity_max_abs_diff"].values() if not isinstance(v, bool)) <= 1e-9 and V["7_no_stop"] and V["7_t_equals_ts_known"]
    N = json.loads((out / "confirm.json").read_text())
    assert N["verdict"] == "CONFIRMED" and N["M"] > 150 and N["se"] == max(N["se_bootstrap"], N["se_week"]) and N["M_heavy"] > 0 and N["M_heavy"] < N["M"]
    T = pd.read_csv(out / "trades.csv")
    assert len(T) == 7 and (~T["stopped"]).all() and ((T["x"] - T["e"]) == 288).all()
    assert np.allclose(T["leg_entry"], 2 * 6.5) and np.allclose(T["leg_exit"], 6.5)                                     # the entry day's legs doubled, the exit at the proxy
    assert (T["hedge_cost"] > 0).all() and np.allclose(T["H"], T["own"] + T["hedge"])
    assert "runup_y" in T and (T["runup_y"] > 300).mean() > 0.8 and "y_1d" in T                                           # the described columns
    assert "Verdict: CONFIRMED" in text and "EV2USDT" in text and "KRW-EV1b" in text
    with pytest.raises(SystemExit):                                                                                       # a second read of the folds is refused by the ledger
        krevent.confirm("R71", "c2")
    assert not (tmp_path / "output" / "listing" / "c2" / "confirm.json").exists()


def test_a_cell_without_a_cost_row_is_counted_not_priced_and_a_missing_recheck_voids(tmp_path, monkeypatch):
    M, t0s = _market()
    days = pd.date_range(M.index[0].floor("D"), M.index[-1].floor("D"), freq="D", tz="UTC")
    legs = np.full((len(days), M.close.shape[1]), 6.5)
    legs[:, 2] = np.nan                                                                                                   # EV3 has no cost row at all
    C = _costs(M, days, legs)
    _plant34(tmp_path, monkeypatch, M, t0s, C)
    monkeypatch.setattr(krevent, "MIN_H_SHARE", 0.5)
    krevent.confirm("R71", "d")
    V = json.loads((tmp_path / "output" / "listing" / "d" / "validity.json").read_text())
    assert V["status"] == "PASS" and V["5_unpriced"] == ["EV3USDT"] and abs(V["5_H_share"] - 6 / 7) < 1e-9
    T = pd.read_csv(tmp_path / "output" / "listing" / "d" / "trades.csv")
    assert T.loc[T["contract"] == "EV3USDT", "H"].isna().all() and json.loads((tmp_path / "output" / "listing" / "d" / "confirm.json").read_text())["n"] == 6
    # a recheck that did not pass voids the read, after the guard
    monkeypatch.setattr(bt, "READS", tmp_path / "output" / "backtest" / "reads2.csv")
    krevent.R70_CHECK.write_text(json.dumps({"status": "FAIL"}))
    text = krevent.confirm("R71", "e")
    assert "**VOID" in text and json.loads((tmp_path / "output" / "listing" / "e" / "validity.json").read_text())["3_r70_recheck"] == "FAIL"


def test_the_recheck_reproduces_r70s_pricing_through_the_confirmations_path(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    L, today = _plant(tmp_path, monkeypatch, M, t0s, C)
    monkeypatch.setattr(krevent, "R70_DIR", tmp_path / "output" / "listing" / "r70")
    monkeypatch.setattr(krevent, "R70_CHECK", tmp_path / "output" / "listing" / "r71_r70_check.json")
    krevent.run("r70")                                                                                                   # R70's own events.csv is the reference
    P = listing._priced(M, C, pd.read_csv(tmp_path / "output" / "listing" / "r70" / "events.csv").rename(columns={"symbol": "contract"}).assign(t=lambda d: pd.to_datetime(d["t"], utc=True)), 288, -1, 5.0)
    monkeypatch.setattr(krevent, "R70_SOLD_X1_NET", round(float(P["net_bps"].mean()), 1))
    r = krevent.recheck()
    assert r["status"] == "PASS" and r["own_vs_r70_priced_max_abs"] <= 1e-9 and r["gross_funding_vs_minus_a_1d_max_abs"] <= 1e-9 and r["a_1d_rows_matched"] == 8
    monkeypatch.setattr(krevent, "R70_SOLD_X1_NET", round(float(P["net_bps"].mean()), 1) + 1.0)
    assert krevent.recheck()["status"] == "FAIL"


def test_a_re_execution_needs_the_plans_tag_and_a_first_read_and_is_logged_beside_it(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    _plant34(tmp_path, monkeypatch, M, t0s, C)
    with pytest.raises(SystemExit):                                                                                       # no first read yet: nothing to re-execute
        krevent.confirm("R71", "x", reexecute="costs")
    krevent.confirm("R71", "c")
    with pytest.raises(SystemExit):                                                                                       # the plan does not name the tag
        krevent.confirm("R71", "x", reexecute="costs")
    bt.PLAN.write_text(bt.PLAN.read_text() + "re-execution `costs`: the cost rows\n")
    for tag in ("x",):
        (tmp_path / "output" / "listing" / f"{tag}_fingerprint_before.csv").write_text("symbol,rows\n")
    text = krevent.confirm("R71", "x", reexecute="costs")
    assert "Verdict: CONFIRMED" in text
    r = pd.read_csv(bt.READS)
    assert r["registration"].tolist() == ["R71", "R71", "R71/costs", "R71/costs"] and json.loads((tmp_path / "output" / "listing" / "x" / "meta.json").read_text())["registration"] == "R71/costs"
    with pytest.raises(SystemExit):                                                                                       # once per tag
        krevent.confirm("R71", "y", reexecute="costs")
