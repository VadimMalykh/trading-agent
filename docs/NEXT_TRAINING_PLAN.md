# Training plan — what is true, what to run next

**Last updated: 2026-08-18** (after the N-wave: N1 walk-forward, N2 GBT-at-4h, N3
cost-aware selection).

This document is the project's session-to-session memory. It contains only what is
**currently true and actionable**. The session-by-session narrative from 2026-07-23 →
2026-08-18 — every superseded plan, every rejected hypothesis, every raw results table —
lives in **`docs/archive/TRAINING_HISTORY.md`**. Go there for "why was X decided"; do not
act on anything in it.

**How to use this doc:**
- §0 — standing rules. Read before touching anything. Every rule cost us a real run.
- §1 — where we are, in numbers. The current reference points.
- §2 — **the run queue.** This is the "what do I type" section.
- §3 — what to bring back so a fresh session can decide.
- §4 — results ledger (one row per run, with a validity flag).
- §5 — levers that are closed, and why. Don't re-propose these.
- §6 — open code tasks.
- §7 — mechanics (scripts, promote, fetch).

---

## §0 — STANDING RULES

### 0.1 Data lives on the always-on VM, never the local DB

**The source of truth for ALL data is the always-on GCP VM `fluxtrader-1`.** Training,
eval, backfill and data-collection all run against the collector Postgres there. The
local `docker compose exec postgres` is a **throwaway dev DB** — it does NOT mirror the
VM's candle/book history, its whitelist, or the backfilled pairs. **Never reason about
pair readiness / history / row counts from the local DB.**

```sh
./scripts/gcp_data_collection_stats.sh          # the full report (slow, ~15min+)
```

Ad-hoc queries are much faster than the full report. Quote-escaping through
`gcloud … --command` breaks SQL string literals (`"1m"` becomes an identifier); pipe a
script over stdin instead:

```sh
cat > /tmp/q.sh <<'EOF'
cd ~/trading_agent && docker compose exec -T postgres psql -U fluxtrader -d fluxtrader <<'SQL'
SELECT interval, symbol, min(open_time)::date, max(open_time)::date, count(*)
FROM candles WHERE interval IN ('1m','5m','15m') GROUP BY 1,2 ORDER BY 1,2;
SQL
EOF
gcloud compute ssh --zone me-central1-b fluxtrader-1 --project fluxtrader -- bash -s < /tmp/q.sh
```

The `candles` time column is **`open_time`**, not `ts`.

### 0.2 One change per run

Never change data AND architecture/selection/labels in the same run — the result becomes
un-attributable. This rule has voided E3a, E2b(v1) and E3-tb.

### 0.3 🔴 Rank arms on the epoch *distribution*, never on the max

**This is the newest rule and it retroactively weakens most of §4.** The headline
`cov05 wilson_lb` printed by every run is `max over epochs`. Measured directly from the
two runs that share a training configuration (F4 and N3 differ only in which epoch gets
checkpointed, which cannot affect the training trajectory):

| run | epochs | mean LB | sd | max LB | max, in sd above mean |
|---|---:|---:|---:|---:|---:|
| F4 | 18 | 0.5058 | 0.0162 | 0.5310 (ep 8) | +1.56 |
| N3 | 11 | 0.4987 | 0.0155 | 0.5230 (ep 1) | +1.57 |

Paired per-epoch difference F4 − N3 across epochs 1–11: mean **+0.010**, sd **0.018**.
Two runs of the *same* config differ by more than most of the effects we have been
chasing. Consequences, all binding:

- **A cov05-LB difference below ~0.04 between two single runs is not evidence.** The GBT
  at 0.469 vs the LSTM at ~0.53 clears that bar. Nothing else in §4 does.
- **The honest point estimate of the current model's cov05 edge is ≈ 0.505 ± 0.016**, not
  0.531. `max over epochs` on a flat, noisy series is an order statistic; it manufactures
  ~+0.025 of apparent edge out of nothing.
- **Report mean ± sd of the per-epoch LB series alongside the selected epoch.** With 20+
  epochs the standard error of the mean is ~0.004, which *can* resolve a 0.01 effect.
  **Every training log now ends with this summary** (C10, done) — read
  `selected - mean = ±… (… sd)` before believing any single-run improvement.

Compute it from any log with:

```sh
grep -oE 'epoch [0-9]+.*lb=[0-9.]+' logs/X.log | grep -oE 'lb=[0-9.]+' | cut -d= -f2 | \
  awk '{n++;s+=$1;q+=$1*$1;if($1>m)m=$1}END{printf "n=%d mean=%.4f sd=%.4f max=%.4f\n",n,s/n,sqrt(q/n-(s/n)^2),m}'
```

### 0.4 Verify these lines in EVERY log before trusting a run

Each line is here because its absence voided a real run.

| grep for | must say | voided |
|---|---|---|
| `=== resolved knobs:` + `knob K=V` | the env you intended | R3 |
| `Pair embedding:` | `ON dim=8`, not `off` | E3a, E3-tb |
| `Training pairs: [...]` | the intended set | F3 |
| `primary=` | matches intent | R3 |
| `Split global_time … train [..] val [..]` | **record it** — a backfill moves it | E2b comparability |
| `WARNING [norm] …` | how many columns degenerate, and which | — |
| `[norm] <pair>: max\|z\|=` | must NOT say `BROKEN SCALE` | all pre-`2e7b272` runs |
| `P&L sim: … hold=N bars` | N == horizon_minutes / bar_minutes | F4 prereq |
| `WARNING: at the SERVED gate` | absent — if present, the checkpoint never reaches the served confidence and would trade nothing | N3 (fired; correctly) |
| `Fixed-coverage P&L` | present — if missing, the run predates C2 | F4 lacks it; see O0 |
| `Early stop at epoch N` | N should not be `1 + patience` — if it is, selection peaked at epoch 1 and the run never explored | N3 |

### 0.5 Standing traps

