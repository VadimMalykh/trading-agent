"""Loading and pooling the per-seed `eval_preds.parquet` dumps.

WHY POOLING MATTERS. A single seed's cov05 slice is ~1,200 trades with a per-trade sd of
259bps, which is not enough to distinguish policies that differ by less than ~15bps. The
three 5m/seq384 seeds are independently initialised models over the *same* validation
window, so pooling them triples the trade count while also acting as a replication check:
NEXT_TRAINING_PLAN §1.8's regime finding is credible precisely because all three seeds
agree. Every table in M3 therefore reports per-seed columns next to the pooled number.

Pooling is a *concatenation with the seed carried as a key*, never a merge: two seeds may
gate the same bar, and those are two independent observations of the same market moment,
not one. All position bookkeeping is keyed on (seed, pair) for the same reason — one seed's
open position must not block another seed's entry.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd

# The dumps M3 works from. Run ids are the eval run, and the `seed` label is the one
# NEXT_TRAINING_PLAN §1.3 uses when it prints per-seed columns (s1/s2/s3).
#
# Seed 2 is the *served* checkpoint — m2_multi_20260819T142759Z_a186182b.pt at gate 0.6311.
# When a policy has to be chosen for deployment it is chosen on that seed; the other two
# exist to show the choice was not seed luck. The `s2` entry of BOTH eras below is that
# same checkpoint: the eras differ in the candles it was scored against, not in the model.
#
# --- The two eras of the same three checkpoints ---------------------------------------
#
# The 2026-08-31 partial-candle defect (docs/CANDLE_POLL_DEFECT.md) corrupted the newest
# months of the validation window. The repair was verified 36/36 and the same three
# checkpoints were then re-scored (docs/RETRAIN_PLAN.md §4). Both scorings are kept:
#
#   prerepair — what every published M3 number was measured on. Keeping it reachable is
#               what lets `m3 validate` stay a reproduction test rather than becoming a
#               claim about data nobody can load any more.
#   repaired  — the same checkpoints and the same eval code over repaired candles.
#
# 🔴 THEY ARE NOT THE SAME CALENDAR ROWS. The split is a fraction of a growing history, so
# re-dumping two weeks later moved BOTH edges: val now starts 2025-12-22 rather than
# ~2025-12-10 (w1 loses ~24% of its bars) and ends 2026-09-03 rather than ~2026-08-18 (w4
# gains ~21%). w2 and w3 are bar-for-bar identical; w1 and w4 are not. Any before/after
# comparison that does not restrict to REPAIR_OVERLAP is comparing three changes at once.
RUNS_BY_ERA = {
    "prerepair": {
        "s1": "20260818T185438Z",
        "s2": "20260819T142759Z",
        "s3": "20260820T025723Z",
    },
    "repaired": {
        "s1": "20260904T061948Z",
        "s2": "20260904T051921Z",
        "s3": "20260904T073714Z",
    },
}

# --- the third era: the walk-forward folds ---------------------------------------------
# WALKFORWARD_PROTOCOL.md's twelve runs. Not three seeds over one split but four splits of
# three seeds each, so the label carries both: "F2s1" is fold F2, seed 1. Everything
# downstream keys on `seed`, and `fold_of()` recovers the fold from the label, so the pooling
# machinery (concatenate, carry the key, never merge) is reused unchanged — with one
# difference that matters: two seeds of the SAME fold see the same market moment and cluster
# together, while two folds do not overlap in calendar at all.
#
# --------------------------------------------------------------------------------------
# The walk-forward fold registry (WALKFORWARD_PROTOCOL.md §6's record, in code).
#
# WHY IT IS A TABLE OF `None`s RATHER THAN AN EMPTY DICT. The protocol pre-registers twelve
# runs before any of them exists, and "which twelve" is part of the registration. A dict
# that grows as results arrive cannot be checked against the plan; this one can — a missing
# fold is a `None` you can see, and `missing_runs()` names it.
#
# Fill each entry from its run's own log line
#
#   Split walkforward_window | val_frac=0.125 val_offset=<x> train_frac=0.5 | train [a → b] | val [c → d]
#
# and record the same line in §6 of the protocol. A run whose split line says `global_time`
# did not receive the fold variables and is VOID — do not record it here.
# --------------------------------------------------------------------------------------
FOLD_OFFSETS = {"F0": 0.000, "F1": 0.125, "F2": 0.250, "F3": 0.375}
FOLD_VAL_FRACTION = 0.125
FOLD_TRAIN_FRACTION = 0.5

# Run order is the protocol's: F2 and F3 (the folds §3 decides on) before F1 and F0, so the
# untouched evidence exists first if the budget is interrupted.
FOLD_RUN_ORDER = ("F2", "F3", "F1", "F0")

WALKFORWARD_RUNS: dict[str, str | None] = {
    "F0s1": None, "F0s2": None, "F0s3": None,
    "F1s1": None, "F1s2": None, "F1s3": None,
    "F2s1": None, "F2s2": None, "F2s3": None,
    "F3s1": None, "F3s2": None, "F3s3": None,
}

# The val span each fold's own `Split` line reports, as (start, end) ISO strings. Recorded
# once per fold from its first completed seed and then checked against the other two: three
# seeds of one fold are the same split, so a disagreement is a mis-recorded run, not noise.
# Used to give the walkforward era its `WINDOWS` — in this era the "window" IS the fold
# (protocol §2), so `add_window` keeps working and every per-window table becomes a per-fold
# table with no special case downstream.
WALKFORWARD_SPLITS: dict[str, tuple[str, str] | None] = {
    "F0": None, "F1": None, "F2": None, "F3": None,
}


def fold_of(label: str) -> str:
    """"F2s1" -> "F2". The fold is the identity that matters for clustering and for §3."""
    return label[:2]


RUNS_BY_ERA["walkforward"] = WALKFORWARD_RUNS

# Default is `prerepair` so that every number this package has ever published reproduces
# with no environment set. Phase 2 of the retrain plan reads `repaired`.
ERA = os.environ.get("M3_ERA", "prerepair")
if ERA not in RUNS_BY_ERA:
    raise SystemExit(f"M3_ERA={ERA!r}; expected one of {sorted(RUNS_BY_ERA)}")

BASELINE_RUNS = RUNS_BY_ERA[ERA]

# The calendar span both eras cover, as the intersection of the two eras' own extents
# (repaired starts later, prerepair ends earlier). Trades outside it exist in one era only,
# so a paired reading clips to it.
REPAIR_OVERLAP = ("2025-12-22T15:20:00Z", "2026-08-17T18:35:00Z")

# O8's 12-pair arm. Not part of the banked 3-seed baseline (single seed, 12-pair validation
# population), but it is 58% more bars to *search* a policy on at an unchanged measured
# edge — see M3_PLAN §5. Use it as an out-of-sample-ish replication of a policy decided on
# the baseline, never as one of the three seeds.
O8_RUN = "20260822T012619Z"

# The 8-pair universe every §1.3 number is measured on.
BASE8 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT",
    "WLDUSDT", "HYPEUSDT", "ZECUSDT", "1000PEPEUSDT",
]

DUMP_DIR = os.environ.get("M3_DUMP_DIR", "output/eval_dumps")
BAR_SECONDS = 300
NS = 1_000_000_000

# Calendar windows, verbatim from NEXT_TRAINING_PLAN §1.2 — the split six models were
# read on. M3-1 scores policies per window and reports the WORST, because §1.8's regime
# rule fails in window 2, which is where 47% of its trades live.
WINDOWS = [
    ("w1", "2025-12-01", "2026-02-01"),
    ("w2", "2026-02-01", "2026-04-01"),
    ("w3", "2026-04-01", "2026-06-01"),
    ("w4", "2026-06-01", "2026-10-01"),
]

if ERA == "walkforward":
    # Protocol §2: in this era the *window* is the fold. The four val spans do not overlap
    # in calendar (offsets 0.375/0.250/0.125/0.000 of one time-ordered history), so the same
    # "tag a row by which span its timestamp falls in" machinery labels a row with its fold.
    #
    # The spans come from the runs' own `Split` lines, never from the protocol's estimate
    # table — so until a fold is recorded it has no window and its rows tag as NA, which is
    # exactly the behaviour a half-filled registry should have. Oldest first, matching the
    # w1..w4 convention that a window list runs forward in time.
    WINDOWS = [(f, lo, hi) for f in ("F3", "F2", "F1", "F0")
               for lo, hi in [WALKFORWARD_SPLITS[f] or (None, None)] if lo]


def recorded_runs() -> dict[str, str]:
    """The era's runs that actually have a run id. Equals BASELINE_RUNS outside walkforward."""
    return {k: v for k, v in BASELINE_RUNS.items() if v}


