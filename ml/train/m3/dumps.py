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
# Seed 2 (20260819T142759Z) is the *served* checkpoint — m2_multi_20260819T142759Z_a186182b.pt
# at gate 0.6311. When a policy has to be chosen for deployment it is chosen on that seed;
# the other two exist to show the choice was not seed luck.
BASELINE_RUNS = {
    "s1": "20260818T185438Z",
    "s2": "20260819T142759Z",
    "s3": "20260820T025723Z",
}

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
