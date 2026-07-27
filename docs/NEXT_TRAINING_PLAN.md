# Next Training Plan (M2 → upgrade run, then M3 prep)

Status doc so work survives session loss. Captures decisions from the planning
session and the exact steps/commands to execute.

## TL;DR

- Training is **compute-bound, never memory-bound** (feature RAM ~48 MiB via lazy
  windowing in `ml/train/data/dataset.py:501`). So the answer to "downsize RAM or
  use it for speed?" is: **neither** — spend on vCPU.
- Baseline run (3 pairs, 180d) is **DONE** — see "Baseline reference". It has a
  modest but real edge at high confidence; serve gate was mis-tuned (raised to 0.58).
- Next run: **6 pairs + e2-standard-4 + gate 0.58**, prepared on branch
  `train-upgrade-e2std4-5pairs`. Merge to `main` then launch (pipeline trains from
  `GIT_REF=main`; reuses one VM name + `latest.*` bucket keys, so no parallel runs).
- Model-head experiment (quantile head) + presence-mask features come **later, as
  their own runs**.

> **Current status (updated 2026-07-27) — read this first.** Presence masks,
> quantile head, 3-class weighting fix, and calibration-aware selection are all
> **implemented + committed on `main`**. See "Microstructure readiness roadmap"
> and "A/B results log" directly below for where things stand and what to do next.

---

## Microstructure readiness roadmap (2026-07-27)

**Why this section exists:** the model's edge is still **candle-driven**. The
order-book / trade-flow / OI features (11 of ~19) are zero-filled for ~95% of the
180-day training window because the live collector only started recently. The
real ceiling on signal quality is this data scarcity, not architecture.

**Current book/trade/OI collection state (from always-on Postgres, 2026-07-27):**

| Pair | book history |
|------|--------------|
| BTC / ETH / SOL | ~9 days |
| DOGE / WLD / HYPE | ~6 days |
| ZEC | ~2 days |
| 1000PEPE | ~40 min |

Collection grows ~1 day/day (no historical backfill exists for book/trades/OI —
only candles + funding can be backfilled).

**Why not train on it yet:** at ~9d vs 180d candles, the "present" region is a
sliver of each training window → zero-fill dominates, and per-pair z-score norm
is unstable on near-constant features. A book-driven edge cannot be learned yet.

**Readiness thresholds (rough):**
- **~30 days** continuous book history → enough to *test* a book edge in training
  (validate on ~1 week of dense-book bars, train on the rest).
- **~60–90 days** → comfortable for a real **microstructure-rich run** where the
  present region dominates windows and norm is stable.
- At current rate that's **~7–11 weeks out** (from 2026-07-27).

