# Next Training Plan (M2 → upgrade run, then M3 prep)

Status doc so work survives session loss. Captures decisions from the planning
session and the exact steps/commands to execute.

## TL;DR

- The current training run is **compute-bound, never memory-bound** (feature RAM
  ~48 MiB via lazy windowing in `ml/train/data/dataset.py:501`). So the answer to
  "should we downsize RAM or use it for speed?" is: **neither** — spend on vCPU.
- Let the **current run finish** and capture it as the **baseline**.
- Prepare infra + data changes **on a branch now**; launch the new run only after
  the current one finishes (pipeline reuses one VM name + `latest.*` bucket keys,
  so parallel runs collide).
- Model-head experiment (quantile head) comes **later, as its own run**.

## Baseline reference (current run, still training)

- Pairs: BTCUSDT, ETHUSDT, SOLUSDT (3), 180 days, seq_len 128.
- Samples: 788,705 (train 630,964 / val 157,741).
- Best so far @ epoch 13: `sel_score=0.5546 dir_acc=0.569 Wilson_lb=0.552 n_dir=4822`.
- Selection score still climbing (new best at 1→6→11→13), val loss monotonic down
  (1.0400 → 1.0258), no overfit signal. **Let it run to completion.**
- Interpretation: a ~0.55 lower-bound directional edge at 5% coverage is a *modest
  but real* signal. It is the apples-to-apples baseline for all future runs.
- **Caveat:** trained on 180d candles but only ~7d of real microstructure, so the
  edge is essentially candle-driven (see "Data audit findings"). The orderbook edge
  is not yet exercised.

---

## Part 0 — Pull current best checkpoint for UI reference (safe, no job impact)

The best checkpoint lives only in the training VM's docker volume
(`trading_agent_model_weights` → `/models/m2_multi.pt`). It is **not** in the
bucket until the run finishes (`scripts/gcp_train.sh:229-235`) — that is why
`gcp_promote.sh` (status `<none>`) and
`gcloud storage cp .../checkpoints/latest.pt` both fail right now. Expected.

Copy it out (read-only w.r.t. the job):

```sh
# 1. On the training VM: copy checkpoint out of the docker volume to VM home
gcloud compute ssh fluxtrader-train --project=fluxtrader --zone=me-central1-b -- \
  'docker run --rm -v trading_agent_model_weights:/models -v $HOME:/out alpine \
     sh -c "cp /models/m2_multi.pt /out/m2_multi_epoch_snapshot.pt && ls -la /out/m2_multi_epoch_snapshot.pt"'

# 2. Copy from VM down to Mac
gcloud compute scp --project=fluxtrader --zone=me-central1-b \
  fluxtrader-train:~/m2_multi_epoch_snapshot.pt ./m2_multi_epoch_snapshot.pt
```

Cautions:
- Point-in-time snapshot; training keeps overwriting the file on each new best.
- **Do NOT use `scripts/gcp_promote.sh`** for UI reference — it recreates
  `ml_inference` on the always-on VM (`scripts/gcp_promote.sh:71`), i.e. puts the
  model in the serving path. Load the copied file in a **separate/dev inference**.
- Checkpoint is self-contained (stores `norm_stats` + head config).

### Serving this checkpoint in the always-on UI (dev-only, not production)

Serve path: `ml_inference` (`ml/train/serve.py`, port 8001) reads
`/models/m2_multi.pt` from the `trading_agent_model_weights` volume → Elixir
`Predict` (Finch, `apps/fluxtrader/lib/fluxtrader/ml/predict.ex`) → `SignalEngine`
→ `DashboardLive`. `serve.py` rebuilds the model from the checkpoint's own `meta`
(horizons/seq_len/feature_dim/hidden/dir_head) and only loads at startup.

```sh
# 1. Upload the pulled checkpoint to the always-on VM
gcloud compute scp --project=fluxtrader --zone=me-central1-b \
  ./m2_multi_epoch_snapshot.pt fluxtrader-1:/tmp/m2_multi.pt

# 2. Install into the model volume + restart inference (mirrors gcp_promote.sh:66-71)
gcloud compute ssh fluxtrader-1 --project=fluxtrader --zone=me-central1-b -- '
  cd ~/trading_agent &&
  docker volume create trading_agent_model_weights >/dev/null 2>&1 || true &&
  docker run --rm -v trading_agent_model_weights:/models -v /tmp:/in:ro alpine \
    sh -c "cp /in/m2_multi.pt /models/m2_multi.pt && ls -la /models/m2_multi.pt" &&
  docker compose up -d --force-recreate ml_inference &&
  sleep 4 && curl -sS http://127.0.0.1:8001/health
'
```

