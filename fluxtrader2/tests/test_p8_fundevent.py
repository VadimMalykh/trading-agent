"""R75 (`ft2/fundevent.py`) on planted bars, no network: the decision bar closes at t0 + 5 min and the position enters one bar later; a bar
before t0's close does not move a decision; a planted squeeze with a known carry (an hourly −0.1 % settlement on a flat price) reproduces a
to 1e-9 at every hold and y against flat members, and CLEARS with the sign POSITIVE; a planted collapse is found with the OPPOSITE sign; the
positive-funding shortenings and the lengthenings come out apart; B_i from the dearer of two days with the fallback and R28's 46; an event
whose exit passes the end is dropped and counted; the label identity with `horizon.labels`, the harness and the hand check; the family-wise
p over three holds; the guard before the market and its refusal of a second run; the fingerprint check's void."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt
from ft2 import fundevent, fundfreq, krlist, listing, universe

D = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
BAR = pd.Timedelta("5min")
H = pd.Timedelta("1h")
EV = [f"EV{k}USDT" for k in range(1, 9)]
POS, LNG = "P1USDT", "G1USDT"
MEM = ["M1USDT", "M2USDT", "M3USDT", "M4USDT", "M5USDT"]
COLS = [*EV, POS, LNG, *MEM, "BTCUSDT"]
CARRY = -0.001                                                     # the hourly rate after a shortening: the shorts pay 0.1 % an hour


def _t0s(idx, n=8):
    return [idx[0].floor("D") + pd.Timedelta(days=4 + 7 * k, hours=8) for k in range(n)]


def _market(weeks=12, seed=0, collapse=0.0):
    """Twelve weeks of 5m bars on a near-flat price (a tiny noise so that no se is zero); with `collapse`, the cells fall by that much over the day after the entry."""
    rng = np.random.default_rng(seed)
    n = weeks * 7 * 288
    idx = pd.date_range("2024-09-02 00:05", periods=n, freq="5min", tz="UTC", name="t")
    r = rng.normal(0, 2e-5, (n, len(COLS)))
    t0s = _t0s(idx)
    if collapse:
        for j, t0 in enumerate(t0s):
            i0 = idx.get_loc(t0)
            if i0 + 3 + 288 < n:
                r[i0 + 3:i0 + 3 + 288, j] += collapse / 288                                     # the day after the entry (row i0 + 1 is the decision, i0 + 2 the entry)
    close = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=COLS)
    dv = pd.DataFrame(1e6, index=idx, columns=COLS)
    return bt.Market(close, close * 1.001, close * 0.999, dv), t0s


def _settlements(t0s):
    """The archive's rows: the cells settle every 4 h at −0.03 % for two days before t0 and hourly at CARRY from t0 for eight days; the
    positive-funding shortening the same with the trailing rates positive; the lengthening hourly before and every 4 h after."""
    rows = []
    for j, t0 in enumerate(t0s):
        for name, before_rate, before_h, after_rate, after_h in ((EV[j], -0.0003, 4, CARRY, 1), (POS, +0.0003, 4, CARRY, 1), (LNG, CARRY, 1, -0.0003, 4)):
            if name != EV[j] and j != 2:                                                           # P1 and G1 have one event each, in the third week
                continue
            for k in range(1, int(48 / before_h) + 1):
                rows.append({"symbol": name, "ts": t0 - k * before_h * H, "rate": before_rate, "interval_h": before_h})
            for k in range(0, int(8 * 24 / after_h) + 1):
                rows.append({"symbol": name, "ts": t0 + k * after_h * H, "rate": after_rate, "interval_h": after_h})
    return pd.DataFrame(rows).sort_values(["symbol", "ts"]).reset_index(drop=True)


def _costs(M, S, days=None, legs=None):
    """`backtest.load_costs`' funding arrays from the planted settlements, the proxy legs 6.5 bps unless given."""
    idx, cols = M.index, list(M.columns)
    n, k = M.close.shape
    days = pd.DatetimeIndex(days) if days is not None else pd.date_range(idx[0].floor("D"), idx[-1].floor("D"), freq="D")
    leg = np.full((len(days), k), 6.5) if legs is None else legs
    one = np.ones((len(days), k))
    cum, val = np.zeros((n, k)), np.zeros((n, k))
    cl = M.close.ffill().to_numpy()
    ins = idx.tz_convert("UTC").tz_localize(None).as_unit("ns").asi8
    for j, sym in enumerate(cols):
        e = S[S["symbol"] == sym].sort_values("ts")
        if len(e):
            ts = pd.DatetimeIndex(e["ts"]).tz_convert("UTC").tz_localize(None).as_unit("ns").asi8
            rate = e["rate"].to_numpy() * 1e4
            pos = np.searchsorted(ts, ins, "right")
            cum[:, j] = np.concatenate([[0.0], np.cumsum(rate)])[pos]
            at = cl[np.clip(np.searchsorted(ins, ts, "right") - 1, 0, None), j]
            val[:, j] = np.concatenate([[0.0], np.cumsum(rate * at)])[pos]
    return bt.Costs(days, leg, one * 0, one, cum, val)


