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
# --- C3: magnitude-weighted directional loss (feeds run O6/R2) -------------------
# The directional CE treats a 5bps move and a 300bps move as equally important;
# the P&L does not. Eval consistently shows the model is right on smaller-than-
# average moves, which is why dir_acc 0.559 converts to only ~+9 gross bps/trade
# (docs/NEXT_TRAINING_PLAN.md §7, "cost arithmetic"). When this is on, each moved
# bar's directional CE is weighted by its realized |forward return|.
#
# The weight is normalized per (pair, horizon) against the TRAIN-window mean |r|
# for that cell. Raw |r| differs several-fold between BTC and 1000PEPE and by an
# order of magnitude between 60m and 1440m, so an unnormalized weight would
# silently reweight the PAIR MIX and the HORIZON MIX rather than the move sizes —
# trap §0.5.8 (a blend is only a blend if its terms share a dynamic range). After
# the clip the weight is rescaled so its train-set mean is exactly 1.0, which
# keeps DIR_LOSS_WEIGHT's meaning and the printed loss scale comparable to an
# unweighted run.
#
# OFF by default: this knob must not move the incumbent baseline. With it off the
# loss is byte-identical to the pre-C3 path (asserted in the unit test).
DIR_MAG_WEIGHT = os.environ.get("DIR_MAG_WEIGHT", "0") not in ("0", "false", "False", "off")
# Cap on the normalized weight, applied AFTER the power. A single 20-sigma bar
# must not own a batch's gradient; 5.0 means the largest moves count at most 5x a
# mean-sized move.
DIR_MAG_WEIGHT_CLIP = float(os.environ.get("DIR_MAG_WEIGHT_CLIP", "5.0"))
# Exponent on the normalized magnitude, applied BEFORE the clip. 1.0 weights by
# |r| (P&L-proportional); 0.5 by sqrt(|r|) is the gentler arm if 1.0 proves too
# aggressive. Do not sweep both in one run (§0.2).
DIR_MAG_WEIGHT_POWER = float(os.environ.get("DIR_MAG_WEIGHT_POWER", "1.0"))

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
    1440: float(os.environ.get("FLAT_TH_1D", "0.015")),
}

