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
    MODEL_DIR,
    OUTPUT_DIR,
    PAIRS,
    ROUND_TRIP_COST,
    SEQ_LEN,
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
)
from data.db import load_whitelist_pairs
from gate import (
    dir_logits_to_three_class,
    directional_signal,
    fixed_coverage_metrics,
    gate_sweep,
    side_split_metrics,
)
from models.multi_horizon import SharedEncoderMultiHead

# Coverages at which to report a stable, cross-model-comparable directional edge.
FIXED_COVERAGES = [0.01, 0.02, 0.05, 0.10, 0.20]

# Bar duration in seconds (1m candles) — used by the serial P&L hold logic.
BAR_SECONDS = 60


def collate_mh(batch):
    xs = torch.stack([b[0] for b in batch], dim=0)
    keys = batch[0][1].keys()
    ys = {k: torch.stack([b[1][k] for b in batch], dim=0) for k in keys}
    return xs, ys


def _ns_to_iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _ns_to_day(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%d")


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
    day_net: Dict[str, float] = {}
    for d, n in booked:
        day_net[d] = day_net.get(d, 0.0) + n
    day_list = np.array(sorted(day_net.values()), dtype=np.float64)
    daily_sharpe = None
    max_dd = 0.0
    if day_list.size >= 2:
        eq = np.cumsum(day_list)
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

    # Directional-symmetry diagnostics ("one-mode" test): per-side accuracy at
    # fixed cov 0.05, and per-side serial P&L at the serve gate.
    side_split = side_split_metrics(gate_logits, y_true, 0.05)
    ls_pnl = None
    if fwd_ret is not None and times is not None and hold_bars is not None:
        ls_pnl = long_short_pnl_split(
            dir_logits, y_true, fwd_ret, times, pair_ids, hold_bars, GATE_THRESHOLD, cost
        )

    serve_row = next((r for r in sweep if abs(r["threshold"] - GATE_THRESHOLD) < 1e-9), None)
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
        "side_split_cov05": side_split,
        "long_short_pnl": ls_pnl,
        "serve_gate": GATE_THRESHOLD,
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
        default="0.35,0.40,0.45,0.50,0.55,0.60",
        help="Comma-separated confidence thresholds",
    )
    p.add_argument(
        "--pairs",
        default="",
        help="Comma-separated pairs. Default: UI whitelist from DB.",
    )
    args = p.parse_args()

    device = torch.device(args.device)
    ckpt_path = Path(args.checkpoint)
    if not ckpt_path.exists():
        print(f"Checkpoint not found: {ckpt_path}")
        sys.exit(1)

    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    meta = ckpt.get("meta", {})
    horizons = meta.get("horizons_minutes") or HORIZONS_MINUTES
    horizon_keys = meta.get("horizon_keys") or [str(h) for h in horizons]
    seq_len = meta.get("seq_len", SEQ_LEN)
    feature_dim = meta.get("feature_dim", FEATURE_DIM)
    hidden = meta.get("hidden_size", HIDDEN_SIZE)
    num_layers = int(meta.get("num_layers", 2))  # pre-capacity ckpts had 2
    norm_stats = meta.get("norm_stats") or {}
    primary = str(meta.get("primary_horizon", horizons[min(1, len(horizons) - 1)]))
    has_dir_head = bool(meta.get("directional_head", False))
    has_quant_head = bool(meta.get("quantile_head", False))
    quant_levels = meta.get("quantile_levels") or [0.1, 0.5, 0.9]

    model = SharedEncoderMultiHead(
        input_size=feature_dim,
        hidden_size=hidden,
        horizons_minutes=horizons,
        directional_head=has_dir_head,
        quantile_head=has_quant_head,
        quantile_levels=quant_levels,
        num_layers=num_layers,
    ).to(device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    print(f"Directional head: {'ON — gating uses aux up/down signal' if has_dir_head else 'off'}")

    if args.pairs.strip():
        pairs = [x.strip().upper() for x in args.pairs.split(",") if x.strip()]
    else:
        pairs = meta.get("pairs") or load_whitelist_pairs(fallback=PAIRS)
    print(f"Eval pairs: {pairs}")
    print(f"Checkpoint primary={primary}m seq_len={seq_len} norm={meta.get('norm', 'legacy')}")

    bundle = build_m2_index_bundle(pairs=pairs, seq_len=seq_len, horizons_minutes=horizons)
    tr_idx, va_idx = time_split_indices(bundle.times, VAL_FRACTION)

    if norm_stats:
        apply_norm_to_bundle(bundle, norm_stats)
    else:
        legacy = fit_norm_from_bundle(bundle, tr_idx)
        apply_norm_to_bundle(bundle, legacy)
        print("Warning: checkpoint has no norm_stats; fitted from current train split")

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

    all_logits = {h: [] for h in horizon_keys}
    all_dir = {h: [] for h in horizon_keys}
    all_y = {h: [] for h in horizon_keys}
    all_quant = {h: [] for h in horizon_keys}
    all_ret = {h: [] for h in horizon_keys}

    with torch.no_grad():
        for xb, yb in loader:
            xb = xb.to(device)
            out, dir_out, quant_out = model.forward_all(xb)
            for h in horizon_keys:
                all_logits[h].append(out[h].cpu())
                all_y[h].append(yb[h].cpu())
                # Raw forward return per horizon (P&L sim + baselines); always emitted.
                all_ret[h].append(yb[f"ret_{h}"].cpu())
                if dir_out is not None:
                    all_dir[h].append(dir_out[h].cpu())
                if quant_out is not None:
                    all_quant[h].append(quant_out[h].cpu())

    thresholds = [float(t) for t in args.gate.split(",") if t.strip()]
    if GATE_THRESHOLD not in thresholds:
        thresholds = sorted(set(thresholds + [GATE_THRESHOLD]))

    report = {
        "n_val": int(va_idx.shape[0]),
        "horizons": {},
        "meta": {k: v for k, v in meta.items() if k != "norm_stats"},
        "val_time_start": _ns_to_iso(int(t_va.min())),
        "val_time_end": _ns_to_iso(int(t_va.max())),
    }

    print(f"M2 Eval | val samples={va_idx.shape[0]} | horizons={horizons}")
    print("=" * 60)

    for h in horizon_keys:
        logits = torch.cat(all_logits[h], dim=0)
        y_true = torch.cat(all_y[h], dim=0)
        dir_logits = torch.cat(all_dir[h], dim=0) if all_dir[h] else None
        fwd_ret = torch.cat(all_ret[h], dim=0) if all_ret[h] else None
        hold_bars = horizon_bars(CANDLE_INTERVAL, int(h))
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
            f"(serve default GATE_THRESHOLD={GATE_THRESHOLD})"
        )
        print(
            f"P&L sim: round-trip cost={ROUND_TRIP_COST*1e4:.1f}bps, hold={hold_bars} bars, "
            f"1 serial position/pair"
        )
        print(
            f"{'gate':>6}  {'coverage':>8}  {'n_gated':>8}  {'gated_acc':>10}  "
            f"{'dir_acc':>8}  {'edge':>6}  {'net_ret':>9}  {'trades':>7}  "
            f"{'win':>5}  {'sharpe':>7}  {'maxdd':>9}  {'mean_conf':>9}"
        )
        for row in result["sweep_rows"]:
            edge = (row.get("gated_dir_acc") or 0.0) - 0.5 if row.get("n_gated", 0) else 0.0
            marker = " *" if abs(row["threshold"] - GATE_THRESHOLD) < 1e-9 else ""
            nr = row.get("net_ret")
            nr_s = f"{nr:+.4f}" if nr is not None else "   n/a  "
            sh = row.get("daily_sharpe")
            sh_s = f"{sh:.2f}" if sh is not None else "   n/a"
            print(
                f"{row['threshold']:6.2f}  {row['coverage']:8.3f}  {row['n_gated']:8d}  "
                f"{row['gated_acc']:10.3f}  {row.get('gated_dir_acc', 0):8.3f}  "
                f"{edge:6.3f}  {nr_s:>9}  {row.get('n_trades', 0):7d}  "
                f"{row.get('win_rate', 0):5.3f}  {sh_s:>7}  {row.get('max_dd', 0):9.4f}  "
                f"{row.get('mean_conf_gated', 0):9.3f}{marker}"
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
            print(f"Long/short serial P&L @ serve gate {GATE_THRESHOLD} (net of cost):")
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
                    (r for r in pr["gate_sweep"] if abs(r["threshold"] - GATE_THRESHOLD) < 1e-9),
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
        hb = horizon_bars(CANDLE_INTERVAL, int(pk))

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
                f"  momentum P&L @ gate {GATE_THRESHOLD}: net_ret={pnl_m['total_net_ret']:+.4f} "
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

    out_path = Path(OUTPUT_DIR) / "eval_m2.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nWrote {out_path}")

    print("\nInterpretation tips:")
    print("  dir_acc         → among gated trades with true up/down, fraction correct")
    print("  edge            → dir_acc - 0.5 (positive = better than coin flip)")
    print("  coverage        → fraction of bars that would trade")
    print(f"  * marker        → serve GATE_THRESHOLD={GATE_THRESHOLD}")
    print("  gated_acc       → also counts true-flat as miss (stricter than dir_acc)")
    print("  fixed-coverage  → edge at top-x% confidence; comparable across models")
    print("  wilson_lb       → conservative lower bound on dir_acc (small n → low)")
    print("  net_ret/sharpe  → serial per-pair P&L sim at round-trip cost (reporting only)")
    print("  book-era split  → if edge lives only in 'book', it's a calendar confound")
    print("  walk-forward    → edge across disjoint time windows (is it stable?)")
    print("  momentum/BnH    → trivial baselines the model must beat")


if __name__ == "__main__":
    main()
