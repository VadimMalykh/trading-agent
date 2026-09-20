"""The time folds (PLAN §3). Fixed on 2026-09-15 from the measured candle extents (DATA.md).

F0 is warm-up: the earliest collector data, used only as training history for the folds after it (a
walk-forward fit for F1 needs something before F1). FP is the pre-history from the public archive's
klines (PLAN P5): no fitted thing and no search has read FP or F0, so a fixed, label-free rule that
was found on F1+F2 can be read there once, by registration, without spending a confirmation fold. F1 and F2 are the exploration folds; F3,
F4, F5 are confirmation folds, read only by registered contrasts (PLAN §8). Boundaries are
calendar dates, UTC, start inclusive, end exclusive. EMBARGO is removed from the START of each
scored fold so that no label of the previous fold overlaps a feature of the next.
"""
from __future__ import annotations

import pandas as pd

FOLDS: dict[str, tuple[str, str]] = {
    "FP": ("2020-05-01", "2022-08-18"),   # pre-history (added 2026-09-21): archive klines, 5–9 pairs; starts 120 days after the archive does
    "F0": ("2022-08-18", "2023-05-01"),   # warm-up, never scored
    "F1": ("2023-05-01", "2024-01-01"),   # exploration
    "F2": ("2024-01-01", "2024-09-01"),   # exploration
    "F3": ("2024-09-01", "2025-05-01"),   # confirmation
    "F4": ("2025-05-01", "2026-01-01"),   # confirmation
    "F5": ("2026-01-01", "2026-09-15"),   # confirmation (grows as data arrives; frozen at first read)
}
EXPLORATION = ("F1", "F2")
PREHISTORY = ("FP", "F0")               # never looked at by anything that chose a rule: the first honest read of a label-free rule found on F1+F2
CONFIRMATION = ("F3", "F4", "F5")
EMBARGO = pd.Timedelta(days=2)   # > the longest horizon studied (1d) + the longest feature lookback


def bounds(fold: str, embargoed: bool = True) -> tuple[pd.Timestamp, pd.Timestamp]:
    a, b = (pd.Timestamp(x, tz="UTC") for x in FOLDS[fold])
    return (a + EMBARGO if embargoed and fold != "F0" else a), b


def order(names) -> list[str]:
    return sorted(names, key=lambda f: FOLDS[f][0])


def mask(ts: pd.Series, fold: str, embargoed: bool = True) -> pd.Series:
    a, b = bounds(fold, embargoed)
    return (ts >= a) & (ts < b)


def training_end(fold: str) -> pd.Timestamp:
    """Walk-forward: a model scored on `fold` may be fitted only on data before the fold starts."""
    return pd.Timestamp(FOLDS[fold][0], tz="UTC")
