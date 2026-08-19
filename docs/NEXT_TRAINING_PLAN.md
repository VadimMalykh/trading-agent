# Training plan — what is true, what to run next

**Last updated: 2026-08-19** (after the O-wave: O0 F4 re-score, O2 5m bars, O3 context
length).

This document is the project's session-to-session memory. It contains only what is
**currently true and actionable**. The session-by-session narrative from 2026-07-23 →
2026-08-19 — every superseded plan, every rejected hypothesis, every raw results table —
lives in **`docs/archive/TRAINING_HISTORY.md`**. Go there for "why was X decided"; do not
act on anything in it.

### What this document is a plan *for* — read once, then stop worrying about it

Everything in this file is **milestone M2: the supervised signal model**. Its only job is
to emit, per pair and per bar, a calibrated directional probability at 1h / 4h / 24h. It
is **not the trading system and it never decides a trade.**

The trading decision belongs to **M3, a discrete policy (RL / bandit) over
flat / long / short / hold / exit**, which consumes M2's per-horizon probabilities and
confidences as *observations*. That is the design in `MODEL.md` §5.5 and `docs/PLAN.md`
§M3, and it has not changed.

Two consequences that keep coming up and are worth stating plainly:

- **"The model is barely break-even after costs" is not a project verdict.** M2 is a
  feature extractor for M3. A signal worth +6 gross bps/trade at 2% coverage is a usable
  observation for a policy that also controls *when to be in the market at all*, position
  size, and holding time — none of which M2 has any say over. The gate sweeps and
  fixed-coverage P&L tables in this doc exist to tell us whether the signal carries
  information, not to define a strategy.
- **Conversely, M2 must not grow policy features.** Anything about sizing, exits, risk
  budget, or execution style is M3's, and building it here would make the policy's job
  harder, not easier. When a lever in this doc starts to look like a trading rule
  (cost-aware checkpoint selection was one — §5), that is a signal it belongs downstream.

The one place M2's economics genuinely matter is the **taker/maker line** (§7): a signal
whose gross edge is under round-trip cost at *every* coverage gives M3 nothing to work
with. §1.3 is the first run where that is no longer the case.

**How to use this doc:** if you are picking this up cold, the fastest path is
§1.1 (one paragraph on where we are) → §2's P0 (what to launch) → §0.3 and §0.6 (why the
numbers are read the way they are).

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

**The mean-of-epochs series to date** (C10 prints this at the end of every training log):

| run | n | mean LB | sd | max | selected − mean |
|---|---:|---:|---:|---:|---|
| **O2** (5m, seq 384) | 34 | **0.5248** | 0.0148 | 0.5565 | +2.15 sd |
| F4 (15m, seq 128) | 18 | 0.5058 | 0.0162 | 0.5310 | +1.56 sd |
| N3 (15m, cost-sel) | 11 | 0.4987 | 0.0155 | 0.5230 | +1.57 sd |
| O3 (15m, seq 256) | 24 | 0.4925 | 0.0227 | 0.5313 | +1.71 sd |

With n in the 20s the standard error of the mean is ~0.003–0.005, so the O2−F4 gap of
**+0.019** is roughly 4 SEM and is the first effect in this project other than the GBT gap
that the measurement can actually resolve. Note it does **not** rescue any of the max-based
numbers: every run's selected epoch still sits 1.5–2.2 sd above its own mean, so every
`Fixed-coverage P&L` table in this document is measured on an optimistically selected
epoch. **Seed replication is the only way to bank a result** — hence P0 in §2.

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
| `Fixed-coverage P&L` | present — if missing, the run predates C2 | resolved by O0 for F4 |
| `Fixed-coverage P&L` ordering | gross bps/trade should **decrease** with coverage; a sign flip between cov 0.01 and 0.05 means confidence is not ranking economics and the head is not usable | O2's 1440m head (fails); O2's 240m head (passes) |
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
9. **Training runs are serial, and a concurrent launch is destructive, not just futile.**
   `gcp_train.sh` adopts a single fixed instance name and will delete/recreate it on a
   machine-type mismatch, so launching a second run can kill the one already in flight
   (§7). Plan queues in summed wall clock.

### 0.6 🔴 When two arms have different bar counts, rank on `dir_acc`, not Wilson-LB

New with the O-wave. Wilson-LB narrows with `n_dir`, and `n_dir` scales with the number of
val *bars*, not with the number of independent observations. O2 (5m bars) has 579,157 val
bars against F4's 193,019 — 3× the rows for the same 8 months of calendar time and the same
4h forward returns, so its 4h labels overlap 48-fold where F4's overlap 16-fold. Both runs
carry ~12,000 independent 4h observations; only one of them gets a tighter confidence
interval for it.

Concretely at cov 0.05: F4 `dir_acc 0.542 → LB 0.531` (gap 0.011); O2 `dir_acc 0.563 →
LB 0.557` (gap 0.006). About a quarter of the apparent LB improvement is just the interval
tightening. **The honest comparison is `dir_acc` 0.563 vs 0.542, i.e. +0.021** — still a
real gain, but quote that number, not the LB delta, whenever the bar interval differs
between arms. Within one bar interval, LB remains fine.

