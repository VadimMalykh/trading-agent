"""R83 (`ft2/govevent.py`) on planted bars, no network: the decision bar is the first 5m bar closing after a vote's end to the second (off
the grid) and the position enters one bar later; a planted drift after the end is found NEGATIVE by the trimmed gate on the `cell_big` cells
while the `cell_all` cells are described with the same numbers; a cell before the first member block and one whose 1-day exit lies past the
market's end are dropped and counted by the window's two ends; a creation row whose bar precedes the market's first bar is dropped from the
row and not from the cell; a batch of votes ending at one second is one cell; a planted run-on in two cells moves the plain mean and not the
trimmed one; the label identity with `horizon.labels` and the harness and the trimmed identity; the fingerprint's void on a changed name."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt
from ft2 import fundevent, govevent, govlist, krevent, krlist, listing, universe, upgevent

D = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
BAR = pd.Timedelta("5min")
EV = ["EV1USDT", "EV2USDT", "EV3USDT", "EV4USDT", "EV5USDT", "EV6USDT", "EV7USDT", "EV8USDT", "EV9USDT", "EV10USDT"]
MEM = ["M1USDT", "M2USDT", "M3USDT", "M4USDT", "M5USDT"]
LEAD = pd.Timedelta(days=5)
WEEKS = 16


def _t0s(idx):
    """Ten ends, 07:03:17 (off the grid) and 07:00:00 (on it) alternately, every ninth day from day 8 — except EV9's on day 1 (before the planted
    first member block, day 2) and EV10's on day 111 of the 112-day market (its 1-day exit past the end)."""
    days = [8, 17, 26, 35, 44, 53, 62, 71, 1, 111]
    return [idx[0].floor("D") + pd.Timedelta(days=d, hours=7, minutes=3 if k % 2 == 0 else 0, seconds=17 if k % 2 == 0 else 0) for k, d in enumerate(days)]


def _market(weeks=WEEKS, seed=0, drift=-0.04, runon=None, names=EV):
    """Sixteen weeks of 5m bars; the event names drift DOWN against their peers over the day after the entry (no run-up: the tally is public)."""
    rng = np.random.default_rng(seed)
    n = weeks * 7 * 288
    idx = pd.date_range("2023-06-05 00:05", periods=n, freq="5min", tz="UTC", name="t")
    cols = [*names, *MEM, "BTCUSDT"]
    r = rng.normal(0, 0.0005, (n, len(cols)))
    t0s = _t0s(idx)
    for j, t0 in enumerate(t0s):
        if t0 + pd.Timedelta(days=2) > idx[-1]:
            continue
        i0 = idx.get_loc(upgevent.decision_close(t0))
        g = drift if runon is None or j not in runon else runon[j]
        r[i0 + 2:i0 + 2 + 288, j] += g / 288
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


def _events(t0s, path, names=EV, early_creation=None):
    """One frozen row an end, plus a BATCH mate of EV1's vote (the same end to the second, not a cell); the first eight big, EV9 and EV10 big too
    (the window's two ends), the batch mate small. `early_creation`: EV2's proposal created before the market's first bar."""
    n = len(names)
    big = [True] * n
    rows = pd.DataFrame({"symbol": names, "base": [s[:-4] for s in names], "mult": 1.0, "t0": t0s, "ts_known": [t - LEAD for t in t0s], "release": [t - LEAD for t in t0s],
                         "code": [f"p{k}" for k in range(n)], "fold": ["F1"] * 5 + ["F2"] * 5, "block": D("2023-06-07"), "perp_first": D("2022-01-01"), "perp_first_source": "archive 5m",
                         "perp_age_days": 500, "member_at_t0": [True, False] * 5, "lead_d": 5.0, "space": [f"{s[:-4].lower()}.eth" for s in names], "start": [t - LEAD + pd.Timedelta(hours=1) for t in t0s],
                         "duration_d": 4.96, "votes": [500, 50, 300, 900, 250, 400, 600, 210, 700, 800], "scores_total": 1000.0, "n_choices": 2, "winner": ["For", "Against"] * 5,
                         "passed": [True, False] * 5, "kind": ["grant", "gauge", "election", "listing", "parameter", "treasury", "other", "grant", "gauge", "other"], "flagged": False, "repeat_n": 0,
                         "cell_all": True, "cell_big": big, "title": [f"Proposal of {s[:-4]}" for s in names]})
    mate = rows.iloc[[0]].copy()
    mate["code"], mate["votes"], mate["cell_all"], mate["cell_big"], mate["title"] = "p0b", 450, False, False, "The batch mate"
    L = pd.concat([rows, mate], ignore_index=True)[govlist.LIST_COLS]
    if early_creation is not None:
        L.loc[1, ["ts_known", "release"]] = early_creation
    L.to_csv(path, index=False)
    return L


