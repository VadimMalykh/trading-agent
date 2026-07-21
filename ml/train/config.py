import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fluxtrader:secret@postgres:5432/fluxtrader",
)

# M1 single-horizon default
HORIZON_MINUTES = int(os.environ.get("HORIZON_MINUTES", "15"))

# M2 multi-horizon (minutes), flagship remains 15m
HORIZONS_MINUTES = [
    int(x) for x in os.environ.get("HORIZONS_MINUTES", "1,15,60").split(",") if x.strip()
]
PRIMARY_HORIZON = int(os.environ.get("PRIMARY_HORIZON", "15"))

SEQ_LEN = int(os.environ.get("SEQ_LEN", "32"))
FLAT_THRESHOLD = float(os.environ.get("FLAT_THRESHOLD", "0.001"))  # 0.1%
# Slightly wider flat band for longer horizons (optional scale in dataset)
FLAT_THRESHOLD_PER_HORIZON = {
    1: float(os.environ.get("FLAT_TH_1M", "0.0005")),
    15: float(os.environ.get("FLAT_TH_15M", "0.001")),
    60: float(os.environ.get("FLAT_TH_1H", "0.002")),
}

PAIRS = [p.strip() for p in os.environ.get("WHITELIST_PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if p.strip()]
CANDLE_INTERVAL = os.environ.get("CANDLE_INTERVAL", "1m")

MODEL_DIR = os.environ.get("MODEL_DIR", "/models")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/workspace/train/output")

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "32"))
EPOCHS = int(os.environ.get("EPOCHS", "10"))
LR = float(os.environ.get("LR", "1e-3"))
HIDDEN_SIZE = int(os.environ.get("HIDDEN_SIZE", "64"))
VAL_FRACTION = float(os.environ.get("VAL_FRACTION", "0.2"))

# Confidence gate default (product: few high-confidence trades)
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.65"))

# Feature vector size per timestep (must match features.py)
FEATURE_DIM = 16

# Class names for logging
CLASS_NAMES = ["down", "flat", "up"]
