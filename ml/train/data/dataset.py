"""Sequence dataset for supervised 15m baseline."""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
import torch
from torch.utils.data import Dataset

from config import (
    CANDLE_INTERVAL,
    FLAT_THRESHOLD,
    HORIZON_MINUTES,
    PAIRS,
    SEQ_LEN,
)
from data.features import build_feature_frame, make_labels


def horizon_bars(candle_interval: str, horizon_minutes: int) -> int:
    mapping = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
    bar = mapping.get(candle_interval, 1)
    return max(1, horizon_minutes // bar)


def build_arrays(
    pairs: List[str] | None = None,
    seq_len: int = SEQ_LEN,
    horizon_minutes: int = HORIZON_MINUTES,
    candle_interval: str = CANDLE_INTERVAL,
) -> Tuple[np.ndarray, np.ndarray, dict]:
    pairs = pairs or PAIRS
    h_bars = horizon_bars(candle_interval, horizon_minutes)

    xs, ys = [], []
    meta = {"pairs": [], "n_per_pair": {}}

    for pair in pairs:
        pair = pair.strip()
        if not pair:
            continue
        frame = build_feature_frame(pair, candle_interval)
        if frame.empty or len(frame) < seq_len + h_bars + 5:
            meta["n_per_pair"][pair] = 0
            continue

        feats = frame.drop(columns=["close"]).values.astype(np.float32)
        labels = make_labels(frame["close"], h_bars, FLAT_THRESHOLD).values

        # standardize features per pair (train-time only; simple z-score)
        mean = feats.mean(axis=0, keepdims=True)
        std = feats.std(axis=0, keepdims=True) + 1e-6
        feats = (feats - mean) / std

        count = 0
        for i in range(seq_len, len(feats) - h_bars):
            y = labels[i]
            if y < 0:
                continue
            xs.append(feats[i - seq_len : i])
            ys.append(y)
            count += 1

        meta["n_per_pair"][pair] = count
        meta["pairs"].append(pair)

    if not xs:
        return np.zeros((0, seq_len, 16), dtype=np.float32), np.zeros((0,), dtype=np.int64), meta

    X = np.stack(xs, axis=0)
    y = np.array(ys, dtype=np.int64)
    meta["n_samples"] = len(y)
    meta["horizon_bars"] = h_bars
    return X, y, meta


class SequenceDataset(Dataset):
    def __init__(self, X: np.ndarray, y: np.ndarray):
        self.X = torch.from_numpy(X)
        self.y = torch.from_numpy(y)

    def __len__(self):
        return len(self.y)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]


def time_split(X, y, val_fraction: float = 0.2):
    """Time-ordered split (no shuffle)."""
    n = len(y)
    if n == 0:
        return X, y, X, y
    cut = int(n * (1.0 - val_fraction))
    cut = max(1, min(cut, n - 1)) if n > 1 else n
    return X[:cut], y[:cut], X[cut:], y[cut:]
