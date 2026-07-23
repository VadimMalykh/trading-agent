"""M2: shared encoder + multi-horizon direction heads."""

from __future__ import annotations

from typing import Dict, List

import torch
import torch.nn as nn
import torch.nn.functional as F


class SharedEncoderMultiHead(nn.Module):
    """
    Shared LSTM encoder with, per horizon:
      - a 3-class head (down/flat/up)  -> flat-vs-directional gating
      - an auxiliary 2-class directional head (down/up), trained ONLY on bars
        that actually moved (|fwd| > flat_threshold). This head is not diluted
        by the ~52% flat mass, so it produces a well-separated up-vs-down
        signal instead of a hedged, near-uniform softmax.

    forward() returns the 3-class logits dict (backward compatible).
    forward_dir() returns the 2-class directional logits dict.
    predict_dir_proba() returns p(up) from the directional head.
    """

    def __init__(
        self,
        input_size: int = 16,
        hidden_size: int = 64,
        num_classes: int = 3,
        horizons_minutes: List[int] | None = None,
        directional_head: bool = True,
    ):
        super().__init__()
        horizons_minutes = horizons_minutes or [1, 15, 60]
        self.horizons = [str(h) for h in horizons_minutes]
        self.num_classes = num_classes
        self.has_directional_head = directional_head

        self.encoder = nn.LSTM(
            input_size,
            hidden_size,
            batch_first=True,
            num_layers=2,
            dropout=0.2,
        )
        self.heads = nn.ModuleDict(
            {
                h: nn.Sequential(
                    nn.Linear(hidden_size, 32),
                    nn.ReLU(),
                    nn.Dropout(0.2),
                    nn.Linear(32, num_classes),
                )
                for h in self.horizons
            }
        )
        if directional_head:
            self.dir_heads = nn.ModuleDict(
                {
                    h: nn.Sequential(
                        nn.Linear(hidden_size, 32),
                        nn.ReLU(),
                        nn.Dropout(0.2),
                        nn.Linear(32, 2),  # 0=down, 1=up
                    )
                    for h in self.horizons
                }
            )

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, T, F] -> [B, H]
        _, (hidden, _) = self.encoder(x)
        return hidden[-1]

    def forward(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        state = self.encode(x)
        return {h: self.heads[h](state) for h in self.horizons}

    def forward_both(self, x: torch.Tensor):
        """Return (three_class_logits, dir_logits_or_None) sharing one encode."""
        state = self.encode(x)
        three = {h: self.heads[h](state) for h in self.horizons}
        if self.has_directional_head:
            two = {h: self.dir_heads[h](state) for h in self.horizons}
        else:
            two = None
        return three, two

    def forward_dir(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        state = self.encode(x)
        return {h: self.dir_heads[h](state) for h in self.horizons}

    def predict_proba(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        logits = self.forward(x)
        return {h: F.softmax(logit, dim=-1) for h, logit in logits.items()}

    def predict_dir_proba(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        """p(up) from the directional head, per horizon."""
        logits = self.forward_dir(x)
        return {h: F.softmax(logit, dim=-1)[:, 1] for h, logit in logits.items()}
