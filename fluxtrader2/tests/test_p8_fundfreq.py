"""Decision BU1's source audit (`ft2/fundfreq.py`) on planted parquets, no network: an interval change is an event at the first settlement
at the new interval; the trailing-day funding's sign and the trigger row; a batch day (≥ 5 shortenings) is flagged; a contract younger than 30
days at t0 is a launch, not an event; F1's event is listed and not frozen, F3's and F5's are frozen in their lists; a lengthening is paired to
its shortening; the notice join (a cached detail, no fetch) dates a notice-era event and leaves the rule era blank; the bars count, the run-up
row reads the day BEFORE t0 only; the audit writes its counts."""
import json

import numpy as np
import pandas as pd

from ft2 import data, fundfreq

H = pd.Timedelta("1h")


def _settle(symbol, first, last, interval_h, rate=0.0001):
    ts = pd.date_range(first, last, freq=f"{int(interval_h)}h", tz="UTC", inclusive="left")
    return pd.DataFrame({"symbol": symbol, "ts": ts, "rate": rate, "interval_h": float(interval_h)})


def _bars(symbol, first, last, close=10.0, step_bps=0.0):
    t = pd.date_range(first, last, freq="5min", tz="UTC", inclusive="left")
    px = close * (1 + step_bps / 1e4) ** np.arange(len(t))
    return pd.DataFrame({"symbol": symbol, "open_time": t, "open": px, "high": px, "low": px, "close": px, "volume": 100.0, "quote_volume": 1000.0})


