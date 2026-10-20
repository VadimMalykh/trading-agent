"""Decision BB1 (i)'s source audit (`ft2/krw.py`) on planted candles, no network: the paging walks backwards from `to` in 200-candle calls
and keeps the oldest-first union inside the window (Upbit's `Z` suffix, Bithumb's none); the ingest drops the bucket in progress, stamps
`ts_known` = start + 1 h and keeps the last tick; the premium is the planted gap — the adjusted one through KRW-USDT, the BTC-relative one
through BTC's own ratio with no control, the 1000× contract divided; the alignment check reads the planted ticks; the audit's cover, member
breadth and tables come out and the DATA.md row names the venue."""
import json

import numpy as np
import pandas as pd

from ft2 import coinbase as cb
from ft2 import krw

T0 = pd.Timestamp("2023-05-01", tz="UTC")
MK = {"KRW-BTC": "BTCUSDT", "KRW-PEPE": "1000PEPEUSDT", "KRW-WLD": "WLDUSDT", "KRW-USDT": None}


def _row(ts: pd.Timestamp, px: float, krw_vol: float = 1e8, tick_offset_s: int = 1800) -> dict:
    return {"market": "x", "candle_date_time_utc": f"{ts:%Y-%m-%dT%H:%M:%S}", "candle_date_time_kst": "", "opening_price": px * 0.999, "high_price": px * 1.001,
            "low_price": px * 0.998, "trade_price": px, "timestamp": int((ts + pd.Timedelta(seconds=tick_offset_s)).timestamp() * 1000), "candle_acc_trade_price": krw_vol,
            "candle_acc_trade_volume": krw_vol / px, "unit": 60}


