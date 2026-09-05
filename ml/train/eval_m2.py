#!/usr/bin/env python3
"""M2 eval: per-horizon accuracy + confidence gate sweep (+ per-pair)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import numpy as np
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    CANDLE_INTERVAL,
    FEATURE_DIM,
    GATE_THRESHOLD,
    HIDDEN_SIZE,
    HORIZONS_MINUTES,
    MAKER_ROUND_TRIP_COST,
    MODEL_DIR,
    OUTPUT_DIR,
    PAIRS,
    ROUND_TRIP_COST,
    SEQ_LEN,
    SERVE_TARGET_COVERAGE,
    VAL_FRACTION,
    WF_WINDOWS,
)
from data.dataset import (
    LazyMultiHorizonDataset,
    apply_norm_to_bundle,
    build_m2_index_bundle,
    fit_norm_from_bundle,
    horizon_bars,
    pair_ids_for_indices,
    time_split_indices,
    time_split_indices_window,
)
from data.db import load_whitelist_pairs
from data.features import ALL_FEATURE_COLS, FEATURE_COLS
from gate import (
    dir_logits_to_three_class,
    directional_signal,
    fixed_coverage_metrics,
    gate_sweep,
    side_split_metrics,
)
from models.multi_horizon import SharedEncoderMultiHead

# Coverages at which to report a stable, cross-model-comparable directional edge.
# SERVE_TARGET_COVERAGE is folded in so the row the served gate is derived FROM is
# always present in the printed table, whatever the operator sets it to.
FIXED_COVERAGES = sorted({0.01, 0.02, 0.05, 0.10, 0.20, round(SERVE_TARGET_COVERAGE, 6)})

# The confidence threshold this eval treats as "the operating point". It starts at
# the config constant and is REPLACED, once the primary horizon's predictions exist,
# by the threshold that realizes SERVE_TARGET_COVERAGE on this val window (C13).
#
# Why a module global rather than a parameter: every table in this file marks and
# measures "the served gate", and before C13 they all read the config constant. A
# checkpoint whose confidence scale differs from the one that constant was tuned on
# then gets every serve-gate row printed at the wrong operating point — which is
# exactly how three seeds of one configuration came to be compared at 1.2% / 2.5% /
# 1.7% coverage (docs/NEXT_TRAINING_PLAN.md 1.5). One global, set once, keeps them
# consistent.
SERVED_GATE = GATE_THRESHOLD
SERVED_GATE_SOURCE = "config"

# Bar duration in seconds — used by the serial P&L hold logic to decide when an open
# position has been held long enough. Was hardcoded to 60, which silently assumed 1m
# candles: under CANDLE_INTERVAL=15m a 4h horizon (16 bars) would have used a 16-MINUTE
# hold, so the sim would open a new position ~15x too often and the reported net_ret /
# trade count would be meaningless. Derived from CANDLE_INTERVAL now.
_BAR_SECONDS_BY_INTERVAL = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


def bar_seconds(candle_interval: str = CANDLE_INTERVAL) -> int:
    secs = _BAR_SECONDS_BY_INTERVAL.get(candle_interval)
    if secs is None:
        raise ValueError(
            f"CANDLE_INTERVAL={candle_interval!r} has no known bar duration; add it to "
            "_BAR_SECONDS_BY_INTERVAL (and to dataset.horizon_bars) before running."
        )
    return secs


BAR_SECONDS = bar_seconds()


def collate_mh(batch):
    xs = torch.stack([b[0] for b in batch], dim=0)
    keys = batch[0][1].keys()
    ys = {k: torch.stack([b[1][k] for b in batch], dim=0) for k in keys}
    return xs, ys


def pred_rows(
    horizon: str,
    logits: torch.Tensor,
    dir_logits: torch.Tensor | None,
    y_true: torch.Tensor,
    fwd_ret: torch.Tensor | None,
    times: np.ndarray,
    pair_ids: np.ndarray,
    book_of_sample: np.ndarray,
) -> dict:
    """
    Per-bar decision record for one horizon (`--dump-preds`).

    Everything the offline regime analysis needs and nothing else: WHEN the bar was
    (`ts`), WHAT the model would have done (`side`, `conf`, `p_up`), and WHAT
    happened (`fwd_ret`, `y3`). Aggregate eval tables can only say the edge is
    concentrated in some windows; answering whether that is *predictable at decision
    time* requires the per-bar rows.

    `side`/`conf` come from the same directional signal the gate and every P&L
    number in this file use, so a re-aggregation of this table reproduces the
    printed fixed-coverage rows exactly.
    """
    gate_logits = dir_logits_to_three_class(dir_logits) if dir_logits is not None else logits
    side, conf = directional_signal(gate_logits)
    p_up = torch.softmax(gate_logits, dim=-1)[:, 2]
    n = int(y_true.numel())
    return {
        # epoch nanoseconds, UTC — the bar the decision is made ON (not the exit).
        "ts": np.asarray(times, dtype=np.int64),
        "pair": np.asarray(pair_ids),
        "horizon": np.full(n, int(horizon), dtype=np.int32),
        # -1 = short, +1 = long (gate.directional_signal's 0/2 remapped).
        "side": np.where(side.numpy() == 2, 1, -1).astype(np.int8),
        "conf": conf.numpy().astype(np.float32),
        "p_up": p_up.numpy().astype(np.float32),
        "fwd_ret": (
            fwd_ret.numpy().astype(np.float32)
            if fwd_ret is not None
            else np.full(n, np.nan, dtype=np.float32)
        ),
        "y3": y_true.numpy().astype(np.int8),  # 0=down 1=flat 2=up
        "has_book": book_of_sample.astype(np.int8),
    }


def write_pred_dump(rows: list, out_dir: str) -> Path | None:
    """
    Concatenate per-horizon `pred_rows` and write one table to OUTPUT_DIR.

    Parquet when the image has an engine, gzipped CSV otherwise — a missing
    pyarrow must not cost a whole eval run, and the columns are identical either
    way. The chosen path is printed so the log always says which one landed.
    """
    if not rows:
        return None
    import pandas as pd

    df = pd.DataFrame({k: np.concatenate([r[k] for r in rows]) for k in rows[0]})
    # `pair` is one Python str per row otherwise — at O2 scale (millions of val bars x
    # 3 horizons) that object column dominates both RAM and file size. Categorical
    # stores one code per row and dictionary-encodes in parquet.
    df["pair"] = df["pair"].astype("category")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "eval_preds.parquet"
    try:
        df.to_parquet(path, index=False)
    except Exception as e:  # no pyarrow/fastparquet in the image
        path.unlink(missing_ok=True)  # don't leave a truncated parquet to be uploaded
        path = out / "eval_preds.csv.gz"
        df.to_csv(path, index=False, compression="gzip")
        print(f"  (parquet engine unavailable: {e} → wrote gzipped CSV instead)")
    print(
        f"Wrote {path} — {len(df):,} rows x {len(df.columns)} cols "
        f"({path.stat().st_size / 1e6:.1f} MB); ts is epoch ns UTC, side is -1/+1"
    )
    return path


def _ns_to_iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _ns_to_day(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%d")


def _iso_to_ns(iso: str) -> int:
    """Inverse of `_ns_to_iso` — parses the "%Y-%m-%d %H:%M UTC" a checkpoint stores."""
    return int(
        datetime.strptime(iso, "%Y-%m-%d %H:%M UTC")
        .replace(tzinfo=timezone.utc)
        .timestamp()
        * 1_000_000_000
    )


def split_from_meta(times, meta: dict):
    """The val rows this CHECKPOINT was scored on, taken from the checkpoint.

    Same rule as `candle_interval` and `feature_cols` above: a re-score trusts the
    checkpoint, not the ambient env. Before this existed, eval always took the newest
    `VAL_FRACTION` of history, which silently scored every walk-forward fold on F0's
    window instead of its own (WALKFORWARD_PROTOCOL §6.1, the 2026-09-05 void). A fold
    model evaluated there is still out-of-sample, so nothing looks wrong in the log —
    which is exactly why the window has to come from the checkpoint.

    Selection is by TIMESTAMP, not by re-deriving the fraction. The dump grows between
    runs, so the same `val_offset` maps to a window shifted by hours (the three F2 seeds'
    split lines already differed by ~9h); the recorded boundaries reproduce the trained
    window exactly. Returns (train_idx, val_idx); train is only ever used to re-fit norm
    for a pre-`norm_stats` checkpoint.
    """
    is_fold = meta.get("split") == "walkforward_window" or bool(
        meta.get("val_offset") or meta.get("train_fraction")
    )
    if not is_fold:
        return time_split_indices(times, VAL_FRACTION)

    val_start, val_end = meta.get("val_start"), meta.get("val_end")
    if val_start and val_end:
        lo, hi = _iso_to_ns(val_start), _iso_to_ns(val_end)
        order = np.argsort(times, kind="mergesort")
        t_sorted = times[order]
        va_idx = order[(t_sorted >= lo) & (t_sorted <= hi)].astype(np.int64)
        tr_idx = order[t_sorted < lo].astype(np.int64)
        print(
            f"Fold split from checkpoint meta: val_offset={meta.get('val_offset')} "
            f"train_frac={meta.get('train_fraction')} | val [{val_start} → {val_end}] "
            f"| {va_idx.shape[0]} of {times.shape[0]} samples"
        )
        if va_idx.shape[0] == 0:
            print(
                "ERROR: the checkpoint's val window holds no rows in this bundle — the "
                "dump does not cover the window this fold was trained against."
            )
            sys.exit(2)
        return tr_idx, va_idx

    # Pre-2026-09-05 fold checkpoints carry the fractions but not the boundaries.
    val_frac = float(meta.get("val_fraction") or VAL_FRACTION)
    print(
        f"WARNING: fold checkpoint records no val_start/val_end — falling back to "
        f"val_frac={val_frac} val_offset={meta.get('val_offset') or 0.0} "
        f"train_frac={meta.get('train_fraction') or 0.0} on TODAY's sample count, so "
        f"the window may be shifted by hours relative to the trained one."
    )
    return time_split_indices_window(
        times,
        val_frac,
        float(meta.get("val_offset") or 0.0),
        float(meta.get("train_fraction") or 0.0),
    )


def simulate_pnl(
    side: torch.Tensor,
    conf: torch.Tensor,
    mask: torch.Tensor,
    fwd_ret: torch.Tensor,
    times: np.ndarray,
    pair_ids: np.ndarray,
    hold_bars: int,
    cost: float = ROUND_TRIP_COST,
) -> dict:
    """
    Serial per-pair position simulation: enter when gated (side = +1/-1), hold
    `hold_bars`, exit on the return booked at entry. Ignores new gates while a
    position is open, so overlapping 1m-entry / 30m-hold trades are not double
    counted. Reports net return (sum of per-trade net returns), trades, win rate,
    profit factor, daily Sharpe (annualized), max drawdown.

    fwd_ret[i] is the forward return realized by the trade opened at sample i, so
    a trade is booked at its entry time but measured over the hold.
    """
    g = mask
    empty = {
        "n_trades": 0,
        "total_net_ret": 0.0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "daily_sharpe": None,
        "max_dd": 0.0,
        "n_days": 0,
    }
    if not g.any():
        return dict(empty)
    side_i = torch.where(side[g] == 2, 1.0, -1.0).cpu().numpy()
    ret_g = fwd_ret[g].cpu().numpy()
    t_g = times[g.numpy()]
    p_g = pair_ids[g.numpy()]
    hold_s = hold_bars * BAR_SECONDS

    # Order each pair's gated samples by time; serial position sim per pair.
    booked = []  # (entry_day, net_ret)
    n_trades = 0
    for pair in np.unique(p_g):
        m = p_g == pair
        order = np.argsort(t_g[m], kind="mergesort")
        times_p = t_g[m][order]
        side_p = side_i[m][order]
        ret_p = ret_g[m][order]
        open_entry = None  # (time_ns, side, fwd_ret_at_entry)
        for t, s, r in zip(times_p, side_p, ret_p):
            if open_entry is not None:
                et, es, er = open_entry
                if t >= et + hold_s * 1_000_000_000:
                    booked.append((_ns_to_day(int(et)), es * er - cost))
                    n_trades += 1
                    open_entry = None
            if open_entry is None:
                open_entry = (t, s, r)
        if open_entry is not None:
            et, es, er = open_entry
            booked.append((_ns_to_day(int(et)), es * er - cost))
            n_trades += 1

    if n_trades == 0:
        return dict(empty)

    nets = np.array([b[1] for b in booked])
    wins = nets > 0
    total = float(nets.sum())
    gross_w = nets[nets > 0].sum()
    gross_l = -nets[nets < 0].sum()
    pf = float(gross_w / gross_l) if gross_l > 0 else float("inf")

    # Daily equity from trade net returns grouped by entry day.
    #
    # C16 (2026-08-22): this used to be `sorted(day_net.values())`, which sorts the
    # daily P&L by VALUE. The equity curve was then built from every losing day first,
    # so `max_dd` was not a drawdown at all — it was the sum of all negative days, a
    # deterministic artifact, in every log written before this fix. `daily_sharpe` was
    # unaffected (mean and std do not depend on order). `_ns_to_day` emits YYYY-MM-DD,
    # so sorting the KEYS is chronological.
    day_net: Dict[str, float] = {}
    for d, n in booked:
        day_net[d] = day_net.get(d, 0.0) + n
    day_list = np.array([day_net[d] for d in sorted(day_net)], dtype=np.float64)
    daily_sharpe = None
    max_dd = 0.0
    if day_list.size >= 2:
        # Equity starts at 0 BEFORE the first trading day, so the running peak must
        # too — otherwise a strategy that loses from day one is measured against its
        # own first loss and its drawdown is understated (bundled with C16).
        eq = np.concatenate(([0.0], np.cumsum(day_list)))
        peak = np.maximum.accumulate(eq)
        max_dd = float((eq - peak).min())
        std = day_list.std()
        if std > 0:
            daily_sharpe = float(day_list.mean() / std * np.sqrt(365))

    return {
        "n_trades": int(n_trades),
        "total_net_ret": round(total, 6),
        "win_rate": round(float(wins.mean()), 4),
        "profit_factor": round(pf, 3) if pf != float("inf") else None,
        "daily_sharpe": round(daily_sharpe, 3) if daily_sharpe is not None else None,
        "max_dd": round(max_dd, 6),
        "n_days": int(len(day_list)),
    }


def _add_pnl_rows(sweep, dir_logits, y_true, fwd_ret, times, pair_ids, hold_bars, cost):
    """Attach a serial-sim P&L to each directional gate-sweep row (in place)."""
    if dir_logits is None or fwd_ret is None or times is None:
        return sweep
    gate_logits = dir_logits_to_three_class(dir_logits)
    side, conf = directional_signal(gate_logits)
    for row in sweep:
        mask = conf >= row["threshold"]
        pnl = simulate_pnl(side, conf, mask, fwd_ret, times, pair_ids, hold_bars, cost)
        row["net_ret"] = pnl["total_net_ret"]
        row["n_trades"] = pnl["n_trades"]
        row["win_rate"] = pnl["win_rate"]
        row["profit_factor"] = pnl["profit_factor"]
        row["daily_sharpe"] = pnl["daily_sharpe"]
        row["max_dd"] = pnl["max_dd"]
    return sweep


def fixed_coverage_pnl(
    dir_logits,
    fwd_ret,
    times,
    pair_ids,
    coverage: float,
    hold_bars: int,
    costs=None,
) -> dict | None:
    """
    Serial-sim P&L at a FIXED coverage (top-`coverage` fraction of bars by
    directional confidence) — the same slice every other verdict metric in this
    file is computed on.

    Why this exists: the gate sweep reports P&L only at absolute confidence
    thresholds, which are (a) not comparable across models as the confidence
    scale drifts and (b) mostly unusable below 0.50, since conf >= 0.5 by
    construction. So the fixed-coverage table carried dir_acc/Wilson-LB but no
    P&L, and the "is this operating point cost-viable" question could not be
    answered from the log at all.

    Cost handling: the sim is run ONCE at cost=0 to get the gross result, then
    every cost model is derived exactly as `gross - n_trades * cost`. That
    identity is exact because trade selection does not depend on cost and
    simulate_pnl subtracts a flat `cost` per booked trade. `gross_bps_per_trade`
    is the durable, cost-independent number — rank arms on it.
    """
    if dir_logits is None or fwd_ret is None or times is None or hold_bars is None:
        return None
    costs = costs or {"taker": ROUND_TRIP_COST, "maker": MAKER_ROUND_TRIP_COST}
    gate_logits = dir_logits_to_three_class(dir_logits)
    side, conf = directional_signal(gate_logits)

    n = int(conf.numel())
    k = int(round(n * float(min(max(coverage, 0.0), 1.0))))
    if n == 0 or k <= 0:
        return None
    topk = torch.topk(conf, k=min(k, n)).indices
    mask = torch.zeros(n, dtype=torch.bool)
    mask[topk] = True

    gross = simulate_pnl(
        side, conf, mask, fwd_ret, times, pair_ids, hold_bars, cost=0.0
    )
    n_trades = int(gross["n_trades"])
    gross_total = float(gross["total_net_ret"])
    out = {
        "coverage": float(coverage),
        "n_gated": int(mask.sum().item()),
        "n_trades": n_trades,
        "gross_ret": gross_total,
        "gross_bps_per_trade": (gross_total / n_trades * 1e4) if n_trades else 0.0,
        "win_rate": float(gross["win_rate"]),
        "daily_sharpe": gross["daily_sharpe"],
        "max_dd": float(gross["max_dd"]),
        "net": {},
    }
    for name, c in costs.items():
        net = gross_total - n_trades * float(c)
        out["net"][name] = {
            "cost_bps": float(c) * 1e4,
            "net_ret": net,
            "net_bps_per_trade": (net / n_trades * 1e4) if n_trades else 0.0,
        }
    return out


def long_short_pnl_split(
    dir_logits,
    y_true,
    fwd_ret,
    times,
    pair_ids,
    hold_bars,
    threshold,
    cost=ROUND_TRIP_COST,
):
    """
    Serial-sim P&L split by trade SIDE at a fixed gate threshold. Runs
    `simulate_pnl` once with only long (pred up) bars gated, once with only short
    (pred down) bars gated, so we can see whether the model's P&L is one-sided —
    the direct P&L companion to `side_split_metrics` (accuracy). See
    docs/NEXT_TRAINING_PLAN.md "one-mode hypothesis".
    """
    if dir_logits is None or fwd_ret is None or times is None:
        return None
    gate_logits = dir_logits_to_three_class(dir_logits)
    side, conf = directional_signal(gate_logits)
    passed = conf >= threshold
    out = {}
    for name, side_val in (("long", 2), ("short", 0)):
        mask = passed & (side == side_val)
        pnl = simulate_pnl(side, conf, mask, fwd_ret, times, pair_ids, hold_bars, cost)
        out[name] = {
            "net_ret": pnl["total_net_ret"],
            "n_trades": pnl["n_trades"],
            "win_rate": pnl["win_rate"],
            "daily_sharpe": pnl["daily_sharpe"],
            "max_dd": pnl["max_dd"],
        }
    return out


def momentum_gate_logits(bundle, sample_idx, h_bars: int) -> torch.Tensor:
    """
    Momentum baseline: side = sign of trailing `h_bars` return
    (close[t]/close[t-h_bars]-1), confidence = |momentum| scaled to a fixed
    logit spread so the shared directional_signal / fixed_coverage / P&L path can
    reuse it. Logits are [down, flat, up] with flat = -inf.
    """
    s = 25.0  # logit scale; softmax confidence saturates as |m| grows
    n = int(sample_idx.shape[0])
    out = np.zeros((n, 3), dtype=np.float64)
    out[:, 1] = -np.inf
    pi_all = bundle.pair_i[sample_idx]
    t_all = bundle.t_i[sample_idx]
    for pi in np.unique(pi_all):
        m = pi_all == pi
        close = bundle.series[int(pi)].close
        tt = t_all[m].astype(int)
        lo = np.maximum(tt - h_bars, 0)
        mom = close[tt] / np.maximum(close[lo], 1e-12) - 1.0
        mom = np.clip(mom, -0.05, 0.05)  # tame outliers
        out[m, 0] = -s * mom
        out[m, 2] = s * mom
    return torch.from_numpy(out.astype(np.float32))


def calibration_report(dir_logits: torch.Tensor, y_true: torch.Tensor, n_bins: int = 10) -> dict:
    """Binned reliability of the directional head's p(up) among moved bars + Brier."""
    probs = torch.softmax(dir_logits, dim=-1)[:, 1]  # p(up)
    move = y_true != 1
    p = probs[move]
    y = (y_true[move] == 2).float()
    bins = []
    edges = torch.linspace(0.0, 1.0, n_bins + 1)
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        sel = (p >= lo) & (p < hi) if hi < 1.0 else (p >= lo) & (p <= hi)
        nb = int(sel.sum())
        bins.append(
            {
                "bin": f"[{lo:.2f},{hi:.2f})" if hi < 1.0 else f"[{lo:.2f},{hi:.2f}]",
                "n": nb,
                "mean_pred": round(float(p[sel].mean()), 4) if nb else None,
                "empirical_up": round(float(y[sel].mean()), 4) if nb else None,
            }
        )
    brier = float(((p - y) ** 2).mean().item()) if p.numel() else None
    return {"bins": bins, "brier": round(brier, 4) if brier is not None else None, "n_moved": int(move.sum())}


