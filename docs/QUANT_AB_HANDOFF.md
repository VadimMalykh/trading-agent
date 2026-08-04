# Quantile-head A/B — handoff

Context for a fresh session that will receive `quant_ab.sh` results. Read this
first, then look at the logs the user pastes / the files under `logs/quant_ab_*`.

## Why this A/B exists

We compared training runs with the quantile head ON vs OFF (logs `logs/run*`):

- `runA_gpu` / `runA_gpu_400`  — quantile_head=0 (baseline)
- `runB_gpu`                   — quantile_head=1, loss weight **0.5**, ~2.2M rows
- `runB_gpu_400_quant_loss_weight_0.2` — quantile_head=1, weight **0.2**, ~4.6M rows

Finding: the quantile head gave a **noisy, data-size-dependent** bump, not a
robust one.
- `runB_gpu` (qw=0.5, small data): primary-30m fixed-cov wilson_lb **0.552**
  (vs runA ~0.519) — but the 3-class head **collapsed** (ungated acc ~0.29,
  predicts almost only "flat").
- `runB_gpu_400` (qw=0.2, ~2x data): advantage **gone** (30m wilson_lb 0.507 ≈
  quant-off 0.520), quantile calibration drifts (60m band cov 0.56 vs 0.80).

The two quantile runs differ in BOTH weight and data size, so it was never a
clean test. `main` already defaults `QUANTILE_LOSS_WEIGHT=0.2` (see
`ml/train/config.py`) and already has calibration-penalty checkpoint selection
for quantile runs. This A/B is the controlled test the old logs lacked.

## The A/B (what the user is running)

`./scripts/quant_ab.sh --gpu 60 128` launches **3 arms sequentially** on the
single self-deleting GPU VM, against the SAME git ref / epochs / seq-len:

1. `quant_off`  — `--quantile-head 0`                     (baseline)
2. `quant_w0.2` — `--quantile-head 1 --quantile-weight 0.2` (current main default)
3. `quant_w0.5` — `--quantile-head 1 --quantile-weight 0.5` (old setting)

Logs land in `logs/quant_ab_<ts>/<arm>_<run_id>.log` (+ `<arm>_launch.out`).

Caveat: each arm pulls a fresh DB dump, so arms don't share a byte-identical
snapshot. Metrics used for the decision are coverage-normalized, so back-to-back
runs are adequate. (For a byte-frozen snapshot you'd pin one dump — not done by
default.)

## How to read the results (decision criteria)

Primary metric = **primary-30m fixed-coverage directional edge**, specifically
`wilson_lb` at cov 0.05 and 0.10 (stable across models; the logs literally say
"comparable across models"). Also check 60m.

Quick extraction from a set of arm logs:
```
grep -nE 'PRIMARY|cov0.05|cov0.10|Quantile calibration|Book-era|Walk-forward' logs/quant_ab_*/*.log
```

Decide qw as follows:
- If **quant_off ≈ quant_w0.2 ≈ quant_w0.5** on 30m/60m wilson_lb → quantile head
  gives no robust edge → **keep it OFF by default** (status quo). Optionally keep
  the flag for the future RL risk context.
- If **quant_w0.2 clearly beats quant_off** on wilson_lb AND its **quantile band
  coverage** is near target (0.80 for p10–p90) AND the **3-class head did NOT
  collapse** (ungated acc ~0.45+, not ~0.29) → consider enabling qw=0.2 by
  default.
- `quant_w0.5` winning on edge but collapsing 3-class / bad calibration is the
  known failure mode — do NOT ship it; it's included only to reconfirm.
- Cross-check the **Walk-forward** table (edge stable across the 4 time windows?)
  and the **Book-era split** (if the edge lives only in the "book" era, it's a
  calendar-time confound, not learned microstructure — treat any edge skeptically).

To enable a winner: set `TRAIN_QUANTILE_HEAD` / `TRAIN_QUANTILE_LOSS_WEIGHT` env
(or the `--quantile-head/--quantile-weight` flags) as the new default, or change
`QUANTILE_HEAD` default in `ml/train/config.py`.

