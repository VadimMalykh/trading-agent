"""R54 (`ft2/magvol.py`, `ft2/dvol.py`): on a synthetic market with persistent volatility and a noisy implied index, the candle
features add to the implied beyond the bar on both names; the target is the formula; the features are causal; only the index's
OPEN is read; the ingest keeps midnight rows and the inventory reads the extent."""
import json

import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import dvol, folds, magvol

SYMS = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}
START, END = pd.Timestamp("2021-01-01", tz="UTC"), folds.bounds("F2")[1]


def _synth(tmp_path, seed=5, close_plant=None):
    rng = np.random.default_rng(seed)
    days = pd.date_range(START, END - pd.Timedelta(days=1), freq="D")
    nd = len(days)
    c5, dv_rows = [], []
    for i, (sym, cur) in enumerate(SYMS.items()):
        lv = np.zeros(nd)
        for k in range(1, nd):
            lv[k] = 0.90 * lv[k - 1] + rng.normal(0, 0.2)
        sig_day = 0.022 * np.exp(lv)                                          # the day's volatility, a persistent process
        r = (rng.normal(0, 1, (nd, 288)) * (sig_day / np.sqrt(288))[:, None]).ravel()
        t5 = pd.date_range(START + bt.BAR, periods=nd * 288, freq="5min")
        px = 1000 * (i + 1) * np.exp(np.cumsum(r))
        vol = np.repeat(np.exp(lv) * 50, 288) * rng.uniform(0.5, 1.5, nd * 288)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - bt.BAR, "high": px * 1.0003, "low": px * 0.9997, "close": px, "volume": vol}))
        # the implied index: the next 30 days' true vol (annualised %), times a noise of ±30 % — informative, noisier than yesterday's realised
        fwd = pd.Series(sig_day).rolling(30).mean().shift(-29).bfill().ffill().to_numpy()
        imp = fwd * np.sqrt(365) * 100 * np.exp(rng.normal(0, 0.3, nd))
        dv_rows.append(pd.DataFrame({"currency": cur, "day": days, "open": imp, "high": imp * 1.1, "low": imp * 0.9,
                                     "close": np.full(nd, close_plant) if close_plant is not None else imp}))
    (tmp_path / "data").mkdir(exist_ok=True)
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(dv_rows).to_parquet("data/dvol.parquet", index=False)
    return days


