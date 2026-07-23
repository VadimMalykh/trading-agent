# GCP training pipeline — V2 design notes (remove Mac relay, reproducible code, 3 steps)

Status: **IMPLEMENTED.** The 3-step scripts (`gcp_train.sh` / `gcp_status.sh` /
`gcp_promote.sh`) replace the old 5-step Mac-relay flow, which has been removed.
This doc records the *why* and the design; the *how-to* lives in
[GCP_TRAIN_EPHEMERAL.md](./GCP_TRAIN_EPHEMERAL.md).

The sections below describe the old 5-step flow for context and the reasoning
behind each V2 decision.

**Two big wins over the current 5-step flow:**
1. The Mac stops relaying bulk data (dump + checkpoint move via a GCS bucket);
   code becomes a reproducible `git` checkout.
2. Because artifacts are durable in the bucket the moment they're produced, the
   ordering constraints that forced 5 steps disappear. The pipeline collapses to
   **3 steps**, and the train VM becomes **self-cleaning** — it deletes itself
   when training finishes (or stops itself on failure), so a lost connection or a
   forgotten manual step can never leave a VM billing (critical once on GPU).

See **§2b** for the collapsed 3-step flow.

---

## 1. What's wrong with the current flow

Two of the three large artifacts pass through the **Mac purely as a relay**, and
code is shipped from the **Mac working tree** (not git), which hurts speed and
reproducibility.

| Artifact | Current path | Problem |
|----------|--------------|---------|
| DB dump `fluxtrader_train.sql.gz` | always-on → **Mac** (step 1) → train VM (step 3) | Largest + growing file crosses home internet **twice**; Mac must be online |
| Code `ml/` + compose | **Mac checkout** → train VM (step 3); **Mac** → always-on (step 5) | Trains/serves whatever is on the Mac (incl. uncommitted edits); not reproducible; needs `sudo rm -rf ml` + `__pycache__` cleanup |
| Checkpoint `m2_multi.pt` | train VM → **Mac** (step 5) → always-on (step 5) | Mac relay; no checkpoint history/versioning |

`gcloud compute scp` cannot copy host→host, which is *why* the Mac became the
relay. A **GCS bucket** removes that constraint.

---

## 2. Target design (V2)

Decisions taken:
- **Code → VMs via `git pull` of a pinned commit/branch** (reproducible; record SHA in checkpoint meta).
- **Large artifacts (dump + checkpoint) exchanged via a single-region GCS bucket** (no Mac bandwidth, resumable, free VM↔bucket transfer in-region, checkpoint history).

```
                 ┌─────────────────────────── git (GitHub) ───────────────────────────┐
                 │ pinned commit/branch                                                │
                 ▼                                                                      ▼
   always-on (fluxtrader-1)                                                   train VM (fluxtrader-train)
        │  pg_dump → gzip                                                          │  git clone/pull @SHA
        │  gsutil cp dump  ─────────►  gs://<bucket>/dumps/…  ◄──────── gsutil cp  │  restore DB → train → eval
        │                                                                          │  gsutil cp checkpoint ─┐
        │  gsutil cp checkpoint ◄──── gs://<bucket>/checkpoints/…  ◄───────────────┘                        │
        │  install into model volume, restart ml_inference                                                 │
        └──────────────────────────────────────────────────────────────────────────────────────────────────┘
   Mac: orchestrates (runs gcloud/gsutil commands, triggers steps). Moves NO bulk data.
```

The **Mac stays the orchestrator** (runs the scripts, holds `gcp_env`), but no
longer carries the dump or checkpoint bytes.

---

## 2b. Collapsed 3-step flow + self-cleaning VM

### Why 5 steps existed — and why they no longer need to

The 5 steps encoded two safety orderings that only mattered because the **Mac**
held the artifacts:

- **1 (dump) before 2 (create VM):** guarantee data is safe on the Mac before
  paying for a VM. → With a bucket, the dump is durable independent of any VM, so
  there's nothing to protect by ordering. Dump can happen *inside* the run.
- **5 = copy results, *then* delete VM:** don't lose the checkpoint. → With a
  bucket, the VM pushes the checkpoint to durable storage the instant training
  ends, so the VM no longer needs to survive until a manual step.

