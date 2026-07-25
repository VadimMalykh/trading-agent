# GCP training pipeline — design notes (archived)

> **ARCHIVED — design/rationale, not a how-to.** The runbook lives in
> [../TRAINING.md → Part 2 (GCP pipeline)](../TRAINING.md#part-2--gcp-pipeline-3-steps-self-cleaning).
> This doc records *why* the pipeline is shaped the way it is (the migration from
> the old 5-step Mac-relay flow, the self-cleaning VM, cost, and GPU plans). It is
> kept for context; operational steps may drift — trust TRAINING.md for commands.

Status: **IMPLEMENTED.** The 3-step scripts (`gcp_train.sh` / `gcp_status.sh` /
`gcp_promote.sh`, plus `gcp_logs.sh`) replaced the old 5-step Mac-relay flow,
which has been removed.

**Two big wins over the old 5-step flow:**
1. The Mac stops relaying bulk data (dump + checkpoint move via a GCS bucket);
   code becomes a reproducible `git` checkout.
2. Because artifacts are durable in the bucket the moment they're produced, the
   ordering constraints that forced 5 steps disappear. The pipeline collapses to
   **3 steps**, and the train VM becomes **self-cleaning** — it deletes itself
   when training finishes (or stops itself on failure), so a lost connection or a
   forgotten manual step can never leave a VM billing (critical once on GPU).

---

## 1. What was wrong with the old 5-step flow

Two of the three large artifacts passed through the **Mac purely as a relay**, and
code was shipped from the **Mac working tree** (not git), which hurt speed and
reproducibility.

| Artifact | Old path | Problem |
|----------|----------|---------|
| DB dump `fluxtrader_train.sql.gz` | always-on → **Mac** → train VM | Largest + growing file crossed home internet **twice**; Mac had to be online |
| Code `ml/` + compose | **Mac checkout** → train VM; **Mac** → always-on | Trained/served whatever was on the Mac (incl. uncommitted edits); not reproducible; needed `sudo rm -rf ml` + `__pycache__` cleanup |
| Checkpoint `m2_multi.pt` | train VM → **Mac** → always-on | Mac relay; no checkpoint history/versioning |

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

## 3. Collapsed 3-step flow + self-cleaning VM

### Why 5 steps existed — and why they no longer need to

The 5 steps encoded two safety orderings that only mattered because the **Mac**
held the artifacts:

- **dump before create-VM:** guarantee data is safe on the Mac before paying for a
  VM. → With a bucket, the dump is durable independent of any VM, so there's
  nothing to protect by ordering. Dump can happen *inside* the run.
- **copy results, *then* delete VM:** don't lose the checkpoint. → With a bucket,
  the VM pushes the checkpoint to durable storage the instant training ends, so
  the VM no longer needs to survive until a manual step.

Removing the Mac as the store of record dissolves both orderings → **3 commands**
(`gcp_train.sh` folds old dump+create+train; `gcp_status.sh` reads bucket
status/log; `gcp_promote.sh` installs the checkpoint, no teardown).

### Self-cleaning VM — the core change

The train job's final act is to remove its own compute. On the VM:

```bash
finish() {  # runs on EXIT of the train job, success OR failure
  status="$1"                       # DONE | FAILED
  gcloud storage cp "$LOG" "$GCS_BUCKET/logs/$RUN_ID.log" || true
  # … write status/<run>.json + status/latest.json …

  SELF=$(curl -s -H 'Metadata-Flavor: Google' \
    'http://metadata.google.internal/computeMetadata/v1/instance/name')
  ZONE=$(basename "$(curl -s -H 'Metadata-Flavor: Google' \
    'http://metadata.google.internal/computeMetadata/v1/instance/zone')")

  if [[ "${KEEP_VM:-0}" == "1" ]]; then exit 0; fi
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
`.stop`) on itself.

### Policy decisions (chosen)

- **On failure:** upload log + `FAILED` marker, then **STOP** the VM (not delete).
  No compute billing while stopped; disk/state preserved so you can start it and
  inspect. (`KEEP_VM=1` skips even the stop.)
- **On success:** upload log + `DONE` marker + checkpoint, then **DELETE** the VM.
- **Dump freshness:** every run generates a **fresh** dump from always-on at job
  start. Always trains on current data; still zero Mac bandwidth; still one command.

### Log access after the VM is gone

The **full log persists in the bucket** at `logs/<run>.log`, and
`status/<run>.json` records DONE/FAILED + git SHA. Fetch it with
`./scripts/gcp_logs.sh` (latest), `--list` (all run ids), or `gcp_logs.sh <run_id>`
(specific). `gcp_status.sh` only tails 40 lines. During a live run,
`gcp_status.sh` offers `tmux attach -t fluxtrain`.

### Failure-mode comparison

| Scenario | Old 5-step | 3-step self-cleaning |
|----------|------------|-----------------------|
| Mac loses internet mid-training | VM keeps running; you must reconnect + finish or it bills forever | VM finishes, pushes checkpoint+log, self-deletes. Nothing to do |
| You forget the final step | Train VM idles (billing) until noticed | No final teardown step exists; VM already gone |
| Training crashes / OOM | tmux `[exited]`, VM left running | Log+FAILED in bucket, VM **stopped** (no billing), ready to inspect |
| Review after completion | log on Mac only if final step ran | log always in bucket (`gcp_logs.sh`) |

---

## 4. Cost of the GCS bucket — negligible

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

## 5. Net effect

| | Old (5 steps) | 3 steps |
|--|---------------|---------|
| Manual steps | 5 | **3** (train / status / promote) |
| Dump transfers over Mac uplink | 2× (growing file) | **0** |
| Checkpoint transfers over Mac | 2× | **0** (optional 1× backup) |
| Code provenance | Mac working tree (mutable) | **pinned git SHA**, recorded in checkpoint |
| Works while Mac asleep during transfers | No | **Yes** |
| VM left billing if final step skipped / net drops | **Yes** | **No** — self-deletes on success, self-stops on failure |
| Extra infra | — | one single-region GCS bucket (~$0.10/mo) + self-delete IAM |
| `sudo rm -rf ml` / pycache dance | needed | **gone** (git owns the tree) |

**Trade-off accepted:** you must `git commit && push` before training (no more
training a dirty local tree). This is the intended reproducibility win.

---

## 6. GPU migration (later) — why this design helps

GPU VMs are billed at a high $/hour, so idle time waiting on a slow Mac uplink is
the expensive failure mode. The GPU VM: boots → `git clone @SHA` → `gcloud storage
cp` the dump from the in-region bucket (near line-rate, free) → trains → pushes
checkpoint to bucket → **self-deletes**. Nothing waits on the Mac, and the
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

*Archived 2026-07-25 (superseded as a how-to by [../TRAINING.md](../TRAINING.md);
retained for design rationale). Original: `GCP_TRAIN_PIPELINE_V2.md`.*