1. Data lives on the VM, not the local DB (§0.1).
2. **Env knobs whose default ≠ the incumbent silently change the experiment.** Echo every
   knob. Prefer defaults that equal the incumbent.
3. **Silent fallbacks** (`.get(x, default)`) on horizons/intervals/primary. Make them raise.
4. **A backfill landing mid-experiment moves the train/val split.** Pin and re-record it.
5. **Additive epsilons are not floors.** (`std = sqrt(var) + 1e-6` — the 2026-08-17 P0 bug.)
6. **A knob that is only applied `if [[ -z "$OTHER" ]]` is dead** if `$OTHER` has a
   default. That is how `WF_LONG_PAIRS_ONLY` silently did nothing in F3. Fixed in C4a.
7. **A knob that exists in `config.py` but not in `FLUX_TRAIN_ENV_KEYS` cannot be set from
   the launcher at all.** `EARLY_STOP_PATIENCE` was one such knob and it is what truncated
   N3 at 11 epochs; there was also no `SEED` knob anywhere, so no run was reproducible.
   Both are fixed (C8) and are now in the allowlist. The trap itself stands: check §7's
   allowlist before assuming a knob you set actually reached the VM.
8. **A blended selection score is only "50/50" if both terms have the same dynamic range.**
   N3's nominal 50/50 blend was ~88% cost term because `net_score` swung 0.378 while
   `edge_lb` swung 0.050.

---

## §1 — WHERE WE ARE (2026-08-18)

### 1.1 The one-paragraph summary

At 4h horizon on 15m bars, the candle-only model produces a gross edge of roughly
**+4 to +6 bps per trade** at 600–900 trades over an 8-month validation window, against
**5bps maker / 14bps taker** round-trip cost. That is break-even at maker and clearly
negative at taker, and it is the same conclusion F4 reached — but the level is now known
to be softer than F4 claimed, because the headline metric is an order statistic over a
noisy flat series (§0.3). Three things changed with the N-wave. **(a) The edge is
regime-locked, and this is reproducible across architectures** — two LSTMs and a
gradient-boosted tree independently agree that two of four validation windows carry
essentially all of it (§1.2). **(b) Architecture is not dead after all**: the GBT that tied
the LSTM at 30m loses badly at 4h (§1.4), so how temporal context is represented matters at
this horizon. **(c) The feature set is six real numbers per bar** (§1.6) — twelve of
nineteen features are constant in the train window — which is the most likely reason
everything else is at the noise floor.

### 1.2 🔴 The edge is regime-locked, and three different models agree on where

`cov05 wilson_lb` on the primary 240m head, val window split into four ~2-month blocks:

| window | period | F4 (LSTM, LB-selected) | N3 (LSTM, cost-selected) | N2 (GBT) |
|---|---|---:|---:|---:|
| 1 | 2025-12-08 → 2026-02-09 | 0.484 | 0.499 | 0.492 |
| 2 | 2026-02-09 → 2026-04-13 | **0.623** | **0.621** | **0.574** |
| 3 | 2026-04-13 → 2026-06-15 | 0.454 | 0.419 | 0.415 |
| 4 | 2026-06-15 → 2026-08-17 | **0.583** | **0.613** | 0.397 |

Two LSTMs selected by *different objectives* and one LightGBM on a *completely different
feature representation* agree on windows 1, 2 and 3. The window-2/window-3 spread is
~0.20 LB — an order of magnitude larger than the 0.016 run-to-run noise of §0.3, and
therefore the only effect in this entire dataset that is unambiguously real.

The 8-month headline is the mean of a bimodal series, not a persistent edge. And the
upside is large: 0.62 at cov05 with E|r| ≈ 100bps at 4h is roughly **+24 bps gross per
trade**, ~5× maker cost. A detector that could tell window-2/4 conditions from
window-1/3 conditions *at decision time* would be worth more than any feature or
architecture change currently on the table. Nothing in the previous queue targeted this.
It is now **O1 + O4**.

### 1.3 Current reference numbers — F4 remains the baseline

Run `20260817T221811Z` · ckpt `m2_multi_20260817T221811Z_94614795.pt` · `logs/F4.log`
Config: `CANDLE_INTERVAL=15m`, seq 128 (= 32h context), `PAIR_EMBED_DIM=8`, fixed labels,
8 pairs, horizons 60/240/1440, primary 240.
Split: `train [2022-08-19 21:45 → 2025-12-08 18:00]`, `val [2025-12-08 18:00 → 2026-08-16 22:45]`,
964,627 samples (771,701 / 192,926).

| | 1h | **4h (primary)** | 24h |
|---|---:|---:|---:|
| cov05 dir_acc / Wilson-LB (selected epoch) | 0.518 / 0.507 | **0.543 / 0.531** | 0.525 / 0.513 |
| cov05 LB, mean ± sd over epochs (§0.3) | — | **0.506 ± 0.016** | — |
| gross bps/trade @ conf≥0.60 | +2.9 | **+6.2** (592 trades) | −33.2 |
| coverage @ conf≥0.60 | 0.6% | 2.6% | 11.0% |

Baselines in the same window: momentum (sign of trailing 16 bars) cov05 LB **0.457**;
buy-and-hold pooled **−8.005**. The model beats both. Both are negative.

**F4 predates C2**, so it has no `Fixed-coverage P&L` table and cannot be compared to N3
on gross-bps-at-matched-coverage — the comparison the queue actually pre-registered. Fixing
that needs no retraining, only an eval-only re-score: **O0**.

N3 (`20260818T031002Z`, `logs/N3.log`) is the same architecture at the same horizon with a
different checkpoint-selection objective. Its cov05 LB is 0.523 (mean 0.499 ± 0.016) and its
4h fixed-coverage gross is **+4.24 bps/trade** at cov 0.05 (855 trades), **+6.0** at gate
0.55 (716 trades). Indistinguishable from F4. Its checkpoint should **not** be promoted
(§1.5).

### 1.4 N2 — GBT at 4h loses badly; the architecture question is reopened

