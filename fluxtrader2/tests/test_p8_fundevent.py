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


# ---- decision BW1: the F5 Data line (nothing read) ------------------------------------------------------------------------------------
def test_the_data_names_are_the_f5_list_the_basket_and_btc(tmp_path, monkeypatch):
    L = pd.DataFrame({"symbol": ["A1USDT", "A2USDT", "A1USDT", "A3USDT"], "dir": ["shorter", "shorter", "longer", "longer"], "t0": [D("2026-02-01")] * 4})
    monkeypatch.setattr(fundfreq, "frozen", lambda tags=("f34", "f5"): L)
    mem = pd.DataFrame({"block": [D("2025-11-29")] * 2 + [D("2025-12-29")] * 3, "symbol": ["B0USDT", "A3USDT", "B1USDT", "B2USDT", "A2USDT"]})
    monkeypatch.setattr(universe, "members", lambda path=None, hindsight=None: mem)
    N = fundevent.data_names()
    assert N["f5"] == ["A1USDT", "A2USDT", "A3USDT"] and N["f5_shortenings"] == ["A1USDT", "A2USDT"] and N["basket"] == ["A2USDT", "B1USDT", "B2USDT"]
    assert N["all"] == ["A1USDT", "A2USDT", "A3USDT", "B1USDT", "B2USDT", "BTCUSDT"]


