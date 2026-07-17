#!/usr/bin/env python3
"""Evaluate M1 checkpoint on time-ordered holdout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import FEATURE_DIM, HORIZON_MINUTES, MODEL_DIR, PAIRS, SEQ_LEN, VAL_FRACTION
from data.dataset import SequenceDataset, build_arrays, time_split
from models.lstm import PriceDirectionLSTM


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", default=f"{MODEL_DIR}/m1_15m.pt")
    p.add_argument("--device", default="cpu")
    p.add_argument("--horizon", type=int, default=HORIZON_MINUTES)
    args = p.parse_args()

    device = torch.device(args.device)
    ckpt_path = Path(args.checkpoint)
    if not ckpt_path.exists():
        print(f"Checkpoint not found: {ckpt_path}")
        sys.exit(1)

    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    model = PriceDirectionLSTM(input_size=FEATURE_DIM).to(device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    X, y, meta = build_arrays(pairs=PAIRS, seq_len=SEQ_LEN, horizon_minutes=args.horizon)
    _, _, X_val, y_val = time_split(X, y, VAL_FRACTION)
    if len(y_val) == 0:
        print("No validation samples")
        sys.exit(2)

    loader = DataLoader(SequenceDataset(X_val, y_val), batch_size=64, shuffle=False)
    correct = 0
    total = 0
    conf_matrix = torch.zeros(3, 3, dtype=torch.long)

    with torch.no_grad():
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)
            pred = model(xb).argmax(dim=1)
            correct += (pred == yb).sum().item()
            total += yb.size(0)
            for t, p_ in zip(yb.view(-1), pred.view(-1)):
                conf_matrix[t.long(), p_.long()] += 1

    acc = correct / max(total, 1)
    print(f"Val samples: {total}")
    print(f"Accuracy: {acc:.4f}")
    print("Confusion (rows=true down/flat/up, cols=pred):")
    print(conf_matrix.numpy())
    print(f"Meta: {ckpt.get('meta')}")


if __name__ == "__main__":
    main()