**What to do while waiting (in order):**
1. **Run the feature-signal audit** (`ml/train/audit_microstructure.py`) — decides
   *now* whether the book edge even exists, before waiting weeks. Read-only, no
   training. **Run it on the always-on VM** (that DB has the real ~9-day book data):
   ```sh
   # on always-on: fluxtrader-1
   docker compose --profile ml run --rm ml_trainer python audit_microstructure.py
   ```
   Decision rule (printed by the script): strongest book-feature |Spearman| >~0.03
   with `wilson_lb(sign_acc) > 0.51` on a pair with enough live rows ⇒ collecting
   more is worth it; all-noise ⇒ keep collecting, don't over-invest. Writes
   `output/microstructure_audit.json`. **Caveat: 2–9 days is a SMELL TEST only** —
   a slow-drifting feature (e.g. `oi`) can show spurious correlation on a trending
   window; treat positives as "worth more collection", never as final.
   - Local run 2026-07-27 (few-day window) already showed BTC 60m `oi`
     (rho≈−0.13, lb≈0.57) and `spread_bps` (rho≈+0.11, lb≈0.56) — a *preliminary*
     book signal. Re-run on always-on for the meaningful read.
   - **Deep dive (added 2026-07-27):** the audit now also runs a sub-window
     stability test (`--thirds`, default 3) and a volatility control (`--vol-buckets`,
     default 5; disable with `--no-deep`). Per feature it prints a verdict:
     - `STABLE/UNSTABLE`: same-sign Spearman across all sub-windows? (UNSTABLE ⇒
       regime/trend artifact)
     - `DIRECTIONAL/VOL-PROXY`: does the sign edge persist across `|fwd|` buckets
       after controlling for volatility? (bucketed test drives the verdict)
     - **Decision:** `STABLE+DIRECTIONAL` ⇒ genuine directional alpha ⇒ **escalate**
       to a dense-window ablation training run (book features on vs off) — do NOT
       wait for 60d to start validating. `STABLE+VOL-PROXY` ⇒ route the feature to
       the quantile/risk head (band width), not direction. `UNSTABLE` ⇒ keep
       collecting, re-audit at ~30d.
   - **Full-audit read (always-on, 2026-07-27):** `spread_bps` was the standout —
     positive, monotone, and strengthening with horizon across ALL pairs (60m ρ:
     BTC +0.10, SOL +0.13, DOGE +0.18, HYPE +0.20; LB up to ~0.56). The deep-dive
     smoke on the local window flagged `spread_bps` as **STABLE+DIRECTIONAL on
     every pair/horizon tested** (dir_buckets 5/5 on BTC 60m; negative vol_corr, so
     not merely a volatility proxy). Depth/imbalance book features were weak
     (|ρ|<0.05). `oi`/`funding` were strong-but-sign-inconsistent across pairs →
     treat as risk features, not directional, pending confirmation.
     → **Re-run the deep-dive audit on always-on** (real ~9-day, 13k-row window)
       to confirm on the larger sample, then act on the STABLE+DIRECTIONAL roll-up.
2. **Keep the collector running** toward the 60–90d target.
3. Presence masks (done) are the enabling plumbing — the model already tolerates
   missing microstructure and flags present-vs-missing per row.

**Then:** microstructure-rich training run at ≥60d → compare vs the candle-only
baseline → only then reassess **RL (M3)**.

---

## A/B results log (primary 30m, fixed-cov top-5% dir_acc @ selected epoch)

| Run | Change | dir_acc@5% | wilson_lb | sel_score | notes |
|-----|--------|-----------:|----------:|----------:|-------|
| Baseline (16-dim) | 3 majors → 6 pairs, 180d | 0.565 | 0.555 | 0.555 | pre-masks; **served? no** |
| Masks v1 (19-dim, old 3-class weights) | presence masks | 0.559 | 0.545 | 0.545 | ~wash; 3-class "down" collapse |
| **Run A** (masks + 3-class fix) | sqrt-inv-freq + clip + label-smooth | 0.554 | 0.544 | 0.544 | **PROMOTED / currently served** |
| **Run B** (+ quantile head @ w=0.5) | pinball aux head | 0.540 | 0.530 | 0.532 | regressed dir (~−0.014); band-cov unstable (0.63–0.81), saved epoch cov=0.68 → **not promoted** |

**Interpretation:** directional ceiling ~0.55 @ 5% coverage, still candle-driven.
Masks did not help *yet* (expected — dead until microstructure accumulates) but
did not break trading. The 3-class fix removed the "never predicts down" argmax
collapse without touching the directional path. The quantile head at weight 0.5
stole encoder capacity (dented direction) and selection saved a poorly-calibrated
epoch → fixed via the two changes below.

**Changes made after Run B (committed on `main`):**
- `QUANTILE_LOSS_WEIGHT` default **0.5 → 0.2** (lighter aux head).
- **Calibration-aware checkpoint selection**: when the quantile head is on, the
  selection score is multiplied by `1 - CAL_PENALTY_WEIGHT·min(1,|band_cov−target|/CAL_TOL)`
  (defaults 0.5 / band-width=0.80 / 0.10), so the saved & early-stop epoch is
  directionally good **and** calibrated. No effect when the head is off.

**Microstructure follow-up (gated on the deep-dive verdict):**
- If `spread_bps` (etc.) confirms **STABLE+DIRECTIONAL** on the always-on run:
  **dense-window ablation training run** — train+validate ONLY on the live-book
  window (has_book==1, ~13k×N bars) with book features ON vs OFF; if book features
  add held-out directional edge, the collection wait is justified and we can start
  using book data sooner than 60d. (This run is not yet built — bring back as its
  own plan when the verdict is in.)