def _plant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(data, "PROC", tmp_path / "data")
    monkeypatch.setattr(data, "RAW", tmp_path / "data" / "raw")
    monkeypatch.setattr(fundfreq, "OUT", tmp_path / "output" / "fundfreq")
    monkeypatch.setattr(fundfreq, "LISTS", {"f34": tmp_path / "fundfreq_f34.csv", "f5": tmp_path / "fundfreq_f5.csv"})
    monkeypatch.setattr(fundfreq, "CMS_DIR", tmp_path / "data" / "raw" / "external" / "binance_cms")
    (tmp_path / "data" / "raw" / "external" / "binance_cms" / "detail").mkdir(parents=True)
    # AAA: 8h from 2023-01, a shortening 8 → 4 on 2024-10-10 08:00 (F3) after a day of −0.3 % funding (the floor), back to 8 on 2024-10-15 (F3)
    a1 = _settle("AAAUSDT", "2023-01-01", "2024-10-09 08:00", 8)
    a2 = _settle("AAAUSDT", "2024-10-09 08:00", "2024-10-10 08:00", 8, rate=-0.003)
    a3 = _settle("AAAUSDT", "2024-10-10 08:00", "2024-10-15 00:00", 4, rate=-0.001)
    a4 = _settle("AAAUSDT", "2024-10-15 00:00", "2025-12-31", 8)
    # BBB: a shortening 4 → 1 on 2025-11-20 13:00 (F4, the rule era, no notice), the longs paying (+0.2 % a day), then back to 4 h 40 h later
    b1 = _settle("BBBUSDT", "2025-01-01", "2025-11-19 13:00", 4)
    b2 = _settle("BBBUSDT", "2025-11-19 13:00", "2025-11-20 13:00", 4, rate=0.0005)
    b3 = _settle("BBBUSDT", "2025-11-20 13:00", "2025-11-22 05:00", 1, rate=0.0002)
    b4 = _settle("BBBUSDT", "2025-11-22 05:00", "2025-12-31", 4)
    # YYY: a contract 10 days old at its shortening (a launch)
    y1 = _settle("YYYUSDT", "2025-06-01", "2025-06-11", 8)
    y2 = _settle("YYYUSDT", "2025-06-11", "2025-07-01", 4, rate=-0.002)
    # FFF: F5's shortening (frozen in f5); the slice has no 2026 bars
    f1 = _settle("FFFUSDT", "2024-01-01", "2026-03-01", 8)
    f2 = _settle("FFFUSDT", "2026-03-01", "2026-04-01", 1, rate=-0.001)
    # the 2023-10-12 batch: six names shortened on one day at zero funding (F1 — listed, not frozen, batch)
    batch = [pd.concat([_settle(f"B{i}USDT", "2022-06-01", "2023-10-12 08:00", 8), _settle(f"B{i}USDT", "2023-10-12 08:00", "2024-01-01", 4)]) for i in range(6)]
    F = pd.concat([a1, a2, a3, a4, b1, b2, b3, b4, y1, y2, f1, f2, *batch], ignore_index=True)
    F["symbol"] = F["symbol"].astype("category")
    F.to_parquet(tmp_path / "data" / "funding_archive.parquet", index=False)
    # bars: AAA rises 2 % over the day before t0 against flat peers; BBB flat; the peers (PPP, QQQ) flat; YYY from its launch day
    bars = pd.concat([_bars("AAAUSDT", "2024-09-01", "2024-10-30", close=10.0, step_bps=0.0),
                      _bars("BBBUSDT", "2025-10-01", "2025-12-31"), _bars("PPPUSDT", "2024-09-01", "2025-12-31"), _bars("QQQUSDT", "2024-09-01", "2025-12-31"),
                      _bars("YYYUSDT", "2025-06-01", "2025-08-01"), _bars("FFFUSDT", "2025-01-01", "2025-12-31")], ignore_index=True)
    # AAA's run-up: the bars over [t0 − 24 h, t0) 2 % above the bar before them
    t0 = pd.Timestamp("2024-10-10 08:00", tz="UTC")
    m = (bars["symbol"] == "AAAUSDT") & (bars["open_time"] >= t0 - pd.Timedelta(days=1))
    bars.loc[m, ["open", "high", "low", "close"]] = 10.2
    bars["symbol"] = bars["symbol"].astype("category")
    bars.to_parquet(tmp_path / "data" / "candles_5m_archive.parquet", index=False)
    M = pd.DataFrame({"block": pd.to_datetime(["2024-10-01", "2024-10-01", "2024-10-01", "2025-11-01", "2025-11-01"], utc=True),
                      "block_end": pd.to_datetime(["2024-11-01", "2024-11-01", "2024-11-01", "2025-12-01", "2025-12-01"], utc=True),
                      "symbol": ["AAAUSDT", "PPPUSDT", "QQQUSDT", "PPPUSDT", "QQQUSDT"], "folds": "F3+F4"})
    monkeypatch.setattr(fundfreq, "member_symbols", lambda: M)
    # a cached notice naming AAA, released 30 h before its t0; the list file holds the title
    lst = [{"id": 1, "code": "c1", "title": "Funding Rate Settlement Frequency of USDⓈ-M AAAUSDT Perpetual Contract Will Be Adjusted (2024-10-10)",
            "releaseDate": int(pd.Timestamp("2024-10-09 02:00", tz="UTC").timestamp() * 1000)},
           {"id": 2, "code": "c2", "title": "Binance Will List Something (SMTH)", "releaseDate": int(pd.Timestamp("2024-10-09", tz="UTC").timestamp() * 1000)}]
    (fundfreq.CMS_DIR / "list_49_20261101.json").write_text(json.dumps(lst))
    (fundfreq.CMS_DIR / "detail" / "c1.json").write_text(json.dumps({"seoDesc": "", "body": json.dumps({"node": "root", "child": [{"node": "text", "text": "the frequency of AAAUSDT changes at 2024-10-10 08:00 (UTC)"}]})}))


