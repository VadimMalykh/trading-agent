"""The walk-forward folds — WALKFORWARD_PROTOCOL.md §2 and §3, in code.

WHAT THIS IS FOR. Every M3 number so far was measured on one validation window,
2025-12 → 2026-09, and every policy the project has looked at was chosen while looking at
it. The folds retrain the same recipe with the split boundary moved back and score the
incumbent rule on months no search has ever seen. This module is the scoring half: the
training half is `train_m2.py`'s `walkforward_window` split, already plumbed, and the run
queue is §5 of the protocol.

THE ORDER THIS FILE INSISTS ON. The protocol is pre-registered, which is only worth
anything if the code cannot quietly re-read it once the numbers exist. So:

  * the criteria W1–W5 are functions with no free parameters — every constant in them is
    §3's, written here once;
  * the verdict is refused, not approximated, while any of the twelve runs is missing.
    A partial family gets a table clearly marked PROVISIONAL and no verdict at all, because
    "F2 looked good so we stopped" is precisely the failure a pre-registration prevents;
  * F0 and F1 are printed in their own section, under a banner saying they may not enter a
    promotion argument (§3, last bullet). They are the §1.1 control and the continuity
    check, nothing else.

WHAT IS SCORED. The incumbent, `cov0.02_hold240_rqnone_mcnone_SIZED` (cli.WINNER_SPEC) —
the rule as served — with **each fold's own coverage cut and its own regime ladder**. That
falls out of `backtest.run` unchanged: it derives the cut and the bar-quintile edges per
dump, and a fold's dump is its own val window. Nothing is inherited from the incumbent, so
no constant crosses a fold boundary. Alongside it, reported and never selected on, the
flat-size anchor `cov0.02_hold240_rqnone_mcnone`, so the ladder's contribution per fold is
visible as it was in M3_3_RESULTS §D2.

THE UNIVERSE. §2 names the rule but not the pair list. **Decided 2026-09-04, before any fold
was trained: the folds are scored on TWELVE** — every pair present in each fold's own dump,
which is the universe actually served since 2026-08-29. `--universe 8` restricts to
`dumps.BASE8` and is a diagnostic, not the decision.

🔴 **What choosing twelve costs, stated here because it is the whole reason §1.1 exists.**
HYPE, WLD, ZEC and 1000PEPE are late listings, so an older fold simply has fewer pairs, and a
pooled number over four folds with different pair lists is not one number — part of any
fold-to-fold difference is the universe moving rather than the market. Every table therefore
prints its fold's pair count, and the §1.1 restriction — the same statistic over only the pairs
present in *every loaded fold* — is printed beneath it. **Read the restricted table before
concluding anything about a fold-to-fold difference.**

CLUSTERING. Day-clustered throughout (`metrics.clustered_mean_bps`), for the reason that
module gives: three seeds gating the same bar are three views of one market moment. Two
*folds* are not — their val windows do not overlap in calendar — so pooling F2 with F3 adds
genuinely new clusters, which is the entire point of the exercise.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import backtest, dumps, metrics, regime

# §3's constants. Every one of them is from the pre-registration; none is a tuning knob.
MIN_TRADES_PER_FOLD = 100        # W3
MIN_CLUSTERS_PER_FOLD = 40       # W3
MIN_TRADES_PER_DAY_PER_SEED = 0.5  # W5
DECISION_FOLDS = ("F2", "F3")    # §3: the untouched folds, the only ones that decide
REPORTED_FOLDS = ("F1", "F0")    # §3, last bullet: reported, never in an argument

COST = metrics.TAKER_COST_BPS    # W1/W2/W4 are all "at taker"


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------

def require_walkforward_era() -> None:
    if dumps.ERA != "walkforward":
        raise SystemExit(
            f"this command reads the fold dumps; run it with M3_ERA=walkforward "
            f"(era is {dumps.ERA!r})"
        )


def registry_state() -> str:
    """A block naming every registered run and whether it exists yet — printed by every
    entry point, so no table is ever read without its provenance next to it."""
    lines = ["the twelve pre-registered runs (WALKFORWARD_PROTOCOL §5–§6):"]
    for fold in dumps.FOLD_RUN_ORDER:
        got = []
        for s in (1, 2, 3):
            rid = dumps.WALKFORWARD_RUNS[f"{fold}s{s}"]
            got.append(f"s{s}={rid}" if rid else f"s{s}=—")
        span = dumps.WALKFORWARD_SPLITS[fold]
        val = f"val [{span[0]} → {span[1]}]" if span else "val span not recorded"
        lines.append(f"  {fold}  offset={dumps.FOLD_OFFSETS[fold]:.3f}  {'  '.join(got)}   {val}")
    missing = dumps.missing_runs()
    lines.append(f"  {12 - len(missing)} of 12 recorded"
                 + (f"; missing {', '.join(missing)}" if missing else " — complete"))
    return "\n".join(lines)


def load_folds(pairs: list[str] | None) -> list[dumps.Dump]:
    """Every recorded fold dump, in F0s1..F3s3 registry order.

    `pairs=None` loads the dump's full pair list, which is what validate's TEST 3 needs (the
    trainer's logged table is over everything it validated on). The scoring path passes
    `dumps.BASE8` or the twelve, and a fold that is missing a pair simply has fewer.
    """
    require_walkforward_era()
    ds = dumps.load_baseline(pairs=pairs)
    if not ds:
        raise SystemExit("no fold dumps recorded yet — nothing to score; the registry above "
                         "says which twelve runs are expected.")
    return ds


def by_fold(ds: list[dumps.Dump]) -> dict[str, list[dumps.Dump]]:
    out: dict[str, list[dumps.Dump]] = {}
    for d in ds:
        out.setdefault(dumps.fold_of(d.seed), []).append(d)
    return out


def fold_span_days(ds: list[dumps.Dump]) -> float:
    """The fold's val window in days, from its bars rather than from its trades.

    W5 is a *rate*, and a rate whose denominator is the span of the trades it counts cannot
    fall below its own threshold — a policy that fires twice in one day and never again
    would read as 2/day. The honest denominator is how long the fold was exposed, i.e. the
    val window itself.
    """
    t = pd.concat([pd.to_datetime(d.at(240)["ts"], unit="ns", utc=True) for d in ds])
    return max((t.max() - t.min()).total_seconds() / 86400.0, 1.0)


def common_pairs(folds: dict[str, list[dumps.Dump]]) -> list[str]:
    """§1.1: the pairs present in every fold. Older folds predate several listings, so a
    pooled statistic over each fold's own pair list is a mix of universes."""
    sets = [set(pd.concat([d.at(240)["pair"] for d in ds]).unique()) for ds in folds.values()]
    return sorted(set.intersection(*sets)) if sets else []


# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------

def run_policy(ds: list[dumps.Dump], spec: backtest.PolicySpec) -> pd.DataFrame:
    regimes = {d.seed: regime.build(d.df) for d in ds} if spec.regime_col else None
    return backtest.run(ds, spec, regimes).trades


def fold_table(trades: pd.DataFrame, folds: dict[str, list[dumps.Dump]],
               cost: float = COST) -> pd.DataFrame:
    """One row per fold: counts, clusters, net with its day-clustered interval, rate."""
    rows = []
    for fold in dumps.FOLD_RUN_ORDER:
        if fold not in folds:
            continue
        t = trades[trades["seed"].map(dumps.fold_of) == fold]
        c = metrics.clustered_mean_bps(t, cost)
        n_seeds = len(folds[fold])
        span = fold_span_days(folds[fold])
        ts = pd.to_datetime(t["entry_ts"], unit="ns", utc=True) if len(t) else None
        rows.append({
            "fold": fold,
            # Printed on every row so a fold's standing is never inferred from its name.
            "role": "DECIDES" if fold in DECISION_FOLDS else "reported",
            "seeds": n_seeds,
            "pairs": int(pd.concat([d.at(240)["pair"] for d in folds[fold]]).nunique()),
            "trades": c["n"],
            "clusters": c["clusters"],
            "gross_bps": float(t["signed_ret"].mean() * metrics.BPS) if len(t) else np.nan,
            "net_bps": c["mean_bps"] if c["n"] else np.nan,
            "lo95": c["lo95_bps"],
            "hi95": c["hi95_bps"],
            "per_day": len(t) / n_seeds / span if n_seeds else np.nan,
            "val_days": span,
            "first": f"{ts.min():%Y-%m-%d}" if ts is not None and len(ts) else "—",
            "last": f"{ts.max():%Y-%m-%d}" if ts is not None and len(ts) else "—",
        })
    return pd.DataFrame(rows)


def _fmt(tbl: pd.DataFrame) -> str:
    out = tbl.copy()
    out["95% CI"] = [f"[{lo:+.1f}, {hi:+.1f}]" if np.isfinite(lo) else "n/a"
                     for lo, hi in zip(out["lo95"], out["hi95"])]
    out = out.drop(columns=["lo95", "hi95"])
    return out.to_string(index=False, float_format=lambda v: f"{v:+.2f}")


# --------------------------------------------------------------------------------------
# §3's five criteria. One function each, no free parameters.
# --------------------------------------------------------------------------------------

def w1(trades: pd.DataFrame) -> dict:
    """THE RANKING STATISTIC: day-clustered 95% lower bound of pooled net at taker on F2+F3."""
    t = trades[trades["seed"].map(dumps.fold_of).isin(DECISION_FOLDS)]
    c = metrics.clustered_mean_bps(t, COST)
    return {"pass": bool(c["n"] and c["lo95_bps"] > 0), **c}


def w2(tbl: pd.DataFrame) -> dict:
    """VETO: each decision fold's clustered UPPER bound must be > 0.

    Note what this does and does not say. A fold with a negative point estimate does not
    fail; a fold whose whole interval sits below zero does. §3 wrote it that way because at
    these sample sizes a negative point estimate is the expected outcome of noise, and a
    veto that fires on noise would reject the rule on a coin flip.
    """
    per = {}
    for fold in DECISION_FOLDS:
        row = tbl[tbl["fold"] == fold]
        if row.empty:
            per[fold] = {"pass": None, "hi95": np.nan}
            continue
        hi = float(row["hi95"].iloc[0])
        per[fold] = {"pass": bool(hi > 0), "hi95": hi,
                     "net_bps": float(row["net_bps"].iloc[0])}
    return {"pass": all(v["pass"] for v in per.values()) if per else False, "per_fold": per}


def w3(tbl: pd.DataFrame) -> dict:
    """ELIGIBILITY: every fold holds >= 100 pooled trades AND >= 40 exit-day clusters."""
    per = {}
    for _, r in tbl.iterrows():
        per[r["fold"]] = {
            "trades": int(r["trades"]), "clusters": int(r["clusters"]),
            "pass": bool(r["trades"] >= MIN_TRADES_PER_FOLD
                         and r["clusters"] >= MIN_CLUSTERS_PER_FOLD),
        }
    return {"pass": all(v["pass"] for v in per.values()) if per else False, "per_fold": per}


def w4(trades: pd.DataFrame) -> dict:
    """P5: all three seeds pooled-positive at taker on F2+F3.

    "Seed" here is the seed *number*, pooled across the two decision folds — seed 1's F2 run
    and seed 1's F3 run are the same initialisation trained on two boundaries, and §3 asks
    whether that initialisation makes money on untouched history, not whether each of its
    six (fold, seed) cells does.
    """
    t = trades[trades["seed"].map(dumps.fold_of).isin(DECISION_FOLDS)]
    per = {}
    for s in ("s1", "s2", "s3"):
        sub = t[t["seed"].str.endswith(s)]
        c = metrics.clustered_mean_bps(sub, COST)
        per[s] = {"trades": c["n"], "net_bps": c["mean_bps"], "pass": bool(c["n"] and c["mean_bps"] > 0)}
    return {"pass": all(v["pass"] for v in per.values()), "per_seed": per}


def w5(tbl: pd.DataFrame) -> dict:
    """P6: trade rate >= 0.5 / day / seed on every fold."""
    per = {}
    for _, r in tbl.iterrows():
        per[r["fold"]] = {"per_day": float(r["per_day"]),
                          "pass": bool(r["per_day"] >= MIN_TRADES_PER_DAY_PER_SEED)}
    return {"pass": all(v["pass"] for v in per.values()) if per else False, "per_fold": per}


def verdict(c1: dict, c2: dict, c3: dict, c4: dict, c5: dict) -> tuple[str, list[str]]:
    """§3's "Readings, fixed now", applied in the order §3 states them."""
    notes = []
    if not c2["pass"]:
        failed = [f for f, v in c2["per_fold"].items() if v["pass"] is False]
        notes.append(f"W2 veto on {', '.join(failed)}: the fold's whole 95% interval is below "
                     f"zero, so the rule is significantly negative on that era.")
        notes.append("§3: that is a finding about the rule, recorded as one. It is NOT grounds "
                     "to drop the fold.")
        return "W2 VETO — the rule fails on an untouched era", notes

    blocked = [n for n, c in (("W3", c3), ("W4", c4), ("W5", c5)) if not c["pass"]]
    if blocked:
        notes.append(f"{', '.join(blocked)} does not hold, so §3's reading of W1 is not "
                     f"reached: the family is ineligible on its own pre-registered terms.")
        return f"INELIGIBLE — {', '.join(blocked)} fails", notes

    notes.append(f"W1 = {c1['lo95_bps']:+.2f} bps/trade (mean {c1['mean_bps']:+.2f}, "
                 f"{c1['n']:,} trades in {c1['clusters']} day-clusters).")
    if c1["pass"]:
        notes.append("W2–W5 all hold. §3: the rule is CONFIRMED out of sample on untouched "
                     "history — the first result in this project that is evidence rather than "
                     "absence-of-refutation, and the precondition for confirming anything "
                     "parked (§4.3) on these folds.")
        return "CONFIRMED — W1 > 0 with W2–W5 holding", notes
    notes.append("W2–W5 hold but W1 <= 0. §3: NOT DECIDABLE at four folds. The next step is "
                 "more folds — a fifth and sixth at offset 0.5/0.625 need TRAIN_FRACTION < 0.5 "
                 "and are a NEW registration — and explicitly not a wider rule.")
    return "NOT DECIDABLE — W1 <= 0 with W2–W5 holding", notes


# --------------------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------------------

def report(sized_spec: dict, flat_spec: dict, universe: str = "12") -> int:
    require_walkforward_era()
    print("=" * 96)
    print("WALK-FORWARD FOLDS — WALKFORWARD_PROTOCOL.md §3")
    print("=" * 96)
    print(registry_state())

    missing = dumps.missing_runs()
    pairs = dumps.BASE8 if universe == "8" else None
    label = ("8 pairs (dumps.BASE8) — DIAGNOSTIC ONLY; §3 is decided on twelve"
             if universe == "8"
             else "every pair in each fold's dump, up to 12 — the served universe, and what "
                  "§3 decides on (pinned 2026-09-04, before the first fold)")
    print(f"\nuniverse: {label}")
    print(f"cost line: taker {COST:.0f} bps round trip; all intervals are day-clustered")

    ds = load_folds(pairs)
    folds = by_fold(ds)
    for d in ds:
        h = d.at(240)
        t = pd.to_datetime(h["ts"], unit="ns", utc=True)
        print(f"  {d.seed}  {d.run_id}  {len(h):>8,} bars  {h['pair'].nunique():>2} pairs  "
              f"{t.min():%Y-%m-%d} .. {t.max():%Y-%m-%d}")

    shared = common_pairs(folds)
    print(f"\npairs present in every LOADED fold (§1.1): {len(shared)} — {', '.join(shared)}")

    sized = backtest.PolicySpec(label="incumbent SIZED", **sized_spec)
    flat = backtest.PolicySpec(label="flat anchor", **flat_spec)

    print("\n" + "=" * 96)
    print("A. THE INCUMBENT, PER FOLD — each fold's own coverage cut and its own ladder")
    print("=" * 96)
    trades = run_policy(ds, sized)
    tbl = fold_table(trades, folds)
    print(_fmt(tbl))

    print("\n   the flat-size anchor (REPORTED, NEVER SELECTED ON — §2):")
    flat_tbl = fold_table(run_policy(ds, flat), folds)
    print("   " + _fmt(flat_tbl).replace("\n", "\n   "))

    if shared:
        print(f"\n   restricted to the {len(shared)} pairs present in every loaded fold (§1.1):")
        r_ds = [dumps.load(d.run_id, seed=d.seed, pairs=shared) for d in ds]
        r_tbl = fold_table(run_policy(r_ds, sized), by_fold(r_ds))
        print("   " + _fmt(r_tbl).replace("\n", "\n   "))

    print("\n" + "=" * 96)
    print(f"B. §3's FIVE CRITERIA — decided on {' + '.join(DECISION_FOLDS)} only")
    print("=" * 96)
    c1, c2 = w1(trades), w2(tbl)
    c3, c4, c5 = w3(tbl), w4(trades), w5(tbl)

    print(f"W1  ranking statistic: pooled net at taker on {'+'.join(DECISION_FOLDS)} = "
          f"{c1['mean_bps']:+.2f} bps, 95% CI [{c1['lo95_bps']:+.2f}, {c1['hi95_bps']:+.2f}], "
          f"n={c1['n']:,} in {c1['clusters']} clusters   -> LOWER BOUND {c1['lo95_bps']:+.2f} "
          f"({'>' if c1['pass'] else '<='} 0)")
    print("W2  veto (each decision fold's clustered UPPER bound > 0):")
    for f, v in c2["per_fold"].items():
        state = "n/a — fold not loaded" if v["pass"] is None else ("ok" if v["pass"] else "🔴 VETO")
        net = f"net {v.get('net_bps', float('nan')):+.2f}  " if v["pass"] is not None else ""
        print(f"      {f}: {net}hi95 {v['hi95']:+.2f}   {state}")
    print(f"W3  eligibility (>= {MIN_TRADES_PER_FOLD} trades and >= {MIN_CLUSTERS_PER_FOLD} "
          f"exit-day clusters per fold):")
    for f, v in c3["per_fold"].items():
        print(f"      {f}: {v['trades']:,} trades, {v['clusters']} clusters   "
              f"{'ok' if v['pass'] else '🔴 FAIL'}")
    print("W4  all three seeds pooled-positive at taker on the decision folds:")
    for s, v in c4["per_seed"].items():
        print(f"      {s}: {v['net_bps']:+.2f} bps over {v['trades']:,} trades   "
              f"{'ok' if v['pass'] else '🔴 FAIL'}")
    print(f"W5  trade rate >= {MIN_TRADES_PER_DAY_PER_SEED}/day/seed on every fold:")
    for f, v in c5["per_fold"].items():
        print(f"      {f}: {v['per_day']:.2f}/day/seed   {'ok' if v['pass'] else '🔴 FAIL'}")

    print("\n" + "=" * 96)
    if missing:
        print("PROVISIONAL — NOT §3's VERDICT")
        print("=" * 96)
        print(f"{len(missing)} of the twelve pre-registered runs are missing "
              f"({', '.join(missing)}).")
        print("§3 is read once, on the complete family. The criteria above are printed so the")
        print("queue can be steered — a fold that is already ineligible on counts (W3) is worth")
        print("knowing about before the next four hours of GPU — and for no other purpose. No")
        print("verdict is produced, and none of these numbers may be quoted as a fold result.")
        return 0

    v, notes = verdict(c1, c2, c3, c4, c5)
    print(f"§3 VERDICT: {v}")
    print("=" * 96)
    for n in notes:
        print(f"  - {n}")

    print("\n" + "=" * 96)
    print("C. F0 AND F1 — REPORTED ONLY (§3, last bullet)")
    print("=" * 96)
    print("These folds' val windows overlap history the M3 policy search has already read, so")
    print("they may not enter a promotion or confirmation argument. F0 is §1.1's control for")
    print("the fixed-width train window; F1 straddles the incumbent's train boundary.")
    shown = [f for f in REPORTED_FOLDS if f in folds]
    if shown:
        print(_fmt(tbl[tbl["fold"].isin(shown)]))
    else:
        print("  (neither is loaded yet)")
    return 0