Removing the Mac as the store of record dissolves both orderings. The pipeline
collapses to **3 commands**:

| New step | Script | Does | Replaces |
|----------|--------|------|----------|
| **1. Train** | `gcp_train.sh` | Create train VM, then the VM runs one self-contained job in tmux: fresh dump (via always-on→bucket), `git clone @GIT_REF`, restore DB, `train_m2.py`, `eval_m2.py`, push **checkpoint + full log + status marker** to bucket, then **self-terminate** (see policy below). Returns immediately. | old 1 + 2 + 3 |
| **2. Status** | `gcp_status.sh` | Read `status/<run>.json` + tail `logs/<run>.log` from the bucket. If VM still alive, offer `tmux attach`. Works even after the VM is gone. | old 4 |
| **3. Promote** | `gcp_promote.sh` | Pull `checkpoints/latest.pt` from bucket → install on always-on model volume → `git checkout @GIT_REF` on always-on → restart `ml_inference` → health check. **No VM teardown needed — the train VM already deleted itself.** | old 5 (minus teardown) |

### Self-cleaning VM — the core change

The train job's final act is to remove its own compute. On the VM:

```bash
finish() {  # runs on EXIT of the train job, success OR failure
  status="$1"                       # DONE | FAILED
  gcloud storage cp "$LOG" "$GCS_BUCKET/logs/$RUN_ID.log" || true
  echo "{\"status\":\"$status\",\"git_sha\":\"$GIT_SHA\",\"run\":\"$RUN_ID\",\"ended\":\"$(date -u +%FT%TZ)\"}" \
    | gcloud storage cp - "$GCS_BUCKET/status/$RUN_ID.json" || true
  gcloud storage cp - "$GCS_BUCKET/status/latest.json" < <(gcloud storage cat "$GCS_BUCKET/status/$RUN_ID.json") || true

  SELF=$(curl -s -H 'Metadata-Flavor: Google' \
    'http://metadata.google.internal/computeMetadata/v1/instance/name')
  ZONE=$(basename "$(curl -s -H 'Metadata-Flavor: Google' \
    'http://metadata.google.internal/computeMetadata/v1/instance/zone')")

  if [[ "${KEEP_VM:-0}" == "1" ]]; then
    exit 0
  fi
  if [[ "$status" == "DONE" ]]; then
    gcloud compute instances delete "$SELF" --zone="$ZONE" --quiet     # success → delete
  else
    gcloud compute instances stop   "$SELF" --zone="$ZONE" --quiet     # failure → STOP (keep for debug)
  fi
}
trap 'code=$?; finish $([[ $code -eq 0 ]] && echo DONE || echo FAILED)' EXIT
```

Because this is a `trap … EXIT`, it fires whether training succeeds, crashes,
OOMs, or the SSH/Mac connection drops. **A lost connection can never leave a VM
running.** The VM needs its service account to have
`roles/compute.instanceAdmin.v1` (or at least `compute.instances.delete` +
`.stop`) on itself — grant at project or instance level.

### Policy decisions (chosen)

- **On failure:** upload log + `FAILED` marker, then **STOP** the VM (not delete).
  No compute billing while stopped; disk/state preserved so you can start it and
  inspect. You delete it manually when done. (`--keep-vm` skips even the stop.)
- **On success:** upload log + `DONE` marker + checkpoint, then **DELETE** the VM.
- **Dump freshness:** every run generates a **fresh** dump from always-on at job
  start (always-on `pg_dump → gzip → bucket`, then VM pulls it). Always trains on
  current data; still zero Mac bandwidth; still one command.

### tmux / log access preserved

- **During the run:** `gcp_status.sh` detects the live VM and can
  `gcloud compute ssh … -- tmux attach -t fluxtrain` (unchanged experience).
- **After the run (VM gone):** the **full log is in the bucket**
  (`logs/<run>.log`), and `status/<run>.json` records DONE/FAILED + git SHA. So
  you never lose the ability to see what happened, even though the VM is deleted.

### Failure-mode comparison