def _events(t0s, path):
    def row(sym, t0, fold, dir_, prev_h, new_h, fund_1d, member):
        return {"symbol": sym, "base": sym[:-4], "mult": 1.0, "t0": t0, "ts_known": t0, "fold": fold, "dir": dir_, "prev_h": prev_h, "new_h": new_h, "perp_first": D("2022-01-01"),
                "perp_first_source": "archive 5m", "perp_age_days": 900, "member_at_t0": member, "fund_1d": fund_1d, "fund_7d": fund_1d * 2, "n_1d": 6, "at_floor": fund_1d < 0, "cap_share_7d": 0.1,
                "batch": False, "pair_of": pd.NaT, "episode_h": np.nan, "notice_release": pd.NaT, "notice_lag_h": np.nan}
    rows = [row(EV[j], t0, "F3" if j < 4 else "F4", "shorter", 4.0, 1.0, -0.0018, j % 2 == 0) for j, t0 in enumerate(t0s)]
    rows.append(row(POS, t0s[2], "F3", "shorter", 4.0, 1.0, +0.0018, False))
    rows.append(row(LNG, t0s[2], "F3", "longer", 1.0, 4.0, -0.024, False))
    L = pd.DataFrame(rows)
    L.to_csv(path, index=False)
    return L


def _plant(tmp_path, monkeypatch, M, t0s, C, S, min_eligible=5):
    monkeypatch.chdir(tmp_path)
    lst = tmp_path / "fundfreq_f34.csv"
    L = _events(t0s, lst)
    out = tmp_path / "output" / "listing"
    out.mkdir(parents=True)
    monkeypatch.setattr(fundevent, "OUT", out)
    monkeypatch.setattr(fundevent, "LIST", lst)
    monkeypatch.setattr(fundevent, "LIST_MD5", hashlib.md5(lst.read_bytes()).hexdigest())
    monkeypatch.setattr(fundevent, "LIST_ROWS", len(L))
    monkeypatch.setattr(fundevent, "CELLS", 8)
    monkeypatch.setattr(fundevent, "MIN_ELIGIBLE", min_eligible)
    monkeypatch.setattr(fundevent, "MIN_MEMBERS", 3)
    monkeypatch.setattr(fundevent, "DRAWS", 2000)
    for tag in ("t", "u", "v", "w"):
        (out / f"{tag}_fingerprint_before.csv").write_text("symbol,rows\n")
    monkeypatch.setattr(listing, "window", lambda folds: (M.index[0], M.index[-1] + BAR))
    mem = pd.DataFrame({"block": [M.index[0].floor("D")] * len(MEM), "symbol": MEM})
    monkeypatch.setattr(universe, "members", lambda path=None, hindsight=None: mem)
    monkeypatch.setattr(universe, "screen_symbols", lambda path=None: MEM)
    monkeypatch.setattr(bt, "market", lambda syms, end, start=None, needs=(): M)
    monkeypatch.setattr(bt, "load_costs", lambda index, cols, end, cost_mult=1.0, close=None: C)
    monkeypatch.setattr(fundfreq, "settlements", lambda: S)
    plan = tmp_path / "PLAN.md"
    plan.write_text("### R75 — the exchange's squeeze flag, bought (registered)\n")
    monkeypatch.setattr(bt, "PLAN", plan)
    monkeypatch.setattr(bt, "READS", tmp_path / "output" / "backtest" / "confirmation_reads.csv")
    return L


