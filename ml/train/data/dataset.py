"""Sequence datasets for M1 (single horizon) and M2 (multi-horizon)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

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


def apply_norm_to_matrix(feats: np.ndarray, stats: dict) -> np.ndarray:
    """In-place-ish z-score of [T, F] using {mean, std} lists."""
    mean = np.asarray(stats["mean"], dtype=np.float32)
    std = np.asarray(stats["std"], dtype=np.float32)
    return (feats - mean) / std


def apply_feature_norm(
    X: np.ndarray,
    pair_ids: np.ndarray,
    norm_stats: Dict[str, dict],
) -> np.ndarray:
    """Legacy helper for serve / tests: apply per-pair z-score on [N,T,F]."""
    if not norm_stats or X.size == 0:
        return X
    out = X.copy()
    global_stats = norm_stats.get("_global")
    for pair in np.unique(pair_ids):
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


@dataclass
class PairSeries:
    """One symbol's bar matrix + labels. Windows are sliced lazily."""

    pair: str
    feats: np.ndarray  # [T, F] float32
    labels: Dict[str, np.ndarray]  # key -> [T] int64
    times: np.ndarray  # [T] int64 ns


@dataclass
class M2IndexBundle:
    """Memory-light M2 data: per-pair series + sample index arrays."""

    series: List[PairSeries]
    pair_i: np.ndarray  # [N] int32 index into series
    t_i: np.ndarray  # [N] int32 end bar index (label at t_i, window ends at t_i)
    times: np.ndarray  # [N] int64
    horizon_keys: List[str]
    seq_len: int
    meta: dict

    @property
    def n_samples(self) -> int:
        return int(self.pair_i.shape[0])


def build_m2_index_bundle(
    pairs: List[str] | None = None,
    seq_len: int = SEQ_LEN,
    horizons_minutes: List[int] | None = None,
    candle_interval: str = CANDLE_INTERVAL,
) -> M2IndexBundle:
    """
    Load per-pair feature matrices once; record (pair, t) for each valid sample.
    Does NOT materialize [N, seq, F] (that caused multi-GB OOM).
    """
    pairs = pairs or PAIRS
    horizons_minutes = horizons_minutes or HORIZONS_MINUTES
    h_bars_map = {h: horizon_bars(candle_interval, h) for h in horizons_minutes}
    max_h = max(h_bars_map.values()) if h_bars_map else 1
    horizon_keys = [str(h) for h in horizons_minutes]

    series_list: List[PairSeries] = []
    pair_i_list: List[int] = []
    t_i_list: List[int] = []
    times_list: List[np.int64] = []
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
        "layout": "lazy_index",
    }

    for pair in pairs:
        pair = pair.strip().upper()
        if not pair:
            continue
        frame = build_feature_frame(pair, candle_interval)
        if frame.empty or len(frame) < seq_len + max_h + 5:
            meta["n_per_pair"][pair] = 0
            continue

        feats = np.ascontiguousarray(
            frame.drop(columns=["close"]).to_numpy(dtype=np.float32)
        )
        times_bar = np.fromiter(
            (_ts_to_i64(ts) for ts in frame.index),
            dtype=np.int64,
            count=len(frame),
        )
        label_cols: Dict[str, np.ndarray] = {}
        for h in horizons_minutes:
            th = FLAT_THRESHOLD_PER_HORIZON.get(h, FLAT_THRESHOLD)
            lab = make_labels(frame["close"], h_bars_map[h], th).to_numpy(dtype=np.int64)
            label_cols[str(h)] = lab

        del frame

        pi = len(series_list)
        series_list.append(
            PairSeries(pair=pair, feats=feats, labels=label_cols, times=times_bar)
        )

        # Vectorized validity: all horizons >= 0
        valid = np.ones(len(feats), dtype=bool)
        valid[:seq_len] = False
        valid[len(feats) - max_h :] = False
        for k in horizon_keys:
            valid &= label_cols[k] >= 0

        idx = np.nonzero(valid)[0]
        n = int(idx.shape[0])
        meta["n_per_pair"][pair] = n
        if n == 0:
            continue
        meta["pairs"].append(pair)
        pair_i_list.append(np.full(n, pi, dtype=np.int32))
        t_i_list.append(idx.astype(np.int32))
        times_list.append(times_bar[idx])

    if not pair_i_list:
        meta["n_samples"] = 0
        return M2IndexBundle(
            series=series_list,
            pair_i=np.zeros((0,), dtype=np.int32),
            t_i=np.zeros((0,), dtype=np.int32),
            times=np.zeros((0,), dtype=np.int64),
            horizon_keys=horizon_keys,
            seq_len=seq_len,
            meta=meta,
        )

    pair_i = np.concatenate(pair_i_list)
    t_i = np.concatenate(t_i_list)
    times = np.concatenate(times_list)
    meta["n_samples"] = int(pair_i.shape[0])
    meta["time_min_ns"] = int(times.min())
    meta["time_max_ns"] = int(times.max())
    return M2IndexBundle(
        series=series_list,
        pair_i=pair_i,
        t_i=t_i,
        times=times,
        horizon_keys=horizon_keys,
        seq_len=seq_len,
        meta=meta,
    )


