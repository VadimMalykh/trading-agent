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

- **Next run pairs: BTC, ETH, SOL, DOGE, WLD (5).** Hold HYPE until its 180d data
  quality is verified. Set via `TRAIN_PAIRS` (`scripts/gcp_common.sh:28`) /
  `WHITELIST_PAIRS` (`ml/train/config.py:36`). Ensure new pairs are in the
  always-on DB and in the dump (`DUMP_TABLES` covers all tables,
  `scripts/gcp_common.sh:44`).
- **Keep 180d for now.** Do NOT extend to 360d until auditing older-data feature
  completeness — if orderbook/trade/funding collectors weren't running >180d ago,
  `ml/train/data/features.py:54-56,69-72` zero-fills half the 16-dim vector,
  degrading quality.
- **Add per-pair evaluation.** Check whether `eval_m2.py` breaks metrics out by
  symbol; if not, add it. Essential to detect whether pooling DOGE/WLD (higher-vol,
  thinner-book) degrades the majors' edge through the shared encoder. If it does →
  consider separate majors/alts models or weighting.
- Sequencing: Run 1 = 5 pairs / 180d / per-pair eval / e2-standard-4. Run 2 (if
  audit passes) = extend majors to 360d. Never change data AND architecture in the
  same run (can't attribute the change).

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
3. **Then:** launch Run 1 (infra + 5 pairs + per-pair eval), compare to baseline.
4. **Later:** Run 2 (360d if audit passes), then Part 5 (quantile head).

## How to stop the current run early (if ever needed)

Delete the instance directly — kills job + removes billing (boot disk) in one step:

```sh
gcloud compute instances delete fluxtrader-train --zone=me-central1-b --project=fluxtrader
```

Do NOT just kill tmux: a non-zero exit triggers `finish FAILED` which only STOPs
the VM (`scripts/gcp_train.sh:178-179`), leaving the boot disk billing.
