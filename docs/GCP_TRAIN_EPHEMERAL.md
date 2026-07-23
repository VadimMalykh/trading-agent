# GCP training (reliable multi-step pipeline)

## Idea

| Machine | Purpose | When it runs |
|---------|---------|----------------|
| **fluxtrader-1** (always-on, small) | Collect book/data, UI, optional live inference | 24/7 |
| **fluxtrader-train** (temporary, more RAM) | Restore DB snapshot → train → eval | Only while training, then delete |

Training runs **inside tmux on the train VM**. Your Mac can sleep or disconnect after step 3.

You do **not** need tmux on the Mac.

---

## One-time setup (Mac)

```bash
cd /path/to/trading_agent

# gcloud must work
gcloud auth login
gcloud config set project fluxtrader

cp scripts/gcp_env.example scripts/gcp_env
# edit scripts/gcp_env only if instance/zone names differ

chmod +x scripts/gcp_*.sh
```

If you already have `scripts/gcp_env`, merge new keys from `gcp_env.example`  
(`TRAIN_HORIZONS`, `TRAIN_PRIMARY`, `TRAIN_PAIRS`).

---

## The only pipeline (5 steps)

Run from your **Mac**, in the repo root, **in order**.

### Step 1 — Dump database from always-on

```bash
./scripts/gcp_1_dump.sh
```

Saves `~/fluxtrader-train-export/fluxtrader_train.sql.gz` on your Mac  
(plain SQL of app tables only — avoids Timescale restore crashes).

### Step 2 — Create temporary train VM

```bash
./scripts/gcp_2_create_train_vm.sh
```

Creates/starts `fluxtrader-train` (default **e2-standard-2**, 8 GB RAM) and installs Docker + tmux.

First boot can take a few minutes.

### Step 3 — Start training (returns immediately)

```bash
./scripts/gcp_3_start_train.sh
# or:
./scripts/gcp_3_start_train.sh 40 64
# override pairs / horizons via env (see gcp_env):
TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT TRAIN_HORIZONS=5,30,60 TRAIN_PRIMARY=30 \
  ./scripts/gcp_3_start_train.sh 40 64
```

This uploads the dump + **current** `ml/` + `docker-compose.yml`, restores Postgres on the train VM, and starts:

`train_m2.py` + `eval_m2.py`

inside remote tmux session **`fluxtrain`**.

**Train defaults (Phase 1+2):**

| Flag | Default |
|------|---------|
| horizons | `5,30,60` |
| primary | `30` |
| seq-len | `64` |
| pairs | `BTCUSDT,ETHUSDT,SOLUSDT` |
| checkpoint | gated dir_acc @ 0.40 + early stop on val loss |
| feature norm | train-only per-pair (stored in `.pt`; serve must match) |

**After this command finishes, you can close the laptop.** Training continues on GCP.

### Step 4 — Check status (repeat anytime)

```bash
./scripts/gcp_4_status.sh
```

- `STILL RUNNING` → wait (hours is normal on CPU)  
- `DONE` → go to step 5  

Optional live view (SSH):

```bash
gcloud compute ssh fluxtrader-train --zone=me-central1-b --project=fluxtrader \
  -- tmux attach -t fluxtrain
# detach without stopping: Ctrl-b then d
```

In the log, look for lines like:

```text
gate@0.40 cov=… n=… dir_acc=… score=…
Early stop at epoch …
--- Horizon 30m (PRIMARY) ---
```

### Step 5 — Install model + serve code on always-on and delete train VM

```bash
./scripts/gcp_5_finish.sh
# keep train VM for debugging:
./scripts/gcp_5_finish.sh --keep-vm
```

This:

1. Downloads `m2_multi.pt` (+ log) to your Mac (`~/fluxtrader-train-export/`)  
2. Syncs **`ml/` + `docker-compose.yml`** to always-on (required so `serve.py` uses checkpoint `norm_stats`)  
3. Installs checkpoint on always-on Docker volume  
4. Recreates/restarts `ml_inference`  
5. Deletes `fluxtrader-train` (unless `--keep-vm`)

