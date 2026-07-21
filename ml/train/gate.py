"""Confidence gating helpers (M2) — not RL; threshold on softmax max prob."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import torch
import torch.nn.functional as F


def softmax_confidence(logits: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
    """(pred_class, max_softmax) for 3-class head."""
    probs = F.softmax(logits, dim=-1)
    conf, pred = probs.max(dim=-1)
    return pred, conf


def directional_signal(logits: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
    """
    Trade-oriented signal: ignore flat mass for confidence.
    side: 0=down, 2=up (never 1)
    conf_dir: max(p_down, p_up)
    """
    probs = F.softmax(logits, dim=-1)
    p_down = probs[:, 0]
    p_up = probs[:, 2]
    conf_dir = torch.maximum(p_down, p_up)
    side = torch.where(p_up >= p_down, torch.full_like(p_up, 2, dtype=torch.long), torch.zeros_like(p_down, dtype=torch.long))
    return side, conf_dir


def apply_gate(
    pred: torch.Tensor,
    conf: torch.Tensor,
    threshold: float,
    skip_flat: bool = True,
) -> torch.Tensor:
    """mask True = take trade (pass gate)."""
    mask = conf >= threshold
    if skip_flat:
        mask = mask & (pred != 1)
    return mask


def gate_metrics(
    logits: torch.Tensor,
    y_true: torch.Tensor,
    threshold: float,
    mode: str = "directional",
) -> Dict[str, float]:
    """
    mode=directional (default): conf = max(p_up,p_down), pred = up/down only.
    mode=argmax: conf = max softmax, skip flat preds.
    gated_acc: among gated samples, does side match true label?
      (true flat counts as miss for directional trades — correct for "few trades")
    """
    if mode == "directional":
        pred, conf = directional_signal(logits)
        mask = conf >= threshold
    else:
        pred, conf = softmax_confidence(logits)
        mask = apply_gate(pred, conf, threshold, skip_flat=True)

    n = int(y_true.numel())
    n_gate = int(mask.sum().item())
    coverage = n_gate / max(n, 1)
    full_pred = logits.argmax(dim=1)
    ungated_acc = float((full_pred == y_true).float().mean().item())

    if n_gate == 0:
        return {
            "threshold": threshold,
            "mode": mode,
            "coverage": 0.0,
            "n_gated": 0,
            "n_total": n,
            "gated_acc": 0.0,
            "ungated_acc": ungated_acc,
            "mean_conf_gated": 0.0,
        }

    gated_acc = float((pred[mask] == y_true[mask]).float().mean().item())
    # Among gated, accuracy only where true label is directional
    true_dir = mask & (y_true != 1)
    n_true_dir = int(true_dir.sum().item())
    dir_hit = (
        float((pred[true_dir] == y_true[true_dir]).float().mean().item()) if n_true_dir else 0.0
    )

    return {
        "threshold": threshold,
        "mode": mode,
        "coverage": coverage,
        "n_gated": n_gate,
        "n_total": n,
        "gated_acc": gated_acc,
        "gated_dir_acc": dir_hit,
        "n_true_directional_gated": n_true_dir,
        "ungated_acc": ungated_acc,
        "mean_conf_gated": float(conf[mask].mean().item()),
    }


def gate_sweep(
    logits: torch.Tensor,
    y_true: torch.Tensor,
    thresholds: Optional[List[float]] = None,
    mode: str = "directional",
) -> List[Dict[str, float]]:
    thresholds = thresholds or [0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]
    return [gate_metrics(logits, y_true, t, mode=mode) for t in thresholds]