def test_the_funding_update_keeps_every_old_row_and_appends_the_newer_ones(tmp_path, monkeypatch):
    from ft2 import data
    monkeypatch.setattr(data, "PROC", tmp_path)
    old = pd.DataFrame({"symbol": ["X"] * 3 + ["Y"] * 2, "ts": [D("2026-08-30"), D("2026-08-31 08:00"), D("2026-08-31 16:00"), D("2026-08-31"), D("2026-08-31 08:00")], "rate": [0.1, 0.2, 0.3, -0.1, -0.2], "interval_h": np.array([8, 8, 8, 8, 8], dtype="int16")})
    old.assign(symbol=old["symbol"].astype("category")).to_parquet(tmp_path / "funding_archive.parquet", index=False)
    ms = lambda t: int(pd.Timestamp(t, tz="UTC").value // 10 ** 6)  # noqa: E731
    zips = {"X": pd.DataFrame({"calc_time": [ms("2026-08-31 16:00") + 1, ms("2026-09-01"), ms("2026-09-01 08:00")], "last_funding_rate": [9.9, 0.4, 0.5], "funding_interval_hours": [8, 8, 4]}),
            "Y": pd.DataFrame(), "Z": pd.DataFrame({"calc_time": [ms("2026-09-01")], "last_funding_rate": [0.7], "funding_interval_hours": [1]})}
    monkeypatch.setattr(data, "_read_zips", lambda kind, sym, pattern="*.zip", **kw: zips[sym])
    r = fundevent.funding_update(["X", "Y", "Z"], ("2026-09",), fetch=False)
    out = pd.read_parquet(tmp_path / "funding_archive.parquet")
    assert r["old_rows_identical"] and r["appended"] == {"X": 2, "Y": 0, "Z": 1} and r["rows_after"] == 8 and r["names_after"] == 3
    assert out.loc[(out["symbol"] == "X") & (out["ts"] == D("2026-08-31 16:00")), "rate"].item() == 0.3                    # the old row kept, the zip's 9.9 at the same stamp (rounded) not taken
    assert out.loc[out["symbol"] == "X", "interval_h"].tolist() == [8, 8, 8, 8, 4] and out.loc[out["symbol"] == "Z", "rate"].tolist() == [0.7]
    assert r["last_per_name_after"]["X"] == str(D("2026-09-01 08:00"))


def test_the_data_line_voids_on_a_changed_old_name_and_writes_the_coverage(tmp_path, monkeypatch):
    from ft2 import archive, data
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fundevent, "DATA_OUT", tmp_path / "r76_data")
    monkeypatch.setattr(fundevent, "F5_LIST", tmp_path / "f5.csv")
    L = pd.DataFrame({"symbol": ["A1USDT"], "dir": ["shorter"], "t0": [D("2026-02-01 05:00")], "fold": ["F5"]})
    L.to_csv(tmp_path / "f5.csv", index=False)
    monkeypatch.setattr(fundevent, "F5_LIST_MD5", hashlib.md5((tmp_path / "f5.csv").read_bytes()).hexdigest())
    monkeypatch.setattr(fundfreq, "frozen", lambda tags=("f34", "f5"): L)
    monkeypatch.setattr(universe, "members", lambda path=None, hindsight=None: pd.DataFrame({"block": [D("2025-12-29")], "symbol": ["B1USDT"]}))
    before = pd.DataFrame({"symbol": ["A1USDT", "B1USDT"], "rows": [10, 20], "first": [D("2025-01-01")] * 2, "last": [D("2025-12-31")] * 2, "sum_close": [1.5, 2.5], "sum_volume": [10.0, 20.0]})
    fps = iter([before.copy(), before.assign(rows=[10, 21])])
    monkeypatch.setattr(krlist, "fingerprint", lambda extent=None: next(fps))
    fetched = []
    monkeypatch.setattr(archive, "fetch_monthly", lambda kind, sym, sub="", months=None, **kw: (fetched.append((kind, sym, tuple(months))) or {"ok": len(months), "skip": 0, "bad": 0, "err": 0, "missing": 0}))
    monkeypatch.setattr(krlist, "ingest_symbols", lambda names: names)
    monkeypatch.setattr(data, "ingest_klines", lambda names, interval="5m": {"rows_out": 1})
    with pytest.raises(SystemExit):
        fundevent.data_line(fetch=True)
    assert {k for k, _, _ in fetched} == {"klines"} and {s for _, s, _ in fetched} == {"A1USDT", "B1USDT", "BTCUSDT"} and all(m == fundevent.DATA_MONTHS for _, _, m in fetched)
    chk = json.loads((tmp_path / "r76_data" / "fingerprint_check.json").read_text())
    assert not chk["pass"] and chk["changed"][0]["symbol"] == "B1USDT" and not (tmp_path / "r76_data" / "coverage_names.csv").exists()
    # the same line with the slice intact: the funding appended, the coverage of the events' windows and of every name over 2026 written
    fps = iter([before.copy(), before.copy()])
    monkeypatch.setattr(fundevent, "funding_update", lambda names, months, fetch=True: {"old_rows_identical": True, "appended": {n: 0 for n in names}})
    idx = pd.date_range("2026-01-01", "2026-03-01", freq="5min", tz="UTC", inclusive="left")
    have = pd.concat([pd.DataFrame({"symbol": s, "open_time": idx}) for s in ("A1USDT", "B1USDT")], ignore_index=True)
    monkeypatch.setattr(data, "load", lambda slice_, columns=None, symbols=None: have[have["symbol"].isin(symbols)].reset_index(drop=True))
    monkeypatch.setattr(fundfreq, "coverage", lambda L: pd.DataFrame({"symbol": ["A1USDT"], "t0": [D("2026-02-01 05:00")], "fold": ["F5"], "dir": ["shorter"], "bars": [2880], "expected": [2880], "share": [1.0]}))
    r = fundevent.data_line(fetch=False)
    assert r["fingerprint"]["pass"] and r["coverage"]["events_complete"] == 1 and r["coverage"]["names_over_2026"]["btc"]["under_95pct"] == ["BTCUSDT"]
    cn = pd.read_csv(tmp_path / "r76_data" / "coverage_names.csv").set_index("symbol")
    assert cn.loc["A1USDT", "group"] == "f5" and cn.loc["B1USDT", "group"] == "basket" and abs(cn.loc["A1USDT", "share"] - 59 / 257) < 1e-9