def missing_runs() -> list[str]:
    """Registered runs with no run id yet — empty for the two completed eras."""
    return [k for k, v in BASELINE_RUNS.items() if not v]


def dump_path(run_id: str) -> str:
    return os.path.join(DUMP_DIR, f"eval_preds_{run_id}.parquet")


@dataclass(frozen=True)
class Dump:
    seed: str
    run_id: str
    df: pd.DataFrame          # all horizons, one row per (bar x horizon)

    def at(self, horizon: int) -> pd.DataFrame:
        h = self.df[self.df["horizon"] == horizon]
        if h.empty:
            raise SystemExit(
                f"{self.run_id}: no rows at horizon {horizon}; "
                f"have {sorted(self.df['horizon'].unique())}"
            )
        return h


def load(run_id: str, seed: str | None = None, pairs: list[str] | None = None) -> Dump:
    df = pd.read_parquet(dump_path(run_id))
    if pairs is not None:
        df = df[df["pair"].isin(pairs)]
    df = df.sort_values(["pair", "horizon", "ts"], kind="mergesort").reset_index(drop=True)
    return Dump(seed=seed or run_id, run_id=run_id, df=df)


def load_baseline(pairs: list[str] | None = None) -> list[Dump]:
    """The era's dumps, in registry order (s1/s2/s3, or F0s1..F3s3 under walkforward).

    Only *recorded* runs are loaded. Every era but `walkforward` has all of its runs, so this
    is the same list it has always returned; under `walkforward` it is however many folds
    have finished, and the callers that must not read a partial family (validate's TEST 3,
    the §3 verdict) check `missing_runs()` themselves rather than being handed a short list
    that looks complete.
    """
    return [load(run_id, seed=seed, pairs=pairs) for seed, run_id in recorded_runs().items()]


