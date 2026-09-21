"""P5 unit tests for the market-factor audit (`ft2/market.py`, registration R6): features never read
their future, a random walk shows no signal, a planted market-wide reversal comes back with its sign
through the screen, the shift null and the walk-forward ridge, and confirmation folds are refused."""
import numpy as np
import pandas as pd
import pytest

from ft2 import market as mk

DAYS, N = 220, 6


def _panel(rev: float, seed: int = 3, start: str = "2023-09-01") -> dict:
    """Six pairs = one market factor + own noise. `rev`: the share of the market's last-4h move that is
    given back over the next 4 hours (0 = a random walk)."""
    rng = np.random.default_rng(seed)
    n = DAYS * 288
    m = rng.normal(0, 6.0, n)
    for i in range(48, n):
        m[i] -= rev * m[i - 48:i].sum() / 48 if rev else 0.0
    r = m[:, None] + rng.normal(0, 4.0, (n, N))
    idx = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=n, freq="5min", name="t")
    close = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0) / 1e4), index=idx, columns=list("ABCDEF"))
    return {"close": close, "high": close, "low": close, "dv": pd.DataFrame(1e6, index=idx, columns=close.columns)}


def _audit(P, draws=20):
    D = mk.derive(P)
    F, signed = mk.features(P, D)
    s = np.asarray(P["close"].index >= P["close"].index[0] + pd.Timedelta(days=40))
    return D, F, signed, s, mk.screen(D, F, signed, s, draws=draws)[0]


def test_features_and_labels_are_causal():
    P = _panel(0.0)
    cut = 150 * 288
    F_all, _ = mk.features(P, mk.derive(P))
    Pc = {k: v.iloc[:cut] for k, v in P.items()}
    Dc = mk.derive(Pc)
    F_cut, _ = mk.features(Pc, Dc)
    for k in F_all:
        pd.testing.assert_series_equal(F_all[k].iloc[:cut], F_cut[k], check_names=False)
    assert Dc["fwd"]["4h"].iloc[-48:].isna().all() and Dc["fwd"]["4h"].iloc[-49:-48].notna().all()      # a label never reaches past the cut


def _per_day_corr(f, y, day):
    """The statistic P2 used until 2026-09-21: the mean of per-day uncentred correlations."""
    ok = ~(np.isnan(f) | np.isnan(y))
    nd = int(day.max()) + 1
    num, sf, sy = (np.bincount(day[ok], w, nd) for w in (f[ok] * y[ok], f[ok] ** 2, y[ok] ** 2))
    with np.errstate(invalid="ignore", divide="ignore"):
        return float(np.nanmean(num / np.sqrt(sf * sy)))


def test_ic_statistic_is_unbiased_on_random_walks():
    """A per-day normaliser is largest on the days that trend, which shrinks exactly the positive products:
    the mean of per-day correlations reads a NEGATIVE IC for a trailing return on pure random walks — on one
    series and on P2's pooled pairs alike. The whole-sample correlation (`ic_stats`, `_ic_pooled`) does not."""
    from ft2 import ceiling
    ts, per_day, ts2, per_day2 = [], [], [], []
    for seed in range(6):
        P = _panel(0.0, seed=seed, start="2023-05-10")                                                   # inside F1, for ceiling.derive
        D = mk.derive(P)
        F, _ = mk.features(P, D)
        idx = P["close"].index
        day = (idx.floor("D") - idx[0].floor("D")).days.to_numpy()
        f, y = F["mret_1d"].clip(-5, 5).to_numpy(), D["z"]["4h"].to_numpy()
        ts.append(mk.ic_stats(f, y, day, 2)["t"])
        per_day.append(_per_day_corr(f, y, day))
        D2 = ceiling.derive(P)                                                                           # P2's pooled (bar × pair) cells
        f2 = ceiling._pair_rank(ceiling.dir_features(D2)["ret_1d"]).to_numpy().ravel()
        y2, day2 = D2["z"]["4h"].clip(-5, 5).to_numpy().ravel(), np.repeat(day, N)
        m, se, _ = ceiling.hac(ceiling._ic_pooled(f2, y2, day2), 2)
        ts2.append(m / se)
        per_day2.append(_per_day_corr(f2, y2, day2))
    for t in (ts, ts2):
        assert abs(np.mean(t)) < 1.0 and max(abs(v) for v in t) < 3.5
    assert np.mean(per_day) < -0.04 and np.mean(per_day2) < -0.015                                       # the bias, kept on record


