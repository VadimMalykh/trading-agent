"""`ft2/cexflow_other.py` on planted files, no network, no price: the other exchanges' files go through `cexflow`'s OWN event rule — the same
file read through `cexflow.events` and through `cexflow_other.events_of` gives the same rows; the exchange's own token is excluded by name per
exchange; the `…-OwnTokens` leg is out; `cexflow`'s module state is put back after the call and nothing is written under its output folder; the
proxy contract table (the laptop: no `um_first_month.csv`) maps a base by Binance's own events table and a member by its first block; the
pooled table counts the cells, the names and the ±1-day coincidences."""
import json

import pandas as pd

from ft2 import cexflow, cexflow_other as co, data, upgrades


def _s(ts):
    return int(pd.Timestamp(ts, tz="UTC").value // 10**9)


def _raw(path, jump_day="2023-06-10", own="OKB", stamp="00:00", own_leg=True):
    """AAA 2,000 from 2023-04-01 with +10 % on `jump_day` (F1, a member → an inflow cell) and −10 % on 2023-07-10 (AAA no longer a member); the
    exchange's own token jumps the same day; an `…-OwnTokens` leg that would double the own token."""
    days = pd.date_range("2023-04-01", "2023-08-15", freq="D", tz="UTC")
    a, rows, own_rows = 2000.0, [], []
    for d in days:
        ds = f"{d:%Y-%m-%d}"
        if ds == jump_day:
            a *= 1.10
        elif ds == "2023-07-10":
            a *= 0.90
        rows.append({"date": _s(f"{ds} {stamp}"), "tokens": {"AAA": a, own: 500.0 * (1.5 if ds >= jump_day else 1.0)}})
        own_rows.append({"date": _s(f"{ds} {stamp}"), "tokens": {own: 9e9, "AAA": 9e9}})
    ch = {"Ethereum": {"tokens": rows, "tokensInUsd": rows}, "Ethereum-staking": {"tokens": own_rows, "tokensInUsd": own_rows}}
    if own_leg:
        ch["Ethereum-OwnTokens"] = {"tokens": own_rows, "tokensInUsd": own_rows}
    path.write_text(json.dumps({"chainTvls": ch}))


def _plant(tmp_path, monkeypatch, first=True):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(data, "PROC", tmp_path / "data")
    monkeypatch.setattr(data, "RAW", tmp_path / "data" / "raw")
    monkeypatch.setattr(cexflow, "OUT", tmp_path / "output" / "cexflow")
    monkeypatch.setattr(cexflow, "RAW_DIR", tmp_path / "data" / "raw" / "external" / "defillama_cex")
    monkeypatch.setattr(co, "RAW_DIR", tmp_path / "data" / "raw" / "external" / "defillama_cex_other")
    monkeypatch.setattr(co, "OUT", tmp_path / "output" / "cexflow_other")
    monkeypatch.setattr(upgrades, "FIRST", tmp_path / "data" / "raw" / "um_first_month.csv")
    co.RAW_DIR.mkdir(parents=True)
    cexflow.RAW_DIR.mkdir(parents=True)
    if first:
        pd.DataFrame({"symbol": ["AAAUSDT", "OKBUSDT", "GTUSDT"], "first_month": ["2023-01", "2020-01", "2020-01"], "last_month": ["2026-09"] * 3}).to_csv(upgrades.FIRST, index=False)
    M = pd.DataFrame({"block": pd.to_datetime(["2023-06-02", "2023-07-02"], utc=True), "block_end": pd.to_datetime(["2023-07-02", "2023-08-01"], utc=True),
                      "symbol": ["AAAUSDT", "CCCUSDT"], "folds": ["F1+F2", "F1+F2"]})
    monkeypatch.setattr(upgrades, "member_symbols", lambda: M)
    return M


def test_the_same_file_reads_the_same_through_cexflow_and_through_the_other_path_and_the_module_is_put_back(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    _raw(co.RAW_DIR / "okx_2026-11-11.json")
    _raw(cexflow.RAW_DIR / "binance-cex_20261106.json", own_leg=False)                   # the same holdings without the OwnTokens leg, read by cexflow's own path
    cexflow.ingest()
    monkeypatch.setattr(cexflow, "EXCLUDED", {"OKB": "the exchange's own token"})
    ref = cexflow.events(write=False)
    before = (cexflow.series, cexflow.commit_days, cexflow.EXCLUDED, upgrades.contracts, upgrades.contract_for, upgrades.perp_first)
    E, info = co.events_of(co.files(("okx",))["okx"], "okx", co.proxy_or_none())
    assert (cexflow.series, cexflow.commit_days, cexflow.EXCLUDED, upgrades.contracts, upgrades.contract_for, upgrades.perp_first) == before      # put back
    pd.testing.assert_frame_equal(E.drop(columns="exchange"), ref)                                                                                # the same rule, the same rows
    by = E.set_index("code")
    assert by.loc["AAA_20230610_in", "why"] == "eligible" and bool(by.loc["AAA_20230610_in", "member_at_t0"]) and bool(by.loc["AAA_20230610_in", "cell"])
    assert abs(by.loc["AAA_20230610_in", "change"] - 0.10) < 1e-9                                                    # the OwnTokens and staking legs are not in the holding
    assert by.loc["OKB_20230610_in", "why"].startswith("excluded:") and not bool(by.loc["AAA_20230710_out", "member_at_t0"])
    assert info["contracts"] == "um_first_month" and info["chains"] == ["Ethereum"] and info["stamps_off_0000"] == 0 and info["first_daily"].startswith("2023-04-01")
    assert co.fold_counts(E, "in") == {"F1": 1, "F2": 0, "F3": 0, "F4": 0, "F5": 0} and co.fold_counts(E, "out") == {f: 0 for f in co.FOLDS}
    assert not (cexflow.OUT / "events.csv").exists() and not list(cexflow.OUT.glob("cexflow_f*.csv"))               # nothing of Binance's lists written


def test_the_own_token_is_per_exchange_the_proxy_maps_by_binances_table_and_the_pool_counts_the_coincidences(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch, first=False)                                            # the laptop: no um_first_month.csv → the proxy
    _raw(co.RAW_DIR / "okx_2026-11-11.json", jump_day="2023-06-10", own="OKB")
    _raw(co.RAW_DIR / "gate_2026-11-11.json", jump_day="2023-06-11", own="GT")            # the same name a day later on a second exchange
    _raw(co.RAW_DIR / "bybit_2026-11-11.json", jump_day="2023-06-20", own="XXX", stamp="03:30")
    (tmp_path / "output" / "cexflow").mkdir(parents=True)
    pd.DataFrame({"base": ["AAA", "OKB", "GT"], "symbol": ["AAAUSDT", "OKBUSDT", "GTUSDT"], "t0": ["2023-06-10 00:00:00+00:00"] * 3,
                  "perp_first": ["2023-02-01 00:00:00+00:00", "2020-02-01 00:00:00+00:00", "2020-02-01 00:00:00+00:00"], "perp_first_source": ["first_month"] * 3,
                  "why": ["eligible"] * 3, "side": ["in"] * 3, "member_at_t0": [True, False, False], "cell": [True] * 3, "fold": ["F1"] * 3}).to_csv(tmp_path / "output" / "cexflow" / "events.csv", index=False)
    monkeypatch.setattr(co, "BINANCE_EVENTS", tmp_path / "output" / "cexflow" / "events.csv")
    assert co.proxy_or_none() is not None
    md = co.audit(("okx", "gate", "bybit", "kucoin"), binance_events=co.BINANCE_EVENTS)
    rep = json.loads((co.OUT / "audit_other.json").read_text())
    assert rep["contracts"] == "proxy" and rep["unusable"] == {"kucoin": "no file"} and [i["exchange"] for i in rep["exchanges"]] == ["okx", "gate", "bybit"]
    ok, gt, bb = (pd.read_csv(co.OUT / f"events_{s}.csv").set_index("code") for s in ("okx", "gate", "bybit"))
    assert ok.loc["OKB_20230610_in", "why"].startswith("excluded:") and ok.loc["AAA_20230610_in", "why"] == "eligible"
    assert gt.loc["GT_20230611_in", "why"].startswith("excluded:") and gt.loc["AAA_20230611_in", "why"] == "eligible" and gt.loc["AAA_20230611_in", "symbol"] == "AAAUSDT"
    assert abs(bb.loc["AAA_20230620_in", "stamp_hour"] - 3.5) < 1e-9 and rep["exchanges"][2]["stamps_off_0000"] > 0                    # a file whose stamps are not midnight says so
    P = rep["pooled"]["F1F2"]
    assert P["cells"] == 3 and P["names"] == 1 and P["exchanges_with_cells"] == 3 and P["with_another_exchange_within_1d"] == 2         # okx ↔ gate; bybit alone
    assert P["name_days_after_collapsing_1d"] == 2 and P["with_a_binance_inflow_row_within_1d"] == 2 and P["binance_cells"] == 1 and P["names_not_in_binance_cells"] == 0
    assert P["binance_cells_with_another_exchange_within_1d"] == 1 and abs(P["top5_share"] - 1.0) < 1e-12 and rep["pooled"]["cells_F3F4"] == 0
    assert "contracts: **proxy**" in md and not any(c in ("open", "close", "high", "low", "y_1d") for c in pd.read_csv(co.OUT / "events_all.csv").columns)
    p = co.Proxy(co.BINANCE_EVENTS)
    assert p.contract_for(None, "AAA", pd.Timestamp("2024-01-01", tz="UTC")) == "AAAUSDT" and p.contract_for(None, "QQQ", pd.Timestamp("2024-01-01", tz="UTC")) is None
    assert p.contract_for(None, "CCC", pd.Timestamp("2023-07-05", tz="UTC")) == "CCCUSDT"                                               # a member never in Binance's table
    assert p.perp_first(["CCCUSDT"], None)["perp_first_source"].iloc[0] == "member_block" and p.perp_first(["NOPE"], None)["perp_first_source"].iloc[0] == "none"
