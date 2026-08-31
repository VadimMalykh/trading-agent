"""Fidelity replay: score the policy the VM actually serves, not the one backtest.py scored.

## Why this module exists

`backtest.py` derives two quantities **once per seed, over the seed's whole evaluation
split**:

  * the coverage cut — `coverage_threshold(conf, c)`, the c-th quantile of every bar in
    the split; and
  * the regime sizing ladder — `r[regime_col].quantile([.2,.4,.6,.8])`, again over every
    bar in the split.

Neither is available to a live trader, so `apps/fluxtrader` computes both over a **trailing
window** instead: `Ledger.coverage_threshold/3` ranks over the last 14 days of recorded bars
(`Ledger.@rank_window_days`), and `Regime` takes its quintile edges over the last 30 days of
BTC 5m klines (`Regime.@history_days`). Both substitutions are deliberate and both are
documented at the point they are made. What was never measured is **what they cost**, and
the substitution is not innocent: a trailing rank admits c% of bars in *every* window by
construction, including a window the fixed cut would have sat out entirely.

That is not a smaller version of the same rule. It is a different rule, and the live
evidence says the difference is large: on 2026-08-31 the served cut stood at 0.5560 while
the three seeds' fixed cuts are 0.6091 / 0.6319 / 0.6153, and all twelve trades the forward
test had taken sat between 0.5565 and 0.5616 — every one of them below every fixed cut.

## What it reports

The 2x2, so the two substitutions can be blamed separately:

    A  fixed cut   + fixed ladder    <- the validated policy; must equal backtest.run()
    B  rolling cut + fixed ladder
    C  fixed cut   + rolling ladder
    D  rolling cut + rolling ladder  <- what fluxtrader-1 is serving

## What it is NOT

🔴 **This is a fidelity check, not a search.** It re-picks no knob: coverage stays at the
0.02 M3-2 selected and the ladder stays the 1/3..5/3 it selected. M3_PROTOCOL §0 forbids
re-choosing a searched dimension after seeing results; it does not forbid asking whether the
served code computes the dimension the way the scoring code did. Arm D is not a candidate
policy to adopt — it is the incumbent, finally measured.

## Faithfulness

`ACCEPTANCE` (run by `validate_fidelity()`) asserts that with an unbounded window and no
cold-start floor this module reproduces `backtest.run()`'s ledger **row for row**. That is
what licenses reading any A-vs-D gap as the windowing and nothing else — a hand-rolled
re-implementation that merely lands near the baseline would not.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import backtest, dumps, metrics
from .dumps import NS

# ---------------------------------------------------------------------------------------
# The live constants, read off the Elixir. Restated here rather than imported because there
# is no import across the two runtimes; `test/fluxtrader/trading/config_test.exs` is where
# the app asserts its own copies, and a change on either side has to be made on both.
# ---------------------------------------------------------------------------------------
RANK_WINDOW_DAYS = 14          # Ledger.@rank_window_days
MIN_RANK_BARS = 7 * 288        # Ledger.@min_rank_bars — a BAR COUNT pooled across pairs
REGIME_WINDOW_DAYS = 30        # Regime.@history_days
REGIME_MIN_BARS = 8 * 288      # Regime.@min_samples + @bars_per_day (health: min_bars 2304)

DAY_NS = 86_400 * NS


def _round_half_up(x: float) -> int:
    """Elixir's `round/1` rounds half AWAY FROM ZERO; Python's rounds half to even.

    k is `round(n * coverage)` on both sides and n is ~30k, so the two disagree only when
    n*c lands exactly on .5 — but the whole point of this module is that the two sides
    agree, so the difference is removed rather than argued about.
    """
    return int(np.floor(x + 0.5))


# The sentinel that collapses a trailing window onto `backtest.py`'s population. It is NOT
# "a very long window": an unbounded *trailing* window is still expanding, so at bar t it
# ranks the bars up to t and not the split. Only the whole split — future bars included —
# reproduces the fixed cut, and that lookahead is exactly what the live code cannot have.
FULL = "full"


def _window_bounds(ts: np.ndarray, grid: np.ndarray,
                   window_days: float | str) -> tuple[np.ndarray, np.ndarray]:
    """(start, end) index of each bar's lookback window into a ts-sorted array."""
    if window_days == FULL:
        return (np.zeros(grid.size, dtype=np.int64),
                np.full(grid.size, ts.size, dtype=np.int64))
    return (np.searchsorted(ts, grid - int(window_days * DAY_NS), side="left"),
            np.searchsorted(ts, grid, side="right"))


