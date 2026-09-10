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


# --------------------------------------------------------------------------------------
# §8 — the retrain trigger's N (WALKFORWARD_PROTOCOL §4.2, registered in §8 before this
# code was written; every constant below is that registration's, none is a knob)
# --------------------------------------------------------------------------------------

DRYSPELL_COVERAGE = 0.02      # §8.2: each dump's own cut, at the served coverage
DRYSPELL_PERCENTILE = 95      # §8.2: N is the p95 of the pooled distribution
DRYSPELL_SPREAD_LIMIT = 2.0   # §8.3: per-fold p95s disagreeing by more than this -> NOT DECIDABLE


def dry_spells(d: dumps.Dump) -> np.ndarray:
    """Completed gaps in DAYS between consecutive bars meeting this dump's own 0.02 cut.

    §8.2 fixes every choice here. The cut is the dump's own `coverage_threshold` (C4 —
    nothing is inherited across folds). Spells are measured between *bar timestamps* pooled
    over pairs, not between trades, because the live trigger reads `policy_bars` and a bar
    can meet the cut while the risk manager declines the trade. The leading and trailing
    intervals are censored (§8.2): neither is a completed spell, and keeping them would let
    the arbitrary placement of the val window move N.
    """
    h = d.at(240)
    conf = h["conf"].to_numpy()
    cut = backtest.coverage_threshold(conf, DRYSPELL_COVERAGE)
    t = pd.to_datetime(h["ts"].to_numpy()[conf >= cut], unit="ns", utc=True)
    if t.size < 2:
        return np.empty(0)
    ordered = np.sort(t.view("int64"))
    return np.diff(ordered) / (86_400 * 1e9)


