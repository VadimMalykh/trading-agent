"""Decision BH1's source audit (`ft2/spot.py`) on planted archive month files, no network: the symbol map takes the base's USDT pair and
falls back to the contract's own symbol; the ingest reads millisecond and microsecond stamps alike, stamps `ts_known` = start + 1 h and
drops a duplicate bar; the audit's taker-buy share and spot/perp ratio are the planted ones, the stamp check reads a basis of bps, the
hole is counted, the deviation's correlation with the planted Coinbase deviation carries the planted sign, the member breadth and the
DATA.md row come out."""
import io
import json
import zipfile

import numpy as np
import pandas as pd

from ft2 import coinbase as cb
from ft2 import spot

T0 = pd.Timestamp("2023-05-01", tz="UTC")
MAP = {"BTCUSDT": "BTCUSDT", "1000PEPEUSDT": "PEPEUSDT", "WLDUSDT": "WLDUSDT", "1000SATSUSDT": "1000SATSUSDT", "NOPEUSDT": None}


def test_candidates_strip_the_multiple_and_fall_back_to_the_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(spot, "RAW", tmp_path / "raw")
    monkeypatch.setattr(spot, "perp_symbols", lambda: list(MAP))
    sf = spot.symbols(today=pd.Timestamp("2026-01-01", tz="UTC"), listed=["BTCUSDT", "PEPEUSDT", "WLDUSDT", "1000SATSUSDT", "ETHUSDT"])
    got = dict(zip(sf["symbol"], sf["spot_symbol"]))
    assert got == MAP
    assert spot.candidates("1000SATSUSDT") == ["SATSUSDT", "1000SATSUSDT"] and spot.candidates("BTCUSDT") == ["BTCUSDT"]
    assert (tmp_path / "raw" / "symbols_20260101.json").exists()
    assert spot.universe(listed_only=True) == {"BTCUSDT": "BTCUSDT", "PEPEUSDT": "1000PEPEUSDT", "WLDUSDT": "WLDUSDT", "1000SATSUSDT": "1000SATSUSDT"}