def _plant(tmp_path, monkeypatch, M, t0s, C, name="t83", early_creation=None):
    monkeypatch.chdir(tmp_path)
    lst = tmp_path / "govvotes_f12.csv"
    L = _events(t0s, lst, early_creation=early_creation)
    out = tmp_path / "output" / "listing"
    monkeypatch.setattr(govevent, "OUT", out)
    monkeypatch.setattr(krevent, "OUT", out)
    monkeypatch.setattr(govevent, "LIST", lst)
    monkeypatch.setattr(govevent, "LIST_MD5", hashlib.md5(lst.read_bytes()).hexdigest())
    monkeypatch.setattr(govevent, "LIST_ROWS", len(L))
    monkeypatch.setattr(govevent, "GATE_ROWS", int(L["cell_big"].sum()))
    monkeypatch.setattr(govevent, "MIN_ELIGIBLE", 7)
    monkeypatch.setattr(govevent, "MIN_MEMBERS", 3)
    monkeypatch.setattr(govevent, "DRAWS", 2000)
    monkeypatch.setattr(govevent, "TOP5", ("EV1USDT", "EV2USDT", "EV3USDT", "EV4USDT", "EV5USDT"))
    monkeypatch.setattr(govevent, "EXPECTED_DESCRIBED", set())
    monkeypatch.setattr(govevent, "EXPECTED_DROPPED", {("EV9USDT", str(t0s[8])), ("EV10USDT", str(t0s[9]))})
    monkeypatch.setattr(govevent, "EXPECTED_3D_DROPPED", set())
    monkeypatch.setattr(listing, "window", lambda folds: (M.index[0], M.index[-1] + BAR))
    first_block = M.index[0].floor("D") + pd.Timedelta(days=2)                                                  # the first member block two days in: EV9's end on day 1 precedes it
    mem = pd.DataFrame({"block": [first_block] * len(MEM), "symbol": MEM})
    monkeypatch.setattr(universe, "members", lambda path=None, hindsight=None: mem)
    monkeypatch.setattr(universe, "screen_symbols", lambda path=None: MEM)
    starts = []
    monkeypatch.setattr(bt, "market", lambda syms, end, start=None, needs=(): (starts.append(start), M)[1])
    monkeypatch.setattr(bt, "load_costs", lambda index, cols, end, cost_mult=1.0, close=None: C)
    today = L.assign(why="eligible")
    monkeypatch.setattr(govlist, "events", lambda write=True: today)
    out.mkdir(parents=True)
    krevent.fp_paths(name)[0].write_text("symbol,rows\n")
    return L, today, starts


