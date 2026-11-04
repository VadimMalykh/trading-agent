"""R80 (`ft2/upgevent.py`) on planted bars, no network: the decision bar is the first 5m bar closing after the upgrade's stated time, on and
off the 5-minute grid, and the position enters one bar later; the twelve's row is described and a row past the market's end is dropped by
the calendar and counted; a planted run-up from the notice and give-back after the hour is found NEGATIVE by the trimmed gate with the INTO
row showing the run-up; a planted run-on in one cell moves the plain mean and not the trimmed one; the label identity with `horizon.labels`
and the harness and the trimmed identity; validity (2), (3) and (7) read; the family-wise p over the three holds."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt
from ft2 import krevent, listing, universe, upgevent, upgrades

D = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
BAR = pd.Timedelta("5min")
EV = ["EV1USDT", "EV2USDT", "EV3USDT", "EV4USDT", "EV5USDT", "EV6USDT", "EV7USDT", "EV8USDT", "ETHUSDT"]
MEM = ["M1USDT", "M2USDT", "M3USDT", "M4USDT", "M5USDT"]
LEAD = pd.Timedelta(hours=36)


def _t0s(idx, n=len(EV)):
    """Nine stated times, 07:03 (off the grid) and 07:00 (on it) alternately, every ninth day — except EV8's (the eighth), on day 108 of a 16-week
    (112-day) market: its 7-day exit past the end, dropped by the calendar; ETHUSDT's (the ninth) on day 76, inside."""
    days = [4, 13, 22, 31, 40, 49, 58, 108, 76]
    return [idx[0].floor("D") + pd.Timedelta(days=d, hours=7, minutes=3 if k % 2 == 0 else 0) for k, d in enumerate(days[:n])]


def _market(weeks=16, seed=0, runup=0.06, giveback=-0.04, runon=None, names=EV):
    """Sixteen weeks of 5m bars; the event names run up from the notice (t0 − 36 h) to the hour and give it back over the day after the entry."""
    rng = np.random.default_rng(seed)
    n = weeks * 7 * 288
    idx = pd.date_range("2023-06-05 00:05", periods=n, freq="5min", tz="UTC", name="t")
    cols = [*names, *MEM, "BTCUSDT"]
    r = rng.normal(0, 0.0005, (n, len(cols)))                                                              # 0.85 % a day: the planted ±4 % stands above the noise of seven cells
    t0s = _t0s(idx, len(names))
    for j, t0 in enumerate(t0s):
        if t0 + pd.Timedelta(days=2) > idx[-1]:
            continue
        i0 = idx.get_loc(upgevent.decision_close(t0))                                             # the decision row
        i_in = idx.get_loc(upgevent.decision_close(t0 - LEAD)) + bt.LATENCY                        # the INTO row's entry row
        r[i_in + 1:i0 + 1, j] += runup / (i0 - i_in)                                                # the run-up: from the bar after the INTO entry to the decision bar
        g = giveback if runon is None or j not in runon else runon[j]
        r[i0 + 2:i0 + 2 + 288, j] += g / 288                                                        # the day after the entry (the entry at i0 + latency)
    close = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=cols)
    dv = pd.DataFrame(1e6, index=idx, columns=cols)
    return bt.Market(close, close * 1.001, close * 0.999, dv), t0s


def _costs(M):
    n, k = M.close.shape
    days = pd.date_range(M.index[0].floor("D"), M.index[-1].floor("D"), freq="D")
    leg = np.full((len(days), k), 6.5)
    one = np.ones((len(days), k))
    rate = np.where(np.arange(n)[:, None] % 96 == 0, 0.5, 0.0) * np.ones((1, k))
    return bt.Costs(days, leg, one * 0, one, np.cumsum(rate, axis=0), np.cumsum(rate * M.close.to_numpy(), axis=0))


def _events(t0s, path, names=EV, folds=("F1",) * 4 + ("F2",) * 5):
    EV = names
    L = pd.DataFrame({"symbol": EV, "base": [s[:-4] for s in EV], "mult": 1.0, "t0": t0s, "ts_known": [t - LEAD for t in t0s], "release": [t - LEAD for t in t0s],
                      "code": [f"c{k}" for k in range(len(EV))], "fold": list(folds), "block": D("2023-06-05"), "perp_first": D("2022-01-01"), "perp_first_source": "archive 5m",
                      "perp_age_days": 500, "member_at_t0": [True, False] * 4 + [True], "lead_d": 1.5, "hardfork": [True, False] * 4 + [True], "multi": [False] * 7 + [True, True],
                      "repeat_n": [0, 0, 0, 1, 1, 1, 2, 2, 0], "t_suspend": [t - pd.Timedelta(hours=1) for t in t0s[:6]] + [pd.NaT] * 3, "stated_how": "upgrade_sentence",
                      "title_date": pd.NaT, "title": [f"Binance Will Support the {s[:-4]} ({s[:-4]}) Network Upgrade" for s in EV]})[upgrades.LIST_COLS]
    L.to_csv(path, index=False)
    return L