def _quantiles_linear(x: np.ndarray, qs: np.ndarray) -> np.ndarray:
    """`np.quantile(x, qs)` without the full sort — O(n) per call instead of O(n log n).

    Matches numpy's default `linear` method, which is also what `Policy.quintile_edges/1`
    does in Elixir, so the ladder edges agree across the two runtimes.
    """
    n = x.size
    pos = (n - 1) * qs
    lo = np.floor(pos).astype(np.int64)
    hi = np.minimum(lo + 1, n - 1)
    part = np.partition(x, np.unique(np.concatenate([lo, hi])))
    return part[lo] * (1.0 - (pos - lo)) + part[hi] * (pos - lo)


def rolling_coverage_threshold(ts: np.ndarray, conf: np.ndarray, coverage: float,
                               window_days: float | str = RANK_WINDOW_DAYS,
                               min_bars: int = MIN_RANK_BARS) -> tuple[np.ndarray, np.ndarray]:
    """The live cut, per bar timestamp. Mirrors `Ledger.coverage_threshold/3`.

    The window is `[t - window_days, t]` over every served pair's bars pooled, exactly as
    the SQL is: `where bar_ts >= ^since` with no upper bound, evaluated on a tick that has
    already recorded the current bar. Returns `(distinct_ts, threshold)` with NaN wherever
    the window is too thin to rank — the live `{:error, :cold, n}`, which is a refusal to
    trade rather than a threshold of zero.

    `ts` must be sorted ascending; `conf` is aligned to it.
    """
    grid = np.unique(ts)
    out = np.full(grid.size, np.nan)
    los, his = _window_bounds(ts, grid, window_days)
    prev = None
    for i in range(grid.size):
        lo, hi = los[i], his[i]
        n = hi - lo
        if n < min_bars:
            continue
        if prev == (lo, hi):                 # the FULL case: one window, computed once
            out[i] = out[i - 1]
            continue
        prev = (lo, hi)
        k = _round_half_up(n * coverage)
        if k <= 0:
            continue
        # k-th largest == the (n-k)-th smallest, 0-indexed; selection stays `conf >= thr`,
        # which is tie-inclusive on both sides.
        out[i] = np.partition(conf[lo:hi], n - k)[n - k]
    return grid, out


def rolling_quintile_edges(ts: np.ndarray, value: np.ndarray,
                           window_days: float | str = REGIME_WINDOW_DAYS,
                           min_bars: int = REGIME_MIN_BARS) -> tuple[np.ndarray, np.ndarray]:
    """The live sizing ladder's edges, per bar timestamp. Mirrors `Regime.refresh/2`.

    `Policy.quintile_edges/1` interpolates linearly between order statistics, which is
    numpy's default method, so the two agree without a method argument. Rows are the
    distinct ts; columns are the four edges. NaN while the window is short — live's
    `ready: false`, under which the policy sizes flat rather than sizing off four points.

    The observable is market-wide (one BTC value broadcast to every pair), so this is fed
    the DEDUPLICATED (ts, value) series: live reads BTC klines directly and never sees the
    value once per pair.
    """
    grid = np.unique(ts)
    out = np.full((grid.size, 4), np.nan)
    los, his = _window_bounds(ts, grid, window_days)
    qs = np.array([0.2, 0.4, 0.6, 0.8])
    prev = None
    for i in range(grid.size):
        lo, hi = los[i], his[i]
        if hi - lo < min_bars:
            continue
        if prev == (lo, hi):                 # the FULL case: one window, computed once
            out[i] = out[i - 1]
            continue
        out[i] = _quantiles_linear(value[lo:hi], qs)
        prev = (lo, hi)
    return grid, out