---

## §1 — WHERE WE ARE (2026-08-19)

### 1.1 The one-paragraph summary

**Bar resolution was a real lever, and it is the first one that has been.** Moving from
15m to 5m bars at a fixed 32h context window (O2) tripled the training set to 2.9M samples
and produced the first improvement in this project that the measurement can resolve:
mean-of-epochs cov05 LB **0.5248 ± 0.0148** against F4's **0.5058 ± 0.0162** (§0.3), and
`dir_acc` at cov 0.05 of **0.563 vs 0.542** (§0.6 — quote this one, the intervals differ).
More importantly it moved the economics: O2's top-2%-confidence slice is **+22 to +24
gross bps/trade**, which is **positive after taker cost** (+8 to +10 net bps/trade over
469–708 trades) where F4's best cell was +6.5 gross and only ever positive at maker. The
serial-P&L sim agrees — at gate 0.62 O2 books **+0.99 net_ret at full 14bps taker cost
over 548 trades, Sharpe 1.41**, the first positive serial P&L in the project's history.
Three other things changed. **(a) Longer context is dead** — O3 (seq 128 → 256 at 15m) is
*worse* on every measure, so the LSTM already uses all the window it can and architecture
goes back in the closed pile (§1.4). **(b) The "regime-locked edge" story is weaker than
it looked** — O2 disagrees with the three 15m models on two of four windows, and the
apparent three-model agreement was partly a shared-bar-grid artifact (§1.2). **(c) The
"flat `loss_tr` ⇒ not data-starved" diagnostic is falsified** — O2's loss was just as flat
as F4's and it still improved (§1.5). Everything now rests on **one seed**, and the
headline P&L is measured on an epoch selected 2.15 sd above its own mean, so the next
run is a replicate, not a new idea.

### 1.2 The regime structure is real but softer, and partly a model artifact

`cov05 wilson_lb` on the primary 240m head, val window split into four ~2-month blocks:

| window | period | F4 (15m) | N3 (15m) | N2 (GBT, 15m) | **O2 (5m)** |
|---|---|---:|---:|---:|---:|
| 1 | 2025-12 → 2026-02 | 0.486 | 0.499 | 0.492 | **0.573** |
| 2 | 2026-02 → 2026-04 | **0.617** | **0.621** | **0.574** | 0.535 |
| 3 | 2026-04 → 2026-06 | 0.457 | 0.419 | 0.415 | 0.500 |
| 4 | 2026-06 → 2026-08 | **0.584** | **0.613** | 0.397 | **0.596** |

The previous version of this section claimed three independent models agreed on where the
edge lives, and treated that as the only unambiguously real effect in the dataset. O2
breaks it. What actually survives all four models is narrower:

- **Window 3 is the worst window** (all four), and **window 4 is a good one** (three of
  four; N2 is the exception).
- Windows 1 and 2 are **model-dependent**: they invert between the 15m models and the 5m
  model.

The "agreement" was among three models that shared a 15m bar grid and the same 771k
training samples — a shared blind spot reads as consensus. And O2's window spread is
**0.096** against F4's **0.160**: the higher-resolution model is *less* regime-locked, not
differently regime-locked, which is what you would expect if part of the window structure
was capacity rather than market state.

This does **not** kill the regime-analysis item — a 0.10 spread is still four to six times
the run-to-run noise of §0.3, and the top window is still worth ~5× maker cost. It changes
the question from "find the observable that flags the good regime" to "how much of this is
market state and how much is the model", and it means the analysis must run on **O2's**
prediction dump, not F4's. See **P1**.

### 1.3 🟢 Current reference numbers — O2 is the new baseline

Run `20260818T185438Z` · ckpt `m2_multi_20260818T185438Z_8c4b2a03.pt` · `logs/O2.log`
Config: `CANDLE_INTERVAL=5m`, seq 384 (= 32h context), `PAIR_EMBED_DIM=8`, `SEED=1`,
`EARLY_STOP_PATIENCE=20`, fixed labels, 8 pairs, horizons 60/240/1440, primary 240.
Split: `train [2022-08-19 21:45 → 2025-12-09 09:45]`, `val [2025-12-09 09:45 → 2026-08-17 18:35]`,
2,895,782 samples (2,316,625 / 579,157). Early stop at epoch 34, **selected epoch 14**.

| | 1h | **4h (primary)** | 24h |
|---|---:|---:|---:|
| cov05 dir_acc / Wilson-LB (selected epoch) | 0.544 / 0.537 | **0.563 / 0.557** | 0.582 / 0.575 |
| cov05 LB, mean ± sd over epochs (§0.3) | — | **0.525 ± 0.015** (n=34) | — |

**4h fixed-coverage P&L — the table that matters** (`net` is exactly `gross − trades ×
cost`, so no re-run changes fees):

| cov | trades | gross bps/trade | net @5bps maker | net @14bps taker | F4 gross, same cov |
|---|---:|---:|---:|---:|---:|
| 0.01 | 469 | **+24.50** | **+19.50** | **+10.50** | +2.61 |
| 0.02 | 708 | **+22.11** | **+17.11** | **+8.11** | +6.53 |
| 0.05 | 1361 | +3.50 | −1.50 | −10.50 | +6.50 |
| 0.10 | 2577 | −5.16 | −10.16 | −19.16 | −2.96 |
| 0.20 | 4489 | −3.13 | −8.13 | −17.13 | −4.38 |

