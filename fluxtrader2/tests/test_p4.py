"""P4 unit tests: the reversal rule buys a fall and sells a rise, only in a volatile stretch, with
cuts taken strictly before the block; and it goes through the harness (causal check included)."""
import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2.rules import RankReversal, Reversal
from test_p3 import PAIRS, _synth


def _market(shock: float) -> bt.Market:
    rng = np.random.default_rng(3)
    idx = pd.date_range("2024-01-01", periods=60 * 288, freq="5min", tz="UTC")
    r = rng.normal(0, 5.0, (len(idx), 2))
    r[-300:] *= 4                                     # the last day is volatile in both pairs …
    r[-40:, 0] += shock / 40                          # … and pair A has just moved by `shock` bps over ~3 hours
    close = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0) / 1e4), index=idx, columns=["A", "B"])
    return bt.Market(close, close, close, close)


def test_the_rule_fades_the_move_and_only_with_cuts_from_before_the_block():
    for shock, side in ((-600.0, 1), (600.0, -1)):
        M = _market(shock)
        now = M.index[-288]
        rule = Reversal(window_days=30)
        rule.fit(M.until(now), None, now)
        cuts = (rule._vol_cut.copy(), rule._sig_cut.copy())
        d = rule.decide(M, now, M.index[-1] + bt.BAR)
        last = d[(d["symbol"] == "A") & (d["t"] == M.index[-1])]
        assert len(last) == 1 and last["side"].iloc[0] == side
        assert (d["t"] >= now).all() and cuts[0].equals(rule._vol_cut) and cuts[1].equals(rule._sig_cut)
        calm = Reversal(window_days=30)
        calm.fit(M.until(now), None, now)
        calm._vol_cut = calm._vol_cut * 100           # nothing is volatile enough → nothing is traded
        assert calm.decide(M, now, M.index[-1] + bt.BAR).empty


def test_a_young_pair_is_not_traded_until_half_a_window_exists():
    M = _market(-600.0)
    M.close.iloc[: 50 * 288, 1] = np.nan              # B lists 10 days before the block
    now = M.index[-288]
    rule = Reversal(window_days=30)
    rule.fit(M.until(now), None, now)
    assert np.isnan(rule._vol_cut["B"]) and not np.isnan(rule._vol_cut["A"])
    assert set(rule.decide(M, now, M.index[-1] + bt.BAR)["symbol"]) <= {"A"}


def test_through_the_harness(tmp_path):
    _synth(tmp_path)                                  # random walks plus a planted flag the rule knows nothing about
    r = bt.run(bt.get_strategy("reversal4h", {"window_days": 30, "hold": 12}), PAIRS, ["F1"], draws=5)
    x = r["results"].query("scope == 'all' and exec == 'taker'").iloc[0]
    assert 20 < x["trades"] < 0.05 * 36 * 288 * len(PAIRS) and x["net"] < 0
    assert r["meta"]["params"] == {"q_vol": 0.9, "q_sig": 0.8, "window_days": 30, "hold": 12, "size": "unit"}


def test_inverse_vol_size_and_the_side_cap(tmp_path):
    M = _market(-600.0)
    now = M.index[-288]
    rule = Reversal(window_days=30, size="invvol")
    rule.fit(M.until(now), None, now)
    d = rule.decide(M, now, M.index[-1] + bt.BAR)
    assert d["size"].between(0.25, 1.0).all() and d["size"].min() < 1.0
    idx = pd.date_range("2024-01-01", periods=100, freq="5min", tz="UTC")
    dec = pd.DataFrame({"t": idx[[10, 11, 12, 13, 30]], "symbol": list("ABCDE"), "side": [1, 1, 1, -1, 1], "size": 1.0, "hold": 12})
    out = bt.accept(dec, idx, max_side=2)
    assert list(out["accepted"]) == [True, True, False, True, True] and out["skip"].iloc[2] == "side_cap"      # by row 30 the first two longs are closed


def test_rank_rule_trades_both_legs_or_neither(tmp_path):
    rng = np.random.default_rng(5)
    idx = pd.date_range("2024-01-01", periods=60 * 288, freq="5min", tz="UTC")
    r = rng.normal(0, 5.0, (len(idx), 6))
    r[-40:, 0] -= 15                                  # A falls ~600 bps against the rest, F rises
    r[-40:, 5] += 15
    close = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0) / 1e4), index=idx, columns=list("ABCDEF"))
    M, now = bt.Market(close, close, close, close), idx[-288]
    rule = RankReversal(window_days=30)
    rule.fit(M.until(now), None, now)
    d = rule.decide(M, now, idx[-1] + bt.BAR)
    last = d[d["t"] == idx[-1]].set_index("symbol")["side"]
    assert dict(last) == {"A": 1, "F": -1} and (d.groupby("group")["side"].sum() == 0).all()
    acc = bt.accept(d.assign(hold=48), idx)
    assert (acc.groupby("group")["accepted"].nunique() == 1).all() and acc["accepted"].sum() % 2 == 0
    _synth(tmp_path)                                  # four pairs < MIN_PAIRS: no basket, so nothing is traded
    M4 = bt.market(PAIRS, pd.Timestamp("2023-06-01", tz="UTC"))
    assert bt.walk(RankReversal(window_days=30, hold=12), M4, ["F1"], bt.labels(M4, 12, 1)).empty