| Scenario | Current 5-step | V2 3-step self-cleaning |
|----------|----------------|--------------------------|
| Mac loses internet mid-training | VM keeps running; you must reconnect + run step 5 or it bills forever | VM finishes, pushes checkpoint+log, self-deletes. Nothing to do |
| You forget the final step | Train VM idles (billing) until noticed | No final teardown step exists; VM already gone |
| Training crashes / OOM | tmux `[exited]`, VM left running | Log+FAILED in bucket, VM **stopped** (no billing), ready to inspect |
| Want to watch live | `tmux attach` (step 4) | `gcp_status.sh` → `tmux attach` (same) |
| Review after completion | log on Mac only if step 5 ran | log always in bucket |

---

## 3. Cost of the GCS bucket — negligible

Single-region Standard bucket **in the same region as the VMs** (`me-central1`):

| Component | Rate | Realistic usage | Cost |
|-----------|------|-----------------|------|
| Storage | ~$0.020–0.023 / GB / month | dump 0.5–2 GB + a handful of checkpoints (each `m2_multi.pt` ~1–5 MB); keep ~5 GB | **~$0.10/mo** |
| **VM ↔ bucket transfer (same region)** | **$0.00** | all dump + checkpoint moves | **$0.00** |
| Class-A/B operations | ~$0.005 / 1,000 ops | dozens per run | **~$0.00** |
| Egress to Mac (optional backup) | ~$0.12 / GB | only if you pull a copy | pennies |

**Total: well under $1/month, likely a few cents.**

> **Hard rule:** bucket **region must equal the VM region**. A multi-region or
> cross-region bucket introduces egress charges. Use a single-region bucket.

Lifecycle rule (optional, recommended): auto-delete objects under `dumps/` after
e.g. 14 days so old dumps don't accumulate.

---

## 4. Exact changes per file

### `scripts/gcp_env.example` / `gcp_common.sh`
Add config with defaults:
```bash
: "${GCS_BUCKET:=gs://fluxtrader-train-artifacts}"   # single-region, VM region
: "${GIT_REMOTE:=https://github.com/<you>/trading_agent.git}"
: "${GIT_REF:=main}"                                  # branch or commit SHA to train
```
Add a small helper in `gcp_common.sh`:
```bash
gsutil_cp() { gcloud storage cp "$@"; }   # or `gsutil cp`
```

### One-time setup (documented, run once)
```bash
gcloud storage buckets create "$GCS_BUCKET" \
  --location=me-central1 --uniform-bucket-level-access
# grant both VMs' service accounts objectAdmin on the bucket
gcloud storage buckets add-iam-policy-binding "$GCS_BUCKET" \
  --member="serviceAccount:<always-on-sa>" --role=roles/storage.objectAdmin
gcloud storage buckets add-iam-policy-binding "$GCS_BUCKET" \
  --member="serviceAccount:<train-vm-sa>" --role=roles/storage.objectAdmin
```
Ensure both VMs are created with cloud-platform (or storage) scope. The default
Compute SA usually works once the IAM binding above is set.

For the **self-cleaning** train VM, also grant its service account permission to
delete/stop itself:
```bash
# project-level is simplest; instance-level is tighter
gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
  --member="serviceAccount:<train-vm-sa>" --role=roles/compute.instanceAdmin.v1
```

### Script map: 5 → 3

| Old | New | Fate |
|-----|-----|------|
| `gcp_1_dump.sh` | folded into `gcp_train.sh` | dump now happens inside the run (fresh each time) |
| `gcp_2_create_train_vm.sh` | folded into `gcp_train.sh` | create VM as part of the one command |
| `gcp_3_start_train.sh` | **`gcp_train.sh`** | main job (dump+git+restore+train+eval+push+self-clean) |
| `gcp_4_status.sh` | **`gcp_status.sh`** | reads bucket status/log; tmux attach if VM alive |
| `gcp_5_finish.sh` | **`gcp_promote.sh`** | promote from bucket + git (no teardown; VM self-deleted) |

### `gcp_train.sh` (new — one command)
Orchestrates from the Mac, returns immediately:
1. Ensure train VM exists (create with `--scopes=cloud-platform`, git + docker in
   startup script — reuse current `gcp_2` startup script).