def walk_forward_edge(
    gate_logits: torch.Tensor,
    y_true: torch.Tensor,
    times: np.ndarray,
    n_windows: int,
    book: np.ndarray | None = None,
) -> list:
    """Fixed-coverage edge on n_windows disjoint time windows of the full range.

    `book`: per-sample 0/1 "window has book data" — reported per window so a
    book-era calendar-time confound (zero-vs-real feature discontinuity) is visible.
    """
    order = np.argsort(times, kind="mergesort")
    n = order.shape[0]
    edges = np.linspace(0, n, n_windows + 1, dtype=int)
    out = []
    for i in range(n_windows):
        a, b = edges[i], edges[i + 1]
        idx = order[a:b]
        if idx.shape[0] == 0:
            continue
        fc5 = fixed_coverage_metrics(gate_logits[idx], y_true[idx], 0.05)
        fc10 = fixed_coverage_metrics(gate_logits[idx], y_true[idx], 0.10)
        tmin, tmax = int(times[idx].min()), int(times[idx].max())
        frac_book = float(book[idx].mean()) if book is not None else None
        out.append(
            {
                "window": i + 1,
                "n": int(idx.shape[0]),
                "start": _ns_to_iso(tmin),
                "end": _ns_to_iso(tmax),
                "frac_book": round(frac_book, 3) if frac_book is not None else None,
                "cov05": {
                    "dir_acc": round(float(fc5.get("dir_acc", 0.0)), 4),
                    "wilson_lb": round(float(fc5.get("dir_acc_wilson_lb", 0.0)), 4),
                    "n_dir": int(fc5.get("n_true_directional_gated") or 0),
                },
                "cov10": {
                    "dir_acc": round(float(fc10.get("dir_acc", 0.0)), 4),
                    "wilson_lb": round(float(fc10.get("dir_acc_wilson_lb", 0.0)), 4),
                    "n_dir": int(fc10.get("n_true_directional_gated") or 0),
                },
            }
        )
    return out


