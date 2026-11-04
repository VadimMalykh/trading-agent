"""Decision CD1's source audit (`ft2/upgrades.py`) on a planted catalog list, planted detail bodies and planted parquets, no network: the
ticker from the title; the UPGRADE's stamp from the block-height sentence and not the deposit suspension's an hour earlier; a body without a
stamp is out; a notice released after its stated time is out; a follow-up within 7 days of the name's previous event collapses onto it; a
perpetual younger than 30 days at t0 is a launch; F5's event is listed and not frozen; the member flag, the block, the lead and the repeat
count; the frozen lists hold no price; the window's bar count starts at the notice; the fingerprint's void; the audit's counts and the 0o (i)
cells come out with no price of an event's name read."""
import json

import pandas as pd

from ft2 import data, upgrades

H = pd.Timedelta("1h")


def _ms(s):
    return int(pd.Timestamp(s, tz="UTC").value // 10**6)


def _body(t_sus, t_up, height="1,234,567"):
    return json.dumps({"node": "root", "children": [
        {"node": "text", "text": f"Binance will suspend deposits and withdrawals for the token at approximately {t_sus} (UTC)."},
        {"node": "text", "text": f"The network upgrade and hard fork will take place at block height of {height}, or at approximately {t_up} (UTC)."},
        {"node": "text", "text": f"Deposits and withdrawals will be reopened at approximately {t_up} (UTC) after the network is stable."}]})


def _bars(symbol, first, last, close=10.0):
    t = pd.date_range(first, last, freq="5min", tz="UTC", inclusive="left")
    return pd.DataFrame({"symbol": symbol, "open_time": t, "open": close, "high": close, "low": close, "close": close, "volume": 100.0, "quote_volume": 1000.0})


ARTS = [
    # AAA: F1, the perpetual old, a member of the block → eligible; the notice a day ahead, the block-height sentence carries t0
    {"id": 1, "code": "a1", "title": "Binance Will Support the Aaa (AAA) Network Upgrade & Hard Fork - 2023-06-11", "releaseDate": _ms("2023-06-10 04:30"), "body": _body("2023-06-11 09:00", "2023-06-11 10:00")},
    # AAA again 3 days later (a follow-up: collapsed); then 20 days later (a second event, a repeat)
    {"id": 2, "code": "a2", "title": "Binance Will Support the Aaa (AAA) Network Upgrade - 2023-06-14", "releaseDate": _ms("2023-06-13 02:00"), "body": _body("2023-06-14 09:00", "2023-06-14 10:00")},
    {"id": 3, "code": "a3", "title": "Binance Will Support the Aaa (AAA) Network Upgrade", "releaseDate": _ms("2023-06-30 02:00"), "body": _body("2023-07-01 09:00", "2023-07-01 10:00")},
    # BBB: F3, the perpetual by first_month (2024-01 → first 2024-02-01), not a member → eligible (f34)
    {"id": 4, "code": "b1", "title": "Binance Will Support the Bbb (BBB) Network Upgrade & Hard Fork", "releaseDate": _ms("2024-10-01 05:00"), "body": _body("2024-10-02 01:00", "2024-10-02 02:00")},
    # YYY: F1 but the perpetual 12 days old → a launch
    {"id": 5, "code": "y1", "title": "Binance Will Support the Yyy (YYY) Network Upgrade", "releaseDate": _ms("2023-11-01 00:00"), "body": _body("2023-11-01 11:00", "2023-11-01 12:00")},
    # FFF: F5 → listed, not frozen
    {"id": 6, "code": "f1", "title": "Binance Will Support the Fff (FFF) Network Upgrade & Hard Fork", "releaseDate": _ms("2026-02-01 00:00"), "body": _body("2026-02-02 11:00", "2026-02-02 12:00")},
    # CCC: released AFTER its stated time → out
    {"id": 7, "code": "c1", "title": "Binance Will Support the Ccc (CCC) Network Upgrade", "releaseDate": _ms("2024-03-05 12:00"), "body": _body("2024-03-05 09:00", "2024-03-05 10:00")},
    # DDD: no stamp in the body → out
    {"id": 8, "code": "d1", "title": "Binance Will Support the Ddd (DDD) Network Upgrade", "releaseDate": _ms("2024-03-20 12:00"), "body": json.dumps({"node": "text", "text": "Binance will support the upgrade. Deposits are suspended."})},
    # a wallet-maintenance title: not an upgrade; and a ticker we do not list
    {"id": 9, "code": "w1", "title": "Binance Will Suspend Deposits and Withdrawals on the Aaa (AAA) Network", "releaseDate": _ms("2024-05-01 00:00"), "body": ""},
    {"id": 10, "code": "z1", "title": "Binance Will Support the Zzz (QQQ) Network Upgrade", "releaseDate": _ms("2024-05-02 00:00"), "body": _body("2024-05-03 01:00", "2024-05-03 02:00")},
]


def _plant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(data, "PROC", tmp_path / "data")
    monkeypatch.setattr(data, "RAW", tmp_path / "data" / "raw")
    monkeypatch.setattr(upgrades, "OUT", tmp_path / "output" / "upgrades")
    monkeypatch.setattr(upgrades, "LISTS", {"f12": tmp_path / "upgrades_f12.csv", "f34": tmp_path / "upgrades_f34.csv"})
    monkeypatch.setattr(upgrades, "CMS_DIR", tmp_path / "data" / "raw" / "external" / "binance_cms")
    monkeypatch.setattr(upgrades, "FIRST", tmp_path / "data" / "raw" / "um_first_month.csv")
    cms = tmp_path / "data" / "raw" / "external" / "binance_cms"
    (cms / "detail").mkdir(parents=True)
    (cms / "list_157_20261104.json").write_text(json.dumps([{k: a[k] for k in ("id", "code", "title", "releaseDate")} for a in ARTS]))
    for a in ARTS:
        if a["code"] != "z1":                                                                            # one detail missing → fetch=False keeps it 'no_detail'
            (cms / "detail" / f"{a['code']}.json").write_text(json.dumps({"code": a["code"], "title": a["title"], "body": a["body"], "seoDesc": ""}))
    bars = pd.concat([_bars("AAAUSDT", "2023-01-01", "2024-04-01"), _bars("YYYUSDT", "2023-10-20", "2024-01-01"), _bars("FFFUSDT", "2025-01-01", "2025-12-31"),
                      _bars("CCCUSDT", "2023-01-01", "2024-06-01"), _bars("DDDUSDT", "2023-01-01", "2024-06-01")], ignore_index=True)
    bars["symbol"] = bars["symbol"].astype("category")
    bars.to_parquet(tmp_path / "data" / "candles_5m_archive.parquet", index=False)
    pd.DataFrame({"symbol": ["BBBUSDT", "AAAUSDT", "YYYUSDT", "FFFUSDT", "CCCUSDT", "DDDUSDT", "1000AAAUSDT"],
                  "first_month": ["2024-01", "2023-01", "2023-10", "2025-01", "2023-01", "2023-01", "2025-06"], "last_month": ["2026-09"] * 7}).to_csv(upgrades.FIRST, index=False)
    M = pd.DataFrame({"block": pd.to_datetime(["2023-06-02", "2024-09-28"], utc=True), "block_end": pd.to_datetime(["2023-07-02", "2024-10-28"], utc=True),
                      "symbol": ["AAAUSDT", "CCCUSDT"], "folds": ["F1+F2", "F3+F4"]})
    monkeypatch.setattr(upgrades, "member_symbols", lambda: M)


def test_stated_time_reads_the_upgrade_sentence_not_the_suspension():
    t_up, t_sus, how = upgrades.stated_time(upgrades.body_text({"seoDesc": "", "body": _body("2026-10-19 11:59", "2026-10-19 12:59", "6,470,279")}))
    assert t_up == pd.Timestamp("2026-10-19 12:59", tz="UTC") and t_sus == pd.Timestamp("2026-10-19 11:59", tz="UTC") and how == "upgrade_sentence"
    t_up, t_sus, how = upgrades.stated_time("Starting at approximately 2025-01-01 10:00 (UTC), Binance will suspend deposits to support its network upgrade and hard fork. "
                                            "The upgrade will take place at the block height of 840,360. Withdrawals reopen at approximately 2025-01-01 12:00 (UTC).")
    assert how == "suspension_only" and pd.isna(t_up) and t_sus == pd.Timestamp("2025-01-01 10:00", tz="UTC")
    t_up, t_sus, how = upgrades.stated_time(upgrades.body_text({"seoDesc": "", "body": json.dumps({"node": "root", "children": [
        {"node": "text", "text": "This will take place at 2023-11-08 15:00 (UTC).&nbsp;"},
        {"node": "text", "text": "Deposits and withdrawals of token(s) on the aforementioned network will be suspended approximately starting from 2023-11-08 14:00 (UTC)."}]})}))
    assert how == "upgrade_sentence" and t_up == pd.Timestamp("2023-11-08 15:00", tz="UTC") and t_sus == pd.Timestamp("2023-11-08 14:00", tz="UTC")
    parts = upgrades.per_name("The MANTRA (OM) network upgrade will take place at the block height of 9,664,888. Binance will suspend the deposits of token(s) on the MANTRA (OM) network "
                              "starting from approximately 2025-10-27 07:51 (UTC). The MultiversX (EGLD) network upgrade will take place at approximately 2025-10-30 17:00 (UTC). "
                              "Binance will suspend the deposits on the MultiversX network starting from approximately 2025-10-30 16:00 (UTC).",
                              "Binance Will Support the MANTRA (OM) and MultiversX (EGLD) Network Upgrades")
    assert set(parts) == {"OM", "EGLD"} and upgrades.stated_time(parts["OM"])[2] == "suspension_only"
    assert upgrades.stated_time(parts["EGLD"]) == (pd.Timestamp("2025-10-30 17:00", tz="UTC"), pd.Timestamp("2025-10-30 16:00", tz="UTC"), "upgrade_sentence")
    t_up, t_sus, how = upgrades.stated_time("no stamp here")
    assert pd.isna(t_up) and how == "none"


def test_events_flags_and_the_frozen_lists(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    D = upgrades.details(fetch=False, write=False)
    assert len(D) == 9 and set(D["tick"]) == {"AAA", "BBB", "YYY", "FFF", "CCC", "DDD", "QQQ"} and not D[D["code"] == "z1"]["has_detail"].iloc[0]
    E = upgrades.events()
    assert "QQQ" not in set(E["tick"])                                                                   # no perpetual of ours
    by = E.set_index("code")
    assert by.loc["a1", "why"] == "eligible" and by.loc["a1", "fold"] == "F1" and bool(by.loc["a1", "member_at_t0"]) and by.loc["a1", "hardfork"]
    assert pd.Timestamp(by.loc["a1", "t0"]) == pd.Timestamp("2023-06-11 10:00", tz="UTC") and pd.Timestamp(by.loc["a1", "t_suspend"]) == pd.Timestamp("2023-06-11 09:00", tz="UTC")
    assert pd.Timestamp(by.loc["a1", "ts_known"]) == pd.Timestamp("2023-06-10 04:30", tz="UTC") and abs(by.loc["a1", "lead_d"] - (29.5 / 24)) < 1e-9
    assert pd.Timestamp(by.loc["a1", "block"]) == pd.Timestamp("2023-06-02", tz="UTC") and by.loc["a1", "symbol"] == "AAAUSDT"   # the plain name over 1000AAAUSDT
    assert by.loc["a2", "why"].startswith("a follow-up within 7 days") and by.loc["a3", "why"] == "eligible" and by.loc["a3", "repeat_n"] == 2 and by.loc["a1", "repeat_n"] == 0
    assert by.loc["b1", "why"] == "eligible" and by.loc["b1", "fold"] == "F3" and not bool(by.loc["b1", "member_at_t0"]) and by.loc["b1", "perp_first_source"] == "first_month"
    assert pd.Timestamp(by.loc["b1", "perp_first"]) == pd.Timestamp("2024-02-01", tz="UTC") and pd.Timestamp(by.loc["b1", "block"]) == pd.Timestamp("2024-09-28", tz="UTC")   # the block exists; the name is not in it
    assert by.loc["y1", "why"].startswith("the perpetual younger") and by.loc["f1", "why"] == "outside F1 … F4 (F5: listed, not frozen)"
    assert by.loc["c1", "why"] == "released after its stated time (not known ahead)" and by.loc["d1", "why"] == "no stated time in the body"
    f12 = pd.read_csv(upgrades.OUT / "upgrades_f12.csv")
    f34 = pd.read_csv(upgrades.OUT / "upgrades_f34.csv")
    assert list(f12.columns) == upgrades.LIST_COLS and list(f12["code"]) == ["a1", "a3"] and list(f34["code"]) == ["b1"]
    assert not any(c in ("open", "close", "high", "low", "volume") for c in f12.columns)                 # no price in the frozen table


def test_bars_fingerprint_cells_and_the_audit(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    upgrades.events()
    for tag in ("f12", "f34"):
        (upgrades.OUT / f"upgrades_{tag}.csv").replace(upgrades.LISTS[tag])                               # the freeze, by hand
    L = upgrades.frozen()
    cov = upgrades.coverage(L).set_index("symbol")
    a1 = cov.loc["AAAUSDT"].iloc[0]
    assert pd.Timestamp(upgrades.windows(L).set_index("symbol").loc["AAAUSDT"].iloc[0]["a"]) == pd.Timestamp("2023-06-09 10:00", tz="UTC")   # t0 − 2 d (the notice is later)
    assert a1["expected"] == int((pd.Timestamp("2023-06-19 10:00", tz="UTC") - pd.Timestamp("2023-06-09 10:00", tz="UTC")) / pd.Timedelta("5min")) and a1["bars"] == a1["expected"]
    assert cov.loc["BBBUSDT", "bars"] == 0
    rep = upgrades.bars(fetch=False)
    assert rep["complete"] == 2 and rep["missing_months_in_fetch_tags"] == {} and rep["missing_symbols"] == ["BBBUSDT"]   # F3+F4's months are decision CE's
    rep = upgrades.bars(fetch=False, fetch_tags=("f34",))
    assert rep["missing_months_in_fetch_tags"] == {"BBBUSDT": ["2024-09", "2024-10"]}
    from ft2 import krlist
    fp = krlist.fingerprint()
    d = pd.read_parquet(tmp_path / "data" / "candles_5m_archive.parquet")
    d.loc[d.index[5], "close"] += 1.0
    d.to_parquet(tmp_path / "data" / "candles_5m_archive.parquet", index=False)
    assert not krlist.fingerprint_check(fp)["pass"]
    md = upgrades.audit(today=pd.Timestamp("2026-11-04 15:00", tz="UTC"))
    J = json.loads((upgrades.OUT / "audit.json").read_text())
    assert J["events"] == 3 and J["distinct_names"] == 2 and J["by_fold_hardfork"] == {"F1": {"False": 1, "True": 1}, "F3": {"False": 0, "True": 1}}
    assert J["by_fold_first_repeat"]["F1"] == {"first": 1, "repeat": 1} and J["members_at_t0"] == 2 and J["stated_how"] == {"upgrade_sentence": 3}
    assert J["t0_minus_suspend_h"]["q10_50_90"] == [1.0, 1.0, 1.0] and J["lead_negative"] == 0
    assert J["cells_0o"]["f12"] == {"frozen": 2, "hold_inside_market": 2, "bars_complete": 2, "cells": 2, "dropped_by_market_end": []}
    assert J["cells_0o"]["f34"]["cells"] == 0 and J["candidates"]["F5_listed_not_frozen"] == 1
    assert "Known-at" in md and "releaseDate" in J["known_at"]
