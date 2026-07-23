#!/usr/bin/env python3
"""M2 eval: per-horizon accuracy + confidence gate sweep (+ per-pair)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    FEATURE_DIM,
    GATE_THRESHOLD,
    HIDDEN_SIZE,
    HORIZONS_MINUTES,
    MODEL_DIR,
    OUTPUT_DIR,
    PAIRS,
    SEQ_LEN,
    VAL_FRACTION,
)
from data.dataset import (
    LazyMultiHorizonDataset,
    apply_norm_to_bundle,
    build_m2_index_bundle,
    fit_norm_from_bundle,
    pair_ids_for_indices,
    time_split_indices,
)
from data.db import load_whitelist_pairs
from gate import dir_logits_to_three_class, fixed_coverage_metrics, gate_sweep
from models.multi_horizon import SharedEncoderMultiHead

# Coverages at which to report a stable, cross-model-comparable directional edge.
FIXED_COVERAGES = [0.01, 0.02, 0.05, 0.10, 0.20]


def collate_mh(batch):
    xs = torch.stack([b[0] for b in batch], dim=0)
    keys = batch[0][1].keys()
    ys = {k: torch.stack([b[1][k] for b in batch], dim=0) for k in keys}
    return xs, ys


def _ns_to_iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def run_horizon_report(logits, y_true, thresholds, pair_ids=None, dir_logits=None):
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
    fixed_cov = [fixed_coverage_metrics(gate_logits, y_true, c) for c in FIXED_COVERAGES]

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
            per_pair[str(pair)] = {
                "n": int(mask.sum()),
                "ungated_acc": sub_ungated,
                "gate_sweep": sub_sweep,
            }

    return {
        "ungated_acc": ungated,
        "confusion": conf_matrix.tolist(),
        "gate_sweep": sweep,
        "fixed_coverage": fixed_cov,
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
    norm_stats = meta.get("norm_stats") or {}
    primary = str(meta.get("primary_horizon", horizons[min(1, len(horizons) - 1)]))
    has_dir_head = bool(meta.get("directional_head", False))

    model = SharedEncoderMultiHead(
        input_size=feature_dim,
        hidden_size=hidden,
        horizons_minutes=horizons,
        directional_head=has_dir_head,
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

    with torch.no_grad():
        for xb, yb in loader:
            xb = xb.to(device)
            out, dir_out = model.forward_both(xb)
            for h in horizon_keys:
                all_logits[h].append(out[h].cpu())
                all_y[h].append(yb[h].cpu())
                if dir_out is not None:
                    all_dir[h].append(dir_out[h].cpu())

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
        result = run_horizon_report(
            logits, y_true, thresholds, pair_ids=p_va, dir_logits=dir_logits
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
            f"{'gate':>6}  {'coverage':>8}  {'n_gated':>8}  {'gated_acc':>10}  "
            f"{'dir_acc':>8}  {'edge':>6}  {'mean_conf':>9}"
        )
        for row in result["sweep_rows"]:
            edge = (row.get("gated_dir_acc") or 0.0) - 0.5 if row.get("n_gated", 0) else 0.0
            marker = " *" if abs(row["threshold"] - GATE_THRESHOLD) < 1e-9 else ""
            print(
                f"{row['threshold']:6.2f}  {row['coverage']:8.3f}  {row['n_gated']:8d}  "
                f"{row['gated_acc']:10.3f}  {row.get('gated_dir_acc', 0):8.3f}  "
                f"{edge:6.3f}  {row.get('mean_conf_gated', 0):9.3f}{marker}"
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

        if result["per_pair"]:
            print("Per-pair @ serve gate:")
            for pair, pr in result["per_pair"].items():
                row = next(
                    (r for r in pr["gate_sweep"] if abs(r["threshold"] - GATE_THRESHOLD) < 1e-9),
                    None,
                )
                if row:
                    print(
                        f"  {pair}: n={pr['n']} ungated={pr['ungated_acc']:.3f} "
                        f"cov={row['coverage']:.3f} dir_acc={row.get('gated_dir_acc', 0):.3f}"
                    )

        report["horizons"][h] = {
            "ungated_acc": result["ungated_acc"],
            "confusion": result["confusion"],
            "gate_sweep": result["gate_sweep"],
            "fixed_coverage": result["fixed_coverage"],
            "serve_gate_dir_edge_vs_half": result["serve_gate_dir_edge_vs_half"],
            "per_pair": {
                k: {
                    "n": v["n"],
                    "ungated_acc": v["ungated_acc"],
                    "gate_sweep": v["gate_sweep"],
                }
                for k, v in result["per_pair"].items()
            },
        }

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


if __name__ == "__main__":
    main()