def _plant(tmp_path, monkeypatch, M, t0s, C, name="t"):
    monkeypatch.chdir(tmp_path)
    lst = tmp_path / "upgrades_f12.csv"
    L = _events(t0s, lst)
    out = tmp_path / "output" / "listing"
    monkeypatch.setattr(upgevent, "OUT", out)
    monkeypatch.setattr(krevent, "OUT", out)
    monkeypatch.setattr(upgevent, "LIST", lst)
    monkeypatch.setattr(upgevent, "LIST_MD5", hashlib.md5(lst.read_bytes()).hexdigest())
    monkeypatch.setattr(upgevent, "LIST_ROWS", len(L))
    monkeypatch.setattr(upgevent, "MIN_ELIGIBLE", 6)
    monkeypatch.setattr(upgevent, "MIN_MEMBERS", 3)
    monkeypatch.setattr(upgevent, "DRAWS", 2000)
    monkeypatch.setattr(upgevent, "EXPECTED_DESCRIBED", {("ETHUSDT", str(t0s[8]))})
    monkeypatch.setattr(upgevent, "EXPECTED_DROPPED", {("EV8USDT", str(t0s[7]))})
    monkeypatch.setattr(listing, "window", lambda folds: (M.index[0], M.index[-1] + BAR))
    mem = pd.DataFrame({"block": [M.index[0].floor("D")] * len(MEM), "symbol": MEM})
    monkeypatch.setattr(universe, "members", lambda path=None, hindsight=None: mem)
    monkeypatch.setattr(universe, "screen_symbols", lambda path=None: MEM)
    monkeypatch.setattr(bt, "market", lambda syms, end, start=None, needs=(): M)
    monkeypatch.setattr(bt, "load_costs", lambda index, cols, end, cost_mult=1.0, close=None: C)
    today = L.assign(why="eligible")
    monkeypatch.setattr(upgrades, "events", lambda write=True: today)
    out.mkdir(parents=True)
    krevent.fp_paths(name)[0].write_text("symbol,rows\n")
    return L, today


def test_the_decision_bar_is_the_first_bar_closing_after_the_stated_time_and_the_rows_out_are_named():
    assert upgevent.decision_close(D("2024-03-13 13:55")) == D("2024-03-13 14:00") and upgevent.decision_close(D("2024-03-13 13:57")) == D("2024-03-13 14:00")
    assert upgevent.decision_close(D("2024-03-13 14:00")) == D("2024-03-13 14:05")                                    # strictly after: the bar closing AT t0 holds no trade after it
    M, t0s = _market(weeks=4)
    L = _events(t0s, "/dev/null")
    L.loc[len(L)] = L.iloc[0]
    L.loc[len(L) - 1, "symbol"] = "GONEUSDT"
    E = upgevent.entries(M, L, end=M.index[-1] + BAR, first_block=M.index[0]).set_index(["symbol", "t0"])
    e1 = E.loc[("EV1USDT", t0s[0])]
    assert e1["t"] == t0s[0].floor("5min") + BAR and M.index[e1["row"]] == e1["t"] and e1["eligible"] and (e1["t"] - t0s[0]) < BAR    # 07:03 → the bar closing 07:05
    e2 = E.loc[("EV2USDT", t0s[1])]
    assert e2["t"] == t0s[1] + BAR and e2["eligible"]                                                                 # 07:00 → the bar closing 07:05
    assert M.index[e1["row"] + bt.LATENCY] == e1["t"] + BAR                                                           # the entry one bar later
    assert M.index[e1["row_into"]] == upgevent.decision_close(t0s[0] - LEAD)                                           # the INTO row's decision bar: the first bar closing after the notice
    assert E.loc[("ETHUSDT", t0s[8]), "why"] == "the decision bar is not in the market"                                 # the ninth event lies past a 4-week market
    assert E.loc[("EV3USDT", t0s[2]), "why"] == "the 7-day exit is not before the end" and E.loc[("GONEUSDT", t0s[0]), "why"] == "no bars of the name in the market"


