"""Decision CG1's source audit (`ft2/govlist.py`) on a planted ranking, planted proposals and planted parquets, no network: the symbol join
keeps one space a base (the busiest) and sends the smaller beside; an EXCLUDED space (the hand check) is out; a space under MIN_PROPOSALS is
out; a derived-token DAO is counted as unreached; t0 = the END and ts_known = created; a follow-up within 7 days is a cell_all False row (a
flag, not a drop); cell_big reads the ≥ 200-voter votes alone; an active proposal, a malformed one and a young perpetual are out; F5's vote
is listed and not frozen; the winner and the kind parse; the frozen lists hold no price; the bars count and rule (a)'s B_i come out of the
audit with no price of a name read after its end."""
import json

import pandas as pd

from ft2 import cost, data, govlist, upgrades

AAVE = "aavedao.eth"


def _s(ts):
    return int(pd.Timestamp(ts, tz="UTC").value // 10**9)


def _bars(symbol, first, last, close=10.0):
    t = pd.date_range(first, last, freq="5min", tz="UTC", inclusive="left")
    return pd.DataFrame({"symbol": symbol, "open_time": t, "open": close, "high": close, "low": close, "close": close, "volume": 100.0, "quote_volume": 1000.0})


def _prop(pid, space, created, start, end, votes, choices=("For", "Against"), scores=(100.0, 10.0), state="closed", flagged=False, title="Grant request for the team"):
    return {"id": pid, "space": {"id": space}, "created": _s(created), "start": _s(start), "end": _s(end), "votes": votes, "scores_total": float(sum(scores)),
            "scores": list(scores), "choices": list(choices), "state": state, "flagged": flagged, "type": "single-choice", "title": title}


RANKING = [
    {"id": AAVE, "name": "Aave DAO", "symbol": "AAA", "verified": True, "proposalsCount": 300, "followersCount": 1000},
    {"id": "aaa-sub.eth", "name": "Aave Grants", "symbol": "AAA", "verified": False, "proposalsCount": 20, "followersCount": 10},     # the smaller space of the same base → beside
    {"id": "fabien.eth", "name": "Fabien", "symbol": "BBB", "verified": False, "proposalsCount": 400, "followersCount": 5},            # EXCLUDED by the hand check
    {"id": "ccc.eth", "name": "Ccc", "symbol": "CCC", "verified": False, "proposalsCount": 3, "followersCount": 5},                   # under MIN_PROPOSALS
    {"id": "yyy.eth", "name": "Yyy DAO", "symbol": "YYY", "verified": True, "proposalsCount": 10, "followersCount": 50},
    {"id": "snapshot.dcl.eth", "name": "Decentraland MANA DAO", "symbol": "VP", "verified": True, "proposalsCount": 2800, "followersCount": 30000},  # a derived-token symbol: unreached, MANA in the name
    {"id": "curve.eth", "name": "Curve Finance", "symbol": "veCRV", "verified": True, "proposalsCount": 900, "followersCount": 3000},                 # a derived-token prefix: unreached, CRV
    {"id": "random.eth", "name": "Random", "symbol": "RND", "verified": False, "proposalsCount": 50, "followersCount": 5},
]
PROPS = [
    _prop("p1", AAVE, "2023-06-07 10:00", "2023-06-08 10:00", "2023-06-11 10:00", 500, title="[ARFC] Grant request for the team"),              # F1, a member, big → the cell
    _prop("p2", AAVE, "2023-06-12 10:00", "2023-06-12 12:00", "2023-06-14 10:00", 50, title="Add XYZ as collateral on V3"),                    # 3 d later → cell_all False; < 200 voters
    _prop("p3", AAVE, "2023-06-28 10:00", "2023-06-28 12:00", "2023-07-01 10:00", 300, choices=("Yes", "No", "Abstain"), scores=(10.0, 90.0, 5.0), title="Treasury buyback programme"),  # 20 d later → both cells; NO wins
    _prop("p4", AAVE, "2026-10-01 10:00", "2026-10-01 12:00", "2026-10-05 10:00", 5, state="active"),                                            # not closed
    _prop("p5", AAVE, "2024-09-28 05:00", "2024-09-28 06:00", "2024-10-02 02:00", 10, flagged=True, title="Gauge weight vote"),                  # F3, not a member, flagged
    _prop("p6", AAVE, "2026-01-29 00:00", "2026-01-29 01:00", "2026-02-02 12:00", 250, title="Elect the council"),                                # F5: listed, not frozen
    _prop("p7", AAVE, "2024-03-10 00:00", "2024-03-05 00:00", "2024-03-08 00:00", 20),                                                           # created after its end: malformed
    _prop("p8", "yyy.eth", "2023-10-29 00:00", "2023-10-29 01:00", "2023-11-01 12:00", 400),                                                     # the perpetual 12 days old → a launch
    _prop("p9", "fabien.eth", "2023-08-01 00:00", "2023-08-01 01:00", "2023-08-04 12:00", 900),                                                  # an excluded space → not loaded
]


def _plant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(data, "PROC", tmp_path / "data")
    monkeypatch.setattr(data, "RAW", tmp_path / "data" / "raw")
    monkeypatch.setattr(govlist, "OUT", tmp_path / "output" / "govlist")
    monkeypatch.setattr(govlist, "SNAP_DIR", tmp_path / "data" / "raw" / "external" / "snapshot")
    monkeypatch.setattr(govlist, "LISTS", {"f12": tmp_path / "govvotes_f12.csv", "f34": tmp_path / "govvotes_f34.csv", "f5": tmp_path / "govvotes_f5.csv"})
    monkeypatch.setattr(govlist, "EXCLUDED", {"fabien.eth": "not Ethereum's governance (a person's space)"})
    monkeypatch.setattr(upgrades, "FIRST", tmp_path / "data" / "raw" / "um_first_month.csv")
    monkeypatch.setattr(cost, "DAILY_WIDE", tmp_path / "data" / "cost_daily_wide.parquet")
    govlist.SNAP_DIR.mkdir(parents=True)
    (govlist.SNAP_DIR / "ranking_20260106.json").write_text(json.dumps(RANKING))
    (govlist.SNAP_DIR / "proposals_20260106.json").write_text(json.dumps(PROPS))
    bars = pd.concat([_bars("AAAUSDT", "2023-01-01", "2024-11-01"), _bars("YYYUSDT", "2023-10-20", "2024-01-01")], ignore_index=True)
    bars["symbol"] = bars["symbol"].astype("category")
    bars.to_parquet(tmp_path / "data" / "candles_5m_archive.parquet", index=False)
    pd.DataFrame({"symbol": ["AAAUSDT", "BBBUSDT", "CCCUSDT", "YYYUSDT", "MANAUSDT", "CRVUSDT"], "first_month": ["2023-01", "2023-01", "2023-01", "2023-10", "2021-01", "2021-01"],
                  "last_month": ["2026-09"] * 6}).to_csv(upgrades.FIRST, index=False)
    days = pd.date_range("2023-06-01", "2024-10-10", freq="D", tz="UTC")
    pd.DataFrame({"symbol": "AAAUSDT", "day": days, "spread_cal_bps": 5.0, "imp_10000": 4.0}).to_parquet(cost.DAILY_WIDE, index=False)   # leg 6.5 → B_i 46
    M = pd.DataFrame({"block": pd.to_datetime(["2023-06-02", "2024-09-28"], utc=True), "block_end": pd.to_datetime(["2023-07-02", "2024-10-28"], utc=True),
                      "symbol": ["AAAUSDT", "CCCUSDT"], "folds": ["F1+F2", "F3+F4"]})
    monkeypatch.setattr(upgrades, "member_symbols", lambda: M)


def test_spaces_join_one_a_base_the_excluded_out_and_the_unreached_counted(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    S = govlist.spaces()
    assert list(S["id"]) == [AAVE, "yyy.eth"] and list(S["base"]) == ["AAA", "YYY"]
    other = pd.read_csv(govlist.OUT / "spaces_other.csv")
    assert set(other["id"]) == {"aaa-sub.eth", "fabien.eth"} and other.set_index("id").loc["fabien.eth", "excluded"].startswith("not Ethereum")
    U = govlist.unreached()
    assert list(U["id"]) == ["snapshot.dcl.eth", "curve.eth"] and list(U["base_in_name"]) == ["MANA", "CRV"]


def test_events_flags_the_collapse_as_flags_and_the_frozen_lists(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    E = govlist.events()
    by = E.set_index("code")
    assert "p9" not in by.index                                                                          # the excluded space's proposals are not loaded
    assert by.loc["p1", "why"] == "eligible" and by.loc["p1", "fold"] == "F1" and bool(by.loc["p1", "member_at_t0"]) and by.loc["p1", "symbol"] == "AAAUSDT"
    assert pd.Timestamp(by.loc["p1", "t0"]) == pd.Timestamp("2023-06-11 10:00", tz="UTC") and pd.Timestamp(by.loc["p1", "ts_known"]) == pd.Timestamp("2023-06-07 10:00", tz="UTC")
    assert abs(by.loc["p1", "lead_d"] - 4.0) < 1e-9 and abs(by.loc["p1", "duration_d"] - 3.0) < 1e-9
    assert by.loc["p1", "winner"] == "For" and bool(by.loc["p1", "passed"]) and by.loc["p1", "kind"] == "grant" and by.loc["p1", "n_choices"] == 2
    assert bool(by.loc["p1", "cell_all"]) and bool(by.loc["p1", "cell_big"]) and by.loc["p1", "repeat_n"] == 0
    assert by.loc["p2", "why"] == "eligible" and not bool(by.loc["p2", "cell_all"]) and not bool(by.loc["p2", "cell_big"]) and by.loc["p2", "kind"] == "listing"   # a flag, not a drop
    assert bool(by.loc["p3", "cell_all"]) and bool(by.loc["p3", "cell_big"]) and by.loc["p3", "winner"] == "No" and not bool(by.loc["p3", "passed"]) and by.loc["p3", "kind"] == "treasury"
    assert by.loc["p4", "why"].startswith("not closed") and by.loc["p7", "why"].startswith("created after its end")
    assert by.loc["p5", "why"] == "eligible" and by.loc["p5", "fold"] == "F3" and not bool(by.loc["p5", "member_at_t0"]) and bool(by.loc["p5", "flagged"]) and by.loc["p5", "kind"] == "gauge"
    assert by.loc["p6", "why"] == govlist.F5_LISTED and bool(by.loc["p6", "cell_all"]) and bool(by.loc["p6", "cell_big"]) and by.loc["p6", "kind"] == "election"
    assert by.loc["p8", "why"].startswith("the perpetual younger")
    f12 = pd.read_csv(govlist.OUT / "govvotes_f12.csv")
    f34 = pd.read_csv(govlist.OUT / "govvotes_f34.csv")
    f5 = pd.read_csv(govlist.OUT / "govvotes_f5.csv")
    assert list(f12.columns) == govlist.LIST_COLS and list(f12["code"]) == ["p1", "p2", "p3"] and list(f34["code"]) == ["p5"] and list(f5["code"]) == ["p6"]
    assert not any(c in ("open", "close", "high", "low", "volume", "scores") for c in f12.columns)       # no price, no tally beyond the winner, in the frozen table


def test_bars_cells_and_the_audits_bar_come_out_with_no_price_read(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    govlist.events()
    for tag in ("f12", "f34", "f5"):
        (govlist.OUT / f"govvotes_{tag}.csv").replace(govlist.LISTS[tag])
    rep = govlist.bars(fetch=False)
    assert rep["events"] == 4 and rep["complete"] == 4 and rep["missing_files_in_fetch_tags"] == 0
    cov = pd.read_csv(govlist.OUT / "bars.csv")
    assert cov["bars"].tolist()[0] == int((pd.Timestamp("2023-06-19 10:00", tz="UTC") - pd.Timestamp("2023-06-07 10:00", tz="UTC")) / pd.Timedelta("5min"))  # the window starts at the creation
    md = govlist.audit(today=pd.Timestamp("2026-11-06", tz="UTC"))
    J = json.loads((govlist.OUT / "audit.json").read_text())
    assert J["events"] == 4 and J["cells_by_fold"]["F1"] == {"cell_all": 2, "cell_big": 2} and J["cells_by_fold"]["F3"] == {"cell_all": 1, "cell_big": 0}
    assert J["bar_rule_a"]["f12 cell_all"]["priced"] == 2 and abs(J["bar_rule_a"]["f12 cell_all"]["B"] - 46.0) < 1e-9     # 2 × 2 × (5 + 6.5)
    assert J["flagged"] == 1 and J["passed_share_all"] == {"passed": 2, "failed": 1, "unparsed": 0} and J["unreached_daos"]["n"] == 2
    assert J["cells_0o_all"]["1"]["f12"]["cells"] == 2 and J["candidates"]["F5_listed_not_frozen"] == 1
    assert "# govlist" in md and not any(c in ("open", "close", "y_1d", "ret") for c in pd.read_csv(govlist.OUT / "costs.csv").columns)   # the audit prices no name after its end
