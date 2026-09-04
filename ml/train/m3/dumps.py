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
    """The three banked seeds, in s1/s2/s3 order."""
    return [load(run_id, seed=seed, pairs=pairs) for seed, run_id in BASELINE_RUNS.items()]


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
    """Tag each row with its calendar window label (§1.2's four ~2-month blocks)."""
    t = pd.to_datetime(df[ts_col], unit="ns", utc=True)
    out = df.copy()
    out["window"] = pd.Series(pd.NA, index=df.index, dtype="object")
    for name, lo, hi in WINDOWS:
        lo_ts = pd.Timestamp(lo, tz="UTC")
        hi_ts = pd.Timestamp(hi, tz="UTC")
        out.loc[(t >= lo_ts) & (t < hi_ts), "window"] = name
    return out