**Next runs, in order:**
1. **Quantile re-run** with the two fixes: `TRAIN_QUANTILE_HEAD=1 ./scripts/gcp_train.sh`
   (weight now defaults to 0.2). Promote **only if**: 30m top-5% dir_acc within
   ~0.01 of Run A (0.554) **AND** band[p10-p90] coverage ≈ 0.80 at the *saved*
   epoch (check the eval "Quantile calibration" line + the `cal_pen`/`sel` epoch
   log). Otherwise keep Run A served.
2. **Microstructure-rich run** once book history ≥ ~60d (see roadmap above).
3. **Reassess RL (M3)** only after the microstructure run.

**Serving state:** Run A is the model currently promoted to the personal UI (not
production). Do not promote Run B. Promote a future run only against the criteria
in step 1.

## Baseline reference (FINISHED — run 20260723T222840Z, git 2b208de)

- Pairs: BTCUSDT, ETHUSDT, SOLUSDT (3), 180 days, seq_len 128, primary 30m.
- Samples: 788,705 (train 630,964 / val 157,741). Val 2026-06-17 → 2026-07-23.
- **Best = epoch 13** (`sel_score=0.5546 dir_acc=0.569 lb=0.555 n_dir=4822`).
  Early-stopped at epoch 18 (no improve for 5 epochs). Clean run, no overfit.
- Final eval per horizon, fixed-coverage top-5% (comparable metric):

  | Horizon | ungated 3-class | top-5% dir_acc | top-5% wilson_lb |
  |---------|----------------:|---------------:|-----------------:|
  | 5m      | 0.527 | 0.568 | 0.554 |
  | 30m (primary) | 0.556 | 0.569 | 0.555 |
  | **60m** | 0.571 | **0.585** | **0.571** |

- **60m is the strongest horizon** on every confidence bucket (top-2% dir_acc
  0.588 / lb 0.566). Primary is 30m → we serve the middle performer. Open item:
  consider switching primary to 60m (decide after next run's per-pair eval).
- **Flat-bias:** the 3-class heads predict "flat" for the large majority of bars
  (see confusion matrices in the log); directional edge is recovered by the aux
  dir heads, which is why dir_acc > ungated tells the real story.
- **⚠️ Serve-gate finding (actionable):** the gate sweep shows gate ≤0.50 →
  coverage 1.000 → dir_acc ~0.521 (≈coin flip). Edge only appears at gate ≥0.55
  (30m gate 0.60 → dir_acc 0.560; 60m gate 0.60 → 0.579). The old serve gate 0.40
  traded ~everything at no edge. **→ raised `ML_GATE_THRESHOLD` 0.40 → 0.58.**
  Caveat: confidence scale drifts between models; re-check the gate sweep each run
  and re-tune. (Only `ML_GATE_THRESHOLD` changed; `CKPT_GATE_THRESHOLD` and
  `CONFIDENCE_THRESHOLD` left alone — checkpoint selection uses fixed-coverage
  `SEL_COVERAGE=0.05`, not the gate.)
- **Caveat:** trained on 180d candles but only ~7d of real microstructure, so the
  edge is essentially candle-driven (see "Data audit findings"). The real ceiling is
  likely microstructure data scarcity, not architecture → the microstructure-rich
  run remains the highest-leverage future step.

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

## Part 2 — Baseline captured (DONE)

Baseline run finished and is recorded above ("Baseline reference"). Artifacts:
- log:        `gs://fluxtrader-train-artifacts/logs/20260723T222840Z.log`
- checkpoint: `gs://fluxtrader-train-artifacts/checkpoints/latest.pt`
  (= `checkpoints/m2_multi_20260723T222840Z_2b208de3.pt`)
- status:     `{"status":"DONE","git_sha":"2b208de...","run":"20260723T222840Z"}`

For future runs, re-capture the same way:
```sh
./scripts/gcp_status.sh
gcloud storage cat gs://fluxtrader-train-artifacts/logs/<RUN_ID>.log
```

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
