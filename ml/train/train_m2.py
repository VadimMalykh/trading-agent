#!/usr/bin/env python3
"""M2 training: shared encoder + multi-horizon heads + checkpoint for gating eval."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    BATCH_SIZE,
    EPOCHS,
    FEATURE_DIM,
    HIDDEN_SIZE,
    HORIZONS_MINUTES,
    LR,
    MODEL_DIR,
    OUTPUT_DIR,
    PAIRS,
    PRIMARY_HORIZON,
    SEQ_LEN,
    VAL_FRACTION,
)
from data.dataset import MultiHorizonDataset, build_multi_horizon_arrays, time_split
from data.db import load_whitelist_pairs, table_counts
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
        help="Comma-separated pairs. Default: UI whitelist from DB (app_settings), else candles symbols.",
    )
    p.add_argument(
        "--horizons",
        type=str,
        default=",".join(str(h) for h in HORIZONS_MINUTES),
        help="Comma-separated horizon minutes, e.g. 1,15,60",
    )
    p.add_argument("--primary", type=int, default=PRIMARY_HORIZON, help="Horizon used for best-ckpt selection")
    return p.parse_args()


def multi_loss(logits_dict, y_dict, crits, horizon_keys):
    loss = 0.0
    for h in horizon_keys:
        loss = loss + crits[h](logits_dict[h], y_dict[h])
    return loss / len(horizon_keys)


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


def main():
    args = parse_args()
    device = torch.device(
        args.device if args.device != "cuda" or torch.cuda.is_available() else "cpu"
    )
    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    horizon_keys = [str(h) for h in horizons]
    primary_key = str(args.primary)
    if primary_key not in horizon_keys:
        primary_key = horizon_keys[min(1, len(horizon_keys) - 1)]

    print("FluxTrader M2 Training (shared encoder + multi-head)")
    print("=" * 50)
    print(f"PyTorch {torch.__version__} | device={device}")
    print(f"Horizons (min): {horizons} | primary={primary_key}m | seq_len={args.seq_len}")
    print(f"Pairs: {args.pairs}")

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
        pairs = load_whitelist_pairs()
    print(f"Training pairs: {pairs}")

    X, y_dict, meta = build_multi_horizon_arrays(
        pairs=pairs,
        seq_len=args.seq_len,
        horizons_minutes=horizons,
    )
    print(f"\nSamples: {meta.get('n_samples', 0)} | per pair: {meta.get('n_per_pair')}")

    n = X.shape[0]
    if n < 50:
        print("Not enough samples (need ~50+). Collect more data, then re-run.")
        if n < 10:
            sys.exit(2)

    X_tr, y_tr, X_va, y_va = time_split(X, y_dict, VAL_FRACTION)
    train_loader = DataLoader(
        MultiHorizonDataset(X_tr, y_tr, horizon_keys),
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collate_mh,
    )
    val_loader = DataLoader(
        MultiHorizonDataset(X_va, y_va, horizon_keys),
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collate_mh,
    )

    model = SharedEncoderMultiHead(
        input_size=FEATURE_DIM,
        hidden_size=HIDDEN_SIZE,
        horizons_minutes=horizons,
    ).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=LR)

    # Inverse-frequency class weights (reduce collapse to "flat")
    crits = {}
    for h in horizon_keys:
        counts = np.bincount(y_tr[h], minlength=3).astype(np.float64)
        counts = np.maximum(counts, 1.0)
        w = counts.sum() / (3.0 * counts)
        w = w / w.mean()
        crits[h] = nn.CrossEntropyLoss(weight=torch.tensor(w, dtype=torch.float32, device=device))
        print(f"  class weights {h}m: down={w[0]:.2f} flat={w[1]:.2f} up={w[2]:.2f}")

    best_primary = -1.0
    history = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        tr_loss, tr_n = 0.0, 0
        tr_acc_sum = {h: 0.0 for h in horizon_keys}

        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = {k: v.to(device) for k, v in yb.items()}
            opt.zero_grad()
            logits = model(xb)
            loss = multi_loss(logits, yb, crits, horizon_keys)
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
        with torch.no_grad():
            for xb, yb in val_loader:
                xb = xb.to(device)
                yb = {k: v.to(device) for k, v in yb.items()}
                logits = model(xb)
                loss = multi_loss(logits, yb, crits, horizon_keys)
                bs = xb.size(0)
                va_loss += loss.item() * bs
                accs = multi_acc(logits, yb, horizon_keys)
                for h in horizon_keys:
                    va_acc_sum[h] += accs[h] * bs
                va_n += bs

        va_loss /= max(va_n, 1)
        va_acc = {h: va_acc_sum[h] / max(va_n, 1) for h in horizon_keys}

        history.append(
            {
                "epoch": epoch,
                "train_loss": tr_loss,
                "val_loss": va_loss,
                "train_acc": tr_acc,
                "val_acc": va_acc,
            }
        )

        acc_str = " ".join(f"{h}m={va_acc[h]:.3f}" for h in horizon_keys)
        print(f"epoch {epoch:02d}  loss_tr={tr_loss:.4f} loss_va={va_loss:.4f}  val_acc [{acc_str}]")

        primary_acc = va_acc.get(primary_key, 0.0)
        if primary_acc >= best_primary:
            best_primary = primary_acc
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
                    "best_val_acc_primary": best_primary,
                    "val_acc": va_acc,
                    "version": "m2",
                },
            }
            path = os.path.join(MODEL_DIR, "m2_multi.pt")
            torch.save(ckpt, path)
            torch.save(ckpt, os.path.join(OUTPUT_DIR, "m2_multi.pt"))
            print(f"  saved → {path} (primary {primary_key}m acc={best_primary:.3f})")

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "history_m2.json"), "w") as f:
        json.dump(history, f, indent=2)

    print(f"\nDone. Best primary ({primary_key}m) val acc={best_primary:.3f}")
    print(f"Checkpoint: {MODEL_DIR}/m2_multi.pt")
    print("Next: python eval_m2.py --checkpoint /models/m2_multi.pt --gate 0.5,0.6,0.7")


if __name__ == "__main__":
    main()
