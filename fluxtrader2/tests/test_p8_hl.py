"""Decision BJ2's source audit (`ft2/hl.py`) on a planted venue, no network: the coin map takes the base, then k<BASE>, then the alias; the
fetch pages the planted history 500 rows a call, resumes from a truncated file and skips a finished coin; the ingest floors the stamp to the
settlement hour, keeps the lag and drops a duplicate; Binance's 1h premium zips are read with ms stamps; the audit finds the 8-hour weeks
and the hourly regime's start, counts the hole, reads the planted premium and funding, the stamp check finds lag 0 where the bars agree
and −1 where Binance's bar is an hour late, the funding check finds the planted identity, the deviations' correlations carry the planted
signs, the member breadth and the DATA.md row come out."""
import io
import json
import math
import zipfile

import numpy as np
import pandas as pd

from ft2 import coinbase as cb
from ft2 import data, hl

T0 = pd.Timestamp("2023-05-01", tz="UTC")
LISTING = pd.DataFrame({"coin": ["BTC", "kPEPE", "WLD", "ETH", "JELLY"], "delisted": [False, False, True, False, False]})


def test_candidates_and_the_coin_map(tmp_path, monkeypatch):
    monkeypatch.setattr(hl, "RAW", tmp_path / "raw")
    monkeypatch.setattr(hl, "perp_symbols", lambda: ["BTCUSDT", "1000PEPEUSDT", "WLDUSDT", "NOPEUSDT", "JELLYJELLYUSDT"])
    sf = hl.symbols(today=pd.Timestamp("2026-01-01", tz="UTC"), listing=LISTING)
    assert dict(zip(sf["symbol"], sf["coin"])) == {"BTCUSDT": "BTC", "1000PEPEUSDT": "kPEPE", "WLDUSDT": "WLD", "NOPEUSDT": None, "JELLYJELLYUSDT": "JELLY"}
    assert dict(zip(sf["symbol"], sf["delisted"]))["WLDUSDT"] and not dict(zip(sf["symbol"], sf["delisted"]))["NOPEUSDT"]
    assert hl.candidates("1000PEPEUSDT") == ["PEPE", "kPEPE"] and hl.candidates("JELLYJELLYUSDT") == ["JELLYJELLY", "kJELLYJELLY", "JELLY"]
    assert (tmp_path / "raw" / "symbols_20260101.json").exists()
    assert hl.universe() == {"BTC": "BTCUSDT", "kPEPE": "1000PEPEUSDT", "WLD": "WLDUSDT", "JELLY": "JELLYJELLYUSDT"}
    assert hl.universe(only=["WLDUSDT", "BTC"]) == {"BTC": "BTCUSDT", "WLD": "WLDUSDT"}