# ---- R76: the confirmation read — R75's candidate BOUGHT on the frozen F5 list, 7 days, in money, once ------------------------------------
def _settlements5(t0s):
    """R75's planted archive with EV3 shortened twice: 4 h → 2 h at its t0, 2 h → 1 h two days later (a second event while the position is open)."""
    S = _settlements(t0s)
    t0 = t0s[2]
    S = S[~((S["symbol"] == EV[2]) & (S["ts"] >= t0))]
    rows = [{"symbol": EV[2], "ts": t0 + k * 2 * H, "rate": CARRY, "interval_h": 2} for k in range(0, 24)]
    rows += [{"symbol": EV[2], "ts": t0 + 48 * H + k * H, "rate": CARRY, "interval_h": 1} for k in range(0, 24 * 7)]
    return pd.concat([S, pd.DataFrame(rows)], ignore_index=True).sort_values(["symbol", "ts"]).reset_index(drop=True)


def _events5(t0s, path):
    L = _events(t0s, path)
    L["fold"] = "F5"
    L.loc[L["symbol"] == EV[2], ["prev_h", "new_h"]] = [4.0, 2.0]
    twin = L[L["symbol"] == EV[2]].iloc[[0]].copy()
    twin["t0"] = twin["ts_known"] = t0s[2] + 48 * H
    twin[["prev_h", "new_h"]] = [2.0, 1.0]
    L = pd.concat([L, twin], ignore_index=True)
    L.to_csv(path, index=False)
    return L


def test_the_cells_are_one_position_per_name_while_a_position_is_open(tmp_path):
    M, t0s = _market(weeks=2)
    L = fundevent.load_events(_events5(t0s, tmp_path / "f5.csv").pipe(lambda d: (d.to_csv(tmp_path / "f5.csv", index=False), tmp_path / "f5.csv")[1]))
    cl, twins, pos, lng = fundevent.cells5(L)
    assert len(cl) == 8 and twins["symbol"].tolist() == [EV[2]] and twins["t0"].iloc[0] == t0s[2] + 48 * H and pos["symbol"].tolist() == [POS] and lng["symbol"].tolist() == [LNG]
    far = L.copy()
    far.loc[far.index[-1], "t0"] = t0s[2] + 8 * 24 * H                                                                    # eight days later: the position is closed, a cell of its own
    assert len(fundevent.cells5(far)[0]) == 9


def _plant5(tmp_path, monkeypatch, M, t0s, C, S):
    monkeypatch.chdir(tmp_path)
    lst = tmp_path / "fundfreq_f5.csv"
    L = _events5(t0s, lst)
    out = tmp_path / "output" / "listing"
    out.mkdir(parents=True)
    monkeypatch.setattr(fundevent, "OUT", out)
    monkeypatch.setattr(fundevent, "LIST5", lst)
    monkeypatch.setattr(fundevent, "LIST5_MD5", hashlib.md5(lst.read_bytes()).hexdigest())
    monkeypatch.setattr(fundevent, "LIST5_ROWS", len(L))
    monkeypatch.setattr(fundevent, "CELLS5", 8)
    monkeypatch.setattr(fundevent, "MIN_CONFIRM", 5)
    monkeypatch.setattr(fundevent, "MIN_MEMBERS", 3)
    monkeypatch.setattr(fundevent, "DRAWS", 2000)
    for tag in ("c", "c2", "d", "e"):
        (out / f"{tag}_fingerprint_before.csv").write_text("symbol,rows\n")
    monkeypatch.setattr(listing, "window", lambda folds: (M.index[0], M.index[-1] + BAR))
    mem = pd.DataFrame({"block": [M.index[0].floor("D")] * len(MEM), "symbol": MEM})
    monkeypatch.setattr(fundevent, "basket_members", lambda path=None: mem)
    monkeypatch.setattr(bt, "market", lambda syms, end, start=None, needs=(): M)
    monkeypatch.setattr(bt, "load_costs", lambda index, cols, end, cost_mult=1.0, close=None: C)
    monkeypatch.setattr(fundfreq, "settlements", lambda: S)
    plan = tmp_path / "PLAN.md"
    plan.write_text("### R76 — the confirmation read (registered)\n")
    monkeypatch.setattr(bt, "PLAN", plan)
    monkeypatch.setattr(bt, "READS", tmp_path / "output" / "backtest" / "confirmation_reads.csv")
    return L