def book_era_edge_split(
    gate_logits: torch.Tensor,
    y_true: torch.Tensor,
    book_of_sample: np.ndarray,
    coverage: float = 0.05,
) -> dict:
    """
    Fixed-coverage directional edge split by book-era membership (book vs
    pre-book). Surfaces the calendar-time confound: if the edge lives only in
    the book window, the model is exploiting the zero→real feature discontinuity
    rather than microstructure.
    """
    out = {}
    for label, sel in (("book", book_of_sample > 0.5), ("pre_book", book_of_sample <= 0.5)):
        idx = np.nonzero(sel)[0]
        if idx.shape[0] == 0:
            out[label] = None
            continue
        ti = torch.from_numpy(idx)
        fc = fixed_coverage_metrics(gate_logits[ti], y_true[ti], coverage)
        out[label] = {
            "n": int(idx.shape[0]),
            "dir_acc": round(float(fc.get("dir_acc", 0.0)), 4),
            "wilson_lb": round(float(fc.get("dir_acc_wilson_lb", 0.0)), 4),
            "n_dir": int(fc.get("n_true_directional_gated") or 0),
        }
    return out


def quantile_calibration(quant: torch.Tensor, ret: torch.Tensor, levels):
    """
    Calibration of a quantile head: for each level q, the fraction of realized
    returns that fall at/below the predicted q-quantile should be ≈ q. Also
    reports central-band [p_low, p_high] coverage (should ≈ p_high - p_low) and
    the median absolute error of p50 vs realized.
    """
    n = ret.shape[0]
    per_level = []
    for i, lv in enumerate(levels):
        emp = float((ret <= quant[:, i]).float().mean().item())
        per_level.append({"level": float(lv), "empirical_below": emp})
    lo, hi = quant[:, 0], quant[:, -1]
    band_cov = float(((ret >= lo) & (ret <= hi)).float().mean().item())
    band_target = float(levels[-1] - levels[0])
    # median absolute error using the middle quantile as point estimate
    mid_i = len(levels) // 2
    p50_mae = float((ret - quant[:, mid_i]).abs().median().item())
    return {
        "n": int(n),
        "per_level": per_level,
        "band_coverage": band_cov,
        "band_target": band_target,
        "p50_mae": p50_mae,
    }


def _member_fingerprint(meta: dict) -> dict:
    """The meta fields that decide WHICH EXPERIMENT a checkpoint is.

    Averaging predictions across checkpoints is only meaningful when the members
    scored the same bars from the same inputs. These five fields are the ones that
    change the bar grid, the window, or the label — differ on any of them and the
    members are not measuring the same thing, so the ensemble is nonsense rather
    than merely noisy.
    """
    horizons = meta.get("horizons_minutes") or HORIZONS_MINUTES
    return {
        "candle_interval": str(meta.get("candle_interval") or CANDLE_INTERVAL),
        "seq_len": int(meta.get("seq_len", SEQ_LEN)),
        "feature_dim": int(meta.get("feature_dim", FEATURE_DIM)),
        # The names, not just the count: two 29-column checkpoints with different
        # column ORDER would average two models reading different inputs.
        "feature_cols": list(meta.get("feature_cols") or []),
        "horizon_keys": list(meta.get("horizon_keys") or [str(h) for h in horizons]),
        "primary_horizon": str(
            meta.get("primary_horizon", horizons[min(1, len(horizons) - 1)])
        ),
        # The fold, since `split_from_meta` reads the val window off member[0]: two
        # different folds averaged together would be scored on ONE of their windows.
        # The fold identity, not the exact boundaries — three seeds of one fold record
        # boundaries hours apart (the dump grows between runs) and must still ensemble,
        # in which case member[0]'s boundaries are the ones used.
        "val_offset": float(meta.get("val_offset") or 0.0),
        "train_fraction": float(meta.get("train_fraction") or 0.0),
    }


