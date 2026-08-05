#!/usr/bin/env python3
"""M2 training: shared encoder + multi-horizon heads + gated checkpoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.multiprocessing as torch_mp
import torch.nn as nn
from torch.utils.data import DataLoader

# DataLoader workers share sampled tensors with the main process. PyTorch's
# default 'file_descriptor' strategy consumes one FD per shared tensor; with a
# large val set (100k+ windows) and persistent_workers, this exhausts the
# process FD limit ("RuntimeError: Too many open files"). 'file_system' uses
# named shm files instead of per-tensor FDs, so it does not scale with N.
try:
    torch_mp.set_sharing_strategy("file_system")
except (RuntimeError, ValueError):  # e.g. platform without file_system strategy
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    BATCH_SIZE,
    CAL_PENALTY_WEIGHT,
    CAL_TARGET,
    CAL_TOL,
    CKPT_GATE_THRESHOLD,
    CLS_LABEL_SMOOTHING,
    CLS_WEIGHT_CLIP,
    CLS_WEIGHT_MODE,
    DIR_LOSS_WEIGHT,
    DIRECTIONAL_HEAD,
    EARLY_STOP_PATIENCE,
    EPOCHS,
    FEATURE_DIM,
    HIDDEN_SIZE,
    DROPOUT,
    HORIZONS_MINUTES,
    LR,
    MIN_GATED_FOR_CKPT,
    MODEL_DIR,
    OUTPUT_DIR,
    PAIRS,
    PRIMARY_HORIZON,
    QUANTILE_HEAD,
    QUANTILE_LEVELS,
    QUANTILE_LOSS_WEIGHT,
    SEL_COVERAGE,
    SEQ_LEN,
    VAL_FRACTION,
    WEIGHT_DECAY,
)
from data.dataset import (
    LazyMultiHorizonDataset,
    apply_norm_to_bundle,
    build_m2_index_bundle,
    class_balance,
    fit_norm_from_bundle,
    labels_for_indices,
    pair_ids_for_indices,
    time_split_indices,
    time_split_indices_window,
)
from data.db import load_whitelist_pairs, table_counts
from data.features import BOOK_FEATURES
from gate import dir_logits_to_three_class, fixed_coverage_metrics, gate_metrics
from models.multi_horizon import SharedEncoderMultiHead


def parse_args():
    p = argparse.ArgumentParser(description="FluxTrader M2 multi-horizon train")
    p.add_argument("--epochs", type=int, default=EPOCHS)
    p.add_argument("--device", type=str, default="cpu")
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    p.add_argument("--seq-len", type=int, default=SEQ_LEN)
    p.add_argument(
        "--pairs",
        type=str,
        default="",
        help="Comma-separated pairs. Default: UI whitelist from DB, else config majors.",
    )
    p.add_argument(
        "--horizons",
        type=str,
        default=",".join(str(h) for h in HORIZONS_MINUTES),
        help="Comma-separated horizon minutes, e.g. 5,30,60",
    )
    p.add_argument(
        "--primary",
        type=int,
        default=PRIMARY_HORIZON,
        help="Horizon used for best-ckpt selection",
    )
    p.add_argument("--lr", type=float, default=LR)
    p.add_argument("--weight-decay", type=float, default=WEIGHT_DECAY)
    p.add_argument("--patience", type=int, default=EARLY_STOP_PATIENCE)
    p.add_argument(
        "--ckpt-gate",
        type=float,
        default=CKPT_GATE_THRESHOLD,
        help="Directional gate threshold for checkpoint score",
    )
    p.add_argument(
        "--num-workers",
        type=int,
        default=2,
        help="DataLoader workers (0 = main process only, lowest RAM; 2 parallelizes window slicing)",
    )
    p.add_argument(
        "--require-book",
        action="store_true",
        help="Dense-window run: only use samples whose full window has book data (has_book==1).",
    )
    p.add_argument(
        "--ablate-book",
        action="store_true",
        help="Zero all microstructure (book/trade/OI) features — the book-OFF arm of the ablation.",
    )
    p.add_argument(
        "--val-frac",
        type=float,
        default=None,
        help="Val window size as a fraction of time-ordered samples (default: VAL_FRACTION).",
    )
    p.add_argument(
        "--val-offset",
        type=float,
        default=0.0,
        help=(
            "Walk-forward: end the val window this fraction of samples from the "
            "latest sample; train = samples strictly before the val window. "
            "0.0 = newest window (== trailing split). Step by --val-frac for "
            "non-overlapping rolling-origin folds."
        ),
    )
    return p.parse_args()


def multi_loss(logits_dict, y_dict, crits, horizon_keys):
    loss = 0.0
    for h in horizon_keys:
        loss = loss + crits[h](logits_dict[h], y_dict[h])
    return loss / len(horizon_keys)


def directional_loss(dir_logits_dict, y_dict, dir_crits, horizon_keys):
    """
    Binary up/down CE per horizon, computed ONLY on bars that actually moved
    (true label != flat). Bars where nothing moved contribute no gradient, so
    this head learns a clean up-vs-down boundary undiluted by the flat mass.
    Returns (loss, n_directional_bars) averaged over horizons.
    """
    total = 0.0
    n_h = 0
    for h in horizon_keys:
        y = y_dict[h]
        move = y != 1  # directional bars only
        if move.sum() == 0:
            continue
        # map 3-class {0=down,2=up} -> 2-class {0=down,1=up}
        y_dir = (y[move] == 2).long()
        total = total + dir_crits[h](dir_logits_dict[h][move], y_dir)
        n_h += 1
    if n_h == 0:
        return None
    return total / n_h


def quantile_loss(quant_dict, y_dict, horizon_keys, levels):
    """
    Pinball (quantile) loss on the raw forward return per horizon.

    quant_dict[h]: [B, n_q] predicted quantiles (sorted).
    y_dict["ret_<h>"]: [B] realized forward return.
    Averaged over horizons and quantile levels. All bars contribute (unlike the
    directional head) since a forward return exists for every valid sample.
    """
    lv = torch.tensor(levels, dtype=torch.float32, device=quant_dict[horizon_keys[0]].device)
    total = 0.0
    for h in horizon_keys:
        target = y_dict[f"ret_{h}"].unsqueeze(1)  # [B, 1]
        pred = quant_dict[h]  # [B, n_q]
        err = target - pred  # [B, n_q]
        # pinball: max(q*err, (q-1)*err)
        loss_h = torch.maximum(lv * err, (lv - 1.0) * err)
        total = total + loss_h.mean()
    return total / len(horizon_keys)


def multi_acc(logits_dict, y_dict, horizon_keys):
    accs = {}
    for h in horizon_keys:
        pred = logits_dict[h].argmax(dim=1)
        accs[h] = (pred == y_dict[h]).float().mean().item()
    return accs


def collate_mh(batch):
    xs = torch.stack([b[0] for b in batch], dim=0)
    keys = batch[0][1].keys()
    ys = {k: torch.stack([b[1][k] for b in batch], dim=0) for k in keys}
    return xs, ys


def _ns_to_iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def collect_primary_logits(model, loader, primary_key, device):
    logits_all, y_all = [], []
    model.eval()
    with torch.no_grad():
        for xb, yb in loader:
            xb = xb.to(device)
            out = model(xb)
            logits_all.append(out[primary_key].cpu())
            y_all.append(yb[primary_key].cpu())
    if not logits_all:
        return None, None
    return torch.cat(logits_all, dim=0), torch.cat(y_all, dim=0)


def checkpoint_score(
    logits: torch.Tensor,
    y: torch.Tensor,
    gate: float,
    min_gated: int,
    sel_coverage: float = SEL_COVERAGE,
) -> tuple[float, dict]:
    """
    Rank checkpoints by directional edge at a FIXED coverage (top-`sel_coverage`
    fraction of bars by confidence), using the Wilson lower bound of dir_acc so a
    lucky tiny sample cannot win. This replaces the old raw-dir_acc-at-threshold
    score, which selected on ~200 noisy samples.

    The threshold-based gate_metrics are still computed and returned for logging /
    checkpoint meta, but no longer drive selection.
    """
    fc = fixed_coverage_metrics(logits, y, sel_coverage)
    m = gate_metrics(logits, y, gate, mode="directional")
    m["fixed_coverage"] = fc

    n_dir = int(fc.get("n_true_directional_gated") or 0)
    lb = float(fc.get("dir_acc_wilson_lb") or 0.0)
    if n_dir < min_gated:
        # Not enough directional trades at target coverage to trust the edge.
        score = lb * (n_dir / max(min_gated, 1))
    else:
        score = lb
    return score, m


def main():
    args = parse_args()
    device = torch.device(
        args.device if args.device != "cuda" or torch.cuda.is_available() else "cpu"
    )
    # On CPU, pin BLAS/intra-op threads to all vCPUs (env OMP_NUM_THREADS if set).
    if device.type == "cpu":
        n_threads = int(os.environ.get("OMP_NUM_THREADS", "0") or 0)
        if n_threads > 0:
            torch.set_num_threads(n_threads)
        print(f"torch CPU threads: {torch.get_num_threads()}")
    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    horizon_keys = [str(h) for h in horizons]
    primary_key = str(args.primary)
    if primary_key not in horizon_keys:
        primary_key = horizon_keys[min(1, len(horizon_keys) - 1)]

    print("FluxTrader M2 Training (shared encoder + multi-head, lazy windows)")
    print("=" * 50)
    print(f"PyTorch {torch.__version__} | device={device}")
    print(f"Horizons (min): {horizons} | primary={primary_key}m | seq_len={args.seq_len}")
    print(f"lr={args.lr} wd={args.weight_decay} patience={args.patience} ckpt_gate={args.ckpt_gate}")
    print(f"hidden_size={HIDDEN_SIZE} dropout={DROPOUT}")

    print("\nDB table counts:")
    try:
        for k, v in table_counts().items():
            print(f"  {k}: {v}")
    except Exception as e:
        print(f"  DB error: {e}")
        sys.exit(1)

    if args.pairs.strip():
        pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    else:
        pairs = load_whitelist_pairs(fallback=PAIRS)
        if not pairs:
            pairs = list(PAIRS)
    print(f"Training pairs: {pairs}")

    ablate = list(BOOK_FEATURES) if args.ablate_book else None
    if args.require_book or args.ablate_book:
        print(
            f"Dense-window ablation: require_book={args.require_book} "
            f"ablate_book={args.ablate_book}"
            + (f" (zeroing {len(ablate)} book features)" if ablate else "")
        )
    bundle = build_m2_index_bundle(
        pairs=pairs,
        seq_len=args.seq_len,
        horizons_minutes=horizons,
        require_book=args.require_book,
        ablate_features=ablate,
    )
    meta = bundle.meta
    print(f"\nSamples: {meta.get('n_samples', 0)} | per pair: {meta.get('n_per_pair')}")
    print(f"Flat thresholds: {meta.get('flat_thresholds')}")
    feat_mb = sum(s.feats.nbytes for s in bundle.series) / (1024 * 1024)
    print(f"Feature matrices in RAM: {feat_mb:.1f} MiB (lazy windows — not full N×seq×F)")

    n = bundle.n_samples
    if n < 50:
        print("Not enough samples (need ~50+). Collect more data, then re-run.")
        if n < 10:
            sys.exit(2)

    val_frac = args.val_frac if args.val_frac is not None else VAL_FRACTION
    if args.val_offset and args.val_offset > 0.0:
        tr_idx, va_idx = time_split_indices_window(bundle.times, val_frac, args.val_offset)
        split_kind = "walkforward_window"
    else:
        tr_idx, va_idx = time_split_indices(bundle.times, val_frac)
        split_kind = "global_time"
    t_tr = bundle.times[tr_idx]
    t_va = bundle.times[va_idx]
    print(
        f"Split {split_kind} | val_frac={val_frac} val_offset={args.val_offset} | "
        f"train={tr_idx.shape[0]} val={va_idx.shape[0]} | "
        f"train [{_ns_to_iso(int(t_tr.min()))} → {_ns_to_iso(int(t_tr.max()))}] | "
        f"val [{_ns_to_iso(int(t_va.min()))} → {_ns_to_iso(int(t_va.max()))}]"
    )
    for h in horizon_keys:
        y_tr_h = labels_for_indices(bundle, tr_idx, h)
        bal = class_balance(y_tr_h)
        print(
            f"  train class bal {h}m: down={bal['down']:.2f} flat={bal['flat']:.2f} "
            f"up={bal['up']:.2f} (n={bal['n']})"
        )

    norm_stats = fit_norm_from_bundle(bundle, tr_idx)
    apply_norm_to_bundle(bundle, norm_stats)
    meta["norm_stats"] = norm_stats
    meta["norm"] = "train_only_per_pair"
    meta["val_fraction"] = val_frac
    meta["val_offset"] = args.val_offset
    meta["split"] = split_kind

    p_va = pair_ids_for_indices(bundle, va_idx)
    val_pair_counts = {p: int(np.sum(p_va == p)) for p in pairs}
    print(f"Val samples per pair: {val_pair_counts}")

    loader_kw = dict(
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collate_mh,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
    )
    if args.num_workers > 0:
        # keep workers alive between epochs so per-pair matrices aren't re-forked each epoch
        loader_kw["persistent_workers"] = True
    train_loader = DataLoader(LazyMultiHorizonDataset(bundle, tr_idx, horizon_keys), **loader_kw)
    val_loader = DataLoader(LazyMultiHorizonDataset(bundle, va_idx, horizon_keys), **loader_kw)

    model = SharedEncoderMultiHead(
        input_size=FEATURE_DIM,
        hidden_size=HIDDEN_SIZE,
        horizons_minutes=horizons,
        directional_head=DIRECTIONAL_HEAD,
        quantile_head=QUANTILE_HEAD,
        quantile_levels=QUANTILE_LEVELS,
        dropout=DROPOUT,
    ).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    print(
        f"Directional head: {'ON' if DIRECTIONAL_HEAD else 'off'} "
        f"(aux up/down loss weight={DIR_LOSS_WEIGHT})"
    )
    print(
        f"Quantile head: {'ON' if QUANTILE_HEAD else 'off'} "
        f"(levels={QUANTILE_LEVELS} loss weight={QUANTILE_LOSS_WEIGHT})"
    )

    print(
        f"3-class weighting: mode={CLS_WEIGHT_MODE} clip={CLS_WEIGHT_CLIP} "
        f"label_smoothing={CLS_LABEL_SMOOTHING} (directional head unaffected)"
    )
    crits = {}
    dir_crits = {}
    for h in horizon_keys:
        y_tr_h = labels_for_indices(bundle, tr_idx, h)
        counts = np.bincount(y_tr_h, minlength=3).astype(np.float64)
        counts = np.maximum(counts, 1.0)
        # 3-class weights: gentler than raw inverse-frequency so the flat mass does
        # not over-inflate down/up weights and collapse the argmax. Clamp so no
        # single class dominates the CE.
        if CLS_WEIGHT_MODE == "inv_freq":
            w = counts.sum() / (3.0 * counts)
        else:  # sqrt_inv_freq (default)
            w = 1.0 / np.sqrt(counts)
        w = w / w.mean()
        if CLS_WEIGHT_CLIP and CLS_WEIGHT_CLIP > 1.0:
            w = np.clip(w, 1.0 / CLS_WEIGHT_CLIP, CLS_WEIGHT_CLIP)
            w = w / w.mean()
        crits[h] = nn.CrossEntropyLoss(
            weight=torch.tensor(w, dtype=torch.float32, device=device),
            label_smoothing=CLS_LABEL_SMOOTHING,
        )
        print(f"  class weights {h}m: down={w[0]:.2f} flat={w[1]:.2f} up={w[2]:.2f}")
        # Directional-head class balance (down vs up only)
        n_down, n_up = float(counts[0]), float(counts[2])
        dw = np.array([(n_down + n_up) / (2 * n_down), (n_down + n_up) / (2 * n_up)])
        dw = dw / dw.mean()
        dir_crits[h] = nn.CrossEntropyLoss(
            weight=torch.tensor(dw, dtype=torch.float32, device=device)
        )

    best_score = -1.0
    best_early_score = -1.0
    bad_epochs = 0
    history = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        tr_loss, tr_n = 0.0, 0
        tr_acc_sum = {h: 0.0 for h in horizon_keys}

        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = {k: v.to(device) for k, v in yb.items()}
            opt.zero_grad()
            logits, dir_logits, quant = model.forward_all(xb)
            loss = multi_loss(logits, yb, crits, horizon_keys)
            if dir_logits is not None:
                dloss = directional_loss(dir_logits, yb, dir_crits, horizon_keys)
                if dloss is not None:
                    loss = loss + DIR_LOSS_WEIGHT * dloss
            if quant is not None:
                loss = loss + QUANTILE_LOSS_WEIGHT * quantile_loss(
                    quant, yb, horizon_keys, QUANTILE_LEVELS
                )
            loss.backward()
            opt.step()
            bs = xb.size(0)
            tr_loss += loss.item() * bs
            accs = multi_acc(logits, yb, horizon_keys)
            for h in horizon_keys:
                tr_acc_sum[h] += accs[h] * bs
            tr_n += bs

        tr_loss /= max(tr_n, 1)
        tr_acc = {h: tr_acc_sum[h] / max(tr_n, 1) for h in horizon_keys}

        model.eval()
        va_loss, va_n = 0.0, 0
        va_acc_sum = {h: 0.0 for h in horizon_keys}
        # Collect primary logits during val pass (avoid second full epoch)
        plogits_chunks, py_chunks = [], []
        pdir_chunks = []
        pquant_chunks, pret_chunks = [], []  # primary-horizon quantiles + realized ret
        with torch.no_grad():
            for xb, yb in val_loader:
                xb = xb.to(device)
                yb = {k: v.to(device) for k, v in yb.items()}
                logits, dir_logits, quant = model.forward_all(xb)
                loss = multi_loss(logits, yb, crits, horizon_keys)
                bs = xb.size(0)
                va_loss += loss.item() * bs
                accs = multi_acc(logits, yb, horizon_keys)
                for h in horizon_keys:
                    va_acc_sum[h] += accs[h] * bs
                va_n += bs
                plogits_chunks.append(logits[primary_key].cpu())
                py_chunks.append(yb[primary_key].cpu())
                if dir_logits is not None:
                    pdir_chunks.append(dir_logits[primary_key].cpu())
                if quant is not None:
                    pquant_chunks.append(quant[primary_key].cpu())
                    pret_chunks.append(yb[f"ret_{primary_key}"].cpu())

        va_loss /= max(va_n, 1)
        va_acc = {h: va_acc_sum[h] / max(va_n, 1) for h in horizon_keys}

        # Quantile calibration on the primary horizon: what fraction of realized
        # returns fall within the predicted [p_low, p_high] band. Well-calibrated
        # p10/p90 → coverage ≈ 0.80. Diagnostic only; does not drive selection.
        q_cov = None
        if pquant_chunks:
            q_all = torch.cat(pquant_chunks, dim=0)  # [N, n_q]
            r_all = torch.cat(pret_chunks, dim=0)  # [N]
            lo, hi = q_all[:, 0], q_all[:, -1]
            q_cov = float(((r_all >= lo) & (r_all <= hi)).float().mean().item())

        if plogits_chunks:
            py = torch.cat(py_chunks, dim=0)
            if pdir_chunks:
                # Score on the clean directional-head signal when available.
                score_logits = dir_logits_to_three_class(torch.cat(pdir_chunks, dim=0))
            else:
                score_logits = torch.cat(plogits_chunks, dim=0)
            score, gate_m = checkpoint_score(score_logits, py, args.ckpt_gate, MIN_GATED_FOR_CKPT)
        else:
            score, gate_m = -1.0, {}

        # Calibration-aware selection: when the quantile head is on, penalize the
        # selection score as the primary-horizon band coverage drifts from target,
        # so the saved/early-stop epoch is directionally good AND calibrated. When
        # the head is off (q_cov is None) sel_score == score (no behavior change).
        cal_pen = 1.0
        if q_cov is not None:
            target = CAL_TARGET if CAL_TARGET > 0 else float(
                QUANTILE_LEVELS[-1] - QUANTILE_LEVELS[0]
            )
            tol = CAL_TOL if CAL_TOL > 0 else 1.0
            cal_pen = 1.0 - CAL_PENALTY_WEIGHT * min(1.0, abs(q_cov - target) / tol)
            cal_pen = max(0.0, cal_pen)
        sel_score = score * cal_pen

        history.append(
            {
                "epoch": epoch,
                "train_loss": tr_loss,
                "val_loss": va_loss,
                "train_acc": tr_acc,
                "val_acc": va_acc,
                "ckpt_score": score,
                "sel_score": sel_score,
                "cal_pen": cal_pen,
                "quantile_cov": q_cov,
                "gate": gate_m,
            }
        )

        acc_str = " ".join(f"{h}m={va_acc[h]:.3f}" for h in horizon_keys)
        fc = gate_m.get("fixed_coverage") or {}
        fc_dir = float(fc.get("dir_acc") or 0.0)
        fc_lb = float(fc.get("dir_acc_wilson_lb") or 0.0)
        fc_n = int(fc.get("n_true_directional_gated") or 0)
        if q_cov is not None:
            q_str = (
                f" q[p{int(QUANTILE_LEVELS[0]*100)}-p{int(QUANTILE_LEVELS[-1]*100)}]"
                f"cov={q_cov:.3f} cal_pen={cal_pen:.3f} sel={sel_score:.4f}"
            )
        else:
            q_str = ""
        print(
            f"epoch {epoch:02d}  loss_tr={tr_loss:.4f} loss_va={va_loss:.4f}  "
            f"val_acc [{acc_str}]  "
            f"sel@cov{SEL_COVERAGE:.2f} dir_acc={fc_dir:.3f} lb={fc_lb:.3f} "
            f"n_dir={fc_n} score={score:.4f}{q_str}"
        )

        if sel_score > best_score + 1e-6:
            best_score = sel_score
            Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)
            Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
            ckpt = {
                "model_state": model.state_dict(),
                "meta": {
                    **meta,
                    "horizons_minutes": horizons,
                    "horizon_keys": horizon_keys,
                    "primary_horizon": int(primary_key),
                    "seq_len": args.seq_len,
                    "feature_dim": FEATURE_DIM,
                    "hidden_size": HIDDEN_SIZE,
                    "dropout": DROPOUT,
                    "directional_head": DIRECTIONAL_HEAD,
                    "cls_weight_mode": CLS_WEIGHT_MODE,
                    "cls_weight_clip": CLS_WEIGHT_CLIP,
                    "cls_label_smoothing": CLS_LABEL_SMOOTHING,
                    "quantile_head": QUANTILE_HEAD,
                    "quantile_levels": QUANTILE_LEVELS,
                    "quantile_loss_weight": QUANTILE_LOSS_WEIGHT,
                    "quantile_cov_primary": q_cov,
                    "cal_penalty_weight": CAL_PENALTY_WEIGHT,
                    "cal_target": (CAL_TARGET if CAL_TARGET > 0 else float(QUANTILE_LEVELS[-1] - QUANTILE_LEVELS[0])),
                    "cal_tol": CAL_TOL,
                    "sel_score": best_score,
                    "sel_coverage": SEL_COVERAGE,
                    "git_sha": os.environ.get("FLUX_GIT_SHA", ""),
                    "best_ckpt_score": best_score,
                    "best_gate_metrics": gate_m,
                    "ckpt_gate_threshold": args.ckpt_gate,
                    "val_acc": va_acc,
                    "val_loss": va_loss,
                    "lr": args.lr,
                    "weight_decay": args.weight_decay,
                    "version": "m2",
                    "norm_stats": norm_stats,
                },
            }
            path = os.path.join(MODEL_DIR, "m2_multi.pt")
            torch.save(ckpt, path)
            torch.save(ckpt, os.path.join(OUTPUT_DIR, "m2_multi.pt"))
            print(
                f"  saved → {path} (primary {primary_key}m sel_score={best_score:.4f} "
                f"dir_acc={fc_dir:.3f} lb={fc_lb:.3f} n_dir={fc_n})"
            )

        # Early stop on the SELECTION score (edge), not val_loss. Val loss barely
        # moves on this near-random task, so it stopped runs before the model
        # developed confident directional mass. We give up only when the edge has
        # not improved for `patience` epochs.
        if sel_score > best_early_score + 1e-5:
            best_early_score = sel_score
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= args.patience:
                print(
                    f"Early stop at epoch {epoch} "
                    f"(no sel-score improve for {args.patience} epochs)"
                )
                break

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "history_m2.json"), "w") as f:
        json.dump(history, f, indent=2)

    print(f"\nDone. Best primary ({primary_key}m) gate score={best_score:.4f}")
    print(f"Checkpoint: {MODEL_DIR}/m2_multi.pt")
    print("Next: python eval_m2.py --checkpoint /models/m2_multi.pt")


if __name__ == "__main__":
    main()
