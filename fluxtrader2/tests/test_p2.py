"""P2 unit tests on synthetic data: planted structure must be recovered (momentum → VR > 1 and a
positive IC on trailing returns; volatility regimes → magnitude R² far above direction R²),
nothing at or after the end of F2 may be read, and an end-to-end `ceiling` run over every source."""
import os

import numpy as np
import pandas as pd
import pytest

from ft2 import ceiling, folds

PAIRS = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"]


def _synth(tmp_path, start="2023-03-20", days=75, phi=0.25, late_days=0):
    """AR(1) 5m returns (momentum) with a volatility that switches every two days; F0 tail → F1."""
    os.chdir(tmp_path)
    for d in ("data/tape", "data/depth", "output"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1)
    t5 = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 288, freq="5min")
    c5, met, fund, cost = [], [], [], []
    regime = np.repeat(rng.choice([1.0, 3.0], days // 2 + 1), 2 * 288)[: len(t5)]
    for i, sym in enumerate(PAIRS):
        e = rng.normal(0, 8e-4, len(t5)) * regime
        r = np.zeros(len(t5))
        for j in range(1, len(t5)):
            r[j] = phi * r[j - 1] + e[j]
        px = 100 * (i + 1) * np.exp(np.cumsum(r))
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5, "high": px * 1.0005, "low": px * 0.9995, "close": px,
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
                                 "taker_ratio": rng.uniform(0.8, 1.2, len(t5))}))
        ft = pd.date_range(t5[0], periods=days * 3, freq="8h")
        fund.append(pd.DataFrame({"symbol": sym, "ts": ft, "rate": rng.normal(1e-4, 5e-5, len(ft)), "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=days + late_days, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{ceiling.NOTIONAL}": 0.5,
                                  f"maker_adv_{ceiling.MAKER_H}": -1.5}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(met).to_parquet("data/metrics.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


def test_variance_ratio_and_hac():
    rng = np.random.default_rng(0)
    e = rng.normal(size=50_000)
    vr, z = ceiling.variance_ratio(e, 12)
    assert abs(vr - 1) < 0.05 and abs(z) < 3                       # a random walk
    r = e.copy()
    for j in range(1, len(r)):
        r[j] = 0.3 * r[j - 1] + e[j]
    vr, z = ceiling.variance_ratio(r, 12)
    assert vr > 1.5 and z > 10                                     # momentum
    m, se, n = ceiling.hac(rng.normal(0.1, 1, 400), 2)
    assert n == 400 and 0.03 < se < 0.08 and abs(m - 0.1) < 0.2


def test_nothing_is_read_at_or_after_the_end_of_f2(tmp_path, monkeypatch):
    monkeypatch.setattr(ceiling, "MIN_PAIRS", 3)
    _synth(tmp_path, start="2024-08-20", days=20, late_days=5)     # runs to 2024-09-09, a week into F3
    P = ceiling.panel(PAIRS)
    D = ceiling.derive(P)
    assert P["close"].index.max() == ceiling.END
    for h, k in ceiling.HORIZONS.items():
        assert D["fwd"][h].iloc[-k:].isna().all().all()            # no label reaches past END
    F, _, notes = ceiling.features(P, D, PAIRS)
    assert not notes and all(f.index.max() == ceiling.END for f in F.values())
    assert D["scored"].sum() > 0 and D["lr"].index[D["scored"]].max() < ceiling.END


def test_features_use_only_the_past(tmp_path, monkeypatch):
    """Changing every source from some instant on must leave every feature before it untouched."""
    monkeypatch.setattr(ceiling, "MIN_PAIRS", 3)
    _synth(tmp_path, days=16)
    P = ceiling.panel(PAIRS)
    F0, _, _ = ceiling.features(P, ceiling.derive(P), PAIRS)
    cut = P["close"].index[len(P["close"]) // 2]
    for path, col in [("data/candles_5m.parquet", "open_time"), ("data/metrics.parquet", "ts"), ("data/funding_archive.parquet", "ts"),
                      *[(f"data/{k}/{s}.parquet", "ts") for k in ("tape", "depth") for s in PAIRS]]:
        x = pd.read_parquet(path)
        late = x[col] >= (cut - ceiling.BAR if col == "open_time" else cut)     # the candle opening at cut − 5m closes at cut
        num = [c for c in x.columns if x[c].dtype.kind == "f"]
        x.loc[late, num] = x.loc[late, num] * 1.37
        x.to_parquet(path, index=False)
    P1 = ceiling.panel(PAIRS)
    F1, _, _ = ceiling.features(P1, ceiling.derive(P1), PAIRS)
    for name in F0:
        a, b = F0[name][F0[name].index < cut], F1[name][F1[name].index < cut]
        pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-9, obj=name)


def test_ceiling_end_to_end_recovers_planted_structure(tmp_path, monkeypatch):
    monkeypatch.setattr(ceiling, "MIN_PAIRS", 3)
    _synth(tmp_path)
    text = ceiling.run(5.0, 2.0, "test", PAIRS)
    assert "Summary" in text and ceiling.OUT_MD.exists()
    mv = pd.read_parquet(ceiling.OUT_DIR / "move_vs_cost.parquet").set_index(["bet", "horizon"])
    assert mv.loc[("directional", "15m"), "taker_rt"] == pytest.approx(2 * 5 + 1 + 2 * 0.5)
    assert mv.loc[("directional", "15m"), "maker_rt"] == pytest.approx(2 * 2 + 2 * 1.5)
    assert mv.loc[("directional", "1d"), "share_gt_taker"] > mv.loc[("directional", "15m"), "share_gt_taker"]
    ls = pd.read_parquet(ceiling.OUT_DIR / "linear_structure.parquet")
    assert (ls[(ls["series"] == "raw") & (ls["horizon"] == "15m")]["vr"] > 1.2).all()
    ic = pd.read_parquet(ceiling.OUT_DIR / "ic.parquet").set_index(["bet", "horizon", "feature"])
    assert ic.loc[("directional", "15m", "ret_15m"), "t"] > 4 and ic.loc[("relative", "15m", "ret_15m"), "t"] > 4
    assert abs(ic.loc[("directional", "15m", "depth_imb_1"), "t"]) < 4          # pure noise stays noise
    r2 = pd.read_parquet(ceiling.OUT_DIR / "mag_vs_dir.parquet").set_index(["target", "horizon"])
    assert r2.loc[("magnitude |move|", "1h"), "r2_oos"] > 0.05
    assert r2.loc[("magnitude |move|", "1h"), "r2_oos"] > 5 * abs(r2.loc[("direction (own)", "1h"), "r2_oos"])
    assert r2.loc[("direction (own)", "15m"), "rank_ic"] > 0.02                  # the planted momentum, out of sample
    vt = pd.read_parquet(ceiling.OUT_DIR / "vol_timing.parquet")
    assert (vt["multiplier"] > 1.2).all()
    pw = pd.read_parquet(ceiling.OUT_DIR / "power.parquet")
    assert (pw["mde_bps_per_trade"] > 0).all()


def test_random_walk_has_no_directional_ic(tmp_path, monkeypatch):
    """Feature and label share the price at t; a statistic that demeans inside the day reads a large
    negative IC on a pure random walk (the defect that voided the first P2 run). Must stay at zero."""
    monkeypatch.setattr(ceiling, "MIN_PAIRS", 3)
    _synth(tmp_path, phi=0.0)
    P = ceiling.panel(PAIRS)
    D = ceiling.derive(P)
    F = {k: v for k, v in ceiling.dir_features(D).items() if k.startswith("ret_")}
    ic, _ = ceiling.ic_screen(D, F, set())
    x = ic[ic["bet"].isin(["directional", "relative"])]
    assert x["t"].abs().max() < 4, x.sort_values("t").head()
    # and the defect itself, kept as a record: one pair read with a within-day Spearman. Inside a day
    # f − mean = (p_t − p̄) − …, y − mean = … − (p_t − p̄): the expected correlation on a random walk is −0.5
    s_ = D["scored"]
    f, y = F["ret_1d"][s_][PAIRS[0]], D["z"]["1d"][s_][PAIRS[0]]
    day = f.index.floor("D")
    ics = [f[day == d].rank().corr(y[day == d].rank()) for d in day.unique()]
    assert np.nanmean(ics) < -0.3
