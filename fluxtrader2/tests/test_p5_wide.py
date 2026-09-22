"""R10 (the wider universe): k names a side pair up into dollar-neutral units; the tick is read off the candles;
the pooled candle proxy recovers a known cost law leave-one-pair-out and prices a pair that has no tape, which the
panel and the cost loader then carry into the harness."""
import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import ceiling, cost
from ft2.ladder import NOTIONALS
from ft2.rules import RankContinuation, RankReversal


def _market(n_pairs: int = 8, days: int = 45, seed: int = 5) -> bt.Market:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=days * 288, freq="5min", tz="UTC")
    r = rng.normal(0, 5.0, (len(idx), n_pairs))
    close = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0) / 1e4), index=idx, columns=[f"P{i}" for i in range(n_pairs)])
    return bt.Market(close, close, close, close)


def test_k_a_side_pairs_the_ith_lowest_with_the_ith_highest():
    M = _market()
    now = M.index[-288 * 3]
    one, two = RankContinuation(window_days=30, k=1), RankContinuation(window_days=30, k=2)
    for rule in (one, two):
        rule.fit(M.until(now), None, now)
    d1, d2 = (r.decide(M, now, M.index[-1] + bt.BAR) for r in (one, two))
    assert len(d1) and (d1["group"].to_numpy() == M.index.get_indexer(d1["t"])).all()               # k = 1: the group is the bar, as before
    per_t = d2.groupby("t").agg(n=("side", "size"), longs=("side", lambda s: (s > 0).sum()))
    assert (per_t["n"] == 4).all() and (per_t["longs"] == 2).all()
    per_g = d2.groupby("group").agg(n=("side", "size"), net=("side", "sum"), t=("t", "nunique"))
    assert (per_g["n"] == 2).all() and (per_g["net"] == 0).all() and (per_g["t"] == 1).all()        # each unit: one long, one short, same bar
    assert set(d1["t"]) == set(d2["t"])                                                             # the trigger (the gap between the extremes) is unchanged
    assert (d2["group"] // 2 == M.index.get_indexer(d2["t"])).all()
    acc = bt.accept(d2.assign(hold=48, fold="F1"), M.index)
    assert acc["accepted"].any() and (acc.groupby("group")["accepted"].nunique() == 1).all()        # a unit stands or falls together
    assert (d2.loc[d2["side"] > 0, "signal"] > d2.loc[d2["side"] < 0, "signal"].max() - 0).any()


def _day(rng, px0: float, tick: float, rel_range: float, volume: float, day: pd.Timestamp, sym: str) -> pd.DataFrame:
    t = pd.date_range(day, periods=288, freq="5min")
    px = np.round((px0 * np.exp(np.cumsum(rng.normal(0, 8.0, 288)) / 1e4)) / tick) * tick
    hi, lo = np.round(px * (1 + rel_range) / tick) * tick, np.round(px * (1 - rel_range) / tick) * tick
    return pd.DataFrame({"symbol": sym, "open_time": t, "high": hi, "low": lo, "close": px, "volume": volume / px})


def test_tick_is_read_off_the_candles():
    rng = np.random.default_rng(0)
    d = _day(rng, 100.0, 0.01, 0.002, 1e6, pd.Timestamp("2024-01-01", tz="UTC"), "X")
    assert abs(cost._tick(d) - 0.01 / d["close"].mean() * 1e4) < 1e-9


LAW = {"spread_cal_bps": (0.4, 0.3, -0.15, 0.9), "imp": (-6.0, 0.6, -0.4, 0.2)}       # (const, b_range, b_dollar_vol, b_tick)


def _law(f: pd.DataFrame, key: str) -> np.ndarray:
    c, br, bv, bt_ = LAW[key]
    return np.exp(c + br * np.log(f["range_bps"]) + bv * np.log(f["dollar_vol"]) + bt_ * np.log(f["tick_bps"]))


def test_wide_cost_proxy_recovers_a_known_law_and_prices_a_pair_without_a_tape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    rng = np.random.default_rng(1)
    days = pd.date_range("2023-06-01", periods=24, freq="D", tz="UTC")
    measured = [f"M{i}USDT" for i in range(12)]
    c5 = [_day(rng, 5.0 * (i + 1), [0.001, 0.01, 0.05][i % 3], 0.001 + 0.0004 * (i % 4), 2e7 * (i + 1), day, sym)
          for i, sym in enumerate(measured) for day in days]
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    new = [_day(rng, 3.0, 0.001, 0.0025, 1.2e7, day, "NEWUSDT") for day in days]              # thinner than every measured pair, tick like the finest
    pd.concat(new).to_parquet("data/candles_5m_archive.parquet", index=False)
    reg = cost.regimes(("candles_5m",))
    d = reg[["symbol", "day", "range_bps", "dollar_vol", "px"]].copy()
    d["spread_src"], d["spread_bps"] = "tape", np.nan
    d["spread_cal_bps"] = _law(reg, "spread_cal_bps")
    for n in NOTIONALS:
        d[f"imp_{n}"] = _law(reg, "imp") * np.sqrt(n / 10_000)
    for H in cost.HOLDS:
        d[f"maker_fill_{H}"], d[f"maker_adv_{H}"] = 0.9, -1.0
    d.to_parquet("data/cost_daily.parquet", index=False)
    text = cost.wide(["NEWUSDT"], pd.Timestamp("2023-06-01", tz="UTC"))
    assert "Leave-one-pair-out" in text and cost.OUT_WIDE_MD.exists()
    w = pd.read_parquet(cost.DAILY_WIDE)
    assert set(w["symbol"]) == {"NEWUSDT"} and len(w) == len(days) and (w["spread_src"] == "proxy_wide").all()
    truth = _law(w, "spread_cal_bps")
    assert np.allclose(w["spread_cal_bps"], np.maximum(truth, w["tick_bps"]), rtol=0.02)     # the law is recovered and extrapolated below every measured pair's volume
    assert np.allclose(w[f"imp_{10_000}"], _law(w, "imp"), rtol=0.02) and w[f"maker_fill_{15}"].isna().all()
    # the panel carries the archive-only pair from START on, and the cost loader prices it from the wide table
    end = pd.Timestamp("2023-06-24", tz="UTC")
    P = ceiling.panel([*measured[:2], "NEWUSDT"], end, ceiling.START)
    assert list(P["close"].columns) == [*measured[:2], "NEWUSDT"] and P["close"]["NEWUSDT"].notna().sum() > 288 * 20
    pd.DataFrame({"symbol": ["NEWUSDT"], "ts": [days[0]], "rate": [0.0], "interval_h": [8]}).to_parquet("data/funding_archive.parquet", index=False)
    C = bt.load_costs(P["close"].index, P["close"].columns, end)
    j = list(P["close"].columns).index("NEWUSDT")
    assert np.isfinite(C.taker_leg[:, j]).sum() >= 20 and np.isnan(C.maker_fill[:, j]).all()
    assert np.allclose(np.nanmedian(C.taker_leg[:, j]), (w["spread_cal_bps"] / 2 + w[f"imp_{10_000}"]).median(), rtol=0.05)