def test_the_decision_bar_is_the_first_bar_closing_after_the_end_to_the_second_and_the_batch_mate_is_a_row_not_a_cell(tmp_path, monkeypatch):
    assert upgevent.decision_close(D("2023-10-13 02:00:00")) == D("2023-10-13 02:05") and upgevent.decision_close(D("2024-08-31 07:20:12")) == D("2024-08-31 07:25")
    M, t0s = _market(weeks=6)
    L = _events(t0s, "/dev/null")
    L = govevent.load_events.__wrapped__(L) if hasattr(govevent.load_events, "__wrapped__") else L
    E = upgevent.entries(M, L, end=M.index[-1] + BAR, first_block=M.index[0], longest=288).set_index(["code"])
    e1 = E.loc["p0"]
    assert e1["t"] == t0s[0].floor("5min") + BAR and (e1["t"] - t0s[0]) < BAR and e1["eligible"]                # 07:03:17 → the bar closing 07:05
    assert E.loc["p1", "t"] == t0s[1] + BAR                                                                     # 07:00:00 → the bar closing 07:05 (strictly after)
    assert M.index[e1["row"] + bt.LATENCY] == e1["t"] + BAR and M.index[e1["row_into"]] == upgevent.decision_close(t0s[0] - LEAD)
    assert E.loc["p0b", "t"] == e1["t"]                                                                         # the batch mate: the same decision bar, a row of the list
    Lb = pd.read_csv("/dev/null") if False else L
    assert int(Lb["cell_big"].sum()) == 10 and not bool(Lb.loc[Lb["code"] == "p0b", "cell_big"].iloc[0])        # the gate's rows exclude it