The ordering is monotone-decreasing in confidence, which is what makes it usable — the
model's confidence ranks its own economics correctly. The matched-trade-count comparison
is the cleanest one available: **O2 at 469 trades earns +24.50 bps/trade where F4 at 466
trades earned +6.53.**

Serial-position sim at the same checkpoint (`hold=48 bars`, 1 position/pair):

| gate | coverage | trades | dir_acc | net_ret @14bps taker | win | Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| 0.58 (served) | 4.8% | 1318 | 0.565 | −1.31 | 0.502 | −1.22 |
| **0.62** | 1.2% | 548 | 0.556 | **+0.99** | 0.586 | **+1.41** |

⚠️ **The served gate is wrong for this model.** `GATE_THRESHOLD=0.58` is tuned to F4's
confidence scale; on O2 the profitable operating point is **0.62**. Do not promote O2
without moving the gate — see **C13** in §6.

Other health checks, all better than F4's:

- **Side split is balanced** — up 0.563 / down 0.563 at cov 0.05 (F4: 0.547 / 0.528). The
  model is no longer meaningfully long-biased.
- **Calibration improved but is still over-confident** — the `[0.60,0.70)` bin has
  `mean_pred 0.624` vs `emp_up 0.574` (F4: 0.636 vs 0.547). Still the wrong direction for
  sharpening; §5's entry stands.
- **No calendar confound** — book-era cov05 LB 0.545 vs pre-book 0.561; the edge is not
  concentrated in the 31-day book window.
- **Beats both trivial baselines** — momentum (sign of trailing 48 bars) cov05 LB 0.460;
  buy-and-hold pooled deeply negative (only HYPE and ZEC are positive over the window).

**Caveats that bound how much of this to believe** — all three are addressed by P0:

1. **n = 1 seed.** §0.3's own rule says a single run cannot resolve much; this run clears
   the bar on mean-of-epochs, but the P&L table does not have an equivalent error bar.
2. **The P&L is measured on an order-statistic epoch.** Epoch 14 was selected as max LB,
   +2.15 sd above the run's own mean. A replicate's epoch-14-equivalent will be worse.
3. **The +24.5 bps cell has ~470 trades across 8 correlated pairs.** With per-trade sd of
   roughly 150bps at 4h, the standard error is ~7bps if trades were independent and more
   like ~11bps once cross-pair correlation is accounted for. That is a ~2σ result, not a
   4σ one. It is the most promising cell in the project and it is not yet banked.

F4 (`20260817T221811Z`, `logs/O0-f4-rescore.log` for its re-scored tables) remains the
comparison point and is still reachable at
`checkpoints/m2_multi_20260817T221811Z_94614795.pt`.

### 1.4 O3 — longer context is worse; architecture is closed again

`logs/O3.log`, run `20260819T021020Z`. Valid: `seq=256`, `CANDLE_INTERVAL=15m`,
`PAIR_EMBED_DIM=8`, 964,483 samples, embed ON, split re-recorded. One variable vs F4.

Mean-of-epochs cov05 LB **0.4925 ± 0.0227** (n=24) against F4's **0.5058 ± 0.0162**. Not
merely flat — the per-epoch series drifts monotonically *down* (≈0.52 through epoch 5,
≈0.47 from epoch 16 on) and the selected epoch is 4 of 24. The failure signature is
consistent: coverage at the served 0.58 gate collapsed to **0.8%** (F4: 4.9%), and the side
split went lopsided at cov 0.05 — 6,266 down-gated vs 3,379 up-gated, with the **up side at
0.499, exactly coin flip**.

The pre-registered verdict fires the negative way: **the LSTM already has all the context
it can use at 15m.** N2's GBT gap is therefore about the GBT's 114-column static summary
throwing away information, not about recurrence being essential. Encoder capacity, context
length, and full architecture swaps all go back in the closed pile (§5). **Do not write a
transformer.**

Read O2 and O3 together and the shape is clear: **more, finer observations helped; more
window did not.** The model is limited by what each timestep tells it, not by how many
timesteps it sees.

### 1.5 The "flat training loss" diagnostic is falsified — stop using it

The previous plan reasoned that `loss_tr` barely moving (1.7318 → 1.7101 over F4's 11
epochs) proved the model was not data-starved and the bottleneck was entirely features.
O2 ran that experiment and the reasoning does not hold. O2's `loss_tr` was **equally flat
for its first 22 epochs** (1.7284 → 1.7184), then descended only because memorization
started at epoch 23, with `loss_va` diverging in lockstep (1.0404 → 1.3031 by epoch 34).
By the loss-curve indicator, O2 looked exactly like F4 in the region where its selected
epoch lives — and it was materially better.

**On a near-noise-floor task the training loss is dominated by the irreducible term and
carries no information about whether more data helps.** Judge the data lever on the
validation-selection metric. This also means O2's own late-epoch descent is not a reason
to add regularization: the selection metric already ignores those epochs.

