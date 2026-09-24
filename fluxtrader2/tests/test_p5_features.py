"""P5 step 10 — the ridge on the P2 screen's full feature set (`RidgeBook(features="all")`, registration R15):
the twelve external features reach the model causally, the candle-only reference inside the run IS the `candle` model,
and a signal that lives only in an external feature is learned on pairs the model never saw."""
import os

import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import ceiling
from ft2 import forecast as fc

PAIRS = ["AAUSDT", "BBUSDT", "CCUSDT", "DDUSDT", "EEUSDT", "FFUSDT"]
HOLD, SD, GAMMA = 12, 5.0, 2.0


def _synth(tmp_path, days=75, start="2023-03-20", seed=5, planted=True):
    """Random-walk pairs sharing a market factor. Each pair carries a latent s, i.i.d. N(0,1) per hour block (bars
    12b … 12b+11), independent across pairs, visible ONLY through the archive metrics' taker ratio (row j shows exp(s_{j//12}))
    and, when `planted`, moving the pair's bars ONE block later: r_j = ε_j + GAMMA · s_{(j−1)//12 − 1}. At a grid bar i (i % 12 = 0)
    `taker_ratio_1h` (the rolling-12 mean of the log ratio, rows i−12 … i−1) equals s_{i//12−1}, which is what the label's
    twelve bars i+1 … i+12 carry; every trailing return at i carries only s_{≤ i//12−2}. The candles cannot see it; the ratio can."""
    os.chdir(tmp_path)
    for d in ("data/tape", "data/depth", "output"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 288, freq="5min")
    mkt = rng.normal(0, SD, len(t5))
    c5, met, fund, cost = [], [], [], []
    for i, sym in enumerate(PAIRS):
        blocks = rng.normal(0, 1, len(t5) // 12 + 3)
        j = np.arange(len(t5))
        s = blocks[j // 12 + 1]
        r = rng.normal(0, SD, len(t5))
        if planted:
            r += GAMMA * blocks[(j - 1) // 12]                                          # = s_{(j−1)//12 − 1} in the block numbering of s
        px = 100 * (i + 1) * np.exp(np.cumsum(r + mkt) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - pd.Timedelta("5min"), "high": px * 1.0005, "low": px * 0.9995, "close": px,
                                "volume": rng.uniform(10, 20, len(t5))}))
        tm = pd.date_range(t5[0], periods=days * 1440, freq="min")
        buy = rng.uniform(1, 2, len(tm))
        pd.DataFrame({"symbol": sym, "ts": tm, "buy_vol": buy, "sell_vol": 3 - buy, "volume": 3.0,
                      "eff_spread_bps": rng.uniform(0.5, 1.5, len(tm))}).to_parquet(f"data/tape/{sym}.parquet", index=False)
        td = pd.date_range(t5[0], periods=days * 2880, freq="30s")
        u = rng.uniform(1e6, 2e6, (len(td), 4))
        pd.DataFrame({"symbol": sym, "ts": td, "usd_m1": u[:, 0], "usd_p1": u[:, 1], "usd_m5": u[:, 2] * 5,
                      "usd_p5": u[:, 3] * 5}).to_parquet(f"data/depth/{sym}.parquet", index=False)
        met.append(pd.DataFrame({"symbol": sym, "ts": t5, "oi": np.exp(np.cumsum(rng.normal(0, 1e-3, len(t5)))) * 1e6, "oi_value": 1.0,
                                 "top_ls_count": 1.0, "top_ls_sum": rng.uniform(0.8, 1.2, len(t5)), "global_ls": rng.uniform(0.8, 1.2, len(t5)),
                                 "taker_ratio": np.exp(s)}))
        ft = pd.date_range(t5[0], periods=days * 3, freq="8h")
        fund.append(pd.DataFrame({"symbol": sym, "ts": ft, "rate": rng.normal(1e-4, 5e-5, len(ft)), "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=days + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(met).to_parquet("data/metrics.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


def test_all_has_26_columns_from_a_prefix_equal_to_the_full_panel_and_candle_is_unchanged(tmp_path):
    _synth(tmp_path, days=20)
    end = pd.Timestamp("2023-04-09", tz="UTC")
    s = fc.RidgeBook(hold=HOLD, groups=2, min_pairs=2, features="all")
    assert s.needs == ("external",) and s.params()["features"] == "all" and "needs" not in s.params()
    M = bt.market(PAIRS, end, needs=s.needs)
    assert list(M.extra["external"].columns.get_level_values(0).unique()) == ceiling.EXTERNAL
    a, b = fc.RidgeBook(hold=HOLD, groups=2, min_pairs=2, features="all"), fc.RidgeBook(hold=HOLD, groups=2, min_pairs=2, features="all")
    a._ensure(M)
    b._ensure(M.until(pd.Timestamp("2023-04-01", tz="UTC")))
    b._ensure(M)
    Xa, Sa = a._rows(pd.DatetimeIndex(a._ts))
    Xb, Sb = b._rows(pd.DatetimeIndex(a._ts))
    assert Xa.shape[-1] == fc.N_ALL == 26 and len(a._ts) == len(b._ts)
    assert np.allclose(np.nan_to_num(Xa), np.nan_to_num(Xb)) and np.allclose(np.nan_to_num(Sa), np.nan_to_num(Sb))
    assert np.isfinite(Xa[-50:]).all()                                                     # after the warm-up every column is there
    # the candle columns of `all` are the `candle` model's columns, in its order
    c = fc.RidgeBook(hold=HOLD, groups=2, min_pairs=2)
    assert c.needs == () and c.n_feat == fc.N_CANDLE == 12
    c._ensure(bt.market(PAIRS, end))
    Xc, _ = c._rows(pd.DatetimeIndex(a._ts))
    assert np.allclose(np.nan_to_num(Xc), np.nan_to_num(Xa[:, :, a._cand]))
    # the external columns are the screen's, to the digit
    D = ceiling.derive({"close": M.close, "high": M.high, "low": M.low, "dv": M.dv})
    E, notes = ceiling.external_features(M.index, list(M.columns), end)
    assert notes == []
    pos = M.index.get_indexer(pd.DatetimeIndex(a._ts))
    for k_, name in enumerate(ceiling.EXTERNAL):
        assert np.allclose(np.nan_to_num(E[name].to_numpy()[pos]), np.nan_to_num(Xa[:, :, 12 + k_])), name


def test_a_signal_only_an_external_feature_carries_is_learned_on_held_out_pairs_and_the_reference_is_the_candle_model(tmp_path):
    _synth(tmp_path)
    s = fc.RidgeBook(hold=HOLD, min_bps=2.0, groups=2, min_pairs=2, features="all")
    r = bt.run(s, PAIRS, ["F1"], draws=2, refit_days=15, execs=("taker",), name="all")
    o = s.oos().dropna(subset=["f_bps"])
    assert len(o) > 3000 and o["f_ref_bps"].notna().all()
    y = bt.labels(bt.market(PAIRS, o["t"].max() + pd.Timedelta("2D")), HOLD, bt.LATENCY)
    o["y"] = y.to_numpy()[y.index.get_indexer(o["t"]), y.columns.get_indexer(o["symbol"])]
    o = o.dropna(subset=["y"])
    o["yres"] = o["y"] - o.groupby("t")["y"].transform("mean")
    ic_all = np.corrcoef(o["f_bps"], o["yres"])[0, 1]
    ic_ref = np.corrcoef(o["f_ref_bps"], o["yres"])[0, 1]
    assert ic_all > 0.3 and abs(ic_ref) < 0.1, (ic_all, ic_ref)                          # the candles cannot see s; the taker ratio can
    res = r["results"].query("exec == 'taker' and scope == 'all'").iloc[0]
    assert res["trades"] > 200 and res["hedged_lo"] > 0
    txt = (r["dir"] / "forecast.md").read_text()
    assert "Paired against the candle-only reference" in txt and "Paired difference `all` − reference: +" in txt
    saved = pd.read_parquet(r["dir"] / "forecast.parquet")
    assert {"f_bps", "f_ref_bps", "sigma_h"} <= set(saved.columns) and len(saved) == len(s.oos())
    # the reference inside the `all` run IS the `candle` run: same forecasts on every cell the candle run forecasts
    c = fc.RidgeBook(hold=HOLD, min_bps=2.0, groups=2, min_pairs=2)
    bt.run(c, PAIRS, ["F1"], draws=0, refit_days=15, execs=("taker",), name="candle")
    oc = c.oos().set_index(["t", "symbol"])["f_bps"]
    oa = s.oos().set_index(["t", "symbol"])["f_ref_bps"].reindex(oc.index)
    assert oc.notna().sum() > 3000 and np.allclose(oc.fillna(0), oa.fillna(0), atol=1e-6)


def test_without_the_planted_signal_the_extra_features_add_nothing(tmp_path):
    _synth(tmp_path, planted=False)
    s = fc.RidgeBook(hold=HOLD, min_bps=2.0, groups=2, min_pairs=2, features="all")
    bt.run(s, PAIRS, ["F1"], draws=0, refit_days=15, execs=("taker",), name="null")
    o = s.oos().dropna(subset=["f_bps"])
    y = bt.labels(bt.market(PAIRS, o["t"].max() + pd.Timedelta("2D")), HOLD, bt.LATENCY)
    o["y"] = y.to_numpy()[y.index.get_indexer(o["t"]), y.columns.get_indexer(o["symbol"])]
    o = o.dropna(subset=["y"])
    o["yres"] = o["y"] - o.groupby("t")["y"].transform("mean")
    assert abs(np.corrcoef(o["f_bps"], o["yres"])[0, 1]) < 0.1


def test_features_must_be_a_known_set():
    import pytest
    with pytest.raises(ValueError):
        fc.RidgeBook(features="book")
