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
        input_size: int = 19,
        hidden_size: int = 64,
        num_classes: int = 3,
        horizons_minutes: List[int] | None = None,
        directional_head: bool = True,
        quantile_head: bool = False,
        quantile_levels: List[float] | None = None,
        dropout: float = 0.2,
        num_layers: int = 2,
        n_pairs: int = 0,
        pair_embed_dim: int = 0,
    ):
        super().__init__()
        horizons_minutes = horizons_minutes or [1, 15, 60]
        self.horizons = [str(h) for h in horizons_minutes]
        self.num_classes = num_classes
        self.has_directional_head = directional_head
        self.has_quantile_head = quantile_head
        self.quantile_levels = list(quantile_levels or [0.1, 0.5, 0.9])
        # Regularization strength. Default 0.2 preserves the served candle model's
        # behavior; raise (via DROPOUT env) for the tiny dense-book walk-forward
        # regime where the model overfits within ~2-5 epochs. LSTM inter-layer
        # dropout only applies with num_layers > 1.
        self.dropout = float(dropout)
        self.num_layers = int(num_layers)

        # Optional per-pair identity embedding. dim 0 → OFF (pair-agnostic, old
        # behavior). n_pairs rows are the trained vocab; row index `n_pairs` is a
        # reserved OOV/unknown-pair bucket used at serve time for symbols not seen
        # in training. The embed vector is concatenated to the pooled encoder state,
        # so the LSTM input_size (and all old checkpoints) stay unchanged.
        self.n_pairs = int(n_pairs)
        self.pair_embed_dim = int(pair_embed_dim)
        self.has_pair_embed = self.pair_embed_dim > 0 and self.n_pairs > 0
        if self.has_pair_embed:
            self.pair_embed = nn.Embedding(self.n_pairs + 1, self.pair_embed_dim)
        head_in = hidden_size + (self.pair_embed_dim if self.has_pair_embed else 0)

        self.encoder = nn.LSTM(
            input_size,
            hidden_size,
            batch_first=True,
            num_layers=self.num_layers,
            # LSTM inter-layer dropout is a no-op (and warns) with a single layer.
            dropout=self.dropout if self.num_layers > 1 else 0.0,
        )
        self.heads = nn.ModuleDict(
            {
                h: nn.Sequential(
                    nn.Linear(head_in, 32),
                    nn.ReLU(),
                    nn.Dropout(self.dropout),
                    nn.Linear(32, num_classes),
                )
                for h in self.horizons
            }
        )
        if directional_head:
            self.dir_heads = nn.ModuleDict(
                {
                    h: nn.Sequential(
                        nn.Linear(head_in, 32),
                        nn.ReLU(),
                        nn.Dropout(self.dropout),
                        nn.Linear(32, 2),  # 0=down, 1=up
                    )
                    for h in self.horizons
                }
            )
        if quantile_head:
            # Per-horizon regression of forward-return quantiles (e.g. p10/p50/p90).
            # Gives the downstream RL policy risk/vol context to size + gate trades.
            n_q = len(self.quantile_levels)
            self.quantile_heads = nn.ModuleDict(
                {
                    h: nn.Sequential(
                        nn.Linear(head_in, 32),
                        nn.ReLU(),
                        nn.Dropout(self.dropout),
                        nn.Linear(32, n_q),
                    )
                    for h in self.horizons
                }
            )

    def encode(self, x: torch.Tensor, pair_idx: torch.Tensor | None = None) -> torch.Tensor:
        # x: [B, T, F] -> [B, H] (+ pair embed [B, E] when enabled)
        _, (hidden, _) = self.encoder(x)
        state = hidden[-1]
        if self.has_pair_embed:
            if pair_idx is None:
                # No id supplied (e.g. an old caller) → OOV bucket for every row.
                pair_idx = torch.full(
                    (state.shape[0],), self.n_pairs, dtype=torch.long, device=state.device
                )
            emb = self.pair_embed(pair_idx.to(state.device))
            state = torch.cat([state, emb], dim=-1)
        return state

    def forward(self, x: torch.Tensor, pair_idx: torch.Tensor | None = None) -> Dict[str, torch.Tensor]:
        state = self.encode(x, pair_idx)
        return {h: self.heads[h](state) for h in self.horizons}

    def forward_both(self, x: torch.Tensor, pair_idx: torch.Tensor | None = None):
        """Return (three_class_logits, dir_logits_or_None) sharing one encode."""
        state = self.encode(x, pair_idx)
        three = {h: self.heads[h](state) for h in self.horizons}
        if self.has_directional_head:
            two = {h: self.dir_heads[h](state) for h in self.horizons}
        else:
            two = None
        return three, two

    def forward_dir(self, x: torch.Tensor, pair_idx: torch.Tensor | None = None) -> Dict[str, torch.Tensor]:
        state = self.encode(x, pair_idx)
        return {h: self.dir_heads[h](state) for h in self.horizons}

    def forward_quantiles(self, x: torch.Tensor, pair_idx: torch.Tensor | None = None) -> Dict[str, torch.Tensor]:
        """Per-horizon quantile predictions [B, n_quantiles] (monotone-sorted)."""
        state = self.encode(x, pair_idx)
        return {h: self._sorted_quantiles(self.quantile_heads[h](state)) for h in self.horizons}

    @staticmethod
    def _sorted_quantiles(q: torch.Tensor) -> torch.Tensor:
        """Enforce non-crossing quantiles (p10<=p50<=p90) by sorting along dim=-1.

        Pinball loss does not by itself guarantee ordering; sorting is a cheap,
        standard fix that keeps the outputs interpretable as a distribution.
        """
        return torch.sort(q, dim=-1).values

    def forward_all(self, x: torch.Tensor, pair_idx: torch.Tensor | None = None):
        """Return (three_class, dir_or_None, quantiles_or_None) sharing one encode."""
        state = self.encode(x, pair_idx)
        three = {h: self.heads[h](state) for h in self.horizons}
        two = (
            {h: self.dir_heads[h](state) for h in self.horizons}
            if self.has_directional_head
            else None
        )
        quant = (
            {h: self._sorted_quantiles(self.quantile_heads[h](state)) for h in self.horizons}
            if self.has_quantile_head
            else None
        )
        return three, two, quant

    def predict_proba(self, x: torch.Tensor, pair_idx: torch.Tensor | None = None) -> Dict[str, torch.Tensor]:
        logits = self.forward(x, pair_idx)
        return {h: F.softmax(logit, dim=-1) for h, logit in logits.items()}

    def predict_dir_proba(self, x: torch.Tensor, pair_idx: torch.Tensor | None = None) -> Dict[str, torch.Tensor]:
        """p(up) from the directional head, per horizon."""
        logits = self.forward_dir(x, pair_idx)
        return {h: F.softmax(logit, dim=-1)[:, 1] for h, logit in logits.items()}