def test_the_entry_is_the_bar_after_t0_and_the_calendar_cuts_what_the_market_cannot_hold():
    M, t0s = _market(weeks=4)
    L = pd.DataFrame({"symbol": ["EV1USDT", "EV2USDT", "EV3USDT", "GONEUSDT", "EV4USDT"], "t0": [t0s[0], t0s[1], t0s[3], t0s[0], D("2024-09-01 20:00")]})
    E = fundevent.entries(M, L, end=M.index[-1] + BAR, first_block=M.index[0]).set_index("symbol")
    assert E.loc["EV1USDT", "t"] == t0s[0] + BAR and M.index[E.loc["EV1USDT", "row"]] == E.loc["EV1USDT", "t"] and E.loc["EV1USDT", "eligible"]
    assert M.index[E.loc["EV1USDT", "row"] + bt.LATENCY] == t0s[0] + 2 * BAR                                                # entered 10 minutes after the settlement
    assert E.loc["EV3USDT", "why"] == "the 7-day exit is not before the end" and E.loc["GONEUSDT", "why"] == "no bars of the name in the market"
    assert E.loc["EV4USDT", "why"] == "the decision bar is not in the market"
    early = fundevent.entries(M, L.iloc[:1], end=M.index[-1] + BAR, first_block=t0s[0] + H)
    assert early["why"].iloc[0] == "before the first member block"
    M2 = bt.Market(M.close.copy(), M.high, M.low, M.dv)
    M2.close.iloc[M.index.get_loc(t0s[1] + 2 * BAR), 1] = np.nan
    assert fundevent.entries(M2, L.iloc[1:2], end=M.index[-1] + BAR, first_block=M.index[0], longest=288)["why"].iloc[0] == "no close at the decision or entry bar"


def test_a_bar_before_t0s_close_does_not_move_a_decision_nor_a_label():
    M, t0s = _market(weeks=6)
    S = _settlements(t0s)
    C = _costs(M, S)
    L = pd.DataFrame({"symbol": EV[:4], "t0": t0s[:4]})
    E = fundevent.entries(M, L, end=M.index[-1] + BAR, first_block=M.index[0])
    M2 = bt.Market(M.close.copy(), M.high, M.low, M.dv)
    for j, t0 in enumerate(t0s[:4]):
        i0 = M.index.get_loc(t0)
        M2.close.iloc[:i0 + 1, j] *= 3.0                                                                                  # every bar of the name closing at or before its t0 tripled
    C2 = _costs(M2, S)
    E2 = fundevent.entries(M2, L, end=M.index[-1] + BAR, first_block=M.index[0])
    assert E2[["t", "row", "why", "eligible"]].equals(E[["t", "row", "why", "eligible"]])
    rows, own = E["row"].to_numpy(), M.columns.get_indexer(E["symbol"])
    for h in fundevent.HOLDS:
        a1 = listing.label_at(M.close.to_numpy(), C.fundval, rows, h)[np.arange(4), own]
        a2 = listing.label_at(M2.close.to_numpy(), C2.fundval, rows, h)[np.arange(4), own]
        assert np.allclose(a1, a2, atol=1e-9)


def test_the_bar_is_the_dearer_of_two_days_with_the_fallback_and_r28s_constant():
    M, _ = _market(weeks=2)
    days = pd.date_range("2024-09-01", "2024-09-14", freq="D", tz="UTC")
    legs = np.full((len(days), M.close.shape[1]), 6.5)
    legs[days.get_loc(D("2024-09-06")), 0], legs[days.get_loc(D("2024-09-05")), 0] = 10.0, 12.0                             # EV1: the day before is dearer: 2 × 2 × (5 + 12) = 68
    legs[days.get_loc(D("2024-09-06")), 1], legs[days.get_loc(D("2024-09-05")), 1] = 10.0, np.nan                          # EV2: only the entry day: 60
    legs[days.get_loc(D("2024-09-03")):days.get_loc(D("2024-09-06")) + 1, 2] = np.nan                                      # EV3: neither day nor the two before …
    legs[days.get_loc(D("2024-09-02")), 2] = 8.0                                                                           # … its last within 7 days: 52
    legs[:, 3] = np.nan                                                                                                    # EV4 never: R28's 46
    C = bt.Costs(days, legs, legs * 0, np.ones_like(legs), np.zeros(M.close.shape), np.zeros(M.close.shape))
    t = pd.DatetimeIndex([D("2024-09-06 08:05")] * 4)
    b = fundevent.bars_per_event(C, np.array([0, 1, 2, 3]), t)
    assert b["B_i"].tolist() == [68.0, 60.0, 52.0, 46.0] and b["B_source"].tolist() == ["day before", "own day", "within 7 d", "R28's 46"]
    assert b["cost_day"].tolist()[:3] == [D("2024-09-05"), D("2024-09-06"), D("2024-09-02")]


