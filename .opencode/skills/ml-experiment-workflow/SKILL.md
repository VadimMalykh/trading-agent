---
name: ml-experiment-workflow
description: Use when training, evaluating, backtesting, or promoting the FluxTrader crypto signal model (M2 multi-horizon LSTM) — e.g. running train_m2.py/eval_m2.py, interpreting eval_m2 metrics (dir_acc, Wilson LB, Sharpe, max drawdown, calibration), running microstructure ablation/walk-forward/audit studies, or using any scripts/gcp_*.sh remote training script. Also use when the user mentions "M2 model", "gate threshold", "checkpoint", GATE_THRESHOLD, or "book-on/book-off" ablation.
---

# FluxTrader ML experiment workflow

Everything here runs in Docker per `AGENTS.md` (no host Python/Mix). Never
`pip install` or run `python` on the host for this project.

## Mental model

- Model: `SharedEncoderMultiHead` (`ml/train/models/multi_horizon.py`) — one
  LSTM encoder, per-horizon 3-class heads (down/flat/up) for horizons in
  `HORIZONS_MINUTES` (default `5,30,60`; primary = 30m), plus an auxiliary
  2-class directional head and an optional quantile head.
- No hand-built TA indicators are core features — see `MODEL.md`. Inputs are
  OHLCV-derived + microstructure (order book, funding, OI) with presence
  masks for missing data.
- Checkpoint: `/models/m2_multi.pt` inside containers, backed by the external
  `trading_agent_model_weights` Docker volume. `ml_inference` loads it once
  at boot; a training run does NOT auto-update the live service — promotion
  is a separate explicit step.
- `GATE_THRESHOLD` (default 0.58 in compose) is the confidence cutoff at
  which the inference service converts a per-horizon softmax into a gated
  BUY/SELL/FLAT trade decision. It's also the default eval/backtest gate in
  `eval_m2.py`; edge historically only shows up around ≥0.55 confidence.

## Local training/eval (small runs, fast iteration)

```bash
# train
docker compose --profile ml run --rm ml_trainer python train_m2.py \
  --epochs 40 --seq-len 128

# eval / backtest the resulting checkpoint
docker compose --profile ml run --rm ml_trainer python eval_m2.py \
  --checkpoint /models/m2_multi.pt
```

Both scripts take env-var hyperparams too (see `ml/train/config.py`):
`HORIZONS_MINUTES`, `SEQ_LEN`, `LR`, `BATCH_SIZE`, `WEIGHT_DECAY`,
`DIRECTIONAL_HEAD`, `DIR_LOSS_WEIGHT`, `QUANTILE_HEAD`,
`QUANTILE_LOSS_WEIGHT`, `GATE_THRESHOLD`, `WHITELIST_PAIRS`,
`BOOK_MAX_AGE_MIN`/`TRADES_MAX_AGE_MIN`/`FUNDING_OI_MAX_AGE_MIN` (staleness
caps — a stale-book outage can otherwise forward-fill frozen features and
silently poison training; see comments in `config.py`).

Sanity-check whether microstructure features are worth training on at all
(cheap, read-only, no training) before investing in a full run:

```bash
docker compose --profile ml run --rm ml_trainer python audit_microstructure.py
```

## Remote training on GCP (bigger runs)

Config/helpers: `scripts/gcp_env` (copy from `gcp_env.example`),
`scripts/gcp_common.sh`. Standard 3-step flow, each step is a single command
run from the host shell (these are ops scripts, not app code — this is the
one part of the ML workflow that's expected to run outside Docker, since
they just orchestrate `gcloud`):

```bash
./scripts/gcp_train.sh [epochs] [seq_len]        # STEP 1/3: spin up throwaway VM, train+eval, push checkpoint, self-delete
./scripts/gcp_status.sh                          # STEP 2/3: poll run status / tail log
./scripts/gcp_promote.sh                         # STEP 3/3: install checkpoint on always-on VM, restart ml_inference
```

Variants:
- `TRAIN_PAIRS=BTCUSDT,ETHUSDT ./scripts/gcp_train.sh 60 128` — override pairs.
- `./scripts/gcp_train.sh --gpu` — GPU instance.
- `KEEP_VM=1 ./scripts/gcp_train.sh` — debug, skip self-delete.
- `./scripts/gcp_logs.sh [run_id] [--list|--save]` — full log (status.sh only tails 40 lines).
- `./scripts/gcp_promote.sh --local-copy` — also back up checkpoint locally; `--force` skips the DONE-status guard.

Research studies (run on their own throwaway VMs, separate from training —
safe to run concurrently with `gcp_train.sh`):
- `./scripts/gcp_ablate.sh` — book-features ON vs OFF, decides if
  microstructure collection is worth it once modeled (not just correlated).
