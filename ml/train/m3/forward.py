"""The pre-registered readings of the forward paper ledger — M3_5_INTEGRATION.md §4.3.

WHY THIS EXISTS. The forward test is the only thing that manufactures new independent
trading days, and every offline question that was parked as "needs untouched data" — the
coverage cut level, the regime split, the hour-of-day set, the size ladder — can be read off
the same ledger as a SUBSET or SPLIT of the trades already taken. No new arm is needed for
any of them, because a tighter cut selects a subset of the bars the 0.02 cut already trades
and every row records its confidence, regime value and entry hour. What makes such a reading
legitimate under M3_PROTOCOL §0 is that the subsets, the constants and the statistics were
fixed BEFORE the ledger held enough trades to suggest them. That is what §4.3 does, and this
module is its executable form: nothing here is a parameter — every constant is transcribed
from the registration, and the registration says the values come from here.

WHAT IT READS. A CSV export of `paper_trades` (both arms, all columns):

    \\copy (select * from paper_trades order by id) to stdout with csv header

Only `status = 'closed'` rows enter any statistic. Open rows are counted and ignored.

THE UNIT. `net_bps` in the ledger is size-weighted (the policy arm's rows carry
size × (gross − cost)), so per-trade means on that arm are flattered by exactly the thing
the A/B tests. Every reading here is therefore stated in net bps **per unit of notional**:
for a set of trades that is Σ net_bps / Σ size, which on the flat arm is the plain mean and
on the policy arm is the size-weighted mean. §4.1 already says this; this module enforces it.

THE INTERVALS. Trades are clustered on the UTC **entry** day — the same calendar day, any
pair, any arm, is one cluster — because a 4h hold on twelve correlated perpetuals during one
BTC move is one bet expressed twelve times (metrics.clustered_mean_bps says why). Contrasts
between two subsets are day-bootstrapped: days are drawn with replacement from the union of
both subsets' days and both means are recomputed on the same draw (universe.bootstrap_diff_se
does the same for the folds). The draw count and seed are fixed so a table is reproducible
to the digit.

WHAT IT NEVER DOES. It changes nothing served. A reading that "passes" licenses a
pre-registration of a served change, written on its own population; it is not one.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

Z = 1.96
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20260913          # the registration date; fixed so tables reproduce

# --- the constants, transcribed from M3_5_INTEGRATION.md §4.3 -------------------------
#
# The coverage cuts are `backtest.coverage_threshold(conf, c)` over the served checkpoint's
# own split (repaired era, seed s2, the eight training pairs, horizon 240), derived on
# 2026-09-13 with the ledger at 7 signal bars — the 0.02 entry reproduces the served
# `Policy.frozen_threshold/0` to the digit, which is the check that the population is right.
CUTS = {
    0.02:    0.6296127438545227,   # the served cut — the full policy arm
    0.015:   0.6431580185890198,
    0.01288: 0.6498615741729736,   # T6's count-matched coverage on twelve pairs
    0.01:    0.6610917448997498,
}
SERVED_COVERAGE = 0.02

# The frozen ladder (`Policy.frozen_regime_edges/0`); p80 is its last edge. The ledger's
# `ladder_p80` column carries the same number on every row and is checked against it.
LADDER_EDGES = [0.003956599626690149, 0.00888611190021038,
                0.015089680440723896, 0.025596268475055695]
LADDER_P80 = LADDER_EDGES[-1]

# WALKFORWARD_PROTOCOL §9.2's recorded hour set (UTC entry hour), chosen on F0+F1 and NOT
# confirmed on F2+F3. The forward ledger is the "larger untouched sample against the same
# recorded set" that §9.2 named as the only way to revive it.
HOUR_SET = {0, 1, 2, 3, 4, 5, 7, 9, 10, 11, 12, 13, 14, 18, 21, 22}

# §4.3's reading schedule: the first reading at this many closed policy-arm trades, then at
# every further multiple. Readings before the first are printed as TEXTURE, never quoted.
READ_AT = 50

ARM_POLICY, ARM_FLAT = "policy", "flat_size"


# ---------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------

@dataclass
class Ledger:
    closed: pd.DataFrame       # both arms, closed rows only
    n_open: int
    n_rows: int

    def arm(self, name: str) -> pd.DataFrame:
        return self.closed[self.closed["arm"] == name]


def load(path: str) -> Ledger:
    df = pd.read_csv(path)
    for c in ("entry_ts", "exit_ts"):
        df[c] = pd.to_datetime(df[c], utc=True)
    closed = df[df["status"] == "closed"].copy()
    closed["per_notional"] = closed["net_bps"] / closed["size"]
    closed["day"] = closed["entry_ts"].dt.floor("D")
    closed["hour"] = closed["entry_ts"].dt.hour
    return Ledger(closed=closed, n_open=int((df["status"] == "open").sum()), n_rows=len(df))


def check(led: Ledger) -> list[str]:
    """Consistency checks a reading must not proceed past. Returns the problems found."""
    problems = []
    c = led.closed
    if c.empty:
        return ["no closed rows"]
    bad_p80 = c[~np.isclose(c["ladder_p80"], LADDER_P80)]
    if len(bad_p80):
        problems.append(f"{len(bad_p80)} rows carry a ladder_p80 != {LADDER_P80}")
    bad_thr = c[~np.isclose(c["threshold"], CUTS[SERVED_COVERAGE])]
    if len(bad_thr):
        problems.append(f"{len(bad_thr)} rows carry a threshold != the served cut")
    below = c[c["confidence"] < CUTS[SERVED_COVERAGE]]
    if len(below):
        problems.append(f"{len(below)} rows entered below the served cut")
    if c["checkpoint"].nunique() > 1:
        problems.append(f"{c['checkpoint'].nunique()} distinct checkpoints in the ledger")
    return problems


# ---------------------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------------------

def per_notional(t: pd.DataFrame) -> float:
    return float(t["net_bps"].sum() / t["size"].sum()) if len(t) else float("nan")


def clustered(t: pd.DataFrame) -> dict:
    """Net bps per unit of notional with a day-clustered (CRVE) interval.

    The estimator is the size-weighted mean m = Σ w_i x_i / Σ w_i with w = size and
    x = per-notional net; its cluster-robust variance is Σ_g (Σ_{i∈g} w_i (x_i − m))² / (Σ w)²
    with the G/(G−1) correction. On the flat arm w ≡ 1 and this is the plain clustered mean.
    """
    n = len(t)
    if n == 0:
        return {"n": 0, "mean": float("nan"), "lo": float("nan"), "hi": float("nan"),
                "clusters": 0, "se": float("nan")}
    w = t["size"].to_numpy(np.float64)
    x = t["per_notional"].to_numpy(np.float64)
    m = float((w * x).sum() / w.sum())
    g = t["day"].to_numpy()
    days = np.unique(g)
    G = days.size
    resid = w * (x - m)
    s = np.array([resid[g == d].sum() for d in days])
    var = (s ** 2).sum() / (w.sum() ** 2)
    if G > 1:
        var *= G / (G - 1)
    se = float(np.sqrt(var)) if G > 1 else float("nan")   # one cluster: no interval exists
    return {"n": n, "mean": m, "lo": m - Z * se, "hi": m + Z * se, "clusters": int(G),
            "se": se, "win": float((x > 0).mean())}


def bootstrap_contrast(a: pd.DataFrame, b: pd.DataFrame,
                       draws: int = BOOTSTRAP_DRAWS, seed: int = BOOTSTRAP_SEED) -> dict:
    """Day-bootstrap of per_notional(a) − per_notional(b). Days are drawn from the union of
    both subsets' entry days; both are recomputed on the same draw (the paired quantity)."""
    if a.empty or b.empty:
        return {"diff": float("nan"), "lo": float("nan"), "hi": float("nan"), "draws": 0}
    diff = per_notional(a) - per_notional(b)
    da, db = a["day"].to_numpy(), b["day"].to_numpy()
    wa, xa = a["size"].to_numpy(np.float64), a["net_bps"].to_numpy(np.float64)
    wb, xb = b["size"].to_numpy(np.float64), b["net_bps"].to_numpy(np.float64)
    days = np.array(sorted(set(da) | set(db)))
    if days.size < 2:                       # one day: a day-bootstrap has nothing to resample
        return {"diff": diff, "lo": float("nan"), "hi": float("nan"), "draws": 0}
    ia = {d: np.flatnonzero(da == d) for d in days}
    ib = {d: np.flatnonzero(db == d) for d in days}
    rng = np.random.default_rng(seed)
    out = np.empty(draws)
    for k in range(draws):
        picked = days[rng.integers(0, days.size, days.size)]
        sa = np.concatenate([ia[d] for d in picked])
        sb = np.concatenate([ib[d] for d in picked])
        ma = xa[sa].sum() / wa[sa].sum() if sa.size else np.nan
        mb = xb[sb].sum() / wb[sb].sum() if sb.size else np.nan
        out[k] = ma - mb
    lo, hi = np.nanpercentile(out, [2.5, 97.5])
    return {"diff": diff, "lo": float(lo), "hi": float(hi), "draws": draws,
            "nan_draws": int(np.isnan(out).sum())}