# --- Label mode (E3: triple-barrier) ---------------------------------------------
# How the 3-class direction label is derived from price after a bar:
#   fixed          (default, legacy): sign of the fixed-Δt forward return over the
#                  horizon vs FLAT_THRESHOLD. Byte-identical to the served recipe.
#   triple_barrier: from each bar, walk forward up to the horizon; label UP if a
#                  +TP barrier is hit before a -SL barrier, DOWN if -SL hits first,
#                  FLAT if neither is touched by the horizon (timeout). This labels
#                  what a TP/SL trade would ACTUALLY realize (tradeable), not the
#                  fixed-Δt endpoint sign — the standard fix for "right but not
#                  tradeable" (see docs/NEXT_TRAINING_PLAN.md E3). The quantile head
#                  still trains on the raw fixed-Δt forward return regardless.
# Barriers are volatility-scaled: TP/SL = TB_TP_MULT/TB_SL_MULT * rolling return std
# (ret_std over TB_VOL_WINDOW bars) at the entry bar, floored at TB_MIN_BARRIER so a
# dead-flat window still uses a sane band. Symmetric by default (TP == SL).
LABEL_MODE = os.environ.get("LABEL_MODE", "fixed")
TB_TP_MULT = float(os.environ.get("TB_TP_MULT", "1.5"))
TB_SL_MULT = float(os.environ.get("TB_SL_MULT", "1.5"))
TB_VOL_WINDOW = int(os.environ.get("TB_VOL_WINDOW", "15"))
TB_MIN_BARRIER = float(os.environ.get("TB_MIN_BARRIER", "0.002"))  # 0.2% floor

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
# --- Reproducibility -------------------------------------------------------------
# Until 2026-08-18 NOTHING in the training path was seeded, so two runs with an
# identical config could differ by more than most of the levers we were trying to
# measure (see docs/NEXT_TRAINING_PLAN.md §0.3: a single run cannot resolve effects
# below ~0.04 LB). That made "did this lever help?" unanswerable, and the multi-seed
# error bars §0.3 asks for were impossible to produce at all.
# SEED seeds random/numpy/torch (+CUDA) at the top of train_m2.main, so a repeat of
# the same config reproduces, and a DELIBERATE sweep (SEED=1,2,3,...) gives the
# run-to-run spread needed to put an error bar on any single-run result.
# Seeding fixes weight init, dropout masks and shuffle order. GPU kernel
# nondeterminism (atomics in cuDNN reductions) can still perturb the low bits, so
# expect same-seed runs to agree closely, not bitwise.
SEED = int(os.environ.get("SEED", "42"))
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
# Per-pair identity embedding width. 0 (default) = OFF → the encoder is fully
# pair-agnostic, exactly reproducing the served model. When >0 the model learns
# an nn.Embedding(n_pairs+1, PAIR_EMBED_DIM) (last row = OOV/unknown-pair bucket)
# and concatenates it to the pooled LSTM state before the heads, so the shared
# encoder can specialize per symbol instead of being forced to average over pairs
# whose ungated dir_acc spans ~0.39–0.66. Checkpoints record the ordered pair
# vocab + this dim so eval/serve rebuild the same symbol→index map (unknown
# symbol → OOV bucket). Old checkpoints (no vocab) load unchanged at dim 0.
# Default flipped 0 -> 8 on 2026-08-17. dim=8 is the incumbent/promoted setting
# (E2b), yet the old default of 0 meant "forgot to pass PAIR_EMBED_DIM" silently
# trained a DIFFERENT architecture than the baseline. That voided E3a and then
# voided E3-tb one session later (both ran pair-agnostic by accident). Defaulting
# to the incumbent makes an omission degrade to "same as baseline" instead of to a
# silent confound. Set PAIR_EMBED_DIM=0 explicitly for a pair-agnostic arm.
PAIR_EMBED_DIM = int(os.environ.get("PAIR_EMBED_DIM", "8"))
VAL_FRACTION = float(os.environ.get("VAL_FRACTION", "0.2"))
# Walk-forward rolling origin: end the val window this fraction of samples
# from the latest sample. 0.0 == the trailing split (the default everything
# published so far was trained on). Step by VAL_FRACTION for non-overlapping
# folds. Env-plumbed so scripts/gcp_train.sh can forward it (RETRAIN_PLAN §7
# option B); --val-offset alone was unreachable from the launcher.
VAL_OFFSET = float(os.environ.get("VAL_OFFSET", "0.0"))
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

# --- Confidence gate default (product / serve) -----------------------------------
# IMPORTANT — the gate statistic has a HARD FLOOR of 0.5. `gate.directional_signal`
# defines conf = max(p_down, p_up) over a 2-way softmax (the 'flat' column is -inf,
# see gate.dir_logits_to_three_class), so p_down + p_up == 1 and conf >= 0.5 always.
# ANY threshold <= 0.50 therefore trades every bar and is indistinguishable from
# every other threshold <= 0.50.
#
# This default used to be 0.40 — below the floor — while docker-compose.yml serves
# 0.58 (ML_GATE_THRESHOLD, raised deliberately 2026-07-23). Serving was fine, but
# eval on the train VM ran at 0.40, so every "P&L at the serve gate" line and every
# `*` marker we have ever printed pointed at a row that cannot fire and is NOT the
# operating point. It also produced the false reading "gates 0.35-0.50 are identical
# => the head emits no confidence spread". Default now matches what we serve, so the
# label tells the truth. (Trap: an env default that differs from the incumbent
# silently changes the experiment — see docs/NEXT_TRAINING_PLAN.md §0.4.2.)
#
# An EMPTY value counts as unset, not as an error. docker-compose.yml passes
# `GATE_THRESHOLD: ${ML_GATE_THRESHOLD:-}` on purpose — an empty string there means
# "no operator override, serve at the checkpoint's own measured gate" (C13) — and
# `float("")` raised ValueError at import, so ml_inference crash-looped whenever the
# override was left unset, i.e. in the default configuration.
def _float_env(name: str, default: str) -> float:
    raw = os.environ.get(name, "")
    return float(raw) if raw.strip() else float(default)


GATE_THRESHOLD = _float_env("GATE_THRESHOLD", "0.58")
# Currently unreferenced (the Elixir app gates via ML_GATE_THRESHOLD and serve.py
# reads GATE_THRESHOLD). Kept in sync so it cannot become a stale trap if wired up.
CONFIDENCE_THRESHOLD = _float_env("CONFIDENCE_THRESHOLD", "0.58")

