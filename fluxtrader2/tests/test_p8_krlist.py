"""Decision BM1's source audit (`ft2/krlist.py`) on planted parquets, no network: a market listed before the window and a thin market's
late first bar are not events; a perpetual younger than 30 days at t0 is a launch, not a listing; F5's event is listed and not frozen; the two
venues' order is read into `first_korean`; the member flag; the window's bar count and the missing months; the fingerprint's void; the audit's
counts and crowd-size rows come out with no price of an event's name read."""
import json

import numpy as np
import pandas as pd

from ft2 import data, krlist, krw

H = pd.Timedelta("1h")
KRW_COLS = ["venue", "market", "symbol", "ts", "ts_known", "open", "high", "low", "close", "volume_krw", "volume", "last_tick"]


def _krw(venue, market, symbol, first, hours, px=1000.0, vol=1e8):
    ts = pd.date_range(first, periods=hours, freq="h", tz="UTC")
    return pd.DataFrame({"venue": venue, "market": market, "symbol": symbol, "ts": ts, "ts_known": ts + H, "open": px, "high": px, "low": px, "close": px,
                         "volume_krw": vol, "volume": vol / px, "last_tick": ts + pd.Timedelta(minutes=30)})[KRW_COLS]


def _bars(symbol, first, last, close=10.0):
    t = pd.date_range(first, last, freq="5min", tz="UTC", inclusive="left")
    return pd.DataFrame({"symbol": symbol, "open_time": t, "open": close, "high": close, "low": close, "close": close, "volume": 100.0, "quote_volume": 1000.0})


def _plant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(data, "PROC", tmp_path / "data")
    monkeypatch.setattr(data, "RAW", tmp_path / "data" / "raw")
    monkeypatch.setattr(krlist, "OUT", tmp_path / "output" / "krlist")
    monkeypatch.setattr(krlist, "FIRST", tmp_path / "data" / "raw" / "um_first_month.csv")
    monkeypatch.setattr(krlist, "LISTS", {"f12": tmp_path / "krlistings_f12.csv", "f34": tmp_path / "krlistings_f34.csv"})
    (tmp_path / "data" / "raw").mkdir(parents=True)
    fx = 1400.0
    bit = pd.concat([_krw("bithumb", "KRW-BTC", "BTCUSDT", "2023-04-01 00:00", 24 * 1000, px=30000 * fx),       # listed before the window
                     _krw("bithumb", "KRW-OGN", "OGNUSDT", "2023-04-01 03:00", 24 * 900),                        # a thin market's late first trade
                     _krw("bithumb", "KRW-AAA", "AAAUSDT", "2023-06-10 05:00", 24 * 400, px=10 * fx, vol=5e8),  # F1: the perpetual old → eligible, first_korean
                     _krw("bithumb", "KRW-YYY", "YYYUSDT", "2023-11-01 00:00", 24 * 300),                        # the perpetual 12 days old → a launch
                     _krw("bithumb", "KRW-FFF", "FFFUSDT", "2026-02-01 00:00", 24 * 100),                        # F5: listed, not frozen
                     _krw("bithumb", "KRW-USDT", None, "2023-12-07 00:00", 24 * 900, px=fx)], ignore_index=True)
    upb = pd.concat([_krw("upbit", "KRW-BTC", "BTCUSDT", "2023-04-01 00:00", 24 * 1000, px=30000 * fx),
                     _krw("upbit", "KRW-AAA", "AAAUSDT", "2024-03-05 02:00", 24 * 300, px=10 * fx),              # F2: the second Korean venue → first_korean False
                     _krw("upbit", "KRW-BBB", "BBBUSDT", "2024-10-01 07:00", 24 * 300, px=2 * fx)], ignore_index=True)   # F3: the perpetual by first_month
    bit.to_parquet(krw.parquet_path("bithumb"), index=False)
    upb.to_parquet(krw.parquet_path("upbit"), index=False)
    bars = pd.concat([_bars("BTCUSDT", "2023-03-01", "2024-06-01", close=30000.0), _bars("AAAUSDT", "2023-01-01", "2024-04-01"),
                      _bars("YYYUSDT", "2023-10-20", "2024-01-01"), _bars("FFFUSDT", "2025-01-01", "2025-12-31")], ignore_index=True)
    bars["symbol"] = bars["symbol"].astype("category")
    bars.to_parquet(tmp_path / "data" / "candles_5m_archive.parquet", index=False)
    pd.DataFrame({"symbol": ["BBBUSDT", "AAAUSDT", "ZZZUSDT"], "first_month": ["2024-01", "2023-01", "2025-01"], "last_month": ["2026-09"] * 3}).to_csv(krlist.FIRST, index=False)
    M = pd.DataFrame({"block": pd.to_datetime(["2023-06-02", "2024-02-28"], utc=True), "block_end": pd.to_datetime(["2023-07-02", "2024-03-29"], utc=True),
                      "symbol": ["AAAUSDT", "CCCUSDT"], "folds": "F1+F2"})
    monkeypatch.setattr(krlist, "member_symbols", lambda: M)