def test_a_planted_run_up_and_give_back_is_found_negative_by_the_trimmed_gate_with_the_into_row_showing_the_run_up(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    L, today = _plant(tmp_path, monkeypatch, M, t0s, C)
    text = upgevent.run("t")
    out = tmp_path / "output" / "listing" / "t"
    V = json.loads((out / "validity.json").read_text())
    assert V["status"] == "PASS" and V["2_rederived"]["status"] == "PASS" and V["3_cells"] == 7 and V["3_described_as_registered"] and V["3_dropped_as_registered"]
    assert V["7_decision_after_t0"] and V["7_decision_after_release"] and V["7_into_entry_after_release"] and V["7_decision_within_5min_of_t0"]
    assert max(max(v) for v in V["6_identity_max_abs_diff"].values()) <= 1e-9 and V["6_trimmed_identity_max"] <= 1e-9
    fam = pd.read_csv(out / "holds.csv").set_index("hold")
    assert fam.loc["1d", "M_trim"] < -300 and fam.loc["1d", "verdict"] == "CLEARS" and fam.loc["1d", "k_trim"] == 1 and fam.loc["1d", "B"] == pytest.approx(2 * 2 * (5 + 6.5))
    assert 0 <= fam.loc["1d", "p_fw_trim"] <= 1 and fam.loc["7d", "se_trim"] > fam.loc["1d", "se_trim"]
    ru = pd.read_csv(out / "runup.csv").set_index("group")
    assert ru.loc["INTO row: all", "median"] > 400 and ru.loc["INTO row: all", "share_above_0"] == 1.0 and ru.loc["INTO row: all", "median_days"] == pytest.approx(1.5, abs=0.01)
    assert ru.loc["run-up t0 − 24 h: all", "median"] > 200                                                           # the last day of the 1.5-day run-up
    assert "INTO row: hardfork = hard fork" in ru.index and "run-up: first = first notice" in ru.index
    sp = pd.read_csv(out / "splits.csv")
    assert sp[(sp["split"] == "hardfork") & (sp["hold"] == "1d")].set_index("group")["n"].to_dict() == {"hard fork": 4, "upgrade only": 3}
    assert set(sp[sp["split"] == "fold"]["group"]) == {"F1", "F2"}
    ref = pd.read_csv(out / "holds.csv")
    E = pd.read_csv(out / "events.csv")
    assert (E["B_source"] == "own day").all() and E["y_suspend_1d"].notna().sum() == 6 and len(E) == 7
    dr = pd.read_csv(out / "described_rows.csv")
    assert list(dr["symbol"]) == ["ETHUSDT"] and np.isfinite(dr["y_1d"]).all()
    assert "Verdict: CLEARS" in text and "the candidate hold 1d" in text and "a run-up to give back exists" in text
    meta = json.loads((out / "meta.json").read_text())
    assert meta["seed"] == 80 and meta["holds"] == [288, 864, 2016] and meta["verdict"] == "CLEARS" and meta["trim_frac"] == 0.05


def test_a_run_on_in_one_cell_moves_the_plain_mean_and_not_the_trimmed_one(tmp_path, monkeypatch):
    M, t0s = _market(runon={2: 0.40})                                                                                 # EV3 runs ON by 40 % after the hour
    C = _costs(M)
    _plant(tmp_path, monkeypatch, M, t0s, C)
    upgevent.run("t")
    fam = pd.read_csv(tmp_path / "output" / "listing" / "t" / "holds.csv").set_index("hold")
    assert fam.loc["1d", "M"] > fam.loc["1d", "M_trim"] + 300 and fam.loc["1d", "M_trim"] < -300                     # the plain mean carried by one cell; the trimmed reads the typical one
    assert fam.loc["1d", "k_trim"] == 1 and fam.loc["1d", "trim_identity"] < 1e-6                                     # (no verdict asserted: on seven cells a draw that doubles the run-on week leaves one copy in, and se_trim says so)


def test_a_moved_t0_an_unregistered_list_or_an_unexpected_drop_voids_the_run(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    L, today = _plant(tmp_path, monkeypatch, M, t0s, C)
    moved = today.copy()
    moved.loc[0, "t0"] = moved.loc[0, "t0"] + pd.Timedelta("1h")
    monkeypatch.setattr(upgrades, "events", lambda write=True: moved)
    text = upgevent.run("t")
    V = json.loads((tmp_path / "output" / "listing" / "t" / "validity.json").read_text())
    assert "**VOID" in text and V["status"] == "FAIL" and V["2_rederived"]["bad"][0]["why"] == "t0 differs"
    monkeypatch.setattr(upgrades, "events", lambda write=True: today)
    monkeypatch.setattr(upgevent, "EXPECTED_DROPPED", set())
    assert "**VOID" in upgevent.run("t")
    monkeypatch.setattr(upgevent, "EXPECTED_DROPPED", {("EV8USDT", str(t0s[7]))})
    monkeypatch.setattr(upgevent, "LIST_MD5", "0" * 32)
    assert "**VOID" in upgevent.run("t")
    with pytest.raises(SystemExit):
        upgevent.main("run", "t")


# ---- R81: the confirmation on the frozen F3+F4 list (decision CE1) — R80's path with the Spec swapped --------------------------------
EV81 = ["EV1USDT", "EV2USDT", "EV3USDT", "EV4USDT", "EV5USDT", "EV6USDT", "ADAUSDT", "EV8USDT", "ETHUSDT"]       # ADA and ETH the twelve's (described), EV8 past the end (dropped)


def _plant81(tmp_path, monkeypatch, M, t0s, C, name="t81"):
    monkeypatch.chdir(tmp_path)
    lst = tmp_path / "upgrades_f34.csv"
    L = _events(t0s, lst, names=EV81, folds=("F3",) * 3 + ("F4",) * 6)
    out = tmp_path / "output" / "listing"
    monkeypatch.setattr(upgevent, "OUT", out)
    monkeypatch.setattr(krevent, "OUT", out)
    monkeypatch.setattr(upgevent, "LIST34", lst)
    monkeypatch.setattr(upgevent, "LIST34_MD5", hashlib.md5(lst.read_bytes()).hexdigest())
    monkeypatch.setattr(upgevent, "LIST34_ROWS", len(L))
    monkeypatch.setattr(upgevent, "MIN_ELIGIBLE81", 5)
    monkeypatch.setattr(upgevent, "MIN_MEMBERS", 3)
    monkeypatch.setattr(upgevent, "DRAWS", 2000)
    monkeypatch.setattr(upgevent, "EXPECTED_DESCRIBED34", {("ADAUSDT", str(t0s[6])), ("ETHUSDT", str(t0s[8]))})
    monkeypatch.setattr(upgevent, "EXPECTED_DROPPED34", {("EV8USDT", str(t0s[7]))})
    monkeypatch.setattr(listing, "window", lambda folds: (M.index[0], M.index[-1] + BAR))
    mem = pd.DataFrame({"block": [M.index[0].floor("D")] * len(MEM), "symbol": MEM})
    monkeypatch.setattr(universe, "members", lambda path=None, hindsight=None: mem)
    monkeypatch.setattr(universe, "screen_symbols", lambda path=None: MEM)
    monkeypatch.setattr(bt, "market", lambda syms, end, start=None, needs=(): M)
    monkeypatch.setattr(bt, "load_costs", lambda index, cols, end, cost_mult=1.0, close=None: C)
    monkeypatch.setattr(bt, "READS", tmp_path / "confirmation_reads.csv")
    guarded = []
    monkeypatch.setattr(bt, "_guard", lambda folds, registration, reexecute=None: (guarded.append((tuple(folds), registration)), list(folds))[1])
    today = L.assign(why="eligible")
    monkeypatch.setattr(upgrades, "events", lambda write=True: today)
    out.mkdir(parents=True)
    krevent.fp_paths(name)[0].write_text("symbol,rows\n")
    return L, today, guarded


def test_r81_the_guard_rows_go_into_the_ledger_before_the_market_the_twelves_rows_are_described_and_a_planted_give_back_is_confirmed_on_the_one_hold(tmp_path, monkeypatch):
    M, t0s = _market(names=EV81)
    C = _costs(M)
    L, today, guarded = _plant81(tmp_path, monkeypatch, M, t0s, C)
    text = upgevent.run("t81", spec=upgevent.spec_r81())
    out = tmp_path / "output" / "listing" / "t81"
    V = json.loads((out / "validity.json").read_text())
    assert guarded == [(("F3", "F4"), "R81")] and V["0_guard"]["folds"] == ["F3", "F4"] and V["0_guard"]["logged_as"] == "R81"
    reads = pd.read_csv(tmp_path / "confirmation_reads.csv")
    assert list(reads["fold"]) == ["F3", "F4"] and (reads["registration"] == "R81").all() and (reads["strategy"] == "upgrade_sold_1d").all()
    assert V["status"] == "PASS" and V["3_cells"] == 6 and V["3_described_as_registered"] and V["3_dropped_as_registered"] and sorted(x[0] for x in V["3_described"]) == ["ADAUSDT", "ETHUSDT"]
    assert V["6_money_row_identity"]["sold_gross_funding_vs_minus_a"] <= 1e-9 and V["6_money_row_identity"]["hold_is_the_gate_hold"] and V["6_money_row_identity"]["no_stop"] and V["7_exits_at_or_after_end"] == 0
    fam = pd.read_csv(out / "holds.csv").set_index("hold")
    assert fam["gate"].to_dict() == {"1d": True, "3d": False, "7d": False} and {"M_trim_F3", "M_trim_F4", "M_F3", "M_F4"} <= set(fam.columns)
    assert fam.loc["1d", "M_trim"] < -300 and fam.loc["1d", "M_trim_F3"] < 0 and fam.loc["1d", "M_trim_F4"] < 0
    assert "Verdict: CONFIRMED — the gate hold 1d" in text
    meta = json.loads((out / "meta.json").read_text())
    assert meta["registration"] == "R81" and meta["decision"] == "CE1" and meta["folds"] == ["F3", "F4"] and meta["gate_holds"] == [288] and meta["seed"] == 81 and meta["verdict"] == "CONFIRMED"
    T = pd.read_csv(out / "trades.csv")
    assert len(T) == 6 and T["H"].notna().all() and (T["x"] - T["e"] == 288).all() and T["H"].mean() > 250                 # the sold unit earns the give-back less the costs and the hedge's drift
    assert "## The money row" in text and (out / "trades_heavy.csv").exists()
    dr = pd.read_csv(out / "described_rows.csv")
    assert sorted(dr["symbol"]) == ["ADAUSDT", "ETHUSDT"]
    sp = pd.read_csv(out / "splits.csv")
    assert set(sp[sp["split"] == "fold"]["group"]) == {"F3", "F4"}


def test_r81_a_planted_drift_the_other_way_is_recorded_as_the_opposite_sign_and_the_verdict_rule_is_as_registered(tmp_path, monkeypatch):
    M, t0s = _market(names=EV81, giveback=+0.04)                                                                     # the name keeps RISING after the hour: the sold unit loses
    C = _costs(M)
    _plant81(tmp_path, monkeypatch, M, t0s, C)
    text = upgevent.run("t81", spec=upgevent.spec_r81())
    meta = json.loads((tmp_path / "output" / "listing" / "t81" / "meta.json").read_text())
    assert meta["verdict"] == "NOT CONFIRMED — the opposite sign" and "NOT CONFIRMED" in text
    assert upgevent.confirm_verdict(-100, 30, -3.3, -80, -120, 46) == "CONFIRMED"
    assert upgevent.confirm_verdict(-100, 30, -3.3, -80, +5, 46) == "NOT CONFIRMED"                                   # one fold the other way
    assert upgevent.confirm_verdict(-40, 30, -1.3, -80, -120, 46) == "NOT CONFIRMED"                                   # under the bar's size, the interval not inside ±B
    assert upgevent.confirm_verdict(-10, 10, -1.0, -8, -12, 46) == "NOT CONFIRMED — under the bar"
    assert upgevent.confirm_verdict(+100, 30, 3.3, 80, 120, 46) == "NOT CONFIRMED — the opposite sign"


def test_r81_an_unregistered_list_or_an_unexpected_described_row_voids_the_run_and_the_guard_rows_stand(tmp_path, monkeypatch):
    M, t0s = _market(names=EV81)
    C = _costs(M)
    _plant81(tmp_path, monkeypatch, M, t0s, C)
    monkeypatch.setattr(upgevent, "EXPECTED_DESCRIBED34", {("ETHUSDT", str(t0s[8]))})                                  # ADA's row not expected as described
    text = upgevent.run("t81", spec=upgevent.spec_r81())
    assert "**VOID" in text and "The guard rows stand in the ledger" in text and (tmp_path / "confirmation_reads.csv").exists()
    monkeypatch.setattr(upgevent, "EXPECTED_DESCRIBED34", {("ADAUSDT", str(t0s[6])), ("ETHUSDT", str(t0s[8]))})
    monkeypatch.setattr(upgevent, "LIST34_MD5", "0" * 32)
    assert "**VOID" in upgevent.run("t81", spec=upgevent.spec_r81())
