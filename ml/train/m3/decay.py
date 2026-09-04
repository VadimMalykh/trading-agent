"""Phase 2 of the retrain plan — is the model's edge decaying with distance from training?

THE QUESTION. Train ends ~2025-12-10, so w1..w4 is not only a regime axis, it is also a
*months-past-the-train-boundary* axis (RETRAIN_PLAN §1). M3-2's grid winner is worst in w4,
the newest window, which is the shape decay predicts — but w4 is also where the
partial-candle defect lived, so decay and the defect were perfectly confounded. The repair
plus the Phase 1 re-scoring separates them, and this module is that reading.

🔴 THE SECOND CONFOUND, WHICH RETRAIN_PLAN §5 DID NOT ANTICIPATE. The two eras are not the
same calendar rows. The split is a fraction of a growing history, so re-dumping two weeks
later moved BOTH edges: w1 lost its first twelve days and w4 gained sixteen. w2 and w3 are
bar-for-bar identical; w1 and w4 — the two windows the whole question is about — are not.
A raw before/after on w4 therefore mixes three things:

    (repaired candles) + (sixteen extra days of newer market) + (whatever decay there is)

So every table here is reported twice: over each era's own full window, and over
`dumps.REPAIR_OVERLAP`, the calendar span both eras cover. Only the clipped one is a
before/after comparison; the full one is what each era actually looks like.

WHAT IS CLIPPED, AND WHAT IS NOT. Each era's backtest runs over its own complete dump, so
its coverage cut is derived from the population it would really be derived from; the
restriction to the overlap is applied to the resulting *trades*, by entry bar. The residual
difference — that the two eras derive their cut over slightly different populations — is
not removed, so the cuts are printed alongside the table rather than hidden.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import backtest, dumps, metrics, regime

WINDOW_NAMES = ("w1", "w2", "w3", "w4")

# RETRAIN_PLAN §1: what each window is on the distance-from-training axis. Printed with
# every table so the decay reading is never left implicit.
MONTHS_PAST_BOUNDARY = {"w1": "0.0-1.7", "w2": "1.7-3.7", "w3": "3.7-5.7", "w4": "5.7-8.7"}


def _load(era: str) -> list[dumps.Dump]:
    return [dumps.load(run_id, seed=seed, pairs=dumps.BASE8)
            for seed, run_id in dumps.RUNS_BY_ERA[era].items()]


def _run(ds: list[dumps.Dump], spec: backtest.PolicySpec) -> backtest.Result:
    regimes = {d.seed: regime.build(d.df) for d in ds} if spec.regime_col else None
    return backtest.run(ds, spec, regimes)


def window_table(trades: pd.DataFrame, cost: float) -> pd.DataFrame:
    """Per-window net bps with a day-clustered interval and the counts §5 demands.

    §5's power check is not optional garnish: w4's trade count *rises* after the repair (the
    defect suppressed confidence, hence the bars clearing a fixed-coverage cut), so a w4
    that looks different may only be a w4 that is bigger. Counts and clusters are therefore
    columns, not a footnote.
    """
    t = dumps.add_window(trades, ts_col="entry_ts")
    rows = []
    for name in WINDOW_NAMES:
        sub = t[t["window"] == name]
        c = metrics.clustered_mean_bps(sub, cost)
        ts = pd.to_datetime(sub["entry_ts"], unit="ns", utc=True) if len(sub) else None
        rows.append({
            "window": name,
            "months_past": MONTHS_PAST_BOUNDARY[name],
            "trades": c["n"],
            "clusters": c["clusters"],
            "gross_bps": float(sub["signed_ret"].mean() * metrics.BPS) if len(sub) else np.nan,
            "net_bps": c["mean_bps"] if c["n"] else np.nan,
            "lo95": c["lo95_bps"],
            "hi95": c["hi95_bps"],
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


def verdict(tbl: pd.DataFrame) -> tuple[str, list[str]]:
    """RETRAIN_PLAN §5's reading, applied to the repaired w1..w4 table.

    Written to follow the pre-registered table rather than to reach a conclusion: the three
    readings and the power check are exactly §5's, evaluated in the order §5 states them.
    The power check runs FIRST and can veto, because §5 requires a criterion to be shown to
    have the power to decide before it is allowed to decide.
    """
    notes = []
    t = tbl.set_index("window")
    net = t["net_bps"]
    w4 = net["w4"]
    others = net[["w1", "w2", "w3"]]

    # Power check (§5): can this table distinguish w4 from the rest at all?
    lo, hi = t.loc["w4", "lo95"], t.loc["w4", "hi95"]
    spanned = [w for w in ("w1", "w2", "w3") if lo <= net[w] <= hi]
    notes.append(f"w4's 95% CI is [{lo:+.1f}, {hi:+.1f}] and contains the mean of "
                 f"{', '.join(spanned) if spanned else 'no other window'}.")
    if len(spanned) == 3:
        notes.append("It contains ALL THREE other windows' means, so no ordering of the "
                     "windows is resolvable at this sample size.")
        return "NOT DECIDABLE", notes

    if w4 >= others.min():
        notes.append(f"w4 ({w4:+.1f}) is not the worst window — {others.idxmin()} is "
                     f"({others.min():+.1f}). §5's first row: w4's weakness was the defect.")
        return "NO DECAY EVIDENCE — do not run Phase 3", notes

    monotone = bool(net["w1"] >= net["w2"] >= net["w3"] >= net["w4"])
    notes.append(f"w4 ({w4:+.1f}) is the worst window; the w1->w4 sequence is "
                 f"{' '.join(f'{v:+.1f}' for v in net)}, which is "
                 f"{'monotone' if monotone else 'NOT monotone'}.")
    if monotone:
        return "DECAY PLAUSIBLE — run Phase 3", notes
    return "REGIME, NOT DISTANCE — Phase 3 optional, low priority", notes


# §6's own resolution estimate for the fresh family: a ~120-day holdout yields ~282 cov-2%
# trades per seed and "degrades §2's +/-37 bps resolution to roughly +/-54 bps". That figure
# is for the fresh family's WHOLE split; its w4-restricted slice is a subset and so can only
# be less precise. It is therefore used below as a LOWER BOUND on the fresh family's SE.
PHASE3_HALFWIDTH_BPS = 54.0

# 1.96 (two-sided 95%) + 0.84 (80% power) — the usual MDE constant for a difference in means.
MDE_Z = 2.80


def phase3_power(tbl: pd.DataFrame, pooled_net_bps: float) -> list[str]:
    """What Phase 3's pre-registered gate would have to clear, given w4's actual precision.

    §6 gates Phase 3 on "the fresh family's w4 net-at-taker beats the stale family's w4 by a
    margin exceeding the between-seed spread". That comparison is two estimates of a w4 mean
    differenced, so its precision is bounded below by the precision of the w4 mean we can
    already measure. This is the arithmetic that says whether three GPU runs can answer the
    question at all — asked before spending them, which is the whole point of §5's power
    check, and the reason that check is written to be able to veto.
    """
    w4 = tbl.set_index("window").loc["w4"]
    se_stale = (w4["hi95"] - w4["lo95"]) / (2 * 1.96)
    se_fresh = PHASE3_HALFWIDTH_BPS / 1.96
    se_diff = float(np.sqrt(se_stale ** 2 + se_fresh ** 2))
    mde = MDE_Z * se_diff
    return [
        f"this family's w4 has a day-clustered SE of {se_stale:.1f} bps/trade "
        f"({w4['trades']:,} trades in {w4['clusters']} day-clusters).",
        f"§6 prices the fresh family's whole split at +/-{PHASE3_HALFWIDTH_BPS:.0f} bps, i.e. "
        f"SE >= {se_fresh:.1f} bps; its w4 slice is a subset, so that is a LOWER bound.",
        f"Differencing the two gives SE >= {se_diff:.1f} bps, so §6's gate can only resolve a "
        f"freshness effect larger than ~{mde:.0f} bps/trade (95% two-sided, 80% power).",
        f"This policy's entire pooled edge is {pooled_net_bps:+.1f} bps/trade — "
        f"{mde / abs(pooled_net_bps):.0f}x smaller than the smallest effect the design can "
        f"see. Phase 3 AS WRITTEN returns NOT DECIDABLE whatever the truth is.",
    ]


def report(specs: dict[str, backtest.PolicySpec], cost: float = metrics.TAKER_COST_BPS) -> None:
    eras = ("prerepair", "repaired")
    loaded = {e: _load(e) for e in eras}

    print("=" * 96)
    print("PHASE 2 — THE DECAY CURVE (RETRAIN_PLAN §5)")
    print("=" * 96)
    print(f"cost line: taker {cost:.0f} bps round trip; intervals are day-clustered "
          f"(metrics.clustered_mean_bps)")
    print("\nthe two eras are not the same calendar rows -----------------------------------")
    for era in eras:
        for d in loaded[era]:
            h = d.at(240)
            ts = pd.to_datetime(h["ts"], unit="ns", utc=True)
            print(f"  {era:<10} {d.seed}  {d.run_id}  {len(h):>8,} bars  "
                  f"{ts.min():%Y-%m-%d} .. {ts.max():%Y-%m-%d}")
    print(f"  shared span (dumps.REPAIR_OVERLAP): {dumps.REPAIR_OVERLAP[0]} .. "
          f"{dumps.REPAIR_OVERLAP[1]}")

    for label, spec in specs.items():
        print("\n" + "=" * 96)
        print(f"POLICY: {label}")
        print(f"  {spec}")
        print("=" * 96)

        results = {e: _run(loaded[e], spec) for e in eras}
        for era in eras:
            cuts = ", ".join(f"{k}={v:.4f}" for k, v in results[era].thresholds.items())
            print(f"  {era:<10} coverage cut per seed: {cuts}")

        for clip in (False, True):
            tag = ("B. RESTRICTED TO THE SHARED SPAN — this is the before/after"
                   if clip else "A. EACH ERA OVER ITS OWN FULL WINDOW — not a comparison")
            print(f"\n--- {tag} " + "-" * max(0, 60 - len(tag)))
            tables = {}
            for era in eras:
                tr = results[era].trades
                if clip:
                    tr = dumps.clip_overlap(tr, ts_col="entry_ts")
                tables[era] = window_table(tr, cost)
                print(f"\n  [{era}]  n={len(tr):,}  pooled net={tr.pipe(metrics.clustered_mean_bps, cost)['mean_bps']:+.2f} bps")
                print("  " + _fmt(tables[era]).replace("\n", "\n  "))

            if clip:
                d = tables["repaired"].set_index("window")
                p = tables["prerepair"].set_index("window")
                print(f"\n  delta (repaired - prerepair), same calendar span:")
                print(f"  {'window':<8}{'net bps pre':>14}{'net bps post':>14}{'delta':>10}"
                      f"{'trades pre':>12}{'trades post':>13}{'CIs overlap':>13}")
                for w in WINDOW_NAMES:
                    overlap = not (p.loc[w, "hi95"] < d.loc[w, "lo95"]
                                   or d.loc[w, "hi95"] < p.loc[w, "lo95"])
                    print(f"  {w:<8}{p.loc[w, 'net_bps']:>+14.2f}{d.loc[w, 'net_bps']:>+14.2f}"
                          f"{d.loc[w, 'net_bps'] - p.loc[w, 'net_bps']:>+10.2f}"
                          f"{p.loc[w, 'trades']:>12,}{d.loc[w, 'trades']:>13,}"
                          f"{'yes' if overlap else 'NO':>13}")
                print("  (a delta whose CIs overlap is not a measured change; with three "
                      "seeds over one\n   market these intervals are wide by construction, "
                      "which is the finding, not a caveat)")

        print(f"\n--- §5's PRE-REGISTERED READING, on the repaired era " + "-" * 22)
        for scope, tbl in (("full window", window_table(results["repaired"].trades, cost)),
                           ("shared span", window_table(
                               dumps.clip_overlap(results["repaired"].trades, ts_col="entry_ts"),
                               cost))):
            v, notes = verdict(tbl)
            print(f"\n  [{scope}] VERDICT: {v}")
            for n in notes:
                print(f"    - {n}")
            if scope == "shared span":
                pooled = metrics.clustered_mean_bps(
                    dumps.clip_overlap(results["repaired"].trades, ts_col="entry_ts"), cost
                )["mean_bps"]
                print(f"\n  [{scope}] WHAT PHASE 3 WOULD NEED (§6's gate, priced):")
                for n in phase3_power(tbl, pooled):
                    print(f"    - {n}")