### 1.6 The model still sees six real numbers per bar

Unchanged by the O-wave, and now the leading suspect. `FEATURE_COLS` has 19 entries, but
every recent log's `WARNING [norm] train fit[...]` block says **12 of 19 are CONSTANT in
the train window** and are correctly zeroed (13 for 1000PEPE, which also loses
`has_funding_oi`). What actually carries signal in F4 / O2 / O3:

| live | dead in the train window |
|---|---|
| `ret_1`, `hl_range`, `oc_range`, `log_vol`, `ret_std_15`, `funding` (+ `has_funding_oi` mask) | `spread_bps`, `imbalance`, `micro_mid`, `bid_ask_vol_ratio`, `depth_near_imb`, `trade_count`, `buy_sell_imb`, `trade_vol`, `oi`, `oi_chg`, `has_book`, `has_trades` |

Six signal columns — four single-bar OHLCV derivatives, one 15-bar rolling vol, and the
funding rate. No multi-timescale returns, no multi-scale volatility, no cross-pair or
market-wide context, no trend. `funding` is correctly aligned
(`FUNDING_OI_MAX_AGE_MIN=480` = 8h matches the funding interval), so it is not silently
zeroed.

§1.4's conclusion sharpens this: the model is starved **per timestep**, not per window.
That is exactly what **P3 / O4** adds, and it is now the highest-EV lever on the board.

### 1.7 Data status (verified on the VM, 2026-08-18; re-verify before P2)

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

O2 and O3 both loaded ~29.4M candles against the audit's counts, so nothing has moved
since; **P2 needs 1m coverage re-confirmed** before launch, since it is the only interval
the audit has not been exercised at by a training run.

---

## §2 — THE RUN QUEUE

The O-wave produced one real result (O2) that rests on one seed, and closed one lever
(O3). The P-wave is therefore ordered: **bank O2 first, then exploit it.** P0 and P1 come
before anything new. P0 is two GPU runs that must go **one at a time** (§7 — training runs
are strictly serial), but P1 is local and free, so run it while P0's first seed trains.

**None of the O-wave commands should be re-launched as written.** O0 is done, O2 is the
new baseline, O3's lever is closed (§5).

### 🔴 Before you launch anything: the promote hazard

`checkpoints/latest.pt` is currently **O3's checkpoint** — the worst run in the wave (§1.4)
— because O3 finished after O2. Every training run overwrites that key and
`gcp_promote.sh` only ever promotes `latest.pt`. **O2 lives at
`checkpoints/m2_multi_20260818T185438Z_8c4b2a03.pt`** and that is the only reachable copy.
Do not run `gcp_promote.sh` at all until C13 (§6) lets it take an explicit key.

### P0 — 🔴 seed replicate of O2 (2 × GPU, ~4–6h each, **run serially**). Runnable now.

**This is the highest-priority item and it is not optional.** §0.3 exists because this
project has repeatedly banked single-run results that did not replicate. O2 is the best
result the project has produced and every number in §1.3 comes from one seed and one
order-statistic epoch. Two replicates turn "promising" into "measured".

⚠️ **These are two separate sessions, not a parallel launch** — see §7: only one
`gcp_train.sh` job can exist at a time, and starting a second while the first runs can
delete the VM doing the first. Budget **~8–12h of wall clock total**, not 4–6.

Identical to O2 except `SEED`. Run the first, wait for `gcp_status.sh` to report DONE and
save its log, **then** run the second.

```sh
# --- run 1 ---
CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 \
  EARLY_STOP_PATIENCE=20 SEED=2 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 384
./scripts/gcp_status.sh                        # wait for DONE before the next launch
./scripts/gcp_logs.sh <run_id> > logs/P0-seed2.log

# --- run 2, only after run 1 has finished ---
CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 \
  EARLY_STOP_PATIENCE=20 SEED=3 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 384
./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> > logs/P0-seed3.log
```

**If only one replicate is affordable, run `SEED=2` and stop there.** One replicate already
decides the reject branch below — two runs 4 SEM apart is exactly the §0.3 comparison — and
the third seed only tightens the banked estimate.

**Verify:** `knob SEED=2` / `knob SEED=3`; `knob CANDLE_INTERVAL=5m`; `Samples:` ≈ 2.9M;
`P&L sim: … hold=48 bars` for 240m; `Early stop at epoch N` with N ≫ 21; split re-recorded
(a backfill may have moved it — record the new one).

**Verdict, pre-registered so it cannot be argued after the fact:**

- **Bank it** if the three-seed mean-of-epochs LB is ≥ 0.515 (i.e. the O2 − F4 gap survives
  at ≥ half strength) **and** at least two of three seeds show gross bps/trade > +12 at
  cov 0.01–0.02. Then 5m/seq384 becomes the permanent baseline, C13 ships, and the model
  is promotable as an M3 input.
- **Half-bank it** if the LB gap survives but the P&L does not. Then the signal genuinely
  improved but the +24 bps cell was epoch-selection luck, and the operating point must be
  re-derived from the three-seed pooled fixed-coverage table rather than any one run's.