def test_random_walk_has_no_signal_and_planted_reversal_is_found_with_its_sign():
    *_, sc = _audit(_panel(0.0))
    d = sc[(sc["bet"] == "directional") & (sc["horizon"] == "4h")].set_index("feature")
    assert abs(d.loc["mret_4h", "t"]) < 3 and d["p_fw"].min() > 0.05
    D, F, signed, s, sc = _audit(_panel(0.5))
    d = sc[(sc["bet"] == "directional") & (sc["horizon"] == "4h")].set_index("feature")
    assert d.loc["mret_4h", "ic"] < -0.05 and d.loc["mret_4h", "p_single"] <= 0.05 and d.loc["mret_4h", "years_same_sign"] == 2
    assert {"2023", "2024"} <= set(sc.columns)
    fc = mk.forecast(D, F, signed, s, draws=10, horizons=("4h",))
    f = fc[fc["window"] == "120"].iloc[0]
    assert f["ic"] > 0.05 and f["p_one_sided"] <= 0.1 and f["years_positive"] == 2


def test_ridge_forecasts_only_after_enough_history_and_only_scored_bars():
    P = _panel(0.5)
    D = mk.derive(P)
    F, signed = mk.features(P, D)
    idx = P["close"].index
    s = np.asarray(idx >= idx[0] + pd.Timedelta(days=45))
    yhat = mk.walk_ridge(mk.design(D, F, signed), D["z"]["4h"].to_numpy(), idx.tz_localize(None).to_numpy(), s, 48, 120)
    first = idx[~np.isnan(yhat)][0]
    assert np.isnan(yhat[~s]).all() and first >= idx[0] + pd.Timedelta(days=30 + mk.MIN_TRAIN_DAYS)     # 30d lookback, then MIN_TRAIN_DAYS of labels


def test_cond_mean_is_a_day_clustered_ratio():
    day = np.repeat(np.arange(40), 10)
    y = np.where(day % 2 == 0, 10.0, 20.0)
    on = np.ones(len(y), dtype=bool)
    on[day % 2 == 1] = np.arange((day % 2 == 1).sum()) % 2 == 0                                         # half as many bars on the 20-days
    r = mk.cond_mean(y, on, day, 2)
    assert abs(r["mean"] - (10 * 200 + 20 * 100) / 300) < 1e-9 and r["days"] == 40 and r["se"] > 0
    assert np.isnan(mk.cond_mean(y, np.zeros(len(y), dtype=bool), day, 2)["mean"])


def test_shifts_stay_away_from_zero_and_confirmation_folds_are_refused(tmp_path, monkeypatch):
    sh = mk.shifts(1000, 500, 0)
    assert sh[0] == 0 and sh[1:].min() >= mk.SHIFT_MIN and sh[1:].max() <= 1000 - mk.SHIFT_MIN
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        mk.run(5.0, 2.0, "test", ["AUSDT"], ["F2", "F3"])


def test_trendfall_buys_every_pair_after_a_market_fall_only_when_the_trend_is_up():
    from ft2 import backtest as bt
    from ft2.rules import TrendFall
    for drift, traded in ((+1.0, True), (-1.0, False)):
        rng = np.random.default_rng(5)
        idx = pd.date_range("2024-01-01", periods=60 * 288, freq="5min", tz="UTC")
        r = rng.normal(0, 5.0, (len(idx), N)) + drift                                                    # ±1 bps a bar ≈ ±86 % over the 30 days
        r[-24:] -= 25                                                                                   # every pair loses ~600 bps in the last 2 hours
        close = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0) / 1e4), index=idx, columns=list("ABCDEF"))
        M = bt.Market(close, close, close, close)
        now = M.index[-288]
        d = TrendFall().decide(M, now, M.index[-1] + bt.BAR)
        last = d[d["t"] == M.index[-1]]
        assert (len(last) == N and (last["side"] == 1).all()) if traded else last.empty
        assert d[d["t"] < M.index[-24]].empty                                                           # nothing before the fall
    bt.causal_check(TrendFall(), M, now, M.index[-1] + bt.BAR)
