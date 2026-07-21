#!/usr/bin/env python3
"""M2 eval: per-horizon accuracy + confidence gate sweep."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    FEATURE_DIM,
    HIDDEN_SIZE,
    HORIZONS_MINUTES,
    MODEL_DIR,
    OUTPUT_DIR,
    PAIRS,
    SEQ_LEN,
    VAL_FRACTION,
)
from data.dataset import MultiHorizonDataset, build_multi_horizon_arrays, time_split
from data.db import load_whitelist_pairs
from gate import gate_sweep
from models.multi_horizon import SharedEncoderMultiHead


def collate_mh(batch):
    xs = torch.stack([b[0] for b in batch], dim=0)
    keys = batch[0][1].keys()
    ys = {k: torch.stack([b[1][k] for b in batch], dim=0) for k in keys}
    return xs, ys


def main():
    p = argparse.ArgumentParser(description="FluxTrader M2 eval + gate sweep")
    p.add_argument("--checkpoint", default=f"{MODEL_DIR}/m2_multi.pt")
    p.add_argument("--device", default="cpu")
    p.add_argument("--gate", default="0.5,0.6,0.65,0.7,0.75", help="Comma-separated confidence thresholds")
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

    model = SharedEncoderMultiHead(
        input_size=feature_dim,
        hidden_size=hidden,
        horizons_minutes=horizons,
    ).to(device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    if args.pairs.strip():
        pairs = [x.strip().upper() for x in args.pairs.split(",") if x.strip()]
    else:
        pairs = load_whitelist_pairs()
    print(f"Eval pairs: {pairs}")

    X, y_dict, build_meta = build_multi_horizon_arrays(
        pairs=pairs, seq_len=seq_len, horizons_minutes=horizons
    )
    _, _, X_val, y_val = time_split(X, y_dict, VAL_FRACTION)
    if X_val.shape[0] == 0:
        print("No validation samples")
        sys.exit(2)

    loader = DataLoader(
        MultiHorizonDataset(X_val, y_val, horizon_keys),
        batch_size=64,
        shuffle=False,
        collate_fn=collate_mh,
    )

    # Collect all logits
    all_logits = {h: [] for h in horizon_keys}
    all_y = {h: [] for h in horizon_keys}

    with torch.no_grad():
        for xb, yb in loader:
            xb = xb.to(device)
            out = model(xb)
            for h in horizon_keys:
                all_logits[h].append(out[h].cpu())
                all_y[h].append(yb[h].cpu())

    thresholds = [float(t) for t in args.gate.split(",") if t.strip()]
    report = {"n_val": int(X_val.shape[0]), "horizons": {}, "meta": meta}

    print(f"M2 Eval | val samples={X_val.shape[0]} | horizons={horizons}")
    print("=" * 60)

    for h in horizon_keys:
        logits = torch.cat(all_logits[h], dim=0)
        y_true = torch.cat(all_y[h], dim=0)
        pred = logits.argmax(dim=1)
        ungated = float((pred == y_true).float().mean().item())

        conf_matrix = torch.zeros(3, 3, dtype=torch.long)
        for t, p_ in zip(y_true.view(-1), pred.view(-1)):
            conf_matrix[t.long(), p_.long()] += 1

        sweep = gate_sweep(logits, y_true, thresholds, mode="directional")

        print(f"\n--- Horizon {h}m ---")
        print(f"Ungated accuracy (3-class argmax): {ungated:.4f}")
        print("Confusion (rows=true down/flat/up, cols=pred):")
        print(conf_matrix.numpy())
        print("Directional gate: conf=max(p_up,p_down); trade when conf>=threshold")
        print(
            f"{'gate':>6}  {'coverage':>8}  {'n_gated':>8}  {'gated_acc':>10}  "
            f"{'dir_acc':>8}  {'mean_conf':>9}"
        )
        for row in sweep:
            print(
                f"{row['threshold']:6.2f}  {row['coverage']:8.3f}  {row['n_gated']:8d}  "
                f"{row['gated_acc']:10.3f}  {row.get('gated_dir_acc', 0):8.3f}  "
                f"{row.get('mean_conf_gated', 0):9.3f}"
            )

        report["horizons"][h] = {
            "ungated_acc": ungated,
            "confusion": conf_matrix.tolist(),
            "gate_sweep": sweep,
        }

    out_path = Path(OUTPUT_DIR) / "eval_m2.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nWrote {out_path}")

    # Quick product note
    print("\nInterpretation tips:")
    print("  coverage ↓ as gate ↑  → fewer signals (desired for few high-confidence trades)")
    print("  gated_acc vs ungated  → quality when we do fire (hope gated_acc >= ungated)")
    print("  n_gated=0            → threshold too high for this val set")


if __name__ == "__main__":
    main()