- **Reject** if seeds 2 and 3 land near F4's 0.506. Then O2 was a lucky seed, 5m is
  neutral, and the whole wave collapses back to §1.6 being the only lever.

**Bring back:** both logs, plus for each the `epoch LB series` line and the 240m
`Fixed-coverage P&L` block.

### P1 — regime analysis on O2's dump (local, no VM, no training). Runnable now.

Was O1; the O0 dump it was blocked on exists, and §1.2 changed what it should ask. Use
**O2's** per-bar dump (`gs://fluxtrader-train-artifacts/eval/20260818T185438Z/eval_preds.parquet`),
with F4's (`.../eval/<O0 run_id>/eval_preds.parquet`) as the contrast.

Costs nothing but a script. For each val bar compute candidate regime observables from
candles already in the DB, all lookahead-free:

- realized vol of the pooled universe over trailing 1d / 7d / 30d
- BTC trailing return over 1d / 7d, and its sign
- cross-sectional dispersion of trailing 4h returns across the 8 pairs
- cross-pair correlation of trailing 1d returns (one "everything moves together" scalar)
- funding level and funding sign, pooled and per pair
- the model's own mean confidence over a trailing 1d window

Three questions, in order:

1. **Separation.** AUC of each observable against "bar is in a high-edge window". Compute
   it **separately for O2 and F4**, because §1.2 says they disagree about which windows
   those are.
2. **Conditional lift.** Bucket val bars by each observable into quintiles; report cov05
   LB *and* gross bps/trade per bucket. The number that matters is the top bucket's gross
   bps/trade against 5bps maker and 14bps taker.
3. **New, and the reason this is worth doing at all now:** how much of the window structure
   is *model* rather than *market*? Compare the O2 and F4 per-bar predictions directly —
   agreement rate, and whether the bars where they disagree cluster in windows 1 and 2. If
   the window structure is largely a model artifact, the observables will separate F4's
   windows and not O2's, and the right conclusion is that finer bars fixed part of it and
   P3 will fix more.

**Verdict:**
- An observable with ≥0.60 AUC whose top bucket shows gross ≫ 5bps → we have both a
  feature (feed it in P3) and a regime gate. Note that a regime *gate* is an M3 policy
  decision, not an M2 one — M2's job is to emit the observable, not to act on it.
- Nothing separates, and O2/F4 disagree mostly in the model-dependent windows → the
  structure is capacity, not state. Skip the regime feature work and put everything into
  P3's per-timestep features.

Bring back the AUC table (both models), the per-quintile gross-bps table, and the
O2-vs-F4 agreement analysis.

### P2 — 1m bars: does the resolution ladder keep paying? (GPU, ~10–16h). After P0.

O2 established that finer bars at fixed context-hours is a real lever. The obvious question
is whether it saturates. The clean single-variable version holds the 32h context: 1m bars
need `seq 1920`, which is 5× O2's sequence length on 3× the samples and is not affordable.

**Do not launch this until P0 reports.** If P0 rejects, this lever does not exist. If P0
banks, launch the affordable compromise and accept that it moves two variables at once —
which is tolerable here only because we are probing a *direction*, not attributing an
effect:

```sh
CANDLE_INTERVAL=1m PAIR_EMBED_DIM=8 \
  EARLY_STOP_PATIENCE=20 SEED=1 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 768
```

`seq 768` at 1m is 12.8h of context — *less* window than O2, which §1.4 says the model was
not using anyway. Expect ~8.7M samples and `hold=240 bars` for the 240m head.

**Verify:** `knob CANDLE_INTERVAL=1m`; `Samples:` ≈ 8–9M; `P&L sim: … hold=240 bars`;
wall-clock — kill it and fall back to `--gpu 40 768` if it will not finish overnight.

**Verdict:** rank on mean-of-epochs LB and on `dir_acc` (§0.6 — the bar counts differ
again, so LB alone will flatter it). Better than O2 → the ladder has another rung and 1m
becomes the baseline. Flat or worse → 5m is the resolution sweet spot, freeze it, and the
lever is closed.

### P3 — cross-pair / regime features (was O4). Blocked on C12. Highest EV after P0.

§1.6 (six live features per bar) and §1.4 (the model is starved per timestep, not per
window) both point here, and O2 raised the prior: the model demonstrably converts more
input into more edge. Add, from candle data that already spans the full history for every
pair and needs zero collection lead time:

- trailing returns at 1h / 4h / 1d (multi-timescale, currently absent entirely)
- rolling volatility at 2–3 scales beyond the single `ret_std_15`
- BTC-relative return and rolling beta per pair
- cross-sectional return rank and dispersion across the universe
- whichever observables P1 finds separate the windows

Needs code task **C12** (a `FEATURE_DIM` bump, which changes the serving contract) and
therefore its own attributable run. **Wait for P1** before fixing the feature list — P1
tells you which regime observables are worth a column.

### After this wave

Read P0 + P1 together in a **fresh session**; P2 and P3 both branch off that reading. Still
queued behind them, unchanged:

