#!/usr/bin/env python3
"""M1 supervised training — 15m direction baseline (CPU-friendly)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

# Ensure /workspace/train is on path when run as python train.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    BATCH_SIZE,
    EPOCHS,
    FEATURE_DIM,
    HIDDEN_SIZE,
    HORIZON_MINUTES,
    LR,
    MODEL_DIR,
    OUTPUT_DIR,
    PAIRS,
    SEQ_LEN,
    VAL_FRACTION,
)
from data.dataset import SequenceDataset, build_arrays, time_split
from data.db import table_counts
from models.lstm import PriceDirectionLSTM


def parse_args():
    p = argparse.ArgumentParser(description="FluxTrader M1 train")
    p.add_argument("--horizon", type=int, default=HORIZON_MINUTES)
    p.add_argument("--epochs", type=int, default=EPOCHS)
    p.add_argument("--device", type=str, default="cpu")
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    p.add_argument("--seq-len", type=int, default=SEQ_LEN)
    p.add_argument("--pairs", type=str, default=",".join(PAIRS))
    return p.parse_args()


def accuracy(logits, y):
    pred = logits.argmax(dim=1)
    return (pred == y).float().mean().item()


def main():
    args = parse_args()
    device = torch.device(args.device if args.device != "cuda" or torch.cuda.is_available() else "cpu")

    print("FluxTrader M1 Training")
    print("=" * 40)
    print(f"PyTorch {torch.__version__} | device={device}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    print(f"Horizon: {args.horizon}m | seq_len={args.seq_len} | epochs={args.epochs}")
    print(f"Pairs: {args.pairs}")

    print("\nDB table counts:")
    try:
        counts = table_counts()
        for k, v in counts.items():
            print(f"  {k}: {v}")
    except Exception as e:
        print(f"  DB error: {e}")
        print("  Ensure postgres is up and app has collected data.")
        sys.exit(1)

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    X, y, meta = build_arrays(
        pairs=pairs,
        seq_len=args.seq_len,
        horizon_minutes=args.horizon,
    )
    print(f"\nSamples: {meta.get('n_samples', 0)} | per pair: {meta.get('n_per_pair')}")

    if len(y) < 50:
        print(
            "\nNot enough labeled samples yet (need ~50+).\n"
            "Leave `docker compose up` running to collect candles/book/trades,\n"
            "then re-run train. Fetching extra history via REST is also possible later."
        )
        # Still create a tiny random run so pipeline is verified if user forces
        if len(y) < 10:
            print("Aborting: fewer than 10 samples.")
            sys.exit(2)

    X_train, y_train, X_val, y_val = time_split(X, y, VAL_FRACTION)
    train_loader = DataLoader(
        SequenceDataset(X_train, y_train),
        batch_size=args.batch_size,
        shuffle=False,
    )
    val_loader = DataLoader(
        SequenceDataset(X_val, y_val),
        batch_size=args.batch_size,
        shuffle=False,
    )

    model = PriceDirectionLSTM(input_size=FEATURE_DIM, hidden_size=HIDDEN_SIZE).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    crit = nn.CrossEntropyLoss()

    best_val = 0.0
    history = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss, train_acc, n = 0.0, 0.0, 0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            logits = model(xb)
            loss = crit(logits, yb)
            loss.backward()
            opt.step()
            bs = yb.size(0)
            train_loss += loss.item() * bs
            train_acc += accuracy(logits, yb) * bs
            n += bs
        train_loss /= max(n, 1)
        train_acc /= max(n, 1)

        model.eval()
        val_loss, val_acc, vn = 0.0, 0.0, 0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                logits = model(xb)
                loss = crit(logits, yb)
                bs = yb.size(0)
                val_loss += loss.item() * bs
                val_acc += accuracy(logits, yb) * bs
                vn += bs
        val_loss /= max(vn, 1)
        val_acc /= max(vn, 1)

        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "train_acc": train_acc,
                "val_loss": val_loss,
                "val_acc": val_acc,
            }
        )
        print(
            f"epoch {epoch:02d}  train_loss={train_loss:.4f} acc={train_acc:.3f}  "
            f"val_loss={val_loss:.4f} acc={val_acc:.3f}"
        )

        if val_acc >= best_val:
            best_val = val_acc
            Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)
            Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
            ckpt = {
                "model_state": model.state_dict(),
                "meta": {
                    **meta,
                    "horizon_minutes": args.horizon,
                    "seq_len": args.seq_len,
                    "feature_dim": FEATURE_DIM,
                    "best_val_acc": best_val,
                },
            }
            path = os.path.join(MODEL_DIR, "m1_15m.pt")
            torch.save(ckpt, path)
            torch.save(ckpt, os.path.join(OUTPUT_DIR, "m1_15m.pt"))
            print(f"  saved checkpoint → {path}")

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "history.json"), "w") as f:
        json.dump(history, f, indent=2)

    print(f"\nDone. Best val acc={best_val:.3f}")
    print(f"Checkpoint: {MODEL_DIR}/m1_15m.pt")


if __name__ == "__main__":
    main()
