"""Sequence datasets for M1 (single horizon) and M2 (multi-horizon)."""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import torch
from torch.utils.data import Dataset

from config import (
    CANDLE_INTERVAL,
    FEATURE_DIM,
    FLAT_THRESHOLD,
    FLAT_THRESHOLD_PER_HORIZON,
    HORIZON_MINUTES,
    HORIZONS_MINUTES,
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
    """M1: single-horizon labels."""
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

        mean = feats.mean(axis=0, keepdims=True)
        std = feats.std(axis=0, keepdims=True) + 1e-6
        feats = (feats - mean) / std

        count = 0
        for i in range(seq_len, len(feats) - h_bars):
            y = int(labels[i])
            if y < 0:
                continue
            xs.append(feats[i - seq_len : i])
            ys.append(y)
            count += 1

        meta["n_per_pair"][pair] = count
        meta["pairs"].append(pair)

    if not xs:
        return (
            np.zeros((0, seq_len, FEATURE_DIM), dtype=np.float32),
            np.zeros((0,), dtype=np.int64),
            meta,
        )

    X = np.stack(xs, axis=0)
    y = np.array(ys, dtype=np.int64)
    meta["n_samples"] = len(y)
    meta["horizon_bars"] = h_bars
    return X, y, meta


def build_multi_horizon_arrays(
    pairs: List[str] | None = None,
    seq_len: int = SEQ_LEN,
    horizons_minutes: List[int] | None = None,
    candle_interval: str = CANDLE_INTERVAL,
) -> Tuple[np.ndarray, Dict[str, np.ndarray], dict]:
    """
    M2: one feature sequence, labels for each horizon.
    Returns X [N,T,F], y_dict { "1": [N], "15": [N], "60": [N] }, meta.
    Sample kept only if all horizon labels are valid.
    """
    pairs = pairs or PAIRS
    horizons_minutes = horizons_minutes or HORIZONS_MINUTES
    h_bars_map = {h: horizon_bars(candle_interval, h) for h in horizons_minutes}
    max_h = max(h_bars_map.values())
    horizon_keys = [str(h) for h in horizons_minutes]

    xs: List[np.ndarray] = []
    ys: Dict[str, List[int]] = {k: [] for k in horizon_keys}
    meta = {"pairs": [], "n_per_pair": {}, "horizons_minutes": horizons_minutes, "horizon_bars": h_bars_map}

    for pair in pairs:
        pair = pair.strip()
        if not pair:
            continue
        frame = build_feature_frame(pair, candle_interval)
        if frame.empty or len(frame) < seq_len + max_h + 5:
            meta["n_per_pair"][pair] = 0
            continue

        feats = frame.drop(columns=["close"]).values.astype(np.float32)
        mean = feats.mean(axis=0, keepdims=True)
        std = feats.std(axis=0, keepdims=True) + 1e-6
        feats = (feats - mean) / std

        label_cols = {}
        for h in horizons_minutes:
            th = FLAT_THRESHOLD_PER_HORIZON.get(h, FLAT_THRESHOLD)
            label_cols[str(h)] = make_labels(frame["close"], h_bars_map[h], th).values

        count = 0
        for i in range(seq_len, len(feats) - max_h):
            row_labels = {k: int(label_cols[k][i]) for k in horizon_keys}
            if any(v < 0 for v in row_labels.values()):
                continue
            xs.append(feats[i - seq_len : i])
            for k, v in row_labels.items():
                ys[k].append(v)
            count += 1

        meta["n_per_pair"][pair] = count
        meta["pairs"].append(pair)

    if not xs:
        empty_y = {k: np.zeros((0,), dtype=np.int64) for k in horizon_keys}
        return np.zeros((0, seq_len, FEATURE_DIM), dtype=np.float32), empty_y, meta

    X = np.stack(xs, axis=0)
    y_dict = {k: np.array(v, dtype=np.int64) for k, v in ys.items()}
    meta["n_samples"] = len(X)
    return X, y_dict, meta


class SequenceDataset(Dataset):
    def __init__(self, X: np.ndarray, y: np.ndarray):
        self.X = torch.from_numpy(X)
        self.y = torch.from_numpy(y)

    def __len__(self):
        return len(self.y)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]


class MultiHorizonDataset(Dataset):
    def __init__(self, X: np.ndarray, y_dict: Dict[str, np.ndarray], horizon_keys: List[str]):
        self.X = torch.from_numpy(X)
        self.horizon_keys = horizon_keys
        self.y = {k: torch.from_numpy(y_dict[k]) for k in horizon_keys}

    def __len__(self):
        return self.X.shape[0]

    def __getitem__(self, idx):
        return self.X[idx], {k: self.y[k][idx] for k in self.horizon_keys}


def time_split(X, y, val_fraction: float = 0.2):
    """Time-ordered split for single-horizon y array."""
    n = len(y) if not isinstance(y, dict) else X.shape[0]
    if n == 0:
        return X, y, X, y
    cut = int(n * (1.0 - val_fraction))
    cut = max(1, min(cut, n - 1)) if n > 1 else n
    if isinstance(y, dict):
        return (
            X[:cut],
            {k: v[:cut] for k, v in y.items()},
            X[cut:],
            {k: v[cut:] for k, v in y.items()},
        )
    return X[:cut], y[:cut], X[cut:], y[cut:]