# The four arms reuse the same two rolling passes, so they are computed once per seed and
# memoised. Keyed on the seed label plus every parameter that changes the answer, so the
# acceptance run (FULL windows) can never be served a 14-day window's cached result.
_CACHE: dict = {}


def clear_cache() -> None:
    _CACHE.clear()


@dataclass(frozen=True)
class Arm:
    label: str
    cut: str        # "fixed" | "rolling"
    ladder: str     # "fixed" | "rolling"


ARMS = [
    Arm("A  fixed cut  + fixed ladder   (validated)", "fixed", "fixed"),
    Arm("B  ROLLING cut + fixed ladder", "rolling", "fixed"),
    Arm("C  fixed cut  + ROLLING ladder", "fixed", "rolling"),
    Arm("D  ROLLING cut + ROLLING ladder (SERVED)", "rolling", "rolling"),
]


@dataclass
class Replay:
    trades: pd.DataFrame
    fixed_thresholds: dict
    rolling_threshold_stats: dict
    cold_bars: dict


def run(ds: list, spec: backtest.PolicySpec, regimes: dict, arm: Arm,
        window_days: float | str = RANK_WINDOW_DAYS, min_rank_bars: int = MIN_RANK_BARS,
        regime_window_days: float | str = REGIME_WINDOW_DAYS,
        regime_min_bars: int = REGIME_MIN_BARS) -> Replay:
    """Score `spec` under one arm's cut/ladder combination.

    Deliberately narrower than `backtest.run`: it handles the served spec's shape only
    (model side, no learned overlay, no hard regime filter) and raises on anything else
    rather than silently scoring a different rule than the caller asked for.
    """
    if spec.side_from != "model" or spec.score_col is not None or spec.size_col is not None:
        raise SystemExit("livemode scores the served spec shape only (model side, no overlay)")
    if spec.regime_quantile is not None or spec.regime_min is not None:
        raise SystemExit("livemode does not implement the hard regime filter — it is not served")
    if not (spec.regime_col and spec.size_by_regime):
        raise SystemExit("livemode needs regime_col + size_by_regime — the SIZED variant")

    hold_h = spec.hold_horizon or spec.signal_horizon
    hold_bars = backtest.HORIZON_BARS[hold_h]

    all_trades, fixed_thr, roll_stats, cold = [], {}, {}, {}
    for d in ds:
        sig = d.at(spec.signal_horizon)[["pair", "ts", "conf", "side", "y3", "has_book"]]
        hold = d.at(hold_h)[["pair", "ts", "fwd_ret"]]
        bars = sig.merge(hold, on=["pair", "ts"], how="inner")
        bars = bars.sort_values("ts", kind="mergesort").reset_index(drop=True)

        ts = bars["ts"].to_numpy()
        conf = bars["conf"].to_numpy(np.float64)

        # ---- the coverage cut ---------------------------------------------------------
        fixed = backtest.coverage_threshold(conf, spec.coverage)
        fixed_thr[d.seed] = fixed
        if arm.cut == "fixed":
            thr_per_bar = np.full(ts.size, fixed)
        else:
            key = ("cut", d.seed, spec.coverage, window_days, min_rank_bars)
            if key not in _CACHE:
                _CACHE[key] = rolling_coverage_threshold(ts, conf, spec.coverage,
                                                        window_days, min_rank_bars)
            grid, thr = _CACHE[key]
            thr_per_bar = thr[np.searchsorted(grid, ts)]
            warm = np.isfinite(thr)
            roll_stats[d.seed] = {
                "fixed": fixed,
                "mean": float(np.nanmean(thr)), "min": float(np.nanmin(thr)),
                "max": float(np.nanmax(thr)),
                "p_below_fixed": float((thr[warm] < fixed).mean()) if warm.any() else float("nan"),
                "cold_ts": int((~warm).sum()), "ts": int(grid.size),
            }
            cold[d.seed] = int((~np.isfinite(thr_per_bar)).sum())

        # A NaN threshold is cold, and cold means "do not trade" — never "threshold 0".
        keep = np.isfinite(thr_per_bar) & (conf >= thr_per_bar)
        sel = bars[keep].copy()

        # ---- the regime, and the sizing ladder ----------------------------------------
        r = regimes[d.seed][["pair", "ts", spec.regime_col]]
        sel = sel.merge(r, on=["pair", "ts"], how="left")
        sel = sel[sel[spec.regime_col].notna()]
        sel["regime"] = sel[spec.regime_col]
        rv = sel[spec.regime_col].to_numpy(np.float64)

        if arm.ladder == "fixed":
            edges = r[spec.regime_col].quantile([0.2, 0.4, 0.6, 0.8]).to_numpy()
            q = np.searchsorted(edges, rv, side="right")
        else:
            # Market-wide observable: one value per ts, deduplicated before ranking, because
            # live reads the BTC series and never sees it once per pair.
            m = r[["ts", spec.regime_col]].dropna().drop_duplicates("ts").sort_values("ts")
            key = ("ladder", d.seed, spec.regime_col, regime_window_days, regime_min_bars)
            if key not in _CACHE:
                _CACHE[key] = rolling_quintile_edges(m["ts"].to_numpy(),
                                                     m[spec.regime_col].to_numpy(np.float64),
                                                     regime_window_days, regime_min_bars)
            grid, ed = _CACHE[key]
            idx = np.searchsorted(grid, sel["ts"].to_numpy())
            rows = ed[np.clip(idx, 0, grid.size - 1)]
            ready = np.isfinite(rows[:, 0])
            # searchsorted right, per row, against that row's own edges
            q = (rv[:, None] >= rows).sum(axis=1).astype(np.int64)
            q = np.where(ready, q, 2)      # ladder cold -> bucket 3 -> flat size 1.0
        sel["size"] = (q.astype(np.float64) + 1.0) / 3.0

        sel = sel.sort_values("ts", kind="mergesort")
        t = backtest._simulate_seed(sel, hold_bars, spec.max_concurrent)
        # `_simulate_seed` carries conf/regime through onto the trade already.
        t["seed"] = d.seed
        all_trades.append(t)

    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    return Replay(trades=trades, fixed_thresholds=fixed_thr,
                  rolling_threshold_stats=roll_stats, cold_bars=cold)


