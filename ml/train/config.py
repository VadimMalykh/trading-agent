import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fluxtrader:secret@postgres:5432/fluxtrader",
)

# M1 single-horizon default
HORIZON_MINUTES = int(os.environ.get("HORIZON_MINUTES", "30"))

# M2 multi-horizon (minutes); primary product horizon is 30m
HORIZONS_MINUTES = [
    int(x) for x in os.environ.get("HORIZONS_MINUTES", "5,30,60").split(",") if x.strip()
]
PRIMARY_HORIZON = int(os.environ.get("PRIMARY_HORIZON", "30"))

SEQ_LEN = int(os.environ.get("SEQ_LEN", "64"))
FLAT_THRESHOLD = float(os.environ.get("FLAT_THRESHOLD", "0.002"))  # 0.2% default
# Flat band scales roughly with horizon (bps of move to count as directional)
FLAT_THRESHOLD_PER_HORIZON = {
    1: float(os.environ.get("FLAT_TH_1M", "0.0005")),
    5: float(os.environ.get("FLAT_TH_5M", "0.0008")),
    15: float(os.environ.get("FLAT_TH_15M", "0.001")),
    30: float(os.environ.get("FLAT_TH_30M", "0.002")),
    60: float(os.environ.get("FLAT_TH_1H", "0.003")),
    240: float(os.environ.get("FLAT_TH_4H", "0.006")),
}

PAIRS = [
    p.strip()
    for p in os.environ.get("WHITELIST_PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
    if p.strip()
]
CANDLE_INTERVAL = os.environ.get("CANDLE_INTERVAL", "1m")

MODEL_DIR = os.environ.get("MODEL_DIR", "/models")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/workspace/train/output")

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "32"))
EPOCHS = int(os.environ.get("EPOCHS", "40"))
LR = float(os.environ.get("LR", "5e-4"))
WEIGHT_DECAY = float(os.environ.get("WEIGHT_DECAY", "1e-4"))
HIDDEN_SIZE = int(os.environ.get("HIDDEN_SIZE", "64"))
VAL_FRACTION = float(os.environ.get("VAL_FRACTION", "0.2"))
EARLY_STOP_PATIENCE = int(os.environ.get("EARLY_STOP_PATIENCE", "5"))
# Gate used when ranking checkpoints (matches serve default)
CKPT_GATE_THRESHOLD = float(os.environ.get("CKPT_GATE_THRESHOLD", "0.40"))
MIN_GATED_FOR_CKPT = int(os.environ.get("MIN_GATED_FOR_CKPT", "50"))

# Confidence gate default (product / serve)
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.40"))
GATE_THRESHOLD = float(os.environ.get("GATE_THRESHOLD", "0.40"))

# Feature vector size per timestep (must match features.py)
FEATURE_DIM = 16

# Class names for logging
CLASS_NAMES = ["down", "flat", "up"]