def dryspell_report(universe: str = "12") -> int:
    """§8's table and N. Prints the spread check before the pooled number, as §8.3 requires."""
    require_walkforward_era()
    print("=" * 96)
    print("THE RETRAIN TRIGGER'S N — WALKFORWARD_PROTOCOL §4.2, registered in §8")
    print("=" * 96)
    print(registry_state())
    if dumps.missing_runs():
        print("\n🔴 the family is incomplete; §8 is a statistic over all twelve. No N.")
        return 1

    pairs = dumps.BASE8 if universe == "8" else None
    ds = load_folds(pairs)
    folds = by_fold(ds)
    restrict = common_pairs(folds)
    print(f"\nuniverse: {'the 8-pair diagnostic' if universe == '8' else 'twelve — §6 pins the folds to the served universe'}")
    print(f"each dump's own cut at coverage {DRYSPELL_COVERAGE} (C4); spells between bars "
          f"meeting it, pooled over pairs; leading/trailing intervals censored (§8.2)\n")

    print(f"  {'fold':>5} {'seed':>5} {'cut':>8} {'bars>=cut':>10} {'spells':>7} "
          f"{'p50':>7} {'p90':>7} {'p95':>7} {'max':>8}")
    per_fold: dict[str, np.ndarray] = {}
    for fold in dumps.FOLD_RUN_ORDER:
        for d in folds.get(fold, []):
            h = d.at(240)
            cut = backtest.coverage_threshold(h["conf"].to_numpy(), DRYSPELL_COVERAGE)
            s = dry_spells(d)
            n_met = int((h["conf"].to_numpy() >= cut).sum())
            print(f"  {fold:>5} {d.seed[-2:]:>5} {cut:8.4f} {n_met:10,} {s.size:7,} "
                  f"{np.percentile(s, 50):7.2f} {np.percentile(s, 90):7.2f} "
                  f"{np.percentile(s, 95):7.2f} {s.max():8.2f}")
            per_fold.setdefault(fold, np.empty(0))
            per_fold[fold] = np.concatenate([per_fold[fold], s])

    print(f"\n  {'fold':>5} {'spells':>8} {'p95 (days)':>12}")
    fold_p95 = {}
    for fold in dumps.FOLD_RUN_ORDER:
        s = per_fold[fold]
        fold_p95[fold] = float(np.percentile(s, DRYSPELL_PERCENTILE))
        print(f"  {fold:>5} {s.size:8,} {fold_p95[fold]:12.2f}")

    lo, hi = min(fold_p95.values()), max(fold_p95.values())
    spread = hi / lo if lo > 0 else float("inf")
    print(f"\n§8.3 spread check (printed BEFORE the pooled number): "
          f"per-fold p95 ranges {lo:.2f} .. {hi:.2f} days, ratio {spread:.2f}x "
          f"(limit {DRYSPELL_SPREAD_LIMIT}x)")

    pooled = np.concatenate([per_fold[f] for f in dumps.FOLD_RUN_ORDER])
    n_raw = float(np.percentile(pooled, DRYSPELL_PERCENTILE))
    print(f"\npooled over all twelve runs: {pooled.size:,} spells   "
          f"p50={np.percentile(pooled, 50):.2f}  p90={np.percentile(pooled, 90):.2f}  "
          f"p95={n_raw:.2f}  p99={np.percentile(pooled, 99):.2f}  max={pooled.max():.2f} days")

    if restrict and universe != "8":
        rs = [dry_spells(d) for d in dumps.load_baseline(pairs=restrict)]
        r = np.concatenate([x for x in rs if x.size])
        print(f"restricted to the {len(restrict)} pairs in every fold (§1.1's control): "
              f"{r.size:,} spells   p95={np.percentile(r, DRYSPELL_PERCENTILE):.2f} days")

    print("\n" + "=" * 96)
    if spread > DRYSPELL_SPREAD_LIMIT:
        print(f"§8.3 VERDICT: NOT DECIDABLE — the per-fold p95s disagree by {spread:.2f}x "
              f"(> {DRYSPELL_SPREAD_LIMIT}x).")
        print("  A trigger whose value depends on which era measured it is not a trigger.")
        print("  M3_PROTOCOL §9.1 Q3 (b)'s N = 65 days STANDS, unchanged.")
    else:
        n = int(np.ceil(n_raw))
        print(f"§8.3 VERDICT: N = {n} days (pooled p95 {n_raw:.2f}, rounded up).")
        print(f"  This REPLACES the 65-day single-split estimate in M3_PROTOCOL §9.1 Q3 (b),")
        print(f"  as §8.3 fixed in advance — including if it is larger.")
    print("=" * 96)
    return 0


# --------------------------------------------------------------------------------------
# §9.1 — served coverage at twelve pairs (WALKFORWARD_PROTOCOL §4.3 item 3, registered in
# §9.1 on 2026-09-09 before this code existed; the 2026-09-10 clarifications in that section
# were written before the first run). Every constant below is the registration's.
#
# THE QUESTION. The served cut was derived over the checkpoint's EIGHT-pair split while
# TWELVE pairs are served. On the folds, does a cut derived over the twelve-pair population
# beat the same coverage derived over the eight and applied to the twelve? One variable —
# the population the cut is derived on. The regime ladder, the seeds, the bars are shared.
#
# THE ORDER. `explore` reads F0+F1 only; `confirm` reads F2+F3, once, after the explore
# table is in §9.1, and refuses without the flag that says so. The code cannot read the
# document, so the flag is the reader's signature that the order was kept.
# --------------------------------------------------------------------------------------

COV91_COVERAGE = 0.02                     # §9.1: the incumbent's coverage
COV91_EXPLORE_FOLDS = ("F0", "F1")        # §9.1 / §9.0 rule 2
COV91_CONFIRM_FOLDS = DECISION_FOLDS      # F2 + F3
# REAL_MONEY_TRACK §5: 5.0 + 5.0 fee + M3-4's measured pooled slippage. Printed beside the
# registered line for information; it decides nothing (§9.1, "Fee").
VERIFIED_TAKER_LINE_BPS = 11.842