## Code changes already on `main` (uncommitted working tree at handoff time)

Ported the **model-agnostic eval harness** from the (now-deleted)
`model-experiments` branch; left the mean-head / regression-first / cost-gated
serve / calibration-module experiments behind (they underperformed — mean head
IC ~0, negative P&L; see `logs/model_2_*` which were deleted).

- `ml/train/eval_m2.py` — NEW eval sections (reporting only, model-agnostic):
  - serial per-pair **P&L sim** (`simulate_pnl`): net_ret, win, profit factor,
    annualized daily Sharpe (√365), max drawdown — wired into the gate-sweep table.
  - **walk_forward_edge**: fixed-cov edge across `WF_WINDOWS` (=4) disjoint time
    windows, with per-window `frac_book`.
  - **book_era_edge_split**: fixed-cov 0.05 edge split book vs pre-book
    (calendar-confound visibility).
  - momentum baseline (`momentum_gate_logits`) + buy-and-hold baseline.
  - directional-head reliability bins + Brier (`calibration_report`) on primary.
  - No new deps (scipy NOT used — mean-head Spearman report was intentionally not
    ported).
- `ml/train/config.py` — cost constants (reporting only, do NOT affect
  train/serve): `FEE_RATE_BPS=4`, `SLIPPAGE_BPS=3`, `ROUND_TRIP_COST` (~14bps),
  `WF_WINDOWS=4`.
- `ml/train/data/dataset.py`:
  - `PairSeries` gained raw `close` + `book_present` (for baselines / book split).
  - **Book-window off-by-one fix**: validity window is now `[t-seq_len, t)`
    (matches the slice the model sees `feats[t-seq_len:t]`); was `(t-seq_len, t]`.
    NOTE: this slightly shifts the valid-sample set, so eval numbers move vs the
    older `logs/run*` — expected, not a regression.
- `scripts/gcp_train.sh` — arg parser rewritten (`while/case`): keeps `--gpu` +
  positional epochs/seq_len, adds `--ref|--branch`, `--quantile-head`,
  `--quantile-weight`, and now **errors on unknown flags** (previously a typo like
  `--gpuu` was silently misread as `epochs`).
- `scripts/quant_ab.sh` — NEW. Sequential 3-arm launcher; poller is
  **run-id-aware** (polls `status/<run_id>.json`, not `latest.json`, so a stale
  marker can't confuse it) with a 15-min "no marker → launch stalled" safety valve.

Verification done: all touched + dependent files `py_compile` clean in the
`ml_trainer` container; `eval_m2` imports with all helpers; `simulate_pnl` /
`book_era_edge_split` / `walk_forward_edge` smoke-tested on synthetic tensors;
both shell scripts pass `bash -n`.

These changes are NOT committed yet (per user workflow: commit only when asked).

## Infra incident during first launch (resolved)

The user's first `quant_ab.sh` launch hung at the **dump-upload** step: the
always-on VM `fluxtrader-1` (me-central1-b) was wedged — `gcloud storage cp` of
the 186MB dump hung and never persisted; SSH to the VM then started failing.
Root cause was VM-level, not the scripts. Recovery performed:
- `gcloud compute instances reset fluxtrader-1` → VM healthy again (uploads
  115 MiB/s, postgres Healthy with ~5.1M candles).
- Its docker stack didn't fully auto-start after reboot; ran
  `docker compose up -d postgres app` on it.
- Reconciled the stale `status/latest.json` RUNNING marker (dead run
  `20260803T155523Z`) to DONE.

If a future launch hangs at "fresh dump ... → gs://.../dumps/<id>.sql.gz" with no
progress and the object never appears in the bucket, suspect the same wedged-VM
condition; `reset fluxtrader-1` then re-run.

## Unrelated dirty files (NOT part of this work)

Working tree also has pre-existing uncommitted edits in
`apps/fluxtrader/**` (binance client/websocket, collector), `mix.exs`,
`docker-compose.yml`. These are unrelated collector work — do not attribute them
to the quant A/B / eval-harness task.