- `./scripts/gcp_walkforward.sh` — repeats the book ON/OFF gap across
  several rolling-origin folds to check it isn't a single-window fluke.
- `./scripts/gcp_audit.sh` — runs `audit_microstructure.py` remotely (the
  always-on VM OOMs on it).
- `./scripts/gcp_data_collection_stats.sh` — SQL freshness/health checks on the
  always-on collector's order book/trade/funding/OI tables.
- `./scripts/quant_ab.sh` — 3-arm A/B on the quantile head (off / weight 0.2 / weight 0.5).

## Interpreting `eval_m2.py` output

**`--gate` vs `GATE_THRESHOLD` — do NOT confuse them (avoids redundant runs).**
`eval_m2.py --gate 0.35,0.4,...` is the *sweep list*: it evaluates ALL those
thresholds in ONE run (`eval_m2.py:462`, split at :617) and prints one row per
threshold. `GATE_THRESHOLD` (env, `config.py:175`, default 0.40) is only the
*serve default* — in eval it merely marks that row with `*` and force-inserts
it into the sweep if missing. So running the same checkpoint 3× with different
`GATE_THRESHOLD` and no `--gate` gives ~identical tables (only the `*` moves) —
wasted compute. To compare thresholds, use ONE run with the full `--gate` list;
set `GATE_THRESHOLD` only to highlight your intended serve gate.

Per horizon, per confidence threshold in the gate sweep:
- `dir_acc` — directional accuracy on gated predictions.
- `dir_acc_wilson_lb` (printed as `wilson_lb`) — Wilson lower bound on
  `dir_acc`; use this, not raw `dir_acc`, when judging if an edge is real at
  low sample counts (`n_dir`).
- `edge` — `dir_acc - 0.5`, i.e. edge over coin-flip.
- `win_rate`, `profit_factor`, `daily_sharpe` (annualized, `sqrt(365)`),
  `max_dd` — from `simulate_pnl`, a serial per-pair backtest net of
  round-trip cost.
- The row marked `*` is the live `GATE_THRESHOLD` (what `ml_inference`
  actually serves) — always check this row, not just the best sweep row.
- `walk_forward_edge` — same dir_acc/Wilson-LB, split across disjoint time
  windows; an edge that only shows up in one window is suspect.
- `calibration_report` — Brier-style bucketed calibration; only meaningful
  alongside directional accuracy, not instead of it. **Read it correctly before
  proposing a "calibration fix":** if p(up) mass is squeezed into a narrow band
  (e.g. [0.48,0.53]) AND `mean_pred ≈ empirical_up` in each bin with Brier ≈ 0.25,
  the head is *well-calibrated to ~zero signal*, NOT under-confident — temperature
  scaling / focal loss would then sharpen edgeless predictions and worsen P&L.
  Under-confidence only holds if `empirical_up` is systematically MORE extreme than
  `mean_pred`. Note the aux directional head (what gates) is trained with plain
  weighted CE and NO label smoothing (`train_m2.py:523`); `CLS_LABEL_SMOOTHING`
  affects only the unused 3-class head, so "disable label smoothing" is a no-op
  for the gate.
- `book_era_edge_split` — same metrics segmented by whether the microstructure
  ("book") era was live at that time, to catch outage-poisoned periods.

Judge a candidate checkpoint by: Wilson-LB edge at the live gate row, holding
up across walk-forward folds, plus acceptable `max_dd`/`daily_sharpe` — not
just headline `dir_acc`.

## Full experiment loop

1. Iterate locally with `docker compose --profile ml run --rm ml_trainer ...`
   for fast feedback (small epochs/seq_len).
2. If a change looks promising, run the full-size job on GCP:
   `gcp_train.sh` → `gcp_status.sh` (poll) → check `eval_m2.py` output in the
   log via `gcp_logs.sh`.
3. Only if Wilson-LB edge holds up across walk-forward folds and drawdown is
   acceptable, `gcp_promote.sh` to push the checkpoint live.
4. After promotion, `docker compose restart app` if the Elixir side also
   needs to pick up new gate/env settings (`ML_GATE_THRESHOLD` etc. in
   `docker-compose.yml`).
5. Log the run and result in `docs/` (check for an existing training-log doc
   like `docs/NEXT_TRAINING_PLAN.md` before creating a new file).

Note: `SignalEngine`'s `[SIM_SIGNAL]` paper-trading logs are a pipeline
smoke test only — never treat them as a substitute for `eval_m2.py` when
judging model quality (see `docs/SIMULATION.md`).
