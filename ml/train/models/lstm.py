import torch.nn as nn

# Re-export multi-horizon as primary; keep M1 single-head for back-compat
from models.multi_horizon import SharedEncoderMultiHead  # noqa: F401


class PriceDirectionLSTM(nn.Module):
    """M1 supervised baseline: sequence → direction (down/flat/up)."""

    def __init__(self, input_size: int = 16, hidden_size: int = 64, num_classes: int = 3):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size,
            hidden_size,
            batch_first=True,
            num_layers=2,
            dropout=0.2,
        )
        self.head = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(32, num_classes),
        )

    def forward(self, x):
        _, (hidden, _) = self.lstm(x)
        return self.head(hidden[-1])