`logs/N2.log`, run `gbt-20260818T070504Z`. Valid: `CANDLE_INTERVAL=15m` reached the
container (C0 works), `hold_bars = horizon_bars(15m, 240) = 16`, primary 240, 8 pairs.

| cov | 0.01 | 0.02 | **0.05** | 0.10 | 0.20 |
|---|---:|---:|---:|---:|---:|
| GBT cov LB | 0.4835 | 0.4719 | **0.4692** | 0.4881 | 0.4874 |

Every coverage is below coin flip, and serial P&L is negative at every coverage. Against
the LSTM's ~0.51–0.53 this is a gap of 0.04–0.06 — the one comparison in the project that
clears the §0.3 noise bar. The pre-registered rule fires: **"GBT clearly worse → the fixed
LSTM's temporal modeling is now contributing → architecture is back on the table."**

Read it carefully, though. E4-GBT tied the LSTM at **30m primary on 30m bars with seq 128
(64h of context)**; N2 lost at **240m primary on 15m bars with seq 128 (32h)**. Two things
changed, so the strict claim is narrower than "recurrence beats trees": *a 114-column
static summary of a 32-hour window fails at 4h where it sufficed at 30m.* Both readings —
"temporal ordering matters more at 4h" and "the summary threw away the long-context
information" — point at **how much context the model gets and how it is represented**. The
cheap, direct test of that is a context-length sweep on the LSTM we already have (**O3**),
not an architecture swap. Do the sweep before writing a transformer.

### 1.5 N3 — cost-aware selection is closed; do not promote its checkpoint

The run is mechanically valid: all four knobs echoed (`SEL_NET_WEIGHT=0.5 SEL_COST_BPS=5
PAIR_EMBED_DIM=8 CANDLE_INTERVAL=15m`), `Cost-aware selection: net_weight=0.5 cost=5.0bps
scale=0.002`, `hold=16 bars`, and `net_sc` moved 0.505 → 0.127 across epochs, so the R1
dead-floor failure did not recur. It "finished immediately" (25 min wall clock) because the
blended score peaked at **epoch 1** and `EARLY_STOP_PATIENCE=10` fired at epoch 11 —
correct behaviour, not a crash.

Why it peaked at epoch 1, and why the lever is dead: the two score terms have mismatched
dynamic range (`edge_lb` spanned 0.050 across the run, `net_score` spanned 0.378 — so the
nominal 50/50 blend was ~88% cost term), and the cost term ranks noise (`net_per_trade` is a
mean over ~9,650 gated bars whose 4h forward returns overlap 16-fold ⇒ ~600 independent
observations ⇒ standard error ~4–6 bps against a total observed range of 19 bps). Full
derivation in the archive. Most importantly it **did not achieve its goal**: at matched
trade counts its chosen epoch is no more profitable than F4's LB-chosen epoch (F4 +6.2 vs
N3 +6.0 bps/trade at ~600–720 trades).

⚠️ **N3 overwrote `checkpoints/latest.pt`** (§7). The epoch-1 checkpoint has a compressed
confidence scale — its 1h head gates **zero** bars at the served 0.58 (the C1 warning fired,
working exactly as designed) and its 4h side split is 9,487 up / 161 down, effectively
long-only. F4 is still reachable at its named key
`checkpoints/m2_multi_20260817T221811Z_94614795.pt`. **Do not run `gcp_promote.sh` until a
run you want has been the most recent one.**

### 1.6 The model sees six real numbers per bar

`FEATURE_COLS` has 19 entries, but the `WARNING [norm] train fit[...]` block in every
recent log says **12 of 19 are CONSTANT in the train window** and are correctly zeroed.
What actually carries signal in F4 / N3 / N2:

| live | dead in the train window |
|---|---|
| `ret_1`, `hl_range`, `oc_range`, `log_vol`, `ret_std_15`, `funding` (+ `has_funding_oi` mask) | `spread_bps`, `imbalance`, `micro_mid`, `bid_ask_vol_ratio`, `depth_near_imb`, `trade_count`, `buy_sell_imb`, `trade_vol`, `oi`, `oi_chg`, `has_book`, `has_trades` |

Six signal columns — four single-bar OHLCV derivatives, one 15-bar rolling vol, and the
funding rate. No multi-timescale returns, no multi-scale volatility, no cross-pair or
market-wide context, no trend. `funding` is correctly aligned
(`FUNDING_OI_MAX_AGE_MIN=480` = 8h matches the funding interval), so it is not silently
zeroed. This is the most likely single reason every other lever sits at the noise floor,
and it is the cheapest thing on the board to fix: everything in **O4** comes from candle
data that already spans the full history for every pair.

### 1.7 Data status (verified on the VM, 2026-08-18)

**✅ The 1m/5m ragged-history problem is GONE.** A backfill has landed since the 2026-08-17
audit. Candle coverage now, per interval:

| pairs | 1m / 5m / 15m first bar | note |
|---|---|---|
| BTC, ETH, SOL, DOGE, ZEC, ADA, AVAX, LINK, XRP | **2022-08-18** | full 4 years, all three intervals |
| 1000PEPE | 2023-05-05 | listing date — unfixable, not ragged |
| WLD | 2023-07-24 | listing date |
| HYPE | 2025-05-30 | listing date |

Row counts at 5m: 420,7xx for each of the nine long pairs, and the full stats report
confirms **zero interior gaps for all 12 pairs × 1m/5m/15m/1h** (48/48 rows at
`gaps=0, missing_hours=0`). **Code task C6's "1m backfill to a common start" is therefore
DONE** and 5m-bar training is launchable now — which is what unblocks **O2**. It also makes
the 12-pair run genuinely cheap: ADA/AVAX/LINK/XRP have full 4-year history at every
interval.

Microstructure, unchanged from 2026-08-17 (re-verify before any book run):