Health check should show something like `primary=30`, `horizons=[5, 30, 60]`, `norm=ckpt`.

---

## Checklist

```text
[ ] Always-on fluxtrader-1 is up (postgres + app collecting)
[ ] Mac repo has latest train/serve code (git pull / this branch)
[ ] scripts/gcp_env has TRAIN_HORIZONS / TRAIN_PRIMARY / TRAIN_PAIRS (or use defaults)
[ ] 1  ./scripts/gcp_1_dump.sh
[ ] 2  ./scripts/gcp_2_create_train_vm.sh
[ ] 3  ./scripts/gcp_3_start_train.sh
[ ]    Mac may disconnect
[ ] 4  ./scripts/gcp_4_status.sh   → until DONE
[ ] 5  ./scripts/gcp_5_finish.sh
[ ]    curl health on always-on — norm=ckpt, primary=30
```

---

## After code changes (retrain)

You **must** re-run the full pipeline (1→5). Step 3 uploads Mac `ml/`; step 5 deploys serve code.

Do **not** only copy an old `m2_multi.pt` onto always-on without updating `ml/train/serve.py` — new checkpoints need train-only normalization from meta.

No extra candle redownload is required for the 5/30/60 horizon change (labels come from existing 1m closes). Keep always-on collecting for book features over time.

---

## Scripts (only these)

| Script | Step |
|--------|------|
| `scripts/gcp_env.example` | Config template → `gcp_env` |
| `scripts/gcp_common.sh` | Shared helpers |
| `scripts/gcp_1_dump.sh` | Dump always-on DB |
| `scripts/gcp_2_create_train_vm.sh` | Create train VM |
| `scripts/gcp_3_start_train.sh` | Start train in remote tmux |
| `scripts/gcp_4_status.sh` | Check progress |
| `scripts/gcp_5_finish.sh` | Promote checkpoint + serve code + delete train VM |

Related (not part of this train loop):

- `docs/TRAINING.md` — what epochs/backfill/eval mean  
- `docs/SIMULATION.md` — live signals UI  
- `docs/GCP_MIGRATE.md` — first-time Mac → always-on data move  

---

## Defaults

| Setting | Default |
|---------|---------|
| Always-on | `fluxtrader-1` |
| Train VM | `fluxtrader-train` |
| Train machine | `e2-standard-2` (8 GB) |
| Epochs | 40 |
| seq-len | 64 |
| horizons | `5,30,60` |
| primary | 30 |
| pairs | `BTCUSDT,ETHUSDT,SOLUSDT` |
| Device | cpu |
| Local export dir | `~/fluxtrader-train-export` |

Change via `scripts/gcp_env`.

---

## Troubleshooting

| Problem | What to do |
|---------|------------|
| Step 1: `cd ... No such file` | Always-on repo must be `~/trading_agent`. Update scripts if path differs (`REMOTE_REPO_NAME`). |
| Step 2: Docker not ready | Wait and re-run step 2; first boot installs packages. |
| Step 3: OOM / train dies | Use majors-only `TRAIN_PAIRS` and/or larger machine; check `gcp_4_status.sh` log tail. |
| `pg_restore` / empty candles / no orderbook | Old bug with `--clean`. Re-run **step 3** with latest scripts (fresh volume restore + verify counts before train). |
| Step 4 never DONE | `gcp_4_status.sh` → read log; or `tmux attach -t fluxtrain` on train VM. |
| Step 5: missing checkpoint | Training did not finish; do not delete VM until DONE. |
| Live UI still old model / wrong horizons | Re-run step 5 (syncs `ml/` + restarts inference). Check `/health` for `primary` / `norm`. |
| health `norm=rolling-fallback` | Old serve code or old checkpoint without `norm_stats` — retrain + finish with latest scripts. |
| Forgot to delete train VM | `./scripts/gcp_5_finish.sh` or delete instance in GCP Console (stops billing). |

---

## Cost reminder

- **Always-on** small VM: pays while it exists (collection).  
- **Train VM**: pays only until step 5 deletes it — do not leave it running for days unused.

---

*Last updated: 2026-07-23*
