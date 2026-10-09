"""R31 unit tests for `rules.IndexHour` (`ixhour4h`) on made-up bars: the frame the harness attaches is R30's ix_1h to the digit;
a decision sits `lag` bars after an hour's close, carries that hour's sign, needs |f| ≥ θ and the index open at H and H − 1 h
(no weekend, no break, no first hour of the week), and takes every pair present; nothing after the hour enters (the value at
H + lag is the value at H, and the harness's causal check passes); a basket planted to follow the index's last hour earns at the
rule's sign; and the rule goes through `backtest.run` with the index read from `data/index_1m.parquet`."""
import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import market_ext as mx
from ft2 import rules
from ft2.audit_index import INDEX, Minutes
from test_p3 import PAIRS, _synth
from test_p8_market_ext import _world

LAG = 3


def _M(follow: float):
    P, D, F6, _, s, mi, idx = _world(follow)
    M = bt.Market(P["close"], P["high"], P["low"], P["dv"])
    M.extra["ix_1h"] = mx.ix_1h_frame(idx, idx[-1] + bt.BAR, mi)
    return M, mi, idx, F6, idx[40 * 288]


def test_the_frame_is_r30s_ix_1h_to_the_digit():
    M, mi, idx, F6, _ = _M(0.0)
    F, _ = mx.features_index(idx, F6, mi)
    a, b = M.extra["ix_1h"]["ix_1h"], F["ix_1h"]
    assert a.isna().equals(b.isna()) and b.notna().sum() > 0.4 * len(idx)
    assert np.allclose(a.dropna().to_numpy(), b.dropna().to_numpy(), rtol=0, atol=1e-12)


def test_a_decision_sits_lag_bars_after_an_open_hour_with_its_sign_on_every_pair():
    M, mi, idx, _, warm = _M(0.0)
    rule = rules.IndexHour(theta=1.0, lag=LAG)
    d = rule.decide(M, warm, idx[-1] + bt.BAR)
    s = M.extra["ix_1h"]["ix_1h"]
    t = pd.DatetimeIndex(d["t"])
    tH = t - LAG * bt.BAR
    assert len(d) and (tH.minute == 0).all() and (t >= warm).all()
    f = s.reindex(tH).to_numpy()
    assert (np.abs(f) >= 1.0).all() and (d["side"].to_numpy() == np.sign(f)).all() and (d["size"] == 1.0).all()
    per_t = d.groupby("t")["side"].agg(["nunique", "size"])
    assert (per_t["nunique"] == 1).all() and (per_t["size"] == M.close.shape[1]).all()
    # the hours under the threshold, and the hours the index was not open at both ends of, give nothing
    hours = s[(s.index.minute == 0) & (s.index >= warm)]
    under = hours[hours.notna() & (hours.abs() < 1.0)].index + LAG * bt.BAR
    closed = hours[hours.isna()].index + LAG * bt.BAR
    assert not (set(under) | set(closed)) & set(t)
    # the made-up index trades Monday 00:00 → Friday 21:00 less the 21:00 hour: no weekend, no 22:00 / 23:00 (closed at H or H − 1 h),
    # no Monday 00:00 / 01:00 (closed at H − 1 h), and the share of trading hours is a third or so (|f| ≥ 1σ)
    assert (tH.dayofweek < 5).all() and not tH.hour.isin([22, 23]).any() and not ((tH.dayofweek == 0) & (tH.hour <= 1)).any()
    assert 0.2 < len(per_t) / max(hours.notna().sum(), 1) < 0.5


