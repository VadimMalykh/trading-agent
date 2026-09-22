"""P5 unit tests for the book-imbalance rule (registration R9): a bid-heavy book is shorted and an ask-heavy
one bought, only when the imbalance is in the pair's top decile with the cut taken before the block; the
harness attaches the book through `needs`, truncates it with the market (causal check), and a planted
book signal comes back through the harness at its planted size minus the cost."""
import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2.rules import BookImbalance
from test_p3 import EDGE, HOLD, PAIRS, TAKER_RT, _synth


def _market(imb_last: float) -> bt.Market:
    rng = np.random.default_rng(5)
    idx = pd.date_range("2024-01-01", periods=60 * 288, freq="5min", tz="UTC")
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 5.0, (len(idx), 2)), axis=0) / 1e4), index=idx, columns=["A", "B"])
    imb = pd.DataFrame(rng.uniform(-0.2, 0.2, (len(idx), 2)), index=idx, columns=["A", "B"])   # an ordinary book: |imb| ≤ 0.2
    imb.iloc[-1, 0] = imb_last                                                                    # … and A's last bar
    return bt.Market(close, close, close, close, {"depth_imb_1": imb})


def test_the_rule_trades_against_a_lopsided_book_with_a_cut_from_before_the_block():
    for imb, side in ((-0.9, 1), (0.9, -1)):        # ask-heavy → long; bid-heavy → short
        M = _market(imb)
        now = M.index[-288]
        rule = BookImbalance(window_days=30)
        rule.fit(M.until(now), None, now)
        cut = rule._cut.copy()
        d = rule.decide(M, now, M.index[-1] + bt.BAR)
        last = d[(d["symbol"] == "A") & (d["t"] == M.index[-1])]
        assert len(last) == 1 and last["side"].iloc[0] == side and last["signal"].iloc[0] == -imb
        assert (d["t"] >= now).all() and cut.equals(rule._cut)
        assert 0.15 < cut["A"] < 0.2 and 0.15 < cut["B"] < 0.2  # the top decile of a uniform(−0.2, 0.2) by size
    calm = _market(0.05)                                        # inside the ordinary range: not traded
    now = calm.index[-288]
    rule = BookImbalance(window_days=30)
    rule.fit(calm.until(now), None, now)
    d = rule.decide(calm, now, calm.index[-1] + bt.BAR)
    assert d[(d["symbol"] == "A") & (d["t"] == calm.index[-1])].empty


def test_no_book_means_no_cut_and_no_trade():
    M = _market(-0.9)
    M.extra["depth_imb_1"].iloc[: 55 * 288, 0] = np.nan          # A's book exists for 5 of the 30 window days
    now = M.index[-288]
    rule = BookImbalance(window_days=30)
    rule.fit(M.until(now), None, now)
    assert np.isnan(rule._cut["A"]) and not np.isnan(rule._cut["B"])
    assert set(rule.decide(M, now, M.index[-1] + bt.BAR)["symbol"]) <= {"B"}


def test_until_truncates_the_extra_frames_with_the_market():
    M = _market(0.0)
    cut = M.until(M.index[100])
    assert len(cut.extra["depth_imb_1"]) == 100 and cut.extra["depth_imb_1"].index.equals(cut.close.index)


def _plant_book(tmp_path, seed=1, days=80, start="2023-03-20"):
    """The synthetic volume flag of test_p3 (20 = up, 5 = down) written into the book: an up-flag bar gets an
    ask-heavy book (imb −0.9), a down-flag bar a bid-heavy one (+0.9), stamped one minute before the bar closes
    so that the rule sees it at t — so a trade on the book earns EDGE gross in expectation, as the volume rule does."""
    c = pd.read_parquet(tmp_path / "data" / "candles_5m.parquet")
    (tmp_path / "data" / "depth").mkdir()
    rng = np.random.default_rng(seed + 100)
    for sym, g in c.groupby("symbol"):
        t = g["open_time"] + pd.Timedelta("4min")
        imb = np.where(g["volume"] > 15, -0.9, np.where(g["volume"] < 7.5, 0.9, rng.uniform(-0.2, 0.2, len(g))))
        tot = 2e6
        pd.DataFrame({"symbol": sym, "ts": t.to_numpy(), "usd_m1": tot * (1 + imb) / 2, "usd_p1": tot * (1 - imb) / 2,
                      "usd_m5": tot * 3, "usd_p5": tot * 3}).to_parquet(tmp_path / "data" / "depth" / f"{sym}.parquet", index=False)


def test_through_the_harness_the_planted_book_edge_comes_back(tmp_path):
    _synth(tmp_path)
    _plant_book(tmp_path)
    r = bt.run(bt.get_strategy("bookimb1d", {"window_days": 30, "hold": HOLD}), PAIRS, ["F1"], draws=5)
    assert r["meta"]["params"] == {"q_sig": 0.9, "window_days": 30, "hold": HOLD}
    dec = r["decisions"]
    assert (dec["side"] == np.where(dec["signal"] > 0, 1, -1)).all()
    # the flag is on 3 % of bars and the rule takes the top decile by size, so ~7 in 10 trades are ordinary books
    # inside (0.14, 0.2): those earn minus the cost, the flagged ones EDGE minus the cost
    f = r["fills"]["taker"].dropna(subset=["net_bps"]).merge(dec[["signal"]], left_on="id", right_index=True)
    planted, noise = f[f["signal"].abs() > 0.5], f[f["signal"].abs() < 0.5]
    assert len(planted) > 100 and len(noise) > 2 * len(planted)
    for part, want in ((planted, EDGE - TAKER_RT), (noise, -TAKER_RT)):
        m, se = part["net_bps"].mean(), part["net_bps"].std() / np.sqrt(len(part))
        assert abs(m - want) < 3 * se + 1.0, (m, want, se)


def test_long_only_takes_the_cut_on_ask_heaviness_and_never_shorts():
    """R11: the cut is the q_sig quantile of −imb itself; a bid-heavy book is never traded, an ask-heavy one in the
    top decile of ask-heaviness is bought — even when it is milder than the pooled |imb| cut of R9 would demand."""
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-01", periods=60 * 288, freq="5min", tz="UTC")
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 5.0, (len(idx), 2)), axis=0) / 1e4), index=idx, columns=["A", "B"])
    imb = pd.DataFrame(rng.uniform(-0.1, 0.5, (len(idx), 2)), index=idx, columns=["A", "B"])   # a skewed, bid-heavy book (R9's 79 % shorts)
    imb.iloc[-1, 0], imb.iloc[-1, 1] = -0.095, 0.49                                             # A mildly ask-heavy, B very bid-heavy
    M = bt.Market(close, close, close, close, {"depth_imb_1": imb})
    now = M.index[-288]
    both, long_ = BookImbalance(window_days=30), BookImbalance(window_days=30, side="long")
    for rule in (both, long_):
        rule.fit(M.until(now), None, now)
    assert 0.04 < long_._cut["A"] < 0.05 and 0.4 < both._cut["A"] < 0.5           # top decile of −imb ~ (0.04, 0.1); of |imb| ~ (0.44, 0.5)
    d = long_.decide(M, now, M.index[-1] + bt.BAR)
    last = d[d["t"] == M.index[-1]]
    assert (d["side"] == 1).all() and list(last["symbol"]) == ["A"] and last["signal"].iloc[0] == 0.095
    assert both.decide(M, now, M.index[-1] + bt.BAR).query("t == @M.index[-1]")["symbol"].tolist() == ["B"]   # R9 would short B and not buy A
    assert long_.params()["side"] == "long"
