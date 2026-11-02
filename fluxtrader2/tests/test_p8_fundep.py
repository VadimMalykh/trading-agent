"""Decision BY1's source audit (`ft2/fundep.py`) on planted parquets, no network: an episode is the FIRST settlement at which the 24-hour
sum of the settled rate reaches the threshold, one per run (a new one only after 14 quiet days), the name ≥ 30 days old by the earlier of its
first bar and first settlement; the side from the sum's sign; the exchange's flag joined within ± 7 days; the prior episodes counted; F1's
and F2's episodes frozen in f12, F3's in f34; a launch is not an event; the eligibility rule on the frozen F1+F2 list names every dropped cell
(the calendar's end, the bars); the cost presence; the audit writes its counts and the described thresholds."""
import json

import numpy as np
import pandas as pd

from ft2 import data, fundep, fundfreq

H = pd.Timedelta("1h")


def _settle(symbol, first, last, interval_h, rate=0.0001):
    ts = pd.date_range(first, last, freq=f"{int(interval_h)}h", tz="UTC", inclusive="left")
    return pd.DataFrame({"symbol": symbol, "ts": ts, "rate": rate, "interval_h": float(interval_h)})


def _bars(symbol, first, last, close=10.0):
    t = pd.date_range(first, last, freq="5min", tz="UTC", inclusive="left")
    return pd.DataFrame({"symbol": symbol, "open_time": t, "open": close, "high": close, "low": close, "close": close, "volume": 100.0, "quote_volume": 1000.0})


