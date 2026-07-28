# Training & Evaluation Guide

The **single** training runbook. Two parts:

- **[Part 1 — Local training](#part-1--local-training)** — collect data, train, eval,
  read curves (Docker on your machine).
- **[Part 2 — GCP pipeline](#part-2--gcp-pipeline-3-steps-self-cleaning)** — the
  3-step self-cleaning cloud flow (`gcp_train.sh` → `gcp_status.sh` →
  `gcp_promote.sh`), plus logs.

Related docs:

| Doc | Role |
|-----|------|
| [SIMULATION.md](./SIMULATION.md) | Live paper **signals** (UI / API, no real orders) |
| [M2_PLAN.md](./M2_PLAN.md) | M2 multi-horizon design |
| [PLAN.md](./PLAN.md) | Full roadmap |
| [MODEL.md](../MODEL.md) | ML architecture |
| [README.md](../README.md) | Quick start |
| [archive/GCP_TRAIN_DESIGN.md](./archive/GCP_TRAIN_DESIGN.md) | *Why* the GCP pipeline is built this way (design notes) |

**Rules:** Docker only. No host Python. Market data needs **no API keys**. GPU optional.

---

## Contents

- [Part 1 — Local training](#part-1--local-training)
  - [1. Goals (before M3)](#1-goals-before-m3)
  - [2. What data you can collect](#2-what-data-you-can-collect)
  - [3. Training (M2)](#3-training-m2)
  - [4. Evaluate signal quality (`eval_m2`)](#4-evaluate-signal-quality-eval_m2)
  - [5. Evaluate the training process (overfitting)](#5-evaluate-the-training-process-overfitting)
  - [6. Live signals (optional)](#6-live-signals-optional-not-the-main-grade)
  - [7. Recommended loop](#7-recommended-loop-no-weeks-of-waiting)
  - [8. GPU note](#8-gpu-note)
  - [9. Local troubleshooting](#9-local-troubleshooting)
  - [10. Command cheat sheet](#10-command-cheat-sheet)
- [Part 2 — GCP pipeline](#part-2--gcp-pipeline-3-steps-self-cleaning)
  - [Idea](#idea)
  - [One-time setup (Mac)](#one-time-setup-mac)
  - [The pipeline (3 steps)](#the-pipeline-3-steps)
  - [GPU mode](#gpu-mode)
  - [Getting the full logs (any run)](#getting-the-full-logs-any-run)
  - [Checklist](#checklist)
  - [Scripts](#scripts)
  - [Defaults](#gcp-defaults)
  - [GCP troubleshooting](#gcp-troubleshooting)
  - [Cost](#cost)

---
---

# Part 1 — Local training

Session-resilient guide: **more data → better M2 train → evaluate quality /
overfitting → optional live peek**.

## 1. Goals (before M3)

Improve **signal quality** of the current M2 model (`m2_multi.pt`):

1. More **historic** candles (and optional funding/OI) from Binance  
2. Longer / better **training**  
3. Judge with **train/val curves** + **`eval_m2.py`**  
4. Optionally glance at live UI signals (not a substitute for eval)

**Not yet:** full paper P&L backtest, M3 policy, real trading.

---

## 2. What data you can collect

### Binance Futures public API (no keys)

| Data | Historic bulk? | Notes |
|------|----------------|--------|
| **Klines OHLCV** | **Yes** | Up to 1500 bars/request; paginate with `startTime`/`endTime` |
| **Funding history** | **Yes** | `/fapi/v1/fundingRate` |
| **Open interest hist** | **Yes** | Futures data endpoints |
| **Agg trades** | Limited | Heavy to backfill long ranges |
| **Order book L2** | **No history** | Only live snapshots (our 5s collector) |

### What the app already does

On start, `MarketData.Collector` backfills **~500** candles per interval (1m/5m/15m/1h) per pair — only hours of 1m data, not months.

### What to run for “more data without waiting weeks”

```bash
docker compose up -d postgres

# Example: 180 days of 1m (+ 15m, 1h) for majors → candles table
docker compose --profile ml run --rm ml_trainer \
  python backfill_history.py \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --intervals 1m,15m,1h \
  --days 180
```

Optional funding backfill:

```bash
docker compose --profile ml run --rm ml_trainer \
  python backfill_history.py --symbols BTCUSDT,ETHUSDT,SOLUSDT --funding --days 180
```

Keep the app running if you also want **live book/trades** to accumulate:

```bash
docker compose up -d postgres app
```

**Book features** only improve with **live** collection time; price model can still improve a lot from kline history alone.

---

## 3. Training (M2)

### Prerequisites

- Postgres up, preferably after backfill  
- Docker image has deps (`sqlalchemy` included); if import errors:

```bash
docker compose build --no-cache ml_trainer ml_inference
```

### Basic retrain (CPU)

```bash
docker volume create trading_agent_model_weights 2>/dev/null || true
docker compose up -d postgres

docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 40 \
  --pairs BTCUSDT,ETHUSDT,SOLUSDT
```

Writes best checkpoint (by **primary gated dir_acc** @ gate 0.40, with early stop on val loss) to:

- `/models/m2_multi.pt` (Docker volume `model_weights`)  
- `/workspace/train/output/m2_multi.pt` + `history_m2.json`

**Defaults (Phase 1+2):** horizons `5,30,60`, primary **30m**, `seq_len=64`, train-only per-pair z-score (stored in checkpoint; serve uses the same), global time val split.

### Useful knobs

| Flag / env | Default | Suggestions |
|------------|---------|-------------|
| `--epochs` | 40 | early-stops on val loss (`--patience`, default 5) |
| `--seq-len` | 64 | 64 default; try 96 for slower horizons |
| `--horizons` | `5,30,60` | drop 1m; optional `15,60,240` experiment |
| `--primary` | 30 | product / checkpoint horizon |
| `--ckpt-gate` | 0.40 | gate used when ranking checkpoints |
| `--batch-size` | 32 | 32–64 |
| `--pairs` | **DB UI whitelist** (auto) | prefer majors: `BTCUSDT,ETHUSDT,SOLUSDT` |
| `--device` | `cpu` | `cuda` if GPU available in container |
| `LR` / `--lr` | `5e-4` | |
| `WEIGHT_DECAY` | `1e-4` | |
| `BATCH_SIZE` env | 32 | same as flag |

Examples:

```bash
# GPU
docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cuda --epochs 40 \
  --pairs BTCUSDT,ETHUSDT,SOLUSDT

# Custom pairs / horizons (override DB whitelist)
docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 40 \
  --pairs BTCUSDT,ETHUSDT,SOLUSDT --horizons 5,30,60 --primary 30
```

**Pairs source:** By default `train_m2` / `eval_m2` load the **Settings UI whitelist** from Postgres (`app_settings`).  
You do **not** edit the train script when you add DOGE in the UI — just collect data for that pair, then re-run train.  
Override only if needed: `--pairs BTCUSDT,DOGEUSDT`.

### After train: reload live inference (optional)

```bash
docker compose restart ml_inference
# or full stack:
docker compose up -d postgres ml_inference app
```

---

## 4. Evaluate signal quality (`eval_m2`)

**Does not** start the UI. Offline report card on **time-ordered** validation split.

```bash
docker compose --profile ml run --rm ml_trainer \
  python eval_m2.py \
  --checkpoint /models/m2_multi.pt \
  --device cpu \
  --gate 0.35,0.4,0.45,0.5,0.55,0.6
```

Output also in `ml/train/output/eval_m2.json`.

### How to read it

| Field | Meaning |
|-------|---------|
| **Ungated accuracy** | 3-class argmax (down/flat/up). Can look high if everything is “flat”. |
| **Confusion matrix** | Rows = truth, cols = pred. Flat column heavy ⇒ shy model. |
| **gate** | Directional conf threshold `max(p_up, p_down)`. |
| **coverage** | Fraction of bars that would **trade**. Falls as gate rises. |
| **n_gated** | Absolute trade count. `0` ⇒ gate too high. |
| **gated_acc** | Hit rate among gated trades (true flat = miss if we forced a side). |
| **dir_acc** | Hit rate among gated trades where truth was up/down. |
| **mean_conf** | Avg conf on gated samples. |

Focus on **primary 30m** (and its gate table) for product decisions. Compare **before vs after** more data/epochs using the same `--gate` list. Look at **edge = dir_acc − 0.5** at the serve gate (`*`).

---

## 5. Evaluate the **training process** (overfitting)

### During training

Each epoch logs train/val loss, per-horizon val acc, and **gate@0.40** coverage / dir_acc / score.  
Checkpoint saves when **primary gated score** improves. Training **early-stops** when val loss stops improving (`patience`, default 5).

| Pattern | Meaning | Action |
|---------|---------|--------|
| train loss ↓ and val loss ↓ | Healthy learning | Continue / more data |
| train ↓ , val ↑ or flat | **Overfitting** | Trust **best** ckpt (early stop should help) |
| Both stuck high | Underfit / hard task | More data, more capacity/epochs, check labels |
| Best gate score early, then worse | Classic overfit | Use saved best `m2_multi.pt` |
| High 3-class acc, tiny gate cov | Flat-dominated / unconfident | Prefer gate **dir_acc** + coverage over raw acc |

### After training

1. Inspect `ml/train/output/history_m2.json` (epoch curves).  
2. Run `eval_m2.py` (section 4).  
3. Optional live peek (section 6) — behaviour only.

### What to write down each run

| Field | Example |
|-------|---------|
| Date | 2026-07-23 |
| Backfill | 180d 1m (+ funding optional) |
| Samples (train log) | ~50000 |
| Horizons / primary | 5,30,60 / 30 |
| Epochs (stopped) | 12 (early stop) |
| seq_len | 64 |
| Best primary gate score | 0.56 |
| eval 30m @ gate 0.4 coverage | 0.15 |
| eval 30m @ gate 0.4 dir_acc | 0.56 |
| Notes | global split + train-only norm |

---

## 6. Live signals (optional, not the main grade)

See [SIMULATION.md](./SIMULATION.md).

```bash
docker compose up -d postgres ml_inference app
curl -s http://localhost:8001/health
curl -s http://localhost:4000/api/signals
# Dashboard http://localhost:4000
```

- **FLAT / SKIP** most of the time can be normal (gate + weak model).  
- Live serve uses **checkpoint train-only norm_stats** (same as eval) when present; health shows `norm=ckpt`.  
- This is **not** full P&L paper trading.

---

## 7. Recommended loop (no weeks of waiting)

```text
1. backfill_history.py --days 90 or 180 (optional if DB already full)
2. train_m2.py --epochs 40 (early-stops; defaults 5/30/60 primary 30)
3. Watch train vs val + gate score each epoch
4. eval_m2.py — save gate table (focus 30m PRIMARY)
5. restart ml_inference (or GCP promote), glance UI
6. If overfit / weak edge → more data / label tuning; not more blind epochs
7. Repeat; only then consider M3 or full paper P&L
```

**Prefer the cloud?** Jump to [Part 2 — GCP pipeline](#part-2--gcp-pipeline-3-steps-self-cleaning):
3 steps (`gcp_train.sh` → `gcp_status.sh` → `gcp_promote.sh`); the train VM self-cleans.

---

## 8. GPU note

- **CPU is enough** to iterate if jobs finish in reasonable time.  
- GPU only speeds training; it does not replace history or good eval.  
- Use `--device cuda` only when the container has GPU access (not typical default Mac Docker).

---

## 9. Local troubleshooting

| Problem | Fix |
|---------|-----|
| `No module named 'sqlalchemy'` | `docker compose build --no-cache ml_trainer ml_inference` |
| `Not enough samples` | Run `backfill_history.py`; ensure postgres has candles |
| `model not found` on inference | Run `train_m2.py` first; check volume `model_weights` |
| eval `n_gated=0` all gates | Model never directionally confident; more data/train or lower gates for plumbing only |
| Binance rate limits on backfill | Script retries/sleeps; reduce `--symbols` parallelism / increase sleep |
| GCP train fails / OOM | See [GCP troubleshooting → Run FAILED](#run-failed--inspect) — VM self-stops; log in bucket + `~/train_m2.log` |

---

## 10. Command cheat sheet

```bash
# Data
docker compose up -d postgres
docker compose --profile ml run --rm ml_trainer \
  python backfill_history.py --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --intervals 1m,15m,1h --days 180

# Train
docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 40 \
  --pairs BTCUSDT,ETHUSDT,SOLUSDT

# Eval signals (offline)
docker compose --profile ml run --rm ml_trainer \
  python eval_m2.py --checkpoint /models/m2_multi.pt \
  --gate 0.35,0.4,0.45,0.5,0.55,0.6

# Live paper signals
docker compose up -d postgres ml_inference app
docker compose up -d --force-recreate ml_inference   # after retrain
```

---
---

# Part 2 — GCP pipeline (3 steps, self-cleaning)

Run training on GCP with **three commands**: **train → status → promote**. The
train VM **self-deletes on success** and **self-stops on failure**, so a dropped
connection or a skipped step can never leave a VM billing. Your Mac only
orchestrates and can sleep after step 1.

> **Why it's built this way** (Mac-relay removal, git-pinned code, GCS bucket,
> cost analysis, GPU migration): [archive/GCP_TRAIN_DESIGN.md](./archive/GCP_TRAIN_DESIGN.md).

## Idea

| Machine | Purpose | When it runs |
|---------|---------|----------------|
| **fluxtrader-1** (always-on, small) | Collect book/data, UI, live inference | 24/7 |
| **fluxtrader-train** (temporary) | git checkout → restore DB snapshot → train → eval → push → **delete itself** | Only while training |

Artifacts (DB dump + checkpoint) move through a **GCS bucket**, not your Mac.
Code is a reproducible **git checkout** on the VMs. The full run **log persists in
the bucket** (`logs/<run_id>.log`) even after the VM is gone.

---

## One-time setup (Mac)

```bash
cd /path/to/trading_agent
gcloud auth login
gcloud config set project fluxtrader

cp scripts/gcp_env.example scripts/gcp_env   # edit if names/bucket/repo differ
chmod +x scripts/gcp_*.sh
```

### Create the artifact bucket (once)

Bucket **must be single-region, in the same region as the VMs** (else you pay
egress). Zone `me-central1-b` → region `me-central1`.

```bash
source scripts/gcp_env
gcloud storage buckets create "$GCS_BUCKET" \
  --location="${GCP_ZONE%-*}" --uniform-bucket-level-access
```

### Grant the train VM's service account access (once)

The train VM needs to read/write the bucket **and delete/stop itself**.

```bash
# service account the train VM runs as (default compute SA is fine)
SA=$(gcloud iam service-accounts list --format='value(email)' \
      --filter='displayName:"Compute Engine default"')

gcloud storage buckets add-iam-policy-binding "$GCS_BUCKET" \
  --member="serviceAccount:$SA" --role=roles/storage.objectAdmin
gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
  --member="serviceAccount:$SA" --role=roles/compute.instanceAdmin.v1
```

The always-on VM also needs bucket read/write (for the dump push + checkpoint
pull) — same `objectAdmin` binding for its SA (usually the same default SA).

### Code source (`GIT_REMOTE` / `GIT_REF`)

The VMs `git clone` the repo. Default is HTTPS public
(`https://github.com/VadimMalykh/trading-agent.git`). If the repo is **private**,
set `GIT_REMOTE=https://<PAT>@github.com/VadimMalykh/trading-agent.git` in
`scripts/gcp_env`. `GIT_REF` is the branch or commit to train + serve.

> **You must `git push` before training** — the VM trains the pushed commit, not
> your local working tree. This is the reproducibility guarantee (the trained
> commit SHA is stored in the checkpoint meta as `git_sha`).

---

## The pipeline (3 steps)

Run from your **Mac**, repo root.

### Step 1 — Train (one command; returns immediately)

```bash
./scripts/gcp_train.sh
# override epochs / seq-len:
./scripts/gcp_train.sh 60 128
# override pairs / horizons via env:
TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT TRAIN_HORIZONS=5,30,60 TRAIN_PRIMARY=30 \
  ./scripts/gcp_train.sh
# enable the auxiliary quantile head (p10/p50/p90 forward return, pinball loss):
TRAIN_QUANTILE_HEAD=1 ./scripts/gcp_train.sh
#   optional: TRAIN_QUANTILE_LEVELS=0.1,0.5,0.9 TRAIN_QUANTILE_LOSS_WEIGHT=0.5
# debug: keep the VM alive after the run (no auto delete/stop):
KEEP_VM=1 ./scripts/gcp_train.sh
# GPU mode (~10-20x faster, ~$0.54/hr vs ~$0.13/hr CPU):
./scripts/gcp_train.sh --gpu
# GPU + custom epochs / seq-len:
./scripts/gcp_train.sh --gpu 120 256
```

> The quantile head is **off by default**. When on, training logs a per-epoch
> `q[p10-p90]cov` calibration diagnostic and `eval_m2.py` prints a per-horizon
> calibration report; serve emits `p10/p50/p90` per horizon. Validate that band
> coverage trends toward ~0.80 and the directional metric does not regress vs a
> head-off baseline.

This one command:
1. Ensures the train VM exists (creates it with `--scopes=cloud-platform`).
2. Triggers a **fresh** dump on always-on → `gs://…/dumps/latest.sql.gz`.
3. Launches a self-contained job in remote tmux `fluxtrain` that: `git clone @GIT_REF`,
   pulls the dump, restores Postgres, runs `train_m2.py` + `eval_m2.py`, pushes the
   checkpoint + full log + status marker to the bucket, then **deletes itself**
   (success) or **stops itself** (failure).

**After it returns you can close the laptop.** Training continues on GCP.

**Train defaults:** epochs 60, seq-len 128, horizons `5,30,60`, primary 30m,
pairs `BTCUSDT,ETHUSDT,SOLUSDT`, device cpu. Checkpoint selected by directional
edge at fixed coverage (Wilson-bounded); see MODEL/eval docs.

### GPU mode

Pass `--gpu` to train on a GCE GPU instance instead of CPU. The script handles
everything: creates a GPU VM with NVIDIA driver, builds a CUDA-enabled Docker
image, and runs training with `--device cuda` + `--gpus all`.

```bash
# basic GPU training:
./scripts/gcp_train.sh --gpu

# GPU + custom params:
./scripts/gcp_train.sh --gpu 120 256

# GPU with env overrides:
TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT ./scripts/gcp_train.sh --gpu
```

**Recommended GPU instance: n1-standard-4 + 1x T4** (default)

| Instance | GPU | Cost/hr | Speed vs CPU | Notes |
|----------|-----|---------|--------------|-------|
| **n1-standard-4 + T4** | Tesla T4 (16GB) | **~$0.54** | **~10-20x** | **Best cost/speed ratio.** T4 VRAM is massive overkill for this LSTM. |
| n1-standard-8 + T4 | Tesla T4 (16GB) | ~$0.73 | ~12-25x | Diminishing returns; CPU rarely bottlenecks when GPU is active. |
| g2-standard-4 + L4 | L4 (24GB) | ~$0.70 | ~15-30x | Newer; may not be available in all zones. |
| e2-standard-4 (CPU) | — | ~$0.13 | 1x | Baseline. Fine for small jobs; GPU shines for 60+ epoch runs. |

**First GPU boot takes 8-12 min** (NVIDIA driver install + reboot + container
toolkit). Subsequent boots are normal speed. The script waits automatically.

**If switching between CPU and GPU:** the script auto-detects machine type
mismatch and recreates the VM. No manual delete needed.

**Zone:** `me-central1-b` has no GPUs. `GCP_TRAIN_ZONE` defaults to the same
zone as always-on but should be overridden (e.g. `us-central1-a`) for GPU mode.
The GPU train VM ends up in a different zone; cross-region GCS dump transfer
costs ~$0.08/GB × ~1-2GB = pennies per run.

**VM self-clean works the same way** — on GPU the self-delete trap is even more
important since idle GPU costs ~$0.35/hr.

Config in `scripts/gcp_env`:

```bash
GCP_TRAIN_MACHINE_GPU=n1-standard-4       # machine type for --gpu
GCP_TRAIN_ACCELERATOR=type=nvidia-tesla-t4,count=1  # GPU accelerator
GCP_TRAIN_ZONE=us-central1-a              # GPU zone (me-central1-b has no GPUs)
```

### Step 2 — Status (repeat anytime)

```bash
./scripts/gcp_status.sh
# a specific run id:
./scripts/gcp_status.sh 20260724T101500Z
```

Reads the bucket status marker + tails the **last 40 lines** of the log (**works
even after the VM is gone**). For the **full** log, see
[Getting the full logs](#getting-the-full-logs-any-run) below. While the VM is
alive it prints the live `tmux attach` command:

```bash
gcloud compute ssh fluxtrader-train --zone=me-central1-b --project=fluxtrader \
  -- tmux attach -t fluxtrain
# detach without stopping: Ctrl-b then d
```

Outcomes:
- **still running** → no status marker yet; poll again (hours is normal on CPU).
- **DONE** → go to step 3.
- **FAILED** → VM was **stopped** (not deleted) for debugging; the log is in the
  bucket, and you can start the VM to inspect `~/train_m2.log`.

### Getting the full logs (any run)

`gcp_status.sh` only tails the last 40 lines. Every run's **complete** log is kept
in the bucket at `gs://<bucket>/logs/<RUN_ID>.log` and **stays there after the VM
self-deletes**. Use `gcp_logs.sh`:

```bash
./scripts/gcp_logs.sh                 # FULL log of the latest run
./scripts/gcp_logs.sh --list          # list every run id + latest status
./scripts/gcp_logs.sh 20260724T144653Z    # FULL log of a specific run
./scripts/gcp_logs.sh --save          # also save latest log to $EXPORT_DIR
```

Tip: pipe to a pager or grep — e.g. `./scripts/gcp_logs.sh | less`, or
`./scripts/gcp_logs.sh | grep -E 'epoch|Eval|dir_acc'` for the training/eval
summary.

> The log is uploaded **when the job finishes** (DONE or FAILED). While a run is
> still in progress, use `gcp_status.sh` for the live `tmux attach` view instead.

Under the hood this is just:

```bash
source scripts/gcp_common.sh
gcloud storage cat "$GCS_BUCKET/logs/<RUN_ID>.log"   # full log
gcloud storage ls  "$GCS_BUCKET/logs/"               # list run ids
```

### Step 3 — Promote (when DONE)

```bash
./scripts/gcp_promote.sh
# also save a Mac backup of the checkpoint + log:
./scripts/gcp_promote.sh --local-copy
# promote even if status isn't DONE (rare):
./scripts/gcp_promote.sh --force
```

Pulls `checkpoints/latest.pt` from the bucket, installs it into the model volume
on always-on, checks out the **same `GIT_REF`** for serve code, and restarts
`ml_inference`. **No VM teardown** — the train VM already self-deleted.

Health check should show `primary=30`, `horizons=[5, 30, 60]`, `norm=ckpt`.

---

## Checklist

```text
[ ] Always-on fluxtrader-1 up (postgres + app collecting)
[ ] Bucket created (same region) + SA has objectAdmin + instanceAdmin
[ ] Code committed & pushed to GIT_REF
[ ] 1  ./scripts/gcp_train.sh        (Mac may disconnect after it returns)
[ ] 2  ./scripts/gcp_status.sh       → until DONE (VM self-cleans)
[ ]    ./scripts/gcp_logs.sh         → full log any time (--list to see all runs)
[ ] 3  ./scripts/gcp_promote.sh
[ ]    curl health on always-on — norm=ckpt, primary=30
```

**After code changes (retrain):** `git commit && git push` to `GIT_REF`, then
`./scripts/gcp_train.sh` → `gcp_status.sh` → `gcp_promote.sh`. No manual data copy
and no VM cleanup step; a fresh dump is generated each run (no candle redownload
for horizon changes — labels come from existing 1m closes). Keep always-on
collecting for book features over time.

---

## Scripts

| Script | Step |
|--------|------|
| `scripts/gcp_env.example` | Config template → `gcp_env` |
| `scripts/gcp_common.sh` | Shared helpers / config |
| `scripts/gcp_train.sh` | **1** — create VM, dump, train, eval, push, self-clean |
| `scripts/gcp_status.sh` | **2** — status + last 40 log lines from bucket; tmux attach if alive |
| `scripts/gcp_logs.sh` | — full log of any run from the bucket (`--list`, `--save`) |
| `scripts/gcp_promote.sh` | **3** — install checkpoint + serve code on always-on |

Related: [GCP_MIGRATE.md](./GCP_MIGRATE.md) — first-time Mac → always-on data move.

---

## GCP defaults

| Setting | Default |
|---------|---------|
| Always-on | `fluxtrader-1` |
| Train VM | `fluxtrader-train` (self-deletes on success) |
| Train machine | `e2-standard-4` (CPU; bump if OOM; see `GCP_TRAIN_MACHINE`) |
| Train machine (GPU) | `n1-standard-4` + `type=nvidia-tesla-t4,count=1` (see `--gpu`) |
| Train zone (GPU) | `us-central1-a` (me-central1-b has no GPUs; see `GCP_TRAIN_ZONE`) |
| Bucket | `gs://fluxtrader-train-artifacts` (single-region) |
| Git | `main` of the repo (HTTPS) |
| Epochs | 60 |
| seq-len | 128 |
| horizons | `5,30,60` (primary 30) |
| pairs | `BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT` |
| Device | cpu (`--gpu` for cuda) |

Change via `scripts/gcp_env`.

---

## GCP troubleshooting

### Run FAILED — inspect

`gcp_status.sh` shows `FAILED`. The VM was **stopped** (not deleted), and the full
log is in the bucket:

```bash
./scripts/gcp_logs.sh --list          # find the run id
./scripts/gcp_logs.sh <run_id>        # read the full log
# equivalently, straight from the bucket:
gcloud storage cat "$GCS_BUCKET/logs/<run_id>.log" | tail -n 120
# or start the VM and read locally:
gcloud compute instances start fluxtrader-train --zone=me-central1-b --project=fluxtrader
gcloud compute ssh fluxtrader-train --zone=me-central1-b --project=fluxtrader -- 'tail -n 120 ~/train_m2.log; free -h; sudo dmesg -T | grep -iE "oom|killed process" | tail'
```

**OOM:** set a larger `GCP_TRAIN_MACHINE` in `scripts/gcp_env`, delete the stopped
train VM, re-run `gcp_train.sh`.

### Other issues

| Problem | Fix |
|---------|-----|
| Can't find the logs (VM self-deleted) | Logs persist in the bucket. `./scripts/gcp_logs.sh` (latest) or `--list` then `./scripts/gcp_logs.sh <run_id>`. |
| `gcp_logs.sh` says "log not found" | Run still in progress (log uploads only at finish) — use `gcp_status.sh` live view; or wrong run id (`--list`). |
| `bucket … not accessible` | Create it (same region) + grant SA `objectAdmin`. See one-time setup. |
| VM can't delete itself (log shows permission error, VM stays up) | Grant SA `roles/compute.instanceAdmin.v1`; delete VM manually meanwhile. |
| `git clone` auth failed | Repo private → set `GIT_REMOTE=https://<PAT>@github.com/…` in `gcp_env`. |
| Trained old code | You forgot to `git push` to `GIT_REF` before `gcp_train.sh`. |
| Restore empty / candles=0 | Always-on postgres not up, or dump tables changed. Check `gcp_train.sh` dump step output. |
| `promote` refuses (`not DONE`) | Wait for DONE, or `--force` if you know the checkpoint is good. |
| Live UI still old model | Re-run `gcp_promote.sh`; check `/health` for `primary` / `norm`. |
| health `norm=rolling-fallback` | Old checkpoint without `norm_stats` — retrain with current code. |
| `volume … external but could not be found` | `docker volume create trading_agent_model_weights` then retry. |
| Forgot `KEEP_VM=1` VM still up | `gcloud compute instances delete fluxtrader-train --zone=me-central1-b --project=fluxtrader --quiet` |

---

## Cost

- **Always-on** small VM: pays while it exists (collection).
- **Train VM**: self-deletes on success. On failure it **stops** (disk only, ~cents).
- **Bucket**: single-region storage of a dump (~0.5–2 GB) + small checkpoints;
  VM↔bucket transfer in-region is free. Well under $1/month.

**CPU vs GPU:** CPU (`e2-standard-4`, ~$0.13/hr) is fine for quick runs. GPU
(`n1-standard-4` + T4, ~$0.54/hr) is ~10-20x faster and worth it for frequent
multi-hour retrains. The self-clean matters more on GPU — idle T4 burns ~$0.35/hr.
Use `./scripts/gcp_train.sh --gpu` to enable; everything else is automatic.

---

*Last updated: 2026-07-25*
