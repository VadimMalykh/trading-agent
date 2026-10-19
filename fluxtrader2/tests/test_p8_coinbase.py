"""Decision AT2's source audit (`ft2/coinbase.py`) on planted data, no network: the candle paging asks whole windows and keeps the
oldest-first union; the ingest drops the bucket in progress and stamps `ts_known` = start + 1 h; the premium is the planted gap, the
1000× contract is divided, the USDT adjustment divides the control's close; the audit's completeness, gaps and cover count the planted
holes and its tables come out."""
import json

import numpy as np
import pandas as pd

from ft2 import coinbase as cb

T0 = pd.Timestamp("2023-05-01", tz="UTC")


def _plant(tmp_path, monkeypatch, hours=24 * 40, hole=(100, 110)):
    """Coinbase hourly month files for four products (BTC, PEPE, WLD missing a hole, USDT) and Binance 5m closes that reproduce a
    planted premium: Coinbase = Binance / mult × usdt × (1 + prem/1e4)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cb, "RAW", tmp_path / "data" / "raw" / "external" / "coinbase")
    monkeypatch.setattr(cb, "PARQUET", tmp_path / "data" / "coinbase_1h.parquet")
    monkeypatch.setattr(cb, "OUT", tmp_path / "output" / "coinbase_audit.md")
    monkeypatch.setattr(cb.data, "PROC", tmp_path / "data")
    ts = pd.date_range(T0, periods=hours, freq="h")
    rng = np.random.default_rng(0)
    usdt = 0.9995 + rng.normal(0, 1e-4, hours)
    prem = {"BTCUSDT": 3.0 + 2.0 * np.sin(np.arange(hours) / 7), "1000PEPEUSDT": -8.0 + rng.normal(0, 1, hours), "WLDUSDT": 1.0 + rng.normal(0, 3, hours)}
    bn_px = {"BTCUSDT": 30000 * np.exp(np.cumsum(rng.normal(0, 1e-3, hours))), "1000PEPEUSDT": 1.5 * np.exp(np.cumsum(rng.normal(0, 2e-3, hours))),
             "WLDUSDT": 2.0 * np.exp(np.cumsum(rng.normal(0, 2e-3, hours)))}
    fetched = (ts[-1] + 2 * cb.HOUR)
    raw = cb.RAW
    for pid, sym in (("BTC-USD", "BTCUSDT"), ("PEPE-USD", "1000PEPEUSDT"), ("WLD-USD", "WLDUSDT"), ("USDT-USD", None)):
        (raw / pid).mkdir(parents=True)
        px = usdt if sym is None else bn_px[sym] / cb.MULT.get(sym, 1.0) * usdt * (1 + prem[sym] / 1e4)
        keep = np.ones(hours, bool)
        if pid == "WLD-USD":
            keep[hole[0]:hole[1]] = False
        rows = [[int(t.timestamp()), p * 0.999, p * 1.001, p, p, 1.0] for t, p, k in zip(ts, px, keep) if k]
        rows.append([int(fetched.timestamp()) - 1800, 1, 1, 1, 1, 1])      # a bucket in progress (its start + 1 h > fetched)
        rows.append(rows[0])                                                # a duplicate
        for m, g in pd.DataFrame(rows).groupby(pd.to_datetime(pd.DataFrame(rows)[0], unit="s", utc=True).dt.to_period("M")):
            (raw / pid / f"{m}.json").write_text(json.dumps({"product": pid, "month": str(m), "fetched": f"{fetched:%Y-%m-%d %H:%M} UTC", "rows": g.values.tolist()}))
        (raw / pid / "daily.json").write_text(json.dumps({"product": pid, "rows": [[int(pd.Timestamp("2021-03-04", tz="UTC").timestamp()), 1, 1, 1, 1, 1]]}))
    (raw / "products_20260101.json").write_text(json.dumps({"rows": [{"product": p, "symbol": s, "listed": p != "HYPE-USD", "status": "online"} for p, s in cb.PRODUCTS.items()]}))
    t5 = pd.date_range(T0 - pd.Timedelta("5min"), periods=hours * 12 + 1, freq="5min")     # bar i ends at T0 + 5i min: the hour T0 + m h is index 12m
    c5 = []
    for sym, px in bn_px.items():
        full = np.concatenate([np.repeat(px, 12), px[-1:]]) * (1 + 1e-3 * np.sin(np.arange(hours * 12 + 1)))     # an intra-hour wiggle
        full[12::12] = px                                                                 # the bar ending at the END of Coinbase's bar k is index 12 (k + 1)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5, "close": full}))
    pd.concat(c5).to_parquet(tmp_path / "data" / "candles_5m.parquet", index=False)
    return ts, prem, usdt


def test_paging_asks_whole_windows_oldest_first(monkeypatch):
    calls = []

    def fake(u, **kw):
        calls.append(u)
        s, e = pd.Timestamp(u.split("start=")[1].split("&")[0]), pd.Timestamp(u.split("end=")[1].split("&")[0])
        return [[int((s + i * cb.HOUR).timestamp()), 1, 2, 1.5, 1.5, 1] for i in range(cb.MAX_BARS) if s + i * cb.HOUR <= e][::-1]
    monkeypatch.setattr(cb, "_get", fake)
    monkeypatch.setattr(cb.time, "sleep", lambda s: None)
    rows = cb._candles("BTC-USD", T0, T0 + pd.Timedelta(hours=700), 3600)
    assert len(calls) == 3 and len(rows) == 700 and rows[0][0] == int(T0.timestamp()) and rows[-1][0] == int((T0 + 699 * cb.HOUR).timestamp())


def test_ingest_drops_the_bucket_in_progress_and_the_premium_is_the_planted_gap(tmp_path, monkeypatch):
    ts, prem, usdt = _plant(tmp_path, monkeypatch)
    rep = cb.ingest()
    assert rep["BTC-USD"]["rows"] == len(ts) and rep["BTC-USD"]["in_progress_dropped"] == 1 and rep["WLD-USD"]["rows"] == len(ts) - 10
    d = cb.load()
    assert (d["ts_known"] - d["ts"] == cb.HOUR).all() and d["ts"].dt.tz is not None
    bn = cb.binance_close_at(["BTCUSDT", "1000PEPEUSDT", "WLDUSDT"], pd.DatetimeIndex(sorted(d["ts_known"].unique())))
    P = cb.premium(d, bn).set_index(["symbol", "ts_known"])
    for sym in ("BTCUSDT", "1000PEPEUSDT"):
        got = P.loc[sym]["prem_adj_bps"].reindex(ts + cb.HOUR).to_numpy()
        assert np.nanmax(np.abs(got - prem[sym])) < 1e-6, sym
    raw = P.loc["BTCUSDT"]["prem_raw_bps"].reindex(ts + cb.HOUR).to_numpy()
    assert np.nanmax(np.abs(raw - ((1 + prem["BTCUSDT"] / 1e4) * usdt - 1) * 1e4)) < 1e-6
    assert P.loc["WLDUSDT"]["prem_adj_bps"].notna().sum() == len(ts) - 10


def test_the_audit_counts_the_hole_and_writes_its_tables(tmp_path, monkeypatch):
    ts, prem, usdt = _plant(tmp_path, monkeypatch)
    cb.ingest()
    lag = {"now": "x", "bars_served": 4, "in_progress_served": True, "last_complete_end": "y", "seconds_since_last_complete_end": 30.0}
    md = cb.audit(today=ts[-1] + 2 * cb.HOUR, lag=lag)
    j = json.loads((tmp_path / "output" / "coinbase_audit.json").read_text())
    cov = {r["product"]: r for r in j["cover"]}
    assert cov["WLD-USD"]["gaps_over_1h"] == 1 and abs(cov["WLD-USD"]["largest_gap_h"] - 11) < 1e-9 and abs(cov["WLD-USD"]["completeness"] - (len(ts) - 10) / len(ts)) < 1e-9
    assert cov["BTC-USD"]["completeness"] == 1.0 and cov["BTC-USD"]["first_daily_bar"] == "2021-03-04" and cov["HYPE-USD"]["listed"] is False and cov["HYPE-USD"]["hours"] == 0
    st = {(r["symbol"], r["premium"]): r for r in j["stats"]}
    assert abs(st[("BTCUSDT", "adj")]["mean"] - np.mean(prem["BTCUSDT"])) < 1e-6 and st[("BTCUSDT", "adj")]["acf_1h"] > 0.9 and abs(st[("1000PEPEUSDT", "adj")]["acf_1h"]) < 0.2
    assert abs(st[("BTCUSDT", "raw")]["mean"] - np.mean(((1 + prem["BTCUSDT"] / 1e4) * usdt - 1) * 1e4)) < 1e-4
    assert "## Products, extent" in md and "## The premium per name" in md and "| **coinbase_1h**" in md and "cover_F1" in md
    assert j["corr_mean"] is not None and (tmp_path / "output" / "coinbase_premium.parquet").exists()
