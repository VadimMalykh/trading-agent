"""Confidence gating helpers (M2) — not RL; threshold on softmax max prob."""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import torch
import torch.nn.functional as F


def dir_logits_to_three_class(dir_logits: torch.Tensor) -> torch.Tensor:
    """
    Convert 2-class directional logits [down, up] into a 3-class-shaped tensor
    [down, flat, up] so the existing directional gate/metrics (which read cols
    0 and 2) operate on the clean up-vs-down probabilities from the aux head.

    The 'flat' column is set to -inf so it carries zero softmax mass; p_down and
    p_up then sum to 1 exactly and reflect the directional head's confidence.
    """
    n = dir_logits.shape[0]
    out = torch.empty((n, 3), dtype=dir_logits.dtype, device=dir_logits.device)
    out[:, 0] = dir_logits[:, 0]
    out[:, 1] = float("-inf")
    out[:, 2] = dir_logits[:, 1]
    return out


def wilson_lower_bound(hits: int, n: int, z: float = 1.96) -> float:
    """
    Lower bound of the Wilson score interval for a binomial proportion.

    Used so a high accuracy on a tiny gated sample (e.g. n=205) cannot beat a
    slightly-lower accuracy measured on a much larger, statistically solid
    sample. Returns 0.0 when n == 0.
    """
    if n <= 0:
        return 0.0
    phat = hits / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = phat + z2 / (2.0 * n)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * n)) / n)
    return max(0.0, (center - margin) / denom)


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
    if n_true_dir:
        dir_correct = (pred[true_dir] == y_true[true_dir])
        dir_hits = int(dir_correct.sum().item())
        dir_hit = dir_hits / n_true_dir
    else:
        dir_hits = 0
        dir_hit = 0.0

    return {
        "threshold": threshold,
        "mode": mode,
        "coverage": coverage,
        "n_gated": n_gate,
        "n_total": n,
        "gated_acc": gated_acc,
        "gated_dir_acc": dir_hit,
        "gated_dir_acc_wilson_lb": wilson_lower_bound(dir_hits, n_true_dir),
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


def fixed_coverage_metrics(
    logits: torch.Tensor,
    y_true: torch.Tensor,
    coverage: float,
) -> Dict[str, float]:
    """
    Directional edge at a FIXED coverage (take the top-`coverage` fraction of
    bars by directional confidence). Unlike a fixed threshold, this is directly
    comparable across epochs/models even as the softmax confidence scale drifts,
    so it is a stable selection & reporting metric.

    Returns dir_acc / edge / a Wilson lower bound over the gated bars whose TRUE
    label is directional (flat excluded, matching gated_dir_acc semantics).
    """
    n = int(y_true.numel())
    coverage = float(min(max(coverage, 0.0), 1.0))
    k = int(round(n * coverage))
    if n == 0 or k <= 0:
        return {
            "coverage": coverage,
            "n_gated": 0,
            "conf_threshold": 0.0,
            "dir_acc": 0.0,
            "edge": 0.0,
            "dir_acc_wilson_lb": 0.0,
            "n_true_directional_gated": 0,
        }

    side, conf = directional_signal(logits)
    # Top-k most confident bars
    topk = torch.topk(conf, k=min(k, n)).indices
    mask = torch.zeros(n, dtype=torch.bool)
    mask[topk] = True
    conf_threshold = float(conf[topk].min().item())

    true_dir = mask & (y_true != 1)
    n_true_dir = int(true_dir.sum().item())
    if n_true_dir == 0:
        dir_acc = 0.0
        hits = 0
    else:
        correct = (side[true_dir] == y_true[true_dir])
        hits = int(correct.sum().item())
        dir_acc = hits / n_true_dir

    return {
        "coverage": k / max(n, 1),
        "n_gated": int(mask.sum().item()),
        "conf_threshold": conf_threshold,
        "dir_acc": dir_acc,
        "edge": dir_acc - 0.5,
        "dir_acc_wilson_lb": wilson_lower_bound(hits, n_true_dir),
        "n_true_directional_gated": n_true_dir,
    }