def load_members(spec: str, device) -> list:
    """
    Resolve --checkpoint (one path, or a comma-separated list) into loaded members.

    A single path behaves exactly as before. Several paths form an ENSEMBLE: their
    per-bar probabilities are averaged before any gate or table is computed (C14).
    That exists because run-to-run seed noise is this project's dominant measurement
    problem — three checkpoints of one configuration disagree by more than most of
    the effects being chased — and averaging is the cheapest way to spend that
    disagreement on a better estimate instead of fighting it.

    Members must agree on `_member_fingerprint`; a mismatch raises rather than
    silently averaging two different experiments. Architecture differences
    (hidden size, layers) only warn — a wider net is still a legitimate ensemble
    member, it just is not what we currently do.
    """
    paths = [Path(x.strip()) for x in str(spec).split(",") if x.strip()]
    if not paths:
        print("No checkpoint given")
        sys.exit(1)

    members = []
    for path in paths:
        if not path.exists():
            print(f"Checkpoint not found: {path}")
            sys.exit(1)
        ckpt = torch.load(path, map_location=device, weights_only=False)
        members.append({"path": path, "ckpt": ckpt, "meta": ckpt.get("meta", {})})

    ref = _member_fingerprint(members[0]["meta"])
    for m in members[1:]:
        got = _member_fingerprint(m["meta"])
        if got != ref:
            diff = {k: (ref[k], got[k]) for k in ref if ref[k] != got[k]}
            print(
                f"ERROR: ensemble members describe different experiments — refusing to "
                f"average.\n  {members[0]['path'].name}: {ref}\n  {m['path'].name}: {got}"
                f"\n  differing: {diff}"
            )
            sys.exit(2)
        for k in ("hidden_size", "num_layers", "pair_embed_dim"):
            a, b = members[0]["meta"].get(k), m["meta"].get(k)
            if a != b:
                print(
                    f"  NOTE: member {m['path'].name} has {k}={b} vs "
                    f"{members[0]['path'].name}'s {a} — averaging anyway (architecture "
                    f"differences are legitimate in an ensemble)."
                )

    if len(members) > 1:
        print(f"=== ENSEMBLE of {len(members)} checkpoints (probability-averaged) ===")
        for i, m in enumerate(members):
            print(f"    member {i}: {m['path'].name}")
        print(
            "    Averaging is on PROBABILITIES, not logits: each member's softmax is "
            "averaged and the result is stored back as log-probabilities, so every "
            "downstream table (which softmaxes again) sees exactly the mean probability."
        )
    return members


def build_model_from_meta(meta: dict, device):
    """Instantiate the encoder described by a checkpoint's meta (no weights loaded)."""
    horizons = meta.get("horizons_minutes") or HORIZONS_MINUTES
    pair_vocab = list(meta.get("pair_vocab") or [])
    pair_embed_dim = int(meta.get("pair_embed_dim", 0))
    return SharedEncoderMultiHead(
        input_size=meta.get("feature_dim", FEATURE_DIM),
        hidden_size=meta.get("hidden_size", HIDDEN_SIZE),
        horizons_minutes=horizons,
        directional_head=bool(meta.get("directional_head", False)),
        quantile_head=bool(meta.get("quantile_head", False)),
        quantile_levels=meta.get("quantile_levels") or [0.1, 0.5, 0.9],
        num_layers=int(meta.get("num_layers", 2)),
        n_pairs=len(pair_vocab) if pair_embed_dim > 0 else 0,
        pair_embed_dim=pair_embed_dim,
    ).to(device)


def probs_to_logits(probs: torch.Tensor) -> torch.Tensor:
    """Store a probability tensor as logits without changing what it means.

    softmax(log p) == p, so writing log-probabilities back into the tensors the rest
    of this file calls "logits" leaves every downstream metric reading the exact
    averaged probability. Clamped because log(0) would poison an argmax.
    """
    return torch.log(probs.clamp_min(1e-12))


def derive_served_gate(
    gate_logits,
    y_true,
    dir_logits,
    fwd_ret,
    times,
    pair_ids,
    hold_bars,
    target_coverage: float,
) -> dict:
    """
    Turn a COVERAGE target into the confidence threshold that realizes it here.

    This is C13's core. `GATE_THRESHOLD` is an absolute probability, and a
    probability is not a portable operating point: three seeds of one configuration
    gate 1.2% / 2.5% / 1.7% of bars at conf >= 0.62, and the 1m model P2 gates 80%
    at 0.58. The fraction of bars traded, by contrast, is what the fixed-coverage
    P&L table is monotone in for every healthy model — so the operator picks a
    coverage, and the threshold that delivers it is a measured property OF THE
    CHECKPOINT, recorded next to the economics it was chosen from.

    Returns the threshold plus enough context to audit the choice later: the val
    window it was measured on, and the realized edge and gross/net bps/trade there.
    """
    fc = fixed_coverage_metrics(gate_logits, y_true, target_coverage)
    pnl = fixed_coverage_pnl(
        dir_logits, fwd_ret, times, pair_ids, target_coverage, hold_bars
    )
    out = {
        "target_coverage": float(target_coverage),
        "conf_threshold": round(float(fc.get("conf_threshold") or 0.0), 6),
        "measured": {
            "n_gated": int(fc.get("n_gated") or 0),
            "dir_acc": round(float(fc.get("dir_acc") or 0.0), 4),
            "wilson_lb": round(float(fc.get("dir_acc_wilson_lb") or 0.0), 4),
            "n_dir": int(fc.get("n_true_directional_gated") or 0),
        },
        "val_time_start": _ns_to_iso(int(np.min(times))) if times is not None else None,
        "val_time_end": _ns_to_iso(int(np.max(times))) if times is not None else None,
    }
    if pnl:
        out["measured"].update(
            {
                "n_trades": int(pnl["n_trades"]),
                "gross_bps_per_trade": round(float(pnl["gross_bps_per_trade"]), 3),
                "net_bps_per_trade": {
                    k: round(float(v["net_bps_per_trade"]), 3)
                    for k, v in pnl["net"].items()
                },
            }
        )
    return out


def write_served_gate_meta(ckpt_path: Path, ckpt: dict, served_gate: dict) -> bool:
    """
    Persist the derived gate into the checkpoint so serving cannot get it wrong.

    Written in place, and the training runner uploads the checkpoint AFTER eval, so
    a normal training run ships a checkpoint that already carries its own operating
    point. Without this the gate lives only in a log, and promoting a model means
    a human transcribing a number — which is how a model tuned at one confidence
    scale ended up served at another's.
    """
    try:
        meta = ckpt.setdefault("meta", {})
        meta["served_gate"] = served_gate
        torch.save(ckpt, ckpt_path)
        return True
    except Exception as exc:  # noqa: BLE001 - a failed write must not void the eval
        print(f"  WARNING: could not write served_gate into {ckpt_path}: {exc}")
        return False


def run_horizon_report(
    logits,
    y_true,
    thresholds,
    pair_ids=None,
    dir_logits=None,
    fwd_ret=None,
    times=None,
    hold_bars=None,
    cost=ROUND_TRIP_COST,
):
    pred = logits.argmax(dim=1)
    ungated = float((pred == y_true).float().mean().item())

    conf_matrix = torch.zeros(3, 3, dtype=torch.long)
    for t, p_ in zip(y_true.view(-1), pred.view(-1)):
        conf_matrix[t.long(), p_.long()] += 1

    # Gate/fixed-coverage use the clean directional-head signal when present.
    gate_logits = (
        dir_logits_to_three_class(dir_logits) if dir_logits is not None else logits
    )
    sweep = gate_sweep(gate_logits, y_true, thresholds, mode="directional")
    # Attach serial-sim P&L (net_ret / trades / win / Sharpe / maxdd) to each row.
    if fwd_ret is not None and times is not None and hold_bars is not None:
        _add_pnl_rows(sweep, dir_logits, y_true, fwd_ret, times, pair_ids, hold_bars, cost)
    fixed_cov = [fixed_coverage_metrics(gate_logits, y_true, c) for c in FIXED_COVERAGES]
    # P&L on the SAME slices the fixed-coverage edge is measured on, at both cost
    # models. This is where "is this operating point cost-viable" gets answered.
    fixed_cov_pnl = [
        fixed_coverage_pnl(dir_logits, fwd_ret, times, pair_ids, c, hold_bars)
        for c in FIXED_COVERAGES
    ]

    # Directional-symmetry diagnostics ("one-mode" test): per-side accuracy at
    # fixed cov 0.05, and per-side serial P&L at the serve gate.
    side_split = side_split_metrics(gate_logits, y_true, 0.05)
    ls_pnl = None
    if fwd_ret is not None and times is not None and hold_bars is not None:
        ls_pnl = long_short_pnl_split(
            dir_logits, y_true, fwd_ret, times, pair_ids, hold_bars, SERVED_GATE, cost
        )

    serve_row = next((r for r in sweep if abs(r["threshold"] - SERVED_GATE) < 1e-9), None)
    edge = None
    if serve_row and serve_row.get("n_gated", 0) > 0:
        edge = float(serve_row.get("gated_dir_acc") or 0.0) - 0.5

    per_pair = {}
    if pair_ids is not None and len(pair_ids) == len(y_true):
        for pair in sorted(set(pair_ids.tolist())):
            mask = pair_ids == pair
            if not np.any(mask):
                continue
            idx = torch.from_numpy(np.where(mask)[0])
            sub_logits = logits[idx]
            sub_y = y_true[idx]
            sub_pred = sub_logits.argmax(dim=1)
            sub_ungated = float((sub_pred == sub_y).float().mean().item())
            sub_gate = gate_logits[idx]
            sub_sweep = gate_sweep(sub_gate, sub_y, thresholds, mode="directional")
            # Fixed-coverage edge per pair: the cross-model-comparable metric used
            # to judge whether adding alts degrades the majors' edge.
            sub_fixed = [fixed_coverage_metrics(sub_gate, sub_y, c) for c in FIXED_COVERAGES]
            per_pair[str(pair)] = {
                "n": int(mask.sum()),
                "ungated_acc": sub_ungated,
                "gate_sweep": sub_sweep,
                "fixed_coverage": sub_fixed,
            }

    return {
        "ungated_acc": ungated,
        "confusion": conf_matrix.tolist(),
        "gate_sweep": sweep,
        "fixed_coverage": fixed_cov,
        "fixed_coverage_pnl": fixed_cov_pnl,
        "side_split_cov05": side_split,
        "long_short_pnl": ls_pnl,
        "serve_gate": SERVED_GATE,
        "serve_gate_source": SERVED_GATE_SOURCE,
        "serve_gate_dir_edge_vs_half": edge,
        "per_pair": per_pair,
        "conf_matrix_tensor": conf_matrix,
        "sweep_rows": sweep,
    }


