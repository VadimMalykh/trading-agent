# GCP training (3-step self-cleaning pipeline)

> Design rationale + migration notes: [GCP_TRAIN_PIPELINE_V2.md](./GCP_TRAIN_PIPELINE_V2.md).
> This is the **only** training pipeline (the old 5-step Mac-relay flow was removed).

## Idea

| Machine | Purpose | When it runs |
|---------|---------|----------------|
| **fluxtrader-1** (always-on, small) | Collect book/data, UI, live inference | 24/7 |
| **fluxtrader-train** (temporary) | git checkout → restore DB snapshot → train → eval → push → **delete itself** | Only while training |

Artifacts (DB dump + checkpoint) move through a **GCS bucket**, not your Mac.
Code is a reproducible **git checkout** on the VMs. The train VM **self-deletes on
success** and **self-stops on failure**, so a dropped connection or a skipped step
can never leave a VM billing. Your Mac only orchestrates and can sleep after step 1.

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
# debug: keep the VM alive after the run (no auto delete/stop):
KEEP_VM=1 ./scripts/gcp_train.sh
```

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

### Step 2 — Status (repeat anytime)

```bash
./scripts/gcp_status.sh
# a specific run id:
./scripts/gcp_status.sh 20260724T101500Z
```

Reads the bucket status marker + tails the log (**works even after the VM is
gone**). While the VM is alive it prints the live `tmux attach` command:

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
[ ] 3  ./scripts/gcp_promote.sh
[ ]    curl health on always-on — norm=ckpt, primary=30
```

---

## After code changes (retrain)

1. `git commit && git push` to `GIT_REF`.
2. `./scripts/gcp_train.sh` → `gcp_status.sh` → `gcp_promote.sh`.

No manual data copy and no VM cleanup step. The fresh dump is generated each run,
so no candle redownload is needed for horizon changes (labels come from existing
1m closes). Keep always-on collecting for book features over time.

---

## Scripts

| Script | Step |
|--------|------|
| `scripts/gcp_env.example` | Config template → `gcp_env` |
| `scripts/gcp_common.sh` | Shared helpers / config |
| `scripts/gcp_train.sh` | **1** — create VM, dump, train, eval, push, self-clean |
| `scripts/gcp_status.sh` | **2** — status + log from bucket; tmux attach if alive |
| `scripts/gcp_promote.sh` | **3** — install checkpoint + serve code on always-on |

Related:
- [TRAINING.md](./TRAINING.md) — what epochs/eval mean
- [GCP_TRAIN_PIPELINE_V2.md](./GCP_TRAIN_PIPELINE_V2.md) — design + rollout notes
- [GCP_MIGRATE.md](./GCP_MIGRATE.md) — first-time Mac → always-on data move

---

## Defaults

| Setting | Default |
|---------|---------|
| Always-on | `fluxtrader-1` |
| Train VM | `fluxtrader-train` (self-deletes on success) |
| Train machine | `e2-standard-2` (8 GB; bump to `e2-standard-4` if OOM) |
| Bucket | `gs://fluxtrader-train-artifacts` (single-region) |
| Git | `main` of the repo (HTTPS) |
| Epochs | 60 |
| seq-len | 128 |
| horizons | `5,30,60` (primary 30) |
| pairs | `BTCUSDT,ETHUSDT,SOLUSDT` |
| Device | cpu (GPU later — see V2 doc) |

Change via `scripts/gcp_env`.

---

## Troubleshooting

### Run FAILED — inspect

`gcp_status.sh` shows `FAILED`. The VM was **stopped** (not deleted), and the full
log is in the bucket:

```bash
gcloud storage cat "$GCS_BUCKET/logs/<run_id>.log" | tail -n 120
# or start the VM and read locally:
gcloud compute instances start fluxtrader-train --zone=me-central1-b --project=fluxtrader
gcloud compute ssh fluxtrader-train --zone=me-central1-b --project=fluxtrader -- 'tail -n 120 ~/train_m2.log; free -h; sudo dmesg -T | grep -iE "oom|killed process" | tail'
```

**OOM on 8 GB:** set `GCP_TRAIN_MACHINE=e2-standard-4` in `scripts/gcp_env`,
delete the stopped train VM, re-run `gcp_train.sh`.

### Other issues

| Problem | Fix |
|---------|-----|
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

### CPU vs GPU

Train on **8 GB CPU** by default (lazy windows). GPU (T4) is ~5–20× faster for the
LSTM loop and worth it for frequent multi-hour retrains; the self-clean matters
more there (idle GPU is expensive). GPU wiring (driver + toolkit + compose GPU +
`--device cuda`) is a separate task — see the V2 doc's GPU section.

*Last updated: 2026-07-24*
</content>