def _zip(path, rows, unit):
    k = 1000 if unit == "ms" else 1_000_000
    buf = io.StringIO()
    for t, o, h, l, c, v, qv, n, tbv, tbq in rows:
        ot = int(t.timestamp()) * k
        buf.write(f"{ot},{o:.8f},{h:.8f},{l:.8f},{c:.8f},{v:.8f},{ot + 3600 * k - 1},{qv:.8f},{n},{tbv:.8f},{tbq:.8f},0\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(path.stem + ".csv", buf.getvalue())
    path.with_suffix(".zip.ok").touch()


def _plant(tmp_path, monkeypatch, hours=24 * 92, hole=(100, 110)):
    """Three spot symbols (BTC, PEPE for the 1000× contract, WLD with a hole), member files holding WLD and 1000PEPE in three F1 blocks and
    NOPE without a spot symbol, the perpetual's 5m bars in the archive slice, AX1's premium parquet with a premium whose deviation
    tracks the planted taker-buy share of BTC and PEPE."""
    from ft2 import universe as uni
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(spot, "RAW", tmp_path / "data" / "raw" / "external" / "binance_spot")
    monkeypatch.setattr(spot, "PARQUET", tmp_path / "data" / "spot_1h.parquet")
    monkeypatch.setattr(spot, "OUT", tmp_path / "output" / "spot_audit.md")
    monkeypatch.setattr(spot, "PREMIUM", tmp_path / "output" / "coinbase_members_premium.parquet")
    monkeypatch.setattr(spot, "KEPT", tmp_path / "kept.csv")
    monkeypatch.setattr(spot, "TWELVE", ["BTCUSDT"])
    monkeypatch.setattr(cb.data, "PROC", tmp_path / "data")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    blocks = ["2023-05-03", "2023-06-02", "2023-07-02"]
    rows = [{"block": b, "symbol": s, "liq_musd": 1.0, "vol_pct": 1.0, "play": "", "age_days": 100} for b in blocks for s in ("WLDUSDT", "1000PEPEUSDT", "NOPEUSDT")]
    pd.DataFrame(rows).to_csv(tmp_path / "members.csv", index=False)
    pd.DataFrame(rows[2:3]).assign(block="2024-09-03").to_csv(tmp_path / "members_f34.csv", index=False)      # NOPE alone in an F3+F4 block
    monkeypatch.setattr(uni, "MEMBERS_CSV", tmp_path / "members.csv")
    monkeypatch.setattr(uni, "F34_MEMBERS_CSV", tmp_path / "members_f34.csv")
    pd.DataFrame({"symbol": ["1000PEPEUSDT", "WLDUSDT"], "sd_adj_bps": [20.0, 60.0], "r62": [True, False]}).to_csv(tmp_path / "kept.csv", index=False)
    ts = pd.date_range(T0, periods=hours, freq="h")
    rng = np.random.default_rng(3)
    z = {s: np.sin(np.arange(hours) / 5.0) + rng.normal(0, 0.3, hours) for s in ("BTCUSDT", "1000PEPEUSDT", "WLDUSDT")}
    tb = {s: np.clip(0.5 + 0.1 * z[s], 0.05, 0.95) for s in z}                   # the planted taker-buy share
    ratio = {"BTCUSDT": 0.5, "1000PEPEUSDT": 0.2, "WLDUSDT": 2.0}                 # the planted spot / perp quote-volume ratio
    bn_px = {"BTCUSDT": 30000 * np.exp(np.cumsum(rng.normal(0, 1e-3, hours))), "1000PEPEUSDT": 1.5 * np.exp(np.cumsum(rng.normal(0, 2e-3, hours))),
             "WLDUSDT": 2.0 * np.exp(np.cumsum(rng.normal(0, 2e-3, hours)))}
    basis = {"BTCUSDT": 3.0, "1000PEPEUSDT": -8.0, "WLDUSDT": 20.0}                # bps, the spot close over the perpetual's
    units = {"BTCUSDT": "ms", "1000PEPEUSDT": "us", "WLDUSDT": "ms"}
    perp_qv_hour = {s: 12 * 10.0 * bn_px[s] for s in bn_px}                        # 12 bars × 10 contracts × close (the perp's 5m bars below)
    for sym, sp in (("BTCUSDT", "BTCUSDT"), ("1000PEPEUSDT", "PEPEUSDT"), ("WLDUSDT", "WLDUSDT")):
        px = bn_px[sym] / cb.mult_of(sym) * (1 + basis[sym] / 1e4)
        qv = ratio[sym] * perp_qv_hour[sym]
        keep = np.ones(hours, bool)
        if sym == "WLDUSDT":
            keep[hole[0]:hole[1]] = False
        rr = [(t, p * 0.999, p * 1.001, p * 0.998, p, q / p, q, 100, tb[sym][i] * q / p, tb[sym][i] * q) for i, (t, p, q, k) in enumerate(zip(ts, px, qv, keep)) if k]
        rr.append(rr[0])                                                           # a duplicate bar
        by = {}
        for r in rr:
            by.setdefault(f"{r[0]:%Y-%m}", []).append(r)
        for m, g in by.items():
            _zip(spot.RAW / "klines" / sp / f"{sp}-1h-{m}.zip", g, units[sym])
    (spot.RAW).mkdir(parents=True, exist_ok=True)
    (spot.RAW / "symbols_20260101.json").write_text(json.dumps({"archive_symbols": 4, "rows": [
        {"symbol": "BTCUSDT", "spot_symbol": "BTCUSDT", "listed": True, "mult": 1.0}, {"symbol": "1000PEPEUSDT", "spot_symbol": "PEPEUSDT", "listed": True, "mult": 1000.0},
        {"symbol": "WLDUSDT", "spot_symbol": "WLDUSDT", "listed": True, "mult": 1.0}, {"symbol": "NOPEUSDT", "spot_symbol": None, "listed": False, "mult": 1.0}]}))
    t5 = pd.date_range(T0, periods=hours * 12, freq="5min")
    c5 = []
    for sym, px in bn_px.items():
        full = np.repeat(px, 12)                                                   # the twelve bars of hour k at the hour's close: Σ vol × close = 12 × 10 × px[k]
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5, "close": full, "volume": 10.0}))
    pd.concat(c5).to_parquet(tmp_path / "data" / "candles_5m_archive.parquet", index=False)
    # AX1's premium: its level's deviation tracks z (the taker share's driver) on BTC and PEPE, the opposite sign on WLD
    prem = []
    for sym, sgn in (("BTCUSDT", 1.0), ("1000PEPEUSDT", 1.0), ("WLDUSDT", -1.0)):
        prem.append(pd.DataFrame({"symbol": sym, "ts_known": ts + spot.HOUR, "prem_adj_bps": 5.0 + sgn * 30.0 * z[sym] + rng.normal(0, 3, hours)}))
    pd.concat(prem).to_parquet(spot.PREMIUM, index=False)
    return ts, tb, ratio, basis, hole


