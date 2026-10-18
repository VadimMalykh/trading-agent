"""AL1 (`ft2/optsrc.py`): the option-price source audit's pure parts — Deribit's instrument names, the strike candidates, the free
days, what a chart answer and an end-of-hour table say — and the report written from a stubbed fetch."""
import json

import numpy as np
import pandas as pd

from ft2 import optsrc as o


def test_names_strikes_and_free_days():
    assert o.expiry_code(pd.Timestamp("2023-06-02", tz="UTC")) == "2JUN23" and o.expiry_code(pd.Timestamp("2024-12-27", tz="UTC")) == "27DEC24"
    assert o.daily_name("BTC", pd.Timestamp("2023-06-02", tz="UTC"), 27250, "C") == "BTC-2JUN23-27250-C"
    ks = o.atm_candidates("BTC", 27239.0)
    assert ks[0] == 27250 and 27000 in ks and 27500 in ks and len(ks) == len(set(ks)) == 6
    assert o.atm_candidates("ETH", 1874.7)[0] == 1875
    fd = o.first_of_months(pd.Timestamp("2023-05-01", tz="UTC"), pd.Timestamp("2024-09-01", tz="UTC"))
    assert len(fd) == 16 and fd[0] == pd.Timestamp("2023-05-01", tz="UTC") and fd[-1] == pd.Timestamp("2024-08-01", tz="UTC")
    assert o.first_of_months(pd.Timestamp("2023-05-02", tz="UTC"), pd.Timestamp("2023-07-01", tz="UTC")) == [pd.Timestamp("2023-06-01", tz="UTC")]


def test_chart_summary_reads_the_open_bar_and_the_traded_bars():
    day = int(pd.Timestamp("2023-06-01", tz="UTC").timestamp() * 1000)
    ticks = [day + i * o.HOUR_MS for i in range(49)]
    vol = [0.0] * 49
    vol[2], vol[3], vol[30] = 0.3, 2.4, 1.0
    cost = [v * 0.005 for v in vol]
    res = {"status": "ok", "ticks": ticks, "open": [0.0085] * 49, "close": [0.0085] * 49, "volume": vol, "cost": cost}
    s = o.chart_summary(res, day)
    assert s["served"] and s["bars"] == 49 and s["bars_with_a_trade"] == 3 and s["day_bars_with_a_trade"] == 2 and s["open_00"] == 0.0085 and not s["traded_00"] and s["vwap_00"] is None
    assert abs(s["day_volume"] - 2.7) < 1e-9
    assert not o.chart_summary({"status": "no_data"}, day)["served"] and not o.chart_summary({"error": {"code": 10020}}, day)["served"]


def test_end_of_hour_straddle_picks_the_next_day_at_the_money():
    rows = []
    for exp in ("230717", "230718", "230719"):
        for k, dc in ((29000, 0.7), (30000, 0.52), (31000, 0.3)):
            rows.append({"symbol": f"BTC-{exp}-{k}-C", "type": "C", "strike": f"{exp}-{k}", "delta": str(dc), "best_bid_price": "230", "best_ask_price": "250", "mark_iv": "0.29", "best_bid_qty": "2", "best_ask_qty": "3"})
            rows.append({"symbol": f"BTC-{exp}-{k}-P", "type": "P", "strike": f"{exp}-{k}", "delta": str(dc - 1), "best_bid_price": "30", "best_ask_price": "45", "mark_iv": "0.33", "best_bid_qty": "1", "best_ask_qty": "5"})
    s = o.summary_straddle(rows, pd.Timestamp("2023-07-18", tz="UTC"))
    assert s["expiry"] == "2023-07-18" and s["strike"] == 30000 and s["call"] == "BTC-230718-30000-C" and s["bid"] == 260 and s["ask"] == 295 and s["spread"] == 35 and s["bid_qty"] == 1
    bs = [{"instrument_name": f"BTC-19OCT26-{k}-{cp}", "bid_price": 0.005, "ask_price": 0.006, "mark_iv": 33.0, "open_interest": 1.0, "volume": 2.0, "underlying_price": 81097.0} for k in (80000, 81000, 82000) for cp in "CP"]
    bs += [{"instrument_name": "BTC-18OCT26-81000-C", "bid_price": 0.001, "ask_price": 0.002, "mark_iv": 30.0, "open_interest": 1.0, "volume": 0.0, "underlying_price": 81097.0}]
    b = o.book_straddle(bs, "BTC", pd.Timestamp("2026-10-19 08:00", tz="UTC"))
    assert b["strike"] == 81000 and b["call"] == "BTC-19OCT26-81000-C" and abs(b["spread"] - 0.002) < 1e-12 and abs(b["spread_over_spot_bps"] - 20) < 1e-9


def test_audit_writes_the_report_from_a_stubbed_fetch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    day = int(pd.Timestamp("2023-06-01", tz="UTC").timestamp() * 1000)

    def fake_get(u, raw=False, timeout=120, retries=5, head_only=False):
        if "PERPETUAL" in u:
            return {"status": "ok", "ticks": [day], "open": [27239.0]}
        if "get_tradingview_chart_data" in u and "27250" in u:
            return {"status": "ok", "ticks": [day + i * o.HOUR_MS for i in range(49)], "open": [0.01] * 49, "close": [0.01] * 49, "volume": [1.0] * 49, "cost": [0.01] * 49}
        if "get_tradingview_chart_data" in u:
            return {"status": "no_data"}
        if "get_instruments" in u:
            return []
        if "get_last_trades" in u:
            return {"trades": []}
        if "get_book_summary" in u:
            return []
        raise AssertionError(u)

    monkeypatch.setattr(o, "_get", fake_get)
    monkeypatch.setattr(o, "PAUSE", 0.0)
    rep = o.audit_deribit(currencies=("BTC",), probe_days=[pd.Timestamp("2023-06-01", tz="UTC")], today=pd.Timestamp("2026-10-18", tz="UTC"))
    assert rep["chart_served_BTC"]["served"] == 1 and rep["chart_probes"]["BTC"][0]["strike"] == 27250 and abs(rep["chart_probes"]["BTC"][0]["straddle_open_00_over_spot_pct"] - 2.0) < 1e-9
    assert (o.RAW_DERIBIT / "chart_probes_20261018.json").exists()
    txt = o._md({"deribit": rep})
    assert "served on 1 of 1 probe days" in txt and "| BTC 2023-06-01 | 27239 | 27250 |" in txt