def test_a_planted_carry_confirms_bought_hedged_with_the_entry_day_doubled_and_the_guard_before_the_market(tmp_path, monkeypatch):
    M, t0s = _market()
    S = _settlements5(t0s)
    C = _costs(M, S)
    _plant5(tmp_path, monkeypatch, M, t0s, C, S)
    loaded = []
    real_market = bt.market
    def market(syms, end, start=None, needs=()):
        loaded.append(pd.read_csv(bt.READS)["registration"].tolist())
        return real_market(syms, end, start, needs)
    monkeypatch.setattr(bt, "market", market)
    text = fundevent.confirm("R76", "c")
    out = tmp_path / "output" / "listing" / "c"
    assert loaded == [["R76"]] and pd.read_csv(bt.READS)["fold"].tolist() == ["F5"]
    V = json.loads((out / "validity.json").read_text())
    assert V["status"] == "PASS" and V["2_cells"] == 8 and len(V["2_second_events_described"]) == 1 and V["3_eligible"] == 8 and V["3_H_share"] == 1.0 and V["3_own_cost_row_share"] == 1.0
    assert max(v for v in V["6_identity_max_abs_diff"].values() if not isinstance(v, bool)) <= 1e-9 and V["6_hand_max_abs_diff"] <= 1e-9 and V["6_hand_cells"] == 8
    assert V["7_no_stop"] and V["7_t_equals_t0_plus_5min"] and V["8_cells_with_a_settlement_gap"] == 0 and V["8_settlements_per_cell_7d"]["max"] == 169 and V["8_settlements_per_cell_7d"]["min"] == 145   # the rows from t0 to the exit; EV3: two days of 2-h rows and five hourly … 24 + 121 = 145
    N = json.loads((out / "confirm.json").read_text())
    assert N["verdict"] == "CONFIRMED" and N["M"] > 1400 and N["se"] == max(N["se_bootstrap"], N["se_week"]) and 0 < N["M_heavy"] < N["M"]
    T = pd.read_csv(out / "trades.csv")
    assert len(T) == 8 and (~T["stopped"]).all() and ((T["x"] - T["e"]) == 2016).all() and (T["settlements_7d"] == [169] * 2 + [145] + [169] * 5).all()
    assert np.allclose(T["leg_entry"], 2 * 6.5) and np.allclose(T["leg_exit"], 6.5)                                     # the entry day's legs doubled, the exit at the proxy
    assert (T["hedge_cost"] > 0).all() and np.allclose(T["hedge"], -T["hedge_gain"] - T["hedge_cost"]) and np.allclose(T["H"], T["own"] + T["hedge"])   # the basket SOLD
    assert np.allclose(T["funding"].iloc[[0, 1, 3]], 1680, atol=5) and (T["gross"].abs() < 30).all()                     # the carry received, the price flat
    assert "runup_y" in T and "y_7d" in T and np.allclose(T["y_7d"], T["gross"] + T["funding"] - 0, atol=30)             # R75's frame on the same cells: a − the flat basket
    assert "Verdict: CONFIRMED" in text and "SOLD at the revert" in text and "second events" in text and (out / "second_events.csv").exists() and (out / "lengthenings_sold.csv").exists()
    meta = json.loads((out / "meta.json").read_text())
    assert meta["registration"] == "R76" and meta["side"] == "long" and meta["seed"] == 76 and meta["hold"] == 2016
    with pytest.raises(SystemExit):                                                                                       # a second read of F5 is refused by the ledger
        fundevent.confirm("R76", "c2")
    assert not (tmp_path / "output" / "listing" / "c2" / "confirm.json").exists()