def test_nothing_after_the_hour_enters():
    M, mi, idx, _, warm = _M(0.0)
    rule = rules.IndexHour(theta=1.0, lag=LAG)
    d = rule.decide(M, warm, idx[-1] + bt.BAR)
    s = M.extra["ix_1h"]["ix_1h"]
    t = pd.DatetimeIndex(d["t"])
    # the signal carried on the decision is the hour's value, not the value at the decision bar (which is a different hour-ending move)
    at_t = s.reindex(t).to_numpy()
    assert np.allclose(d["signal"].to_numpy(), s.reindex(t - LAG * bt.BAR).to_numpy()) and not np.allclose(d["signal"].to_numpy(), np.nan_to_num(at_t))
    # the harness's own check: decisions before the middle of a block do not change when the market after it is removed
    bt.causal_check(rule, M, warm, idx[-1] + bt.BAR)
    # and a rewritten future: the minutes after an hour H with a decision are replaced → the decision at H + lag is unchanged
    H = (t - LAG * bt.BAR)[len(t) // 2]
    m = mi.ts, np.exp(mi.lc)
    df = pd.DataFrame({"ts": m[0], "close": m[1]})
    df.loc[df["ts"] > H, "close"] = df.loc[df["ts"] > H, "close"].to_numpy()[::-1]
    M2 = bt.Market(M.close, M.high, M.low, M.dv, {"ix_1h": mx.ix_1h_frame(idx, idx[-1] + bt.BAR, Minutes(df))})
    d2 = rules.IndexHour(theta=1.0, lag=LAG).decide(M2, warm, H + (LAG + 1) * bt.BAR)
    d1 = d[d["t"] <= H + LAG * bt.BAR]
    assert len(d1) and d1[["t", "symbol", "side"]].reset_index(drop=True).equals(d2[["t", "symbol", "side"]].reset_index(drop=True))


def test_a_planted_follower_earns_at_the_rules_sign():
    M, mi, idx, _, warm = _M(2.0)                       # the basket makes twice the index's hourly move, 0.4 inside the hour and 0.3 / 0.2 / 0.1 after
    d = rules.IndexHour(theta=1.0, lag=LAG).decide(M, warm, idx[-1] + bt.BAR)
    y = bt.labels(M, 48, bt.LATENCY)
    g = d["side"].to_numpy() * y.to_numpy()[M.index.get_indexer(d["t"]), M.columns.get_indexer(d["symbol"])]
    per_hour = pd.Series(g).groupby(d["t"].to_numpy()).mean().dropna()
    tstat = per_hour.mean() / (per_hour.std() / np.sqrt(len(per_hour)))
    assert per_hour.mean() > 0 and tstat > 4
    M0 = _M(0.0)[0]                                      # the same index, a basket that ignores it: the same decisions earn nothing
    d0 = rules.IndexHour(theta=1.0, lag=LAG).decide(M0, warm, idx[-1] + bt.BAR)
    y0 = bt.labels(M0, 48, bt.LATENCY)
    g0 = d0["side"].to_numpy() * y0.to_numpy()[M0.index.get_indexer(d0["t"]), M0.columns.get_indexer(d0["symbol"])]
    assert abs(np.nanmean(g0)) < per_hour.mean() / 3  # a basket that ignores the index earns nothing at the sign


def _index_file(start: pd.Timestamp, days: int, seed: int = 11) -> None:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start - pd.Timedelta(days=40), periods=(days + 40) * 1440, freq="1min")
    keep = (ts.dayofweek < 5) & (ts.hour != 21) & ~((ts.dayofweek == 4) & (ts.hour >= 21))
    ts = ts[keep]
    pd.DataFrame({"symbol": INDEX, "ts": ts, "close": 100 * np.exp(np.cumsum(rng.normal(0, 1.5e-4, len(ts))))}).to_parquet("data/index_1m.parquet", index=False)


def test_through_the_harness(tmp_path):
    _synth(tmp_path)
    _index_file(pd.Timestamp("2023-03-20", tz="UTC"), 80)
    r = bt.run(bt.get_strategy("ixhour4h", {}), PAIRS, ["F1"], draws=3)
    assert r["meta"]["params"] == {"theta": 1.0, "lag": 3, "hold": 48}
    res = r["results"]
    x = res.query("scope == 'all' and exec == 'maker'").iloc[0]
    assert x["trades"] > 50 and 0 < x["p_fill"] <= 1
    f = r["fills"]["maker"] if "fills" in r else None
    if f is not None:
        tH = pd.DatetimeIndex(f["entry_t"]) - (bt.LATENCY + 3) * bt.BAR
        assert (tH.minute == 0).all() and (tH.dayofweek < 5).all()