| source | coverage |
|---|---|
| `orderbook_snapshots` | BTC/ETH/SOL **31d** (from 2026-07-17 21:13) · DOGE/HYPE/WLD ~28d · ZEC 24d · 1000PEPE ~22d · ADA/AVAX/LINK/XRP ~4d. Cadence ~1/10s, staleness <45s. |
| `orderbook_levels` (raw L2) | 8 main pairs ~14d (from 2026-08-05), 100 bid + 100 ask levels, zero integrity errors |
| `market_trades`, `open_interest` | mirror snapshots |
| `funding_rates` | 2y9mo–3y11mo — the only microstructure source with real history, and the only one that is a live feature |
| `liquidations` | **0 rows** — WS egress blocked from datacenters. Dropped from all plans. |

**60-day book milestone for BTC/ETH/SOL: ≈2026-09-15.**

---

## §2 — THE RUN QUEUE

The wave is ordered: a small code batch, then one free analysis that decides the shape of
everything after it, then two GPU runs that are launchable in parallel.

**None of the three N-wave commands should be re-launched as written.** N1's design is
retired (§5), N2 answered its question, N3's lever is closed (§1.5).

### C-batch — DONE (2026-08-18). The queue is unblocked; start at O0.

C7, C8, C9 and C10 are implemented (details in §6). What this changed for the runs below:

- `--eval-only` exists, defaults to CPU, and never writes `checkpoints/latest.pt`.
- `EARLY_STOP_PATIENCE` and `SEED` are forwarded from the launcher, so O2/O3 can control
  patience and produce multi-seed error bars.
- Every eval now writes a per-bar dump, and **every eval run uploads its artifacts** to
  `gs://…/eval/<run_id>/` (`eval_m2.json`, `eval_preds.parquet`, `history_m2.json`), which
  previously died with the VM.
- Every training log ends with the epoch-LB order-statistic summary.

### O0 — re-score F4 on today's eval code (CPU, ~25 min). Runnable now.

