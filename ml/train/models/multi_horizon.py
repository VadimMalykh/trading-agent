"""M2: shared encoder + multi-horizon direction heads."""

from __future__ import annotations

from typing import Dict, List

import torch
import torch.nn as nn
import torch.nn.functional as F


class SharedEncoderMultiHead(nn.Module):
    """
    Shared LSTM encoder; one classification head per horizon (minutes).
    Forward returns dict[str, logits] keyed by horizon name e.g. "15".
    """

    def __init__(
        self,
        input_size: int = 16,
        hidden_size: int = 64,
        num_classes: int = 3,
        horizons_minutes: List[int] | None = None,
    ):
        super().__init__()
        horizons_minutes = horizons_minutes or [1, 15, 60]
        self.horizons = [str(h) for h in horizons_minutes]
        self.num_classes = num_classes

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

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, T, F] -> [B, H]
        _, (hidden, _) = self.encoder(x)
        return hidden[-1]

    def forward(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        state = self.encode(x)
        return {h: self.heads[h](state) for h in self.horizons}

    def predict_proba(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        logits = self.forward(x)
        return {h: F.softmax(logit, dim=-1) for h, logit in logits.items()}
