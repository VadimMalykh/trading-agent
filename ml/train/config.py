import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fluxtrader:secret@postgres:5432/fluxtrader",
)

# M1 defaults (see MODEL.md / docs/M1_PLAN.md)
HORIZON_MINUTES = int(os.environ.get("HORIZON_MINUTES", "15"))
SEQ_LEN = int(os.environ.get("SEQ_LEN", "32"))
FLAT_THRESHOLD = float(os.environ.get("FLAT_THRESHOLD", "0.001"))  # 0.1%
PAIRS = os.environ.get("WHITELIST_PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
CANDLE_INTERVAL = os.environ.get("CANDLE_INTERVAL", "1m")

MODEL_DIR = os.environ.get("MODEL_DIR", "/models")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/workspace/train/output")

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "32"))
EPOCHS = int(os.environ.get("EPOCHS", "10"))
LR = float(os.environ.get("LR", "1e-3"))
HIDDEN_SIZE = int(os.environ.get("HIDDEN_SIZE", "64"))
VAL_FRACTION = float(os.environ.get("VAL_FRACTION", "0.2"))

# Feature vector size per timestep (must match features.py)
FEATURE_DIM = 16