def test_a_planted_collapse_closes_the_confirmation(tmp_path, monkeypatch):
    M, t0s = _market(collapse=-0.30)
    S = _settlements5(t0s)
    C = _costs(M, S)
    _plant5(tmp_path, monkeypatch, M, t0s, C, S)
    text = fundevent.confirm("R76", "d")
    N = json.loads((tmp_path / "output" / "listing" / "d" / "confirm.json").read_text())
    assert N["verdict"] == "CLOSED" and N["M"] < -500 and N["M"] + 1.96 * N["se"] < 0 and "Verdict: CLOSED" in text


def test_an_unregistered_f5_list_voids_after_the_guard(tmp_path, monkeypatch):
    M, t0s = _market()
    S = _settlements5(t0s)
    C = _costs(M, S)
    _plant5(tmp_path, monkeypatch, M, t0s, C, S)
    monkeypatch.setattr(fundevent, "LIST5_MD5", "0" * 32)
    text = fundevent.confirm("R76", "e")
    assert "**VOID" in text and pd.read_csv(bt.READS)["registration"].tolist() == ["R76"] and not (tmp_path / "output" / "listing" / "e" / "confirm.json").exists()


# ====================================================================================================================================
# R77 (decision BY1): the same frame on the frozen EPISODE list — no guard, the gate on the 10 % trimmed mean, fundep's rederivation
# ====================================================================================================================================
def _settlements77(t0s, carry=CARRY, runon=()):
    """The archive's rows for R77's cells: flat 4-hourly settlements from 2024-01 (the age), the four settlements up to t0 at −0.6 % each (the
    day's sum crosses −2 % AT t0 and not before), then hourly at `carry` for eight days (0 → no carry)."""
    rows = []
    for j, t0 in enumerate(t0s):
        name = EV[j]
        for ts in pd.date_range(D("2024-01-01"), t0 - 16 * H, freq="4h"):
            rows.append({"symbol": name, "ts": ts, "rate": 0.0001, "interval_h": 4})
        for k in (3, 2, 1, 0):
            rows.append({"symbol": name, "ts": t0 - k * 4 * H, "rate": -0.006, "interval_h": 4})
        for k in range(1, 8 * 24 + 1):
            rows.append({"symbol": name, "ts": t0 + k * H, "rate": carry, "interval_h": 1})
    return pd.DataFrame(rows).sort_values(["symbol", "ts"]).reset_index(drop=True)


def _events77(S, t0s, path):
    """The frozen list as `fundep.episodes` writes it from the planted settlements (so that the rederivation agrees to the digit)."""
    from ft2 import fundep
    T = fundep.trailing(S)
    first = S.groupby("symbol")["ts"].min()
    E = fundep.episodes(T, 0.02, first)
    assert E["t0"].tolist() == sorted(t0s), (E["t0"].tolist(), t0s)
    E["base"], E["mult"], E["ts_known"] = E["symbol"].str[:-4], 1.0, E["t0"]
    E["fold"] = ["F1" if j < 4 else "F2" for j in range(len(E))]
    E["perp_first"], E["perp_first_source"], E["perp_age_days"] = first.reindex(E["symbol"]).to_numpy(), "funding", 240
    E["member_at_t0"] = [j % 2 == 0 for j in range(len(E))]
    E["flag_t0"], E["flag_lag_h"], E["flagged_7d"] = pd.NaT, np.nan, [j == 1 for j in range(len(E))]
    E["cap_share_7d"], E["cap_rate"] = 0.0, 0.006
    E = E[fundep.LIST_COLS]
    E.to_csv(path, index=False)
    return E


