"""P4 — the dumbest trade generator for the bet P2 funded (PLAN §4 P4, registration R1 in §8).

`reversal4h`: a pair's own move over the next 4 hours, by short-term reversal, traded only when the
pair is volatile. No model, no labels. At decision time t, per pair:

    signal  s = −½·(z_4h + z_1d),  z_w = the trailing w return / (σ_1w · √bars)     (P2's ret_4h, ret_1d)
    vol     v = the standard deviation of the last 4 hours of 5m returns
    trade   side = sign(s), one unit, held 48 bars — only if v ≥ the pair's q_vol quantile of v AND
            |s| ≥ its q_sig quantile of |s|, both quantiles taken over the `window_days` before the
            block (the harness refits them every block; nothing inside the block is used)

Three parameters: q_vol, q_sig, window_days. The lookbacks and the equal weights are P2's funded
features, not tuned. Everything else (one position per pair, latency, costs, fills) is the harness's.

P5's two spread-cutting variants of the same rule (registration R3; R1 is `size=unit`, no cap):
    size=invvol   the position is vol_cut / v units (≤ 1 by construction, floored at 0.25): the more
                  violent the pair, the smaller the bet, so that one wild day weighs less
    max_side=K    the harness takes at most K positions at once on one side: eleven longs opened into
                  one market-wide fall are one bet, not eleven

`rank4h` (registration R2): the pair-vs-basket bet as a rank rule, market-neutral by construction.
    x_j   = z_4h of pair j minus the mean z_4h of all pairs at t (needs ≥ MIN_PAIRS)
    trade long the pair with the lowest x, short the one with the highest, one unit each, as ONE
          unit of the book (both legs or neither) — only if the gap between them is at least its
          q_disp quantile over the `window_days` before the block

P5's two hypotheses, found on F1+F2 by taking R1 and R2 apart (registrations R4, R5):
`panic4h` (H1): buy the market after a market-wide fall. A pair is FALLING at t when R1 would buy it (same
    v, s and cuts). When at least `breadth` of the pairs that have cuts were falling at some bar of the
    last `memory` bars, go long EVERY such pair, one unit each, for 48 bars. Long only; the book rule
    (one position per pair) makes it one basket per 4 hours for as long as the panic lasts.
`trendfall4h` (R6's hypothesis, registration R8): H1 made conditional on the regime. The basket (equal weight, ≥ MIN_PAIRS)
    has fallen by at least `fall` of its own 4h sigmas (trailing 1-week volatility) AND its `trend_days` return is
    positive → long every pair, one unit each, 48 bars. No fit, no quantile: both numbers are `market.py`'s money view.
`rankcont4h` (H2): `rank4h` with the sides swapped — long the pair torn furthest above the others, short
    the one furthest below.
`bookimb1d` (R7's lead, registration R9): P2's `depth_imb_1` — (bid − ask notional within ±1 % of mid) / their sum,
    from the archive book's last 30 s sample before t — traded as it was screened. Its 1d IC is NEGATIVE (a bid-heavy
    book precedes a fall), so: side = −sign(imb), one unit, 288 bars, only when |imb| is in the pair's top decile
    (q_sig 0.90 — P2's cost bars were written for "trade the top decile") over the `window_days` before the block.
    No candle feature enters; the harness attaches the book through `needs`.
    `side=long` (registration R11): the ask-heavy book as its own question — long only, when −imb is at or above the
    pair's q_sig quantile of −imb (the top decile of ask-heaviness itself, not of |imb|), everything else unchanged.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import Market, Strategy, decisions_from
from .ceiling import MIN_PAIRS, W, basket

WARMUP = pd.Timedelta(days=9)            # σ_1w needs a week of bars, the 1d return a day more


class Reversal(Strategy):
    name = "reversal4h"

    def __init__(self, q_vol: float = 0.90, q_sig: float = 0.80, window_days: int = 120, hold: int = 48, size: str = "unit", max_side: int | None = None):
        assert size in ("unit", "invvol")
        self.q_vol, self.q_sig, self.window_days, self.hold, self.size = float(q_vol), float(q_sig), int(window_days), int(hold), size
        self.max_side = None if max_side is None else int(max_side)
        self._vol_cut = self._sig_cut = None

    @staticmethod
    def features(close: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        lr = np.log(close)
        r1 = lr.diff() * 1e4
        s1w = r1.rolling(W["1w"], min_periods=int(W["1w"] * 0.8)).std()
        z = lambda k: (lr - lr.shift(k)) * 1e4 / (s1w * np.sqrt(k))                               # noqa: E731
        return -(z(W["4h"]) + z(W["1d"])) / 2, r1.rolling(W["4h"], min_periods=int(W["4h"] * 0.8)).std()

    def fit(self, M: Market, y: pd.DataFrame, now: pd.Timestamp) -> None:
        a = now - pd.Timedelta(days=self.window_days)
        s, v = self.features(M.close.loc[a - WARMUP:])
        s, v = s.loc[a:].abs(), v.loc[a:]
        enough = lambda x: x.notna().sum() >= 0.5 * self.window_days * 288                        # noqa: E731
        self._sig_cut, self._vol_cut = s.quantile(self.q_sig).where(enough(s)), v.quantile(self.q_vol).where(enough(v))

    def decide(self, M: Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        s, v = self.features(M.close.loc[a - WARMUP:])
        on = (v >= self._vol_cut) & (s.abs() >= self._sig_cut)                                    # a NaN cut (young pair) compares False
        units = (self._vol_cut / v).clip(0.25, 1.0) if self.size == "invvol" else 1.0
        return decisions_from((np.sign(s) * units).where(on, 0.0), a, b, signal=s, why=f"reversal: vol≥q{self.q_vol:g}, |s|≥q{self.q_sig:g}")


class RankReversal(Strategy):
    name = "rank4h"

    def __init__(self, q_disp: float = 0.90, window_days: int = 120, hold: int = 48, k: int = 1):
        self.q_disp, self.window_days, self.hold, self.k = float(q_disp), int(window_days), int(hold), int(k)
        self._cut = np.nan

    @staticmethod
    def features(close: pd.DataFrame, min_pairs: int = MIN_PAIRS) -> pd.DataFrame:
        lr = np.log(close)
        s1w = (lr.diff() * 1e4).rolling(W["1w"], min_periods=int(W["1w"] * 0.8)).std()
        z = (lr - lr.shift(W["4h"])) * 1e4 / (s1w * np.sqrt(W["4h"]))
        return z.sub(z.mean(axis=1), axis=0).where(z.notna().sum(axis=1) >= min_pairs)

    @property
    def min_pairs(self) -> int:
        return max(MIN_PAIRS, 2 * self.k)          # k a side needs 2k names present; the basket needs MIN_PAIRS regardless

    def fit(self, M: Market, y: pd.DataFrame, now: pd.Timestamp) -> None:
        a = now - pd.Timedelta(days=self.window_days)
        x = self.features(M.close.loc[a - WARMUP:], self.min_pairs).loc[a:]
        gap = (x.max(axis=1) - x.min(axis=1)).dropna()
        self._cut = gap.quantile(self.q_disp) if len(gap) >= 0.5 * self.window_days * 288 else np.nan

    def decide(self, M: Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        """k = 1: long the lowest, short the highest, as one unit (both legs or neither). k > 1 (R10, the wider
        universe): the k lowest against the k highest; the i-th lowest and the i-th highest form one unit, so each
        unit is dollar-neutral and a pair already in a position blocks its own unit only."""
        x = self.features(M.close.loc[a - WARMUP:], self.min_pairs)
        on = (x.max(axis=1) - x.min(axis=1)) >= self._cut
        rl, rh = x.rank(axis=1, method="first"), x.rank(axis=1, method="first", ascending=False)
        lo, hi = rl <= self.k, rh <= self.k
        d = decisions_from((lo.astype(float) - hi.astype(float)).where(on, 0.0, axis=0), a, b, signal=-x, why=f"rank: gap≥q{self.q_disp:g}" + (f", {self.k} a side" if self.k > 1 else ""))
        slot = rl.where(lo, rh).to_numpy()[x.index.get_indexer(d["t"]), x.columns.get_indexer(d["symbol"])]      # 1 … k on both sides
        return d.assign(group=M.index.get_indexer(d["t"]) * self.k + slot.astype(int) - 1)


class RankContinuation(RankReversal):
    name = "rankcont4h"

    def decide(self, M: Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        d = super().decide(M, a, b)
        return d.assign(side=-d["side"], signal=-d["signal"], why=d["why"].str.replace("rank:", "rank continuation:"))


class Panic(Strategy):
    name = "panic4h"

    def __init__(self, breadth: float = 1 / 3, q_vol: float = 0.90, q_sig: float = 0.80, window_days: int = 120, hold: int = 48, memory: int = 48):
        self.breadth, self.q_vol, self.q_sig, self.window_days, self.hold, self.memory = float(breadth), float(q_vol), float(q_sig), int(window_days), int(hold), int(memory)
        self._r1 = Reversal(q_vol, q_sig, window_days, hold)

    def fit(self, M: Market, y: pd.DataFrame, now: pd.Timestamp) -> None:
        self._r1.fit(M, y, now)

    def decide(self, M: Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        s, v = Reversal.features(M.close.loc[a - WARMUP:])
        can = s.notna() & v.notna() & (self._r1._vol_cut.notna() & self._r1._sig_cut.notna())      # pairs that could fire at t
        falling = ((v >= self._r1._vol_cut) & (s >= self._r1._sig_cut)).astype(float)                # s > 0: the pair fell
        share = (falling.rolling(self.memory, min_periods=1).max() * can).sum(axis=1) / can.sum(axis=1).where(can.sum(axis=1) >= MIN_PAIRS)
        on = share >= self.breadth - 1e-12
        return decisions_from(can.astype(float).where(on, 0.0, axis=0), a, b, signal=pd.DataFrame({c: share for c in s.columns}),
                              why=f"panic: ≥{self.breadth:.2f} of the pairs fell within {self.memory} bars")


class TrendFall(Strategy):
    name = "trendfall4h"

    def __init__(self, fall: float = 2.0, trend_days: int = 30, hold: int = 48):
        self.fall, self.trend_days, self.hold = float(fall), int(trend_days), int(hold)

    def decide(self, M: Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        close = M.close.loc[a - WARMUP - pd.Timedelta(days=self.trend_days):]
        b1 = basket(np.log(close).diff() * 1e4)
        blr = b1.fillna(0.0).cumsum().where(b1.notna())
        k = W["4h"]
        m4 = (blr - blr.shift(k)) / (b1.rolling(W["1w"], min_periods=int(W["1w"] * 0.8)).std() * np.sqrt(k))
        on = (m4 <= -self.fall) & ((blr - blr.shift(self.trend_days * 288)) > 0)
        return decisions_from(close.notna().astype(float).where(on, 0.0, axis=0), a, b, signal=pd.DataFrame({c: -m4 for c in close.columns}),
                              why=f"basket fell ≥{self.fall:g}σ in 4h, {self.trend_days}d trend up")


class BookImbalance(Strategy):
    name = "bookimb1d"
    needs = ("depth_imb_1",)

    def __init__(self, q_sig: float = 0.90, window_days: int = 120, hold: int = 288, side: str = "both"):
        assert side in ("both", "long")
        self.q_sig, self.window_days, self.hold, self.side = float(q_sig), int(window_days), int(hold), side
        self._cut = None

    def _size(self, x: pd.DataFrame) -> pd.DataFrame:
        """What the cut is taken on and compared with: |imb| for both sides, −imb (ask-heaviness) for long only."""
        return x.abs() if self.side == "both" else -x

    def fit(self, M: Market, y: pd.DataFrame, now: pd.Timestamp) -> None:
        x = self._size(M.extra["depth_imb_1"].loc[now - pd.Timedelta(days=self.window_days):])
        self._cut = x.quantile(self.q_sig).where(x.notna().sum() >= 0.5 * self.window_days * 288)     # NaN: not enough book yet

    def decide(self, M: Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        x = M.extra["depth_imb_1"]
        on = (self._size(x) >= self._cut) & M.close.notna()                                         # a NaN cut compares False
        side = (-np.sign(x)) if self.side == "both" else pd.DataFrame(1.0, index=x.index, columns=x.columns)
        what = "±1% book imbalance in its top decile" if self.side == "both" else "ask-heavy ±1% book in its top decile of −imb"
        return decisions_from(side.where(on, 0.0), a, b, signal=-x, why=f"{what} (q{self.q_sig:g}), against it")


STRATEGIES = {BookImbalance.name: BookImbalance, TrendFall.name: TrendFall, Reversal.name: Reversal, RankReversal.name: RankReversal, RankContinuation.name: RankContinuation, Panic.name: Panic}