def test_events_flags_and_the_frozen_lists(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    E = fundfreq.events()
    k = E.set_index(["symbol", "t0"])
    a = k.loc[("AAAUSDT", pd.Timestamp("2024-10-10 08:00", tz="UTC"))]
    assert a["dir"] == "shorter" and a["prev_h"] == 8 and a["new_h"] == 4 and a["fold"] == "F3" and a["why"] == "eligible"
    assert a["at_floor"] and abs(a["fund_1d"] - (-0.003 * 3)) < 1e-12 and a["n_1d"] == 3     # the three settlements of the day before t0 (t0 − 24 h, t0 − 16 h, t0 − 8 h)
    assert a["cap_share_7d"] > 0 and a["member_at_t0"] and not a["batch"]
    assert pd.Timestamp(a["notice_release"]) == pd.Timestamp("2024-10-09 02:00", tz="UTC") and abs(a["notice_lag_h"] - 30) < 1e-9
    al = k.loc[("AAAUSDT", pd.Timestamp("2024-10-15 00:00", tz="UTC"))]
    assert al["dir"] == "longer" and pd.Timestamp(al["pair_of"]) == pd.Timestamp("2024-10-10 08:00", tz="UTC") and abs(al["episode_h"] - 112) < 1e-9
    b = k.loc[("BBBUSDT", pd.Timestamp("2025-11-20 13:00", tz="UTC"))]
    assert b["dir"] == "shorter" and b["fold"] == "F4" and not b["at_floor"] and b["fund_1d"] > 0 and pd.isna(b["notice_release"]) and not b["member_at_t0"]
    y = k.loc[("YYYUSDT", pd.Timestamp("2025-06-11 00:00", tz="UTC"))]
    assert y["why"].startswith("the contract younger")
    f = k.loc[("FFFUSDT", pd.Timestamp("2026-03-01 00:00", tz="UTC"))]
    assert f["fold"] == "F5" and f["why"] == "eligible"
    bt = E[E["symbol"].str.startswith("B") & (E["symbol"] != "BBBUSDT")]
    assert len(bt) == 6 and bt["batch"].all() and (bt["fold"] == "F1").all() and bt["why"].str.startswith("outside").all()
    f34 = pd.read_csv(fundfreq.OUT / "fundfreq_f34.csv")
    f5 = pd.read_csv(fundfreq.OUT / "fundfreq_f5.csv")
    assert sorted(f34["symbol"]) == ["AAAUSDT", "AAAUSDT", "BBBUSDT", "BBBUSDT"] and list(f5["symbol"]) == ["FFFUSDT"]
    assert list(f34.columns) == fundfreq.LIST_COLS


def test_bars_runup_costs_and_the_audit(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    fundfreq.events()
    for tag in ("f34", "f5"):
        (fundfreq.OUT / f"fundfreq_{tag}.csv").replace(fundfreq.LISTS[tag])
    rep = fundfreq.bars()
    assert rep["events"] == 5 and rep["complete"] == 4 and rep["missing_symbols"] == ["FFFUSDT"]      # F5's 2026 bars are not in the slice
    L = fundfreq.frozen()
    ru = fundfreq.runup(L, fundfreq.member_symbols()).set_index(["symbol", "t0"])
    r = ru.loc[("AAAUSDT", pd.Timestamp("2024-10-10 08:00", tz="UTC"))]
    assert abs(r["own_bps"] - 200) < 1 and abs(r["peers_bps"]) < 1e-6 and abs(r["runup_bps"] - 200) < 1 and r["n_peers"] == 2
    assert np.isnan(ru.loc[("FFFUSDT", pd.Timestamp("2026-03-01", tz="UTC")), "own_bps"])
    assert fundfreq.cost_rows(L).empty       # no cost_daily_wide planted → an empty frame, not a crash
    md = fundfreq.audit(today=pd.Timestamp("2026-11-01 12:00", tz="UTC"))
    J = json.loads((fundfreq.OUT / "audit.json").read_text())
    assert J["events"] == 5 and J["shortenings"] == 3 and J["lengthenings"] == 2 and J["by_fold_dir"]["F3"] == {"longer": 1, "shorter": 1}
    assert J["shortenings_by_fold_at_floor"]["F4"]["False"] == 1 and J["shortenings_by_fold_at_floor"]["F3"]["True"] == 1 and J["notice_era"]["with_notice"] == 1 and J["notice_era"]["rule_era_without_notice"] == 2
    assert J["lengthenings_paired"] == 2 and J["candidates"]["F1F2_batch"] == 6 and "fundfreq" in md and (fundfreq.OUT / "runup.csv").exists()