# ---------------------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------------------

def validate_fidelity(ds: list, spec: backtest.PolicySpec, regimes: dict) -> None:
    """With an unbounded window and no cold floor, arm D must equal `backtest.run` exactly.

    This is the test that makes the A-vs-D gap readable as the windowing. Without it a
    difference could just as easily be a bug in this file.
    """
    ref = backtest.run(ds, spec, regimes).trades
    got = run(ds, spec, regimes, ARMS[3],
              window_days=FULL, min_rank_bars=0,
              regime_window_days=FULL, regime_min_bars=0).trades
    cols = ["seed", "pair", "entry_ts", "exit_ts", "side", "size", "signed_ret"]
    a = ref[cols].sort_values(cols[:4]).reset_index(drop=True)
    b = got[cols].sort_values(cols[:4]).reset_index(drop=True)
    if len(a) != len(b):
        raise SystemExit(f"ACCEPTANCE FAILED: {len(a)} trades in backtest.run, {len(b)} here")
    bad = ~np.isclose(a["signed_ret"], b["signed_ret"], rtol=0, atol=1e-12)
    if bad.any() or not (a["pair"].to_numpy() == b["pair"].to_numpy()).all():
        raise SystemExit(f"ACCEPTANCE FAILED: {int(bad.sum())} rows differ from backtest.run")
    print(f"  acceptance: unbounded-window replay reproduces backtest.run exactly "
          f"({len(a):,} trades, every signed_ret identical)")
