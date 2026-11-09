"""R85 (`ft2/cexevent.py`) on planted bars, no network: the decision bar is the first 5m bar closing after t0 + the lag (08:05 UTC for a
00:00 stamp; 06:05 when the probe sets 6 h) and the position enters one bar later; a planted drift after the lag is found NEGATIVE by the
trimmed gate on the members' inflow cells while the members' outflow cells, bought, are described with the mirrored sign and the non-members'
cells beside; a cell before the first member block is dropped at 1d and one whose 3-day exit lies past the market's end is dropped at 3d and
kept at 1d; a planted run-on in two cells moves the plain mean and not the trimmed one; the label identity with `horizon.labels` and the
harness and the trimmed identity; a moved t0, a flipped cell, an unregistered list or an unexpected drop voids the run and the fingerprint
voids the check; gate (a) — a REWRITTEN known-at file or one fetched before the registered day — and gate (b) — a lag outside {6, 8} — void
the run BEFORE the market is loaded."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt
from ft2 import cexevent, cexflow, fundevent, krevent, krlist, listing, universe, upgevent

D = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
BAR = pd.Timedelta("5min")
EV = [f"EV{k}USDT" for k in range(1, 11)]          # the gate's rows: members' inflow cells
OF = [f"OF{k}USDT" for k in range(1, 5)]           # the members' outflow cells (the mirror)
NM = ["NM1USDT", "NM2USDT"]                        # the non-members' inflow cells
MEM = ["M1USDT", "M2USDT", "M3USDT", "M4USDT", "M5USDT"]
WEEKS = 16


def _t0s(idx, days=(8, 17, 26, 35, 44, 53, 62, 71, 1, 110)):
    """Ten stamps at 00:00 UTC every ninth day from day 8 — except EV9's on day 1 (before the planted first member block, day 2) and EV10's on
    day 110 of the 112-day market (its 1-day exit inside, its 3-day exit past the end)."""
    return [idx[0].floor("D") + pd.Timedelta(days=d) for d in days]


def _market(weeks=WEEKS, seed=0, drift=-0.04, runon=None, lag_h=8, drift_bars=288):
    """Sixteen weeks of 5m bars; the inflow names drift DOWN against their peers over the day after the entry at t0 + the lag; the outflow names
    drift UP (the mirror earns when bought); the non-members drift down too."""
    rng = np.random.default_rng(seed)
    n = weeks * 7 * 288
    idx = pd.date_range("2023-06-05 00:05", periods=n, freq="5min", tz="UTC", name="t")
    cols = [*EV, *OF, *NM, *MEM, "BTCUSDT"]
    r = rng.normal(0, 0.0005, (n, len(cols)))
    t0s = _t0s(idx)
    plan = [(j, t0s[j], drift if runon is None or j not in runon else runon[j]) for j in range(len(EV))]
    plan += [(len(EV) + k, t0s[k + 1], -drift) for k in range(len(OF))]                     # the outflow names share EV2…EV5's stamps, drift up
    plan += [(len(EV) + len(OF) + k, t0s[k + 2], drift) for k in range(len(NM))]
    for j, t0, g in plan:
        if t0 + pd.Timedelta(hours=lag_h) + pd.Timedelta(minutes=5 * (drift_bars + 4)) > idx[-1]:
            continue
        i0 = idx.get_loc(upgevent.decision_close(t0 + pd.Timedelta(hours=lag_h)))
        r[i0 + 2:i0 + 2 + drift_bars, j] += g / drift_bars
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


def _row(sym, t0, side, member, fold, code, cell=True, change=0.08, usd=5e7, chains=1, rep=0, commit=False):
    return {"symbol": sym, "base": sym[:-4], "mult": 1.0, "t0": t0, "ts_known": t0, "release": t0, "code": code, "fold": fold, "block": D("2023-06-07"), "perp_first": D("2022-01-01"),
            "perp_first_source": "archive 5m", "perp_age_days": 500, "member_at_t0": member, "side": side, "stamp_hour": 0.0, "gap_d": 1.0, "amount_before": 1000.0, "amount_after": 1000.0 * (1 + change),
            "change": change, "usd_before": usd, "usd_jump": usd * change, "chains_n": chains, "flag_10": abs(change) >= 0.10, "flag_20": abs(change) >= 0.20, "list_commit": commit, "repeat_n": rep,
            "days_since_prior": np.nan if rep == 0 else 9.0, "cell": cell}


def _events(t0s, path):
    """Ten gate rows (members' inflow cells; EV9 before the first block, EV10 at the end), four outflow member cells, two non-member inflow
    cells, and one inflow member row with `cell` False (a repeat within 7 days — a row, not a cell)."""
    folds = ("F1",) * 5 + ("F2",) * 5
    rows = [_row(s, t, "in", True, f, f"{s[:-4]}_{t:%Y%m%d}_in", change=[0.06, 0.12, 0.25, 0.07, 0.15, 0.3, 0.08, 0.11, 0.09, 0.21][k], usd=[1e6, 9e7][k % 2], chains=1 + (k % 3 == 0), rep=k % 2, commit=k == 3)
            for k, (s, t, f) in enumerate(zip(EV, t0s, folds))]
    rows += [_row(s, t0s[k + 1], "out", True, folds[k + 1], f"{s[:-4]}_{t0s[k + 1]:%Y%m%d}_out", change=-0.08) for k, s in enumerate(OF)]
    rows += [_row(s, t0s[k + 2], "in", False, folds[k + 2], f"{s[:-4]}_{t0s[k + 2]:%Y%m%d}_in") for k, s in enumerate(NM)]
    rows.append(_row(EV[0], t0s[0] + pd.Timedelta(days=2), "in", True, "F1", f"EV1_{t0s[0] + pd.Timedelta(days=2):%Y%m%d}_in", cell=False, rep=1))
    L = pd.DataFrame(rows)[cexflow.LIST_COLS]
    L.to_csv(path, index=False)
    return L


def _knownat(path, verdict="IDENTICAL on the overlap — a point-in-time source", newer="binance-cex_2026-11-13.json", differ=0, removed=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"files": ["data/raw/external/defillama_cex/binance-cex_2026-11-09.json", f"data/raw/external/defillama_cex/{newer}"], "in_both": 640000, "equal": 640000 - differ,
                                "differ": differ, "stamps_only_in_older": list(removed), "live_point_older": "2026-11-09 04:17:35+00:00", "verdict": verdict}))


def _plant(tmp_path, monkeypatch, M, t0s, C, name="t85"):
    monkeypatch.chdir(tmp_path)
    lst = tmp_path / "cexflow_f12.csv"
    L = _events(t0s, lst)
    out = tmp_path / "output" / "listing"
    kn = tmp_path / "output" / "cexflow" / "knownat.json"
    _knownat(kn)
    ev = tmp_path / "output" / "cexflow" / "events.csv"
    L.assign(revert_3d=[k % 3 == 0 for k in range(len(L))], why="eligible").to_csv(ev, index=False)
    monkeypatch.setattr(cexevent, "OUT", out)
    monkeypatch.setattr(krevent, "OUT", out)
    monkeypatch.setattr(cexevent, "LIST", lst)
    monkeypatch.setattr(cexevent, "LIST_MD5", hashlib.md5(lst.read_bytes()).hexdigest())
    monkeypatch.setattr(cexevent, "LIST_ROWS", len(L))
    monkeypatch.setattr(cexevent, "GATE_ROWS", 10)
    monkeypatch.setattr(cexevent, "KNOWNAT", kn)
    monkeypatch.setattr(cexevent, "EVENTS_CSV", ev)
    monkeypatch.setattr(cexevent, "MIN_ELIGIBLE", 7)
    monkeypatch.setattr(cexevent, "MIN_MEMBERS", 3)
    monkeypatch.setattr(cexevent, "DRAWS", 2000)
    monkeypatch.setattr(cexevent, "TOP5", ("EV1USDT", "EV2USDT", "EV3USDT", "EV4USDT", "EV5USDT"))
    monkeypatch.setattr(cexevent, "EXPECTED_DESCRIBED", set())
    monkeypatch.setattr(cexevent, "EXPECTED_DROPPED", {("EV9USDT", str(t0s[8]))})
    monkeypatch.setattr(cexevent, "EXPECTED_3D_DROPPED", {("EV10USDT", str(t0s[9]))})
    monkeypatch.setattr(listing, "window", lambda folds: (M.index[0], M.index[-1] + BAR))
    first_block = M.index[0].floor("D") + pd.Timedelta(days=2)                                                  # EV9's stamp on day 1 precedes it
    mem = pd.DataFrame({"block": [first_block] * len(MEM), "symbol": MEM})
    monkeypatch.setattr(universe, "members", lambda path=None, hindsight=None: mem)
    monkeypatch.setattr(universe, "screen_symbols", lambda path=None: MEM)
    starts = []
    monkeypatch.setattr(bt, "market", lambda syms, end, start=None, needs=(): (starts.append(start), M)[1])
    monkeypatch.setattr(bt, "load_costs", lambda index, cols, end, cost_mult=1.0, close=None: C)
    today = L.assign(why="eligible")
    monkeypatch.setattr(cexflow, "events", lambda write=True: today)
    out.mkdir(parents=True)
    krevent.fp_paths(name)[0].write_text("symbol,rows\n")
    return L, today, starts


def test_the_decision_bar_is_the_first_bar_closing_after_t0_plus_the_lag_and_the_position_enters_one_bar_later(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    _plant(tmp_path, monkeypatch, M, t0s, C)
    cexevent.run("t85")
    E = pd.read_csv(tmp_path / "output" / "listing" / "t85" / "events.csv", parse_dates=["t0", "t", "t_known"]).set_index("symbol")
    for s in ("EV1USDT", "EV5USDT"):
        assert E.loc[s, "t"] == E.loc[s, "t0"] + pd.Timedelta(hours=8) + BAR and E.loc[s, "t_known"] == E.loc[s, "t0"] + pd.Timedelta(hours=8)   # 00:00 → known 08:00 → the bar closing 08:05
        assert M.index[int(E.loc[s, "row"]) + bt.LATENCY] == E.loc[s, "t"] + BAR                                       # entered one bar later
        assert M.index[int(E.loc[s, "lag_row"])] == E.loc[s, "t0"] + BAR                                               # the lag row from the bar closing 00:05
    monkeypatch.setattr(cexevent, "LAG_H", 6)
    cexevent.run("t85")
    E6 = pd.read_csv(tmp_path / "output" / "listing" / "t85" / "events.csv", parse_dates=["t0", "t"]).set_index("symbol")
    assert E6.loc["EV1USDT", "t"] == E6.loc["EV1USDT", "t0"] + pd.Timedelta(hours=6) + BAR
    meta = json.loads((tmp_path / "output" / "listing" / "t85" / "meta.json").read_text())
    assert meta["lag_h"] == 6 and meta["runup_bars"] == 288 + 72 + 1


def test_a_planted_drift_after_the_lag_is_found_negative_on_the_inflow_cells_and_the_outflow_mirror_is_described_with_the_opposite_sign(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    L, today, starts = _plant(tmp_path, monkeypatch, M, t0s, C)
    text = cexevent.run("t85")
    out = tmp_path / "output" / "listing" / "t85"
    V = json.loads((out / "validity.json").read_text())
    assert V["status"] == "PASS" and V["0_gate_a_knownat"]["status"] == "PASS" and V["0_gate_b_lag_h"] == 8 and V["2_rederived"]["status"] == "PASS" and V["2_gate_rows"] == 10 and V["3_cells"] == 9
    assert V["3_dropped_as_registered"] and set(V["3_dropped"].values()) == {"before the folds' first member block"}
    assert V["3_3d_dropped_as_registered"] and V["3_3d_label_dropped"] == [["EV10USDT", str(t0s[9])]]                 # dropped at 3d, kept at 1d
    assert V["7_decision_after_t0_plus_lag"] and V["7_decision_within_5min_of_t0_plus_lag"] and V["7_lag_row_entry_after_t0"] and V["7_lag_row_entry_before_decision"]
    assert V["5_runup_rows_dropped"] == 0 and V["5_lag_rows_dropped"] == 0 and V["5_min_members_lag"] >= 3
    assert max(max(v) for v in V["6_identity_max_abs_diff"].values()) <= 1e-9 and V["6_trimmed_identity_max"] <= 1e-9 and V["6_same_cells"]
    assert starts[-1] == M.index[0] - pd.Timedelta(days=7)                                                      # the pad
    fam = pd.read_csv(out / "holds.csv").set_index("hold")
    assert fam["gate"].to_dict() == {"1d": True, "3d": False} and fam.loc["1d", "M_trim"] < -300 and fam.loc["1d", "k_trim"] == fundevent.k_trim(9) and fam.loc["1d", "B"] == pytest.approx(2 * 2 * (5 + 6.5))
    assert 0 <= fam.loc["1d", "p_trim"] <= 1 and fam.loc["1d", "M_trim_F1"] < 0 and fam.loc["1d", "M_trim_F2"] < 0
    ru = pd.read_csv(out / "runup.csv").set_index("group")
    assert abs(ru.loc["RUN-UP t0 − 24 h → the decision bar: all", "median"]) < 100 and abs(ru.loc["LAG row t0 + 5 min → the decision bar: all", "median"]) < 100 and "rule (b)" in text
    assert "RUN-UP: flag_20 = |change| ≥ 20 %" in ru.index and "LAG row: revert_3d = the balance back within 3 stamps (post-t0)" in ru.index
    sp = pd.read_csv(out / "splits.csv")
    assert sp[(sp["split"] == "flag_20") & (sp["hold"] == "1d")].set_index("group")["n"].to_dict() == {"|change| ≥ 20 %": 3, "under 20 %": 6}
    assert set(sp[sp["split"] == "fold"]["group"]) == {"F1", "F2"} and (sp["split"] == "name").sum() == 18 and "revert_3d" in set(sp["split"])
    E = pd.read_csv(out / "events.csv")
    assert (E["B_source"] == "own day").all() and len(E) == 9 and E["lag_y"].notna().all() and set(E["symbol"]) == set(EV) - {"EV9USDT"}
    assert "Verdict:" in text and "the gate hold 1d" in text and (out / "screen_blocks.csv").exists()
    meta = json.loads((out / "meta.json").read_text())
    assert meta["seed"] == 85 and meta["holds"] == [288, 864] and meta["gate_hold"] == 288 and meta["pad_days"] == 7 and meta["lag_h"] == 8 and meta["runup_little"]
    oh = pd.read_csv(out / "outflow" / "holds.csv").set_index("hold")                                              # the mirror, bought: the planted drift up → M_trim > 0, described
    assert oh.loc["1d", "M_trim"] > 300 and oh["verdict"].str.startswith("described").all() and len(pd.read_csv(out / "outflow" / "events.csv")) == 4
    nm = pd.read_csv(out / "nonmembers" / "events.csv")
    assert set(nm["symbol"]) == set(NM) and "The members' OUTFLOW cells, BOUGHT (the mirror)" in text and "The NON-MEMBERS' inflow cells" in text


def test_a_run_on_in_two_cells_moves_the_plain_mean_and_not_the_trimmed_one(tmp_path, monkeypatch):
    M, t0s = _market(runon={2: 0.40, 5: 0.40})
    C = _costs(M)
    _plant(tmp_path, monkeypatch, M, t0s, C)
    cexevent.run("t85")
    fam = pd.read_csv(tmp_path / "output" / "listing" / "t85" / "holds.csv").set_index("hold")
    assert fam.loc["1d", "M"] > fam.loc["1d", "M_trim"] + 300 and fam.loc["1d", "k_trim"] == 1 and fam.loc["1d", "trim_identity"] < 1e-6


def test_a_moved_t0_a_flipped_cell_an_unregistered_list_or_an_unexpected_drop_voids_the_run_and_the_fingerprint_voids_the_check(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    L, today, _ = _plant(tmp_path, monkeypatch, M, t0s, C)
    moved = today.copy()
    moved.loc[0, "t0"] = moved.loc[0, "t0"] + pd.Timedelta("1h")
    monkeypatch.setattr(cexflow, "events", lambda write=True: moved)
    text = cexevent.run("t85")
    V = json.loads((tmp_path / "output" / "listing" / "t85" / "validity.json").read_text())
    assert "**VOID" in text and V["status"] == "FAIL" and V["2_rederived"]["bad"][0]["why"] == "t0 differs"
    flipped = today.copy()
    flipped.loc[0, "cell"] = False
    monkeypatch.setattr(cexflow, "events", lambda write=True: flipped)
    assert "**VOID" in cexevent.run("t85")
    V = json.loads((tmp_path / "output" / "listing" / "t85" / "validity.json").read_text())
    assert V["2_rederived"]["bad"][0]["why"] == "the side or the cell flag differs"
    monkeypatch.setattr(cexflow, "events", lambda write=True: today)
    monkeypatch.setattr(cexevent, "EXPECTED_DROPPED", set())
    assert "**VOID" in cexevent.run("t85")
    monkeypatch.setattr(cexevent, "EXPECTED_DROPPED", {("EV9USDT", str(t0s[8]))})
    monkeypatch.setattr(cexevent, "LIST_MD5", "0" * 32)
    assert "**VOID" in cexevent.run("t85")
    with pytest.raises(SystemExit):
        cexevent.main("run", "t85")
    monkeypatch.setattr(krlist, "fingerprint_check", lambda before, after_fn=None: {"pass": False, "changed": [{"symbol": "EV1USDT", "why": "changed"}], "names_before": 1, "names_after": 1})
    with pytest.raises(SystemExit) as ex:
        cexevent.main("check", "t85")
    assert ex.value.code == 2


def test_gate_a_rewritten_or_early_knownat_and_gate_b_an_unregistered_lag_void_the_run_before_the_market_is_loaded(tmp_path, monkeypatch):
    M, t0s = _market()
    C = _costs(M)
    L, today, starts = _plant(tmp_path, monkeypatch, M, t0s, C)
    kn = tmp_path / "output" / "cexflow" / "knownat.json"
    _knownat(kn, verdict="REWRITTEN — the history moved under a re-fetch", differ=3)
    text = cexevent.run("t85")
    assert "**VOID" in text and "the market was NOT loaded" in text and starts == []
    V = json.loads((tmp_path / "output" / "listing" / "t85" / "validity.json").read_text())
    assert V["status"] == "FAIL" and V["0_gate_a_knownat"]["status"] == "FAIL" and V["0_gate_a_knownat"]["differ"] == 3
    _knownat(kn, newer="binance-cex_2026-11-12.json")                                                            # identical, but fetched before the registered day
    assert "**VOID" in cexevent.run("t85") and starts == []
    _knownat(kn, removed=["2024-01-01 00:00:00+00:00"])                                                         # a day's point gone from the middle of the history
    assert "**VOID" in cexevent.run("t85") and starts == []
    kn.unlink()
    assert "**VOID" in cexevent.run("t85") and starts == []
    _knownat(kn)
    monkeypatch.setattr(cexevent, "LAG_H", 7)
    assert "**VOID" in cexevent.run("t85") and starts == []
    monkeypatch.setattr(cexevent, "LAG_H", 8)
    assert "**VOID" not in cexevent.run("t85") and len(starts) == 1