- **O5 — L2 ladder feature audit (read-only, NO training).** `orderbook_levels` has ~14d ×
  100 levels × 8 pairs with zero integrity errors, and the five book features are all
  *instantaneous snapshot levels* with no dynamics. Two known gaps, both fixable from data
  already on disk: (a) no order-flow imbalance, no book delta over the last N snapshots, no
  queue-depletion rate, no depth slope, no microprice drift — at 30m+ horizons
  microstructure predictive power comes mostly from OFI and its persistence, not from a
  snapshot's static imbalance; (b) `_align_with_age` keeps only the *last* snapshot per bar
  and discards ~5 of every 6, so per-bar aggregates (mean/std/range of imbalance within the
  bar, summed OFI, max spread) are free information. Run `audit_microstructure.py` on the
  candidates before spending a `FEATURE_DIM` bump. This replaces the retired book
  walk-forward (§5) as the way the book question gets answered. **Note the 5m/1m move makes
  this more attractive**: at 5m bars a 10s snapshot cadence gives ~30 snapshots per bar to
  aggregate instead of ~90 thrown away.
- **O6 — magnitude-weighted directional loss** (code task C3). The train-time twin of the
  idea N3 tested at selection time, worth trying *because* the selection-time version failed
  for a reason that does not apply at train time: a per-sample loss weight uses every
  training bar rather than a ~600-effective-sample validation statistic. O2's 24h head
  (§ archive) is a live example of the pathology it targets — right on small moves, wrong on
  large ones.
- **O7 — triple-barrier redo.** Blocked on C4b (barrier-aware `simulate_pnl`), wider
  barriers (target ~30–40% flat), `PAIR_EMBED_DIM=8`, and a pinned dataset.
- **O8 — 12 pairs.** Cheap (§1.7): ADA/AVAX/LINK/XRP have full 4-year history at every
  interval. One variable, one run. Low priority, but no longer blocked.

---

## §3 — WHAT TO BRING BACK (for the next session)

Save each run's full log under `logs/` **named after the queue item** (`P0-seed2.log`, not
the run id), then open a **fresh session** and paste the paths. Do not summarize the logs
yourself — the numbers that matter are often not the headline ones.

```sh
./scripts/gcp_logs.sh <run_id> > logs/<queue-name>.log     # e.g. logs/P0-seed2.log
./scripts/gcp_logs.sh          > logs/<queue-name>.log     # omit the id for the latest run
```

⚠️ **Do not use `--save`.** It copies to `$EXPORT_DIR/<run_id>.log`, and `EXPORT_DIR`
defaults to `$HOME/fluxtrader-train-export` (`scripts/gcp_common.sh:102`) with no override
in `scripts/gcp_env` — so the file lands in the home directory under its raw run id, not in
`logs/` and not under the queue name a later session is told to look for. Redirect stdout
instead; that is how every log currently in `logs/` was produced.

**Self-check before you hand them over** — if any of these fails, the run is void and
should be relaunched rather than analyzed:

```sh
L=logs/P0-seed2.log                        # repeat for each run in the wave
grep -nE 'resolved knobs|knob |Pair embedding|Training pairs|primary=|Split global_time' $L
grep -nE 'WARNING \[norm\]|max\|z\||BROKEN SCALE' $L
grep -n  'P&L sim:' $L                     # hold must be horizon_min / bar_min (5m/240m ⇒ 48)
grep -n  'Early stop at epoch' $L           # must NOT be 1 + patience
grep -n  'Samples:' $L                      # 5m/8 pairs ⇒ ~2.90M
grep -n  'epoch LB series' $L               # the §0.3 verdict metric, printed by C10
```

If a log predates C10 and has no `epoch LB series` line, compute it:

```sh
grep -oE 'epoch [0-9]+.*lb=[0-9.]+' $L | grep -oE 'lb=[0-9.]+' | cut -d= -f2 | \
  awk '{n++;s+=$1;q+=$1*$1;if($1>m)m=$1}END{printf "n=%d mean=%.4f sd=%.4f max=%.4f\n",n,s/n,sqrt(q/n-(s/n)^2),m}'
```

**What the next session will read, in order:**
1. The §0.4 verification lines — is the run valid at all.
2. **The per-epoch LB mean ± sd (§0.3)** — this is the verdict metric now, not the max.
   Pool it across seeds when a wave has replicates.
3. `Fixed-coverage P&L` → **gross bps/trade** at cov 0.01–0.20, against 5bps maker **and**
   14bps taker. Since O2 the taker column is no longer automatically negative, so read it.
3b. `dir_acc` alongside every Wilson-LB whenever the arms differ in bar interval (§0.6).
4. `--- Walk-forward edge on val window ---` win 1–4 → does the §1.2 regime pattern hold,
   and did anything narrow the window-2-vs-window-3 spread.
5. `Fixed-coverage directional edge` → is the ordering monotone in confidence.
6. `Side split` + `Long/short serial P&L` → one-sided?
7. `Book-era split` → is the edge a calendar confound?
8. `Momentum baseline` + `Buy-and-hold` → did it beat the trivial baselines.

---

## §4 — RESULTS LEDGER

⚠️ **Read §0.3 and §0.6 first.** Every `cov05 LB` below is `max over epochs` of a series
with sd ≈ 0.015–0.023, so differences under ~0.04 between single runs are not evidence —
use the parenthesised `mean±sd` column instead where it exists. And LB is not comparable
across bar intervals (§0.6): O2's LB benefits from 3× the val rows for the same 8 months.
**Post-`2e7b272` runs are a new lineage and are not comparable to anything above the
line.**