def test_a_planted_drift_after_the_end_is_found_negative_on_the_big_cells_and_the_whole_cells_are_described_with_the_same_numbers(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    L, today, starts = _plant(tmp_path, monkeypatch, M, t0s, C)
    text = govevent.run("t83")
    out = tmp_path / "output" / "listing" / "t83"
    V = json.loads((out / "validity.json").read_text())
    assert V["status"] == "PASS" and V["2_rederived"]["status"] == "PASS" and V["2_flag_rows"] == 10 and V["3_cells"] == 8
    assert V["3_dropped_as_registered"] and set(V["3_dropped"].values()) == {"before the folds' first member block", "the 1d exit is not before the end"}
    assert V["3_3d_dropped_as_registered"] and V["3_creation_rows_dropped"] == 0 and V["5_min_members_creation"] >= 3
    assert V["7_decision_after_t0"] and V["7_decision_after_creation"] and V["7_creation_entry_after_creation"] and V["7_decision_within_5min_of_t0"]
    assert max(max(v) for v in V["6_identity_max_abs_diff"].values()) <= 1e-9 and V["6_trimmed_identity_max"] <= 1e-9 and V["6_same_cells"]
    assert starts[-1] == M.index[0] - pd.Timedelta(days=21)                                                     # the pad
    fam = pd.read_csv(out / "holds.csv").set_index("hold")
    assert fam["gate"].to_dict() == {"1d": True, "3d": False} and fam.loc["1d", "M_trim"] < -300 and fam.loc["1d", "k_trim"] == fundevent.k_trim(8) and fam.loc["1d", "B"] == pytest.approx(2 * 2 * (5 + 6.5))
    assert 0 <= fam.loc["1d", "p_trim"] <= 1 and fam.loc["1d", "M_trim_F1"] < 0 and fam.loc["1d", "M_trim_F2"] < 0
    ru = pd.read_csv(out / "runup.csv").set_index("group")
    assert abs(ru.loc["CREATION row: all", "median"]) < 100 and ru.loc["CREATION row: all", "median_days"] == pytest.approx(5.0, abs=0.01)   # no run-up planted: nothing to give back
    assert "CREATION row: passed = passed" in ru.index and "CREATION row: kind = grant" in ru.index and "rule (b)" in text
    sp = pd.read_csv(out / "splits.csv")
    assert sp[(sp["split"] == "passed") & (sp["hold"] == "1d")].set_index("group")["n"].to_dict() == {"passed": 4, "failed": 4}
    assert set(sp[sp["split"] == "fold"]["group"]) == {"F1", "F2"} and (sp["split"] == "name").sum() == 16 and "kind = grant" in set(sp["split"])
    E = pd.read_csv(out / "events.csv")
    assert (E["B_source"] == "own day").all() and len(E) == 8 and E["creation_y"].notna().all()
    assert "Verdict:" in text and "the gate hold 1d" in text and (out / "screen_blocks.csv").exists()
    meta = json.loads((out / "meta.json").read_text())
    assert meta["seed"] == 83 and meta["holds"] == [288, 864] and meta["gate_hold"] == 288 and meta["pad_days"] == 21 and meta["creation_little"]
    oh = pd.read_csv(out / "cell_all" / "holds.csv").set_index("hold")                                            # the whole-vote cells: the same numbers, described
    assert oh.loc["1d", "M_trim"] == pytest.approx(fam.loc["1d", "M_trim"]) and oh["verdict"].str.startswith("described").all()
    assert "The whole-vote cells (`cell_all`)" in text


def test_a_creation_row_before_the_markets_first_bar_is_dropped_from_the_row_and_not_from_the_cell(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    _plant(tmp_path, monkeypatch, M, t0s, C, early_creation=M.index[0] - pd.Timedelta(days=3))
    govevent.run("t83")
    V = json.loads((tmp_path / "output" / "listing" / "t83" / "validity.json").read_text())
    assert V["status"] == "PASS" and V["3_cells"] == 8 and V["3_creation_rows_dropped"] == 1 and V["3_creation_rows_dropped_cells"][0].startswith("EV2USDT")
    monkeypatch.setattr(govevent, "MAX_CREATION_DROPPED", 0)
    assert "**VOID" in govevent.run("t83")


def test_a_run_on_in_two_cells_moves_the_plain_mean_and_not_the_trimmed_one(tmp_path, monkeypatch):
    M, t0s = _market(runon={2: 0.40, 5: 0.40})
    C = _costs(M)
    _plant(tmp_path, monkeypatch, M, t0s, C)
    govevent.run("t83")
    fam = pd.read_csv(tmp_path / "output" / "listing" / "t83" / "holds.csv").set_index("hold")
    assert fam.loc["1d", "M"] > fam.loc["1d", "M_trim"] + 300 and fam.loc["1d", "k_trim"] == 1 and fam.loc["1d", "trim_identity"] < 1e-6


def test_a_moved_t0_a_changed_flag_an_unregistered_list_or_an_unexpected_drop_voids_the_run_and_the_fingerprint_voids_the_check(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    L, today, _ = _plant(tmp_path, monkeypatch, M, t0s, C)
    moved = today.copy()
    moved.loc[0, "t0"] = moved.loc[0, "t0"] + pd.Timedelta("1h")
    monkeypatch.setattr(govlist, "events", lambda write=True: moved)
    text = govevent.run("t83")
    V = json.loads((tmp_path / "output" / "listing" / "t83" / "validity.json").read_text())
    assert "**VOID" in text and V["status"] == "FAIL" and V["2_rederived"]["bad"][0]["why"] == "t0 differs"
    flipped = today.copy()
    flipped.loc[0, "cell_big"] = False
    monkeypatch.setattr(govlist, "events", lambda write=True: flipped)
    V = json.loads((tmp_path / "output" / "listing" / "t83" / "validity.json").read_text()) if "**VOID" in govevent.run("t83") else None
    assert V is not None and V["2_rederived"]["bad"][0]["why"] == "the cell flags differ"
    monkeypatch.setattr(govlist, "events", lambda write=True: today)
    monkeypatch.setattr(govevent, "EXPECTED_DROPPED", set())
    assert "**VOID" in govevent.run("t83")
    monkeypatch.setattr(govevent, "EXPECTED_DROPPED", {("EV9USDT", str(t0s[8])), ("EV10USDT", str(t0s[9]))})
    monkeypatch.setattr(govevent, "LIST_MD5", "0" * 32)
    assert "**VOID" in govevent.run("t83")
    with pytest.raises(SystemExit):
        govevent.main("run", "t83")
    monkeypatch.setattr(krlist, "fingerprint_check", lambda before, after_fn=None: {"pass": False, "changed": [{"symbol": "EV1USDT", "why": "changed"}], "names_before": 1, "names_after": 1})
    with pytest.raises(SystemExit) as ex:
        govevent.main("check", "t83")
    assert ex.value.code == 2