def test_events_flags_and_the_frozen_lists(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    E = krlist.events()
    by = E.set_index(["venue", "market"])
    assert by.loc[("bithumb", "KRW-OGN"), "why"].startswith("before the window's margin")
    assert ("bithumb", "KRW-BTC") not in by.index and ("upbit", "KRW-BTC") not in by.index          # first bar AT the fetch start: not a candidate
    assert by.loc[("bithumb", "KRW-YYY"), "why"].startswith("the perpetual younger")
    assert by.loc[("bithumb", "KRW-FFF"), "why"] == "outside F1 … F4 (F5: listed, not frozen)"
    el = E[E["why"] == "eligible"]
    assert set(zip(el["venue"], el["market"])) == {("bithumb", "KRW-AAA"), ("upbit", "KRW-AAA"), ("upbit", "KRW-BBB")}
    a1, a2, b = by.loc[("bithumb", "KRW-AAA")], by.loc[("upbit", "KRW-AAA")], by.loc[("upbit", "KRW-BBB")]
    assert bool(a1["first_korean"]) and not bool(a2["first_korean"]) and bool(b["first_korean"])
    assert pd.Timestamp(a2["other_venue_t0"]) == pd.Timestamp("2023-06-10 05:00", tz="UTC")
    assert bool(a1["member_at_t0"]) and not bool(a2["member_at_t0"])
    assert a1["perp_first_source"] == "archive 5m" and a1["perp_age_days"] == (pd.Timestamp("2023-06-10 05:00", tz="UTC") - pd.Timestamp("2023-01-01", tz="UTC")).days
    assert b["perp_first_source"] == "first_month" and pd.Timestamp(b["perp_first"]) == pd.Timestamp("2024-02-01", tz="UTC")
    assert a1["fold"] == "F1" and a2["fold"] == "F2" and b["fold"] == "F3"
    assert pd.Timestamp(a1["ts_known"]) == pd.Timestamp(a1["t0"]) + H
    f12 = pd.read_csv(krlist.OUT / "krlistings_f12.csv")
    f34 = pd.read_csv(krlist.OUT / "krlistings_f34.csv")
    assert list(f12.columns) == krlist.LIST_COLS and len(f12) == 2 and len(f34) == 1 and set(f34["market"]) == {"KRW-BBB"}
    assert not any("close" in c or "open" in c for c in f12.columns)                                   # no price in the frozen table


def test_bars_coverage_fingerprint_and_audit(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    krlist.events()
    for tag in ("f12", "f34"):
        (krlist.OUT / f"krlistings_{tag}.csv").replace(krlist.LISTS[tag])                              # the freeze, by hand
    L = krlist.frozen()
    cov = krlist.coverage(L)
    c = cov.set_index(["venue", "market"])
    assert c.loc[("bithumb", "KRW-AAA"), "bars"] == krlist.EXPECTED_BARS == 2880
    assert c.loc[("upbit", "KRW-AAA"), "bars"] == 2880 and c.loc[("upbit", "KRW-BBB"), "bars"] == 0
    need = krlist.missing_months(cov)
    assert need == {"BBBUSDT": ["2024-09", "2024-10"]}
    rep = krlist.bars(fetch=False)
    assert rep["complete_before"] == 2 and rep["missing_before"] == need
    fp = krlist.fingerprint()
    assert set(fp["symbol"]) == {"BTCUSDT", "AAAUSDT", "YYYUSDT", "FFFUSDT"}
    assert krlist.fingerprint_check(fp)["pass"]
    d = pd.read_parquet(tmp_path / "data" / "candles_5m_archive.parquet")
    d.loc[d.index[5], "close"] += 1.0                                                                  # one planted change → void
    d.to_parquet(tmp_path / "data" / "candles_5m_archive.parquet", index=False)
    chk = krlist.fingerprint_check(fp)
    assert not chk["pass"] and chk["changed"][0]["why"] == "changed"
    md = krlist.audit(today=pd.Timestamp("2026-10-24 12:00", tz="UTC"))
    J = json.loads((krlist.OUT / "audit.json").read_text())
    assert J["events"] == 3 and J["by_fold_venue"] == {"F1": {"bithumb": 1, "upbit": 0}, "F2": {"bithumb": 0, "upbit": 1}, "F3": {"bithumb": 0, "upbit": 1}}
    assert J["by_fold_first_korean"]["F2"] == {"False": 1, "True": 0}
    assert J["members_at_t0"] == 1 and J["candidates"]["F5_listed_not_frozen"] == 1 and J["bars_complete"] == 2
    cs = pd.read_csv(krlist.OUT / "crowd_size.csv").set_index(["venue", "market"])
    r = cs.loc[("bithumb", "KRW-AAA")]
    assert r["t0_hour_kst"] == 14                                                                       # 05:00 UTC = 14:00 KST
    assert np.isclose(r["venue_usdt_d1"], 24 * 5e8 / 1400.0, rtol=1e-6)                                 # the FX through KRW-BTC over BTCUSDT (no KRW-USDT yet)
    assert np.isclose(r["binance_quote_d1"], 24 * 12 * 1000.0) and np.isclose(r["share_d1"], (24 * 5e8 / 1400.0) / (24 * 12 * 1000.0), rtol=1e-6)
    assert "Known-at" in md and "final at t0 + 1 h" in J["known_at"]