def ladder_size(regime: float) -> float:
    """`Policy.size_multiplier/2`: bucket = count of edges <= value; size = (bucket+1)/3."""
    bucket = sum(1 for e in LADDER_EDGES if regime >= e)
    return (bucket + 1) / 3.0


# ---------------------------------------------------------------------------------------
# The readings
# ---------------------------------------------------------------------------------------

def _fmt(c: dict) -> str:
    if c["n"] == 0:
        return "n=0"
    return (f"n={c['n']:<4d} net/notional {c['mean']:+8.2f}  "
            f"[{c['lo']:+8.2f}, {c['hi']:+8.2f}]  days={c['clusters']}  win={c['win']:.2f}")


def _contrast_line(label: str, a: pd.DataFrame, b: pd.DataFrame) -> str:
    r = bootstrap_contrast(a, b)
    if r["draws"] == 0:
        d = "" if np.isnan(r["diff"]) else f" {r['diff']:+8.2f}, interval undefined"
        return f"  {label}:{d} (one side empty or a single entry day)"
    return (f"  {label}: {r['diff']:+8.2f}  95% [{r['lo']:+8.2f}, {r['hi']:+8.2f}]  "
            f"(day-bootstrap, {r['draws']} draws)")


def reading_arms(led: Ledger) -> None:
    """R0 — §4.1's A/B: does the size ladder earn more per unit of notional than flat size?"""
    p, f = led.arm(ARM_POLICY), led.arm(ARM_FLAT)
    print("\nR0  the A/B (§4.1) — policy (sized) vs flat_size, net bps per unit of notional")
    print(f"  policy    {_fmt(clustered(p))}")
    print(f"  flat_size {_fmt(clustered(f))}")
    print(_contrast_line("policy − flat_size", p, f))
    key = ["pair", "entry_ts"]
    m = p.merge(f, on=key, how="outer", suffixes=("_p", "_f"), indicator=True)
    only_p = int((m["_merge"] == "left_only").sum())
    only_f = int((m["_merge"] == "right_only").sum())
    print(f"  bars on both arms {int((m['_merge'] == 'both').sum())}, policy-only {only_p}, "
          f"flat-only {only_f}  (a non-zero flat-only count is R4's population)")


