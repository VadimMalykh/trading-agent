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
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import Market, Strategy, decisions_from
from .ceiling import W

WARMUP = pd.Timedelta(days=9)            # σ_1w needs a week of bars, the 1d return a day more


class Reversal(Strategy):
    name = "reversal4h"

    def __init__(self, q_vol: float = 0.90, q_sig: float = 0.80, window_days: int = 120, hold: int = 48):
        self.q_vol, self.q_sig, self.window_days, self.hold = float(q_vol), float(q_sig), int(window_days), int(hold)
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
        return decisions_from(np.sign(s).where(on, 0.0), a, b, signal=s, why=f"reversal: vol≥q{self.q_vol:g}, |s|≥q{self.q_sig:g}")


STRATEGIES = {Reversal.name: Reversal}