def _plant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(data, "PROC", tmp_path / "data")
    monkeypatch.setattr(data, "RAW", tmp_path / "data" / "raw")
    monkeypatch.setattr(fundep, "OUT", tmp_path / "output" / "fundep")
    monkeypatch.setattr(fundep, "LISTS", {tag: tmp_path / f"fundep_{tag}.csv" for tag in ("f12", "f34", "f5")})
    monkeypatch.setattr(fundfreq, "CMS_DIR", tmp_path / "data" / "raw" / "external" / "binance_cms")
    (tmp_path / "data").mkdir()
    # AAA (8h, from 2023-01): the shorts pay −0.7 % a settlement for two days from 2023-08-10 00:00 (F1) → the sum reaches −2.1 % at the THIRD
    # settlement (16:00); a second extreme day five days later is the SAME episode (inside 14 quiet days); a third run 2023-09-20 is a new
    # episode (prior 1); AAA is a member of the block holding its first t0
    a = [_settle("AAAUSDT", "2023-01-01", "2023-08-10", 8), _settle("AAAUSDT", "2023-08-10", "2023-08-12", 8, rate=-0.007), _settle("AAAUSDT", "2023-08-12", "2023-08-17", 8),
         _settle("AAAUSDT", "2023-08-17", "2023-08-18", 8, rate=-0.007), _settle("AAAUSDT", "2023-08-18", "2023-09-20", 8),
         _settle("AAAUSDT", "2023-09-20", "2023-09-21", 8, rate=-0.007), _settle("AAAUSDT", "2023-09-21", "2025-12-31", 8)]
    # BBB (F3): the LONGS pay +0.7 % a settlement from 2024-11-05 00:00; the exchange shortens 8 → 4 two days later (the flag, after the crossing)
    b = [_settle("BBBUSDT", "2024-01-01", "2024-11-05", 8), _settle("BBBUSDT", "2024-11-05", "2024-11-07 08:00", 8, rate=0.007),
         _settle("BBBUSDT", "2024-11-07 08:00", "2024-11-10", 4, rate=0.002), _settle("BBBUSDT", "2024-11-10", "2025-12-31", 8)]
    # YYY: a contract 10 days old at its crossing (a launch, not an event)
    y = [_settle("YYYUSDT", "2025-06-01", "2025-06-11", 8), _settle("YYYUSDT", "2025-06-11", "2025-06-13", 8, rate=-0.007), _settle("YYYUSDT", "2025-06-13", "2025-07-01", 8)]
    # CCC (F2): a crossing on 2024-08-29 — the 7-day exit falls after F2's end (dropped by the calendar); DDD (F1): a crossing without bars in the slice
    c = [_settle("CCCUSDT", "2024-01-01", "2024-08-29", 8), _settle("CCCUSDT", "2024-08-29", "2024-08-31", 8, rate=-0.007), _settle("CCCUSDT", "2024-08-31", "2025-12-31", 8)]
    d = [_settle("DDDUSDT", "2023-01-01", "2023-11-02", 8), _settle("DDDUSDT", "2023-11-02", "2023-11-04", 8, rate=-0.007), _settle("DDDUSDT", "2023-11-04", "2025-12-31", 8)]
    F = pd.concat([*a, *b, *y, *c, *d], ignore_index=True)
    F["symbol"] = F["symbol"].astype("category")
    F.to_parquet(tmp_path / "data" / "funding_archive.parquet", index=False)
    bars = pd.concat([_bars("AAAUSDT", "2023-01-01", "2024-01-15"), _bars("BBBUSDT", "2024-10-01", "2024-12-01"), _bars("CCCUSDT", "2024-08-01", "2024-09-15"),
                      _bars("YYYUSDT", "2025-06-01", "2025-08-01"), _bars("PPPUSDT", "2023-01-01", "2025-12-31")], ignore_index=True)
    bars["symbol"] = bars["symbol"].astype("category")
    bars.to_parquet(tmp_path / "data" / "candles_5m_archive.parquet", index=False)
    # cost rows: AAA has a row on its entry day; CCC and DDD none
    cost = pd.DataFrame({"symbol": ["AAAUSDT", "AAAUSDT", "BBBUSDT"], "day": pd.to_datetime(["2023-08-10", "2023-09-20", "2024-11-01"], utc=True), "spread_cal_bps": 5.0, "imp_10000": 2.0})
    cost.to_parquet(tmp_path / "data" / "cost_daily_wide.parquet", index=False)
    from ft2 import cost as costmod
    monkeypatch.setattr(costmod, "DAILY_WIDE", tmp_path / "data" / "cost_daily_wide.parquet")
    M = pd.DataFrame({"block": pd.to_datetime(["2023-05-01", "2023-05-01", "2023-08-01", "2023-08-01", "2024-09-02", "2024-09-02"], utc=True),
                      "block_end": pd.to_datetime(["2023-08-01", "2023-08-01", "2023-09-01", "2023-09-01", "2024-12-01", "2024-12-01"], utc=True),
                      "symbol": ["PPPUSDT", "QQQUSDT", "AAAUSDT", "PPPUSDT", "PPPUSDT", "QQQUSDT"], "folds": ["F1+F2"] * 4 + ["F3+F4"] * 2})
    monkeypatch.setattr(fundep, "member_symbols", lambda: M)