def _plant77(tmp_path, monkeypatch, M, t0s, C, S, expected_dropped=frozenset()):
    monkeypatch.chdir(tmp_path)
    lst = tmp_path / "fundep_f12.csv"
    L = _events77(S, t0s, lst)
    out = tmp_path / "output" / "listing"
    out.mkdir(parents=True)
    monkeypatch.setattr(fundevent, "OUT", out)
    monkeypatch.setattr(fundevent, "LIST77", lst)
    monkeypatch.setattr(fundevent, "LIST77_MD5", hashlib.md5(lst.read_bytes()).hexdigest())
    monkeypatch.setattr(fundevent, "LIST77_ROWS", len(L))
    monkeypatch.setattr(fundevent, "CELLS77", len(L))
    monkeypatch.setattr(fundevent, "MIN_ELIGIBLE77", 5)
    monkeypatch.setattr(fundevent, "EXPECTED_DROPPED77", set(expected_dropped))
    monkeypatch.setattr(fundevent, "MIN_MEMBERS", 3)
    monkeypatch.setattr(fundevent, "DRAWS", 2000)
    (out / "r77_fingerprint_before.csv").write_text("symbol,rows\n")
    monkeypatch.setattr(listing, "window", lambda folds: (M.index[0], M.index[-1] + BAR))
    mem = pd.DataFrame({"block": [M.index[0].floor("D")] * len(MEM), "symbol": MEM})
    monkeypatch.setattr(universe, "members", lambda path=None, hindsight=None: mem)
    monkeypatch.setattr(universe, "screen_symbols", lambda path=None: MEM)
    monkeypatch.setattr(bt, "market", lambda syms, end, start=None, needs=(): M)
    monkeypatch.setattr(bt, "load_costs", lambda index, cols, end, cost_mult=1.0, close=None: C)
    monkeypatch.setattr(fundfreq, "settlements", lambda: S)
    monkeypatch.setattr(fundfreq, "perp_first", lambda syms, F: pd.DataFrame({"symbol": list(syms), "perp_first": pd.NaT, "perp_first_source": "none"}))   # no slice: the first settlement is the stamp
    monkeypatch.setattr(bt, "READS", tmp_path / "output" / "backtest" / "confirmation_reads.csv")
    return L, lst


def _runon(M, t0s, cells, bps):
    """The cells' price jumps by `bps` over the first hour after the entry (a run-on in the mean, not in the trimmed statistic)."""
    close = M.close.copy()
    for j in cells:
        i0 = M.index.get_loc(t0s[j])
        close.iloc[i0 + 3:, j] *= 1 + bps / 1e4
    return bt.Market(close, close * 1.001, close * 0.999, M.dv)


def test_r77_a_planted_carry_clears_on_the_trimmed_statistic_without_a_guard_row_and_the_episode_splits_come_out(tmp_path, monkeypatch):
    M, t0s = _market()
    S = _settlements77(t0s)
    C = _costs(M, S)
    _plant77(tmp_path, monkeypatch, M, t0s, C, S)
    text = fundevent.run("R77")
    out = tmp_path / "output" / "listing" / "r77"
    assert not bt.READS.exists()                                                                                           # the exploration folds: no ledger row
    V = json.loads((out / "validity.json").read_text())
    assert V["status"] == "PASS" and V["2_rederived"]["status"] == "PASS" and V["2_rederived"]["episodes_today"] == 8 and V["3_eligible"] == 8 and V["3_dropped"] == [] and V["3_dropped_as_named"]
    assert V["6_guard"]["status"].startswith("none") and V["6_hand_max_abs_diff"] <= 1e-9 and V["8_settlements_per_cell_1d"]["median"] == 24.0
    fam = pd.read_csv(out / "holds.csv").set_index("hold")
    for d, carry in (("1d", 240), ("3d", 720), ("7d", 1680)):
        assert abs(fam.loc[d, "M_trim"] - carry) < 10 * np.sqrt(carry / 240) and fam.loc[d, "k_trim"] == 1 and fam.loc[d, "trim_identity"] <= 1e-9
    assert (fam["verdict"] == "CLEARS").all() and (fam["u_gate"] == fam["u_trim"]).all() and (fam["M_trim_F1"] > 0).all() and (fam["M_trim_F2"] > 0).all() and fam["p_fw_trim"].max() <= 0.05
    ru = pd.read_csv(out / "runup.csv").set_index("group")
    assert set(ru.index) >= {"flagged_7d = flagged within 7 d", "flagged_7d = not flagged", "first_episode = first episode", "clock = 4h", "fold = F1", "fold = F2"} and ru.loc["flagged_7d = flagged within 7 d", "n"] == 1
    meta = json.loads((out / "meta.json").read_text())
    assert meta["registration"] == "R77" and meta["decision"] == "BY1" and meta["gate"] == "trimmed" and meta["seed"] == 77 and meta["verdict"] == "CLEARS"
    assert "TRIMMED mean" in text and "Verdict: CLEARS" in text and "sum_half" in text and "SOLD at the revert" in text        # the mirror's line prints 'none eligible' on an episode list
    E = pd.read_csv(out / "events.csv")
    assert set(E["clock"]) == {"4h"} and E["first_episode"].all()


