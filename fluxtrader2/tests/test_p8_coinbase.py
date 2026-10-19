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


# ---- decision AX1 (i): the members' universe -------------------------------------------------------------------------------------
def _plant_members(tmp_path, monkeypatch, hours=24 * 92):
    """Two member files (ARB and 1000SHIB members of three F1+F2 blocks, NOPE a member without a Coinbase product), raw month files for
    ARB-USD, SHIB-USD and USDT-USD with a planted premium and a planted volume share, Binance 5m bars in the ARCHIVE slice."""
    from ft2 import universe as uni
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cb, "RAW", tmp_path / "data" / "raw" / "external" / "coinbase")
    monkeypatch.setattr(cb, "PARQUET", tmp_path / "data" / "coinbase_1h.parquet")
    monkeypatch.setattr(cb, "MEMBERS_PARQUET", tmp_path / "data" / "coinbase_1h_members.parquet")
    monkeypatch.setattr(cb, "OUT", tmp_path / "output" / "coinbase_audit.md")
    monkeypatch.setattr(cb, "MEMBERS_OUT", tmp_path / "output" / "coinbase_members_audit.md")
    monkeypatch.setattr(cb.data, "PROC", tmp_path / "data")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    blocks = ["2023-05-03", "2023-06-02", "2023-07-02"]
    rows = [{"block": b, "symbol": s, "liq_musd": 1.0, "vol_pct": 1.0, "play": "", "age_days": 100} for b in blocks for s in ("ARBUSDT", "1000SHIBUSDT", "NOPEUSDT")]
    pd.DataFrame(rows).to_csv(tmp_path / "members.csv", index=False)
    pd.DataFrame(rows[:1]).assign(block="2024-09-03").to_csv(tmp_path / "members_f34.csv", index=False)
    monkeypatch.setattr(uni, "MEMBERS_CSV", tmp_path / "members.csv")
    monkeypatch.setattr(uni, "F34_MEMBERS_CSV", tmp_path / "members_f34.csv")
    ts = pd.date_range(T0, periods=hours, freq="h")
    rng = np.random.default_rng(1)
    usdt = 0.9995 + rng.normal(0, 1e-4, hours)
    prem = {"ARBUSDT": 2.0 + rng.normal(0, 1, hours), "1000SHIBUSDT": -5.0 + rng.normal(0, 1, hours)}
    share = {"ARBUSDT": 0.25, "1000SHIBUSDT": 0.05}                         # Coinbase's USD volume over Binance's, planted flat
    bn_px = {"ARBUSDT": 1.2 * np.exp(np.cumsum(rng.normal(0, 1e-3, hours))), "1000SHIBUSDT": 0.009 * np.exp(np.cumsum(rng.normal(0, 1e-3, hours)))}
    fetched = ts[-1] + 2 * cb.HOUR
    for pid, sym in (("ARB-USD", "ARBUSDT"), ("SHIB-USD", "1000SHIBUSDT"), ("USDT-USD", None)):
        (cb.RAW / pid).mkdir(parents=True)
        px = usdt if sym is None else bn_px[sym] / cb.mult_of(sym) * usdt * (1 + prem[sym] / 1e4)
        vol = np.ones(hours) if sym is None else share[sym] * 12 * 10.0 * bn_px[sym] / px       # Binance's hour: 12 bars × 10 contracts × close
        rr = [[int(t.timestamp()), p * 0.999, p * 1.001, p, p, v] for t, p, v in zip(ts, px, vol)]
        for m, g in pd.DataFrame(rr).groupby(pd.to_datetime(pd.DataFrame(rr)[0], unit="s", utc=True).dt.to_period("M")):
            (cb.RAW / pid / f"{m}.json").write_text(json.dumps({"product": pid, "month": str(m), "fetched": f"{fetched:%Y-%m-%d %H:%M} UTC", "rows": g.values.tolist()}))
        (cb.RAW / pid / "daily.json").write_text(json.dumps({"product": pid, "rows": [[int(pd.Timestamp("2022-01-01", tz="UTC").timestamp()), 1, 1, 1, 1, 1]]}))
    (cb.RAW / "products_members_20260101.json").write_text(json.dumps({"rows": [{"product": "ARB-USD", "symbol": "ARBUSDT", "listed": True, "status": "online"},
                                                                                 {"product": "SHIB-USD", "symbol": "1000SHIBUSDT", "listed": True, "status": "online"},
                                                                                 {"product": "NOPE-USD", "symbol": "NOPEUSDT", "listed": False, "status": None},
                                                                                 {"product": "USDT-USD", "symbol": None, "listed": True, "status": "online"}]}))
    t5 = pd.date_range(T0 - pd.Timedelta("5min"), periods=hours * 12 + 1, freq="5min")
    c5 = []
    for sym, px in bn_px.items():
        full = np.concatenate([np.repeat(px, 12), px[-1:]]) * (1 + 1e-3 * np.sin(np.arange(hours * 12 + 1)))
        full[12::12] = px
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5, "close": full, "volume": 10.0}))
    pd.concat(c5).to_parquet(tmp_path / "data" / "candles_5m_archive.parquet", index=False)
    return ts, prem, share


