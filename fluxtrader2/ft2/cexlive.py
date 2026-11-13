"""R96 (PLAN §8, decision CT1) — the LIVE balance files of `scripts/cexflow_live.py` as event rows: which day has a usable file, and the day's
change per base from that file ALONE. Reads no price. The eligibility (the perpetual, its age, BNB, the members, the 7-day collapse) and the
cells are the read session's, on these rows.

usable     a day d has a usable file when a fetch with status ok STARTED 05:55:00 … 06:04:59 UTC on d (the log's `started_utc`; the first
           such row of the day) — and, checked when the file is opened, it holds the 00:00 UTC point of d.
change     per base the amount summed over chains (`cexflow._rows`: the `-staking` / `-borrowed` chains out) at the 00:00 points of d and of
           d − 1 AS THAT FILE GIVES THEM; change = amount_d ÷ amount_(d−1) − 1, NaN when either point is absent or the earlier one is not
           positive; `first_stamp` = the base's first point in the file (the 30-day warm-up).
rewritten  the d − 1 amount in the file of d against the d amount in the usable file of d − 1: a relative difference above REWRITE_TOL flags
           the row (`rewritten`); `checked` False when d − 1 has no usable file.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import cexflow, data

RAW_DIR = data.RAW / "external" / "defillama_cex_live"
LOG = Path("output/cexflow_live/fetch_log.csv")
WINDOW = (pd.Timedelta(hours=5, minutes=55), pd.Timedelta(hours=6, minutes=5))      # the fetch's start, time of day UTC: [05:55:00, 06:05:00)
REWRITE_TOL = 0.005
DAY = pd.Timedelta(days=1)


def usable(log: pd.DataFrame) -> pd.DataFrame:
    """(day, file, raw_md5, started) — the first ok fetch of each day that started inside the window."""
    L = log.copy()
    L["started"] = pd.to_datetime(L["started_utc"], utc=True)
    L["day"] = L["started"].dt.floor("D")
    tod = L["started"] - L["day"]
    ok = L["status"].astype(str).str.startswith("ok") & (tod >= WINDOW[0]) & (tod < WINDOW[1]) & L["file"].notna()
    return L[ok].sort_values("started").drop_duplicates("day")[["day", "file", "raw_md5", "started"]].reset_index(drop=True)


def day_change(path: Path, day: pd.Timestamp) -> pd.DataFrame:
    """Per base from ONE file: amount at `day` 00:00, prev_amount at day − 1, change, first_stamp; an empty frame when the file lacks the day's point."""
    R = cexflow._rows(Path(path))
    if not (R["stamp"] == day).any():
        return pd.DataFrame(columns=["day", "base", "amount", "prev_amount", "change", "first_stamp"])
    first = R.groupby("base")["stamp"].min()
    a = R[R["stamp"] == day].groupby("base")["amount"].sum()
    b = R[R["stamp"] == day - DAY].groupby("base")["amount"].sum().reindex(a.index)
    ch = np.where(b.gt(0).to_numpy(), a.to_numpy() / b.to_numpy() - 1.0, np.nan)
    return pd.DataFrame({"day": day, "base": a.index, "amount": a.to_numpy(), "prev_amount": b.to_numpy(), "change": ch, "first_stamp": first.reindex(a.index).to_numpy()})


def live_rows(raw_dir: Path = RAW_DIR, log: Path = LOG) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(every (day, base) row of the usable files with `checked` / `rewritten`, the usable table with `has_point`)."""
    U = usable(pd.read_csv(log))
    parts, has = [], []
    for r in U.itertuples(index=False):
        d = day_change(Path(raw_dir) / r.file, r.day)
        has.append(len(d) > 0)
        parts.append(d)
    U["has_point"] = has
    A = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["day", "base", "amount", "prev_amount", "change", "first_stamp"])
    y = A[["day", "base", "amount"]].assign(day=lambda x: x["day"] + DAY).rename(columns={"amount": "amount_in_prev_file"})
    A = A.merge(y, on=["day", "base"], how="left")
    A["checked"] = A["amount_in_prev_file"].notna()
    with np.errstate(invalid="ignore", divide="ignore"):
        A["rewritten"] = A["checked"] & ((A["prev_amount"] - A["amount_in_prev_file"]).abs() > REWRITE_TOL * A["amount_in_prev_file"].abs())
    return A, U
