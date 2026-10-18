"""R51 unit tests for `scripts/r51_unlocks.py` on made-up schedules and bars: the point-in-time event table from made-up snapshots
(an event as the last page at least 7 days before it; a page that did not list the protocol yet promises nothing; a cliff today's file
moved stays an event with `today` = not as dated; a cliff only today's file has is the hindsight set), the label identity, a planted
fall into and after the cliff recovered on the right rows by stage 1 and CONFIRMED by stage 2 on fresh events, and a world without the
plant clearing nothing (stage 2 NOTHING TO CONFIRM without loading a bar). No network, no real bar."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import horizon, listing

READ = Path(__file__).resolve().parents[1] / "scripts" / "r51_unlocks.py"
D = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
BAR = pd.Timedelta("5min")
A, B = D("2023-05-03"), D("2023-10-01")                       # the stage window the made-up world covers (inside F1)
NAMES = ["AAAUSDT", "BBBUSDT", "M1USDT", "M2USDT", "M3USDT", "M4USDT", "M5USDT", "M6USDT", "M7USDT", "M8USDT", "BTCUSDT"]
AAA_DAYS = [D(f"2023-{m:02d}-15") for m in (5, 6, 7, 8, 9)]
BBB_DAYS = [D(f"2023-{m:02d}-01") for m in (6, 7, 8, 9)]


def _module():
    spec = importlib.util.spec_from_file_location("r51_unlocks", READ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _tables():
    """Today's schedule and the snapshots. AAA: cliffs on the 15th 2023-05 → 2023-09, every page lists it; its 2023-07-25 cliff is in
    today's file only (hindsight). BBB: cliffs on the 1st 2023-06 → 2023-09 plus 2023-05-05; the 2023-04-01 page does not list BBB yet
    (its May cliff is promised by no page: uncovered → not an event); today's file has the 2023-08-01 cliff moved to 2023-08-20 (the
    promised one stays an event, `today` = not as dated; the moved one is NOT an event: no page promised it)."""
    def rows(pid, name, sym, days, asof=None, tokens=50.0, max_supply=1000.0, recipient="Team", kind="cliff"):
        return [{"pid": pid, "name": name, "symbol": sym, "gecko_id": sym.lower(), "max_supply": max_supply, "ts": d, "kind": kind, "recipient": recipient, "category": "", "tokens": tokens, **({"asof": asof} if asof is not None else {})} for d in days]
    fin = pd.DataFrame(rows("1", "Aaa", "AAA", [*AAA_DAYS, D("2023-07-25")]) + rows("2", "Bbb", "BBB", [D("2023-05-05"), D("2023-06-01"), D("2023-07-01"), D("2023-08-20"), D("2023-09-01")], recipient="Investors")
                       + rows("1", "Aaa", "AAA", [D("2023-06-10")], tokens=0.5))        # dust: under 0.1 % of the maximum supply
    snaps = []
    for at in (D("2023-04-01 12:00"), D("2023-05-01 12:00"), D("2023-06-01 12:00"), D("2023-07-01 12:00"), D("2023-08-01 12:00")):
        snaps += rows("1", "Aaa", "AAA", AAA_DAYS, asof=at)
        if at >= D("2023-05-01"):
            snaps += rows("2", "Bbb", "BBB", [D("2023-05-05"), *BBB_DAYS], asof=at, recipient="Investors")
    asof = pd.DataFrame(snaps)
    return fin, asof


def _members(path):
    blocks = pd.date_range("2023-05-03", "2023-10-01", freq="30D", tz="UTC")
    rows = [{"block": b, "symbol": s, "liq_musd": 100 + i, "vol_pct": 5 + 0.1 * i, "play": 1 + 0.1 * i, "age_days": 100 * (i + 1)} for b in blocks for i, s in enumerate(NAMES[:-1])]
    pd.DataFrame(rows).to_csv(path, index=False)


def _world(events_days: dict, plant: bool, seed=0, sd=0.001, into_bps=-2000.0, after_bps=-1500.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(D("2023-05-01 00:05"), B, freq="5min", tz="UTC", inclusive="left", name="t")
    n, k = len(idx), len(NAMES)
    r = rng.normal(0, sd, (n, k))
    if plant:
        for sym, days in events_days.items():
            j = NAMES.index(sym)
            for d in days:
                a0, a1 = idx.searchsorted(d - 7 * pd.Timedelta(days=1)), idx.searchsorted(d)
                r[a0:a1, j] += into_bps / 1e4 / max(a1 - a0, 1)
                b0, b1 = idx.searchsorted(d), idx.searchsorted(d + pd.Timedelta(days=1))
                r[b0:b1, j] += after_bps / 1e4 / max(b1 - b0, 1)
    close = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=NAMES)
    dv = pd.DataFrame(1e6, index=idx, columns=NAMES)
    M = bt.Market(close, close * 1.001, close * 0.999, dv)
    rate = np.where(np.arange(n)[:, None] % 96 == 0, rng.normal(1.0, 2.0, (n, k)), 0.0)
    days = pd.date_range(idx[0].floor("D"), idx[-1].floor("D"), freq="D", tz="UTC")                    # a cost row every day: the harness prices every trade
    one = np.ones((len(days), k))
    C = bt.Costs(days, one * 1.5, one * 0, one, np.cumsum(rate, axis=0), np.cumsum(rate * close.to_numpy(), axis=0))
    return M, C


def test_the_point_in_time_table_takes_what_a_page_promised_a_week_ahead_and_nothing_else(tmp_path):
    m = _module()
    fin, asof = _tables()
    _members(tmp_path / "m.csv")
    ev = m.promised_events(fin, asof, m.members_df(tmp_path / "m.csv", "f12"))
    assert ev["perp"].tolist().count("AAAUSDT") == 5 and ev["perp"].tolist().count("BBBUSDT") == 4 and len(ev) == 9
    assert D("2023-05-05") not in set(ev["day"]) and D("2023-07-25") not in set(ev["day"]) and D("2023-08-20") not in set(ev["day"])   # uncovered; hindsight only; moved — never promised
    assert D("2023-06-10") not in set(ev["day"])                                                                                           # dust
    assert (ev["asof"] <= ev["day"] - pd.Timedelta(days=7)).all() and ev["lead_days"].min() >= 7
    assert ev.set_index("day").loc[D("2023-08-01"), "today"] == "not as dated" and (ev[ev["day"] != D("2023-08-01")]["today"] == "same").all()
    assert ev.set_index("day").loc[D("2023-05-15"), "asof"] == D("2023-05-01 12:00")                                                        # the LAST page at least 7 days before
    assert set(ev["fold"]) == {"F1"} and (ev["pct_max"] == 5.0).all()
    h = m.hindsight_events(fin, asof, m.members_df(tmp_path / "m.csv", "f12"), ev)
    assert set(h["day"]) == {D("2023-05-05"), D("2023-07-25"), D("2023-08-20")}                                                      # what today's file has and no page promised
    ev.to_csv(tmp_path / "ev.csv", index=False)
    back = m.load_events(tmp_path / "ev.csv")
    assert m.reproduce(back, ev)["same"]


def test_the_window_the_shifts_and_the_label_identity():
    m = _module()
    days = m.event_days(A, B)
    assert days[0] == D("2023-05-10") and days[-1] + 7 * pd.Timedelta(days=1) + 2 * BAR <= B and days[-1] + 8 * pd.Timedelta(days=1) + 2 * BAR > B
    ks = m.shifts(len(days))
    assert ks[0] == 15 and ks[-1] == len(days) - 15 and len(ks) == len(days) - 29
    M, C = _world({}, plant=False)
    fr = m.Frame(M, C, pd.DataFrame({"block": [D("2023-05-03")] * 10, "symbol": NAMES[:-1]}), A, B)
    assert fr.span == len(days) and fr.mid[0] == D("2023-05-02") and fr.mid[-1] == (B - BAR).floor("D")
    sh = fr.shifted_days(pd.DatetimeIndex([days[0], days[-1]]), 15)
    assert sh[0] == days[15] and sh[1] == days[14]                                                                                         # circular inside the window
    E = pd.DataFrame({"perp": ["AAAUSDT", "BBBUSDT"], "day": [D("2023-06-15"), D("2023-07-01")]})
    real = fr.rows(E["perp"].to_numpy(), pd.DatetimeIndex(E["day"]))
    for name, h in m.ROWS.items():
        t = pd.DatetimeIndex(E["day"]) - (7 * pd.Timedelta(days=1) if name.startswith("into") else pd.Timedelta(0))
        full = horizon.labels(M, C, h, bt.LATENCY)[1]
        own = full.to_numpy()[M.index.get_indexer(t), M.columns.get_indexer(E["perp"])]
        assert np.allclose(real[name]["a"], own, atol=1e-9)
        peers = [np.nanmean(np.delete(full.to_numpy()[M.index.get_indexer([tt])[0], :10], i)) for tt, i in zip(t, (0, 1))]
        assert np.allclose(real[name]["b"], peers, atol=1e-9) and (real[name]["n_b"] == 9).all()                                            # the block's members, the name itself left out


def _stage1(m, tmp_path, plant, seed=0):
    fin, asof = _tables()
    _members(tmp_path / "m.csv")
    ev = m.promised_events(fin, asof, m.members_df(tmp_path / "m.csv", "f12"))
    ev.to_csv(tmp_path / "ev.csv", index=False)
    M, C = _world({"AAAUSDT": AAA_DAYS, "BBBUSDT": BBB_DAYS}, plant=plant, seed=seed)
    out = tmp_path / "out"
    s = m.stage1(frozen=tmp_path / "ev.csv", members_csv=tmp_path / "m.csv", fold_names=["F1"], out=out, state_daily=None, market=(M, C), tables=(fin, asof),
                 min_members=4, min_events=5, draws=300, window=(A, B))
    return s, out, (M, C), (fin, asof)


def test_a_planted_fall_into_and_after_the_cliff_clears_stage_1_on_the_right_rows_and_is_confirmed_by_stage_2(tmp_path):
    m = _module()
    s, out, market, tables = _stage1(m, tmp_path, plant=True)
    v = s["validity"]
    assert v["status"] == "PASS" and v["1_list_reproduces"]["same"] and v["2_asof_at_or_before_D_minus_7d"] and v["6_shifts"] == v["6_shifts_expected"]
    assert all(d["max_abs_diff_horizon"] <= 1e-9 and d["max_abs_diff_harness"] <= 1e-9 and d["same_cells"] for d in v["3_identity"].values())
    assert v["events_eligible"] == 9 and min(v["4_label_share"].values()) == 1.0 and min(v["5_min_members"].values()) == 9
    tab = pd.DataFrame(s["rows"]).set_index("row")
    assert (tab["M_c"] < 0).all() and (tab.loc[["into_7d", "after_1d", "after_3d"], "u"] < -2).all(), tab[["M_c", "se", "u", "p_family", "verdict"]]
    assert tab.loc["into_7d", "M_c"] < -1200 and tab.loc["after_1d", "M_c"] < -900                                                    # the planted sizes, less what the peers moved
    assert (tab["verdict"] == "CLEARS").sum() >= 3 and tab.loc["after_1d", "verdict"] == "CLEARS" and tab.loc["into_7d", "verdict"] == "CLEARS"
    assert s["run_stage2"] and {c["row"] for c in s["cleared"]} >= {"into_7d", "after_1d"} and all(c["sign"] == -1 for c in s["cleared"])
    assert all((out / f).exists() for f in ("stage1.md", "stage1.json", "validity.json", "rows.csv", "shifts.parquet", "events_labelled.csv"))
    text = (out / "stage1.md").read_text()
    assert "CLEARS" in text and "stage 2 RUNS" in text and "hindsight set" in text and "not as dated" in text
    desc = s["described"]
    assert any(r["split"] == "today: not as dated" and r["n"] == 1 for r in desc["splits"]) and desc["n_hindsight"] == 3
    assert any(r["row"] == "after_7d" and r["side"] == "sold" and r["net"] > 0 for r in desc["money"])                               # the sold position earns the planted fall less its costs
    # stage 2 on FRESH events of the same world (the F3+F4 list stands in for F3+F4's members): the cleared rows one-sided, CONFIRMED
    fin, asof = tables
    ev2 = m.load_events(tmp_path / "ev.csv")
    ev2.to_csv(tmp_path / "ev2.csv", index=False)
    s2 = m.stage2(frozen=tmp_path / "ev2.csv", members_csv=tmp_path / "m.csv", fold_names=["F1"], out=out, market=market, tables=tables, min_members=4, min_events=5, window=(A, B))
    assert s2["verdict"] == "CONFIRMED" and s2["confirmed"] and s2["stage1_written"] == s["written"] and s2["validity"]["status"] == "PASS"
    res = pd.DataFrame(s2["rows"]).set_index("row")
    assert res.loc["after_1d", "verdict"] == "CLEARS" and res.loc["after_1d", "signed_u"] > 2 and res.loc["after_1d", "p_family"] <= 0.05
    assert (out / "stage2.md").exists() and (out / "rows_f34.csv").exists() and "CONFIRMED" in (out / "stage2.md").read_text()


def test_a_world_without_the_plant_clears_nothing_and_stage_2_has_nothing_to_confirm(tmp_path):
    m = _module()
    s, out, _, _ = _stage1(m, tmp_path, plant=False, seed=7)
    assert s["validity"]["status"] == "PASS" and s["cleared"] == [] and not s["run_stage2"]
    tab = pd.DataFrame(s["rows"]).set_index("row")
    assert (tab["verdict"] != "CLEARS").all() and (tab["u"].abs() < 3.5).all(), tab[["M_c", "se", "u", "p_family", "verdict"]]
    assert (tab["centre"].abs() < 1.5 * tab["se"]).all()                                                                                 # the shifted dates' mean sits near zero on a null world
    s2 = m.stage2(frozen=tmp_path / "ev.csv", members_csv=tmp_path / "m.csv", fold_names=["F1"], out=out, market=None, tables=None, window=(A, B))   # loads nothing: the stub
    assert s2["verdict"] == "NOTHING TO CONFIRM" and not s2["confirmed"] and not (out / "rows_f34.csv").exists()
    assert "NOTHING TO CONFIRM" in (out / "stage2.md").read_text()


def test_the_gates():
    m = _module()
    r = {"M_c": -300.0, "se": 100.0, "u": -3.0, "p_family": 0.01, "M_c_F1": -400.0, "M_c_F2": -200.0, "M_trim_c": -250.0}
    assert m.verdict1(r, ["F1", "F2"]) == "CLEARS"
    assert m.verdict1({**r, "M_c_F2": 50.0}, ["F1", "F2"]) == "NOT DETECTABLE"                                                           # one fold the other sign
    assert m.verdict1({**r, "p_family": 0.2}, ["F1", "F2"]) == "NOT DETECTABLE"
    assert m.verdict1({"M_c": 5.0, "se": 10.0, "u": 0.5, "p_family": 0.9, "M_c_F1": 5.0, "M_c_F2": 5.0, "M_trim_c": 5.0}, ["F1", "F2"]) == "CLOSED"
    assert m.verdict2(-300.0, 100.0, 0.01, -1, -400.0, 3.0, -250.0) == "CLEARS"
    assert m.verdict2(-300.0, 100.0, 0.01, -1, -400.0, 3.0, +20.0) == "NOT CLEAR"                                                        # the trimmed mean turned
    assert m.verdict2(+100.0, 100.0, 0.9, -1, -400.0, -1.0, 100.0) == "REFUTED"                                                          # the interval wholly above half the stage-1 fact
    assert m.verdict2(-100.0, 100.0, 0.4, -1, -400.0, 1.0, -100.0) == "NOT DETECTABLE"
    assert m.verdict2(np.nan, 100.0, 0.4, -1, -400.0, 1.0, -100.0) == "NOT READABLE"
