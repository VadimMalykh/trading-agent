"""The policy simulator.

WHAT A POLICY IS HERE. A decision rule over already-computed predictions: which bars to
enter on, on which side, how large, and when to exit. No model is trained and no price
series is read — which bounds what this file can honestly simulate:

  🔴 **Fixed-hold only.** The dumps carry `fwd_ret` at 60/240/1440 minutes and nothing
  else, so an exit can only be placed at one of those horizons. Stops, take-profits and
  trailing exits need the price/funding side-table of M3_PLAN §M3-0b and are deliberately
  NOT approximated here — a barrier policy backtested against a fixed-horizon return is
  the exact "policy mismatch" C4b was filed for.

THREE INVARIANTS, each one a finding paid for with a wave of runs (§1.3):

  1. **Entry is by coverage rank, never by a confidence constant.** The same probability is
     1.2%/2.5%/1.7% coverage across the three seeds, so a policy written against
     `conf > 0.63` silently changes meaning on the next checkpoint. `PolicySpec.coverage`
     is a fraction of bars; the threshold is derived per seed.
  2. **Positions are serial per (seed, pair).** While a position is open, new signals on
     that pair are ignored, exactly as eval_m2.simulate_pnl does — otherwise overlapping
     4h entries book the same move several times and the P&L is fiction.
  3. **The portfolio is capped.** `max_concurrent` bounds simultaneously open positions
     across pairs within a seed. The trainer's per-pair simulation is unbounded in
     aggregate, i.e. not a tradeable portfolio.

TIE HANDLING. `torch.topk` resolves ties at the coverage boundary in an order that is an
artifact of its kernel and is not reproducible from numpy — `reaggregate_preds.py`'s
argpartition picks the other side of the one contended tie in these dumps and loses a trade
because of it. This simulator instead takes **every bar at or above the k-th largest
confidence**, which is deterministic, re-derivable, and the honest definition of "the top
c% of bars" when bars are tied. Measured, not assumed: across 3 seeds x 5 coverages exactly
one boundary is contended (seed 3 at cov05, 2 bars for 1 slot) and the tie-inclusive rule
still reproduces all 15 logged cells to the digit (validate.py TEST 1).

"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .dumps import BAR_SECONDS, NS, Dump

HORIZON_BARS = {60: 12, 240: 48, 1440: 288}


@dataclass
class PolicySpec:
    """Every degree of freedom the policy has. Count these before searching: M3_PLAN §M3-1
    requires the number of configurations to be pre-registered, and this dataclass is what
    that number is counted over."""

    coverage: float = 0.05                 # entry: top fraction of bars by confidence
    signal_horizon: int = 240              # which head's confidence decides entry
    hold_horizon: int | None = None        # which head's fwd_ret books the exit (default: signal)
    regime_col: str | None = None          # e.g. "btc_absret_1d"
    regime_min: float | None = None        # absolute threshold on that column
    regime_quantile: float | None = None   # or a per-split quantile of BARS (not of trades)
    #   regime_col set with NEITHER threshold = condition without filtering (sizing-only)
    size_by_regime: bool = False           # flat size, or scaled by BAR-quintile of regime
    max_concurrent: int | None = None      # portfolio cap, per seed, across pairs
    sides: str = "both"                    # "both" | "long" | "short"
    side_from: str = "model"               # "model" | "momentum" (M3_PROTOCOL §3.2 control)
    label: str = ""

    def degrees_of_freedom(self) -> int:
        knobs = [self.coverage, self.hold_horizon, self.regime_col,
                 self.regime_min or self.regime_quantile,
                 self.size_by_regime, self.max_concurrent]
        return sum(1 for k in knobs if k not in (None, False))


@dataclass
class Result:
    trades: pd.DataFrame
    thresholds: dict = field(default_factory=dict)   # per-seed confidence threshold
    regime_thresholds: dict = field(default_factory=dict)
    spec: PolicySpec | None = None


def coverage_threshold(conf: np.ndarray, coverage: float) -> float:
    """The k-th largest confidence, k = round(n * coverage) — the trainer's definition of a
    fixed-coverage slice (gate.fixed_coverage_metrics). Selection then takes conf >= this,
    which is tie-inclusive and deterministic (see the module docstring)."""
    n = conf.size
    k = int(round(n * coverage))
    if k <= 0:
        raise ValueError(f"coverage {coverage} selects 0 of {n} bars")
    k = min(k, n)
    return float(np.partition(conf, n - k)[n - k])


def _simulate_seed(bars: pd.DataFrame, hold_bars: int, max_concurrent: int | None) -> pd.DataFrame:
    """Serial-per-pair, capped-in-aggregate event loop over one seed's candidate bars.

    `bars` must be the already-filtered entry candidates, sorted by ts, and carry the
    fwd_ret of the HOLD horizon. Positions close on time; the loop walks bars in time order
    so that the concurrency cap is applied with the same information a live trader has.
    """
    hold_ns = hold_bars * BAR_SECONDS * NS
    ts = bars["ts"].to_numpy()
    pair = bars["pair"].astype(str).to_numpy()
    side = bars["side"].to_numpy(np.float64)
    ret = bars["fwd_ret"].to_numpy(np.float64)
    size = bars["size"].to_numpy(np.float64) if "size" in bars else np.ones(len(bars))
    # Columns carried through onto the trade so downstream tables (dir_acc ladders,
    # regime quintiles, book-era splits) never have to re-join against the dump.
    extra_cols = [c for c in ("conf", "y3", "has_book") if c in bars]
    extra = {c: bars[c].to_numpy() for c in extra_cols}
    if "regime" in bars:
        extra["regime"] = bars["regime"].to_numpy(np.float64)

    open_until: dict[str, int] = {}       # pair -> exit ts of its open position
    rows = []
    for i in range(len(bars)):
        t = ts[i]
        # retire anything that has closed by now (a dict scan is cheap: <= 12 pairs)
        for p, exit_ts in list(open_until.items()):
            if exit_ts <= t:
                del open_until[p]
        p = pair[i]
        if p in open_until:                       # invariant 2: serial per pair
            continue
        if max_concurrent is not None and len(open_until) >= max_concurrent:
            continue                              # invariant 3: portfolio cap
        exit_ts = t + hold_ns
        open_until[p] = exit_ts
        rows.append((i, p, t, exit_ts, side[i], ret[i], size[i], side[i] * ret[i] * size[i]))

    out = pd.DataFrame(
        rows, columns=["_i", "pair", "entry_ts", "exit_ts", "side", "fwd_ret", "size", "signed_ret"]
    )
    for c, v in extra.items():
        out[c] = v[out["_i"].to_numpy()] if len(out) else []
    return out.drop(columns="_i")


def run(dumps: list[Dump], spec: PolicySpec,
        regimes: dict[str, pd.DataFrame] | None = None) -> Result:
    """Run one policy across a list of seed dumps and return the pooled trade ledger.

    `regimes` maps seed -> the frame returned by regime.build(); required iff the spec
    conditions or sizes on a regime column.
    """
    hold_h = spec.hold_horizon or spec.signal_horizon
    if hold_h not in HORIZON_BARS:
        raise SystemExit(f"hold_horizon must be one of {sorted(HORIZON_BARS)} (the dumped heads)")
    hold_bars = HORIZON_BARS[hold_h]

    all_trades, thresholds, regime_thr = [], {}, {}
    for d in dumps:
        sig = d.at(spec.signal_horizon)[["pair", "ts", "conf", "side", "y3", "has_book"]]
        hold = d.at(hold_h)[["pair", "ts", "fwd_ret"]]
        bars = sig.merge(hold, on=["pair", "ts"], how="inner")

        # --- the side control (M3_PROTOCOL §3.2) --------------------------------------
        # Replace the model's side with sign(trailing 240m return) while leaving entry
        # selection untouched, so the control trades the SAME bars as the policy it is a
        # control for. Applied before any filtering, because coverage rank, the regime cut
        # and the concurrency cap all key off confidence and time, never off side.
        if spec.side_from == "momentum":
            if regimes is None or d.seed not in regimes:
                raise SystemExit("side_from='momentum' needs regimes carrying trail_240m")
            m = regimes[d.seed][["pair", "ts", "trail_240m"]]
            bars = bars.merge(m, on=["pair", "ts"], how="left")
            # Bars whose 4h lookback is incomplete carry no momentum side; drop rather
            # than default to long, which would silently make the control directional.
            bars = bars[bars["trail_240m"].notna()].copy()
            bars["side"] = np.where(bars["trail_240m"] >= 0.0, 1.0, -1.0)
        elif spec.side_from != "model":
            raise SystemExit(f"side_from must be 'model' or 'momentum', got {spec.side_from!r}")

        # --- invariant 1: coverage rank over this seed's own population ---------------
        thr = coverage_threshold(bars["conf"].to_numpy(np.float64), spec.coverage)
        thresholds[d.seed] = thr
        sel = bars[bars["conf"] >= thr].copy()

        # --- regime conditioning ------------------------------------------------------
        if spec.regime_col:
            if regimes is None or d.seed not in regimes:
                raise SystemExit(f"spec conditions on {spec.regime_col} but no regimes for {d.seed}")
            r = regimes[d.seed][["pair", "ts", spec.regime_col]]
            sel = sel.merge(r, on=["pair", "ts"], how="left")
            # A bar whose lookback is incomplete carries no regime value. Drop it rather
            # than zero-fill — validate.py's TEST 2 drops the same 24 pooled bars, so the
            # simulator and the acceptance test agree on the population.
            sel = sel[sel[spec.regime_col].notna()]
            # EVERY regime cut — the hard filter here and the sizing buckets below — is a
            # quantile of BARS, not of trades. It has to be a statement about the market,
            # derivable without knowing which bars the model gated; a quantile taken over
            # the already-selected trades is conditioned on the model and is not that.
            if spec.regime_quantile is not None:
                cut = float(r[spec.regime_col].quantile(spec.regime_quantile))
            elif spec.regime_min is not None:
                cut = float(spec.regime_min)
            else:
                cut = None       # sizing-only: condition on the regime without filtering
            if cut is not None:
                regime_thr[d.seed] = cut
                sel = sel[sel[spec.regime_col] >= cut]
            sel["regime"] = sel[spec.regime_col]

        if spec.sides == "long":
            sel = sel[sel["side"] > 0]
        elif spec.sides == "short":
            sel = sel[sel["side"] < 0]

        sel["size"] = 1.0
        if spec.size_by_regime:
            if not spec.regime_col:
                raise SystemExit("size_by_regime needs regime_col")
            # Bucket against the BAR distribution's quintile edges, for the reason given
            # above. One consequence is worth stating out loud: combined with a hard
            # regime_quantile=0.8 filter every surviving trade is already in bucket 5, so
            # sizing degenerates to a flat 5/3 and buys nothing. Regime sizing is a
            # distinct policy only when the hard filter is OFF — it is the soft version of
            # the same idea, trading small out-of-regime instead of not at all.
            edges = r[spec.regime_col].quantile([0.2, 0.4, 0.6, 0.8]).to_numpy()
            q = np.searchsorted(edges, sel[spec.regime_col].to_numpy(), side="right")
            sel["size"] = (q.astype(np.float64) + 1.0) / 3.0        # 1/3 .. 5/3, mean ~1

        sel = sel.sort_values("ts", kind="mergesort")
        t = _simulate_seed(sel, hold_bars, spec.max_concurrent)
        t["seed"] = d.seed
        all_trades.append(t)

    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    return Result(trades=trades, thresholds=thresholds, regime_thresholds=regime_thr, spec=spec)