def reading_cut(led: Ledger) -> None:
    """R1 — the cut level: are the marginal trades between two cuts worth anything?

    For each tighter coverage c: TIGHT = policy-arm trades with confidence >= cut(c)
    (tie-inclusive, as the live rule is), MARGINAL = the rest of the arm. The number that
    answers the parked question is MARGINAL's own per-notional net and the contrast
    TIGHT − MARGINAL. A subset is a sub-sample, not a re-simulation: under serial-per-pair a
    freed pair could have taken a later bar, so a served tighter cut would not trade exactly
    TIGHT. That bias is second-order at these trade rates and is stated, not corrected.
    """
    p = led.arm(ARM_POLICY)
    print("\nR1  the cut level — policy arm split at tighter cuts (subset reading)")
    print(f"  served cov {SERVED_COVERAGE}: cut {CUTS[SERVED_COVERAGE]}   {_fmt(clustered(p))}")
    for c, cut in CUTS.items():
        if c == SERVED_COVERAGE:
            continue
        tight, marginal = p[p["confidence"] >= cut], p[p["confidence"] < cut]
        print(f"  cov {c:<8} cut {cut:.4f}")
        print(f"    tight     {_fmt(clustered(tight))}")
        print(f"    marginal  {_fmt(clustered(marginal))}")
        print(_contrast_line("  tight − marginal", tight, marginal))


def reading_regime(led: Ledger) -> None:
    """R2 — the regime split (BACKLOG row 7): top quintile of btc_absret_1d vs the rest."""
    p = led.arm(ARM_POLICY)
    top, rest = p[p["regime"] >= LADDER_P80], p[p["regime"] < LADDER_P80]
    print(f"\nR2  the regime split — entry regime >= frozen p80 {LADDER_P80:.6f} vs below")
    print(f"  top quintile {_fmt(clustered(top))}")
    print(f"  below        {_fmt(clustered(rest))}")
    print(_contrast_line("top − below", top, rest))
    counts = p["size"].round(4).value_counts().sort_index()
    print("  size rungs traded: " + ", ".join(f"{s:g}×{n}" for s, n in counts.items()))