def _cov91_folds(stage: str) -> tuple[str, ...]:
    if stage == "explore":
        return COV91_EXPLORE_FOLDS
    if stage == "confirm":
        return COV91_CONFIRM_FOLDS
    raise SystemExit(f"stage must be 'explore' or 'confirm', got {stage!r}")


def _cov91_load(folds: tuple[str, ...]) -> list[dumps.Dump]:
    """Only the stage's folds are read from disk — the other two are not loaded at all."""
    require_walkforward_era()
    wanted = {k: v for k, v in dumps.recorded_runs().items() if dumps.fold_of(k) in folds}
    missing = [k for k in dumps.WALKFORWARD_RUNS if dumps.fold_of(k) in folds
               and k not in wanted]
    if missing:
        raise SystemExit(f"§9.1 needs every seed of {', '.join(folds)}; missing {missing}")
    return [dumps.load(rid, seed=seed) for seed, rid in wanted.items()]


def coverage12_arms(d: dumps.Dump, spec: backtest.PolicySpec) -> dict:
    """Both §9.1 arms for ONE fold-seed, with the provenance the section asks to see."""
    from . import universe as _u   # local: universe imports backtest/metrics, not us
    h = d.at(240)
    conf = h["conf"].to_numpy(np.float64)
    present = set(h["pair"].unique())
    base8 = [p for p in dumps.BASE8 if p in present]
    extra = sorted(present - set(dumps.BASE8))
    cut12 = backtest.coverage_threshold(conf, COV91_COVERAGE)
    cut8 = backtest.coverage_threshold(
        h.loc[h["pair"].isin(base8), "conf"].to_numpy(np.float64), COV91_COVERAGE)
    regimes = {d.seed: regime.build(d.df)}

    # Arm A: the engine derives the cut over the fold-seed's whole population, as `m3 folds`.
    res12 = backtest.run([d], spec, regimes)
    if abs(res12.thresholds[d.seed] - cut12) > 1e-12:
        raise SystemExit(f"{d.seed}: engine cut {res12.thresholds[d.seed]!r} != {cut12!r}")
    # Self-check (§9.1, "regime ladder held fixed"): the fixed-threshold path must reproduce
    # the derived path exactly at the same cut, so arm B differs only in the cut's value.
    fixed_spec = _u.with_fields(spec, score_col="conf", score_min=cut12)
    chk = backtest.run([d], fixed_spec, regimes).trades
    if len(chk) != len(res12.trades) or not np.allclose(
            chk["signed_ret"].to_numpy(), res12.trades["signed_ret"].to_numpy()):
        raise SystemExit(f"{d.seed}: fixed-threshold path does not reproduce the derived path")
    # Arm B: the eight-pair cut, applied to every pair present.
    res8 = backtest.run([d], _u.with_fields(spec, score_col="conf", score_min=cut8), regimes)

    is_extra = h["pair"].isin(extra).to_numpy()
    return {
        "seed": d.seed, "fold": dumps.fold_of(d.seed),
        "pairs": len(present), "base8_present": len(base8), "extra": len(extra),
        "cut12": cut12, "cut8": cut8,
        "cov12": float((conf >= cut12).mean()),
        "cov8_on12": float((conf >= cut8).mean()),
        "cov8_on_extra": float((conf[is_extra] >= cut8).mean()) if is_extra.any() else np.nan,
        "trades12": res12.trades, "trades8": res8.trades,
    }


def _cov91_row(label: str, a: pd.DataFrame, b: pd.DataFrame, cost: float) -> dict:
    from . import universe as _u
    ca, cb = metrics.clustered_mean_bps(a, cost), metrics.clustered_mean_bps(b, cost)
    d = _u.paired_diff_bps(a, b, cost)
    return {"unit": label, "n12": ca["n"], "net12": ca["mean_bps"],
            "n8": cb["n"], "net8": cb["mean_bps"],
            "diff": d["diff_bps"], "lo95": d["lo95_bps"], "hi95": d["hi95_bps"],
            "clusters": d["clusters"]}