def _plant(tmp_path, monkeypatch, venue="bithumb", hours=24 * 40, hole=(100, 110)):
    """Month files for four markets (BTC, PEPE, WLD with a hole, USDT) and Binance 5m closes reproducing a planted premium:
    KRW close = Binance ÷ mult × fx × (1 + prem/1e4), fx the KRW-USDT rate."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(krw.data, "RAW", tmp_path / "data" / "raw")
    monkeypatch.setattr(krw.data, "PROC", tmp_path / "data")
    monkeypatch.setattr(cb.data, "PROC", tmp_path / "data")
    monkeypatch.setattr(krw, "markets_of", lambda: dict(MK))
    U = krw.universe(venue)
    U["out"] = tmp_path / "output" / f"krw_{venue}_audit.md"
    ts = pd.date_range(T0, periods=hours, freq="h")
    rng = np.random.default_rng(0)
    fx = 1350.0 + np.cumsum(rng.normal(0, 0.5, hours))
    prem = {"BTCUSDT": 150.0 + 40.0 * np.sin(np.arange(hours) / 7), "1000PEPEUSDT": 400.0 + rng.normal(0, 30, hours), "WLDUSDT": 100.0 + rng.normal(0, 60, hours)}
    bn_px = {"BTCUSDT": 30000 * np.exp(np.cumsum(rng.normal(0, 1e-3, hours))), "1000PEPEUSDT": 1.5 * np.exp(np.cumsum(rng.normal(0, 2e-3, hours))),
             "WLDUSDT": 2.0 * np.exp(np.cumsum(rng.normal(0, 2e-3, hours)))}
    fetched = ts[-1] + 2 * krw.HOUR
    for mk, sym in MK.items():
        (U["raw"] / mk).mkdir(parents=True)
        px = fx if sym is None else bn_px[sym] / krw.cb.mult_of(sym) * fx * (1 + prem[sym] / 1e4)
        keep = np.ones(hours, bool)
        if mk == "KRW-WLD":
            keep[hole[0]:hole[1]] = False
        rows = [_row(t, p) for t, p, k in zip(ts, px, keep) if k]
        rows.append(_row(fetched - pd.Timedelta(minutes=30), 1.0))        # the bucket in progress (its start + 1 h > fetched)
        rows.append(rows[0])                                                # a duplicate
        by = {}
        for r in rows:
            by.setdefault(r["candle_date_time_utc"][:7], []).append(r)
        for m, g in by.items():
            (U["raw"] / mk / f"{m}.json").write_text(json.dumps({"venue": venue, "market": mk, "month": m, "fetched": f"{fetched:%Y-%m-%d %H:%M} UTC", "rows": g}))
    (U["raw"] / "markets_20260101.json").write_text(json.dumps({"rows": [{"market": m, "symbol": s, "listed": True} for m, s in MK.items()]}))
    t5 = pd.date_range(T0 - pd.Timedelta("5min"), periods=hours * 12 + 1, freq="5min")
    c5 = []
    for sym, px in bn_px.items():
        full = np.concatenate([np.repeat(px, 12), px[-1:]]) * (1 + 1e-3 * np.sin(np.arange(hours * 12 + 1)))
        full[12::12] = px                                                   # the 5m bar ending at the END of the hourly bar k
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5, "close": full, "volume": 100.0}))
    pd.concat(c5).to_parquet(tmp_path / "data" / "candles_5m.parquet", index=False)
    return U, ts, prem, fx


def test_paging_walks_backwards_from_to_and_keeps_the_window_oldest_first(monkeypatch):
    calls = []

    def fake(u, **kw):
        calls.append(u)
        to = pd.Timestamp(u.split("to=")[1].split("&")[0].rstrip("Z"), tz="UTC")
        return [_row(to - i * krw.HOUR, 1.0) for i in range(1, krw.MAX_BARS + 1)]              # newest first, strictly before `to`
    monkeypatch.setattr(krw, "_get", fake)
    monkeypatch.setattr(krw.time, "sleep", lambda s: None)
    for venue, suffix in (("upbit", "Z"), ("bithumb", "")):
        calls.clear()
        U = {"api": "x", "to_suffix": suffix, "venue": venue}
        rows = krw._candles(U, "KRW-BTC", T0, T0 + pd.Timedelta(hours=500))
        assert len(calls) == 3 and all(c.endswith(f"T00:00:00{suffix}&count=200") or "to=" in c for c in calls)
        assert calls[0].split("to=")[1].split("&")[0] == f"2023-05-21T20:00:00{suffix}"
        assert len(rows) == 500 and rows[0]["candle_date_time_utc"] == "2023-05-01T00:00:00" and rows[-1]["candle_date_time_utc"] == "2023-05-21T19:00:00"


def test_ingest_drops_the_bucket_in_progress_and_the_premium_is_the_planted_gap(tmp_path, monkeypatch):
    U, ts, prem, fx = _plant(tmp_path, monkeypatch)
    rep = krw.ingest(U)
    assert rep["KRW-BTC"]["rows"] == len(ts) and rep["KRW-BTC"]["in_progress_dropped"] == 1 and rep["KRW-WLD"]["rows"] == len(ts) - 10 and rep["KRW-USDT"]["rows"] == len(ts)
    kr = krw.load(U["parquet"])
    assert list(kr.columns) == krw.COLS and (kr["ts_known"] - kr["ts"] == krw.HOUR).all() and kr["venue"].eq("bithumb").all()
    assert kr["last_tick"].notna().all() and ((kr["last_tick"] - kr["ts"]).dt.total_seconds() == 1800).all()
    stamps = pd.DatetimeIndex(sorted(kr.loc[kr["symbol"].notna(), "ts_known"].unique()))
    bn = cb.binance_close_at(["BTCUSDT", "1000PEPEUSDT", "WLDUSDT"], stamps, ("candles_5m",))
    P = krw.premium(kr, bn, U["mult"])
    for sym in prem:
        g = P[P["symbol"] == sym].set_index("ts_known").sort_index()
        want = pd.Series(prem[sym], index=ts + krw.HOUR).reindex(g.index)
        assert np.allclose(g["prem_adj_bps"], want, atol=1e-6), sym
        want_rel = ((1 + want / 1e4) / (1 + pd.Series(prem["BTCUSDT"], index=ts + krw.HOUR).reindex(g.index) / 1e4) - 1) * 1e4
        assert np.allclose(g["prem_btc_bps"], want_rel, atol=1e-6), sym
        assert np.allclose(g["fx_krw_usdt"], pd.Series(fx, index=ts + krw.HOUR).reindex(g.index), atol=1e-9)
    assert len(P[P["symbol"] == "WLDUSDT"]) == len(ts) - 10
    # without the control the adjusted premium is empty and the BTC-relative one stands
    P2 = krw.premium(kr[kr["market"] != "KRW-USDT"], bn, U["mult"])
    assert P2["prem_adj_bps"].isna().all() and np.isfinite(P2["prem_btc_bps"]).sum() == len(P2)
    a = krw.alignment(kr)
    assert a["share_tick_inside_hour"] == 1.0 and a["median_tick_offset_s"] == 1800


def test_the_audit_counts_the_hole_and_writes_the_tables_and_the_row(tmp_path, monkeypatch):
    U, ts, prem, fx = _plant(tmp_path, monkeypatch)
    krw.ingest(U)
    monkeypatch.setattr(krw.cb, "member_symbols", lambda: pd.DataFrame({"block": [T0, T0, T0 + pd.Timedelta(days=30)], "symbol": ["WLDUSDT", "1000PEPEUSDT", "WLDUSDT"],
                                                                        "block_end": [T0 + pd.Timedelta(days=30)] * 2 + [T0 + pd.Timedelta(days=40)], "folds": ["F1"] * 3}))
    lag = {"venue": "bithumb", "now": str(ts[-1]), "bars_served": 3, "in_progress_served": True, "last_complete_end": str(ts[-1]), "seconds_since_last_complete_end": 20.0}
    txt = krw.audit(U, today=ts[-1] + 3 * krw.HOUR, lag=lag)
    j = json.loads((U["out"].parent / "krw_bithumb_audit.json").read_text())
    cov = pd.DataFrame(j["cover"]).set_index("market")
    assert cov.loc["KRW-WLD", "gaps_over_1h"] == 1 and abs(cov.loc["KRW-WLD", "largest_gap_h"] - 11) < 1e-9 and cov.loc["KRW-BTC", "gaps_over_1h"] == 0
    assert cov.loc["KRW-BTC", "completeness"] > 0.99 and cov.loc["KRW-WLD", "completeness"] < cov.loc["KRW-BTC", "completeness"]
    assert cov.loc["KRW-WLD", "cover_member"] < 1.0 and cov.loc["KRW-PEPE", "cover_member"] == 1.0
    blocks = pd.DataFrame(j["blocks"])
    assert list(blocks["members"]) == [2, 1] and list(blocks["cover_ge_0.9"]) == [2, 1]
    st = pd.DataFrame(j["stats"]).set_index(["symbol", "premium"])
    assert abs(st.loc[("1000PEPEUSDT", "adj"), "mean"] - 400) < 5 and abs(st.loc[("BTCUSDT", "btc_rel"), "mean"]) < 1e-6 and st.loc[("BTCUSDT", "adj"), "acf_1h"] > 0.9      # 40·sin(t/7): period 44 h, so the 24-h lag is near −1 by construction
    assert j["alignment"]["share_tick_inside_hour"] == 1.0 and j["market_premium"]["hours"] == len(ts) and 100 < j["market_premium"]["median"] < 400
    assert "## DATA.md row" in txt and "**krw_1h_bithumb**" in txt and "3 of 3 bases listed, 3 with hourly bars" in txt and "KRW-USDT on bithumb" in txt
    assert (U["out"].parent / "krw_bithumb_premium.parquet").exists() and U["out"].exists()
    vs = pd.DataFrame(j["volume_share"])
    assert set(vs["symbol"]) == set(prem) and (vs["hours"] > 0).all()