def reading_hours(led: Ledger) -> None:
    """R3 — WALKFORWARD §9.2's hour set, as a subset reading on untouched data."""
    p = led.arm(ARM_POLICY)
    inside, outside = p[p["hour"].isin(HOUR_SET)], p[~p["hour"].isin(HOUR_SET)]
    print(f"\nR3  hour-of-day — §9.2's recorded set {sorted(HOUR_SET)} vs excluded hours")
    print(f"  in set   {_fmt(clustered(inside))}")
    print(f"  excluded {_fmt(clustered(outside))}")
    print(_contrast_line("in − excluded", inside, outside))


def reading_counterfactual(led: Ledger) -> None:
    """R4 — the daily-loss-limit counterfactual (M3_FIDELITY_RESULTS §4.2).

    The policy arm passes through RiskManager and the flat arm does not, so a bar the risk
    manager refused exists on the flat arm only. The refused policy trade is reconstructed
    from that flat row: same fill, size from the frozen ladder at the row's own regime value.
    The counterfactual policy arm is the recorded arm plus those rows; its per-notional net is
    the unbiased estimate §4.2 asked for. Flat-only rows that follow a refusal (the pair held on
    one arm and not the other until both are flat) are included as well — they are the same
    divergence and the same bias.
    """
    p, f = led.arm(ARM_POLICY), led.arm(ARM_FLAT)
    key = ["pair", "entry_ts"]
    missing = f.merge(p[key], on=key, how="left", indicator=True)
    missing = missing[missing["_merge"] == "left_only"].drop(columns="_merge").copy()
    print("\nR4  the loss-limit counterfactual — flat-arm rows with no policy-arm counterpart")
    if missing.empty:
        print("  none: the policy arm took every bar the flat arm took, so §4.2's bias is zero "
              "over this ledger")
        return
    missing["size"] = missing["regime"].map(ladder_size)
    missing["net_bps"] = missing["per_notional"] * missing["size"]
    cf = pd.concat([p, missing], ignore_index=True)
    print(f"  {len(missing)} suppressed policy trades reconstructed at ladder size")
    print(f"  recorded policy arm       {_fmt(clustered(p))}")
    print(f"  counterfactual policy arm {_fmt(clustered(cf))}")
    print(f"  the suppressed rows alone {_fmt(clustered(missing))}")


# ---------------------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------------------

def run(path: str) -> int:
    led = load(path)
    p = led.arm(ARM_POLICY)
    n_policy = len(p)
    print(f"FORWARD LEDGER READINGS — M3_5_INTEGRATION §4.3   ({path})")
    print(f"rows {led.n_rows}, closed {len(led.closed)}, open {led.n_open}; "
          f"policy-arm closed trades {n_policy}")
    if n_policy:
        print(f"entry span {p['entry_ts'].min():%Y-%m-%d %H:%M} -> "
              f"{p['entry_ts'].max():%Y-%m-%d %H:%M} UTC, {p['day'].nunique()} entry days")
    problems = check(led)
    if problems:
        print("\nCONSISTENCY FAILED — do not read the tables below:")
        for x in problems:
            print(f"  - {x}")
        return 2
    print("consistency: ok (one checkpoint, served cut and ladder on every row)")
    if n_policy < READ_AT:
        print(f"\n⚠️  TEXTURE ONLY: {n_policy} < {READ_AT} closed policy trades. §4.3's first "
              f"reading is at {READ_AT}; nothing below may be quoted as a result.")
    else:
        k = n_policy // READ_AT
        print(f"\nreading #{k} of the schedule (every {READ_AT} closed policy trades)")
    reading_arms(led)
    reading_cut(led)
    reading_regime(led)
    reading_hours(led)
    reading_counterfactual(led)
    print("\nEvery interval above is day-clustered on the UTC entry day. Per-trade sd on this "
          "policy offline is ~259 bps; ~290 trades resolve a +30 bps mean against zero.")
    return 0


def add_parser(sub) -> None:
    ap = sub.add_parser("forward", help="M3_5_INTEGRATION §4.3: the pre-registered readings "
                        "of the forward paper ledger — the A/B, the cut level, the regime "
                        "split, the hour set and the loss-limit counterfactual, all as "
                        "subsets of the same trades. Changes nothing served.")
    ap.add_argument("--ledger", required=True,
                    help="CSV export of paper_trades (both arms, all columns), container path "
                         "e.g. output/forward/paper_trades_<date>.csv")
    ap.set_defaults(fn=lambda args: run(args.ledger))