| Run | What | Primary | cov05 LB | Valid? | Verdict |
|---|---|---:|---:|---|---|
| **O2** `20260818T185438Z` | **5m bars, seq 384 (32h), 2.9M samples** | 240m | **0.557 (mean 0.525±0.015, n=34)** | ✅ **new baseline** | Resolution is a real lever — first effect other than the GBT gap that the measurement resolves. `dir_acc` 0.563 vs F4's 0.542 (§0.6). Gross **+24.5 bps/trade @469 trades**, positive at taker; serial P&L +0.99 @14bps at gate 0.62, Sharpe 1.41. WF spread narrowed to .573/.535/.500/.596. **One seed — P0 must replicate before this is banked.** Served gate must move 0.58→0.62 (C13). §1.3 |
| **O3** `20260819T021020Z` | 15m bars, **seq 256 (64h)** — context length | 240m | 0.531 (mean 0.4925±0.023, n=24) | ✅ **decisive, negative** | Worse than F4 on mean-of-epochs; per-epoch series drifts monotonically down; served-gate coverage collapsed 4.9%→0.8%; up side at 0.499. Longer context is dead and **architecture is closed again**. §1.4 |
| **O0** `eval-only re-score of F4` | F4 on today's eval code, CPU | 240m | 0.531 (reproduced exactly) | ✅ | Delivered F4's missing `Fixed-coverage P&L`: +2.61 / +6.53 / +6.50 / −2.96 / −4.38 gross bps at cov .01/.02/.05/.10/.20. Closes N3-vs-F4 — N3's +4.24 @cov05 is inside noise of F4's +6.50. |
| **F4** `20260817T221811Z` | 15m bars, seq 128, horizon ladder | 240m | 0.531 (mean 0.506±0.016, n=18) | ✅ **prior baseline, superseded by O2** | 4h is the horizon peak. Best cell +6.5 gross bps/trade ≈ maker break-even, never positive at taker. WF .486/.617/.457/.584. C2 table now supplied by O0. |
| **N3** `20260818T031002Z` | cost-aware selection, `SEL_NET_WEIGHT=0.5 SEL_COST_BPS=5` | 240m | 0.523 (mean 0.499±0.016) | ✅ valid, **lever closed** | Selected epoch 1, stopped at 11. Score blend was ~88% cost term and the cost term ranks noise. Gross +4.2bps @cov05 — no better than F4. **Do not promote**; it overwrote `latest.pt`. §1.5 |
| **N2** `gbt-20260818T070504Z` | LightGBM 114-col static summary at 15m/4h | 240m | **0.4692** | ✅ decisive, **re-read after O3** | Below coin flip at every coverage; 0.04–0.06 worse than the LSTM. Originally read as "recurrence matters, try more context". O3 tested that and refuted it, so the surviving reading is narrower: **the 114-column static summary throws information away**, and this says nothing about needing a bigger architecture. §1.4 |
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
| **Context length / sequence window** | **Closed (new, 2026-08-19)** | O3 ran seq 128→256 at 15m as a clean one-variable test and it is *worse* on mean-of-epochs (0.4925±0.023 vs F4's 0.5058±0.016), with a collapsing confidence distribution and a coin-flip up side. The LSTM already uses all the window it can. Do not sweep seq 512. Note this is about *window*, not *resolution* — finer bars at the same window (O2) is a separate and live lever. §1.4 |
| Encoder capacity / layers / hidden sweeps | **Closed again (2026-08-19)** | Was reopened on N2's GBT gap. O3 tested the cheap version of that hypothesis and refuted it: the gap is about the GBT's static summary discarding information, not about the LSTM needing more modelling power. Also barred by the last row of this table — a single-run capacity sweep cannot resolve what it would be measuring. |
| Full architecture swap (transformer / TCN) | **Closed (2026-08-19)** | Was gated behind O3; O3 came back negative. **Do not write a transformer.** Reopen only if P3's richer per-timestep features saturate and the residual failure looks like a modelling limit rather than an input limit. |
| Confidence calibration / temperature / focal loss | **Closed** | F4's head is *over*-confident (`[0.60,0.70)` bin mean_pred 0.636 vs empirical 0.547; N3's is 0.609 vs 0.521). Sharpening an over-confident head is the wrong direction. |
| Raising `GATE_THRESHOLD` as an experiment | **Superseded by C1+C2** | The served gate is 0.58 and eval now reports there. Derive the operating point from the fixed-coverage P&L table, not from another sweep. |
| Quantile head | **Deferred** | Regressed direction ~0.014; band coverage unstable. Revisit at M3, detached. |
| `liquidations` feed | **Dropped** | 0 rows; Binance gates WS market data from datacenter egress (verified from 3 hosts). |
| More candle *history* | **Closed** | Adds more of the pre-book regime we already fit. Note this is about *history*, not *resolution*. |
| **Bar resolution (15m → 5m)** | **🟢 OPEN and paying** | O2 is the project's first resolvable improvement (§1.3). Provisional pending P0's seed replicate; the next rung (1m) is P2. |
| **"Flat `loss_tr` proves the model is not data-starved"** | **Falsified (new, 2026-08-19)** | O2's loss was as flat as F4's through the region its selected epoch lives in, and it still improved materially. On a near-noise-floor task the training loss is dominated by the irreducible term. Judge data levers on the validation-selection metric only. §1.5 |
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

