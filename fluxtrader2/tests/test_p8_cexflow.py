"""Decision CK1's source audit (`ft2/cexflow.py`) on a planted raw file, planted parquets and planted member blocks, no network: the per-chain
balances sum per token and the staking chain is out; a ≥ 5 % jump is a row with its side, a 3 % one is not; a second jump within 7 days is a
cell False row (a flag, not a drop); the series' first 30 days and a gap between stamps are out by reason; an EXCLUDED base is out with its
reason; a young perpetual is out; F5's jump is listed and not frozen; the list-commit flag reads the wallet list's git log; `revert_3d` is in
events.csv and NOT in the frozen lists; the frozen lists hold no price; the known-at probe reads two files as identical or rewritten; the
bars count and rule (a)'s B_i come out of the audit with no price of a name read after its t0."""
import json

import pandas as pd

from ft2 import cexflow, cost, data, upgrades


def _s(ts):
    return int(pd.Timestamp(ts, tz="UTC").value // 10**9)


def _bars(symbol, first, last, close=10.0):
    t = pd.date_range(first, last, freq="5min", tz="UTC", inclusive="left")
    return pd.DataFrame({"symbol": symbol, "open_time": t, "open": close, "high": close, "low": close, "close": close, "volume": 100.0, "quote_volume": 1000.0})


def _raw(path, tweak=None, extra_day=False):
    """AAA: 1,000 on Ethereum + 1,000 on Binance from 2023-04-01, stamps at 00:07 UTC; the jumps planted on the Ethereum leg."""
    days = pd.date_range("2023-04-01", "2023-08-15", freq="D", tz="UTC")
    if extra_day:
        days = days.append(pd.DatetimeIndex([pd.Timestamp("2023-08-16", tz="UTC")]))
    eth, bnb_, yyy, zzz = {}, {}, {}, {}
    a = 1000.0
    for d in days:
        ds = d.strftime("%Y-%m-%d")
        if ds == "2023-04-15":
            a *= 1.50            # the series 14 days old → warm-up
        elif ds == "2023-06-10":
            a *= 1.10            # the leg 1,500 of 2,500 → +6 % of the holding: F1, a member → the cell (in)
        elif ds == "2023-06-12":
            a *= 1.20            # 2 days later, +12.5 % → a row, cell False, flag_10
        elif ds == "2023-06-20":
            a *= 1.05            # +3 % of the holding: under the threshold → no row
        elif ds == "2023-07-01":
            a *= 0.85            # −10 % of the holding: the out side → its own cell
        elif ds == "2023-07-02":
            a /= 0.85            # the revert of the out jump (described); an in row in the NEXT block, where AAA is not a member → cell True, member False
        elif ds == "2023-07-20":
            a *= 1.15            # the stamp after a 2-day gap → undated
        eth[ds] = a
    for d in list(days):
        ds = d.strftime("%Y-%m-%d")
        if ds == "2023-07-19":
            del eth[ds]          # the gap before 07-20
    rows_eth = [{"date": _s(f"{ds} 00:07"), "tokens": {"AAA": v, "BNB": 5000.0 * (1.2 if ds == "2023-06-10" else 1.0), "YYY": 300.0 * (1.1 if ds == "2023-06-10" else 1.0)}} for ds, v in eth.items()]
    rows_bnb = [{"date": _s(f"{ds} 00:07"), "tokens": {"AAA": 1000.0}} for ds in eth]
    usd_eth = [{"date": r["date"], "tokens": {k: v * 2.0 for k, v in r["tokens"].items()}} for r in rows_eth]
    usd_bnb = [{"date": r["date"], "tokens": {k: v * 2.0 for k, v in r["tokens"].items()}} for r in rows_bnb]
    stk = [{"date": _s(f"{ds} 00:07"), "tokens": {"AAA": 99999.0}} for ds in eth]
    zdays = pd.date_range("2026-01-01", "2026-03-01", freq="D", tz="UTC")
    z = [{"date": _s(f"{d:%Y-%m-%d} 00:07"), "tokens": {"ZZZ": 100.0 * (1.3 if d >= pd.Timestamp("2026-02-15", tz="UTC") else 1.0)}} for d in zdays]
    d = {"chainTvls": {"Ethereum": {"tokens": rows_eth, "tokensInUsd": usd_eth}, "Binance": {"tokens": rows_bnb, "tokensInUsd": usd_bnb},
                       "Ethereum-staking": {"tokens": stk, "tokensInUsd": stk}, "Solana": {"tokens": z, "tokensInUsd": z}}}
    if tweak:
        tweak(d)
    path.write_text(json.dumps(d))


def _plant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(data, "PROC", tmp_path / "data")
    monkeypatch.setattr(data, "RAW", tmp_path / "data" / "raw")
    monkeypatch.setattr(cexflow, "OUT", tmp_path / "output" / "cexflow")
    monkeypatch.setattr(cexflow, "RAW_DIR", tmp_path / "data" / "raw" / "external" / "defillama_cex")
    monkeypatch.setattr(cexflow, "LISTS", {"f12": tmp_path / "cexflow_f12.csv", "f34": tmp_path / "cexflow_f34.csv", "f5": tmp_path / "cexflow_f5.csv"})
    monkeypatch.setattr(cexflow, "EXCLUDED", {"BNB": "the exchange's own token"})
    monkeypatch.setattr(upgrades, "FIRST", tmp_path / "data" / "raw" / "um_first_month.csv")
    monkeypatch.setattr(cost, "DAILY_WIDE", tmp_path / "data" / "cost_daily_wide.parquet")
    cexflow.RAW_DIR.mkdir(parents=True)
    _raw(cexflow.RAW_DIR / "binance-cex_20261106.json")
    (cexflow.RAW_DIR / "adapter_commits_20261106.json").write_text(json.dumps({"config.js": [{"date": "2023-07-01T10:00:00Z", "sha": "abc", "message": "add wallet"}], "index.js": []}))
    bars = _bars("AAAUSDT", "2023-01-01", "2023-09-01")
    bars["symbol"] = bars["symbol"].astype("category")
    bars.to_parquet(tmp_path / "data" / "candles_5m_archive.parquet", index=False)
    pd.DataFrame({"symbol": ["AAAUSDT", "BNBUSDT", "YYYUSDT", "ZZZUSDT"], "first_month": ["2023-01", "2020-01", "2023-06", "2024-01"], "last_month": ["2026-09"] * 4}).to_csv(upgrades.FIRST, index=False)
    days = pd.date_range("2023-04-01", "2023-09-01", freq="D", tz="UTC")
    pd.DataFrame({"symbol": "AAAUSDT", "day": days, "spread_cal_bps": 5.0, "imp_10000": 4.0}).to_parquet(cost.DAILY_WIDE, index=False)   # leg 6.5 → B_i 46
    M = pd.DataFrame({"block": pd.to_datetime(["2023-06-02", "2023-07-02"], utc=True), "block_end": pd.to_datetime(["2023-07-02", "2023-08-01"], utc=True),
                      "symbol": ["AAAUSDT", "CCCUSDT"], "folds": ["F1+F2", "F1+F2"]})
    monkeypatch.setattr(upgrades, "member_symbols", lambda: M)


def test_ingest_sums_the_chains_and_leaves_the_staking_leg_out(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    rep = cexflow.ingest()
    assert rep["bases"] == 4 and rep["chains"] == 3 and "Ethereum-staking" not in set(pd.read_parquet(data.PROC / "cex_balance.parquet")["chain"])
    S = cexflow.series().set_index(["base", "stamp"])
    assert abs(S.loc[("AAA", pd.Timestamp("2023-05-01 00:07", tz="UTC")), "amount"] - 2500.0) < 1e-9 and S.loc[("AAA", pd.Timestamp("2023-05-01 00:07", tz="UTC")), "chains_n"] == 2


def test_events_flags_sides_reasons_and_the_frozen_lists(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    cexflow.ingest()
    E = cexflow.events()
    by = E.set_index("code")
    r = by.loc["AAA_20230610_in"]
    assert r["why"] == "eligible" and r["fold"] == "F1" and bool(r["member_at_t0"]) and r["symbol"] == "AAAUSDT" and r["side"] == "in" and bool(r["cell"])
    assert abs(r["change"] - 0.10 * 1500 / 2500) < 1e-9 and abs(r["stamp_hour"] - 7 / 60) < 1e-9 and not bool(r["flag_10"]) and not bool(r["list_commit"]) and not bool(r["revert_3d"])
    assert pd.Timestamp(r["t0"]) == pd.Timestamp("2023-06-10 00:07", tz="UTC") and pd.Timestamp(r["ts_known"]) == pd.Timestamp(r["t0"])
    r2 = by.loc["AAA_20230612_in"]
    assert r2["why"] == "eligible" and not bool(r2["cell"]) and bool(r2["flag_10"]) and r2["repeat_n"] == 1 and abs(r2["days_since_prior"] - 2.0) < 1e-9
    assert "AAA_20230620_in" not in by.index                                                                     # 3 % is under the threshold
    r3 = by.loc["AAA_20230701_out"]
    assert r3["why"] == "eligible" and r3["side"] == "out" and bool(r3["cell"]) and bool(r3["list_commit"]) and bool(r3["revert_3d"])   # the commit's day; the revert next day
    assert by.loc["AAA_20230415_in", "why"].startswith("the series younger") and by.loc["AAA_20230720_in", "why"].startswith("the previous stamp more than")
    assert by.loc["BNB_20230610_in", "why"].startswith("excluded:") and by.loc["YYY_20230610_in", "why"].startswith("the perpetual younger")
    assert by.loc["ZZZ_20260215_in", "why"] == cexflow.F5_LISTED and bool(by.loc["ZZZ_20260215_in", "cell"])
    f12 = pd.read_csv(cexflow.OUT / "cexflow_f12.csv")
    f5 = pd.read_csv(cexflow.OUT / "cexflow_f5.csv")
    assert list(f12.columns) == cexflow.LIST_COLS and sorted(f12["code"]) == ["AAA_20230610_in", "AAA_20230612_in", "AAA_20230701_out", "AAA_20230702_in"] and list(f5["code"]) == ["ZZZ_20260215_in"]
    assert "revert_3d" not in f12.columns and not any(c in ("open", "close", "high", "low", "volume", "y_1d") for c in f12.columns)   # post-t0 and price out of the frozen table
    assert (cexflow.OUT / "cexflow_f34.csv").exists() and len(pd.read_csv(cexflow.OUT / "cexflow_f34.csv")) == 0


def test_knownat_reads_identical_and_rewritten(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    _raw(cexflow.RAW_DIR / "binance-cex_20261113.json", extra_day=True)
    rep = cexflow.knownat()
    assert rep["differ"] == 0 and rep["verdict"].startswith("IDENTICAL") and len(rep["stamps_only_in_newer"]) == 1 and rep["in_both"] > 100
    def tweak(d):
        d["chainTvls"]["Ethereum"]["tokens"][40]["tokens"]["AAA"] *= 1.01
    _raw(cexflow.RAW_DIR / "binance-cex_20261120.json", tweak=tweak, extra_day=True)
    rep = cexflow.knownat()
    assert rep["differ"] == 1 and rep["verdict"].startswith("REWRITTEN") and len(rep["differ_sample"]) == 1


def test_knownat_the_older_files_live_point_is_not_a_removal(tmp_path, monkeypatch):
    """The first fetch carries the adapter's run at fetch time as its last stamp (07:02:23 on 2026-11-06); the next fetch holds the day's
    00:00 point instead — IDENTICAL, the live point reported; a day's point gone from the middle of the history is still a removal."""
    _plant(tmp_path, monkeypatch)
    def live(d):
        for ch in ("Ethereum", "Binance"):
            for key in ("tokens", "tokensInUsd"):
                last = d["chainTvls"][ch][key][-1]
                d["chainTvls"][ch][key].append({"date": _s("2026-03-01 07:02:23"), "tokens": dict(last["tokens"])})
    _raw(cexflow.RAW_DIR / "binance-cex_20261106.json", tweak=live)      # the older, re-planted with a live point
    _raw(cexflow.RAW_DIR / "binance-cex_20261113.json", extra_day=True)  # the newer: the day's point, no live point
    rep = cexflow.knownat()
    assert rep["verdict"].startswith("IDENTICAL") and rep["differ"] == 0 and rep["stamps_only_in_older"] == []
    assert rep["live_point_older"] == "2026-03-01 07:02:23+00:00" and rep["live_point_keys"] == 4 and rep["keys_only_in_older"] == 4
    def gone(d):
        for ch in ("Ethereum", "Binance"):
            for key in ("tokens", "tokensInUsd"):
                d["chainTvls"][ch][key] = [r for r in d["chainTvls"][ch][key] if r["date"] != _s("2023-05-10 00:07")]
    _raw(cexflow.RAW_DIR / "binance-cex_20261120.json", tweak=gone, extra_day=True)
    rep = cexflow.knownat()
    assert rep["verdict"].startswith("REWRITTEN") and rep["stamps_only_in_older"] == ["2023-05-10 00:07:00+00:00"] and rep["live_point_older"] is None


def test_bars_cells_and_the_audits_bar_come_out_with_no_price_read(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    cexflow.ingest()
    cexflow.events()
    for tag in ("f12", "f34", "f5"):
        (cexflow.OUT / f"cexflow_{tag}.csv").replace(cexflow.LISTS[tag])
    rep = cexflow.bars(fetch=False)
    assert rep["events"] == 4 and rep["complete"] == 4 and rep["missing_files_in_fetch_tags"] == 0
    md = cexflow.audit(today=pd.Timestamp("2026-11-06", tz="UTC"))
    J = json.loads((cexflow.OUT / "audit.json").read_text())
    assert J["events"] == 4 and J["population_members_in"] == {"cells": 1, "by_fold": {"F1": 1}, "names": 1}
    assert J["cells_by_fold_side_member"]["F1"] == {"in False": 1, "in True": 1, "out True": 1}
    assert J["bar_rule_a"]["f12 in members"]["priced"] == 1 and abs(J["bar_rule_a"]["f12 in members"]["B"] - 46.0) < 1e-9
    assert J["cells_0o_members_in"]["1"]["f12"]["cells"] == 1 and J["flags"]["list_commit"] == 2 and J["revert_3d_described"]["share_all"] > 0
    assert J["known_at_probe"]["verdict"].startswith("not run") and J["candidates"]["F5_listed_not_frozen"] == 1
    assert "# cexflow" in md and not any(c in ("open", "close", "y_1d", "ret") for c in pd.read_csv(cexflow.OUT / "costs.csv").columns)
