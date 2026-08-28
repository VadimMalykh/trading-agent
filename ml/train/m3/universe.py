"""T6 — the three offline tests that decide the traded universe (8 pairs vs 12).

WHY THIS MODULE EXISTS, and why it is not a scratch script. The T-wave (NEXT_TRAINING_PLAN
§1.10) spent 8h of GPU to kill a "+7.5 net bps/trade from 12 pairs" headline, and then a
first write-up over-reached and recorded 12 pairs as *rejected*. Both mistakes have the same
root: two point estimates were put side by side, with no interval on their difference and no
check that the criterion doing the deciding could decide anything. This file is the fix, in
code, so the next universe question is answered the same way:

  TEST 1 — TRADE-COUNT-MATCHED, not coverage-matched. `m3 universe` targets 2% coverage in
  each universe, so the 12-pair arm takes ~50% MORE trades rather than better ones. The
  hypothesis actually on trial is that a deeper cross-section lets the policy pick better
  trades, and that is tested by holding the trade budget fixed at the 8-pair number and
  letting each universe spend it on its own best candidates.

  TEST 2 — RE-TUNE THE CONCURRENCY CAP. The winner spec carries `max_concurrent=None`,
  chosen on 8 pairs. On 12 correlated pairs firing on one BTC-derived regime signal, max
  drawdown grew -2.83 -> -4.53. ⚠️ This is a SIZING re-tune on a fixed policy, at the cap
  values the M3-2 grid already contains — NOT a re-search of the 40-config grid on a new
  pair population, which M3_PROTOCOL §0 forbids. The wider cap ladder is printed as texture
  and is explicitly excluded from the decision.

  TEST 3 — THE DIFFERENCE, ITS INTERVAL, AND THE CRITERION'S POWER. Every comparison here
  reports the paired-by-exit-day CI on the DIFFERENCE, and every Tier-1 criterion used to
  decide reports its bootstrap failure rate on BOTH arms. §1.10's P5 "failure" was a coin
  flip: the incumbent 8-pair universe fails the same criterion 53.8% of the time.

PAIRING. Two universes scored on the same dumps trade on the same days, so their means are
not independent and a difference of two separately-clustered intervals is wrong. The
estimator below is the cluster-robust variance of the DIFFERENCE: each exit day contributes
its residual sum from arm A minus its residual sum from arm B, which is the standard CRVE
influence-function form and the exact generalisation of `metrics.clustered_mean_bps`.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from . import backtest, dumps, metrics, search

BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20260827          # fixed, so the table is reproducible to the digit


def with_fields(spec: backtest.PolicySpec, **kw) -> backtest.PolicySpec:
    """A copy of `spec` with some fields replaced — specs are compared by value, and
    mutating the shared winner spec in place is how a re-tune quietly becomes a re-search."""
    return replace(spec, **kw)

# ---------------------------------------------------------------------------------------
# The paired difference (TEST 3, first half)
# ---------------------------------------------------------------------------------------

def _net_and_day(trades: pd.DataFrame, cost_bps: float) -> tuple[np.ndarray, np.ndarray]:
    net = (trades["signed_ret"] - cost_bps / metrics.BPS * trades.get("size", 1.0))
    net = net.to_numpy(np.float64) * metrics.BPS
    day = pd.to_datetime(trades["exit_ts"], unit="ns", utc=True).dt.floor("D").to_numpy()
    return net, day


def paired_diff_bps(a: pd.DataFrame, b: pd.DataFrame, cost_bps: float = metrics.TAKER_COST_BPS,
                    z: float = 1.96) -> dict:
    """Mean net bps of `a` minus that of `b`, with a cluster-robust SE on the DIFFERENCE.

    Clusters are exit calendar days, the same key `metrics.clustered_mean_bps` uses, for the
    same two reasons: seeds gating one bar are three views of one market moment, and trades
    overlapping in time across correlated pairs are one bet expressed several ways. A day
    present in only one arm still contributes — it is a day on which the two policies
    genuinely differ, and dropping it would understate the variance of the difference.
    """
    if a.empty or b.empty:
        return {"diff_bps": 0.0, "se_bps": float("nan"), "lo95_bps": float("nan"),
                "hi95_bps": float("nan"), "clusters": 0, "shared_days": 0,
                "n_a": len(a), "n_b": len(b)}
    xa, da = _net_and_day(a, cost_bps)
    xb, db = _net_and_day(b, cost_bps)
    ma, mb = float(xa.mean()), float(xb.mean())
    sa = pd.Series(xa - ma).groupby(pd.Series(da)).sum()
    sb = pd.Series(xb - mb).groupby(pd.Series(db)).sum()
    # Align on the union of days; a day missing from one arm contributes 0 residual there.
    joined = pd.concat([sa.rename("a"), sb.rename("b")], axis=1).fillna(0.0)
    contrib = joined["a"].to_numpy() / xa.size - joined["b"].to_numpy() / xb.size
    g = contrib.size
    if g < 2:
        return {"diff_bps": ma - mb, "se_bps": float("nan"), "lo95_bps": float("nan"),
                "hi95_bps": float("nan"), "clusters": g,
                "shared_days": int(len(set(sa.index) & set(sb.index))),
                "n_a": len(a), "n_b": len(b)}
    se = float(np.sqrt((contrib ** 2).sum() * g / (g - 1.0)))
    return {"diff_bps": ma - mb, "se_bps": se, "lo95_bps": ma - mb - z * se,
            "hi95_bps": ma - mb + z * se, "clusters": int(g),
            "shared_days": int(len(set(sa.index) & set(sb.index))),
            "n_a": len(a), "n_b": len(b)}


def day_weighted_diff_bps(a: pd.DataFrame, b: pd.DataFrame,
                          cost_bps: float = metrics.TAKER_COST_BPS,
                          shared_only: bool = True, z: float = 1.96) -> dict:
    """The OTHER paired estimator — mean over days of (day mean of A - day mean of B).

    ⚠️ THIS IS NOT THE ESTIMATOR FOR A PER-TRADE CLAIM, and it is committed here only so
    the difference between the two is visible rather than a matter of whose script ran.

    It equally weights calendar days, so its estimand is "the average daily difference in
    net bps per trade", not "the difference in net bps per trade". Those coincide only when
    every day carries the same number of trades in both arms, which is exactly what a
    universe change breaks. With `shared_only` it also drops days on which only one
    universe traded — the days on which the two policies differ most.

    It is reconstructed because NEXT_TRAINING_PLAN §1.10's published interval (-0.85 bps,
    95% CI [-6.79, +5.09], 167 shared days) is this estimator with `shared_only=True`,
    while the table it sits beside reports trade-weighted means (+9.00 vs +9.29, i.e.
    -0.29). `paired_diff_bps` is the interval that belongs to that table.
    """
    if a.empty or b.empty:
        return {"diff_bps": 0.0, "se_bps": float("nan"), "lo95_bps": float("nan"),
                "hi95_bps": float("nan"), "days": 0}
    xa, da = _net_and_day(a, cost_bps)
    xb, db = _net_and_day(b, cost_bps)
    ma = pd.Series(xa).groupby(pd.Series(da)).mean()
    mb = pd.Series(xb).groupby(pd.Series(db)).mean()
    j = pd.concat([ma.rename("a"), mb.rename("b")], axis=1)
    j = j.dropna() if shared_only else j.fillna(0.0)
    d = (j["a"] - j["b"]).to_numpy(np.float64)
    if d.size < 2:
        return {"diff_bps": float(d.mean()) if d.size else 0.0, "se_bps": float("nan"),
                "lo95_bps": float("nan"), "hi95_bps": float("nan"), "days": int(d.size)}
    se = float(d.std(ddof=1) / np.sqrt(d.size))
    return {"diff_bps": float(d.mean()), "se_bps": se, "lo95_bps": float(d.mean()) - z * se,
            "hi95_bps": float(d.mean()) + z * se, "days": int(d.size)}


def bootstrap_diff_se(a: pd.DataFrame, b: pd.DataFrame,
                      cost_bps: float = metrics.TAKER_COST_BPS,
                      draws: int = BOOTSTRAP_DRAWS, seed: int = BOOTSTRAP_SEED) -> dict:
    """Day-bootstrap SE of the same difference, as a check on the analytic CRVE above.

    WHY BOTHER. The interval on the difference is the number T6 exists to produce, and
    §1.10's ad-hoc version of it (-0.85 bps, SE ~3.0) does not agree with the difference of
    its own published means (+9.00 - 9.29 = -0.29) — a sign it was a different estimator,
    computed once, checked against nothing. An analytic SE and a resampling SE are derived
    by completely different routes, so agreement between them is real evidence that the
    interval is right and disagreement is a bug caught before it reaches a decision.

    Days are drawn with replacement from the union of both arms' exit days and BOTH arms
    are recomputed on the same draw, which is what makes it the paired quantity.
    """
    if a.empty or b.empty:
        return {"se_bps": float("nan"), "draws": 0}
    xa, da = _net_and_day(a, cost_bps)
    xb, db = _net_and_day(b, cost_bps)
    days = np.array(sorted(set(da) | set(db)))
    ia = {d: np.flatnonzero(da == d) for d in days}
    ib = {d: np.flatnonzero(db == d) for d in days}
    rng = np.random.default_rng(seed)
    out = np.empty(draws)
    for k in range(draws):
        picked = days[rng.integers(0, days.size, days.size)]
        sa = np.concatenate([ia[d] for d in picked])
        sb = np.concatenate([ib[d] for d in picked])
        out[k] = (xa[sa].mean() if sa.size else np.nan) - (xb[sb].mean() if sb.size else np.nan)
    return {"se_bps": float(np.nanstd(out, ddof=1)), "draws": draws}


# ---------------------------------------------------------------------------------------
# The power of a Tier-1 criterion (TEST 3, second half)
# ---------------------------------------------------------------------------------------

class Arm:
    """One arm's trades, flattened into the arrays the bootstrap needs.

    Everything a Tier-1 check reads is precomputed once — net bps per trade, the seed it
    came from, its calendar window, and which exit day it belongs to — so a draw is a
    concatenation of index arrays and six bincounts, not a re-run of `scorecard`.
    """

    def __init__(self, trades: pd.DataFrame, seeds: list[str], cal_days: float,
                 cost_bps: float = metrics.TAKER_COST_BPS):
        self.n_seeds = len(seeds)
        self.cal_days = cal_days
        net, day = _net_and_day(trades, cost_bps)
        self.net = net
        w = dumps.add_window(trades, ts_col="entry_ts")["window"]
        names = list(search.WINDOW_NAMES)
        self.win = w.map({n: i for i, n in enumerate(names)}).fillna(-1).to_numpy(int)
        self.n_win = len(names)
        self.seed = trades["seed"].map({s: i for i, s in enumerate(seeds)}).to_numpy(int)
        self.day = day
        order = np.argsort(day, kind="mergesort")
        self._day_index = {d: idx for d, idx in
                           zip(*_split_by_day(day[order], order))}

    def days(self) -> list:
        return list(self._day_index)

    def sample(self, days) -> np.ndarray:
        parts = [self._day_index[d] for d in days if d in self._day_index]
        return np.concatenate(parts) if parts else np.empty(0, dtype=int)

    def tier1(self, idx: np.ndarray) -> dict:
        """The six M3_PROTOCOL §4.2 criteria over a subset of this arm's trades."""
        if idx.size == 0:
            return {k: False for k in ("P1", "P2", "P3", "P4", "P5", "P6")}
        net, win, seed = self.net[idx], self.win[idx], self.seed[idx]
        keep = win >= 0
        wsum = np.bincount(win[keep], weights=net[keep], minlength=self.n_win)
        wcnt = np.bincount(win[keep], minlength=self.n_win)
        wmean = np.divide(wsum, wcnt, out=np.full(self.n_win, np.nan), where=wcnt > 0)
        ssum = np.bincount(seed, weights=net, minlength=self.n_seeds)
        scnt = np.bincount(seed, minlength=self.n_seeds)
        smean = np.divide(ssum, scnt, out=np.full(self.n_seeds, np.nan), where=scnt > 0)
        return {
            "P1": bool(net.mean() > 0),
            "P2": int(np.nansum(wmean > 0)) >= search.MIN_WINDOWS_POSITIVE,
            "P3": bool(np.nanmin(wmean) >= search.WORST_WINDOW_FLOOR_BPS),
            "P4": int(wcnt.min()) >= search.MIN_TRADES_PER_WINDOW,
            # A seed with no trades in the draw cannot be "pooled-positive"; NaN counts as
            # a failure, which is the conservative reading and matches search.tier1's
            # "all(s['net_bps'] > 0)" over a seed whose summarise() returns 0.0.
            "P5": bool(np.all(np.nan_to_num(smean, nan=-1.0) > 0)),
            "P6": bool(idx.size / self.n_seeds / self.cal_days >= search.MIN_TRADES_PER_DAY),
        }