def _zip(path, rows):
    buf = io.StringIO()
    for t, p in rows:
        ot = int(t.timestamp()) * 1000
        buf.write(f"{ot},{p:.10f},{p:.10f},{p:.10f},{p:.10f},0,{ot + 3600 * 1000 - 1},0,0,0,0,0\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(path.stem + ".csv", buf.getvalue())
    path.with_suffix(".zip.ok").touch()


def _plant(tmp_path, monkeypatch, hours=24 * 92, hole=(100, 110), eight_h_rows=10, frozen_tail=200):
    """Three coins — BTC (8-hourly for the first `eight_h_rows` settlements, then hourly), kPEPE for the 1000× contract, WLD with a hole — and
    NOPE unlisted; member files holding WLD, 1000PEPE and NOPE in three F1 blocks; Binance's 1h premium bars equal to the venue's hour
    premium on BTC and PEPE and an hour LATE on WLD; Binance's 8-hour funding equal to the venue's eight settlements summed on BTC and
    noise on PEPE; AX1's premium tracking the venue's premium on PEPE and the opposite on WLD; R68's `tb24_dev` tracking BTC's."""
    from ft2 import universe as uni
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hl, "RAW", tmp_path / "data" / "raw" / "external" / "hyperliquid")
    monkeypatch.setattr(hl, "PARQUET", tmp_path / "data" / "hl_funding_1h.parquet")
    monkeypatch.setattr(hl, "BN_PARQUET", tmp_path / "data" / "premium_1h.parquet")
    monkeypatch.setattr(hl, "OUT", tmp_path / "output" / "hl_audit.md")
    monkeypatch.setattr(hl, "PREMIUM", tmp_path / "output" / "coinbase_members_premium.parquet")
    monkeypatch.setattr(hl, "SPOT_RATIOS", tmp_path / "output" / "spot_ratios.parquet")
    monkeypatch.setattr(hl, "KEPT", tmp_path / "kept.csv")
    monkeypatch.setattr(hl, "TWELVE", ["BTCUSDT"])
    monkeypatch.setattr(hl, "PAUSE", 0.0)
    monkeypatch.setattr(data, "PROC", tmp_path / "data")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    blocks = ["2023-05-03", "2023-06-02", "2023-07-02"]
    rows = [{"block": b, "symbol": s, "liq_musd": 1.0, "vol_pct": 1.0, "play": "", "age_days": 100} for b in blocks for s in ("WLDUSDT", "1000PEPEUSDT", "NOPEUSDT")]
    pd.DataFrame(rows).to_csv(tmp_path / "members.csv", index=False)
    pd.DataFrame(rows[2:3]).assign(block="2024-09-03").to_csv(tmp_path / "members_f34.csv", index=False)
    monkeypatch.setattr(uni, "MEMBERS_CSV", tmp_path / "members.csv")
    monkeypatch.setattr(uni, "F34_MEMBERS_CSV", tmp_path / "members_f34.csv")
    pd.DataFrame({"symbol": ["1000PEPEUSDT", "WLDUSDT"], "sd_adj_bps": [20.0, 60.0], "r62": [True, False]}).to_csv(tmp_path / "kept.csv", index=False)
    ts = pd.date_range(T0, periods=hours, freq="h")
    rng = np.random.default_rng(5)
    z = {s: np.sin(np.arange(hours) / 5.0) + rng.normal(0, 0.3, hours) for s in ("BTCUSDT", "1000PEPEUSDT", "WLDUSDT")}
    prem = {s: (2.0 + 5.0 * z[s]) / 1e4 for s in z}                                   # the planted premium, a fraction (2 bps ± 5)
    rate = {s: prem[s] + 0.0000125 for s in z}                                          # + the interest term
    coins = {"BTCUSDT": "BTC", "1000PEPEUSDT": "kPEPE", "WLDUSDT": "WLD"}
    history = {}
    for sym, coin in coins.items():
        keep = np.ones(hours, bool)
        if sym == "WLDUSDT":
            keep[hole[0]:hole[1]] = False
        rr = []
        for i, t in enumerate(ts):
            if sym == "BTCUSDT" and i < 8 * eight_h_rows:
                if i % 8 != 7:
                    continue
                lag_ms = 60_000                                                         # the 8-hour weeks: a minute late
            else:
                lag_ms = 100
            if keep[i]:
                pz = 0.0 if (sym == "WLDUSDT" and i >= hours - frozen_tail) else prem[sym][i]      # WLD delisted: a frozen tail of exact zeros
                rr.append({"coin": coin, "fundingRate": f"{rate[sym][i]:.10f}", "premium": f"{pz:.10f}", "time": int(t.timestamp() * 1000) + lag_ms})
        rr.append(dict(rr[-1]))                                                         # a duplicate row
        history[coin] = rr
    calls = {"n": 0}

    def fake_post(payload, timeout=60, retries=6):
        calls["n"] += 1
        if payload["type"] == "meta":
            return {"universe": [{"name": c, "isDelisted": d} for c, d in zip(LISTING["coin"], LISTING["delisted"])]}
        rows_ = [r for r in history.get(payload["coin"], []) if payload["startTime"] <= r["time"] <= payload.get("endTime", 10**14)]
        return rows_[:hl.PAGE]
    monkeypatch.setattr(hl, "_post", fake_post)
    monkeypatch.setattr(hl, "perp_symbols", lambda: ["BTCUSDT", "1000PEPEUSDT", "WLDUSDT", "NOPEUSDT"])
    # Binance's 1h premium bars: the venue's hour premium on BTC and PEPE; an hour LATE on WLD (the bar at t holds the venue's t − 1)
    root = tmp_path / "data" / "raw" / "external" / "binance"
    for sym in coins:
        p = prem[sym] if sym != "WLDUSDT" else np.r_[np.nan, prem[sym][:-1]]
        rows_ = [(t - hl.HOUR, v) for t, v in zip(ts, p) if not np.isnan(v)]          # a bar starting at H is read at H + 1 h: start = t − 1 h
        by = {}
        for r in rows_:
            by.setdefault(f"{r[0]:%Y-%m}", []).append(r)
        for m, g in by.items():
            _zip(root / hl.BN_KIND / sym / f"{sym}-{hl.BN_INTERVAL}-{m}.zip", g)
    # Binance's funding: 8-hourly settlements; BTC's rate the venue's eight hourly rates summed, PEPE's noise
    fa = []
    for sym in ("BTCUSDT", "1000PEPEUSDT"):
        for i in range(8 * eight_h_rows + 8, hours, 8):
            r8 = float(np.sum(rate[sym][i - 7:i + 1])) if sym == "BTCUSDT" else float(rng.normal(0, 1e-4))
            fa.append({"symbol": sym, "ts": ts[i], "rate": r8, "interval_h": 8})
    pd.DataFrame(fa).to_parquet(tmp_path / "data" / "funding_archive.parquet", index=False)
    cbp = []
    for sym, sgn in (("1000PEPEUSDT", 1.0), ("WLDUSDT", -1.0)):
        cbp.append(pd.DataFrame({"symbol": sym, "ts_known": ts, "prem_adj_bps": 5.0 + sgn * 30.0 * z[sym] + rng.normal(0, 3, hours)}))
    pd.concat(cbp).to_parquet(hl.PREMIUM, index=False)
    sr = pd.DataFrame({"ts_known": ts, "symbol": "BTCUSDT", "tb24_dev": z["BTCUSDT"], "sr24_dev": rng.normal(0, 1, hours)})
    sr.to_parquet(hl.SPOT_RATIOS, index=False)
    return ts, z, prem, rate, coins, hole, history, calls, root


