"""The M3-3 observation vector — what a learned policy is allowed to see.

M3_PLAN §2 (M3-3) names four groups: M2's per-horizon probabilities and confidences *as
coverage rank*, trailing market-move magnitude, position state, and optionally a realised-vol
context. Three of the four are buildable from the dumps alone; the fourth is not, and saying
so out loud is part of the point of this file.

THE FOUR DESIGN RULES, each inherited from a finding rather than chosen here:

  1. **Everything is a rank, never a level.** §1.3.3: the same probability is 1.2% / 2.5% /
     1.7% coverage across the three seeds, so a feature written against `conf` silently
     changes meaning on the next checkpoint. Every observation below is a percentile within
     its own seed's bar population, which is invariant to that drift. It also makes the
     features scale-free, so one ridge penalty is meaningful across all of them.

  2. **The regime enters continuously.** M3_2_RESULTS §F: the hard top-quintile filter failed
     Tier 1 in all twelve forms while the same observable as a *size multiplier* passed, so a
     learned policy is given `btc_absret_1d` as a continuous observation rather than handed a
     threshold to rediscover. Its percentile is the continuous form of the quintile the M3-2
     winner buckets on, which makes that winner a step function of feature 6 and therefore
     inside this policy class rather than outside it.

  3. **Ranks are target-free.** They are computed over each seed's full 240m bar population,
     including bars in the held-out fold. That is a *monotone transform estimated on the whole
     period*, and it uses no `fwd_ret`, so it cannot leak P&L into a fold. It is also the
     identical assumption M3-2's coverage thresholds already make (backtest.coverage_threshold
     ranks over the seed's whole population), and keeping the two consistent is what makes the
     learned policy and the baseline comparable. It is an approximation and it is declared.

  4. **Position state is absent, deliberately.** Side / age / unrealised P&L need a price path
     between entry and exit, which the dumps do not carry — M3_PLAN §M3-0a constraint 1. Under
     fixed-hold serial entries, age and unrealised P&L are not decision-relevant anyway: there
     is no exit decision to make. They arrive with M3-0b's side-table, together with the
     barrier exits that would give them something to decide.

WHAT IS GENUINELY NEW HERE relative to every M3-2 configuration: the 60m and 1440m heads.
The rules baseline only ever read the 240m confidence. Whether the other two horizons agree
with it is free information sitting in the same dump, it is the sort of thing a linear model
can use and a hand-written rule would not have thought to try, and it is the main reason to
expect a learned policy might beat +0.25 at all.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import regime
from .dumps import Dump, add_window

# The candidate pool: the top POOL_COVERAGE of bars by 240m confidence. Fitting on all
# 579k bars per seed would drown the ~2% of them the policy will ever act on in the 98% it
# will not, and fitting on the top 2% alone would make coverage un-widenable — §1.3.1 makes
# coverage a first-class decision variable and a pool that pins it is not a policy class.
# 10% is a superset of every coverage the M3-2 grid scored (0.01 / 0.02 / 0.05) with
# headroom, and it caps the learned policy at 10% coverage. That cap is a real constraint
# and it is pre-registered rather than discovered.
POOL_COVERAGE = 0.10

SIGNAL_HORIZON = 240

# The observation vector, in a fixed order. This list IS the pre-registration: M3_3_PROTOCOL
# §3 counts its length, and a feature added later is a new protocol, not a new run.
FEATURES = [
    "conf_rank",          # 1. percentile of the 240m confidence — the continuous coverage knob
    "conf_rank_60",       # 2. percentile of the 60m head's confidence
    "conf_rank_1440",     # 3. percentile of the 1440m head's confidence
    "agree_60",           # 4. +1 if the 60m head takes the same side as the 240m, else -1
    "agree_1440",         # 5. likewise for the 1440m head
    "btc_absret_rank",    # 6. percentile of btc_absret_1d — §1.8's observable, continuous
    "rv_rank",            # 7. percentile of the pair's trailing-1d realised vol
    "vol_expansion",      # 8. percentile of rv_1d / rv_7d — is vol rising or falling
    "xs_disp_rank",       # 9. percentile of the cross-sectional dispersion of 4h moves
]


def _pct_rank(s: pd.Series) -> pd.Series:
    """Percentile within the population, in [0, 1]. `average` ties so that a block of equal
    confidences maps to one value rather than to an order that depends on the sort."""
    return s.rank(pct=True, method="average")


def build(d: Dump, reg: pd.DataFrame | None = None) -> pd.DataFrame:
    """The full per-bar observation frame for one seed: (pair, ts, side, fwd_ret, y, FEATURES).

    Returns EVERY 240m bar, not just the pool — `pool()` cuts it, and `m3 fitprep` needs the
    uncut population to report how many bars carry a complete observation.
    """
    if reg is None:
        reg = regime.build(d.df)

    sig = d.at(SIGNAL_HORIZON)[["pair", "ts", "conf", "side", "fwd_ret"]].copy()
    out = sig.rename(columns={"fwd_ret": "fwd_ret_240"})
    out["conf_rank"] = _pct_rank(out["conf"])

    # --- the other two heads (the information M3-2 never looked at) --------------------
    for h in (60, 1440):
        o = d.at(h)[["pair", "ts", "conf", "side"]].rename(
            columns={"conf": f"conf_{h}", "side": f"side_{h}"})
        out = out.merge(o, on=["pair", "ts"], how="left")
        out[f"conf_rank_{h}"] = _pct_rank(out[f"conf_{h}"])
        # Agreement is signed, not boolean, so a linear model reads "disagreement" as the
        # mirror image of "agreement" rather than as the absence of a bonus.
        out[f"agree_{h}"] = np.where(out[f"side_{h}"] == out["side"], 1.0, -1.0)
        out.loc[out[f"side_{h}"].isna(), f"agree_{h}"] = np.nan

    # --- market state -----------------------------------------------------------------
    cols = ["pair", "ts", "btc_absret_1d", "rv_1d", "rv_7d", "xs_disp_4h"]
    out = out.merge(reg[cols], on=["pair", "ts"], how="left")
    out["btc_absret_rank"] = _pct_rank(out["btc_absret_1d"])
    out["rv_rank"] = _pct_rank(out["rv_1d"])
    with np.errstate(divide="ignore", invalid="ignore"):
        expansion = out["rv_1d"] / out["rv_7d"].replace(0.0, np.nan)
    out["vol_expansion"] = _pct_rank(expansion)
    out["xs_disp_rank"] = _pct_rank(out["xs_disp_4h"])

    # The regression target: the gross return of taking this trade, in bps. The fee is a
    # known constant per unit of size, so it is applied at decision time rather than fitted
    # — a model fitted to net return would have to re-fit to answer the maker question,
    # which M3_PLAN §3.3 says is the most valuable open measurement in the milestone.
    out["y_bps"] = out["side"] * out["fwd_ret_240"] * 1e4

    out["seed"] = d.seed
    return add_window(out, ts_col="ts")


def complete(f: pd.DataFrame) -> pd.DataFrame:
    """Bars carrying a complete observation. A bar whose 7-day vol lookback or 24h BTC
    lookback is not yet available is DROPPED, never imputed: an imputed feature value is a
    made-up market state, and §1.8's own rebuild drops the same class of bar (validate.py
    TEST 2 loses 24 pooled trades to it) so the two populations stay comparable."""
    return f[f[FEATURES].notna().all(axis=1) & f["y_bps"].notna()]


def pool(f: pd.DataFrame, coverage: float = POOL_COVERAGE) -> pd.DataFrame:
    """The candidate pool: the top `coverage` of the seed's bars by 240m confidence.

    Cut on `conf_rank` over the FULL bar population (before the completeness filter), so the
    pool is "the top 10% of bars" in the same sense backtest.coverage_threshold means it,
    and an incomplete-lookback bar consumes its slot rather than promoting a less confident
    bar into the pool.
    """
    return complete(f[f["conf_rank"] >= 1.0 - coverage])


def design(f: pd.DataFrame, quadratic: bool = False) -> tuple[np.ndarray, list[str]]:
    """The design matrix, without an intercept column (the fitter adds an unpenalised one).

    `quadratic=False` is model A: the nine features, linear.

    `quadratic=True` is model B: the nine, plus each one squared, plus the eight products of
    `conf_rank` with the other eight — 26 terms. It is NOT a full quadratic expansion (which
    would be 54 terms). The restriction is a pre-registered prior, not a result: with ~220
    independent trading days behind the sample (M3_PROTOCOL §2) the only interaction worth
    spending degrees of freedom on is *does the confidence signal's value depend on market
    state*, which is precisely conf_rank x context. Everything else is capacity we cannot pay
    for, and M3_PLAN §4 ranks overfitting as risk #1 for the whole milestone.
    """
    base = f[FEATURES].to_numpy(np.float64)
    if not quadratic:
        return base, list(FEATURES)
    cols = [base]
    names = list(FEATURES)
    cols.append(base ** 2)
    names += [f"{n}^2" for n in FEATURES]
    ci = FEATURES.index("conf_rank")
    inter = base[:, [ci]] * np.delete(base, ci, axis=1)
    cols.append(inter)
    names += [f"conf_rank*{n}" for n in FEATURES if n != "conf_rank"]
    return np.hstack(cols), names


# ---------------------------------------------------------------------------------------
# Folds
# ---------------------------------------------------------------------------------------
#
# M3_PROTOCOL §1 states plainly that there is no held-out time period and that pretending
# otherwise would be the dishonest move. That is survivable for a five-knob rule scored on
# all four windows; it is not survivable for a fitted model, whose worst-window number would
# be its own training error. So M3-3 buys a hold-out the only way this evidence allows —
# by refitting, four times, and letting each window be scored by a model that never saw it.

WINDOW_NAMES = ("w1", "w2", "w3", "w4")


@dataclass(frozen=True)
class LearnedConfig:
    """One of M3_3_PROTOCOL §4's pre-registered runs, as a value rather than as prose.

    `model` selects the term set (§4.1), `entry` the entry rule (§4.3) and `sizing` the size
    rule (§4.4). Everything else the policy needs is a constant fixed by §4.5 and lives in
    `learn.spec_for()`, not here — a constant that can be varied per config is a knob.
    """

    model: str          # "A" (9 linear terms) | "B" (26 terms) | "conf" (the C2 ablation)
    entry: str          # "R1" (score >= 14bps) | "R2" (top 2% of each seed-window)
    sizing: str         # "S1" (flat) | "S2" (clip(s/s_ref, 1/3, 5/3))

    @property
    def label(self) -> str:
        return f"learn{self.model}_{self.entry}_{self.sizing}"

    @property
    def quadratic(self) -> bool:
        return self.model == "B"


# §4.3 / §4.4, as constants so the report and the runner cannot disagree about them.
ENTRY_THRESHOLD_BPS = 14.0     # R1: the taker round trip
MATCHED_COVERAGE = 0.02        # R2: the M3-2 winner's trade budget
SIZE_CLIP = (1.0 / 3.0, 5.0 / 3.0)   # S2: copied from M3-2's sizing variant, not tuned


def folds() -> list[tuple[str, tuple[str, ...]]]:
    """Leave-one-window-out: (held-out window, the three windows fitted on)."""
    return [(w, tuple(v for v in WINDOW_NAMES if v != w)) for w in WINDOW_NAMES]


def inner_folds(train: tuple[str, ...]) -> list[tuple[str, tuple[str, ...]]]:
    """The same split again inside a training set, for selecting the ridge penalty without
    ever consulting the outer held-out window."""
    return [(w, tuple(v for v in train if v != w)) for w in train]