def _split_by_day(sorted_days: np.ndarray, order: np.ndarray):
    """(unique days, index arrays into the ORIGINAL trade order), for a day-sorted view."""
    uniq, starts = np.unique(sorted_days, return_index=True)
    parts = np.split(order, starts[1:])
    return uniq, parts


def criterion_power(arms: dict, draws: int = BOOTSTRAP_DRAWS,
                    seed: int = BOOTSTRAP_SEED) -> pd.DataFrame:
    """Bootstrap failure rate of every Tier-1 criterion, on every arm, on COMMON draws.

    Days are resampled with replacement from the union of both arms' exit days, and the
    SAME resampled day list is scored on every arm. Common random numbers matter here: the
    question is not "how noisy is each arm" but "does this criterion separate the arms",
    and independent draws would add noise that is not in the comparison.

    A criterion whose failure rate is near 50% on the INCUMBENT is not evidence about the
    challenger. That is the whole finding this table exists to make un-missable.
    """
    rng = np.random.default_rng(seed)
    all_days = sorted(set().union(*[set(a.days()) for a in arms.values()]))
    n_days = len(all_days)
    days_arr = np.array(all_days)
    checks = ("P1", "P2", "P3", "P4", "P5", "P6")
    fails = {name: {c: 0 for c in checks + ("PASS",)} for name in arms}
    for _ in range(draws):
        picked = days_arr[rng.integers(0, n_days, n_days)]
        for name, arm in arms.items():
            res = arm.tier1(arm.sample(picked))
            for c in checks:
                fails[name][c] += 0 if res[c] else 1
            fails[name]["PASS"] += 0 if all(res[c] for c in checks) else 1
    rows = []
    for name in arms:
        row = {"arm": name, "days_resampled": n_days}
        row.update({c: fails[name][c] / draws for c in checks + ("PASS",)})
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------
# Matching the trade budget (TEST 1)
# ---------------------------------------------------------------------------------------

def match_coverage(ds: list[dumps.Dump], spec: backtest.PolicySpec, regimes: dict,
                   target_trades: int, lo: float = 0.0005, hi: float = 0.05,
                   tol: float = 0.005, max_iter: int = 30) -> tuple[float, backtest.Result]:
    """Bisect coverage until this universe books `target_trades` pooled trades.

    Trade count is NOT a fixed multiple of coverage: the serial-per-pair invariant and the
    concurrency cap both drop selected bars, and they drop proportionally more of them as
    coverage rises. So the matching coverage is solved for rather than scaled to.

    Monotone in coverage (a larger slice can only be a superset of a smaller one before
    blocking, and blocking is monotone too), which is what makes bisection valid here.
    """
    best = None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        res = backtest.run(ds, with_fields(spec, coverage=mid), regimes)
        n = len(res.trades)
        if best is None or abs(n - target_trades) < abs(len(best[1].trades) - target_trades):
            best = (mid, res)
        if abs(n - target_trades) <= tol * target_trades:
            return mid, res
        if n < target_trades:
            lo = mid
        else:
            hi = mid
    return best