### Next up

- 🔴 **C13 — make promotion safe and make the served gate a per-checkpoint property.**
  Two coupled defects that O2 exposed and that block promoting it:
  1. `gcp_promote.sh` only ever promotes `checkpoints/latest.pt`, and every training run
     overwrites that key. `latest.pt` is currently **O3's** checkpoint (§1.4) and O2 is
     reachable only at its named key. Give the script an explicit
     `--checkpoint <key>` argument and make the bare form refuse to run when `latest.pt`
     is not the checkpoint the operator names.
  2. `GATE_THRESHOLD=0.58` is a global serving constant tuned to F4's confidence scale.
     On O2 the profitable operating point is **0.62** (§1.3), and O3 showed the scale can
     shift far enough to gate almost nothing. The gate belongs in the checkpoint meta,
     chosen at eval time from the fixed-coverage P&L table and read by `serve.py` — with
     the config value as a fallback only. Until this ships, promoting any new checkpoint
     silently changes the operating point.

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
| Train (GPU) | `./scripts/gcp_train.sh --gpu 60 128` | `./scripts/gcp_status.sh` | `./scripts/gcp_logs.sh <run_id> > logs/X.log` | `fluxtrader-train` |
| Eval only (no training) | `./scripts/gcp_train.sh --eval-only <ckpt-key>` | `./scripts/gcp_status.sh` | `./scripts/gcp_logs.sh <run_id> > logs/X.log` + `gs://…/eval/<run_id>/` | `fluxtrader-train` |
| Walk-forward | `./scripts/gcp_walkforward.sh` | `--status` | `--fetch` | `fluxtrader-walkforward` |
| GBT diagnostic | `./scripts/gcp_gbt.sh` | `--status` | `--fetch` / `--log` | `fluxtrader-gbt` |
| Single-window ablate | `./scripts/gcp_ablate.sh` | — | — | own VM |
| Feature audit | `./scripts/gcp_audit.sh` | — | — | own VM |
| Data stats | `./scripts/gcp_data_collection_stats.sh` | — | — | always-on |
| Promote | `./scripts/gcp_promote.sh --local-copy` | — | — | always-on |

Each *job type* has its own VM, so a walk-forward, a GBT diagnostic and a training run can
overlap. They self-DELETE on success and self-STOP on failure. `KEEP_VM=1` keeps the VM for
debugging. Never run a training-sized job on the always-on VM — it has 2GB and the kernel
OOM-kills it silently.

🔴 **Two runs of the SAME job type cannot overlap — training runs are strictly serial.**
`gcp_train.sh` targets one fixed instance name (`$GCP_TRAIN_INSTANCE`) and *adopts*
whatever it finds there: it starts a stopped VM, reuses a running one, or **deletes and
recreates it** when the requested machine type or accelerator does not match
(`scripts/gcp_train.sh:239,251,297`). A second launch during a live job can therefore
destroy the run already in flight. The shared `gs://…/status/latest.json` marker and the
fixed on-VM paths (`$HOME/run_flux_train.sh`, `m2_multi.pt`) collide the same way.

**Consequence for planning:** a queue of N training runs costs the *sum* of their wall
clocks, not the max. Write multi-run items in this doc as an ordered serial list, never as
a loop or a "launch both" instruction, and state the total wall clock when proposing
replicates.

⚠️ `gcp_promote.sh` only ever promotes `checkpoints/latest.pt`, and every new training run
overwrites that key. **`latest.pt` is currently O3's checkpoint — the worst run of the
O-wave (§1.4) — and must not be promoted.** The checkpoints you may actually want:

| run | key |
|---|---|
| **O2** (current baseline) | `checkpoints/m2_multi_20260818T185438Z_8c4b2a03.pt` |
| F4 (prior baseline) | `checkpoints/m2_multi_20260817T221811Z_94614795.pt` |
| O3 (do not promote) | `checkpoints/m2_multi_20260819T021020Z_8c4b2a03.pt` = `latest.pt` |

**Do not run `gcp_promote.sh` until C13 ships** (§6) — and note that promoting O2 also
requires moving the served gate from 0.58 to 0.62, or it will trade at a loss-making
operating point.

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

Worth keeping in view — **this paragraph changed with O2.** Through F4 the only positive
cells in the project appeared at maker cost (F4's best: +6.5 gross, +1.5 net at maker,
−7.5 at taker), which made execution work the single largest sign-flipping lever
available. O2's top-2% slice is **+22 to +24 gross bps/trade, i.e. +8 to +10 net at full
taker cost**, and its serial sim books +0.99 net_ret at 14bps. Execution work is still
worth roughly +9 bps/trade and is still not an ML change — but it is no longer the
difference between a signal that can and cannot be traded, and it is M3's problem
regardless. Do not let it block the model queue.

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