2. Trigger a **fresh dump** on always-on → bucket:
   ```bash
   gssh "$GCP_ALWAYS_ON" "cd \$HOME/$REMOTE_REPO_NAME && \
     docker compose exec -T postgres bash -c 'pg_dump -U fluxtrader -d fluxtrader \
       --format=plain --no-owner --no-acl <TFLAGS>' | gzip > /tmp/dump.sql.gz && \
     gcloud storage cp /tmp/dump.sql.gz $GCS_BUCKET/dumps/$RUN_ID.sql.gz && \
     gcloud storage cp $GCS_BUCKET/dumps/$RUN_ID.sql.gz $GCS_BUCKET/dumps/latest.sql.gz"
   ```
3. Write the self-contained job to the VM and launch it in tmux `fluxtrain`.
   The job body:
   ```bash
   RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)
   LOG=$HOME/train_m2.log; : > "$LOG"; exec > >(tee -a "$LOG") 2>&1
   trap 'code=$?; finish $([[ $code -eq 0 ]] && echo DONE || echo FAILED)' EXIT   # see §2b

   rm -rf $HOME/trading_agent
   git clone --branch "$GIT_REF" "$GIT_REMOTE" $HOME/trading_agent
   GIT_SHA=$(git -C $HOME/trading_agent rev-parse HEAD)
   cd $HOME/trading_agent

   gcloud storage cp "$GCS_BUCKET/dumps/latest.sql.gz" \
     $HOME/fluxtrader-train-export/fluxtrader_train.sql.gz
   #  … restore DB (same as current gcp_3 remote body) …

   FLUX_GIT_SHA=$GIT_SHA docker compose --profile ml run --rm \
     -e HORIZONS_MINUTES=$HORIZONS -e PRIMARY_HORIZON=$PRIMARY -e SEQ_LEN=$SEQ_LEN \
     ml_trainer python train_m2.py --device $TRAIN_DEVICE --epochs $EPOCHS \
       --seq-len $SEQ_LEN --horizons $HORIZONS --primary $PRIMARY $PAIRS_FLAG
   docker compose --profile ml run --rm … python eval_m2.py --checkpoint /models/m2_multi.pt …

   docker run --rm -v trading_agent_model_weights:/models -v $HOME:/out alpine \
     sh -c 'cp /models/m2_multi.pt /out/m2_multi.pt'
   CKPT_KEY="checkpoints/m2_multi_${RUN_ID}_${GIT_SHA:0:8}.pt"
   gcloud storage cp $HOME/m2_multi.pt "$GCS_BUCKET/$CKPT_KEY"
   gcloud storage cp "$GCS_BUCKET/$CKPT_KEY" "$GCS_BUCKET/checkpoints/latest.pt"
   # trap → finish DONE → uploads log+status, deletes VM
   ```
   (Optionally read `FLUX_GIT_SHA` in `train_m2.py` and store it in checkpoint
   meta for full provenance.)

### `gcp_status.sh` (new — replaces step 4)
```bash
gcloud storage cat "$GCS_BUCKET/status/latest.json" 2>/dev/null || echo "no status yet (still running?)"
gcloud storage cat "$GCS_BUCKET/logs/$RUN_ID.log" 2>/dev/null | tail -n 40   # after finish
# if VM alive, live view:
gcloud compute instances describe "$GCP_TRAIN_INSTANCE" … && \
  echo "attach: gcloud compute ssh $GCP_TRAIN_INSTANCE -- tmux attach -t fluxtrain"
```
Interpretation: `status.status == DONE` → run promote; `FAILED` → VM is stopped,
start it and read `~/train_m2.log` to debug; no status yet → still running.

### `gcp_promote.sh` (new — replaces step 5, no teardown)
```bash
# guard: only promote a DONE run
[[ "$(gcloud storage cat $GCS_BUCKET/status/latest.json | jq -r .status)" == "DONE" ]] || exit 1
gssh "$GCP_ALWAYS_ON" "set -e
  cd \$HOME/$REMOTE_REPO_NAME
  git fetch --all && git checkout '$GIT_REF' && git pull --ff-only   # same code as trained
  gcloud storage cp '$GCS_BUCKET/checkpoints/latest.pt' /tmp/m2_multi.pt
  docker run --rm -v trading_agent_model_weights:/models -v /tmp:/in:ro alpine \
    sh -c 'cp /in/m2_multi.pt /models/m2_multi.pt'
  docker compose up -d --force-recreate ml_inference
  curl -sS http://127.0.0.1:8001/health"
```
No `sudo rm -rf ml` / `__pycache__` scrub (git owns the tree). **No VM teardown**
— the train VM already deleted itself on success.