def test_episodes_flags_and_the_frozen_lists(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    E = fundep.events()
    k = E.set_index(["symbol", "t0"])
    a1 = k.loc[("AAAUSDT", pd.Timestamp("2023-08-10 16:00", tz="UTC"))]
    assert a1["side"] == "bought" and a1["fold"] == "F1" and a1["why"] == "eligible" and a1["n_1d"] == 3 and abs(a1["fund_1d"] + 0.021) < 1e-12 and abs(a1["rate_t0"] + 0.007) < 1e-12
    assert a1["interval_h"] == 8 and a1["prior_episodes"] == 0 and a1["member_at_t0"] and not a1["flagged_7d"] and a1["perp_first_source"] == "archive 5m" and a1["perp_age_days"] > 200
    aa = E[E["symbol"] == "AAAUSDT"]
    assert len(aa) == 2 and pd.Timestamp(aa["t0"].iloc[1]) == pd.Timestamp("2023-09-20 16:00", tz="UTC") and aa["prior_episodes"].iloc[1] == 1 and abs(aa["days_since_prior"].iloc[1] - 41) < 1e-9
    b = k.loc[("BBBUSDT", pd.Timestamp("2024-11-05 16:00", tz="UTC"))]
    assert b["side"] == "sold" and b["fold"] == "F3" and b["flagged_7d"] and pd.Timestamp(b["flag_t0"]) == pd.Timestamp("2024-11-07 08:00", tz="UTC") and abs(b["flag_lag_h"] + 40) < 1e-9
    assert b["perp_first_source"] == "funding"                       # BBB's bars begin after its first settlement: the earlier stamp is the settlement's
    assert "YYYUSDT" not in set(E["symbol"])                          # 10 days old at its crossing: a launch, not an event
    c = k.loc[("CCCUSDT", pd.Timestamp("2024-08-29 16:00", tz="UTC"))]
    assert c["fold"] == "F2" and c["why"] == "eligible"
    f12 = pd.read_csv(fundep.OUT / "fundep_f12.csv")
    f34 = pd.read_csv(fundep.OUT / "fundep_f34.csv")
    f5 = pd.read_csv(fundep.OUT / "fundep_f5.csv")
    assert sorted(f12["symbol"]) == ["AAAUSDT", "AAAUSDT", "CCCUSDT", "DDDUSDT"] and list(f34["symbol"]) == ["BBBUSDT"] and len(f5) == 0
    assert list(f12.columns) == fundep.LIST_COLS
    desc = json.loads((fundep.OUT / "events_described.json").read_text())
    assert desc["thr_0.01"]["episodes"] >= len(E) and desc["thr_0.03"]["episodes"] == 0 and desc["count_rule_first_settlement"]["F1"] == 3


def test_eligibility_names_every_dropped_cell_and_the_audit_writes(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    fundep.events()
    for tag in ("f12", "f34", "f5"):
        (fundep.OUT / f"fundep_{tag}.csv").replace(fundep.LISTS[tag])
    L = fundep.frozen()
    assert sorted(L["list"].unique()) == ["f12", "f34"]
    e = fundep.eligibility(L[L["list"] == "f12"].reset_index(drop=True), "f12", fundep.member_symbols()).set_index("symbol")
    assert e.loc["CCCUSDT", "why"] == "the 7-day exit is not before the end"                # 2024-08-29 + 7 d ≥ 2024-09-01
    assert e.loc["DDDUSDT", "why"].startswith("bars under")                                  # no bars in the slice
    assert e.loc["AAAUSDT", "eligible"].all() and pd.Timestamp(e["first_block"].iloc[0]) == pd.Timestamp("2023-05-01", tz="UTC")
    assert (e.loc["AAAUSDT", "cost_source"] == "own day or the day before").all() and e.loc["CCCUSDT", "cost_source"] == "none"
    md = fundep.audit(today=pd.Timestamp("2026-11-02 12:00", tz="UTC"))
    J = json.loads((fundep.OUT / "audit.json").read_text())
    assert J["episodes"] == 5 and J["by_fold_side"]["F1"]["bought"] == 3 and J["by_fold_side"]["F3"]["sold"] == 1 and J["by_fold_flagged_7d"]["F3"]["True"] == 1
    assert J["eligibility_f12"]["cells"] == 4 and J["eligibility_f12"]["eligible"] == 2 and len(J["eligibility_f12"]["dropped"]) == 2 and J["eligibility_f12"]["eligible_members"] == 1
    assert J["f12_per_month"] == {"2023-08": 1, "2023-09": 1, "2023-11": 1, "2024-08": 1} and J["prior_episodes"] == {0: 4, 1: 1} or J["prior_episodes"] == {"0": 4, "1": 1}
    assert J["data_line_need"]["f34"]["complete"] == 1 and J["data_line_need"]["f34"]["files"] == 0 and J["described"]["thr_0.03"]["episodes"] == 0
    assert "fundep" in md and (fundep.OUT / "eligibility_f12.csv").exists() and (fundep.OUT / "audit.md").exists()
