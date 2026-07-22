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

---

## The only pipeline (5 steps)

Run from your **Mac**, in the repo root, **in order**.

### Step 1 — Dump database from always-on

```bash
./scripts/gcp_1_dump.sh
```

Saves `~/fluxtrader-train-export/fluxtrader.dump` on your Mac.

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
# majors only (less RAM):
TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT ./scripts/gcp_3_start_train.sh 40 64
```

This uploads the dump + code, restores Postgres on the train VM, and starts:

`train_m2.py` + `eval_m2.py`

inside remote tmux session **`fluxtrain`**.

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

### Step 5 — Install model on always-on and delete train VM

```bash
./scripts/gcp_5_finish.sh
# keep train VM for debugging:
./scripts/gcp_5_finish.sh --keep-vm
```

This:

1. Downloads `m2_multi.pt` to your Mac (`~/fluxtrader-train-export/`)  
2. Installs it on always-on Docker volume  
3. Restarts `ml_inference` if it is running  
4. Deletes `fluxtrader-train` (unless `--keep-vm`)

---

## Checklist

```text
[ ] Always-on fluxtrader-1 is up (postgres + app collecting)
[ ] 1  ./scripts/gcp_1_dump.sh
[ ] 2  ./scripts/gcp_2_create_train_vm.sh
[ ] 3  ./scripts/gcp_3_start_train.sh
[ ]    Mac may disconnect
[ ] 4  ./scripts/gcp_4_status.sh   → until DONE
[ ] 5  ./scripts/gcp_5_finish.sh
[ ]    Optional: curl health/signals on always-on
```

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
| `scripts/gcp_5_finish.sh` | Promote checkpoint + delete train VM |

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
| Device | cpu |
| Local export dir | `~/fluxtrader-train-export` |

Change via `scripts/gcp_env`.

---

## Troubleshooting

| Problem | What to do |
|---------|------------|
| Step 1: `cd ... No such file` | Always-on repo must be `~/trading_agent`. Update scripts if path differs (`REMOTE_REPO_NAME`). |
| Step 2: Docker not ready | Wait and re-run step 2; first boot installs packages. |
| Step 3: OOM / train dies | Use `TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT` and/or `e2-standard-2`; check `gcp_4_status.sh` log tail. |
| Step 4 never DONE | `gcp_4_status.sh` → read log; or `tmux attach -t fluxtrain` on train VM. |
| Step 5: missing checkpoint | Training did not finish; do not delete VM until DONE. |
| Live UI still old model | On always-on: `docker compose restart ml_inference` |
| Forgot to delete train VM | `./scripts/gcp_5_finish.sh` or delete instance in GCP Console (stops billing). |

---

## Cost reminder

- **Always-on** small VM: pays while it exists (collection).  
- **Train VM**: pays only until step 5 deletes it — do not leave it running for days unused.

---

*Last updated: 2026-07-22*