def test_r77_a_run_on_moves_the_mean_and_not_the_trimmed_statistic_which_gates(tmp_path, monkeypatch):
    M, t0s = _market()
    S = _settlements77(t0s, carry=0.0)                                                                                  # no carry after t0: the typical cell earns nothing
    M2 = _runon(M, t0s, cells=[2], bps=5000)
    C = _costs(M2, S)
    _plant77(tmp_path, monkeypatch, M2, t0s, C, S)
    fundevent.run("R77")
    fam = pd.read_csv(tmp_path / "output" / "listing" / "r77" / "holds.csv").set_index("hold")
    assert (fam["M"] > 500).all() and (fam["M_trim"].abs() < 30).all() and (fam["se_trim"] < fam["se"]).all()               # the mean is the run-on; the trimmed statistic is the population's
    assert not (fam["verdict"] == "CLEARS").any() and (fam["M_without_5"].abs() < 30).all()
    meta = json.loads((tmp_path / "output" / "listing" / "r77" / "meta.json").read_text())
    assert meta["verdict"] in ("NOT DETECTABLE", "CLOSED")


def test_r77_the_rederivation_voids_on_a_changed_frozen_rate_the_calendar_drop_is_named_and_the_registration_is_required(tmp_path, monkeypatch):
    M, t0s = _market()
    S = _settlements77(t0s)
    C = _costs(M, S)
    L, lst = _plant77(tmp_path, monkeypatch, M, t0s, C, S)
    with pytest.raises(SystemExit):                                                                                       # no guard, but the read is R77's
        fundevent.run(None)
    assert not (tmp_path / "output" / "listing" / "r77" / "validity.json").exists()
    # a frozen row's fund_1d edited: the md5 is re-pinned to the edited file so that (2)'s rederivation is what fails
    L2 = pd.read_csv(lst)
    L2.loc[0, "fund_1d"] = -0.03
    L2.to_csv(lst, index=False)
    monkeypatch.setattr(fundevent, "LIST77_MD5", hashlib.md5(lst.read_bytes()).hexdigest())
    text = fundevent.run("R77", "v")
    V = json.loads((tmp_path / "output" / "listing" / "v" / "validity.json").read_text())
    assert "**VOID" in text and V["status"] == "FAIL" and V["2_rederived"]["status"] == "FAIL" and V["2_rederived"]["bad"][0]["why"] == "fund_1d differs"
    # the last cell's exit passes the end: dropped, named, and not the expected set
    M3, t0s3 = _market(weeks=4)
    t0s3 = t0s3[:8]
    S3 = _settlements77(t0s3)
    C3 = _costs(M3, S3)
    monkeypatch.undo()
    (tmp_path / "b").mkdir()
    _plant77(tmp_path / "b", monkeypatch, M3, t0s3, C3, S3, expected_dropped={(EV[3], str(t0s3[3]))})
    fundevent.run("R77", "w")
    V = json.loads((tmp_path / "b" / "output" / "listing" / "w" / "validity.json").read_text())
    assert V["3_eligible"] == 3 and {d["why"] for d in V["3_dropped"]} == {"the 7-day exit is not before the end", "the decision bar is not in the market"} and V["3_dropped_as_named"] is False
    assert V["status"] == "FAIL"                                                                                          # 3 of 8 eligible: under the planted minimum of 5 — a void by (3), the dropped named