# --- The served gate is a COVERAGE target, not a probability (C13) ---------------
# GATE_THRESHOLD above is an ABSOLUTE confidence. That is not a well-defined
# operating point across checkpoints, and the 2026-08-21 seed replicate proved it
# with three runs of ONE configuration: at conf >= 0.62 they gate 1.2% / 2.5% /
# 1.7% of bars, and the 1m model P2 gates 80% at the served 0.58. The same number
# is a different strategy on every checkpoint, so a global constant silently moves
# the operating point every time a model is promoted.
#
# What IS stable across checkpoints is the fraction of bars traded: the
# fixed-coverage P&L table is monotone in confidence for every healthy model, and
# the 5m family earns +19 to +22 gross bps/trade in its top 1-2% against roughly
# 0 at 20%. So the operator picks a COVERAGE; eval_m2.py measures the confidence
# threshold that realizes it on the val window and writes BOTH into the
# checkpoint's meta ("served_gate"); serve.py reads the threshold from there.
#
# 0.02 = trade the top 2% of bars by confidence. Chosen from the three-seed pooled
# table (+22.0 gross bps/trade over 1,783 trades, +8.0 net at 14bps taker); see
# docs/NEXT_TRAINING_PLAN.md 1.3 and 1.5.
SERVE_TARGET_COVERAGE = float(os.environ.get("SERVE_TARGET_COVERAGE", "0.02"))

# --- Cost model (eval P&L only) --------------------------------------------------
# Round-trip trading cost used by the eval P&L simulator and cost-sweep. Purely a
# reporting/analysis input at eval time; it does NOT affect training or serving.
#   round_trip = 2 * (fee + slippage), expressed as a fraction (bps / 1e4).
FEE_RATE_BPS = float(os.environ.get("FEE_RATE_BPS", "4"))
SLIPPAGE_BPS = float(os.environ.get("SLIPPAGE_BPS", "3"))
ROUND_TRIP_COST = 2.0 * (FEE_RATE_BPS + SLIPPAGE_BPS) / 1e4

# Second (optimistic / maker-execution) cost model, reported ALONGSIDE the primary
# one in the fixed-coverage P&L table. Because simulate_pnl books `side*r - cost`
# per trade and trade SELECTION is cost-independent, net P&L is exactly linear in
# cost: net(c) = gross - n_trades * c. So a second cost model costs nothing to
# report and removes the need to ever re-run eval just to change a fee assumption.
MAKER_FEE_RATE_BPS = float(os.environ.get("MAKER_FEE_RATE_BPS", "2"))
MAKER_SLIPPAGE_BPS = float(os.environ.get("MAKER_SLIPPAGE_BPS", "0.5"))
MAKER_ROUND_TRIP_COST = 2.0 * (MAKER_FEE_RATE_BPS + MAKER_SLIPPAGE_BPS) / 1e4
# Number of disjoint time windows for walk-forward edge/P&L reporting in eval.
WF_WINDOWS = int(os.environ.get("WF_WINDOWS", "4"))

