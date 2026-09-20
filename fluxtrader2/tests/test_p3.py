"""P3 unit tests on synthetic data: a planted edge of known size must come back through the harness
with the right number and an interval that covers it; a coin must come back at minus the cost; the
ledger re-prices without re-deciding; a rule that reads its future, a fit that sees a label from its
block, and an unregistered or repeated confirmation read are all refused."""
import os

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt

PAIRS = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"]
HOLD, EDGE, SD = 12, 30.0, 5.0                     # bars; planted gross bps per trade; noise bps per 5m bar
TAKER_RT = 2 * 5.0 + 1.0 + 2 * 0.5                 # fees + spread + impact, as written into cost_daily below
MAKER_RT = 2 * (0.9 * (2.0 + 1.5) + 0.1 * (5.0 + 0.5 + 0.5))


def _synth(tmp_path, start="2023-03-20", days=80, rate=0.0, seed=1):
    """Random-walk pairs. Volume carries a public signal (20 = up, 5 = down, else ~10): after it the
    price drifts EDGE bps over the HOLD bars that follow the execution bar — so a trade on the signal
    earns exactly EDGE gross in expectation at latency 1."""
    os.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 288, freq="5min")
    c5, fund, cost = [], [], []
    for i, sym in enumerate(PAIRS):
        sig = rng.choice([-1.0, 0.0, 1.0], len(t5), p=[0.015, 0.97, 0.015])
        drift = np.zeros(len(t5))
        for k in range(2, HOLD + 2):               # bar t+1 closes at the entry price; bars t+2 … t+1+HOLD carry the move
            drift[k:] += sig[:-k] * EDGE / HOLD
        px = 100 * (i + 1) * np.exp(np.cumsum(rng.normal(0, SD, len(t5)) + drift) / 1e4)
        vol = np.where(sig > 0, 20.0, np.where(sig < 0, 5.0, rng.uniform(9, 11, len(t5))))
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - pd.Timedelta("5min"), "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": vol}))
        ft = pd.date_range(t5[0], periods=days * 3, freq="8h")
        fund.append(pd.DataFrame({"symbol": sym, "ts": ft, "rate": rate, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=days + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5,
                                  f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


class Planted(bt.Strategy):
    name = "planted"

    def __init__(self, hold=HOLD):
        self.hold = hold

    def side(self, M):
        v = M.dv / M.close
        return (v > 15).astype(float) - (v < 7.5).astype(float)

    def decide(self, M, a, b):
        return bt.decisions_from(self.side(M), a, b, why="volume flag")


class Peeking(Planted):
    name = "peeking"

    def side(self, M):
        on_the_hour = np.repeat(np.asarray(M.index.minute == 0)[:, None], M.close.shape[1], 1)
        return np.sign(M.close.shift(-3) - M.close).where(on_the_hour, 0.0)


class Fitted(Planted):
    """Learns the sign of the flag from labels; records what `fit` was shown."""
    name, uses_labels = "fitted", True

    def __init__(self, hold=HOLD):
        super().__init__(hold)
        self._seen, self._coef = [], 1.0

    def fit(self, M, y, now):
        self._seen.append((now, M.index.max(), y.index.max()))
        s = self.side(M).reindex(y.index)
        self._coef = float(np.sign(np.nansum((s * y).to_numpy())) or 1.0)

    def decide(self, M, a, b):
        return bt.decisions_from(self.side(M) * self._coef, a, b, why="fitted flag")


def test_trade_stats_interval_covers_a_known_mean():
    rng = np.random.default_rng(0)
    days = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")
    cover = []
    for _ in range(300):
        n = rng.poisson(8, len(days))
        day = np.repeat(days, n)
        x = 2.0 + np.repeat(rng.normal(0, 6, len(days)), n) + rng.normal(0, 20, n.sum())        # a shared day effect: trades within a day are not independent
        r = bt.trade_stats(x, np.ones(len(x)), pd.DatetimeIndex(day), days, 2)
        cover.append(r["lo"] <= 2.0 <= r["hi"])
    assert 0.90 <= np.mean(cover) <= 0.99


def test_planted_edge_is_recovered_and_a_coin_pays_the_cost(tmp_path):
    _synth(tmp_path)
    r = bt.run(Planted(), PAIRS, ["F1"], draws=40)
    res = r["results"].query("scope == 'all'").set_index("exec")
    assert EDGE - TAKER_RT < res.loc["maker", "net"] < EDGE - 2 * 2.0 and 0.5 < res.loc["maker", "p_fill"] < 1      # between all-taker and all-maker
    for e, rt in (("taker", TAKER_RT), ("maker_ev", MAKER_RT)):
        x = res.loc[e]
        assert x["trades"] > 500 and abs(x["gross"] - EDGE) < 3 * x["net_se"]
        assert abs(x["net"] - (EDGE - rt)) < 3 * x["net_se"] and x["net_lo"] > 0
        assert 0.3 < x["net_se"] < 1.5                                                           # ≈ SD·√HOLD / √trades
        assert abs(x["fee"] + x["other_cost"] - rt) < 1e-9
    fl = r["floor"].set_index("exec")
    assert (fl["p"] <= 0.05).all() and abs(fl.loc["taker", "null_mean"] + TAKER_RT) < 3        # the null centres on minus the cost
    assert (fl["flip_p"] <= 0.05).all() and abs(fl.loc["taker", "flip_null_mean"] + TAKER_RT) < 3  # … and so does the day-flip null
    assert abs(res.loc["taker", "hedged"] - EDGE) < 3            # independent walks: hedging with the other pairs costs nothing
    sides = r["results"].query("exec == 'taker' and scope in ['long', 'short']")
    assert sides["trades"].sum() == res.loc["taker", "trades"] and (sides["gross"] > EDGE / 2).all()
    assert (r["dir"] / "report.md").exists() and "profitable outside the noise" in (r["dir"] / "report.md").read_text()

    c = bt.run(bt.Coin(hold=HOLD), PAIRS, ["F1"], draws=40)
    x = c["results"].query("scope == 'all' and exec == 'taker'").iloc[0]
    assert abs(x["net"] + TAKER_RT) < 3 * x["net_se"] and x["net_hi"] < 0 and abs(x["hit"] - 0.5) < 0.05
    assert c["floor"].set_index("exec").loc["taker", ["p", "flip_p"]].min() > 0.05

    # the ledger: the same decisions re-priced — fee, execution and latency change fills, never decisions
    M, dec = bt.market(PAIRS, r["decisions"]["t"].max() + pd.Timedelta("2D")), r["decisions"]
    C = bt.load_costs(M.index, M.columns, M.index[-1] + bt.BAR)
    a, b = bt.price(dec, M, C, "taker", 5.0, 2.0), bt.price(dec, M, C, "taker", 4.0, 2.0)
    assert np.allclose((b["net_bps"] - a["net_bps"]).dropna(), 2.0) and (a["id"] == b["id"]).all()
    assert a["net_bps"].isna().sum() <= len(PAIRS)                                               # only a trade whose exit lies past the data is left unpriced
    l0 = bt.price(dec, M, C, "taker", 5.0, 2.0, latency=0)
    assert l0["gross_bps"].mean() < a["gross_bps"].mean() - 1                                    # executed a bar early, the position is closed one bar before the drift ends
    assert not dec["accepted"].all() and (dec.loc[~dec["accepted"], "skip"] == "position_open").all()


def test_a_rule_that_reads_its_future_is_refused(tmp_path):
    _synth(tmp_path, days=60)
    with pytest.raises(AssertionError, match="reads its future"):
        bt.run(Peeking(), PAIRS, ["F1"], draws=0)


def test_fit_never_sees_a_label_from_its_block_and_the_null_refits(tmp_path):
    _synth(tmp_path, days=70)
    s = Fitted()
    r = bt.run(s, PAIRS, ["F1"], draws=3, refit_days=10)
    assert len(s._seen) >= 4 * 2                                                                  # blocks × (1 real + 3 shuffled walks)
    for now, m_last, y_last in s._seen:
        assert m_last < now and y_last + (bt.LATENCY + HOLD) * bt.BAR < now
    assert r["results"].query("scope == 'all' and exec == 'taker'")["gross"].iloc[0] > 20
    assert r["null"]["net"].notna().all()


def test_accept_one_position_per_pair():
    idx = pd.date_range("2024-01-01", periods=100, freq="5min", tz="UTC")
    dec = pd.DataFrame({"t": idx[[10, 15, 22, 12]], "symbol": ["A", "A", "A", "B"], "side": 1, "hold": 12}).sort_values("t")
    out = bt.accept(dec, idx).set_index(["symbol", "t"])["accepted"]
    assert out["A", idx[10]] and not out["A", idx[15]] and out["A", idx[22]] and out["B", idx[12]]


def test_funding_is_signed_and_only_while_open():
    idx = pd.date_range("2024-01-01", periods=100, freq="5min", tz="UTC")
    flat = pd.DataFrame(100.0, index=idx, columns=["A"])
    M = bt.Market(flat, flat, flat, flat)
    z = np.zeros((1, 1))
    C = bt.Costs(pd.DatetimeIndex([idx[0].floor("D")]), z, z, z + 1.0, np.where(np.arange(100) >= 50, 1.0, 0.0)[:, None])    # +1 bps paid by longs at row 50
    dec = pd.DataFrame({"t": idx[[40, 40, 60]], "symbol": "A", "side": [1, -1, 1], "size": 1.0, "hold": 20, "fold": "F1", "accepted": True})
    f = bt.price(dec, M, C, "taker", 0.0, 0.0)
    assert list(f["net_bps"].round(9)) == [-1.0, 1.0, 0.0]


def test_maker_fills_only_when_traded_through():
    idx = pd.date_range("2024-01-01", periods=60, freq="5min", tz="UTC")
    close = pd.DataFrame({"A": 100.0, "B": 100.0}, index=idx)
    close.iloc[11:, 1] = 101.0                       # B runs away right after the order is placed at row 10 …
    close.iloc[31:, 1] = 102.0                       # … and again after the exit order at row 30
    low, high = close.copy(), close.copy()
    low.iloc[11, 0] = 99.9                           # A dips through the resting bid (entry filled) …
    high.iloc[32, 0] = 100.1                         # … and later trades through the resting offer (exit filled)
    M = bt.Market(close, high, low, close)
    one = np.ones((1, 2))
    C = bt.Costs(pd.DatetimeIndex([idx[0].floor("D")]), one * 1.5, one * 0, one, np.zeros((60, 2)))
    dec = pd.DataFrame({"t": idx[[10, 10]], "symbol": ["A", "B"], "side": 1, "size": 1.0, "hold": 20, "fold": "F1", "accepted": True})
    f = bt.price(dec, M, C, "maker", 5.0, 2.0, latency=0).set_index("symbol")
    assert f.loc["A", "p_fill"] == 1 and f.loc["A", "fee_bps"] == 4.0 and f.loc["A", "other_cost_bps"] == 0 and abs(f.loc["A", "gross_bps"]) < 1e-9
    b = f.loc["B"]                                   # bought at 101 after the wait; the offer at 101 (row 30) is traded through by the move to 102
    assert b["entry_px"] == 101.0 and b["exit_px"] == 101.0 and b["p_fill"] == 0.5 and b["fee_bps"] == 7.0 and b["other_cost_bps"] == 1.5
    assert abs(b["net_bps"] + 8.5) < 1e-9            # the run-up it missed is not in gross: that is the adverse selection


def test_confirmation_folds_need_a_registration_and_are_read_once(tmp_path):
    _synth(tmp_path, start="2024-08-05", days=55)
    with pytest.raises(SystemExit, match="confirmation folds"):
        bt.run(Planted(), PAIRS, ["F3"], draws=0)
    with pytest.raises(SystemExit, match="write the registration"):
        bt.run(Planted(), PAIRS, ["F3"], draws=0, registration="R1")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/PLAN.md").write_text("## 8\n\n### R1 — planted (registered 2026-09-21, read —)\n")
    r = bt.run(Planted(), PAIRS, ["F3"], draws=2, registration="R1")
    assert r["results"].query("scope == 'all' and exec == 'taker'")["trades"].iloc[0] > 100
    assert list(pd.read_csv(bt.READS)["fold"]) == ["F3"]
    with pytest.raises(SystemExit, match="already read"):
        bt.run(Planted(), PAIRS, ["F3"], draws=0, registration="R1")


def test_flip_null_keeps_the_timing_and_flips_whole_days():
    idx = pd.date_range("2024-01-01", periods=3 * 288, freq="5min", tz="UTC")
    dec = pd.DataFrame({"t": idx[[5, 9, 300, 310, 700]], "symbol": list("ABABA"), "side": [1, -1, 1, 1, -1], "size": 1.0})
    seen = set()
    for k in range(40):
        f = bt.flip_days(dec, np.random.default_rng(k))
        g = (f["side"] * dec["side"]).to_numpy()
        assert f.drop(columns="side").equals(dec.drop(columns="side")) and g[0] == g[1] and g[2] == g[3]
        seen.add(tuple(g[[0, 2, 4]]))
    assert len(seen) == 8                                          # every combination of day signs turns up


def test_hedged_gross_removes_a_move_every_pair_shares():
    idx = pd.date_range("2024-01-01", periods=60, freq="5min", tz="UTC")
    close = pd.DataFrame(100.0, index=idx, columns=list("ABC"))
    close.iloc[20:] *= 1.01                          # the whole market gaps up 1 % while the position is open …
    close.iloc[25:, 0] *= 1.002                      # … and A adds 20 bps of its own
    M = bt.Market(close, close, close, close)
    z = np.zeros((1, 3))
    C = bt.Costs(pd.DatetimeIndex([idx[0].floor("D")]), z, z, z + 1.0, np.zeros((60, 3)))
    dec = pd.DataFrame({"t": idx[[10]], "symbol": "A", "side": 1, "size": 1.0, "hold": 20, "fold": "F1", "accepted": True})
    f = bt.price(dec, M, C, "taker", 0.0, 0.0).iloc[0]
    assert abs(f["gross_bps"] - (np.log(1.01) + np.log(1.002)) * 1e4) < 1e-6 and abs(f["hedged_bps"] - np.log(1.002) * 1e4) < 1e-6