def clip_overlap(df: pd.DataFrame, ts_col: str = "ts") -> pd.DataFrame:
    """Restrict to REPAIR_OVERLAP — the calendar span both eras cover.

    Needed because the pre-repair and repaired dumps have different val boundaries (see
    RUNS_BY_ERA above). Without this, "the repair moved w4 by X bps" also contains "w4 grew
    by sixteen days of newer, post-fix market", and the two are not separable afterwards.
    """
    t = pd.to_datetime(df[ts_col], unit="ns", utc=True)
    lo, hi = (pd.Timestamp(x) for x in REPAIR_OVERLAP)
    return df[(t >= lo) & (t <= hi)]


def add_window(df: pd.DataFrame, ts_col: str = "ts") -> pd.DataFrame:
    """Tag each row with its window label — §1.2's four ~2-month blocks, or, in the
    `walkforward` era, the fold whose val span contains it (see WINDOWS above)."""
    t = pd.to_datetime(df[ts_col], unit="ns", utc=True)
    out = df.copy()
    out["window"] = pd.Series(pd.NA, index=df.index, dtype="object")
    for name, lo, hi in WINDOWS:
        lo_ts = pd.Timestamp(lo, tz="UTC")
        hi_ts = pd.Timestamp(hi, tz="UTC")
        out.loc[(t >= lo_ts) & (t < hi_ts), "window"] = name
    return out