# --- Feature normalization safety (P0 fix, 2026-08-17) ---------------------------
# BUG BEING FIXED: per-pair z-score stats are fit on TRAIN bars only, as
#   std = sqrt(mean_sq_dev) + 1e-6
# The 1e-6 was an ADDITIVE epsilon, not a floor. Any feature that is identically
# zero across the whole train window therefore got mean=0, std=1e-6 — and the same
# stats are then applied to VAL and to LIVE serving. Because order-book / trade /
# OI collection only started 2026-07-17 while train windows end months earlier,
# 13 of 19 features were constant-0 in train, so the moment val/live crossed into
# the book era those inputs were multiplied by 1e6 (trade_count reached ~1e8).
# The LSTM saturated and emitted a near-constant, which is what produced the
# "recent book-era edge is ~0 / the head has no confidence spread / tail-30d
# dir_acc 0.477" readings that misdirected five sessions of work. Verified in
# m2_multi_20260816T023427Z (E3-tb) and the older 16-feature snapshot.
#
# Two independent guards, both cheap:
#   1. DEGENERATE: if a column's train std is below NORM_DEGENERATE_STD it carries
#      no train information. Set std=1.0 so the column passes through UNSCALED
#      (still centered) instead of being blown up by 1/std. Columns above the
#      threshold keep the legacy `+1e-6` arithmetic exactly, so this is a no-op for
#      every feature that was already normalized sanely (the smallest real std
#      observed is funding ~9.6e-5, three orders of magnitude above the threshold).
#   2. CLIP: hard-clip normalized values to +/-NORM_CLIP. Catches the NEAR-constant
#      case that guard 1 cannot (e.g. a 0/1 mask with 3 nonzero bars in 9M has a
#      small-but-nonzero std -> z up to ~1700). 50 sigma is far outside anything a
#      real feature reaches, so this too is inert on healthy columns. 0 disables.
# Degenerate columns are ALWAYS logged loudly (train, eval and serve) — a silent
# feature-scaling failure must never happen again (cf. the R3 silent-fallback lesson).
NORM_DEGENERATE_STD = float(os.environ.get("NORM_DEGENERATE_STD", "1e-8"))
NORM_CLIP = float(os.environ.get("NORM_CLIP", "50.0"))
# What to feed the model for a column that was CONSTANT in train:
#   "zero"        (default) -> force the column to 0 in train, val AND serve. This is
#                 the only train/val-consistent choice: the model was trained with that
#                 input pinned at one value, so showing it a real value at val/serve time
#                 is out-of-distribution for an input it demonstrably learned nothing
#                 from. Zero = "this feature does not exist for this model".
#   "passthrough" -> keep the raw (centered, unscaled) value. Bounded by NORM_CLIP, but
#                 still a distribution shift, and raw scales differ wildly (trade_count
#                 ~1e2, oi ~20, imbalance ~1) so it feeds the encoder junk of assorted
#                 magnitudes. Kept for diagnosing how much the shift was costing.
# Either way the fix is 1e6x safer than the old divide-by-1e-6. To actually LEARN from
# book features you need a train window that contains them (--require-book), not a
# normalization tweak.
NORM_DEGENERATE_MODE = os.environ.get("NORM_DEGENERATE_MODE", "zero").strip().lower()
# Legacy checkpoints (every one produced before 2026-08-17) have the broken
# std=1e-6 baked into meta.norm_stats. serve.py / eval sanitize on load: a stored
# std at or below this value is treated as degenerate and rewritten to 1.0. Set
# just above 1e-6 so the exact broken value is caught.
NORM_LEGACY_BROKEN_STD = float(os.environ.get("NORM_LEGACY_BROKEN_STD", "1.1e-6"))

# Feature vector size per timestep (must match len(features.FEATURE_COLS)).
#
#   19 legacy = 16 signal + 3 presence masks (has_book/has_trades/has_funding_oi),
#               so the model can tell "genuinely zero" from "missing" microstructure.
#              The masks also protect per-pair z-score norm from near-constant
#              (mostly-zero) columns when a source has little/no history.
# +  6 (C12)  own-pair multi-scale: ret_1h/4h/1d, vol_1h/4h/1d
# +  5 (C12)  market context: btc_rel_ret_1h, beta_btc_1d, xs_rank_1h, xs_disp_1h,
#              has_market
#   = 30
#
# Changing this changes the SERVING CONTRACT. Old checkpoints keep working because
# features.FEATURE_COLS[:19] is frozen as LEGACY_FEATURE_COLS and eval/serve request
# the column list recorded in the checkpoint's own meta.
FEATURE_DIM = int(os.environ.get("FEATURE_DIM", "30"))

# Which feature groups to build (C18, 2026-08-22). Comma-separated:
#
#   legacy      the 19 frozen columns (LEGACY_FEATURE_COLS) - always required
#   multiscale  own-pair ret_1h/4h/1d + vol_1h/4h/1d         (6)
#   market      cross-pair context, incl. has_market         (5)
#
# The default reproduces the 30-column set exactly, so this knob is a no-op unless
# it is set. features.FEATURE_DIM_EFFECTIVE is DERIVED from the selected groups;
# FEATURE_DIM above stays as the documented default and is no longer asserted
# against the column list - that assert is what made a subset impossible to run
# without editing source.
#
# This knob must also be in FLUX_TRAIN_ENV_KEYS in scripts/gcp_train.sh, or it is a
# silent no-op on the GPU VM and the run quietly trains the default column set while
# the launcher claims otherwise (trap 0.5.7). It is; keep it that way.
FEATURE_GROUPS = os.environ.get("FEATURE_GROUPS", "legacy,multiscale,market")

# Class names for logging
CLASS_NAMES = ["down", "flat", "up"]
