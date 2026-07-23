"""Sequence datasets for M1 (single horizon) and M2 (multi-horizon)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
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


def _ts_to_i64(index_val) -> np.int64:
    ts = pd.Timestamp(index_val)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return np.int64(ts.value)


def fit_feature_norm(
    X: np.ndarray,
    pair_ids: np.ndarray,
    pairs: List[str],
) -> Dict[str, dict]:
    """
    Per-pair mean/std over all timesteps in train windows.
    Returns {pair: {"mean": [F], "std": [F]}} plus optional "_global" fallback.
    """
    stats: Dict[str, dict] = {}
    flat_all = []
    for pair in pairs:
        mask = pair_ids == pair
        if not np.any(mask):
            continue
        flat = X[mask].reshape(-1, X.shape[-1]).astype(np.float64)
        flat_all.append(flat)
        mean = flat.mean(axis=0)
        std = flat.std(axis=0) + 1e-6
        stats[pair] = {
            "mean": mean.astype(np.float32).tolist(),
            "std": std.astype(np.float32).tolist(),
        }
    if flat_all:
        g = np.concatenate(flat_all, axis=0)
        stats["_global"] = {
            "mean": g.mean(axis=0).astype(np.float32).tolist(),
            "std": (g.std(axis=0) + 1e-6).astype(np.float32).tolist(),
        }
    return stats


def apply_feature_norm(
    X: np.ndarray,
    pair_ids: np.ndarray,
    norm_stats: Dict[str, dict],
) -> np.ndarray:
    """Apply per-pair z-score; unknown pairs use _global if present."""
    if not norm_stats or X.size == 0:
        return X
    out = X.copy()
    global_stats = norm_stats.get("_global")
    pairs_in = np.unique(pair_ids)
    for pair in pairs_in:
        st = norm_stats.get(str(pair)) or norm_stats.get(pair) or global_stats
        if st is None:
            continue
        mean = np.asarray(st["mean"], dtype=np.float32).reshape(1, 1, -1)
        std = np.asarray(st["std"], dtype=np.float32).reshape(1, 1, -1)
        mask = pair_ids == pair
        out[mask] = (out[mask] - mean) / std
    return out


def build_arrays(
    pairs: List[str] | None = None,
    seq_len: int = SEQ_LEN,
    horizon_minutes: int = HORIZON_MINUTES,
    candle_interval: str = CANDLE_INTERVAL,
    normalize: bool = True,
) -> Tuple[np.ndarray, np.ndarray, dict]:
    """M1: single-horizon labels. normalize=True keeps legacy full-series z-score."""
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

        if normalize:
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
) -> Tuple[np.ndarray, Dict[str, np.ndarray], np.ndarray, np.ndarray, dict]:
    """
    M2: raw (unnormalized) feature sequences + multi-horizon labels.

    Returns:
      X [N,T,F], y_dict, times_ns [N] int64, pair_ids [N] str, meta
    Sample kept only if all horizon labels are valid.
    Normalization is applied later on the train split only.
    """
    pairs = pairs or PAIRS
    horizons_minutes = horizons_minutes or HORIZONS_MINUTES
    h_bars_map = {h: horizon_bars(candle_interval, h) for h in horizons_minutes}
    max_h = max(h_bars_map.values())
    horizon_keys = [str(h) for h in horizons_minutes]

    xs: List[np.ndarray] = []
    ys: Dict[str, List[int]] = {k: [] for k in horizon_keys}
    times: List[np.int64] = []
    pair_list: List[str] = []
    meta = {
        "pairs": [],
        "n_per_pair": {},
        "horizons_minutes": horizons_minutes,
        "horizon_bars": {str(k): int(v) for k, v in h_bars_map.items()},
        "flat_thresholds": {
            str(h): float(FLAT_THRESHOLD_PER_HORIZON.get(h, FLAT_THRESHOLD))
            for h in horizons_minutes
        },
        "candle_interval": candle_interval,
    }

    for pair in pairs:
        pair = pair.strip().upper()
        if not pair:
            continue
        frame = build_feature_frame(pair, candle_interval)
        if frame.empty or len(frame) < seq_len + max_h + 5:
            meta["n_per_pair"][pair] = 0
            continue

        feats = frame.drop(columns=["close"]).values.astype(np.float32)
        index = frame.index

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
            times.append(_ts_to_i64(index[i]))
            pair_list.append(pair)
            count += 1

        meta["n_per_pair"][pair] = count
        if count > 0:
            meta["pairs"].append(pair)

    if not xs:
        empty_y = {k: np.zeros((0,), dtype=np.int64) for k in horizon_keys}
        return (
            np.zeros((0, seq_len, FEATURE_DIM), dtype=np.float32),
            empty_y,
            np.zeros((0,), dtype=np.int64),
            np.zeros((0,), dtype=object),
            meta,
        )

    X = np.stack(xs, axis=0)
    y_dict = {k: np.array(v, dtype=np.int64) for k, v in ys.items()}
    times_arr = np.asarray(times, dtype=np.int64)
    pair_ids = np.asarray(pair_list, dtype=object)
    meta["n_samples"] = len(X)
    if len(times_arr):
        meta["time_min_ns"] = int(times_arr.min())
        meta["time_max_ns"] = int(times_arr.max())
    return X, y_dict, times_arr, pair_ids, meta


def time_split(X, y, val_fraction: float = 0.2):
    """Legacy sequential cut (assumes X already time-ordered as stored)."""
    n = len(y) if not isinstance(y, dict) else X.shape[0]
    if n == 0:
        if isinstance(y, dict):
            return X, y, X, y
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


def time_split_global(
    X: np.ndarray,
    y_dict: Dict[str, np.ndarray],
    times: np.ndarray,
    pair_ids: np.ndarray,
    val_fraction: float = 0.2,
) -> Tuple[
    np.ndarray,
    Dict[str, np.ndarray],
    np.ndarray,
    np.ndarray,
    np.ndarray,
    Dict[str, np.ndarray],
    np.ndarray,
    np.ndarray,
]:
    """
    Global chronological split: sort all samples by timestamp, hold out last val_fraction.
    Returns train/val X, y, times, pair_ids.
    """
    n = X.shape[0]
    if n == 0:
        empty_y = {k: v[:0] for k, v in y_dict.items()}
        empty_t = times[:0]
        empty_p = pair_ids[:0]
        return X, empty_y, empty_t, empty_p, X, empty_y, empty_t, empty_p

    order = np.argsort(times, kind="mergesort")
    X = X[order]
    times = times[order]
    pair_ids = pair_ids[order]
    y_dict = {k: v[order] for k, v in y_dict.items()}

    cut = int(n * (1.0 - val_fraction))
    cut = max(1, min(cut, n - 1)) if n > 1 else n

    X_tr, X_va = X[:cut], X[cut:]
    y_tr = {k: v[:cut] for k, v in y_dict.items()}
    y_va = {k: v[cut:] for k, v in y_dict.items()}
    t_tr, t_va = times[:cut], times[cut:]
    p_tr, p_va = pair_ids[:cut], pair_ids[cut:]
    return X_tr, y_tr, t_tr, p_tr, X_va, y_va, t_va, p_va


def class_balance(y: np.ndarray) -> Dict[str, float]:
    counts = np.bincount(y, minlength=3).astype(np.float64)
    total = max(counts.sum(), 1.0)
    return {
        "down": float(counts[0] / total),
        "flat": float(counts[1] / total),
        "up": float(counts[2] / total),
        "n": int(counts.sum()),
    }


class SequenceDataset(Dataset):
    def __init__(self, X: np.ndarray, y: np.ndarray):
        self.X = torch.from_numpy(X)
        self.y = torch.from_numpy(y)

    def __len__(self):
        return len(self.y)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]


class MultiHorizonDataset(Dataset):
    def __init__(
        self,
        X: np.ndarray,
        y_dict: Dict[str, np.ndarray],
        horizon_keys: List[str],
        pair_ids: Optional[np.ndarray] = None,
    ):
        self.X = torch.from_numpy(X.astype(np.float32))
        self.horizon_keys = horizon_keys
        self.y = {k: torch.from_numpy(y_dict[k]) for k in horizon_keys}
        self.pair_ids = pair_ids

    def __len__(self):
        return self.X.shape[0]

    def __getitem__(self, idx):
        return self.X[idx], {k: self.y[k][idx] for k in self.horizon_keys}