Healthy = `{"ok": true, "model_path": "/models/m2_multi.pt", "norm": "ckpt", ...}`.
Notes: overwrites whatever `m2_multi.pt` is currently served; predictions need live
features from the always-on DB, so keep the whitelist on pairs with recent data.
Later, run a second `serve.py` on another port/`MODEL_PATH` to separate dev-eval
from UI signals (no code change needed).

---

## Part 1 — Do NOT launch a second run in parallel

Pipeline reuses fixed VM name `fluxtrader-train` (`scripts/gcp_common.sh:19`) and
fixed bucket keys (`dumps/latest.sql.gz`, `status/latest.json`,
`checkpoints/latest.pt`). A second `gcp_train.sh` collides with the running job.
Prepare changes on a branch; launch only after the current run finishes.

---

## Part 2 — Capture baseline when current run finishes

On success the job self-deletes the VM and uploads log/status/checkpoint
(`scripts/gcp_train.sh:174-176`).

```sh
./scripts/gcp_status.sh                 # confirm DONE, VM gone
gcloud storage cp gs://fluxtrader-train-artifacts/checkpoints/latest.pt ./baseline_m2_multi.pt
gcloud storage cat gs://fluxtrader-train-artifacts/status/latest.json    # record git_sha + run id
```

Save final `sel_score/dir_acc/lb/n_dir` and the `eval_m2.py` gate sweep from the
log. This is the comparison point for every future run.

---

## Part 3 — Infra changes (branch now, apply to next run)

RAM was never the bottleneck; this is purely CPU/wall-clock.

- `scripts/gcp_common.sh:20` — `GCP_TRAIN_MACHINE=e2-standard-2` → `e2-standard-4`
  (4 vCPU). Note: e2-standard-4 is fixed at 16 GB. For 4 vCPU with less RAM (cost),
  use `e2-custom-4-4096`.
- `scripts/gcp_env.example:13-14` — update stale "8GB is enough" RAM comment.
- `docker-compose.yml` (ml_trainer env) — add `BATCH_SIZE=128`, `OMP_NUM_THREADS=4`;
  reconcile the `SEQ_LEN=64` compose override vs. GCP's 128 (`scripts/gcp_common.sh:23`).
- `ml/train/train_m2.py` DataLoader (~lines 268-276) — pass `num_workers=2` +
  `persistent_workers=True` (arg exists at `train_m2.py:89`, defaults 0). Optionally
  add `torch.set_num_threads(N)` at startup (none exists today).
- Optional `ml/train/config.py:44` — bump default `BATCH_SIZE`.

Verify: short run (`--epochs 2`) comparing wall-clock/epoch + peak RAM
(`docker stats`) before/after; confirm larger batch doesn't degrade val metrics.
Larger batch may need a small LR nudge (`ml/train/config.py:46`).

---

## Part 4 — Data changes (branch now, run after baseline)

- **Next run pairs: BTC, ETH, SOL, DOGE, WLD, HYPE (6).** Audit passed for all six
  (see "Data audit findings" below). Set via `TRAIN_PAIRS` (`scripts/gcp_common.sh`).
  All six are enrolled in the always-on whitelist and in the dump (`DUMP_TABLES`
  covers all tables, `scripts/gcp_common.sh:44`).
- **Keep 180d for now.** 360d not useful yet — candles go back ~180d only, and
  microstructure is far shorter (below). Extending needs more candle history first.
- **Per-pair evaluation** is implemented (`ml/train/eval_m2.py`), enhanced to report
  fixed-coverage 0.05 `dir_acc / wilson_lb / n_dir` per pair. Use it to detect
  whether pooling higher-vol alts (DOGE/WLD/HYPE) degrades the majors' edge through
  the shared encoder. If it does → consider separate majors/alts models or weighting.