def test_the_candles_add_beyond_a_noisy_implied_and_the_read_is_causal_and_reads_the_open(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _synth(tmp_path)
    magvol.run(holds=(1, 7), name="t")
    out = magvol.OUT / "t"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "PASS", v
    for sym in SYMS:
        nv = v["names"][sym]
        assert nv["(1) DVOL cover and range"] == "PASS" and nv["(3) causal"] == "PASS" and nv["causal_max_diff"] <= 1e-9 and nv["dropped_share"] <= 0.02, nv
        assert nv["(4) refits causal h=1"] == "PASS" and nv["(4) refits causal h=7"] == "PASS"
        assert np.isfinite(nv["vrp_log_mean"]) and nv["dvol_vs_rv30_corr"] > 0.3
    rows = pd.read_csv(out / "rows.csv")
    fam = rows[rows["family"]].set_index(["symbol", "hold_days"])
    assert len(fam) == 4 and set(fam["verdict"]) <= {"ALIVE", "NOT DETECTABLE", "CLOSED"}
    for sym in SYMS:
        r = fam.loc[(sym, 1)]
        assert r["t"] > 2.24 and r["dr2"] > 0.02 and r["verdict"] == "ALIVE", r.to_dict()
    r2 = pd.read_csv(out / "r2.csv").set_index(["symbol", "hold_days", "model"])
    assert r2.loc[("BTCUSDT", 1, "C"), "r2_all"] > 0.3 and r2.loc[("BTCUSDT", 1, "I+C"), "r2_all"] >= r2.loc[("BTCUSDT", 1, "I"), "r2_all"]
    assert "SOLUSDT" in v["names"] and v["names"]["SOLUSDT"].get("note") == "not in the panel"
    rows_a = rows.copy()
    # the OPEN is the value read: a planted close changes nothing
    _synth(tmp_path, close_plant=999.0)
    magvol.run(holds=(1, 7), name="t2")
    rows_b = pd.read_csv(magvol.OUT / "t2" / "rows.csv")
    pd.testing.assert_frame_equal(rows_a, rows_b)


def test_the_target_is_the_formula_and_the_table_is_causal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _synth(tmp_path, seed=9)
    c = pd.read_parquet("data/candles_5m.parquet")
    c = c[c["symbol"] == "BTCUSDT"].copy()
    c["t"] = c["open_time"] + bt.BAR
    close = pd.Series(c["close"].to_numpy(), index=pd.DatetimeIndex(c["t"]))
    dv = pd.Series((c["close"] * c["volume"]).to_numpy(), index=close.index)
    T = magvol.table(close, dv, None, (1, 7))
    d = pd.Timestamp("2023-06-10", tz="UTC")
    r = np.log(close).diff()
    inside = (close.index > d) & (close.index <= d + pd.Timedelta(days=1))
    y1 = np.log(np.sqrt(365 * (r[inside] ** 2).sum()) * 100)
    assert abs(T.loc[d, "y1"] - y1) < 1e-9
    w7 = (close.index > d) & (close.index <= d + pd.Timedelta(days=7))
    assert abs(T.loc[d, "y7"] - np.log(np.sqrt(365 / 7 * (r[w7] ** 2).sum()) * 100)) < 1e-9
    prev = (close.index > d - pd.Timedelta(days=1)) & (close.index <= d)
    assert abs(T.loc[d, "lrv1"] - np.log(np.sqrt(365 * (r[prev] ** 2).sum()) * 100)) < 1e-9
    # a spike planted after d leaves every feature at or before d unchanged; a broken day poisons its windows
    close2 = close.copy()
    close2[close2.index > d + pd.Timedelta(hours=1)] *= 3.0
    T2 = magvol.table(close2, dv, None, (1, 7))
    upto = T.index[T.index <= d]
    assert np.nanmax(np.abs(T.loc[upto, ["lrv1", "lrv7", "lrv30", "dvs"]].to_numpy() - T2.loc[upto, ["lrv1", "lrv7", "lrv30", "dvs"]].to_numpy())) == 0.0
    close3 = close[~((close.index > d + pd.Timedelta(days=2)) & (close.index <= d + pd.Timedelta(days=2, hours=2)))]
    T3 = magvol.table(close3, dv.reindex(close3.index), None, (1, 7))
    assert not T3.loc[d + pd.Timedelta(days=2), "whole"] and np.isnan(T3.loc[d, "y7"]) and np.isfinite(T3.loc[d, "y1"])


def test_dvol_ingest_keeps_midnight_rows_and_the_inventory_reads_the_extent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dvol.RAW.mkdir(parents=True)
    days = pd.date_range("2023-04-01", "2024-09-30", freq="D", tz="UTC")
    rows = [[int(t.timestamp() * 1000), 50.0 + i % 7, 55.0, 45.0, 50.0 + (i + 1) % 7] for i, t in enumerate(days)]
    rows.append([int(days[5].timestamp() * 1000) + 3_600_000, 1.0, 1.0, 1.0, 1.0])            # an off-midnight row: dropped
    rows.append(rows[10])                                                                       # a duplicate: dropped
    (dvol.RAW / "dvol_BTC_1D_20261018.json").write_text(json.dumps({"currency": "BTC", "fetched": "x", "rows": rows}))
    rep = dvol.ingest(("BTC",))
    assert rep["BTC"]["rows"] == len(days) and rep["BTC"]["rows_off_midnight_dropped"] == 1
    d = dvol.load()
    assert d["day"].is_unique and (d["open"].to_numpy()[1:] == d["close"].to_numpy()[:-1]).all()
    txt = dvol.inventory(("F1", "F2"))
    assert "BTC 2023-04-01 → 2024-09-30" in txt and "F1 100%, F2 100%" in txt and "| **DVOL**" in txt
