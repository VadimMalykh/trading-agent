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

SEQ_LEN = int(os.environ.get("SEQ_LEN", "128"))
# Auxiliary 2-class directional head (down/up), trained only on bars that moved.
# Gives a clean up-vs-down signal not diluted by the ~52% flat mass.
DIRECTIONAL_HEAD = os.environ.get("DIRECTIONAL_HEAD", "1") not in ("0", "false", "False")
# Weight of the auxiliary directional loss relative to the 3-class loss.
DIR_LOSS_WEIGHT = float(os.environ.get("DIR_LOSS_WEIGHT", "1.0"))
# Auxiliary quantile head: per-horizon regression of forward-return quantiles
# (pinball loss). Policy-agnostic risk/vol context for the future RL policy; does
# not affect the 3-class or directional heads. Off by default until validated.
QUANTILE_HEAD = os.environ.get("QUANTILE_HEAD", "0") not in ("0", "false", "False")
QUANTILE_LEVELS = [
    float(x) for x in os.environ.get("QUANTILE_LEVELS", "0.1,0.5,0.9").split(",") if x.strip()
]
# 0.2 (was 0.5): at 0.5 the pinball loss stole shared-encoder capacity and dented
# the directional edge (~-0.014). 0.2 keeps the risk head as a light auxiliary.
QUANTILE_LOSS_WEIGHT = float(os.environ.get("QUANTILE_LOSS_WEIGHT", "0.2"))
# --- Calibration-aware checkpoint selection (quantile runs only) -----------------
# Checkpoint selection ranks on directional edge (Wilson-LB dir_acc @ top-cov).
# When the quantile head is on, that alone can save a directionally-good but
# poorly-calibrated epoch. These knobs multiply the selection score by a penalty
# that grows as the primary-horizon band coverage drifts from its target, so the
# saved epoch is both directionally good AND calibrated. No effect when the
# quantile head is off (q_cov is None → no penalty).
#   penalty = 1 - CAL_PENALTY_WEIGHT * min(1, |band_cov - target| / CAL_TOL)
# CAL_TARGET<=0 is a sentinel meaning "use the band width" (levels[-1]-levels[0]).
CAL_PENALTY_WEIGHT = float(os.environ.get("CAL_PENALTY_WEIGHT", "0.5"))
CAL_TARGET = float(os.environ.get("CAL_TARGET", "0"))  # 0 => band width (e.g. 0.80)
CAL_TOL = float(os.environ.get("CAL_TOL", "0.10"))
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
EPOCHS = int(os.environ.get("EPOCHS", "60"))
LR = float(os.environ.get("LR", "5e-4"))
WEIGHT_DECAY = float(os.environ.get("WEIGHT_DECAY", "1e-4"))
HIDDEN_SIZE = int(os.environ.get("HIDDEN_SIZE", "64"))
# LSTM + head dropout. 0.2 default preserves the served candle model. Raise it
# (and/or lower HIDDEN_SIZE) for the tiny dense-book walk-forward regime, where
# the model overfits within ~2-5 epochs (see docs/NEXT_TRAINING_PLAN.md).
DROPOUT = float(os.environ.get("DROPOUT", "0.2"))
VAL_FRACTION = float(os.environ.get("VAL_FRACTION", "0.2"))
# Patience raised: directional coverage kept climbing when the old run stopped.
EARLY_STOP_PATIENCE = int(os.environ.get("EARLY_STOP_PATIENCE", "10"))
# Gate used when ranking checkpoints (matches serve default)
CKPT_GATE_THRESHOLD = float(os.environ.get("CKPT_GATE_THRESHOLD", "0.40"))
# Checkpoints are ranked by directional edge at this FIXED coverage (top fraction
# of bars by confidence), not by a fixed confidence threshold. This keeps the
# selection metric comparable across epochs even as the softmax scale drifts.
SEL_COVERAGE = float(os.environ.get("SEL_COVERAGE", "0.05"))
# Minimum number of *true-directional* gated trades (at SEL_COVERAGE) required
# before a checkpoint's edge is trusted at full weight. Raised from 50 so a
# lucky ~200-sample fluke can no longer win selection.
MIN_GATED_FOR_CKPT = int(os.environ.get("MIN_GATED_FOR_CKPT", "500"))

# --- 3-class head class weighting (down/flat/up) ---------------------------------
# The plain inverse-frequency weighting (w = N / (3*count), mean-normalized) let
# the large flat mass inflate the down/up weights, which — on a near-signal-less
# task — pushed the 3-class argmax to collapse onto flat + the recent drift
# direction (it stopped predicting "down" almost entirely). These knobs gentle
# that pressure. They touch ONLY the 3-class head; the directional head keeps its
# own separate (down-vs-up) weighting, so directional edge is unaffected.
#   sqrt_inv_freq: w = 1/sqrt(count)   (gentler than 1/count)
#   inv_freq:      w = 1/count         (legacy behavior)
CLS_WEIGHT_MODE = os.environ.get("CLS_WEIGHT_MODE", "sqrt_inv_freq")
# Clamp normalized weights to [1/clip, clip] so no class dominates the CE.
CLS_WEIGHT_CLIP = float(os.environ.get("CLS_WEIGHT_CLIP", "2.0"))
# Label smoothing on the 3-class CE keeps some mass on every class, discouraging
# a hard collapse to a single class. Directional CE is left unsmoothed.
CLS_LABEL_SMOOTHING = float(os.environ.get("CLS_LABEL_SMOOTHING", "0.05"))

# Confidence gate default (product / serve)
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.40"))
GATE_THRESHOLD = float(os.environ.get("GATE_THRESHOLD", "0.40"))

# --- Cost model (eval P&L only) --------------------------------------------------
# Round-trip trading cost used by the eval P&L simulator and cost-sweep. Purely a
# reporting/analysis input at eval time; it does NOT affect training or serving.
#   round_trip = 2 * (fee + slippage), expressed as a fraction (bps / 1e4).
FEE_RATE_BPS = float(os.environ.get("FEE_RATE_BPS", "4"))
SLIPPAGE_BPS = float(os.environ.get("SLIPPAGE_BPS", "3"))
ROUND_TRIP_COST = 2.0 * (FEE_RATE_BPS + SLIPPAGE_BPS) / 1e4
# Number of disjoint time windows for walk-forward edge/P&L reporting in eval.
WF_WINDOWS = int(os.environ.get("WF_WINDOWS", "4"))

# Feature vector size per timestep (must match features.py)
# 16 signal features + 3 presence-mask flags (has_book/has_trades/has_funding_oi)
# so the model distinguishes "genuinely zero" from "missing" microstructure. The
# masks also protect per-pair z-score norm from near-constant (mostly-zero)
# features when a source has little/no history.
FEATURE_DIM = 19

# Class names for logging
CLASS_NAMES = ["down", "flat", "up"]