def test_the_gate_reads_the_positive_sign_and_records_the_opposite_one():
    v = fundevent.hold_verdict
    assert v(+300, 100, +3.0, 0.01, +350, +250, +280, 50) == "CLEARS"
    assert v(-300, 100, -3.0, 0.01, -350, -250, -280, 50) == "CLEARS WITH THE OPPOSITE SIGN"
    assert v(+300, 100, +3.0, 0.06, +350, +250, +280, 50) == "NOT DETECTABLE"                                           # the family-wise p
    assert v(+300, 100, +3.0, 0.01, +600, -20, +280, 50) == "NOT DETECTABLE"                                            # one fold of the other sign
    assert v(+300, 100, +3.0, 0.01, +350, +250, +30, 50) == "NOT DETECTABLE"                                            # six events made it
    assert v(+150, 100, +1.5, 0.3, +150, +150, +150, 50) == "NOT DETECTABLE" and v(5, 10, 0.5, 0.8, 5, 5, 5, 50) == "under the bar"
    fam = pd.DataFrame({"hold": ["1d", "3d", "7d"], "u": [2.5, 3.1, 1.0], "verdict": ["CLEARS", "CLEARS", "NOT DETECTABLE"]})
    assert fundevent.family_verdict(fam) == ("CLEARS", "3d")


def test_the_cells_are_the_at_floor_shortenings_and_the_others_come_out_apart(tmp_path):
    M, t0s = _market(weeks=2)
    L = fundevent.load_events(_events(t0s, tmp_path / "f34.csv").pipe(lambda d: (d.to_csv(tmp_path / "f34.csv", index=False), tmp_path / "f34.csv")[1]))
    cl, pos, lng = fundevent.cells(L)
    assert cl["symbol"].tolist() == EV and pos["symbol"].tolist() == [POS] and lng["symbol"].tolist() == [LNG]
    assert (L["era"] == "notice").all() and (L["formula"] == "before 2025-09-18").all()