def test_fetch_ingest_and_audit_on_the_planted_venue(tmp_path, monkeypatch):
    ts, z, prem, rate, coins, hole, history, calls, root = _plant(tmp_path, monkeypatch)
    hours = len(ts)
    hl.symbols(today=pd.Timestamp("2026-01-01", tz="UTC"))
    r = hl.fetch(end="2023-08-15")
    assert r["coins"] == 3 and r["err"] == 0 and r["skipped"] == 0
    assert r["pages"] == sum(math.ceil(len(h) / hl.PAGE) + (1 if len(h) % hl.PAGE == 0 else 0) for h in history.values())   # a full last page asks once more
    assert r["rows"] == sum(len(h) for h in history.values())
    r2 = hl.fetch(end="2023-08-15")
    assert r2["skipped"] == 3 and r2["pages"] == 0                                        # the done markers
    # resume: WLD's file cut to 300 rows and its marker removed → the rest fetched, no row lost
    p = hl.RAW / "funding" / "WLD.json"
    rows_ = json.load(open(p))["rows"]
    p.write_text(json.dumps({"coin": "WLD", "rows": rows_[:300]}))
    p.with_suffix(".done").unlink()
    r3 = hl.fetch(end="2023-08-15")
    assert r3["skipped"] == 2 and r3["rows"] == len(rows_) - 300 and json.load(open(p))["rows"] == rows_
    ri = hl.ingest()
    assert ri["coins_asked"] == 3 and ri["coins_with_rows"] == 3 and ri["frozen_rows"] == 200 and ri["coins_with_frozen"] == 1
    full = hl.load(hl.PARQUET, live_only=False)
    n_btc = hours - 8 * 10 + 10
    assert len(full) == n_btc + hours + hours - (hole[1] - hole[0])                         # the duplicates dropped, the hole absent
    assert full["frozen"].sum() == 200 and (full.loc[full["frozen"], "symbol"] == "WLDUSDT").all() and full.loc[full["frozen"], "ts"].min() == ts[-200]
    d = hl.load(hl.PARQUET)
    assert len(d) == len(full) - 200 and not d["frozen"].any()
    assert hl.frozen_mask(pd.Series([0.0] * 23 + [1.0] + [0.0] * 24)).tolist() == [False] * 24 + [True] * 24      # a run short of the bar is kept
    g = d[d["symbol"] == "BTCUSDT"].sort_values("ts")
    assert (g["ts_known"] == g["ts"]).all() and g["ts"].dt.tz is not None and g["ts"].iloc[-1] == ts[-1]
    assert abs(g["lag_s"].iloc[0] - 60.0) < 1e-9 and abs(g["lag_s"].iloc[-1] - 0.1) < 1e-9 and (g["ts"].dt.minute == 0).all()
    assert (d[d["symbol"] == "1000PEPEUSDT"]["coin"] == "kPEPE").all()
    rb = hl.bnprem_ingest(root=root)
    assert rb["symbols_with_bars"] == 3 and rb["rows"] == 3 * hours - 1
    bn = pd.read_parquet(hl.BN_PARQUET)
    b = bn[bn["symbol"] == "BTCUSDT"].sort_values("ts")
    assert (b["ts_known"] - b["ts"] == hl.HOUR).all() and abs(b["close"].iloc[5] - prem["BTCUSDT"][5]) < 1e-9
    txt = hl.audit(today=pd.Timestamp("2026-01-01", tz="UTC"), path=hl.PARQUET, bn_path=hl.BN_PARQUET, out=hl.OUT, premium=hl.PREMIUM, spot_ratios=hl.SPOT_RATIOS, kept_csv=hl.KEPT)
    J = json.loads((hl.OUT.parent / "hl_audit.json").read_text())
    cov = pd.DataFrame(J["cover"]).set_index("symbol")
    assert cov.loc["BTCUSDT", "rows_8h"] == 9 and pd.Timestamp(cov.loc["BTCUSDT", "hourly_from"]) == ts[79]    # the 10th 8-hour row starts the hourly chain
    assert cov.loc["WLDUSDT", "gaps_over_1h"] == 1 and abs(cov.loc["WLDUSDT", "largest_gap_h"] - (hole[1] - hole[0] + 1)) < 1e-9
    assert cov.loc["1000PEPEUSDT", "gaps_over_1h"] == 0 and cov.loc["1000PEPEUSDT", "rows_8h"] == 0
    assert cov.loc["NOPEUSDT", "rows"] == 0 and not cov.loc["NOPEUSDT", "listed"] and cov.loc["WLDUSDT", "delisted"]
    assert cov.loc["WLDUSDT", "frozen_rows"] == 200 and pd.Timestamp(cov.loc["WLDUSDT", "last"]) == ts[-201] and cov.loc["BTCUSDT", "frozen_rows"] == 0
    assert "carry FROZEN rows" in txt
    assert cov.loc["WLDUSDT", "cover_member"] > 0.9 and cov.loc["1000PEPEUSDT", "cover_member"] > 0.99
    assert abs(cov.loc["BTCUSDT", "lag_s_max"] - 60.0) < 1e-9 and abs(cov.loc["WLDUSDT", "lag_s_p50"] - 0.1) < 1e-9
    bl = pd.DataFrame(J["blocks"])
    f12 = bl[bl["folds"] == "F1+F2"]
    assert len(f12) == 3 and (f12["members"] == 3).all() and (f12["with_bars"] == 2).all() and f12["cover_ge_0.9"].tolist() == [2, 2, 1]   # WLD's frozen tail drops it from the third block
    st = pd.DataFrame(J["stats"]).set_index(["symbol", "quantity"])
    for sym in coins:
        a = st.loc[(sym, "hl_prem")]
        assert abs(a["mean"] - np.mean(prem[sym]) * 1e4) < 0.3 and 2 < a["sd"] < 5
        f = st.loc[(sym, "hl_fund")]
        assert abs(f["mean"] - a["mean"] - 0.125) < 0.3                                   # the interest term, 0.125 bps an hour
        assert st.loc[(sym, "hl_prem24"), "hours"] < a["hours"] and st.loc[(sym, "bn_prem24"), "hours"] < st.loc[(sym, "bn_prem"), "hours"]
    assert st.loc[("BTCUSDT", "hl_prem"), "corr_dev_bn_prem_dev"] > 0.99 and st.loc[("1000PEPEUSDT", "hl_prem24"), "corr_dev_bn_prem24_dev"] > 0.99
    assert st.loc[("1000PEPEUSDT", "hl_prem"), "corr_dev_cb_dev"] > 0.6 and st.loc[("WLDUSDT", "hl_prem"), "corr_dev_cb_dev"] < -0.6
    assert st.loc[("BTCUSDT", "hl_prem"), "corr_dev_tb24_dev"] > 0.6 and abs(st.loc[("BTCUSDT", "hl_prem"), "corr_dev_sr24_dev"]) < 0.2
    assert np.isnan(st.loc[("1000PEPEUSDT", "hl_prem"), "corr_dev_tb24_dev"])            # no spot row for PEPE
    assert st.loc[("1000PEPEUSDT", "hl_prem"), "kept_r62"] and not st.loc[("WLDUSDT", "hl_prem"), "kept_r62"]
    assert abs(st.loc[("BTCUSDT", "gap24"), "mean"]) < 0.05                                 # the same premium on both venues: no gap
    sc = pd.DataFrame(J["stamp"]).set_index("symbol")
    assert sc.loc["BTCUSDT", "best_lag"] == 0 and sc.loc["1000PEPEUSDT", "best_lag"] == 0 and sc.loc["WLDUSDT", "best_lag"] == -1
    assert sc.loc["BTCUSDT", "corr_lag0"] > 0.99 and sc.loc["WLDUSDT", "corr_lag-1"] > 0.99 and abs(sc.loc["BTCUSDT", "level_hl_minus_bn_bps"]) < 1e-6
    fc = pd.DataFrame(J["funding"]).set_index("symbol")
    assert fc.loc["BTCUSDT", "corr"] > 0.99 and abs(fc.loc["1000PEPEUSDT", "corr"]) < 0.3 and fc.loc["BTCUSDT", "settlements"] > 200
    assert abs(fc.loc["BTCUSDT", "hl_mean_pct_yr"] - fc.loc["BTCUSDT", "bn_mean_pct_yr"]) < 1e-6
    S = J["summary"]["hl_prem"]
    assert S["names"] == 1 and S["corr_cb_dev"]["median"] > 0.6 and S["corr_cb_dev"]["share_abs_ge_0.5"] == 1.0 and S["corr_bn_prem_dev"]["median"] > 0.99
    assert set(J["summary"]) == set(hl.QUANTITIES)
    assert "## DATA.md row" in txt and "| **hl_funding_1h**" in txt and "2023-05-03 2 of 3" in txt
    Q = pd.read_parquet(hl.OUT.parent / "hl_quantities.parquet")
    assert set(Q.columns) >= {"ts_known", "symbol", "hl_prem", "hl_fund", "hl_prem24", "hl_fund24", "bn_prem", "bn_prem24", "gap24", "hl_prem_dev", "bn_prem_dev", "cb_dev", "tb24_dev", "sr24_dev"}
    assert Q["symbol"].nunique() == 3
