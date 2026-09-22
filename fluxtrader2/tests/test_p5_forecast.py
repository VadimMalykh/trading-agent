"""P5 step 7 — the pair-held-out ridge forecast (`ft2/forecast.py`, registration R12)."""
import os

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt
from ft2 import forecast as fc

PAIRS = ["AAUSDT", "BBUSDT", "CCUSDT", "DDUSDT", "EEUSDT", "FFUSDT"]
HOLD, SD, PHI = 12, 5.0, 0.06


def _synth(tmp_path, days=75, start="2023-03-20", seed=3):
    """Random-walk pairs sharing a market factor. Each pair's own move over the next hour follows its last hour
    (r_t = ε_t + φ · Σ ε over bars t−13 … t−2, a stationary moving average — a signal `dir_features`'s ret_1h
    carries): φ = −PHI (reversal) on the pairs in group 1 of two (BB, DD, FF) and +PHI (continuation) on group 0
    (AA, CC, EE). A model fitted on one group and scored on the other must forecast it wrong: the hold-out proof."""
    os.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 288, freq="5min")
    mkt = rng.normal(0, SD, len(t5))
    c5, fund, cost = [], [], []
    for i, sym in enumerate(PAIRS):
        phi = PHI if i % 2 == 0 else -PHI
        eps = rng.normal(0, SD, len(t5))
        r = eps.copy()
        for k in range(2, 14):
            r[k:] += phi * eps[:-k]
        px = 100 * (i + 1) * np.exp(np.cumsum(r + mkt) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - pd.Timedelta("5min"), "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0], periods=days * 3, freq="8h"), "rate": 0.0, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=days + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


def test_features_from_a_prefix_equal_the_full_panel_and_are_on_the_grid(tmp_path):
    _synth(tmp_path, days=20)
    M = bt.market(PAIRS, pd.Timestamp("2023-04-09", tz="UTC"))
    a, b = fc.RidgeBook(hold=HOLD, groups=2, min_pairs=2), fc.RidgeBook(hold=HOLD, groups=2, min_pairs=2)
    a._ensure(M)
    b._ensure(M.until(pd.Timestamp("2023-04-01", tz="UTC")))
    b._ensure(M)                                                                      # grown in two steps, the second on a tail
    assert all(t.minute == 0 for t in a._ts) and len(a._ts) == len(b._ts)
    Xa, Sa = a._rows(pd.DatetimeIndex(a._ts))
    Xb, Sb = b._rows(pd.DatetimeIndex(a._ts))
    assert np.allclose(np.nan_to_num(Xa), np.nan_to_num(Xb)) and np.allclose(np.nan_to_num(Sa), np.nan_to_num(Sb))
    # after the warm-up every feature is finite, and a full-panel computation agrees
    D = fc._derive(M.close)
    X, S = fc._cells(fc.dir_features(D), D["sig"]["1w"])
    pos = M.index.get_indexer(pd.DatetimeIndex(a._ts))
    assert np.allclose(np.nan_to_num(X[pos]), np.nan_to_num(Xa)) and np.isfinite(Xa[-100:]).all()


def test_held_out_pairs_are_scored_by_a_model_that_never_saw_them(tmp_path):
    _synth(tmp_path)
    s = fc.RidgeBook(hold=HOLD, min_bps=2.0, groups=2, min_pairs=2)
    r = bt.run(s, PAIRS, ["F1"], draws=3, refit_days=15, execs=("taker",))
    o = s.oos().dropna(subset=["f_bps"])
    assert len(o) > 3000 and set(o["group"]) == {0, 1} and (o.groupby("t").size() <= len(PAIRS)).all()
    y = bt.labels(bt.market(PAIRS, o["t"].max() + pd.Timedelta("2D")), HOLD, bt.LATENCY)
    o["y"] = y.to_numpy()[y.index.get_indexer(o["t"]), y.columns.get_indexer(o["symbol"])]
    o = o.dropna(subset=["y"])
    o["yres"] = o["y"] - o.groupby("t")["y"].transform("mean")
    corr = {g: np.corrcoef(d["f_bps"], d["yres"])[0, 1] for g, d in o.groupby("group")}
    # group 0 (AA, CC, EE) continues and is scored by the model fitted on group 1, which reverses; group 1 by the model fitted
    # on group 0. Each model learned the OTHER behaviour, so both held-out forecasts must come out wrong: the sign is the proof.
    assert corr[0] < -0.10 and corr[1] < -0.10, corr
    res = r["results"].query("exec == 'taker' and scope == 'all'").iloc[0]
    assert res["trades"] > 200 and res["gross"] < 0 and np.isfinite(res["hedged_net"])
    assert (r["dir"] / "forecast.md").exists() and "held-out IC" in (r["dir"] / "forecast.md").read_text()


def test_same_sign_pairs_are_forecast_right_and_hedged_net_is_net_against_the_market(tmp_path):
    _synth(tmp_path)
    # every pair reverses: rewrite the continuing ones by flipping the sign convention (group 0 rebuilt with PHI)
    c = pd.read_parquet("data/candles_5m.parquet")
    keep = c[c["symbol"].isin(["BBUSDT", "DDUSDT", "FFUSDT"])]
    pairs = ["BBUSDT", "DDUSDT", "FFUSDT"]
    pd.concat([keep, keep.assign(symbol=keep["symbol"].map(dict(zip(pairs, ["AAUSDT", "CCUSDT", "EEUSDT"]))), close=keep["close"] * 1.5, high=keep["high"] * 1.5, low=keep["low"] * 1.5)]).to_parquet("data/candles_5m.parquet", index=False)
    s = fc.RidgeBook(hold=HOLD, min_bps=2.0, groups=2, min_pairs=2)
    r = bt.run(s, PAIRS, ["F1"], draws=3, refit_days=15, execs=("taker",))
    res = r["results"].query("exec == 'taker' and scope == 'all'").iloc[0]
    assert res["trades"] > 200 and res["gross"] > 2 and res["hedged_lo"] > 0
    f = r["fills"]["taker"].dropna(subset=["net_bps"])
    assert np.allclose(f["hedged_net_bps"], f["net_bps"] - (f["gross_bps"] - f["hedged_bps"]))
    assert 0.25 <= f["size"].min() and f["size"].max() <= s.cap
    txt = (r["dir"] / "forecast.md").read_text()
    assert "held-out IC" in txt and "Calibration" in txt and "| F1" in txt


def test_decisions_do_not_read_the_future(tmp_path):
    _synth(tmp_path, days=60)
    s = fc.RidgeBook(hold=HOLD, min_bps=2.0, groups=2, min_pairs=2)
    M = bt.market(PAIRS, pd.Timestamp("2023-05-19", tz="UTC"))
    y = bt.labels(M, HOLD, bt.LATENCY)
    a, b = pd.Timestamp("2023-05-03", tz="UTC"), pd.Timestamp("2023-05-18", tz="UTC")
    cut = M.index.searchsorted(a) - (bt.LATENCY + HOLD)
    s.fit(M.until(a), y.iloc[:cut], a)
    bt.causal_check(s, M, a, b)


def test_no_model_means_no_trade():
    s = fc.RidgeBook(hold=HOLD, groups=2, min_pairs=2)
    idx = pd.date_range("2024-01-01", periods=300, freq="5min", tz="UTC")
    flat = pd.DataFrame(np.random.default_rng(0).normal(100, 1, (300, 2)), index=idx, columns=["A", "B"])
    M = bt.Market(flat, flat, flat, flat)
    s.fit(M.until(idx[200]), bt.labels(M, HOLD, 1).iloc[:150], idx[200])
    assert s.decide(M, idx[200], idx[-1]).empty


def test_a_flat_stretch_makes_no_feature_and_no_forecast(tmp_path):
    _synth(tmp_path, days=60)
    c = pd.read_parquet("data/candles_5m.parquet")
    flat = (c["symbol"] == "AAUSDT") & (c["open_time"] >= pd.Timestamp("2023-05-01", tz="UTC")) & (c["open_time"] < pd.Timestamp("2023-05-10", tz="UTC"))
    c.loc[flat, ["close", "high", "low"]] = 100.0                                                 # nine days without a tick: σ_1w = 0
    c.to_parquet("data/candles_5m.parquet", index=False)
    s = fc.RidgeBook(hold=HOLD, min_bps=2.0, groups=2, min_pairs=2)
    r = bt.run(s, PAIRS, ["F1"], draws=2, refit_days=15, execs=("taker",))
    o = s.oos()
    assert o["f_bps"].notna().sum() > 1000 and np.isfinite(o["f_bps"].dropna()).all()
    assert o[(o["symbol"] == "AAUSDT") & (o["t"] < pd.Timestamp("2023-05-10", tz="UTC"))]["f_bps"].isna().all()
    assert r["results"].query("exec == 'taker' and scope == 'all'")["trades"].iloc[0] > 100