def test_a_planted_squeeze_reproduces_the_carry_to_1e9_and_clears_positive_with_the_guard_before_the_market(tmp_path, monkeypatch):
    M, t0s = _market()
    S = _settlements(t0s)
    C = _costs(M, S)
    _plant(tmp_path, monkeypatch, M, t0s, C, S)
    loaded = []
    real_market = bt.market
    def market(syms, end, start=None, needs=()):
        loaded.append(pd.read_csv(bt.READS)["registration"].tolist())              # the ledger holds the guard rows when the market is asked for
        return real_market(syms, end, start, needs)
    monkeypatch.setattr(bt, "market", market)
    text = fundevent.run("R75", "t")
    out = tmp_path / "output" / "listing" / "t"
    assert loaded == [["R75", "R75"]] and pd.read_csv(bt.READS)["fold"].tolist() == ["F3", "F4"]
    V = json.loads((out / "validity.json").read_text())
    assert V["status"] == "PASS" and V["2_rederived"]["status"] == "PASS" and V["2_cells_as_registered"] and V["3_eligible"] == 8 and V["3_own_cost_row_share"] == 1.0
    assert max(max(v) for v in V["6_identity_max_abs_diff"].values()) <= 1e-9 and V["6_hand_max_abs_diff"] <= 1e-9 and V["6_hand_cells"] == 8
    assert V["7_t_equals_t0_plus_5min"] and V["7_ts_known_equals_t0"] and V["8_cells_with_a_settlement_gap"] == 0 and V["8_settlements_per_cell_1d"] == {"min": 24, "median": 24.0, "max": 24}
    E = pd.read_csv(out / "events.csv")
    for h, d in ((288, "1d"), (864, "3d"), (2016, "7d")):
        carry = -CARRY * 1e4 * (h // 12)                                                                                  # 10 bps an hour on a flat price: 240 / 720 / 1,680
        tol = 10 * np.sqrt(h / 288)                                                                                        # the planted noise: sd 2e-5 a bar → ≈ 3.4 bps a day
        assert np.allclose(E[f"funding_{d}"], carry, atol=0.5 + carry * 2e-3) and np.allclose(E[f"a_{d}"], carry, atol=tol) and np.allclose(E[f"b_{d}"], 0, atol=tol) and np.allclose(E[f"y_{d}"], carry, atol=tol)
        assert (E[f"settlements_{d}"] == h // 12).all()
    hand = pd.read_csv(out / "hand_check.csv")
    assert len(hand) == 24 and (hand["diff"] <= 1e-9).all() and (hand["settlements"] == hand["hold"].map({"1d": 24, "3d": 72, "7d": 168})).all()
    fam = pd.read_csv(out / "holds.csv").set_index("hold")
    assert (fam["verdict"] == "CLEARS").all() and fam.loc["1d", "M"] > 200 and fam.loc["1d", "B"] == pytest.approx(2 * 2 * (5 + 6.5))
    assert fam["p_fw"].nunique() == 1 and 0 <= fam["p_fw"].iloc[0] <= 0.05 and (fam["M_F3"] > 0).all() and (fam["M_F4"] > 0).all()
    assert np.allclose(fam["funding_part"], [240, 720, 1680], atol=2) and np.abs(fam["price_part"]).max() < 15
    ru = pd.read_csv(out / "runup.csv").set_index("group")
    assert abs(ru.loc["all", "median"] - 28) < 10 and set(ru.index) >= {"era = notice", "fold = F3", "fold = F4", "member_at_t0 = member at t0", "member_at_t0 = not a member"}
    assert "Verdict: CLEARS" in text and "the candidate hold" in text and POS in text and "SOLD at the revert" in text and "Reference rows" in text
    assert (out / "positive_funding.csv").exists() and (out / "lengthenings.csv").exists()
    G = pd.read_csv(out / "lengthenings.csv")
    assert G["symbol"].tolist() == [LNG] and abs(G["y_1d"].iloc[0] - 6 * 3) < 5                                           # the lengthening's day: six 4-h settlements at 3 bps
    meta = json.loads((out / "meta.json").read_text())
    assert meta["seed"] == 75 and meta["holds"] == [288, 864, 2016] and meta["verdict"] == "CLEARS" and meta["registration"] == "R75" and meta["side"] == "long"
    with pytest.raises(SystemExit):                                                                                       # a second read of the folds is refused by the ledger
        fundevent.run("R75", "u")
    assert not (tmp_path / "output" / "listing" / "u" / "validity.json").exists()


def test_a_planted_collapse_is_found_with_the_opposite_sign(tmp_path, monkeypatch):
    M, t0s = _market(collapse=-0.30)                                                                                      # deeper than a week's carry: no hold clears positive
    S = _settlements(t0s)
    C = _costs(M, S)
    _plant(tmp_path, monkeypatch, M, t0s, C, S)
    text = fundevent.run("R75", "v")
    fam = pd.read_csv(tmp_path / "output" / "listing" / "v" / "holds.csv").set_index("hold")
    assert fam.loc["1d", "M"] < -2000 and fam.loc["1d", "verdict"] == "CLEARS WITH THE OPPOSITE SIGN" and fam.loc["1d", "price_part"] < -2000 and 190 < fam.loc["1d", "funding_part"] < 240   # charged on the value: the falling position pays less
    assert (fam["verdict"] == "CLEARS WITH THE OPPOSITE SIGN").all()
    assert "Verdict: CLEARS WITH THE OPPOSITE SIGN" in text
    ru = pd.read_csv(tmp_path / "output" / "listing" / "v" / "runup.csv").set_index("group")
    assert abs(ru.loc["all", "median"] - 28) < 10                                                                         # no run-up was planted: the trailing carry alone


def test_a_frozen_row_the_archive_no_longer_gives_voids_the_run_after_the_guard_and_an_unregistered_list_too(tmp_path, monkeypatch):
    M, t0s = _market()
    S = _settlements(t0s)
    C = _costs(M, S)
    _plant(tmp_path, monkeypatch, M, t0s, C, S)
    moved = S.copy()
    moved.loc[(moved["symbol"] == EV[0]) & (moved["ts"] == t0s[0]), "interval_h"] = 4.0                                   # EV1's change is an hour later today
    monkeypatch.setattr(fundfreq, "settlements", lambda: moved)
    text = fundevent.run("R75", "v")
    V = json.loads((tmp_path / "output" / "listing" / "v" / "validity.json").read_text())
    assert "**VOID" in text and V["status"] == "FAIL" and V["2_rederived"]["bad"][0]["symbol"] == EV[0] and pd.read_csv(bt.READS)["fold"].tolist() == ["F3", "F4"]
    monkeypatch.setattr(bt, "READS", tmp_path / "output" / "backtest" / "reads2.csv")
    monkeypatch.setattr(fundfreq, "settlements", lambda: S)
    monkeypatch.setattr(fundevent, "LIST_MD5", "0" * 32)
    assert "**VOID" in fundevent.run("R75", "w")


def test_a_settlement_gap_is_counted_and_over_the_share_voids(tmp_path, monkeypatch):
    M, t0s = _market()
    S = _settlements(t0s)
    gapped = S[~((S["symbol"].isin(EV[:2])) & (S["ts"] > S["symbol"].map(dict(zip(EV, t0s))) + 30 * H) & (S["ts"] <= S["symbol"].map(dict(zip(EV, t0s))) + 36 * H))]   # EV1, EV2 lose six hourly rows on day two
    C = _costs(M, gapped)
    _plant(tmp_path, monkeypatch, M, t0s, C, gapped)
    text = fundevent.run("R75", "t")
    V = json.loads((tmp_path / "output" / "listing" / "t" / "validity.json").read_text())
    assert V["status"] == "FAIL" and V["8_cells_with_a_settlement_gap"] == 2 and V["8_gap_share"] == pytest.approx(0.25) and "**VOID" in text
    g = fundevent.settlement_gaps(gapped, EV[0], t0s[0], t0s[0] + 7 * 24 * H)
    assert g["gap"] and g["max_gap_ratio"] == 7.0 and g["n_rows"] == 169 - 6
    assert not fundevent.settlement_gaps(S, EV[0], t0s[0], t0s[0] + 7 * 24 * H)["gap"]
    # a revert inside the hold (hourly → every 4 h from day two, the rows on the 4-h grid labelled 4) is the archive's own row, not a gap
    t0 = t0s[2]
    rev = S[~((S["symbol"] == EV[2]) & (S["ts"] > t0 + 30 * H) & (((S["ts"] - t0) / H) % 4 != 0))].copy()
    rev.loc[(rev["symbol"] == EV[2]) & (rev["ts"] > t0 + 30 * H), "interval_h"] = 4.0
    g = fundevent.settlement_gaps(rev, EV[2], t0, t0 + 7 * 24 * H)
    assert not g["gap"] and g["max_gap_ratio"] == 1.0 and g["n_rows"] == 31 + (168 - 32) // 4 + 1


def test_the_fingerprint_check_writes_its_verdict_and_fails_on_a_changed_name(tmp_path, monkeypatch):
    monkeypatch.setattr(fundevent, "FP_BEFORE", tmp_path / "fp_before.csv")
    monkeypatch.setattr(fundevent, "FP_CHECK", tmp_path / "fp_check.json")
    monkeypatch.setattr(fundevent, "OUT", tmp_path)
    before = pd.DataFrame({"symbol": ["A", "B"], "rows": [10, 20], "first": [D("2023-01-01")] * 2, "last": [D("2023-02-01")] * 2, "sum_close": [1.5, 2.5], "sum_volume": [10.0, 20.0]})
    before.to_csv(fundevent.FP_BEFORE, index=False)
    (tmp_path / "r75").mkdir()
    (tmp_path / "r75" / "validity.json").write_text(json.dumps({"status": "PASS"}))
    monkeypatch.setattr(krlist, "fingerprint", lambda extent=None: before.copy())
    r = fundevent.check()
    assert r["status"] == "PASS" and json.loads(fundevent.FP_CHECK.read_text())["pass"] and json.loads((tmp_path / "r75" / "validity.json").read_text())["1_fingerprint_after"] == "PASS"
    monkeypatch.setattr(krlist, "fingerprint", lambda extent=None: before.assign(rows=[10, 21]))
    r = fundevent.check()
    assert r["status"] == "FAIL" and r["changed"][0]["symbol"] == "B"
    with pytest.raises(SystemExit):
        fundevent.main("check")
