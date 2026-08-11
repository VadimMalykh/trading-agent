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
# --- Microstructure staleness caps (feature build) -------------------------------
# The book/trade/OI/funding sources are asof-ffilled onto the 1m candle grid. A
# collection OUTAGE (e.g. the 6.4-day book gap 2026-07-29→08-04) would otherwise
# forward-fill a single FROZEN snapshot across thousands of bars, all mislabeled
# has_*=1 — off-distribution garbage the model can't tell from fresh data (this was
# the root cause of the book-era edge collapse; see docs/NEXT_TRAINING_PLAN.md
# "TASK 1"). When the ffilled source is older than its cap we revert to the honest
# "missing" path: zero that group's features AND set its presence mask to 0.
# Caps are per-source because their natural cadence differs:
#   book   ~7-16s   → minutes-scale cap
#   trades ~per 1m  → minutes-scale cap
#   funding/OI      → LOW frequency (hourly+); a long cap, else they'd read missing
# 0 disables a cap (legacy unbounded-ffill behavior).
BOOK_MAX_AGE_MIN = float(os.environ.get("BOOK_MAX_AGE_MIN", "5"))
TRADES_MAX_AGE_MIN = float(os.environ.get("TRADES_MAX_AGE_MIN", "5"))
FUNDING_OI_MAX_AGE_MIN = float(os.environ.get("FUNDING_OI_MAX_AGE_MIN", "480"))  # 8h

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

# 256 (was 32): the M2 LSTM is tiny (~65k params), so a 32-batch GPU step was
# ~117k steps/epoch bottlenecked on DataLoader IPC, not compute. Bigger batches
# cut steps/epoch 8x and feed the GPU properly. A 256-batch input tensor is ~2.5MB
# vs GBs of VRAM; no OOM risk at these sizes. Override with env BATCH_SIZE.
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "256"))
# DataLoader workers for window slicing. The M2 model is data-pipeline-bound
# (millions of windows/epoch), so a handful of workers keeps a GPU fed without
# the main process doing per-sample slicing. n1-standard-4 has 4 vCPUs — 4 fits.
# 0 = main process only (lowest RAM). Override with env NUM_WORKERS.
NUM_WORKERS = int(os.environ.get("NUM_WORKERS", "4"))
# Batches prefetched ahead per worker; 2 is the torch default, 4 smooths
# pipeline jitter. Override with env PREFETCH_FACTOR.
PREFETCH_FACTOR = int(os.environ.get("PREFETCH_FACTOR", "4"))
EPOCHS = int(os.environ.get("EPOCHS", "60"))
LR = float(os.environ.get("LR", "5e-4"))
WEIGHT_DECAY = float(os.environ.get("WEIGHT_DECAY", "1e-4"))
HIDDEN_SIZE = int(os.environ.get("HIDDEN_SIZE", "64"))
# Encoder depth (stacked LSTM layers). Default 2 preserves the served model. The
# GPU run early-stopped with train/val loss still moving together and the aux head
# never emitting confidence >0.5 (see logs/latest_fixed.log) → the directional task
# is UNDERfit, so capacity is a candidate lever now that we're on GPU. Bump via
# NUM_LAYERS / HIDDEN_SIZE for a capacity arm; watch for book-era overfit.
NUM_LAYERS = int(os.environ.get("NUM_LAYERS", "2"))
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

# --- Cost-aware checkpoint selection ---------------------------------------------
# The Wilson-LB dir_acc score ranks a model on HIT-RATE only. At a real round-trip
# cost, hit-rate ignores trade SIZE: being right 55% on tiny moves loses money while
# 52% on large moves wins. SEL_NET_WEIGHT blends a cost-aware term (mean net return
# per gated trade at SEL_COVERAGE, after SEL_COST_BPS round-trip, scaled to bps and
# squashed) into the selection score so training targets expected P&L, not just
# accuracy. 0.0 = legacy hit-rate-only selection (safe default until validated).
#   sel_score = (1 - w) * edge_lb_score + w * net_ret_score
# SEL_COST_BPS is the round-trip cost used ONLY for selection (kept separate from the
# eval cost model FEE/SLIPPAGE so we can stress selection without touching reporting).
SEL_NET_WEIGHT = float(os.environ.get("SEL_NET_WEIGHT", "0.0"))
SEL_COST_BPS = float(os.environ.get("SEL_COST_BPS", "14"))
# Net-return-per-trade (a fraction, e.g. 0.0006) is tiny vs the ~0.5 edge score, so
# squash it into a comparable (0,1) range before blending. Mapping is a smooth,
# strictly-monotonic logistic centered at 0 (train_m2.checkpoint_score):
#   net_score = sigmoid(2 * net_per_trade / SEL_NET_SCALE)
#   net=0 → 0.5 ; net=+SCALE → ~0.88 ; net=-SCALE → ~0.12
# SCALE ≈ the net-return width that spans most of (0,1). It NEVER saturates to
# exactly 0/1, so — unlike the old clip(0.5+net/scale,0,1) — the score keeps
# ranking epochs even when every epoch is net-negative to cost (the R1 failure
# mode: net_sc pinned at 0.000 all run). Tunable; only affects selection ranking.
SEL_NET_SCALE = float(os.environ.get("SEL_NET_SCALE", "0.002"))

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