The N3-vs-F4 comparison the queue pre-registered ("compare gross bps/trade at matched
coverage") was unexecutable, because F4's log predates C2 and has no `Fixed-coverage P&L`
table. This costs no training.

```sh
./scripts/gcp_train.sh --eval-only checkpoints/m2_multi_20260817T221811Z_94614795.pt
./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> --save          # → logs/O0-f4-rescore.log
```

No other flags are needed. `--eval-only` implies `--cpu`, and `eval_m2.py` takes
`seq_len`, `horizons` **and `candle_interval`** from the checkpoint's own meta — which
matters here: **F4 was trained on 15m candles** while `CANDLE_INTERVAL` defaults to `1m`,
so re-scoring it under today's ambient config would otherwise have rebuilt a different bar
grid, a different val window, and a `hold_bars` 15x off, printing a complete and plausible
table of wrong numbers.

**Bring back:** `logs/O0-f4-rescore.log`, plus the path
`gs://fluxtrader-train-artifacts/eval/<run_id>/eval_preds.parquet`.

**Verify in the log:** the line `Checkpoint primary=… candles=15m`; a `Fixed-coverage P&L`
block for 240m; the gate sweep running 0.50–0.75; and a final
`Wrote …/eval_preds.parquet — N rows`.

**Delivers:** F4's gross bps/trade at cov 0.01/0.02/0.05/0.10/0.20, closing the N3
question with numbers instead of the gate-row arithmetic in §1.3 — and F4's per-bar
predictions, which O1 consumes.

### O1 — 🔴 regime analysis (local, no VM, no training). Needs O0.

**This is the highest-value item in the queue and it costs nothing but a script.** §1.2
established that two of four val windows carry essentially all the edge, reproducibly
across three models. The question is whether that is *predictable at decision time*.

Take F4's per-bar dump from O0. For each bar compute candidate regime observables from
candles that are already in the DB and available with no lookahead:

- realized vol of the pooled universe over trailing 1d / 7d / 30d
- BTC trailing return over 1d / 7d, and its sign
- cross-sectional dispersion of trailing 4h returns across the 8 pairs
- cross-pair correlation of trailing 1d returns (a single "everything moves together" scalar)
- funding level and funding sign, pooled and per pair
- the model's own mean confidence over a trailing 1d window

Then ask two things:

1. **Separation.** Do any of these separate window 2/4 bars from window 1/3 bars? Report
   AUC of each observable against the binary "bar is in a good window".
2. **Conditional lift.** Bucket val bars by each observable (quintiles), and report cov05
   LB *and* gross bps/trade per bucket. The number that matters is the top bucket's gross
   bps/trade against the 5bps maker cost.

**Verdict:**
- Some observable gives ≥0.60 AUC and its top bucket shows gross ≫ 5bps → we have both a
  feature (feed it, O4) and a gate (trade only in that regime). This becomes the whole
  next wave.
- Nothing separates → the window structure is real but not observable from what we have,
  which is itself a strong argument for the cross-pair/market-wide features in O4 and
  against any further single-pair feature work.

Bring back the AUC table and the per-quintile gross-bps table.

### O2 — 5m bars: 3× the training data (GPU, ~4–6h). Runnable now.

The visible failure in both F4 and N3 is that **training does nothing**: `loss_tr` moved
1.7318 → 1.7101 over 11 epochs, `loss_va` is flat, and the per-epoch LB series is flat
noise (§0.3). At 15m there are only 771k train samples. §1.7 just established that 5m
candles now go back to 2022-08-18 for every long pair, so this is finally launchable.

One variable vs F4: the bar interval. `seq 384` holds the context window at 32h so the
comparison stays clean (5m × 384 = 32h = 15m × 128).

```sh
CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 \
  EARLY_STOP_PATIENCE=20 SEED=1 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 384
./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> --save          # → logs/O2.log
```

If wall-clock is a problem, `--gpu 60 288` (24h context) is the cheaper fallback — but
then the context length has changed too and the run is two variables, so prefer 384.

**Verify:** `knob CANDLE_INTERVAL=5m`; `Samples:` ≈ 2.3–2.9M (vs F4's 965k); `P&L sim: …
hold=48 bars` for the 240m head; `Early stop at epoch N` with N well above 21.

**Verdict:** rank on mean ± sd of the per-epoch LB (§0.3) and on gross bps/trade at cov
0.05, both against F4/O0. `loss_tr` finally moving is the leading indicator; if it is
still flat at 3× the data, the model is not data-starved and the bottleneck is entirely
features (O4).

### O3 — context length at 15m (GPU, ~3–5h). Runnable now.

The direct, cheap test of what N2 actually showed (§1.4). One variable vs F4: `seq_len`
128 → 256, i.e. 32h → 64h of context, which is the context E4-GBT had when it tied the
LSTM at 30m.

```sh
CANDLE_INTERVAL=15m PAIR_EMBED_DIM=8 \
  EARLY_STOP_PATIENCE=20 SEED=1 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 256
./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> --save          # → logs/O3.log
```

**Verify:** `seq=256`; `Samples:` slightly below F4's 965k (longer windows lose a few
head samples per pair); split re-recorded.

**Verdict:** longer context clearly better on mean-of-epochs LB → keep extending
(seq 512, then consider a temporal CNN or small transformer, `MODEL.md` §4.4). Flat or
worse → the LSTM already has all the context it can use, N2's result is about the GBT's
summary rather than about recurrence, and architecture goes back in the closed pile.

### After this wave

Read O1 + O2 + O3 together in a **fresh session**. The second wave depends on them, but
two items are worth doing regardless:

- **O4 — cross-pair / regime features** (the old N5). Trailing 1h/4h/1d returns,
  multi-scale rolling vol, BTC-relative return and beta, cross-sectional return rank and
  dispersion. Free from candles that already span the whole history for every pair, zero
  collection lead time. Needs a `FEATURE_DIM` bump (code task **C12**) and therefore its
  own attributable run. **§1.6 (six live features) and §1.2 (regime-locked edge) both
  point here**, and O1 tells you which specific features to add. This is the single
  highest-EV feature lever.
- **O5 — L2 ladder feature audit (read-only, NO training; the old N4).**
  `orderbook_levels` has ~14d × 100 levels × 8 pairs with zero integrity errors, and the
  five book features are all *instantaneous snapshot levels* with no dynamics. Two known
  gaps, both fixable from data already on disk: (a) no order-flow imbalance, no book delta
  over the last N snapshots, no queue-depletion rate, no depth slope, no microprice drift
  — at 30m+ horizons microstructure predictive power comes mostly from OFI and its
  persistence, not from a snapshot's static imbalance; (b) `_align_with_age` keeps only
  the *last* snapshot per bar and discards ~5 of every 6, so per-bar aggregates (mean/std/
  range of imbalance within the bar, summed OFI, max spread) are free information. Run
  `audit_microstructure.py` on the candidates before spending a `FEATURE_DIM` bump. This
  now **replaces** the retired book walk-forward (§5) as the way the book question gets
  answered.
- **O6 — magnitude-weighted directional loss** (code task C3). The train-time twin of the
  idea N3 tested at selection time. Worth trying *because* the selection-time version
  failed for a reason that does not apply at train time: a per-sample loss weight uses
  every training bar rather than a 600-effective-sample validation statistic.
- **O7 — triple-barrier redo.** Blocked on C4b (barrier-aware `simulate_pnl`), wider
  barriers (target ~30–40% flat), `PAIR_EMBED_DIM=8`, and a pinned dataset.
- **O8 — 12 pairs.** Now genuinely cheap (§1.7): ADA/AVAX/LINK/XRP have full 4-year
  history at every interval. One variable, one run. Low priority, but no longer blocked.

---

## §3 — WHAT TO BRING BACK (for the next session)

Save each run's full log under `logs/` with the queue name, then open a **fresh session**
and paste the paths. Do not summarize the logs yourself — the numbers that matter are
often not the headline ones.

```sh
./scripts/gcp_logs.sh <run_id> --save          # writes logs/<run_id>.log → rename O2.log / O3.log
```

**Self-check before you hand them over** — if any of these fails, the run is void and
should be relaunched rather than analyzed:

```sh
grep -nE 'resolved knobs|knob |Pair embedding|Training pairs|primary=|Split global_time' logs/O2.log
grep -nE 'WARNING \[norm\]|max\|z\||BROKEN SCALE' logs/O2.log
grep -n  'P&L sim:' logs/O2.log            # hold must be horizon_min / bar_min
grep -n  'Early stop at epoch' logs/O2.log # must NOT be 1 + patience
grep -n  'Samples:' logs/O2.log            # O2 only: must be ~3x F4's 964,627
# the §0.3 epoch-distribution summary (do this for every run):
grep -oE 'epoch [0-9]+.*lb=[0-9.]+' logs/O2.log | grep -oE 'lb=[0-9.]+' | cut -d= -f2 | \
  awk '{n++;s+=$1;q+=$1*$1;if($1>m)m=$1}END{printf "n=%d mean=%.4f sd=%.4f max=%.4f\n",n,s/n,sqrt(q/n-(s/n)^2),m}'
```

**What the next session will read, in order:**
1. The §0.4 verification lines — is the run valid at all.
2. **The per-epoch LB mean ± sd (§0.3)** — this is the verdict metric now, not the max.
3. `Fixed-coverage P&L` → **gross bps/trade** at cov 0.01–0.20, against 5bps maker.
4. `--- Walk-forward edge on val window ---` win 1–4 → does the §1.2 regime pattern hold,
   and did anything narrow the window-2-vs-window-3 spread.
5. `Fixed-coverage directional edge` → is the ordering monotone in confidence.
6. `Side split` + `Long/short serial P&L` → one-sided?
7. `Book-era split` → is the edge a calendar confound?
8. `Momentum baseline` + `Buy-and-hold` → did it beat the trivial baselines.

---

## §4 — RESULTS LEDGER

⚠️ **Read §0.3 first.** Every `cov05 LB` below is `max over epochs` of a series with
sd ≈ 0.016. Differences under ~0.04 between single runs are not evidence. **Post-`2e7b272`
runs are a new lineage and are not comparable to anything above the line.**

| Run | What | Primary | cov05 LB | Valid? | Verdict |
|---|---|---:|---:|---|---|
| **F4** `20260817T221811Z` | 15m bars, seq 128, horizon ladder | 240m | 0.531 (mean 0.506±0.016) | ✅ **current baseline** | 4h is the horizon peak. Gross +6.2bps/trade @592 trades ≈ maker break-even. WF regime-locked: .484/.623/.454/.583. Needs O0 to get its C2 table. |
| **N3** `20260818T031002Z` | cost-aware selection, `SEL_NET_WEIGHT=0.5 SEL_COST_BPS=5` | 240m | 0.523 (mean 0.499±0.016) | ✅ valid, **lever closed** | Selected epoch 1, stopped at 11. Score blend was ~88% cost term and the cost term ranks noise. Gross +4.2bps @cov05 — no better than F4. **Do not promote**; it overwrote `latest.pt`. §1.5 |
| **N2** `gbt-20260818T070504Z` | LightGBM 114-col static summary at 15m/4h | 240m | **0.4692** | ✅ **decisive** | Below coin flip at every coverage; 0.04–0.06 worse than the LSTM, the only gap in the project that clears the §0.3 noise bar. Reopens architecture as a lever. §1.4 |
| **N1** `wf-20260818T063858Z` | book ON/OFF walk-forward, 4 long pairs, C4a floor active | 30m | — | ⚠️ **INCONCLUSIVE by its own rule** | 2 of 6 folds decidable; decidable gaps `+0.073`, `−0.122`. Book-OFF collapses to flat and cannot be scored. **Design retired**, see §5. |
| **F3** `wf-20260817T030350Z` | book ON/OFF, 8 pairs | 30m | — | ❌ superseded by N1 | Ran the wrong pair set (dead `WF_LONG_PAIRS_ONLY`), no decidability floor. |
| — | *norm fix `2e7b272` — lineage boundary* | | | | Everything below is measured through the `std=1e-6` bug unless noted. |
| E4-GBT `gbt-20260816T132201Z` | LightGBM, 114-col summary, 30m bars seq 128 (64h) | 30m | 0.5314 | ✅ (scale-invariant) | Tied the LSTM at 30m. N2 shows this does **not** carry to 4h. |
| E3-tb `20260816T023427Z` | triple-barrier labels | 30m | 0.530 | ❌ confounded | 3 variables changed; barriers mis-parameterized. Redo as O7. |
| E2b `20260813T114311Z` | pair-embed dim=8, 8 pairs | 30m | 0.566 | ❌ **retired** | Measured through the bug on a since-changed dataset. |
| E3b1 / E3b2 | pair-embed dim 4 / 16 | 30m | 0.559 / 0.554 | ❌ | Dim curve flat — and by §0.3 it was always going to be. |
| E2a′ / E2c | pair-set sweeps | 30m | 0.568 / 0.559 | ❌ | "More pairs > fewer" — conclusion may survive, evidence does not. |
| E1a / E1b | 4h / 1d primary at 1m bars | 240m / 1440m | 0.533 / 0.523 | ❌ | Rejected at the time for book-era collapse = the norm cliff. F4 supersedes. |
| R0–R6 | staleness fix, cost-sel, capacity, rebalance | 30m | 0.542–0.559 | ❌ | The "tuning ceiling" narrative; the whole 0.017 spread is under one §0.3 sd. |
| ablate `20260804T083752Z` | book ON/OFF, single dense window | 30m | ON 0.691 / OFF 0.494 | ✅ (`--require-book`) | The strong book result. Never replicated. Unconfirmed and now unfalsifiable by this design (§5). |
| E3a `20260814T144713Z` | 12 pairs | 30m | — | ❌ VOID | Log truncated + embed off. Redo as O8 — now cheap (§1.7). |

---

## §5 — CLOSED LEVERS (do not re-propose without new evidence)

| Lever | Status | Why |
|---|---|---|
| **Cost-aware checkpoint selection (`SEL_NET_WEIGHT`)** | **Closed (new, 2026-08-18)** | N3 ran it at the horizon where R5's objection no longer applies. The term is alive but ranks a statistic with ~600 effective samples and ~5bps standard error against a 19bps range, at ~88% effective weight. Chosen epoch was no more profitable than F4's. §1.5. Reopen only with a fixed range (`SEL_NET_SCALE≈0.04`) *and* a reason to believe per-epoch net/trade is estimable. |
| **The book ON/OFF walk-forward *design*** | **Retired (new, 2026-08-18)** | Three attempts, zero decidable verdicts. The book-OFF arm's modal failure (collapse to an all-flat predictor) is exactly what pushes `n_dir` under the reliability floor, so the design is least able to decide precisely when the book helps most. The book question is not closed — it moves to within-model attribution (**O5**). Do not launch `gcp_walkforward.sh` for it again. |
| Encoder capacity / layers / hidden sweeps | **REOPENED (2026-08-18)** | Was closed on "E4-GBT tied a static summary against a 128-step LSTM". N2 shows that tie does not survive the move to 4h. Reopened via **O3** (context length first), not via a capacity sweep. §1.4 |
| Full architecture swap (transformer / TCN) | **Gated behind O3** | O3 is the cheap test. Do not write a transformer before reading it. |
| Confidence calibration / temperature / focal loss | **Closed** | F4's head is *over*-confident (`[0.60,0.70)` bin mean_pred 0.636 vs empirical 0.547; N3's is 0.609 vs 0.521). Sharpening an over-confident head is the wrong direction. |
| Raising `GATE_THRESHOLD` as an experiment | **Superseded by C1+C2** | The served gate is 0.58 and eval now reports there. Derive the operating point from the fixed-coverage P&L table, not from another sweep. |
| Quantile head | **Deferred** | Regressed direction ~0.014; band coverage unstable. Revisit at M3, detached. |
| `liquidations` feed | **Dropped** | 0 rows; Binance gates WS market data from datacenter egress (verified from 3 hosts). |
| More candle *history* | **Closed** | Adds more of the pre-book regime we already fit. Note this is about *history*, not *resolution* — more samples at finer resolution (**O2**) is a different and open lever. |
| Tuning any single hyperparameter on one run | **Closed by §0.3** | The measurement cannot resolve effects below ~0.04 LB from a single run. Any such sweep is reading noise. |

---

## §6 — OPEN CODE TASKS

**C0, C1, C2, C4a are DONE** (2026-08-18, committed in `5f4046e`) and were exercised by the
N-wave: C0's `CANDLE_INTERVAL` forwarding reached the GBT container, C1's served-gate
warning fired on N3, C2's fixed-coverage P&L table printed, C4a's decidability floor
correctly marked four N1 folds undecidable. **C6 is DONE** — a backfill landed and 1m/5m
now start 2022-08-18 for all nine long pairs (§1.7).

### The C-batch — DONE 2026-08-18

- ✅ **C7 — `gcp_train.sh --eval-only <ckpt-key>`.** Takes a bare filename, a
  `checkpoints/<name>.pt` key or a full `gs://` URL; verifies it exists **before** creating
  a VM (and lists the available keys if not). Restores the DB dump as usual, skips
  `train_m2.py`, evals the named checkpoint, and **never writes `checkpoints/latest.pt`**,
  so a re-score cannot be promoted by mistake. Implies `--cpu` unless `--gpu` is passed.
  Unlike a training run it does **not** swallow an eval failure — eval is the whole job, so
  a failure stops the VM for debugging instead of reporting DONE.
  - **Bundled fix:** `eval_m2.py` now takes `candle_interval` from the checkpoint meta
    instead of ambient config, and says so in the log. This is what makes re-scoring an old
    checkpoint meaningful at all — F4 is a 15m model and the config default is 1m.
  - **Bundled fix:** `--cpu` now forces `TRAIN_DEVICE=cpu`. It previously only chose the
    machine type, so a `TRAIN_DEVICE=cuda` in `scripts/gcp_env` would have run the GPU
    docker path on a CPU VM.
- ✅ **C8 — launcher control over `EARLY_STOP_PATIENCE`, and a real `SEED`.**
  1. `EARLY_STOP_PATIENCE` is in `FLUX_TRAIN_ENV_KEYS`.
  2. `SEED` (`config.py`, default 42) seeds `random`/`numpy`/`torch`/CUDA at the top of
     `train_m2.main`, is exposed as `--seed`, is forwarded via the allowlist, and is echoed
     in the log. Sweep `SEED=1,2,3` for the §0.3 error bars.
  - **Bundled fix:** `docker-compose.yml` defaulted `EARLY_STOP_PATIENCE` to 5 while
    `config.py` said 10, so with the knob unset the CPU path ran half the patience of the
    GPU path. Now both are 10.
  - ⚠️ **Still divergent, deliberately left alone:** compose defaults `BATCH_SIZE` to 128
    vs `config.py`'s 256. Set `BATCH_SIZE` explicitly on any CPU-vs-GPU comparison.
- ✅ **C9 — `eval_m2 --dump-preds`.** Writes `OUTPUT_DIR/eval_preds.parquet` with
  `(ts, pair, horizon, side, conf, p_up, fwd_ret, y3, has_book)` for every val bar and
  every horizon. `ts` is epoch **nanoseconds** UTC; `side` is -1/+1; `y3` is 0/1/2.
  `side`/`conf` come from the same directional signal the gate uses, so re-aggregating this
  table reproduces the printed fixed-coverage rows exactly. Falls back to `eval_preds.csv.gz`
  (same columns) if the image lacks a parquet engine — `pyarrow` was added to both
  requirements files, but a reused VM image may predate it. The eval runner is now on by
  default, so **every** run produces the dump, not just eval-only ones.
- ✅ **C10 — epoch-distribution summary.** Training ends with
  `epoch LB series @cov0.05: n=… mean=… sd=… max=… selected=epoch N (lb=…)` followed by
  `selected - mean = ±… (… sd)`. Read the second line first: a gap within ~1 sd is the
  order statistic, not a result.

### Later

- ⬜ **C12 — `FEATURE_DIM` bump for cross-pair / regime features.** Required by O4. Adding
  columns changes the serving contract (`serve.py`, the checkpoint's feature list, and the
  Elixir side's expectations), so scope it as its own change and confirm the eval-time
  feature-name mapping in `dataset.py:425` still resolves.
- ⬜ **C3 — magnitude-weighted directional loss.** Weight the aux up/down CE by `|r_T|`.
  Gate behind a config flag defaulting to off. Feeds O6.
- ⬜ **C4b — barrier-aware `simulate_pnl`.** Under triple-barrier labels the model predicts
  a TP/SL outcome but `simulate_pnl` books `fwd_ret` at a fixed `hold_bars` — a policy
  mismatch. Walk forward to first TP/SL touch, else timeout. **Blocks O7.**
- ⬜ **C4a-remainder — matched-`n_dir` walk-forward comparison.** Lower priority now that
  the two-arm design is retired (§5), but the same idea is what would let O5's within-model
  attribution be scored fairly.
- ⬜ **C5 — `oi` conditioning.** `oi = log1p(open_interest)` is a *level*: near-constant in
  any short window, so ordinary drift becomes hundreds of sigma. Drop the raw level and keep
  `oi_chg`, or use a rolling-normalized version. Same question for `log_vol`. Only matters
  inside a dense-book arm, since both are currently dead in the global train window (§1.6).
- ⬜ **C11 — `torch==2.5.1+cpu` pin.** No longer resolves on the PyTorch CPU index, so
  `ml_trainer` fails a clean rebuild; `gcp_gbt.sh` works around it in the throwaway VM only.
  Fixing the pin properly changes served numerics → its own decision. (Split out of the old
  C6, whose backfill half is now done.)

---

## §7 — MECHANICS

### Launch / monitor / fetch

| Job | Launch | Status | Fetch | VM |
|---|---|---|---|---|
| Train (GPU) | `./scripts/gcp_train.sh --gpu 60 128` | `./scripts/gcp_status.sh` | `./scripts/gcp_logs.sh <run_id> --save` | `fluxtrader-train` |
| Eval only (no training) | `./scripts/gcp_train.sh --eval-only <ckpt-key>` | `./scripts/gcp_status.sh` | `./scripts/gcp_logs.sh <run_id> --save` + `gs://…/eval/<run_id>/` | `fluxtrader-train` |
| Walk-forward | `./scripts/gcp_walkforward.sh` | `--status` | `--fetch` | `fluxtrader-walkforward` |
| GBT diagnostic | `./scripts/gcp_gbt.sh` | `--status` | `--fetch` / `--log` | `fluxtrader-gbt` |
| Single-window ablate | `./scripts/gcp_ablate.sh` | — | — | own VM |
| Feature audit | `./scripts/gcp_audit.sh` | — | — | own VM |
| Data stats | `./scripts/gcp_data_collection_stats.sh` | — | — | always-on |
| Promote | `./scripts/gcp_promote.sh --local-copy` | — | — | always-on |

Each creates its own throwaway VM with its own tmux session and status marker, so **they
are safe to run concurrently**. They self-DELETE on success and self-STOP on failure.
`KEEP_VM=1` keeps the VM for debugging. Never run a training-sized job on the always-on
VM — it has 2GB and the kernel OOM-kills it silently.

⚠️ `gcp_promote.sh` only ever promotes `checkpoints/latest.pt`, and every new training run
overwrites that key. **`latest.pt` is currently N3's epoch-1 checkpoint, which must not be
promoted** (§1.5). F4 lives at `checkpoints/m2_multi_20260817T221811Z_94614795.pt`.
Promote before launching the next run, or the checkpoint you wanted becomes unreachable
via the script.

### Env knob passthrough

`scripts/gcp_train.sh` forwards only the allowlist in `FLUX_TRAIN_ENV_KEYS`:

```
SEL_NET_WEIGHT SEL_COST_BPS SEL_NET_SCALE SEL_COVERAGE
NUM_LAYERS HIDDEN_SIZE DROPOUT LR WEIGHT_DECAY BATCH_SIZE
EARLY_STOP_PATIENCE SEED
PAIR_EMBED_DIM NUM_WORKERS PREFETCH_FACTOR
CLS_WEIGHT_MODE CLS_WEIGHT_CLIP CLS_LABEL_SMOOTHING DIR_LOSS_WEIGHT
LABEL_MODE TB_TP_MULT TB_SL_MULT TB_VOL_WINDOW TB_MIN_BARRIER
CANDLE_INTERVAL NORM_DEGENERATE_STD NORM_CLIP NORM_LEGACY_BROKEN_STD
BOOK_MAX_AGE_MIN TRADES_MAX_AGE_MIN FUNDING_OI_MAX_AGE_MIN
GATE_THRESHOLD FEE_RATE_BPS SLIPPAGE_BPS MAKER_FEE_RATE_BPS MAKER_SLIPPAGE_BPS
```

`EARLY_STOP_PATIENCE` and `SEED` were added to this list by C8 (2026-08-18).

**Add every new config knob to this list when you create it** — an unforwarded knob is a
silent no-op on the GPU VM (trap §0.5.2/§0.5.7). Note `TRAIN_PRIMARY` / `TRAIN_HORIZONS` /
`TRAIN_PAIRS` are consumed on the *launcher* and forwarded as CLI flags instead.
`gcp_gbt.sh` and `gcp_walkforward.sh` have their own, narrower forwarding — check before
assuming a knob reaches them.

### Cost arithmetic (never needs a re-run)

Cost model: **taker = 14bps** round-trip (`FEE_RATE_BPS=4` + `SLIPPAGE_BPS=3`, ×2 sides);
**maker = 5bps** (`FEE_RATE_BPS=2` + `SLIPPAGE_BPS=0.5`, ×2). `net_ret` is exactly linear
in cost and trade selection is cost-independent (`eval_m2.py:143`), so:

```
net_ret(c) = net_ret(0.0014) + n_trades × (0.0014 − c)
gross_bps_per_trade = (net_ret(0.0014) + n_trades × 0.0014) / n_trades × 1e4
```

**Rank arms on measured gross bps/trade, not on a dir_acc-derived break-even.** A
break-even computed from dir_acc assumes correct and incorrect trades have the same E|r|;
they do not — the model is systematically right on smaller-than-average moves. C2's
`Fixed-coverage P&L` table prints the durable number directly.

Worth keeping in view: at 4h the only positive cells in the whole project appear at
**maker** cost. F4's best operating point is +6.2 gross bps/trade, i.e. **+1.2 net at
maker and −7.8 at taker.** Execution work that moves the fill from taker to post-only
maker is the single largest sign-flipping lever available, and it is not an ML change.

### Where things live

- Checkpoints: `gs://fluxtrader-train-artifacts/checkpoints/` (+ `latest.pt`)
- Logs: `gs://fluxtrader-train-artifacts/logs/<RUN_ID>.log`
- Walk-forward compares: `…/walkforward/<run_id>.compare.txt`
- GBT reports: `…/gbt/<run_id>.json`
- Status markers: `…/status/latest.json`

### Related docs

- `docs/archive/TRAINING_HISTORY.md` — the full session narrative, 2026-07-23 → 2026-08-18.
- `docs/DATA_COLLECTION_AUDIT.md` — what the collector captures vs silently drops.
- `docs/QUANT_AB_HANDOFF.md` — quantile-head A/B and its deferral.
- `MODEL.md` — architecture contract; §4.3 labels, §4.4 architecture options.
- `AGENTS.md` — Docker-only workflow, data-lives-on-the-VM rule.