def time_split_indices(
    times: np.ndarray,
    val_fraction: float = 0.2,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return index arrays into the sample list for train / val (global time)."""
    n = times.shape[0]
    if n == 0:
        empty = np.zeros((0,), dtype=np.int64)
        return empty, empty
    order = np.argsort(times, kind="mergesort")
    cut = int(n * (1.0 - val_fraction))
    cut = max(1, min(cut, n - 1)) if n > 1 else n
    return order[:cut].astype(np.int64), order[cut:].astype(np.int64)


def fit_norm_from_bundle(
    bundle: M2IndexBundle,
    train_sample_idx: np.ndarray,
) -> Dict[str, dict]:
    """
    Per-pair mean/std from bars that appear in train windows
    (approx: all bars up to last train end-index per pair — cheap and stable).
    """
    stats: Dict[str, dict] = {}
    flat_all: List[np.ndarray] = []

    for pi, ser in enumerate(bundle.series):
        mask = bundle.pair_i[train_sample_idx] == pi
        if not np.any(mask):
            continue
        t_ends = bundle.t_i[train_sample_idx[mask]]
        # Include full windows: [min(t_end-seq+1), max(t_end)]
        t_hi = int(t_ends.max()) + 1
        t_lo = max(0, int(t_ends.min()) - bundle.seq_len)
        block = ser.feats[t_lo:t_hi]
        if block.size == 0:
            continue
        flat = block.reshape(-1, block.shape[-1]).astype(np.float64)
        flat_all.append(flat)
        mean = flat.mean(axis=0)
        std = flat.std(axis=0) + 1e-6
        stats[ser.pair] = {
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


def apply_norm_to_bundle(bundle: M2IndexBundle, norm_stats: Dict[str, dict]) -> None:
    """Normalize each pair matrix in-place using checkpoint-style stats."""
    global_stats = norm_stats.get("_global")
    for ser in bundle.series:
        st = norm_stats.get(ser.pair) or global_stats
        if st is None:
            continue
        ser.feats = np.ascontiguousarray(apply_norm_to_matrix(ser.feats, st))


def labels_for_indices(
    bundle: M2IndexBundle,
    sample_idx: np.ndarray,
    horizon_key: str,
) -> np.ndarray:
    """Gather labels for a set of sample indices (for class weights / balance)."""
    if sample_idx.size == 0:
        return np.zeros((0,), dtype=np.int64)
    out = np.empty(sample_idx.shape[0], dtype=np.int64)
    # group by pair for fewer python loops
    pi_all = bundle.pair_i[sample_idx]
    t_all = bundle.t_i[sample_idx]
    for pi in np.unique(pi_all):
        m = pi_all == pi
        out[m] = bundle.series[int(pi)].labels[horizon_key][t_all[m]]
    return out


def pair_ids_for_indices(bundle: M2IndexBundle, sample_idx: np.ndarray) -> np.ndarray:
    names = np.array([s.pair for s in bundle.series], dtype=object)
    return names[bundle.pair_i[sample_idx]]


def class_balance(y: np.ndarray) -> Dict[str, float]:
    counts = np.bincount(y, minlength=3).astype(np.float64)
    total = max(counts.sum(), 1.0)
    return {
        "down": float(counts[0] / total),
        "flat": float(counts[1] / total),
        "up": float(counts[2] / total),
        "n": int(counts.sum()),
    }


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


# Back-compat aliases used by older imports
def build_multi_horizon_arrays(*args, **kwargs):
    """Deprecated heavy path — builds full X (OOM risk). Prefer build_m2_index_bundle."""
    bundle = build_m2_index_bundle(*args, **kwargs)
    n = bundle.n_samples
    if n == 0:
        empty_y = {k: np.zeros((0,), dtype=np.int64) for k in bundle.horizon_keys}
        return (
            np.zeros((0, bundle.seq_len, FEATURE_DIM), dtype=np.float32),
            empty_y,
            bundle.times,
            np.zeros((0,), dtype=object),
            bundle.meta,
        )
    # Only for small debug sets
    if n > 100_000:
        raise MemoryError(
            f"build_multi_horizon_arrays refused N={n}; use build_m2_index_bundle / LazyMultiHorizonDataset"
        )
    xs = []
    ys = {k: [] for k in bundle.horizon_keys}
    pairs = []
    for i in range(n):
        pi = int(bundle.pair_i[i])
        t = int(bundle.t_i[i])
        ser = bundle.series[pi]
        xs.append(ser.feats[t - bundle.seq_len : t])
        for k in bundle.horizon_keys:
            ys[k].append(int(ser.labels[k][t]))
        pairs.append(ser.pair)
    X = np.stack(xs, axis=0)
    y_dict = {k: np.asarray(v, dtype=np.int64) for k, v in ys.items()}
    return X, y_dict, bundle.times.copy(), np.asarray(pairs, dtype=object), bundle.meta


def time_split_global(X, y_dict, times, pair_ids, val_fraction: float = 0.2):
    """Legacy full-array split."""
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
    return (
        X[:cut],
        {k: v[:cut] for k, v in y_dict.items()},
        times[:cut],
        pair_ids[:cut],
        X[cut:],
        {k: v[cut:] for k, v in y_dict.items()},
        times[cut:],
        pair_ids[cut:],
    )


def fit_feature_norm(X, pair_ids, pairs):
    """Legacy fit on materialized X."""
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


class SequenceDataset(Dataset):
    def __init__(self, X: np.ndarray, y: np.ndarray):
        self.X = torch.from_numpy(X)
        self.y = torch.from_numpy(y)

    def __len__(self):
        return len(self.y)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]


class MultiHorizonDataset(Dataset):
    """Materialized windows (small sets / tests only)."""

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


class LazyMultiHorizonDataset(Dataset):
    """
    Windows sliced from per-pair matrices at __getitem__ time.
    Peak RAM ≈ sum(T_pair * F) + index arrays (~tens of MB for months of 1m data).
    """

    def __init__(
        self,
        bundle: M2IndexBundle,
        sample_idx: np.ndarray,
        horizon_keys: Optional[Sequence[str]] = None,
    ):
        self.bundle = bundle
        self.sample_idx = np.asarray(sample_idx, dtype=np.int64)
        self.horizon_keys = list(horizon_keys or bundle.horizon_keys)
        self.seq_len = bundle.seq_len

    def __len__(self):
        return int(self.sample_idx.shape[0])

    def __getitem__(self, i: int):
        j = int(self.sample_idx[i])
        pi = int(self.bundle.pair_i[j])
        t = int(self.bundle.t_i[j])
        ser = self.bundle.series[pi]
        # copy so DataLoader collation owns the buffer
        x = np.array(ser.feats[t - self.seq_len : t], dtype=np.float32, copy=True)
        y = {
            k: torch.tensor(int(ser.labels[k][t]), dtype=torch.long)
            for k in self.horizon_keys
        }
        return torch.from_numpy(x), y