def test_members_universe_has_its_own_parquet_the_multiple_the_cover_and_the_volume_share(tmp_path, monkeypatch):
    ts, prem, share = _plant_members(tmp_path, monkeypatch)
    assert cb.base("1000SHIBUSDT") == "SHIB" and cb.base("1MBABYDOGEUSDT") == "BABYDOGE" and cb.base("1000LUNCUSDT") == "LUNC" and cb.base("ARBUSDT") == "ARB"
    assert cb.mult_of("1000SHIBUSDT") == 1000.0 and cb.mult_of("1MBABYDOGEUSDT") == 1e6 and cb.mult_of("ARBUSDT") == 1.0
    U = cb.universe("members")
    assert set(U["products"]) == {"ARB-USD", "SHIB-USD", "NOPE-USD", "USDT-USD"} and U["mult"]["1000SHIBUSDT"] == 1000.0 and U["parquet"].name == "coinbase_1h_members.parquet"
    # listed-only fetch skips the unlisted product and never calls the API for it
    calls = []
    monkeypatch.setattr(cb, "_get", lambda u, **kw: calls.append(u) or [])
    monkeypatch.setattr(cb.time, "sleep", lambda s: None)
    rep = cb.fetch(start="2022-01-01", end="2022-02-01", today=ts[-1] + 2 * cb.HOUR, U=U, listed_only=True, daily=False)      # a month before the plant: nothing on disk is touched
    assert rep["skipped_unlisted"] == ["NOPE-USD"] and not any("NOPE-USD" in u for u in calls) and any("ARB-USD" in u for u in calls)
    rep = cb.ingest(U=U)
    assert rep["ARB-USD"]["rows"] == len(ts) and rep["NOPE-USD"]["rows"] == 0 and U["parquet"].exists() and not cb.PARQUET.exists()    # the twelve's file untouched
    d = cb.load(U["parquet"])
    bn = cb.binance_close_at(["ARBUSDT", "1000SHIBUSDT"], pd.DatetimeIndex(sorted(d["ts_known"].unique())), U["slices"])
    P = cb.premium(d, bn, U["mult"]).set_index(["symbol", "ts_known"])
    for sym in ("ARBUSDT", "1000SHIBUSDT"):
        assert np.nanmax(np.abs(P.loc[sym]["prem_adj_bps"].reindex(ts + cb.HOUR).to_numpy() - prem[sym])) < 1e-6, sym      # the 1000× multiple divided
    md = cb.audit(today=ts[-1] + 2 * cb.HOUR, lag={"now": "x"}, U=U)
    j = json.loads((tmp_path / "output" / "coinbase_members_audit.json").read_text())
    cov = {r["symbol"]: r for r in j["cover"]}
    assert abs(cov["ARBUSDT"]["cover_member"] - 0.75) < 1e-9 and cov["ARBUSDT"]["member_blocks"] == 4 and cov["ARBUSDT"]["member_hours"] == 4 * 30 * 24   # three F1+F2 blocks full, the F3+F4 block empty
    assert cov["NOPEUSDT"]["hours"] == 0 and cov["NOPEUSDT"]["listed"] is False and cov["NOPEUSDT"]["cover_member"] == 0.0      # a member without a product: zero cover, counted
    bl = {b["block"]: b for b in j["blocks"]}
    assert bl["2023-05-03"]["members"] == 3 and bl["2023-05-03"]["with_bars"] == 2 and bl["2023-05-03"]["cover_ge_0.9"] == 2 and bl["2023-07-02"]["cover_ge_0.9"] == 2 and bl["2024-09-03"]["with_bars"] == 0
    vs = {r["symbol"]: r for r in j["volume_share"]}
    for sym in share:
        assert abs(vs[sym]["share_median"] - share[sym]) < 1e-3 and vs[sym]["hours"] > 1000
    assert "## The members' cover of their own hours" in md and "## The volume share per name" in md and "coinbase_1h_members" in md
    assert (tmp_path / "output" / "coinbase_members_premium.parquet").exists() and (tmp_path / "output" / "coinbase_members_audit.md").exists()