def test_ingest_reads_both_stamp_units_and_the_audit_reads_the_planted_ratios(tmp_path, monkeypatch):
    ts, tb, ratio, basis, hole = _plant(tmp_path, monkeypatch)
    hours = len(ts)
    r = spot.ingest(listed_only=True)
    assert r["symbols_asked"] == 3 and r["symbols_with_bars"] == 3
    d = spot.load(spot.PARQUET)
    assert len(d) == 3 * hours - (hole[1] - hole[0])                                   # the duplicates dropped, the hole absent
    for sym in ("BTCUSDT", "1000PEPEUSDT"):
        g = d[d["symbol"] == sym].sort_values("ts")
        assert g["ts"].iloc[0] == ts[0] and g["ts"].iloc[-1] == ts[-1] and (g["ts_known"] - g["ts"] == spot.HOUR).all()   # ms and µs alike
        assert g["ts"].dt.tz is not None
    pepe = d[d["symbol"] == "1000PEPEUSDT"]
    assert (pepe["spot_symbol"] == "PEPEUSDT").all()
    txt = spot.audit(today=pd.Timestamp("2026-01-01", tz="UTC"), path=spot.PARQUET, out=spot.OUT, premium=spot.PREMIUM, kept_csv=spot.KEPT)
    J = json.loads((spot.OUT.parent / "spot_audit.json").read_text())
    cov = pd.DataFrame(J["cover"]).set_index("symbol")
    assert cov.loc["WLDUSDT", "gaps_over_1h"] == 1 and abs(cov.loc["WLDUSDT", "largest_gap_h"] - (hole[1] - hole[0] + 1)) < 1e-9
    assert cov.loc["BTCUSDT", "gaps_over_1h"] == 0 and cov.loc["NOPEUSDT", "hours"] == 0 and not cov.loc["NOPEUSDT", "listed"]
    assert cov.loc["WLDUSDT", "cover_member"] > 0.9 and cov.loc["1000PEPEUSDT", "cover_member"] > 0.99
    bl = pd.DataFrame(J["blocks"])
    f12 = bl[bl["folds"] == "F1+F2"]
    assert len(f12) == 3 and (f12["members"] == 3).all() and (f12["with_bars"] == 2).all() and (f12["cover_ge_0.9"] == 2).all()
    assert bl[bl["folds"] == "F3+F4"]["with_bars"].sum() == 0
    st = pd.DataFrame(J["stats"]).set_index(["symbol", "ratio"])
    for sym in ("BTCUSDT", "1000PEPEUSDT", "WLDUSDT"):
        a = st.loc[(sym, "taker_buy_share")]
        assert abs(a["mean"] - np.nanmean(tb[sym])) < 2e-3 and 0.05 < a["sd"] < 0.15
        b = st.loc[(sym, "spot_over_perp_log")]
        assert abs(b["median"] - np.log(ratio[sym])) < 1e-6 and b["sd"] < 1e-6                 # the planted ratio, flat: the multiple cancels
    assert st.loc[("BTCUSDT", "taker_buy_share"), "corr_dev_cbdev"] > 0.6 and st.loc[("WLDUSDT", "taker_buy_share"), "corr_dev_cbdev"] < -0.6
    assert st.loc[("1000PEPEUSDT", "taker_buy_share"), "kept_r62"] and not st.loc[("WLDUSDT", "taker_buy_share"), "kept_r62"]
    bc = pd.DataFrame(J["basis"]).set_index("symbol")
    for sym in basis:
        assert abs(bc.loc[sym, "basis_median_bps"] - basis[sym]) < 0.5 and bc.loc[sym, "share_abs_gt_50"] == 0.0
    S = J["summary"]["taker_buy_share"]
    assert S["names"] == 1 and S["corr_median"] > 0.6 and S["share_abs_corr_ge_0.5"] == 1.0
    assert "## DATA.md row" in txt and "| **spot_1h**" in txt and "2023-05-03 2 of 3" in txt
    R = pd.read_parquet(spot.OUT.parent / "spot_ratios.parquet")
    assert set(R.columns) >= {"ts_known", "symbol", "tb", "sr", "basis", "tb_dev", "sr_dev", "cb_dev"} and R["symbol"].nunique() == 3