def main():
    p = argparse.ArgumentParser(description="FluxTrader M2 eval + gate sweep")
    p.add_argument("--checkpoint", default=f"{MODEL_DIR}/m2_multi.pt")
    p.add_argument("--device", default="cpu")
    p.add_argument(
        "--gate",
        # conf = max(p_down, p_up) over a 2-way softmax, so conf >= 0.5 ALWAYS and
        # every threshold <= 0.50 trades 100% of bars. The old default swept
        # 0.35/0.40/0.45/0.50 — four identical, uninformative rows. Sweep above the
        # floor instead, bracketing the served 0.58.
        default="0.50,0.55,0.58,0.62,0.68,0.75",
        help="Comma-separated confidence thresholds (must be >= 0.50; see config.GATE_THRESHOLD)",
    )
    p.add_argument(
        "--pairs",
        default="",
        help="Comma-separated pairs. Default: UI whitelist from DB.",
    )
    p.add_argument(
        "--tail-days",
        type=int,
        default=None,
        help="Only the last N days of 1m candles per pair (bounds RAM on small "
        "hosts like the 2GB always-on VM). Default: full history.",
    )
    p.add_argument(
        "--dump-preds",
        action="store_true",
        help="Write per-bar (ts, pair, horizon, side, conf, p_up, fwd_ret, y3, "
        "has_book) for the val window to OUTPUT_DIR/eval_preds.parquet.",
    )
    p.add_argument(
        "--target-coverage",
        type=float,
        default=SERVE_TARGET_COVERAGE,
        help="Fraction of bars the served gate should trade. The confidence "
        "threshold that realizes it on this val window becomes the operating point "
        "and is written into the checkpoint meta (C13).",
    )
    p.add_argument(
        "--no-write-gate-meta",
        action="store_true",
        help="Derive and print the served gate but do NOT write it back into the "
        "checkpoint file. Default is to write (the training runner uploads the "
        "checkpoint after eval, so it ships carrying its own operating point).",
    )
    args = p.parse_args()

    device = torch.device(args.device)
    # One path evaluates one checkpoint; several (comma-separated) evaluate their
    # probability-averaged ensemble (C14). Everything after this point is identical
    # for both cases — the ensemble is materialized as one set of averaged tensors.
    members = load_members(args.checkpoint, device)
    is_ensemble = len(members) > 1
    ckpt_path = members[0]["path"]
    ckpt = members[0]["ckpt"]
    meta = members[0]["meta"]
    horizons = meta.get("horizons_minutes") or HORIZONS_MINUTES
    horizon_keys = meta.get("horizon_keys") or [str(h) for h in horizons]
    seq_len = meta.get("seq_len", SEQ_LEN)
    primary = str(meta.get("primary_horizon", horizons[min(1, len(horizons) - 1)]))
    has_dir_head = bool(meta.get("directional_head", False))
    quant_levels = meta.get("quantile_levels") or [0.1, 0.5, 0.9]

    # --- Rebuild the checkpoint's OWN feature columns (C12) ----------------------
    # FEATURE_COLS grows over time. A checkpoint trained on 19 columns must be fed
    # those 19, in that order — feeding it today's 29 is a shape error at best and a
    # silent feature-shuffle at worst. Checkpoints written before C12 carry no
    # feature_cols, so fall back to the frozen legacy prefix, which is exactly what
    # they were trained on.
    ckpt_feature_dim = int(meta.get("feature_dim", FEATURE_DIM))
    eval_feature_cols = list(meta.get("feature_cols") or [])
    if not eval_feature_cols:
        eval_feature_cols = list(ALL_FEATURE_COLS[:ckpt_feature_dim])
        print(
            f"NOTE: checkpoint records no feature_cols (pre-C12) — rebuilding its "
            f"{ckpt_feature_dim} columns from the frozen legacy list."
        )
    if len(eval_feature_cols) != ckpt_feature_dim:
        print(
            f"ERROR: checkpoint feature_dim={ckpt_feature_dim} but feature_cols has "
            f"{len(eval_feature_cols)} entries — refusing to guess."
        )
        sys.exit(2)
    print(f"Feature columns: {len(eval_feature_cols)} ({', '.join(eval_feature_cols)})")

    # --- Candle interval comes from the CHECKPOINT, not the ambient env ----------
    # Re-scoring a historical checkpoint (gcp_train.sh --eval-only) runs with today's
    # config, and CANDLE_INTERVAL defaults to 1m. A checkpoint trained on 15m bars
    # rebuilt at 1m would silently be a different experiment: a different bar grid, a
    # different val window, and hold_bars/BAR_SECONDS off by 15x — so its P&L and
    # trade counts would be meaningless while still printing a full, plausible table.
    # The bundle records candle_interval in meta, so trust the checkpoint and say so.
    global BAR_SECONDS, SERVED_GATE, SERVED_GATE_SOURCE
    ckpt_interval = meta.get("candle_interval")
    if ckpt_interval:
        eval_interval = str(ckpt_interval)
        if eval_interval != CANDLE_INTERVAL:
            print(
                f"NOTE: checkpoint was trained on {eval_interval} candles but "
                f"CANDLE_INTERVAL={CANDLE_INTERVAL} — using the CHECKPOINT's "
                f"{eval_interval} so this eval reproduces the trained recipe."
            )
    else:
        eval_interval = CANDLE_INTERVAL
        print(
            f"WARNING: checkpoint records no candle_interval (pre-2026 checkpoint) — "
            f"falling back to CANDLE_INTERVAL={eval_interval}. If it was trained on a "
            f"different bar size, every P&L number below is wrong; pass the right "
            f"CANDLE_INTERVAL explicitly."
        )
    BAR_SECONDS = bar_seconds(eval_interval)

    for m in members:
        mdl = build_model_from_meta(m["meta"], device)
        mdl.load_state_dict(m["ckpt"]["model_state"])
        mdl.eval()
        m["model"] = mdl
    print(f"Directional head: {'ON — gating uses aux up/down signal' if has_dir_head else 'off'}")

    if args.pairs.strip():
        pairs = [x.strip().upper() for x in args.pairs.split(",") if x.strip()]
    else:
        pairs = meta.get("pairs") or load_whitelist_pairs(fallback=PAIRS)
    print(f"Eval pairs: {pairs}")
    print(
        f"Checkpoint primary={primary}m seq_len={seq_len} "
        f"candles={eval_interval} norm={meta.get('norm', 'legacy')}"
    )

    # Tail window bounds peak RAM on small hosts: the always-on VM has 2GB and
    # already runs postgres + app + ml_inference, so a full ~180d multi-pair
    # bundle OOMs there (same failure mode training had before the streaming
    # norm fix). 1m candles -> 1440 rows/day.
    max_rows = None
    if args.tail_days and args.tail_days > 0:
        # Rows/day follows the bar size — hardcoding 1440 would ask for 15x too much
        # history on a 15m checkpoint, which is exactly the OOM this flag prevents.
        max_rows = int(args.tail_days * 86400 / BAR_SECONDS)
        print(f"Tail window: last {args.tail_days}d (~{max_rows:,} {eval_interval} candles/pair)")

    bundle = build_m2_index_bundle(
        pairs=pairs,
        seq_len=seq_len,
        horizons_minutes=horizons,
        max_rows=max_rows,
        candle_interval=eval_interval,
        feature_cols=eval_feature_cols,
    )
    tr_idx, va_idx = split_from_meta(bundle.times, meta)

    # Each member normalizes with ITS OWN train-fit statistics, and those differ
    # between runs (the val split moves as collection continues, so no two runs fit
    # norm on exactly the same bars). Normalization is in-place, so an ensemble has
    # to restore the raw matrices between members — snapshot them first. One extra
    # copy of [T, F] float32 per pair; for the 5m/8-pair bundle that is ~0.25GB.
    raw_feats = (
        [ser.feats.copy() for ser in bundle.series] if is_ensemble else None
    )

    def _normalize_for(member_meta: dict, report: bool) -> None:
        st = member_meta.get("norm_stats") or {}
        if st:
            apply_norm_to_bundle(bundle, st, report=report)
        else:
            legacy = fit_norm_from_bundle(bundle, tr_idx)
            apply_norm_to_bundle(bundle, legacy, report=report)
            print("Warning: checkpoint has no norm_stats; fitted from current train split")

    _normalize_for(meta, report=True)

    if va_idx.shape[0] == 0:
        print("No validation samples")
        sys.exit(2)

    t_va = bundle.times[va_idx]
    p_va = pair_ids_for_indices(bundle, va_idx)
    print(
        f"Val samples={va_idx.shape[0]} | "
        f"[{_ns_to_iso(int(t_va.min()))} → {_ns_to_iso(int(t_va.max()))}]"
    )
    print(f"Val per pair: {{{', '.join(f'{p}: {int((p_va == p).sum())}' for p in pairs)}}}")

    # Raw per-sample "window is in the book era" flag (calendar-time confound
    # visibility). Uses the pre-normalization book_present array so the check is
    # exact, unlike thresholding the z-scored has_book feature.
    book_of_sample = np.zeros(va_idx.shape[0], dtype=np.float64)
    for _pi, ser in enumerate(bundle.series):
        m = p_va == ser.pair
        if not m.any():
            continue
        if getattr(ser, "book_present", None) is not None:
            book_of_sample[m] = ser.book_present[bundle.t_i[va_idx[m]]].astype(np.float64)

    loader = DataLoader(
        LazyMultiHorizonDataset(bundle, va_idx, horizon_keys),
        batch_size=64,
        shuffle=False,
        collate_fn=collate_mh,
        num_workers=0,
    )

    # The dataset emits "__pair_idx" in THIS bundle's series order while the
    # embedding is indexed by the TRAINED pair vocab, so a translation LUT is needed
    # per member — built inside the member loop below, since two checkpoints can
    # legitimately carry different vocabularies.

    all_logits = {h: [] for h in horizon_keys}
    all_dir = {h: [] for h in horizon_keys}
    all_y = {h: [] for h in horizon_keys}
    all_quant = {h: [] for h in horizon_keys}
    all_ret = {h: [] for h in horizon_keys}

    # Running PROBABILITY sums across ensemble members. Summing probabilities (not
    # logits) is the whole point: logit averaging is a geometric mean of
    # probabilities and would quietly change the calibration this eval reports on,
    # which is the very property the ensemble exists to improve.
    prob_sum = {h: None for h in horizon_keys}
    dir_prob_sum = {h: None for h in horizon_keys}
    quant_sum = {h: None for h in horizon_keys}

    for mi, member in enumerate(members):
        if mi > 0:
            # Restore raw features, then normalize with THIS member's statistics.
            # The norm range report stays ON for every member: `BROKEN SCALE` is a
            # run-validity check (docs/NEXT_TRAINING_PLAN.md 0.4) and suppressing it
            # for members 1..N would let a bad member into an ensemble unnoticed.
            print(f"  ensemble member {mi} ({member['path'].name}):")
            for ser, raw in zip(bundle.series, raw_feats):
                np.copyto(ser.feats, raw)
            _normalize_for(member["meta"], report=True)

        m_vocab = list(member["meta"].get("pair_vocab") or [])
        m_embed = int(member["meta"].get("pair_embed_dim", 0))
        if m_embed > 0:
            m_to_id = {q: i for i, q in enumerate(m_vocab)}
            m_lut = np.array(
                [m_to_id.get(ser.pair, len(m_vocab)) for ser in bundle.series],
                dtype=np.int64,
            )
        else:
            m_lut = None

        parts_logits = {h: [] for h in horizon_keys}
        parts_dir = {h: [] for h in horizon_keys}
        parts_quant = {h: [] for h in horizon_keys}
        with torch.no_grad():
            for xb, yb in loader:
                xb = xb.to(device)
                pair_idx = yb.get("__pair_idx")
                if pair_idx is not None and m_lut is not None:
                    pair_idx = torch.from_numpy(m_lut[pair_idx.numpy()]).to(device)
                else:
                    pair_idx = None
                out, dir_out, quant_out = member["model"].forward_all(xb, pair_idx)
                for h in horizon_keys:
                    parts_logits[h].append(out[h].cpu())
                    if dir_out is not None:
                        parts_dir[h].append(dir_out[h].cpu())
                    if quant_out is not None:
                        parts_quant[h].append(quant_out[h].cpu())
                    # Labels and forward returns come from the bundle, not the model,
                    # so they are identical for every member — collect them once.
                    if mi == 0:
                        all_y[h].append(yb[h].cpu())
                        all_ret[h].append(yb[f"ret_{h}"].cpu())

        for h in horizon_keys:
            pr = torch.softmax(torch.cat(parts_logits[h], dim=0), dim=-1)
            prob_sum[h] = pr if prob_sum[h] is None else prob_sum[h] + pr
            if parts_dir[h]:
                dpr = torch.softmax(torch.cat(parts_dir[h], dim=0), dim=-1)
                dir_prob_sum[h] = dpr if dir_prob_sum[h] is None else dir_prob_sum[h] + dpr
            if parts_quant[h]:
                q = torch.cat(parts_quant[h], dim=0)
                quant_sum[h] = q if quant_sum[h] is None else quant_sum[h] + q

    n_members = len(members)
    for h in horizon_keys:
        all_logits[h] = [probs_to_logits(prob_sum[h] / n_members)]
        if dir_prob_sum[h] is not None:
            all_dir[h] = [probs_to_logits(dir_prob_sum[h] / n_members)]
        if quant_sum[h] is not None:
            all_quant[h] = [quant_sum[h] / n_members]

    # --- C13: the served gate is derived from a COVERAGE target ------------------
    # Done here, before any table is printed, so every "serve gate" row below marks
    # the operating point this checkpoint would actually run at rather than a global
    # constant tuned on some earlier model's confidence scale.
    served_gate = None
    if primary in horizon_keys and all_dir[primary]:
        _p_dir = all_dir[primary][0]
        served_gate = derive_served_gate(
            dir_logits_to_three_class(_p_dir),
            torch.cat(all_y[primary], dim=0),
            _p_dir,
            torch.cat(all_ret[primary], dim=0) if all_ret[primary] else None,
            t_va,
            p_va,
            horizon_bars(eval_interval, int(primary)),
            float(args.target_coverage),
        )
        SERVED_GATE = float(served_gate["conf_threshold"])
        SERVED_GATE_SOURCE = f"derived@cov{args.target_coverage:g}"
    else:
        print(
            "NOTE: no directional head on the primary horizon — the served gate "
            f"falls back to the config constant GATE_THRESHOLD={GATE_THRESHOLD}."
        )

    thresholds = [float(t) for t in args.gate.split(",") if t.strip()]
    thresholds = sorted(set(thresholds + [GATE_THRESHOLD, SERVED_GATE]))

    report = {
        "n_val": int(va_idx.shape[0]),
        "horizons": {},
        "meta": {k: v for k, v in meta.items() if k != "norm_stats"},
        "val_time_start": _ns_to_iso(int(t_va.min())),
        "val_time_end": _ns_to_iso(int(t_va.max())),
    }

    print(f"M2 Eval | val samples={va_idx.shape[0]} | horizons={horizons}")
    if served_gate:
        me = served_gate["measured"]
        print(
            f"SERVED GATE (C13, coverage-targeted): trade the top "
            f"{served_gate['target_coverage']*100:.3g}% of bars by confidence on the "
            f"primary {primary}m head → conf >= {served_gate['conf_threshold']:.4f}"
        )
        print(
            f"  measured here: n_gated={me['n_gated']} dir_acc={me['dir_acc']:.3f} "
            f"lb={me['wilson_lb']:.3f} "
            + (
                f"trades={me['n_trades']} gross={me['gross_bps_per_trade']:+.2f}bps/trade "
                f"net@taker={me['net_bps_per_trade']['taker']:+.2f} "
                f"net@maker={me['net_bps_per_trade']['maker']:+.2f}"
                if "n_trades" in me
                else ""
            )
        )
        print(
            f"  config GATE_THRESHOLD={GATE_THRESHOLD} is NOT used for the rows marked "
            f"'*' below — an absolute threshold means a different coverage on every "
            f"checkpoint (see docs/NEXT_TRAINING_PLAN.md 1.5)."
        )
    print("=" * 60)

    dump_rows = []
    for h in horizon_keys:
        logits = torch.cat(all_logits[h], dim=0)
        y_true = torch.cat(all_y[h], dim=0)
        dir_logits = torch.cat(all_dir[h], dim=0) if all_dir[h] else None
        fwd_ret = torch.cat(all_ret[h], dim=0) if all_ret[h] else None
        hold_bars = horizon_bars(eval_interval, int(h))
        if args.dump_preds:
            dump_rows.append(
                pred_rows(h, logits, dir_logits, y_true, fwd_ret, t_va, p_va, book_of_sample)
            )
        result = run_horizon_report(
            logits,
            y_true,
            thresholds,
            pair_ids=p_va,
            dir_logits=dir_logits,
            fwd_ret=fwd_ret,
            times=t_va,
            hold_bars=hold_bars,
        )

        print(f"\n--- Horizon {h}m {'(PRIMARY)' if h == primary else ''} ---")
        print(f"Ungated accuracy (3-class argmax): {result['ungated_acc']:.4f}")
        print("Confusion (rows=true down/flat/up, cols=pred):")
        print(result["conf_matrix_tensor"].numpy())
        print(
            f"Directional gate: conf=max(p_up,p_down); trade when conf>=threshold "
            f"(SERVED gate={SERVED_GATE:.4f}, source={SERVED_GATE_SOURCE})"
        )
        print(
            f"P&L sim: round-trip cost={ROUND_TRIP_COST*1e4:.1f}bps, hold={hold_bars} bars, "
            f"1 serial position/pair"
        )
        print(
            f"{'gate':>8}  {'coverage':>8}  {'n_gated':>8}  {'gated_acc':>10}  "
            f"{'dir_acc':>8}  {'edge':>6}  {'net_ret':>9}  {'trades':>7}  "
            f"{'win':>5}  {'sharpe':>7}  {'maxdd':>9}  {'mean_conf':>9}"
        )
        for row in result["sweep_rows"]:
            edge = (row.get("gated_dir_acc") or 0.0) - 0.5 if row.get("n_gated", 0) else 0.0
            marker = " *" if abs(row["threshold"] - SERVED_GATE) < 1e-9 else ""
            nr = row.get("net_ret")
            nr_s = f"{nr:+.4f}" if nr is not None else "   n/a  "
            sh = row.get("daily_sharpe")
            sh_s = f"{sh:.2f}" if sh is not None else "   n/a"
            print(
                f"{row['threshold']:8.4f}  {row['coverage']:8.3f}  {row['n_gated']:8d}  "
                f"{row['gated_acc']:10.3f}  {row.get('gated_dir_acc', 0):8.3f}  "
                f"{edge:6.3f}  {nr_s:>9}  {row.get('n_trades', 0):7d}  "
                f"{row.get('win_rate', 0):5.3f}  {sh_s:>7}  {row.get('max_dd', 0):9.4f}  "
                f"{row.get('mean_conf_gated', 0):9.3f}{marker}"
            )

        # The served gate is an ABSOLUTE confidence threshold, but the confidence
        # scale drifts between checkpoints — so a model can be perfectly good and
        # still never reach it, in which case serving it trades nothing at all.
        # That used to be invisible: GATE_THRESHOLD defaulted to 0.40, below the
        # conf>=0.5 floor, so the serve row always showed coverage 1.0. Say it out
        # loud now, because it is a promote-blocking fact about the checkpoint.
        serve_r = next(
            (r for r in result["sweep_rows"] if abs(r["threshold"] - SERVED_GATE) < 1e-9),
            None,
        )
        if serve_r is not None and int(serve_r.get("n_gated", 0)) == 0:
            top_conf = max(
                (r["threshold"] for r in result["sweep_rows"] if r.get("n_gated", 0) > 0),
                default=None,
            )
            scope = (
                "this checkpoint would never trade at all"
                if h == primary
                else f"the {h}m head would never fire (the gate is derived on the "
                f"primary {primary}m head, and serve.py applies one threshold to "
                f"every horizon)"
            )
            print(
                f"  ⚠️  WARNING: at the SERVED gate {SERVED_GATE:.4f} this head gates "
                f"ZERO bars — {scope}. Highest swept threshold with any coverage: "
                f"{top_conf if top_conf is not None else 'none'}."
            )

        print(
            "Fixed-coverage directional edge "
            "(top-x% by confidence; stable across models):"
        )
        print(
            f"{'cov':>6}  {'n_gated':>8}  {'conf_thr':>8}  {'dir_acc':>8}  "
            f"{'edge':>6}  {'wilson_lb':>9}  {'n_dir':>7}"
        )
        for fc in result["fixed_coverage"]:
            print(
                f"{fc['coverage']:6.3f}  {fc['n_gated']:8d}  {fc['conf_threshold']:8.3f}  "
                f"{fc['dir_acc']:8.3f}  {fc['edge']:6.3f}  {fc['dir_acc_wilson_lb']:9.3f}  "
                f"{fc['n_true_directional_gated']:7d}"
            )

        # P&L on the same fixed-coverage slices, at both cost models. `gross` is
        # the durable number: it is what the model actually earns before any fee
        # assumption, so it is what arms should be ranked on. A cost model only
        # decides whether that gross clears the toll.
        fcp = [p for p in (result.get("fixed_coverage_pnl") or []) if p]
        if fcp:
            taker_bps = ROUND_TRIP_COST * 1e4
            maker_bps = MAKER_ROUND_TRIP_COST * 1e4
            print(
                "Fixed-coverage P&L (same slices; net is exactly "
                "gross - trades x cost, so no re-run is needed to change fees):"
            )
            print(
                f"{'cov':>6}  {'trades':>7}  {'gross':>9}  {'gross_bps':>9}  "
                f"{'net@' + format(taker_bps, '.0f') + 'bps':>12}  "
                f"{'bps/trade':>9}  "
                f"{'net@' + format(maker_bps, '.0f') + 'bps':>12}  "
                f"{'bps/trade':>9}  {'win':>5}"
            )
            for p in fcp:
                tk = p["net"]["taker"]
                mk = p["net"]["maker"]
                print(
                    f"{p['coverage']:6.3f}  {p['n_trades']:7d}  {p['gross_ret']:+9.4f}  "
                    f"{p['gross_bps_per_trade']:+9.2f}  {tk['net_ret']:+12.4f}  "
                    f"{tk['net_bps_per_trade']:+9.2f}  {mk['net_ret']:+12.4f}  "
                    f"{mk['net_bps_per_trade']:+9.2f}  {p['win_rate']:5.3f}"
                )

        # Directional symmetry ("one-mode" test): is the edge/P&L two-sided, or
        # does the model only really trade/win on one side?
        ss = result.get("side_split_cov05") or {}
        if ss:
            print("Side split @ fixed-cov 0.05 (did it learn one mode?):")
            print(f"  {'side':>5}  {'n_gated':>8}  {'n_dir':>7}  {'dir_acc':>8}  {'wilson_lb':>9}")
            for name in ("up", "down"):
                s = ss.get(name) or {}
                print(
                    f"  {name:>5}  {int(s.get('n_gated', 0)):8d}  {int(s.get('n_dir', 0)):7d}  "
                    f"{float(s.get('dir_acc', 0.0)):8.3f}  {float(s.get('wilson_lb', 0.0)):9.3f}"
                )
        ls = result.get("long_short_pnl")
        if ls:
            print(f"Long/short serial P&L @ serve gate {SERVED_GATE:.4f} (net of cost):")
            for name in ("long", "short"):
                v = ls.get(name) or {}
                sh = v.get("daily_sharpe")
                sh_s = f"{sh:.2f}" if sh is not None else "n/a"
                print(
                    f"  {name:>5}: net_ret={v.get('net_ret', 0.0):+.4f} "
                    f"trades={int(v.get('n_trades', 0))} win={v.get('win_rate', 0.0):.3f} "
                    f"sharpe={sh_s} maxdd={v.get('max_dd', 0.0):.4f}"
                )

        # Book-era split of the directional edge (calendar-time confound). If the
        # edge concentrates in the book era, it's the zero→real feature
        # discontinuity, not learned microstructure.
        gate_logits_h = (
            dir_logits_to_three_class(dir_logits) if dir_logits is not None else logits
        )
        book_split = book_era_edge_split(gate_logits_h, y_true, book_of_sample, 0.05)
        if any(book_split.values()):
            print("Book-era split of fixed-cov 0.05 edge (dir_acc / wilson_lb / n_dir):")
            for k in ("book", "pre_book"):
                v = book_split.get(k)
                if v:
                    print(
                        f"  {k:>9}: n={v['n']} dir_acc={v['dir_acc']:.3f} "
                        f"lb={v['wilson_lb']:.3f} n_dir={v['n_dir']}"
                    )

        if result["per_pair"]:
            print("Per-pair @ serve gate  |  fixed-cov 0.05 (dir_acc / wilson_lb / n_dir):")
            for pair, pr in result["per_pair"].items():
                row = next(
                    (r for r in pr["gate_sweep"] if abs(r["threshold"] - SERVED_GATE) < 1e-9),
                    None,
                )
                fc05 = next(
                    (f for f in pr.get("fixed_coverage", []) if abs(f["coverage"] - 0.05) < 1e-9),
                    None,
                )
                serve_part = (
                    f"cov={row['coverage']:.3f} dir_acc={row.get('gated_dir_acc', 0):.3f}"
                    if row
                    else "cov=n/a"
                )
                fc_part = (
                    f"cov0.05 dir_acc={fc05['dir_acc']:.3f} lb={fc05['dir_acc_wilson_lb']:.3f} "
                    f"n_dir={fc05['n_true_directional_gated']}"
                    if fc05
                    else ""
                )
                print(
                    f"  {pair}: n={pr['n']} ungated={pr['ungated_acc']:.3f} "
                    f"{serve_part}  |  {fc_part}"
                )

        cal_dir = None
        if h == primary and dir_logits is not None:
            cal_dir = calibration_report(dir_logits, y_true)
            print(f"\nDirectional head calibration (primary {h}m, moved bars only):")
            print(f"  brier={cal_dir['brier']} n_moved={cal_dir['n_moved']}")
            print(f"  {'p(up) bin':>10}  {'n':>8}  {'mean_pred':>10}  {'emp_up':>8}")
            for b in cal_dir["bins"]:
                mp = f"{b['mean_pred']:.3f}" if b["mean_pred"] is not None else "   -  "
                eu = f"{b['empirical_up']:.3f}" if b["empirical_up"] is not None else "   -  "
                print(f"  {b['bin']:>10}  {b['n']:8d}  {mp:>10}  {eu:>8}")

        calib = None
        if all_quant[h]:
            q_cat = torch.cat(all_quant[h], dim=0)
            r_cat = torch.cat(all_ret[h], dim=0)
            calib = quantile_calibration(q_cat, r_cat, quant_levels)
            lvl_str = " ".join(
                f"p{int(round(pl['level']*100))}={pl['empirical_below']:.3f}"
                for pl in calib["per_level"]
            )
            print(
                f"Quantile calibration: band[p{int(round(quant_levels[0]*100))}-"
                f"p{int(round(quant_levels[-1]*100))}] coverage={calib['band_coverage']:.3f} "
                f"(target {calib['band_target']:.2f})  emp_below[{lvl_str}]  "
                f"p50_MAE={calib['p50_mae']:.5f}"
            )

        report["horizons"][h] = {
            "ungated_acc": result["ungated_acc"],
            "confusion": result["confusion"],
            "gate_sweep": result["gate_sweep"],
            "fixed_coverage": result["fixed_coverage"],
            "side_split_cov05": result.get("side_split_cov05"),
            "long_short_pnl": result.get("long_short_pnl"),
            "quantile_calibration": calib,
            "directional_calibration": cal_dir,
            "book_era_split": book_split,
            "serve_gate_dir_edge_vs_half": result["serve_gate_dir_edge_vs_half"],
            "per_pair": {
                k: {
                    "n": v["n"],
                    "ungated_acc": v["ungated_acc"],
                    "gate_sweep": v["gate_sweep"],
                    "fixed_coverage": v.get("fixed_coverage", []),
                }
                for k, v in result["per_pair"].items()
            },
        }

    # --- Walk-forward + baselines on the primary horizon (holdout window) ----
    if primary in horizon_keys:
        pk = primary
        wf_y = torch.cat(all_y[pk], dim=0)
        fwd_ret_pk = torch.cat(all_ret[pk], dim=0) if all_ret[pk] else None
        if all_dir[pk]:
            wf_gate = dir_logits_to_three_class(torch.cat(all_dir[pk], dim=0))
        else:
            wf_gate = torch.cat(all_logits[pk], dim=0)
        hb = horizon_bars(eval_interval, int(pk))

        print(
            f"\n--- Walk-forward edge on val window (primary {pk}m, split into "
            f"{WF_WINDOWS} time windows) ---"
        )
        wf = walk_forward_edge(wf_gate, wf_y, t_va, WF_WINDOWS, book=book_of_sample)
        print(
            f"{'win':>4}  {'n':>9}  {'start':>16}  {'end':>16}  {'book':>6}  "
            f"{'cov05':>7}  {'lb':>5}  {'n_dir':>6}  {'cov10':>7}  {'lb':>5}  {'n_dir':>6}"
        )
        for w in wf:
            c5, c10 = w["cov05"], w["cov10"]
            bk = f"{w['frac_book']:.2f}" if w["frac_book"] is not None else "  -"
            print(
                f"{w['window']:4d}  {w['n']:9d}  {w['start']:>16}  {w['end']:>16}  {bk:>6}  "
                f"{c5['dir_acc']:7.3f}  {c5['wilson_lb']:5.3f}  {c5['n_dir']:6d}  "
                f"{c10['dir_acc']:7.3f}  {c10['wilson_lb']:5.3f}  {c10['n_dir']:6d}"
            )
        report["walk_forward"] = wf

        # Momentum baseline (sign of trailing hb-bar return).
        mom_gate = momentum_gate_logits(bundle, va_idx, hb)
        print(f"\n--- Momentum baseline (sign of trailing {hb} bar return), val window ---")
        mom_fc = []
        for cov in (0.02, 0.05, 0.10, 0.20):
            fc = fixed_coverage_metrics(mom_gate, wf_y, cov)
            mom_fc.append(
                {
                    "coverage": cov,
                    "dir_acc": round(float(fc.get("dir_acc", 0.0)), 4),
                    "wilson_lb": round(float(fc.get("dir_acc_wilson_lb", 0.0)), 4),
                    "n_dir": int(fc.get("n_true_directional_gated") or 0),
                }
            )
            print(
                f"  cov{cov:.2f}: dir_acc={mom_fc[-1]['dir_acc']:.3f} "
                f"lb={mom_fc[-1]['wilson_lb']:.3f} n_dir={mom_fc[-1]['n_dir']}"
            )
        pnl_m = None
        if fwd_ret_pk is not None:
            side_m, conf_m = directional_signal(mom_gate)
            mask_m = conf_m >= GATE_THRESHOLD
            pnl_m = simulate_pnl(side_m, conf_m, mask_m, fwd_ret_pk, t_va, p_va, hb)
            print(
                f"  momentum P&L @ config gate {GATE_THRESHOLD} (its own confidence "
                f"scale — the fixed-coverage rows above are the real comparison): "
                f"net_ret={pnl_m['total_net_ret']:+.4f} "
                f"trades={pnl_m['n_trades']} win={pnl_m['win_rate']} "
                f"sharpe={pnl_m['daily_sharpe']} maxdd={pnl_m['max_dd']}"
            )
        report["momentum_baseline"] = {"fixed_coverage": mom_fc, "pnl": pnl_m}

        # Buy-and-hold baseline: sum of forward returns per pair on the val window.
        print(f"\n--- Buy-and-hold ({pk}m forward returns, val window) ---")
        bnh = {}
        for _pi, ser in enumerate(bundle.series):
            m = p_va == ser.pair
            if m.any():
                r = ser.returns[pk][bundle.t_i[va_idx[m]]]
                bnh[ser.pair] = round(float(np.sum(r)), 5)
        pooled = round(float(sum(bnh.values())), 5)
        print(f"  {bnh}\n  pooled sum (net of 1 round trip) = {pooled:.5f}")
        report["buy_hold"] = {"per_pair": bnh, "pooled_sum": pooled}

    report["served_gate"] = served_gate
    report["served_gate_effective"] = {
        "conf_threshold": float(SERVED_GATE),
        "source": SERVED_GATE_SOURCE,
        "config_gate_threshold": float(GATE_THRESHOLD),
    }
    report["ensemble"] = {
        "n_members": len(members),
        "members": [m["path"].name for m in members],
    }

    out_path = Path(OUTPUT_DIR) / "eval_m2.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nWrote {out_path}")

    # --- C13: persist the operating point INTO the checkpoint --------------------
    # The training runner uploads the checkpoint after eval, so a normal run ships a
    # file that already knows the gate it should be served at. An ensemble has no
    # single file to write to; its gate is reported and must be carried by whatever
    # the ensemble is eventually served as.
    if served_gate and not args.no_write_gate_meta:
        if is_ensemble:
            print(
                "NOTE: ensemble eval — the derived gate is reported above and in "
                "eval_m2.json, but is NOT written into any member checkpoint (it "
                "belongs to the ensemble, not to any one member)."
            )
        elif write_served_gate_meta(ckpt_path, ckpt, served_gate):
            print(
                f"Wrote served_gate into {ckpt_path.name}: "
                f"conf>={served_gate['conf_threshold']:.4f} @ target coverage "
                f"{served_gate['target_coverage']:g}. serve.py reads this; the config "
                f"GATE_THRESHOLD is only a fallback."
            )

    if args.dump_preds:
        write_pred_dump(dump_rows, OUTPUT_DIR)

    print("\nInterpretation tips:")
    print("  dir_acc         → among gated trades with true up/down, fraction correct")
    print("  edge            → dir_acc - 0.5 (positive = better than coin flip)")
    print("  coverage        → fraction of bars that would trade")
    print(f"  * marker        → the SERVED gate {SERVED_GATE:.4f} ({SERVED_GATE_SOURCE})")
    print("  served gate     → derived so the top SERVE_TARGET_COVERAGE of bars trade;")
    print("                    it is a property of THIS checkpoint, not a global constant")
    print("  gated_acc       → also counts true-flat as miss (stricter than dir_acc)")
    print("  fixed-coverage  → edge at top-x% confidence; comparable across models")
    print("  wilson_lb       → conservative lower bound on dir_acc (small n → low)")
    print("  net_ret/sharpe  → serial per-pair P&L sim at round-trip cost (reporting only)")
    print("  gross_bps       → pre-cost bps per trade. THE durable number — rank arms on")
    print("                    this, not on a dir_acc-derived break-even (dir_acc assumes")
    print("                    right and wrong trades have the same |return|; they don't)")
    print(f"  net@Nbps        → gross - trades x cost. Exactly linear in cost, so a new fee")
    print("                    assumption never needs a re-run — just recompute it")
    print("  gate floor      → conf >= 0.50 by construction; any gate <= 0.50 trades all bars")
    print("  book-era split  → if edge lives only in 'book', it's a calendar confound")
    print("  walk-forward    → edge across disjoint time windows (is it stable?)")
    print("  momentum/BnH    → trivial baselines the model must beat")


if __name__ == "__main__":
    main()