def _cov91_fmt(rows: list[dict]) -> str:
    t = pd.DataFrame(rows)
    t["95% CI of diff"] = [f"[{lo:+.2f}, {hi:+.2f}]" if np.isfinite(lo) else "n/a"
                           for lo, hi in zip(t["lo95"], t["hi95"])]
    t = t.drop(columns=["lo95", "hi95"])
    return t.to_string(index=False, float_format=lambda v: f"{v:+.2f}")


def coverage12_report(spec_fields: dict, stage: str, exploration_recorded: bool = False) -> int:
    """§9.1's table for one stage. `explore` = F0+F1, `confirm` = F2+F3 (once)."""
    folds = _cov91_folds(stage)
    print("=" * 96)
    print(f"§9.1 — SERVED COVERAGE AT TWELVE PAIRS — stage {stage.upper()} "
          f"({' + '.join(folds)})")
    print("=" * 96)
    print(registry_state())
    if stage == "confirm" and not exploration_recorded:
        print("\n🔴 refusing: --stage confirm reads F2+F3, the only untouched history. Pass")
        print("   --exploration-recorded only after the F0+F1 table is written into §9.1.")
        return 2
    if stage == "explore":
        print("\nF0 and F1 overlap history the policy search has read (§3, last bullet). This")
        print("stage spends nothing and decides nothing; a positive pooled point estimate")
        print("authorises ONE confirmation run on F2+F3 (§9.1).")
    else:
        print("\n🔴 F2 + F3 are being read for §9.1. This happens once.")

    spec = backtest.PolicySpec(label="incumbent SIZED", **spec_fields)
    print(f"\narms: A = cut derived over the fold-seed's full population (as `m3 folds`)")
    print(f"      B = cut derived over its dumps.BASE8 pairs, applied to every pair present")
    print(f"      both at coverage {COV91_COVERAGE}, same regime ladder, same seeds, same bars")
    print(f"diff = A − B; registered line taker {COST:.0f} bps; the verified "
          f"{VERIFIED_TAKER_LINE_BPS:.2f} line is printed for information only")

    ds = _cov91_load(folds)
    cards = []
    for d in ds:
        h = d.at(240)
        t = pd.to_datetime(h["ts"], unit="ns", utc=True)
        print(f"  {d.seed}  {d.run_id}  {len(h):>8,} bars  {h['pair'].nunique():>2} pairs  "
              f"{t.min():%Y-%m-%d} .. {t.max():%Y-%m-%d}")
        cards.append(coverage12_arms(d, spec))

    print("\n" + "=" * 96)
    print("A. THE CUTS AND THEIR REALIZED COVERAGE, PER FOLD-SEED (§9.1, 'reported with it')")
    print("=" * 96)
    prov = pd.DataFrame([{
        "seed": c["seed"], "pairs": c["pairs"], "base8": c["base8_present"],
        "cut A (12)": c["cut12"], "cut B (8)": c["cut8"],
        "cov A on 12": c["cov12"], "cov B on 12": c["cov8_on12"],
        "cov B on the 4 extra": c["cov8_on_extra"],
        "trades A": len(c["trades12"]), "trades B": len(c["trades8"]),
    } for c in cards])
    print(prov.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print("cut B is tighter than cut A when the eight carry higher confidence than the four")
    print("added pairs; the 'cov B on the 4 extra' column is the under-/over-trading of the")
    print("added pairs that an eight-pair cut produces.")

    print("\n" + "=" * 96)
    print(f"B. THE CONTRAST — net bps at taker {COST:.0f}, day-clustered, diff = A − B")
    print("=" * 96)
    rows = [_cov91_row(c["seed"], c["trades12"], c["trades8"], COST) for c in cards]
    for f in folds:
        cs = [c for c in cards if c["fold"] == f]
        rows.append(_cov91_row(f"{f} pooled", pd.concat([c["trades12"] for c in cs]),
                               pd.concat([c["trades8"] for c in cs]), COST))
    all12 = pd.concat([c["trades12"] for c in cards])
    all8 = pd.concat([c["trades8"] for c in cards])
    pooled = _cov91_row(f"{'+'.join(folds)} pooled", all12, all8, COST)
    rows.append(pooled)
    print(_cov91_fmt(rows))

    alt = _cov91_row(f"{'+'.join(folds)} pooled @ {VERIFIED_TAKER_LINE_BPS:.2f}", all12, all8,
                     VERIFIED_TAKER_LINE_BPS)
    print(f"\n   for information (decides nothing): at the verified line the pooled diff is "
          f"{alt['diff']:+.2f} [{alt['lo95']:+.2f}, {alt['hi95']:+.2f}]")

    print("\n" + "=" * 96)
    if stage == "explore":
        pos = pooled["diff"] > 0
        print(f"§9.1 EXPLORE READING: pooled F0+F1 point estimate {pooled['diff']:+.2f} bps "
              f"-> {'POSITIVE' if pos else 'NOT POSITIVE'}")
        print("=" * 96)
        if pos:
            print("  - §9.1 authorises ONE confirmation run on F2+F3. Write this table into §9.1")
            print("    first, then: m3 coverage12 --stage confirm --exploration-recorded")
        else:
            print("  - §9.1 closes here: F2/F3 are NOT read. Record the table and the closure.")
        return 0
    ok = bool(pooled["clusters"] >= 2 and pooled["lo95"] > 0)
    print(f"§9.1 VERDICT: {'CONFIRMED' if ok else 'NOT CONFIRMED'} — F2+F3 clustered 95% "
          f"lower bound of the difference {pooled['lo95']:+.2f} ({'>' if ok else '<='} 0)")
    print("=" * 96)
    if ok:
        print("  - A cut derived over the served population beats one derived over eight and")
        print("    applied to twelve, on untouched history. That is the evidence the parked")
        print("    'Re-pre-register the served coverage' item (BACKLOG) was waiting for; the")
        print("    re-registration itself is still a document written before anything is scored.")
    else:
        print("  - Not confirmed on untouched history. The served eight-derived cut stands; the")
        print("    point estimate and interval above are the record, not a negative result.")
    return 0


# --------------------------------------------------------------------------------------
# §9.2 — the hour-of-day probe (WALKFORWARD_PROTOCOL §4.3 item 3, registered in §9.2 on
# 2026-09-09; the choice rule and the rest were fixed there on 2026-09-10 before the first
# run). Every constant below is the registration's.
#
# THE SHAPE. `explore` runs the incumbent unrestricted on F0+F1, ranks the 24 UTC entry
# hours by mean net, and takes hours from the top until >= 60% of trades are kept. That set
# is written into §9.2 by the reader. `confirm` takes the set ONLY from --hours, so the
# document, not a recomputation, is what is confirmed on F2+F3 — once.
# --------------------------------------------------------------------------------------

HOD_RETENTION_FLOOR = 0.60          # §9.2: the filter must keep >= 60% of trades
HOD_EXPLORE_FOLDS = COV91_EXPLORE_FOLDS
HOD_CONFIRM_FOLDS = DECISION_FOLDS


def _hod_hours(trades: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(trades["entry_ts"], unit="ns", utc=True).dt.hour


def hod_hour_table(trades: pd.DataFrame, cost: float = COST) -> pd.DataFrame:
    """Per UTC entry hour: trades, share, mean net at `cost`. The ranking input of §9.2."""
    net = (trades["signed_ret"] - cost / metrics.BPS * trades.get("size", 1.0)) * metrics.BPS
    t = pd.DataFrame({"hour": _hod_hours(trades).to_numpy(), "net": net.to_numpy()})
    g = t.groupby("hour")["net"].agg(["size", "mean"]).reindex(range(24), fill_value=0)
    g.columns = ["trades", "net_bps"]
    g["net_bps"] = g["net_bps"].where(g["trades"] > 0, np.nan)
    g["share"] = g["trades"] / max(len(t), 1)
    return g


def hod_choose(tbl: pd.DataFrame, floor: float = HOD_RETENTION_FLOOR) -> tuple[int, ...]:
    """§9.2's choice rule: hours in descending mean net until cumulative share >= floor."""
    ranked = tbl.dropna(subset=["net_bps"]).sort_values("net_bps", ascending=False)
    chosen, cum = [], 0.0
    for hour, row in ranked.iterrows():
        chosen.append(int(hour))
        cum += float(row["share"])
        if cum >= floor:
            break
    return tuple(sorted(chosen))


def _hod_arms(d: dumps.Dump, spec: backtest.PolicySpec,
              hours: tuple[int, ...] | None) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    from . import universe as _u
    regimes = {d.seed: regime.build(d.df)}
    free = backtest.run([d], spec, regimes).trades
    if hours is None:
        return free, None
    kept = backtest.run([d], _u.with_fields(spec, entry_hours=tuple(hours)), regimes).trades
    return free, kept


def hourofday_report(spec_fields: dict, stage: str, exploration_recorded: bool = False,
                     hours: tuple[int, ...] | None = None) -> int:
    """§9.2. `explore` chooses the hour set on F0+F1; `confirm` tests --hours on F2+F3."""
    folds = HOD_EXPLORE_FOLDS if stage == "explore" else HOD_CONFIRM_FOLDS
    print("=" * 96)
    print(f"§9.2 — THE HOUR-OF-DAY PROBE — stage {stage.upper()} ({' + '.join(folds)})")
    print("=" * 96)
    print(registry_state())
    if stage == "confirm":
        if not exploration_recorded:
            print("\n🔴 refusing: --stage confirm reads F2+F3. Pass --exploration-recorded only")
            print("   after the chosen hour set is written into §9.2.")
            return 2
        if not hours:
            print("\n🔴 refusing: --stage confirm takes the hour set from --hours, transcribed")
            print("   from §9.2. It never recomputes it.")
            return 2
        print(f"\n🔴 F2 + F3 are being read for §9.2. This happens once. Hour set under test "
              f"(from --hours): {list(hours)}")
    else:
        print("\nF0 and F1 overlap history the search has read (§3, last bullet). This stage")
        print("chooses the hour set by §9.2's rule and decides nothing; its contrast is")
        print("in-sample by construction.")

    spec = backtest.PolicySpec(label="incumbent SIZED", **spec_fields)
    print(f"\narms: unrestricted = the incumbent as `m3 folds` scores it")
    print(f"      restricted   = same cut, entries kept only in the hour set, re-simulated")
    print(f"diff = restricted − unrestricted; taker {COST:.0f} bps decides; "
          f"{VERIFIED_TAKER_LINE_BPS:.2f} printed for information")

    ds = _cov91_load(folds)
    for d in ds:
        h = d.at(240)
        t = pd.to_datetime(h["ts"], unit="ns", utc=True)
        print(f"  {d.seed}  {d.run_id}  {len(h):>8,} bars  {h['pair'].nunique():>2} pairs  "
              f"{t.min():%Y-%m-%d} .. {t.max():%Y-%m-%d}")

    if stage == "explore":
        free = {d.seed: _hod_arms(d, spec, None)[0] for d in ds}
        pooled_free = pd.concat(free.values())
        print("\n" + "=" * 96)
        print(f"A. THE 24 UTC ENTRY HOURS, F0+F1 UNRESTRICTED, POOLED OVER SIX SEEDS "
              f"(n={len(pooled_free):,})")
        print("=" * 96)
        tbl = hod_hour_table(pooled_free)
        show = tbl.copy()
        show["rank"] = show["net_bps"].rank(ascending=False, method="first").astype("Int64")
        print(show.to_string(float_format=lambda v: f"{v:+.2f}"))
        hours = hod_choose(tbl)
        share = float(tbl.loc[list(hours), "share"].sum())
        print("\n" + "=" * 96)
        print(f"B. §9.2's CHOICE RULE -> hour set {list(hours)}  ({len(hours)} hours, "
              f"{share:.1%} of F0+F1 unrestricted trades)")
        print("=" * 96)
        print("🔴 Write this set into WALKFORWARD_PROTOCOL §9.2 before anything else is run.")
        kept = {d.seed: _hod_arms(d, spec, hours)[1] for d in ds}
    else:
        free, kept = {}, {}
        for d in ds:
            free[d.seed], kept[d.seed] = _hod_arms(d, spec, hours)

    print("\n" + "=" * 96)
    print(f"C. THE CONTRAST — net bps at taker {COST:.0f}, day-clustered, "
          f"diff = restricted − unrestricted")
    print("=" * 96)
    rows = []
    for d in ds:
        r = _cov91_row(d.seed, kept[d.seed], free[d.seed], COST)
        rows.append(r)
    for f in folds:
        seeds = [d.seed for d in ds if dumps.fold_of(d.seed) == f]
        rows.append(_cov91_row(f"{f} pooled", pd.concat([kept[s] for s in seeds]),
                               pd.concat([free[s] for s in seeds]), COST))
    all_kept, all_free = pd.concat(kept.values()), pd.concat(free.values())
    pooled = _cov91_row(f"{'+'.join(folds)} pooled", all_kept, all_free, COST)
    rows.append(pooled)
    out = _cov91_fmt(rows).replace("n12", "n_restr").replace("net12", "net_restr") \
                          .replace(" n8 ", " n_free ").replace("net8", "net_free")
    print(out)
    retention = len(all_kept) / max(len(all_free), 1)
    alt = _cov91_row("alt", all_kept, all_free, VERIFIED_TAKER_LINE_BPS)
    print(f"\n   retention (re-simulated): {len(all_kept):,} / {len(all_free):,} = "
          f"{retention:.1%}  (floor {HOD_RETENTION_FLOOR:.0%})")
    print(f"   for information: at the verified line the pooled diff is {alt['diff']:+.2f} "
          f"[{alt['lo95']:+.2f}, {alt['hi95']:+.2f}]")
    se = (pooled["hi95"] - pooled["lo95"]) / (2 * 1.96)
    print(f"   clustered SE of the difference {se:.2f} bps -> minimum detectable effect "
          f"(1.96 × SE) {1.96 * se:.2f} bps"
          + (" — a FORECAST for F2+F3, from F0+F1" if stage == "explore" else ""))

    print("\n" + "=" * 96)
    if stage == "explore":
        print(f"§9.2 EXPLORE: hour set {list(hours)} chosen; in-sample diff {pooled['diff']:+.2f} "
              f"bps (decides nothing).")
        print("=" * 96)
        print("  - Record section A, the set and section C in §9.2, then run ONCE:")
        print(f"    m3 hourofday --stage confirm --exploration-recorded "
              f"--hours {','.join(str(h) for h in hours)}")
        return 0
    ok_lb = bool(pooled["clusters"] >= 2 and pooled["lo95"] > 0)
    ok_ret = retention >= HOD_RETENTION_FLOOR
    ok = ok_lb and ok_ret
    print(f"§9.2 VERDICT: {'CONFIRMED' if ok else 'NOT CONFIRMED'} — lower bound "
          f"{pooled['lo95']:+.2f} ({'>' if ok_lb else '<='} 0); retention {retention:.1%} "
          f"({'>=' if ok_ret else '<'} {HOD_RETENTION_FLOOR:.0%})")
    print("=" * 96)
    if not ok:
        print(f"  - Read against the MDE above: an hour effect smaller than {1.96 * se:.1f} bps")
        print("    per trade could not have been confirmed by this test. Not a negative result.")
    return 0