- Sequencing: Run 1 = 6 pairs / 180d / per-pair eval / e2-standard-4. Never change
  data AND architecture in the same run (can't attribute the change).

## Data audit findings (2026-07-24)

Queried the always-on VM Postgres (`fluxtrader-1`). Per-symbol row counts + spans:

| Pair | 1m candles | candle span | book/trades/OI/funding span |
|------|-----------:|-------------|-----------------------------|
| BTC  | 263,705 | Jan 22 → Jul 24 (~180d) | Jul 17 → Jul 24 (~7d) |
| ETH  | 263,694 | Jan 22 → Jul 24 | Jul 17 → Jul 24 (~7d) |
| SOL  | 263,683 | Jan 22 → Jul 24 | Jul 17 → Jul 24 (~7d) |
| DOGE | 259,784 | Jan 24 → Jul 24 | Jul 21 → Jul 24 (~3d) |
| WLD  | 259,746 | Jan 24 → Jul 24 | Jul 21 → Jul 24 (~3d) |
| HYPE | 259,765 | Jan 24 → Jul 24 | Jul 21 → Jul 24 (~3d) |

Key facts and their consequences:

- **All 6 pairs have full ~180d of 1m candles** (~260K rows). HYPE is valid — no
  reason to hold it out. → next run uses 6 pairs.
- **Microstructure is tiny for EVERY pair** (~3–7 days). The live collector
  (`apps/fluxtrader/lib/fluxtrader/market_data/collector.ex`) only began populating
  `orderbook_snapshots`, `market_trades`, `open_interest`, `funding_rates` recently.
  There is **no historical backfill** for book/trades/OI (only candles+funding can be
  backfilled via `ml/train/backfill_history.py`).
- **⚠️ Affects the CURRENT baseline model too.** For ~173 of 180 days, ~11 of 16
  features (`spread_bps, imbalance, micro_mid, bid_ask_vol_ratio, depth_near_imb,
  trade_count, buy_sell_imb, trade_vol, funding, oi, oi_chg`) are **zero-filled**
  (`ml/train/data/features.py:54-56,69-72,80-81,89-91`). The ~0.55 directional edge
  is therefore driven mainly by the 4 OHLCV-derived features; the orderbook edge is
  NOT meaningfully exercised yet.
- **Design decision:** the model tolerates missing microstructure via zero-fill.
  New pairs will always start with empty microstructure, so this must always work.
- **Normalization risk:** near-constant (mostly-zero) features → tiny std in per-pair
  z-score (`fit_norm_from_bundle`), which can amplify the few real values into
  spikes. Watch per-pair eval for instability.

### Follow-up work created by this finding
1. **Presence-mask features (Part 5 experiment):** add `has_book / has_trades /
   has_funding_oi` binary columns so the model distinguishes "genuinely zero" from
   "missing". Bumps `FEATURE_DIM` 16→~19 — coordinated change across
   `ml/train/data/features.py`, `ml/train/config.py` (`FEATURE_DIM`), and the model
   `input_size` (`ml/train/models/multi_horizon.py`). Requires retrain.
2. **Microstructure-rich run (weeks out):** once the collector has accumulated enough
   book/trades/OI history, do a run that actually tests the orderbook edge, and
   compare against the current candle-driven baseline.

---

## Part 5 — Model-head experiment (LATER, separate run)

Design principle: **"M2 describes the market; M3 (RL) decides the trade."** M2
outputs stay policy-agnostic (direction, confidence, forward distribution);
stops/takes/size belong to M3.

- Add **one per-horizon quantile head (p10/p50/p90 of forward return, pinball
  loss)** on the existing shared encoder (`ml/train/models/multi_horizon.py:40-69`),
  leaving current 3-class + directional heads untouched.
- Rationale for RL: quantiles/vol let the policy risk-normalize (the thing naive RL
  gets wrong). Avoid triple-barrier as the primary M2→RL input (pre-commits to fixed
  levels, constrains the policy); keep it as an eval label / rules fallback.
- Validate calibration first (do ~80% of outcomes fall in [p10,p90]?) and confirm
  the directional metric doesn't regress vs. baseline. Expect the first version to
  be rough — treat as "risk context," not precision.
- One change at a time, its own run.

---

## Execution order

1. **Now:** Part 0 (pull epoch checkpoint for UI); Part 3+4 code/config on a new
   git branch (no run launched).
2. **When current run finishes:** Part 2 (capture baseline).
3. **Then:** launch Run 1 (infra + 6 pairs + per-pair eval), compare to baseline.
4. **Later:** microstructure-rich run once book history accumulates, presence-mask
   features, and Part 5 (quantile head).

## How to stop the current run early (if ever needed)

Delete the instance directly — kills job + removes billing (boot disk) in one step:

```sh
gcloud compute instances delete fluxtrader-train --zone=me-central1-b --project=fluxtrader
```

Do NOT just kill tmux: a non-zero exit triggers `finish FAILED` which only STOPs
the VM (`scripts/gcp_train.sh:178-179`), leaving the boot disk billing.
