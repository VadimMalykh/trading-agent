"""R32 unit tests for `trend1d` on made-up bars: the rule's trend IS R6's basket return (`market.derive`'s blr) to 1e-9; it decides
once a day at the registered hour, on every pair, at the basket's sign; nothing with fewer than MIN_PAIRS pairs; the causal check
passes; and a planted trending basket comes back through the harness long every day, one round trip a day, at its planted size minus
the cost."""
import os

import numpy as np
import pandas as pd

from ft2 import backtest as bt, market as mk
from ft2.rules import Trend1d

PAIRS = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT", "FFFUSDT"]
K = 30 * 288


def _close(drift: float, n_pairs: int = 6, days: int = 70, seed: int = 7, start: str = "2024-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 288, freq="5min", name="t")
    r = rng.normal(0, 5.0, (len(idx), n_pairs)) + drift
    return pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0) / 1e4), index=idx, columns=PAIRS[:n_pairs])


def test_the_rules_trend_is_r6s_basket_return():
    close = _close(0.0)
    D = mk.derive({"close": close, "high": close, "low": close, "dv": pd.DataFrame(1e6, index=close.index, columns=close.columns)})
    r6 = D["blr"] - D["blr"].shift(K)
    tr = Trend1d().trend(close)
    both = r6.notna() & tr.notna()
    assert both.sum() > 30 * 288 and r6.notna().equals(tr.notna())
    assert np.allclose(tr[both], r6[both], atol=1e-9)


def test_decides_once_a_day_at_the_hour_on_every_pair_at_the_baskets_sign():
    for drift, side in ((+1.0, 1), (-1.0, -1)):
        close = _close(drift)
        M = bt.Market(close, close, close, close)
        a, b = M.index[-10 * 288], M.index[-1] + bt.BAR
        d = Trend1d().decide(M, a, b)
        t = pd.DatetimeIndex(d["t"])
        assert len(d) == 10 * 6 and (t.hour == 0).all() and (t.minute == 0).all()           # one bar a day, every pair
        assert (d["side"] == side).all() and (d["size"] == 1.0).all()
        assert d.groupby("t")["symbol"].nunique().eq(6).all()
        assert np.sign(d["signal"]).eq(side).all()                                          # the signal is the trend itself
        bt.causal_check(Trend1d(), M, a, b)
    close = _close(1.0)
    M = bt.Market(close, close, close, close)
    assert (Trend1d(hour=8).decide(M, M.index[-2 * 288], M.index[-1] + bt.BAR)["t"].dt.hour == 8).all()


def test_fewer_than_min_pairs_or_no_history_means_no_trade():
    close = _close(1.0, n_pairs=4)
    M = bt.Market(close, close, close, close)
    assert Trend1d().decide(M, M.index[-5 * 288], M.index[-1] + bt.BAR).empty           # 4 < MIN_PAIRS: the basket is NaN
    close = _close(1.0, days=25)                                                         # 25 days < the 30-day window
    M = bt.Market(close, close, close, close)
    assert Trend1d().decide(M, M.index[0], M.index[-1] + bt.BAR).empty


def _world(tmp_path, drift: float, days: int = 80, start: str = "2023-03-20", seed: int = 3):
    """Six random-walk pairs with a common drift (bps a 5m bar), test_p3's cost and funding files: F0's tail → F1."""
    os.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 288, freq="5min")
    c5, fund, cost = [], [], []
    for i, sym in enumerate(PAIRS):
        px = 100 * (i + 1) * np.exp(np.cumsum(rng.normal(0, 5.0, len(t5)) + drift) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - bt.BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        ft = pd.date_range(t5[0], periods=days * 3, freq="8h")
        fund.append(pd.DataFrame({"symbol": sym, "ts": ft, "rate": 0.0, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=days + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


def test_a_trending_basket_comes_back_long_every_day_through_the_harness(tmp_path):
    drift = 3.0                                                                          # +3 bps a bar ≈ +864 bps a day
    _world(tmp_path, drift)
    out = bt.run(Trend1d(), PAIRS, ["F1"], execs=("taker",), draws=3)
    dec, f = out["decisions"], out["fills"]["taker"].dropna(subset=["net_bps"])
    acc = dec[dec["accepted"]]
    t = pd.DatetimeIndex(acc["t"])
    assert (t.hour == 0).all() and (acc["side"] == 1).all()
    assert acc.groupby("t")["symbol"].nunique().eq(6).all()
    days = bt.scored_days(["F1"], out["decisions"]["t"].max())
    assert len(acc) == 6 * len(days) and len(dec) == len(acc)                           # every scored day, every pair, nothing blocked
    assert len(f) >= 6 * (len(days) - 2)                                                 # the last day's exit may be unpriced
    a = out["results"]
    a = a[(a["scope"] == "all") & (a["exec"] == "taker")].iloc[0]
    rt = 2 * 5.0 + 1.0 + 2 * 0.5
    assert 700 < a["gross"] < 1050 and 0 <= a["gross"] - a["net"] - rt < 1.0           # the planted move, less one round trip a day (the exit leg is charged on the position's value: a little more after a +9 % day)
    assert a["net_lo"] > 0 and a["trades_per_day"] == len(f) / len(days)
