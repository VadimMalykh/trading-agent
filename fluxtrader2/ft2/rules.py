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
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import Market, Strategy, decisions_from
from .ceiling import MIN_PAIRS, W

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

    def __init__(self, q_disp: float = 0.90, window_days: int = 120, hold: int = 48):
        self.q_disp, self.window_days, self.hold = float(q_disp), int(window_days), int(hold)
        self._cut = np.nan

    @staticmethod
    def features(close: pd.DataFrame) -> pd.DataFrame:
        lr = np.log(close)
        s1w = (lr.diff() * 1e4).rolling(W["1w"], min_periods=int(W["1w"] * 0.8)).std()
        z = (lr - lr.shift(W["4h"])) * 1e4 / (s1w * np.sqrt(W["4h"]))
        return z.sub(z.mean(axis=1), axis=0).where(z.notna().sum(axis=1) >= MIN_PAIRS)

    def fit(self, M: Market, y: pd.DataFrame, now: pd.Timestamp) -> None:
        a = now - pd.Timedelta(days=self.window_days)
        x = self.features(M.close.loc[a - WARMUP:]).loc[a:]
        gap = (x.max(axis=1) - x.min(axis=1)).dropna()
        self._cut = gap.quantile(self.q_disp) if len(gap) >= 0.5 * self.window_days * 288 else np.nan

    def decide(self, M: Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        x = self.features(M.close.loc[a - WARMUP:])
        on = (x.max(axis=1) - x.min(axis=1)) >= self._cut
        lo, hi = x.rank(axis=1, method="first") == 1, x.rank(axis=1, method="first", ascending=False) == 1
        d = decisions_from((lo.astype(float) - hi.astype(float)).where(on, 0.0, axis=0), a, b, signal=-x, why=f"rank: gap≥q{self.q_disp:g}")
        return d.assign(group=M.index.get_indexer(d["t"]))


STRATEGIES = {Reversal.name: Reversal, RankReversal.name: RankReversal}