Optional `--local-copy` flag: also pull `checkpoints/latest.pt` +
`logs/<run>.log` to `EXPORT_DIR` for a personal backup (pennies of egress).

---

## 5. Net effect

| | Current (5 steps) | V2 (3 steps) |
|--|-------------------|--------------|
| Manual steps | 5 | **3** (train / status / promote) |
| Dump transfers over Mac uplink | 2× (growing file) | **0** |
| Checkpoint transfers over Mac | 2× | **0** (optional 1× backup) |
| Code provenance | Mac working tree (mutable) | **pinned git SHA**, recorded in checkpoint |
| Works while Mac asleep during transfers | No | **Yes** |
| VM left billing if final step skipped / net drops | **Yes** (idle until noticed) | **No** — VM self-deletes on success, self-stops on failure |
| Extra infra | — | one single-region GCS bucket (~$0.10/mo) + self-delete IAM |
| step-5 `sudo rm -rf ml` / pycache dance | needed | **gone** |

**Trade-off accepted:** you must `git commit && push` before training (no more
training a dirty local tree). This is the intended reproducibility win. If you
want to keep a fast dirty-tree loop for experiments, add a `--from-mac` flag to
`gcp_train.sh` that scp's the Mac `ml/` instead of `git clone` (self-clean still
applies).

---

## 6. GPU migration (later) — why V2 helps

GPU VMs are billed at a high $/hour, so idle time waiting on a slow Mac uplink is
the expensive failure mode. With V2 the GPU VM: boots → `git clone @SHA` → `gcloud
storage cp` the dump from the in-region bucket (near line-rate, free) → trains →
pushes checkpoint to bucket → **self-deletes**. Nothing waits on the Mac, and the
self-delete trap means a dropped connection can never leave a costly GPU idle.

GPU-specific work still required (separate task):
- Create train VM with a GPU (`--accelerator=type=nvidia-tesla-t4,count=1` +
  `--maintenance-policy=TERMINATE`) and install the NVIDIA driver + container
  toolkit in the startup script.
- Add a compose GPU path (`--gpus all` / `deploy.resources.reservations.devices`)
  and run `train_m2.py --device cuda`. The image is already CUDA-enabled PyTorch
  (`+cu130`), so mostly it's host driver + toolkit + compose GPU wiring.
- Set `GCP_TRAIN_MACHINE` to a GPU-capable type; keep `SEL_COVERAGE`/eval flow
  unchanged.

---

## 7. Suggested rollout order

Incremental, each step independently safe (keep old scripts until V2 verified):

1. Create the single-region bucket + IAM (storage objectAdmin for both SAs;
   `compute.instanceAdmin.v1` for the train SA so it can self-delete). One-time.
2. **Artifacts to bucket, still 5 scripts:** dump→bucket in `gcp_1`, dump←bucket
   in `gcp_3`, checkpoint→bucket in `gcp_3`, promote-from-bucket in `gcp_5`.
   Biggest, safest win; no ordering/self-clean change yet.
3. **Code to git:** add `GIT_REF`/`GIT_REMOTE`; `git clone` in `gcp_3`, `git pull`
   in `gcp_5`. Verify a full reproducible run.
4. **Self-cleaning VM:** add the `trap … EXIT → finish()` (delete on DONE, stop on
   FAILED) to the train job. Test the failure path (force an error) → confirm VM
   stops and log+FAILED land in the bucket.
5. **Collapse to 3 scripts:** introduce `gcp_train.sh` (folds 1+2+3, fresh dump
   inside run), `gcp_status.sh` (bucket status/log + tmux attach), `gcp_promote.sh`
   (folds old 5 minus teardown). Retire `gcp_1/2/3/4/5`.
6. Add optional `--local-copy` / `--from-mac` flags for backups / dirty-tree runs.
7. (Later) GPU startup script (driver + toolkit) + compose GPU profile +
   `--device cuda`.

*Last updated: 2026-07-24*
</content>
</invoke>
