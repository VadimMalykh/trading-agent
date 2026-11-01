"""R73's table (`ft2/mix.py`) on planted 5m zips, no network: the hour's sums of count / quote volume / taker-buy, the last close, the bar
count, both stamp units and a header row read; a missing 5m bar leaves an 11-bar hour; a bar present in two zips is counted once; a
symbol without zips or outside the member files is not read; the fingerprint is stable; the audit's aggregation check reads ≈ 1 against
the planted archive slice and the spot overlap reads the planted spot share."""
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import coinbase as cb, data, mix, spot

T0 = pd.Timestamp("2023-05-01", tz="UTC")


def _zip(path, bars, unit):
    k = 1000 if unit == "ms" else 1_000_000
    buf = io.StringIO()
    if unit == "us":
        buf.write("open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n")   # the newer files' header row
    for t, c, v, qv, n, tbq in bars:
        ot = int(t.timestamp()) * k
        buf.write(f"{ot},{c:.6f},{c:.6f},{c:.6f},{c:.6f},{v:.6f},{ot + 300 * k - 1},{qv:.6f},{n},{v / 2:.6f},{tbq:.6f},0\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(path.stem + ".csv", buf.getvalue())
    path.with_suffix(".zip.ok").touch()


def _plant(tmp_path, monkeypatch, hours=24 * 70):
    from ft2 import universe as uni
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "data" / "raw" / "external" / "binance" / "klines"
    monkeypatch.setattr(mix, "RAW_KL", raw)
    monkeypatch.setattr(mix, "PARQUET", tmp_path / "data" / "perp_mix_1h.parquet")
    monkeypatch.setattr(mix, "OUT", tmp_path / "output" / "perp_mix_audit.md")
    monkeypatch.setattr(mix, "R68_CSV", tmp_path / "r68.csv")
    monkeypatch.setattr(spot, "PARQUET", tmp_path / "data" / "spot_1h.parquet")
    monkeypatch.setattr(data, "PROC", tmp_path / "data")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    blocks = ["2023-05-03", "2023-06-02"]
    rows = [{"block": b, "symbol": s, "liq_musd": 1.0, "vol_pct": 1.0, "play": "", "age_days": 100} for b in blocks for s in ("AAAUSDT", "BBBUSDT", "NOZIPUSDT")]
    pd.DataFrame(rows).to_csv(tmp_path / "members.csv", index=False)
    pd.DataFrame(rows[:1]).assign(block="2024-09-03").to_csv(tmp_path / "members_f34.csv", index=False)
    monkeypatch.setattr(uni, "MEMBERS_CSV", tmp_path / "members.csv")
    monkeypatch.setattr(uni, "F34_MEMBERS_CSV", tmp_path / "members_f34.csv")
    pd.DataFrame({"symbol": ["AAAUSDT", "BBBUSDT", "NOZIPUSDT"], "spot_symbol": ["AAAUSDT", "BBBUSDT", ""], "hours": [hours, hours, 0], "cover_member": 1.0,
                  "abs_basis_median_bps": 3.0, "share_abs_basis_gt_50": [0.001, 0.001, np.nan], "r68": [True, True, False]}).to_csv(tmp_path / "r68.csv", index=False)
    t5 = pd.date_range(T0, periods=hours * 12, freq="5min")
    rng = np.random.default_rng(1)
    arch, spot_rows, planted = [], [], {}
    for sym, unit in (("AAAUSDT", "ms"), ("BBBUSDT", "us")):
        px = 10.0 * np.exp(np.cumsum(rng.normal(0, 1e-3, len(t5))))
        vol = rng.uniform(5, 50, len(t5))
        n = rng.integers(1, 40, len(t5))
        qv = vol * px * (1 + rng.normal(0, 1e-4, len(t5)))                 # the true quote volume: within-bar drift only
        bars = list(zip(t5, px, vol, qv, n, qv * 0.5))
        if sym == "AAAUSDT":
            drop = int(np.flatnonzero(t5 == T0 + pd.Timedelta(hours=5, minutes=30))[0])        # one 5m bar missing → an 11-bar hour
            bars = bars[:drop] + bars[drop + 1:]
        # two monthly zips; the first bar of the second month repeated in the first zip (a duplicate counted once)
        m1 = [b for b in bars if b[0] < pd.Timestamp("2023-06-01", tz="UTC")]
        m2 = [b for b in bars if b[0] >= pd.Timestamp("2023-06-01", tz="UTC")]
        _zip(raw / sym / f"{sym}-5m-2023-05.zip", m1 + m2[:1], unit)
        _zip(raw / sym / f"{sym}-5m-2023-06.zip", m2, unit)
        _zip(raw / sym / f"{sym}-1d-2023-05.zip", m1[:3], unit)                                # a daily-interval zip: not read
        arch.append(pd.DataFrame({"symbol": sym, "open_time": [b[0] for b in bars], "high": [b[1] for b in bars], "low": [b[1] for b in bars], "close": [b[1] for b in bars], "volume": [b[2] for b in bars]}))
        planted[sym] = pd.DataFrame(bars, columns=["t", "px", "vol", "qv", "n", "tbq"])
        hrs = pd.date_range(T0 + pd.Timedelta(hours=1), periods=hours, freq="h")
        spot_rows.append(pd.DataFrame({"spot_symbol": sym, "symbol": sym, "ts": hrs - mix.HOUR, "ts_known": hrs, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
                                       "quote_volume": 100.0, "count": 60, "taker_buy_volume": 0.5, "taker_buy_quote_volume": 50.0}))
    pd.concat(arch, ignore_index=True).to_parquet(tmp_path / "data" / "candles_5m_archive.parquet", index=False)
    pd.concat(spot_rows, ignore_index=True).to_parquet(tmp_path / "data" / "spot_1h.parquet", index=False)
    # a zip without .zip.ok and a symbol outside the member files: neither is read
    _zip(raw / "AAAUSDT" / "AAAUSDT-5m-2023-07.zip", m2[:12], "ms"); (raw / "AAAUSDT" / "AAAUSDT-5m-2023-07.zip.ok").unlink()
    _zip(raw / "ZZZUSDT" / "ZZZUSDT-5m-2023-05.zip", m1[:12], "ms")
    return planted


def test_ingest_sums_the_hour_reads_both_units_and_counts_a_duplicate_once(tmp_path, monkeypatch):
    planted = _plant(tmp_path, monkeypatch)
    assert mix.symbols() == ["AAAUSDT", "BBBUSDT"]
    r = mix.ingest()
    d = mix.load()
    assert r["symbols"] == 2 and set(d["symbol"]) == {"AAAUSDT", "BBBUSDT"} and list(d.columns) == mix.COLS
    for sym, P in planted.items():
        g = d[d["symbol"] == sym].set_index("ts_known")
        P = P.assign(he=(P["t"] + mix.BAR).dt.ceil("h"))
        H = P.groupby("he").agg(n=("n", "sum"), qv=("qv", "sum"), vol=("vol", "sum"), tbq=("tbq", "sum"), px=("px", "last"), bars=("n", "size"))
        assert len(g) == len(H) and (g.index == H.index).all()
        assert (g["count"].to_numpy() == H["n"].to_numpy()).all() and np.allclose(g["quote_volume"], H["qv"]) and np.allclose(g["taker_buy_quote_volume"], H["tbq"])
        assert np.allclose(g["volume"], H["vol"]) and np.allclose(g["close"], H["px"]) and (g["bars"].to_numpy() == H["bars"].to_numpy()).all()
        assert (g["ts"] == g.index - mix.HOUR).all()
    a = d[d["symbol"] == "AAAUSDT"].set_index("ts_known")
    assert a.loc[T0 + pd.Timedelta(hours=6), "bars"] == 11 and (a["bars"] == 12).sum() == len(a) - 1          # the dropped 5m bar
    assert (d[d["symbol"] == "BBBUSDT"]["bars"] == 12).all()
    assert d["ts"].min() == T0 and d["ts_known"].min() == T0 + mix.HOUR
    fp = mix.fingerprint(d)
    assert fp == {"rows": len(d), "symbols": 2, "first": str(T0), "last": str(d["ts"].max()), "count_sum": int(d["count"].sum()), "quote_volume_sum": round(float(d["quote_volume"].sum()), 2)}
    assert {k: r[k] for k in fp} == fp
    md = mix.audit()
    j = json.loads((tmp_path / "output" / "perp_mix_audit.json").read_text())
    assert j["fingerprint"] == fp and "## Fingerprint" in md and "| **perp_mix_1h**" in md
    agg = pd.DataFrame(j["agg_check"]).set_index("symbol")
    assert set(agg.index) == {"AAAUSDT", "BBBUSDT"} and (abs(agg["ratio_median"] - 1) < 1e-3).all() and (agg["share_off_0.05"] == 0).all() and (agg["hours_compared"] > 1600).all()
    ov = pd.DataFrame(j["overlap"]).set_index("symbol")
    assert (ov["both_hours"] == ov["perp_hours"]).all() and (ov["spot_share_of_count_median"].between(0.1, 0.4)).all()
    assert len(j["blocks"]) == 3 and j["blocks"][0]["cover_ge_0.9"] == 2 and j["blocks"][0]["members"] == 3
    per = pd.DataFrame(j["per_symbol"]).set_index("symbol")
    assert per.loc["AAAUSDT", "share_bars_lt_12"] > 0 and per.loc["BBBUSDT", "share_bars_lt_12"] == 0
