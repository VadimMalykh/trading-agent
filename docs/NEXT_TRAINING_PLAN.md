# Training plan — what is true, what to run next

**Last updated: 2026-08-21** (after the P-wave: P0 seed replicates of O2, P2 1m bars).

This document is the project's session-to-session memory. It contains only what is
**currently true and actionable**. The session-by-session narrative from 2026-07-23 →
2026-08-21 — every superseded plan, every rejected hypothesis, every raw results table —
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
with. §1.3 is where that stopped being the case, and as of the P-wave it is measured on
three seeds rather than one.

The second place they matter is **calibration**, which the P-wave promoted to a
first-class acceptance criterion: M3 consumes probabilities, so a model that ranks well
while emitting meaningless probabilities (P2, §1.4) has not improved.

**How to use this doc:** if you are picking this up cold, the fastest path is
§1.1 (one paragraph on where we are) → §2's Q0/Q1 (what to do, neither needs a GPU) →
§0.3 and §0.6 (why the numbers are read the way they are).

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
| **O2** (5m, seq 384, seed 1) | 34 | **0.5248** | 0.0148 | 0.5565 | +2.15 sd |
| **P0-seed2** (5m, seq 384, seed 2) | 28 | **0.5207** | 0.0202 | 0.5576 | +1.83 sd |
| **P0-seed3** (5m, seq 384, seed 3) | 39 | **0.5203** | 0.0123 | 0.5425 | +1.81 sd |
| P2 (1m, seq 768) | 38 | 0.5256 | 0.0150 | 0.5579 | +2.15 sd — *LB inflated, see §0.6* |
| F4 (15m, seq 128) | 18 | 0.5058 | 0.0162 | 0.5310 | +1.56 sd |
| N3 (15m, cost-sel) | 11 | 0.4987 | 0.0155 | 0.5230 | +1.57 sd |
| O3 (15m, seq 256) | 24 | 0.4925 | 0.0227 | 0.5313 | +1.71 sd |

🟢 **The three 5m seeds are the first replicated result in the project.** Their means agree
to within 0.0025 (SEM 0.0014), pooling to **0.5219**, and the gap to F4 is **+0.016 ≈ 4σ**.
Note what replicated and what did not: the *mean-of-epochs level* and the *top-2%
fixed-coverage P&L* both did; the *serial-sim P&L magnitude* did not (§1.5), and neither
did side balance, the book-era split, or any per-pair number (§1.3). Between-seed sd of
the mean is the error bar to quote — not one run's sd, which describes epochs.

Every run's selected epoch still sits 1.5–2.2 sd above its own mean, so any *single* run's
`Fixed-coverage P&L` table is measured on an optimistically selected epoch. **Seed
replication is the only way to bank a result** — P0 did it, and §1.3 is what a banked
result looks like: pool the trades across seeds, quote the between-seed SEM.

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
| `Feature columns:` | the count and list you intended (30 after C12; 19 for a pre-C12 checkpoint) | — |
| `[market] cross-pair context filled for N/N pairs` | **N/N**, and `mean has_market` ≈ 1.0. Anything less means the cross-pair columns are zeros for some pair and Q3 tested less than it looks | — |
| `SERVED GATE (C13, coverage-targeted)` | present, and the realized coverage is the one you asked for | — |

**Two CONSTANT-column warnings are EXPECTED after C12 and are not defects.**
`has_market` is constant (always 1) because the market context spans the whole
history — unlike `has_book`, there is no era where it is missing, so the mask is
correctly zeroed by the degenerate handler and costs one dead column. And
`btc_rel_ret_1h` is identically zero **for BTCUSDT only**, since BTC's return relative
to itself is zero; it is live for every other pair. Expect
`13/30 CONSTANT` for BTC and `12/30` for the others, not the old 12/19.

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

**P2 demonstrated the trap a second time and more starkly** (§1.4). At 1m bars it has 2.9M
val rows — 5× the 5m family's 0.58M — and posts the highest mean-of-epochs LB in the whole
ledger (0.5256) while its `dir_acc` at cov05 is **0.561 against the family's 0.559**, i.e.
dead flat, and its economics are two to eight times worse. Had this section not existed,
P2 would have been read as the best run in the project. **When the bar interval differs,
LB is not a ranking metric at all.**

---

## §1 — WHERE WE ARE (2026-08-21)

### 1.1 The one-paragraph summary

**The 5m-bar result is banked, and the resolution ladder is closed at 5m.** P0 replicated
O2 at `SEED=2` and `SEED=3` and the pre-registered "bank it" branch fires on both clauses:
three-seed mean-of-epochs cov05 LB **0.5219 ± 0.0014** (between-seed SEM, n=101 epochs)
against F4's 0.5058 — a **+0.016** gap at roughly 4σ — and all three seeds clear +12 gross
bps/trade at cov 0.01–0.02, pooling to **+19.4 / +22.0 gross bps/trade** on 1,081 / 1,783
trades, i.e. **+5.4 / +8.0 net at full 14bps taker cost**. `5m bars, seq 384, PAIR_EMBED_DIM=8`
is now the permanent baseline and the model is a usable M3 input once C13 ships. P2 tested
the next rung and it is not there: 1m bars at seq 768 land at mean LB 0.5256 (inside seed
noise, and inflated by 5× the val rows — §0.6), `dir_acc` at cov05 **0.561 vs the 5m
family's 0.559**, materially *worse* fixed-coverage P&L (+2.6 / +8.5 at cov 0.01/0.02),
**destroyed calibration** (every probability bin from 0.05 to 0.95 has `emp_up ≈ 0.48`;
brier 0.323 vs 0.250), and 20h of wall clock against 2.5–3h. Two things the replicates
*corrected*: the serial-P&L headline did not survive (§1.5 — an absolute confidence gate
is not seed-stable, which changes what C13 must do), and the O-wave's regime story was
half seed noise (§1.2). With resolution, context length, and architecture all now closed,
**§1.6 — the model sees six real numbers per bar — is the only large lever left**, and the
next GPU run is the feature expansion.

### 1.2 The regime structure, re-read on six models

`cov05 wilson_lb` on the primary 240m head, val window split into four ~2-month blocks:

| window | period | F4 (15m) | N3 (15m) | N2 (GBT) | O2 (5m s1) | **P0 s2** | **P0 s3** | **P2 (1m)** |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2025-12 → 2026-02 | 0.486 | 0.499 | 0.492 | 0.573 | **0.621** | **0.593** | 0.542 |
| 2 | 2026-02 → 2026-04 | 0.617 | 0.621 | 0.574 | 0.535 | **0.618** | **0.592** | 0.506 |
| 3 | 2026-04 → 2026-06 | 0.457 | 0.419 | 0.415 | 0.500 | **0.482** | **0.491** | **0.607** |
| 4 | 2026-06 → 2026-08 | 0.584 | 0.613 | 0.397 | 0.596 | **0.596** | **0.621** | 0.623 |
| spread | | 0.160 | 0.202 | 0.177 | 0.096 | 0.139 | 0.130 | 0.117 |

Two of the O-wave's readings were single-seed artifacts and are withdrawn:

- **Window 2 does not invert between 15m and 5m.** O2's 0.535 was the outlier; seeds 2 and
  3 score 0.618 / 0.592, right on top of F4's 0.617. Only **window 1** is genuinely
  resolution-dependent: every 5m model finds edge there (0.573–0.621) where every 15m model
  is at coin flip (0.486–0.499). That is the sharpest thing this table says, and it is
  consistent with 5m simply being a better model rather than a differently-regime-locked one.
- **The 5m model is not meaningfully less regime-locked.** O2's 0.096 spread was the low
  draw; the 5m family averages ~0.12 against the 15m family's ~0.18. A real but small
  narrowing, not a change of kind.

What survives across all six directional models: **window 3 is the worst window and window
4 is a good one.** The single exception is P2, which inverts window 3 into its *best*
(0.607) — but P2's confidence scale is broken (§1.4), so its top-5% slice is not selecting
the same kind of bar as anyone else's and it should not be given a vote here.

A ~0.13 spread is still 5–8× the run-to-run noise of §0.3 and the top window is worth
several times maker cost. The regime analysis is still worth doing, and it is now **Q1** —
but it must run on **all three 5m seed dumps**, because this table is exactly the place
where one seed misled us. An observable that only separates windows for one seed is noise.

### 1.3 🟢 Current reference numbers — the 5m/seq384 family (3 seeds, banked)

Config, identical across all three: `CANDLE_INTERVAL=5m`, `seq 384` (= 32h context),
`PAIR_EMBED_DIM=8`, `EARLY_STOP_PATIENCE=20`, fixed labels, 8 pairs, horizons 60/240/1440,
primary 240. ~2.90M samples (~2.32M / ~0.58M).

| seed | run | log | checkpoint key | epochs | mean LB ± sd | selected |
|---|---|---|---|---:|---|---|
| 1 (O2) | `20260818T185438Z` | `logs/O2.log` | `m2_multi_20260818T185438Z_8c4b2a03.pt` | 34 | 0.5248 ± 0.0148 | ep 14 (0.5565) |
| 2 | `20260819T142759Z` | `logs/P0-seed2.log` | `m2_multi_20260819T142759Z_a186182b.pt` | 28 | 0.5207 ± 0.0202 | ep 8 (0.5576) |
| 3 | `20260820T025723Z` | `logs/P0-seed3.log` | `m2_multi_20260820T025723Z_a186182b.pt` | 39 | 0.5203 ± 0.0123 | ep 19 (0.5425) |

**Pooled mean-of-epochs cov05 LB = 0.5219**, between-seed sd 0.0025 (SEM 0.0014).
Against F4's 0.5058 that is **+0.0161, ≈ 4σ**. This is the number to quote for the model's
edge. Every seed's *selected* epoch still sits 1.5–2.2 sd above its own mean, so single-run
`max` figures remain order statistics (§0.3) — but the family mean no longer depends on that.

**4h pooled fixed-coverage P&L — the table that matters.** Trade-weighted across the three
seeds; `net` is exactly `gross − trades × cost`, so no re-run changes fees.

| cov | trades | gross bps/trade | net @5bps maker | net @14bps taker | per-seed gross (s1/s2/s3) |
|---|---:|---:|---:|---:|---|
| 0.01 | 1081 | **+19.38** | **+14.38** | **+5.38** | +24.5 / +16.6 / +14.5 |
| 0.02 | 1783 | **+22.03** | **+17.03** | **+8.03** | +22.1 / +16.8 / +26.2 |
| 0.05 | 3718 | +8.91 | +3.91 | −5.09 | +3.5 / +14.7 / +9.6 |
| 0.10 | 7104 | +1.89 | −3.11 | −12.11 | −5.2 / +4.9 / +6.8 |
| 0.20 | 13462 | −0.00 | −5.00 | −14.00 | −3.1 / +1.8 / +1.3 |

Three things to read off it. **(a) The top-2% cell replicated almost exactly** — pooled
+22.0 against O2's own +22.11, with every seed above +16. **(b) The cov-0.05 collapse in
O2 (+3.5) was seed noise**, not a decay curve; seeds 2 and 3 book +14.7 and +9.6 there, so
the signal degrades more gently with coverage than O2 alone suggested. **(c) The ordering
is monotone in confidence** at the family level, which is the §0.4 check that makes the
head usable at all. With per-trade sd ≈ 150bps, the cov-0.02 pooled gross has a standard
error near 3.5bps if trades were independent and ~5–6bps allowing for cross-pair
correlation — so **+22 gross is a ~4σ result and +8 net at taker is ~1.5σ**. The signal is
banked; that it clears *taker* cost is suggestive, not proven.

Health checks across the three seeds:

- **Beats both trivial baselines, every seed.** Momentum (sign of trailing 48 bars) cov05
  `dir_acc` 0.469 in both replicates; pooled buy-and-hold ≈ −35 over the val window (only
  HYPE and ZEC positive).
- **Side balance is NOT seed-stable.** s1 up 0.563 / down 0.563; s2 up 0.567 / down 0.561;
  **s3 up 0.563 / down 0.502** — one seed's short side is a coin flip. Do not treat
  "balanced sides" as a property of the configuration; check it per checkpoint.
- **Calibration is unchanged and still over-confident** — `[0.60,0.70)` bin `mean_pred`
  0.640 / 0.626 vs `emp_up` 0.576 / 0.578 (s2 / s3). §5's entry stands: do not sharpen.
- **The book-era split says nothing.** s1 0.545 vs 0.561, s2 **0.486 vs 0.569**, s3
  **0.624 vs 0.552** — the sign flips between seeds because the book era is ~31 days and
  ~1,300–1,900 directional bars. Stop reading this line until the window is months long.
- **Per-pair `dir_acc` at cov05 is not stable either** (ZEC 0.498 / 0.602 / 0.565 across
  seeds). There is no per-pair story in this data.

### 1.4 P2 — 1m bars are worse; the resolution ladder is closed at 5m

`logs/P2.log`, run `20260820T100042Z`, ckpt `m2_multi_20260820T100042Z_a186182b.pt`.
Valid: `knob CANDLE_INTERVAL=1m`, `seq 768` (12.8h), `PAIR_EMBED_DIM=8`, `SEED=1`, embed ON,
**14,507,307 samples** (11.6M / 2.9M — the plan predicted 8–9M and was low), `hold=240 bars`,
split re-recorded, early stop at epoch 38. As pre-registered, it moves two variables
(interval *and* context hours) and was launched as a direction probe, not an attribution.

The probe comes back negative on every axis that matters:

| | 5m family (3 seeds) | P2 (1m) |
|---|---|---|
| mean-of-epochs cov05 LB | 0.5219 ± 0.0014 | 0.5256 (n=38) — *inflated, 5× val rows* |
| **cov05 `dir_acc`** (§0.6, the honest comparison) | 0.563 / 0.564 / 0.549 → **0.559** | **0.561** |
| gross bps/trade @cov 0.01 / 0.02 | **+19.4 / +22.0** | **+2.6 / +8.5** |
| brier (240m, moved bars) | 0.250 | **0.323** |
| ungated 3-class accuracy | 0.472 / 0.473 | 0.443 |
| wall clock | 2h36m / 3h17m | **20h16m** |

`dir_acc` is flat and the economics are two to eight times worse at the coverages that pay.
The LB looks best-in-class purely because 2.9M val rows narrow the Wilson interval — the
exact trap §0.6 was written for, now demonstrated a second time.

**The calibration failure is the decisive finding.** P2's probability output spreads across
the entire \[0,1\] range — 160k bars in `[0.00,0.10)`, 162k in `[0.90,1.00]` — and
`emp_up` is **0.448 … 0.505 in every single bin**. The head emits confident probabilities
that carry no calibration whatsoever. Two consequences: the serial sim is meaningless at
any gate (80% coverage at `GATE_THRESHOLD=0.58`, net_ret −18), and **an uncalibrated
probability is worthless to M3**, which consumes these as observations. That the ranking
still yields 0.561 `dir_acc` at the top 5% only means the *order* survived what the *scale*
did not.

**Verdict, per the pre-registered rule: flat-to-worse ⇒ 5m is the resolution sweet spot.
Freeze it and close the lever.** The strict caveat — that 1m *with* a 32h window (seq 1920)
is untested — is noted and dismissed: it is unaffordable at 5× P2's already-20h run, and
§5's context-length entry says window is not the binding constraint anyway.

Read O2/O3/P2 together and the shape is settled: **finer observations helped once, from 15m
to 5m, and then stopped. More window never helped.** The model is limited by *what each
timestep tells it* — which is §1.6.

### 1.5 🔴 An absolute confidence gate is not seed-stable — the gate must target coverage

This is the P-wave's most actionable new finding and it rewrites what C13 has to build.

Serial-position sim (`hold=48 bars`, 1 position/pair, 14bps taker) at the two gates that matter:

| seed | gate 0.58 (served) cov / net_ret / Sharpe | gate 0.62 cov / trades / net_ret / Sharpe |
|---|---|---|
| 1 (O2) | 4.8% / **−1.31** / −1.22 | 1.2% / 548 / **+0.99** / **+1.41** |
| 2 | 6.1% / **−0.91** / −0.85 | 2.5% / 595 / **+0.10** / +0.15 |
| 3 | 5.4% / **−0.34** / −0.31 | 1.7% / 497 / **+0.23** / +0.41 |

**What replicated:** the served gate of 0.58 loses money in 3 of 3 seeds, and 0.62 is
profitable in 3 of 3. Moving the gate is confirmed and is not optional.

**What did not replicate:** the magnitude. O2's +0.99 / Sharpe 1.41 headline is 4–10× the
other two seeds and was an epoch-selection artifact. The honest expectation for a 5m
checkpoint at its profitable gate is **≈ +0.4 net_ret, Sharpe ≈ 0.6**, not 1.4.

**Why the two tables disagree** — the fixed-coverage P&L replicated cleanly (§1.3) while
the serial sim did not — is the useful part. A fixed *coverage* compares the same fraction
of each model's bars; a fixed *confidence threshold* compares whatever fraction each seed's
confidence distribution happens to put above 0.62, and that is 1.2% / 2.5% / 1.7% here.
The same absolute number is three different operating points. O3 showed the extreme version
(0.8% coverage at 0.58) and P2 the opposite extreme (80%).

**Therefore C13's gate must be stored as a coverage target, not a probability.** Pick the
operating coverage from the fixed-coverage P&L table at eval time (the family says 1–2%),
have eval write the per-checkpoint confidence threshold that realizes it into the checkpoint
meta, and have `serve.py` read that. A global `GATE_THRESHOLD` constant is not a
well-defined operating point across checkpoints and never was.

### 1.6 🔴 The model still sees six real numbers per bar — the last large lever

Unchanged by the O- and P-waves, and now the *only* remaining suspect: resolution (§1.4),
context length and architecture (§5) are all closed. `FEATURE_COLS` has 19 entries, but
every recent log's `WARNING [norm] train fit[...]` block says **12 of 19 are CONSTANT in
the train window** and are correctly zeroed (13 for 1000PEPE, which also loses
`has_funding_oi`). What actually carries signal in every run of both waves — F4, O2, O3, both P0 seeds and P2:

| live | dead in the train window |
|---|---|
| `ret_1`, `hl_range`, `oc_range`, `log_vol`, `ret_std_15`, `funding` (+ `has_funding_oi` mask) | `spread_bps`, `imbalance`, `micro_mid`, `bid_ask_vol_ratio`, `depth_near_imb`, `trade_count`, `buy_sell_imb`, `trade_vol`, `oi`, `oi_chg`, `has_book`, `has_trades` |

Six signal columns — four single-bar OHLCV derivatives, one 15-bar rolling vol, and the
funding rate. No multi-timescale returns, no multi-scale volatility, no cross-pair or
market-wide context, no trend. `funding` is correctly aligned
(`FUNDING_OI_MAX_AGE_MIN=480` = 8h matches the funding interval), so it is not silently
zeroed.

§1.4 sharpens this from both ends: the model is starved **per timestep**, not per window
*and* not per bar-interval. It converted 15m→5m into real edge and then saturated, which is
what an input-limited model looks like.

🔴 **The 12 dead columns are dead for a structural reason, and it constrains what can be
added.** They are not broken — they are constant because the train window opens 2022-08-19
while the book / trade / OI feeds open 2026-07. Any new microstructure column would be
constant in the train window too, and `NORM_DEGENERATE_MODE=zero` would zero it. **Every
column added in Q3 must be candle-derived**, and no book-feature work is worth doing until
the book history is months long (§2, O5 demoted).

### 1.7 Data status (verified on the VM, 2026-08-18; exercised at 1m/5m by the P-wave)

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
DONE.** It also makes the 12-pair run genuinely cheap: ADA/AVAX/LINK/XRP have full 4-year
history at every interval.

**The P-wave exercised every interval and found no data problems.** P2 loaded 14.5M samples
at 1m (the 2026-08-19 plan predicted 8–9M and was low by ~60% — budget 1m runs accordingly
if they ever come back). The 5m seeds loaded ~2.90M each. One thing to keep in view:
**the val split moves between runs** because collection is continuous — the three 5m seeds
start val at 2025-12-09 09:45, 12-10 01:40 and 12-10 11:35. It is a few hours on an
8-month window and did not matter here, but any run intended as a *matched* comparison
(Q3 against §1.3) should record its split and, if the drift ever exceeds a few days, pin
the dataset instead.

Microstructure, unchanged from 2026-08-17 (re-verify before any book run):

| source | coverage |
|---|---|
| `orderbook_snapshots` | BTC/ETH/SOL **31d** (from 2026-07-17 21:13) · DOGE/HYPE/WLD ~28d · ZEC 24d · 1000PEPE ~22d · ADA/AVAX/LINK/XRP ~4d. Cadence ~1/10s, staleness <45s. |
| `orderbook_levels` (raw L2) | 8 main pairs ~14d (from 2026-08-05), 100 bid + 100 ask levels, zero integrity errors |
| `market_trades`, `open_interest` | mirror snapshots |
| `funding_rates` | 2y9mo–3y11mo — the only microstructure source with real history, and the only one that is a live feature |
| `liquidations` | **0 rows** — WS egress blocked from datacenters. Dropped from all plans. |

**60-day book milestone for BTC/ETH/SOL: ≈2026-09-15.**

All O- and P-wave runs loaded candle counts consistent with the audit, and P2 exercised the
1m interval end to end without a data complaint, so **every interval the audit covers has
now been validated by a training run.** Re-verify only if a backfill lands.

---

## §2 — THE RUN QUEUE

The P-wave banked the 5m result (P0) and closed the resolution ladder (P2). **All of the
Q-wave's code shipped on 2026-08-21** (C12, C13, C14 — §6), so every item below is
runnable now. Suggested order, given training runs are strictly serial (§7):

| item | what | cost | needs a GPU? |
|---|---|---|---|
| **Q0** | derive seed 2's gate, then promote it | ~1h CPU + a promote | no |
| **Q3** | the 30-column feature run — **the experiment** | ~3h GPU | **yes** |
| **Q2** | 3-seed ensemble eval | ~1h CPU | no |
| **Q1** | regime analysis on the three dumps | local, free | no |

Q3 is the only GPU job, so start it first and do Q0 / Q2 / Q1 while it runs — but note
Q0 and Q2 are both `gcp_train.sh` jobs and therefore **cannot overlap Q3 or each other**
(§7: one training VM, and a second launch can delete the first). Q1 is the only item that
is genuinely parallel.

**None of the P-wave commands should be re-launched.** P0 is banked, P2's lever is closed
(§5). Do not run any further seed of the 5m baseline — three is enough, and a fourth buys
0.0006 of SEM.

### The promote hazard — ✅ fixed by C13, but read this once

`checkpoints/latest.pt` is still **P2's checkpoint** — the broken-calibration 1m model
(§1.4) — because P2 finished last, and every training run still overwrites that key.
What changed is that `gcp_promote.sh` can no longer ship it by accident: `--checkpoint`
is required and the bare form refuses. Two things to keep in mind anyway:

- **Naming `latest` is still naming P2** until a newer run lands. Use an explicit key.
- **Every existing checkpoint predates C13**, so none carries a `served_gate` and each
  will serve at the config fallback unless you pass one. Q0 covers this.

### Q0 — ✅ C13 SHIPPED (2026-08-21). Promotion is now safe; do the promote.

The code is in (§6). What remains is the operational step, and it needs one eval first:
**the three P0/O2 checkpoints predate C13, so none of them carries a `served_gate`.**
Serving one today logs `gate_source=config-fallback` and trades at 0.58 — the operating
point §1.5 shows loses money in 3 of 3 seeds. So:

```sh
# 1. give the chosen checkpoint its own measured gate (CPU, ~1h, writes nothing to latest.pt)
./scripts/gcp_train.sh --eval-only m2_multi_20260819T142759Z_a186182b.pt
./scripts/gcp_status.sh
./scripts/gcp_logs.sh > logs/Q0-seed2-gate.log
```

⚠️ `--eval-only` **never writes a checkpoint back to the bucket** (C7's guarantee), so this
run derives and *prints* the gate but does not persist it. Read `SERVED GATE` from the log
and promote with the gate set explicitly until a post-C13 training run produces a
checkpoint that carries its own:

```sh
./scripts/gcp_promote.sh --list
ML_GATE_THRESHOLD=<the conf_threshold from the log> \
  ./scripts/gcp_promote.sh --checkpoint m2_multi_20260819T142759Z_a186182b.pt
```

Check the `/health` line the promote prints: `gate_source` must be `env-override` (with the
threshold you set) or `checkpoint` — **never `config-fallback`**.

**Which checkpoint:** promote **seed 2**
(`m2_multi_20260819T142759Z_a186182b.pt`). It is the most internally consistent of the
three — balanced side split (0.567 / 0.561), monotone fixed-coverage P&L that is positive
at taker down to cov 0.05, and a profitable serial gate. Seed 1 has the prettiest headline
and a cov-0.05 hole; seed 3's short side is a coin flip. If Q2 lands first, promote the
ensemble instead.

### Q1 — regime analysis on the three 5m dumps (local, free, no VM). Runnable now.

Carried over from P1, which never ran, and **its inputs changed**: use all three 5m seed
dumps, not O2's alone, because §1.2 is precisely where one seed misled us.

```
gs://fluxtrader-train-artifacts/eval/20260818T185438Z/eval_preds.parquet   # seed 1 (O2)
gs://fluxtrader-train-artifacts/eval/20260819T142759Z/eval_preds.parquet   # seed 2
gs://fluxtrader-train-artifacts/eval/20260820T025723Z/eval_preds.parquet   # seed 3
```

For each val bar compute candidate regime observables from candles already in the DB, all
lookahead-free:

- realized vol of the pooled universe over trailing 1d / 7d / 30d
- BTC trailing return over 1d / 7d, and its sign
- cross-sectional dispersion of trailing 4h returns across the 8 pairs
- cross-pair correlation of trailing 1d returns (one "everything moves together" scalar)
- funding level and funding sign, pooled and per pair
- the model's own mean confidence over a trailing 1d window

Three questions, in order:

1. **Separation.** AUC of each observable against "bar is in a high-edge window", computed
   **per seed**. Report the three AUCs side by side; an observable that separates for one
   seed and not the other two is noise and must be discarded.
2. **Conditional lift.** Bucket val bars into quintiles by each observable; report cov05 LB
   *and* gross bps/trade per bucket, **pooled across the three seeds** (pool the trades, do
   not average the bps). The number that matters is the top bucket's gross bps/trade against
   5bps maker and 14bps taker.
3. **Window 1 specifically.** §1.2's one sharp finding is that all three 5m models find edge
   in 2025-12 → 2026-02 where every 15m model is at coin flip. Ask what is different about
   that window — if an observable flags it, that observable is a feature.

**Verdict:**
- An observable with ≥0.60 AUC **in all three seeds** whose top bucket shows gross ≫ 5bps →
  it is both a Q3 feature column and an M3 regime observable. (The *gating* decision is
  M3's; M2's job is to emit the observable, not act on it.)
- Nothing separates consistently → the window structure is capacity, not state. Skip regime
  features entirely and give Q3's whole column budget to §1.6's per-timestep features.

**Bring back:** the three-seed AUC table, the pooled per-quintile gross-bps table, and the
window-1 finding.

### Q2 — ✅ code shipped. 3-seed ensemble eval (one CPU eval-only run, ~1h). Cheap, high EV.

New, and it falls directly out of §0.3 being the project's dominant problem. Three
checkpoints of one configuration exist and their disagreement *is* the noise we keep
fighting. Averaging their per-bar `p_up` costs one CPU eval and typically buys both a
tighter estimate and better calibration — and M2's deliverable to M3 is exactly a
calibrated probability.

**C14 is shipped** (§6) — `--eval-only` takes a comma-separated list and averages the
members' probabilities. Run:

```sh
./scripts/gcp_train.sh --eval-only \
  m2_multi_20260818T185438Z_8c4b2a03.pt,m2_multi_20260819T142759Z_a186182b.pt,m2_multi_20260820T025723Z_a186182b.pt
./scripts/gcp_status.sh
./scripts/gcp_logs.sh > logs/Q2-ensemble.log
```

Note the three training runs each derived a slightly different val split (data keeps
landing: val starts 2025-12-09 09:45 / 12-10 01:40 / 12-10 11:35). That does **not** affect
this run — a single eval-only job scores all three checkpoints on one current split.

**Verdict:** compare the ensemble's fixed-coverage P&L and brier against §1.3's pooled
table and against each member. Better on both → the ensemble is what gets promoted and what
M3 consumes. Better on brier but not P&L → still promote it; calibration is the deliverable.
No better than the best member → drop the idea, promote seed 2, and note it in §5.

### Q3 — ✅ code shipped (C12). Per-timestep feature expansion. **The main event — launch it.**

**This is the only large lever left.** §1.6 (six live columns per bar), §1.4-of-the-O-wave
(context length is closed) and §1.4 here (resolution is closed) all converge on it: the
model is starved *per timestep*, and the one time we gave it more input per unit time it
converted that into edge.

🔴 **Every new column must be candle-derived.** This is not a preference, it is forced by
the same mechanism that kills 12 of the current 19 columns: the train window starts
2022-08-19 and the book/trade/OI feeds start 2026-07, so **any microstructure column is
CONSTANT in the train window and gets zeroed** (`NORM_DEGENERATE_MODE=zero`). Adding book
features to this run would add zeros. That is also why O5 is demoted below.

Candidate columns, all computable from candles that span the full history for every pair:

- trailing returns at 1h / 4h / 1d — multi-timescale return is currently absent entirely
- rolling volatility at 2–3 scales beyond the single `ret_std_15`
- BTC-relative return and rolling beta per pair
- cross-sectional return rank and dispersion across the universe
- whichever observables Q1 finds separate **in all three seeds**

**Shipped as `FEATURE_DIM` 19 → 30** (C12, §6). The column list was frozen without waiting
for Q1: the four groups above were decided by §1.6 regardless of what Q1 finds, and Q1's
contribution was only ever *additional* columns. If Q1 turns up an observable that
separates in all three seeds, it is a second, later bump — not a reason to hold this run.

One variable — the feature set — against the §1.3 baseline: `CANDLE_INTERVAL=5m`,
`seq 384`, `PAIR_EMBED_DIM=8`, `EARLY_STOP_PATIENCE=20`, same 8 pairs, horizons
60/240/1440, primary 240, **`SEED=1`**.

```sh
CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 \
  EARLY_STOP_PATIENCE=20 SEED=1 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 384
```

**Verify** (§0.4 has the full list; these are the C12-specific ones):
`Feature columns: 30`; `[market] cross-pair context filled for 8/8 pairs` with
`mean has_market` ≈ 1.0; the `WARNING [norm]` block reports **13/30 CONSTANT for BTC and
12/30 for the rest** — if a *new* column beyond `has_market` (and `btc_rel_ret_1h` on BTC
alone) lands in that list, the run tested less than it looks; `knob CANDLE_INTERVAL=5m`;
`Samples:` ≈ 2.9M; `P&L sim: … hold=48 bars`; split re-recorded. This run's checkpoint
will be the **first one carrying its own `served_gate`**, so it is also the first that is
promotable without an override.

**Verdict, pre-registered.** Rank on mean-of-epochs cov05 LB against the family's
**0.5219 ± 0.0014** (same bar interval, so LB is fine here — §0.6 does not bite) and on
pooled gross bps/trade at cov 0.01–0.02 against **+19.4 / +22.0**:

- **≥ 0.535 mean LB** (≈ +0.013, comparable to the 15m→5m gain) → features are the live
  lever; replicate at two more seeds and expand the column set again.
- **0.525–0.535** → real but small; bank it and go once more with a wider column set.
- **≤ 0.525** → the per-timestep story is wrong too, and M2's supervised ceiling on candle
  data is roughly where it is. That is a genuine milestone conclusion: stop tuning M2, ship
  the ensemble to M3, and let the policy do the work M2 cannot.

### After this wave

Read Q1 + Q2 + Q3 together in a **fresh session**. Still queued, re-prioritized by the
P-wave:

- **O6 — magnitude-weighted directional loss** (code task C3). Promoted to *next after Q3*.
  It is the one remaining idea that attacks the failure §7's cost arithmetic describes — the
  model is systematically right on smaller-than-average moves — and it does so at train time
  with per-sample weights over 2.3M bars, not over a ~600-effective-sample validation
  statistic (which is why N3's selection-time cousin failed). Cheap, one variable, one run.
- **O8 — 12 pairs.** Cheap (§1.7): ADA/AVAX/LINK/XRP have full 4-year history at 5m. One
  variable, one run. Worth doing after Q3 so it tests the *final* feature set.
- **O7 — triple-barrier redo.** Blocked on C4b (barrier-aware `simulate_pnl`), wider
  barriers (target ~30–40% flat), and a pinned dataset.
- **O5 — L2 ladder feature audit (read-only, NO training). Demoted.** The analysis is still
  correct — `orderbook_levels` has ~14d × 100 levels with no integrity errors, the five book
  features are static snapshot levels with no OFI/flow dynamics, and `_align_with_age`
  discards ~5 of every 6 snapshots at 5m bars. But Q3's constraint applies to it with full
  force: **book-derived columns are constant across 99% of the train window and get zeroed**,
  so no amount of feature cleverness helps until either the book history is measured in
  months or the training window is deliberately shortened to the book era (which throws away
  the 3+ years that make the model work). Revisit when book coverage passes ~6 months —
  the 60-day milestone for BTC/ETH/SOL is ≈2026-09-15, so this is a 2027 item, not a now item.

## §3 — WHAT TO BRING BACK (for the next session)

Save each run's full log under `logs/` **named after the queue item** (`Q3.log`, not
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
L=logs/Q3.log                              # repeat for each run in the wave
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
   P2 is the cautionary example: highest LB in the ledger, flat `dir_acc`, worse economics.
3c. **`brier` on the 240m head, and the calibration bin table.** New with the P-wave — P2
   posted respectable `dir_acc` with a probability output that was pure noise as a
   probability (`emp_up ≈ 0.48` in every bin). M2's deliverable to M3 is a *calibrated*
   probability, so a run that improves ranking while destroying calibration has not
   improved. Reject any run whose bin table is flat in `emp_up`.
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
| **5m/seq384 family** — **O2** `20260818T185438Z` (s1) · **P0-seed2** `20260819T142759Z` · **P0-seed3** `20260820T025723Z` | **5m bars, seq 384 (32h), ~2.90M samples, 3 seeds** | 240m | **pooled mean-of-epochs 0.5219 (between-seed SEM 0.0014)** | ✅ **BANKED — the baseline** | The project's first replicated result. +0.016 ≈ 4σ over F4. Pooled fixed-coverage P&L **+19.4 / +22.0 gross bps/trade at cov 0.01 / 0.02** (1,081 / 1,783 trades) = +5.4 / +8.0 net at 14bps taker. Per-seed max LB 0.5565 / 0.5576 / 0.5425 — all order statistics, do not quote. Did **not** replicate: serial-sim magnitude (§1.5), side balance, book-era split, per-pair numbers. Served gate must become a coverage target (C13). §1.3 |
| **P2** `20260820T100042Z` | **1m bars, seq 768 (12.8h)** — the next resolution rung | 240m | 0.5579 (mean 0.5256±0.015, n=38) — **LB is inflated, do not rank on it** | ✅ **decisive, negative** | Highest LB in the ledger on 5× the val rows, and flat where it counts: `dir_acc` cov05 **0.561 vs the 5m family's 0.559**; gross bps/trade +2.6/+8.5 at cov 0.01/0.02 vs +19.4/+22.0; **brier 0.323 vs 0.250 with `emp_up ≈ 0.48` in every probability bin** — calibration destroyed; 20h wall clock vs 2.5–3h. **Resolution ladder closed at 5m.** §1.4 |
| **O3** `20260819T021020Z` | 15m bars, **seq 256 (64h)** — context length | 240m | 0.531 (mean 0.4925±0.023, n=24) | ✅ **decisive, negative** | Worse than F4 on mean-of-epochs; per-epoch series drifts monotonically down; served-gate coverage collapsed 4.9%→0.8%; up side at 0.499. Longer context is dead and **architecture is closed again**. §1.4 |
| **O0** `eval-only re-score of F4` | F4 on today's eval code, CPU | 240m | 0.531 (reproduced exactly) | ✅ | Delivered F4's missing `Fixed-coverage P&L`: +2.61 / +6.53 / +6.50 / −2.96 / −4.38 gross bps at cov .01/.02/.05/.10/.20. Closes N3-vs-F4 — N3's +4.24 @cov05 is inside noise of F4's +6.50. |
| **F4** `20260817T221811Z` | 15m bars, seq 128, horizon ladder | 240m | 0.531 (mean 0.506±0.016, n=18) | ✅ **prior baseline, superseded by the 5m family** | 4h is the horizon peak. Best cell +6.5 gross bps/trade ≈ maker break-even, never positive at taker. WF .486/.617/.457/.584. C2 table now supplied by O0. |
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
| Full architecture swap (transformer / TCN) | **Closed (2026-08-19)** | Was gated behind O3; O3 came back negative. **Do not write a transformer.** Reopen only if Q3's richer per-timestep features saturate and the residual failure looks like a modelling limit rather than an input limit. |
| Confidence calibration / temperature / focal loss | **Closed** | F4's head is *over*-confident (`[0.60,0.70)` bin mean_pred 0.636 vs empirical 0.547; N3's is 0.609 vs 0.521). Sharpening an over-confident head is the wrong direction. |
| Raising `GATE_THRESHOLD` as an experiment | **Superseded by C1+C2** | The served gate is 0.58 and eval now reports there. Derive the operating point from the fixed-coverage P&L table, not from another sweep. |
| Quantile head | **Deferred** | Regressed direction ~0.014; band coverage unstable. Revisit at M3, detached. |
| `liquidations` feed | **Dropped** | 0 rows; Binance gates WS market data from datacenter egress (verified from 3 hosts). |
| More candle *history* | **Closed** | Adds more of the pre-book regime we already fit. Note this is about *history*, not *resolution*. |
| **Bar resolution — 15m → 5m** | **🟢 BANKED and frozen (2026-08-21)** | Replicated across three seeds: pooled mean-of-epochs 0.5219 ± 0.0014 vs F4's 0.5058, and pooled +22 gross bps/trade at the top 2% (§1.3). `5m / seq 384` is the permanent baseline. Nothing further to test here — do not run a fourth seed. |
| **Bar resolution — finer than 5m** | **Closed (new, 2026-08-21)** | P2 ran 1m/seq768 as a direction probe: flat `dir_acc` (0.561 vs 0.559), materially worse economics, **destroyed calibration** (`emp_up ≈ 0.48` in every bin, brier 0.323 vs 0.250), 20h wall clock. The ladder has one rung and we are standing on it. The untested variant (1m at a 32h window, seq 1920) is unaffordable and context length is separately closed. §1.4 |
| **Absolute `GATE_THRESHOLD` as a serving constant** | **Closed (new, 2026-08-21)** | Not a lever, a defect. The same probability is 1.2% / 2.5% / 1.7% coverage across three seeds of one configuration and 80% on P2 (§1.5). The gate must be a per-checkpoint coverage target chosen from the fixed-coverage P&L table. C13. |
| **"Flat training loss proves nothing" — and now "one seed proves nothing"** | **Reinforced (2026-08-21)** | Of the four claims the O-wave made from one seed, three did not survive replication (§1.2, §1.5). Any result quoted from a single run is provisional until a second seed agrees. |
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

### The C-batch — DONE 2026-08-21 (the Q-wave code, committed together)

- ✅ **C13 — safe promotion + a coverage-targeted served gate.** This was Q0.
  1. `gcp_promote.sh --checkpoint <key>` is now **required**; the bare form refuses and
     prints the promotable keys. Accepts a bare filename, `checkpoints/<name>.pt`, a
     `gs://` URL, or the literal `latest`. It also pins serve code to the commit
     encoded in the checkpoint's own filename (`m2_multi_<run>_<sha8>.pt`) rather than
     the ambient `GIT_REF`, so a named historical checkpoint is served by the code
     that wrote it. `--list` shows what is promotable.
  2. **The gate is a coverage target, not a probability.** `SERVE_TARGET_COVERAGE`
     (config, default **0.02**, in `FLUX_TRAIN_ENV_KEYS`) says what fraction of bars
     should trade. `eval_m2.py` measures the confidence threshold that realizes it on
     the val window, prints a `SERVED GATE (C13, coverage-targeted)` block with the
     realized dir_acc and gross/net bps, and **writes `meta.served_gate` into the
     checkpoint file**. Because the runner evals before uploading, a training run now
     ships a checkpoint carrying its own operating point. Every `*` marker, serve-gate
     row, long/short split and per-pair line in the log follows that derived gate
     instead of the config constant.
  3. `serve.py` reads `meta.served_gate`. Precedence: explicit env override >
     checkpoint > config default, each logged, and `/health` + every prediction now
     report `gate_source` (`checkpoint` / `config-fallback` / `env-override`) and
     `gate_target_coverage`.
  4. ⚠️ **`docker-compose.yml` no longer defaults `GATE_THRESHOLD`.** It was
     `${ML_GATE_THRESHOLD:-0.58}`, which as an override would have defeated all of the
     above on every deploy — trap §0.5.2 in a new costume. It is now
     `${ML_GATE_THRESHOLD:-}`, and an empty value means "use the checkpoint".
     The Elixir side already prefers serve's `gate_threshold` over its own env, so it
     follows automatically.
- ✅ **C14 — multi-checkpoint ensemble eval.** `--eval-only` (and `eval_m2.py
  --checkpoint`) take a comma-separated list. Members are averaged on **probabilities**,
  not logits — each member's softmax is averaged and stored back as log-probabilities,
  so every downstream table sees exactly the mean probability and calibration means what
  it says. Members must agree on candle interval, seq_len, feature_dim, the feature
  column list, horizons and primary; a mismatch **exits 2** with a diff rather than
  averaging two different experiments. Architecture differences only warn. The norm
  range report runs for every member, so `BROKEN SCALE` still guards each one. An
  ensemble's derived gate is reported but deliberately **not** written into any member.
- ✅ **C12 — `FEATURE_DIM` 19 → 30.** Eleven new columns, all candle-derived (§1.6
  explains why nothing microstructure-shaped can be added yet):
  - own-pair multi-scale: `ret_1h`, `ret_4h`, `ret_1d`, `vol_1h`, `vol_4h`, `vol_1d`
  - market context: `btc_rel_ret_1h`, `beta_btc_1d`, `xs_rank_1h`, `xs_disp_1h`,
    `has_market`
  - Windows are in **minutes** and converted per candle interval, so `ret_1d` is a day
    at 1m, 5m and 15m rather than a different span at each.
  - **Old checkpoints still work.** `FEATURE_COLS[:19]` is frozen as
    `LEGACY_FEATURE_COLS`, new columns are appended after the masks, and train records
    `meta.feature_cols`. eval/serve rebuild the checkpoint's own list, falling back to
    the legacy prefix for pre-C12 checkpoints. Verified byte-identical.
  - The cross-pair columns are computed in a **second pass** over all pairs (a ragged
    timestamp join, since pairs list on different dates), then patched into the
    existing float32 matrices, so peak memory is unchanged. Serving needs the same
    context, so it loads the universe through a candles-only path cached for
    `MARKET_CACHE_TTL_S` (default 30s). Train-vs-serve parity was verified exact
    (max |train − serve| = 0 on all five columns), and a failed context degrades to
    zeros with `has_market=0` rather than refusing to serve.

### Later

- ⬜ **C3 — magnitude-weighted directional loss.** Weight the aux up/down CE by `|r_T|`.
  Gate behind a config flag defaulting to off. Feeds **O6**, which the P-wave promoted to
  next-after-Q3 (§2).
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
| Eval only (no training) | `./scripts/gcp_train.sh --eval-only <key>[,<key>,…]` (several = ensemble) | `./scripts/gcp_status.sh` | `./scripts/gcp_logs.sh <run_id> > logs/X.log` + `gs://…/eval/<run_id>/` | `fluxtrader-train` |
| Walk-forward | `./scripts/gcp_walkforward.sh` | `--status` | `--fetch` | `fluxtrader-walkforward` |
| GBT diagnostic | `./scripts/gcp_gbt.sh` | `--status` | `--fetch` / `--log` | `fluxtrader-gbt` |
| Single-window ablate | `./scripts/gcp_ablate.sh` | — | — | own VM |
| Feature audit | `./scripts/gcp_audit.sh` | — | — | own VM |
| Data stats | `./scripts/gcp_data_collection_stats.sh` | — | — | always-on |
| Promote | `./scripts/gcp_promote.sh --checkpoint <key>` (`--list` to see keys) | — | — | always-on |

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
overwrites that key. **`latest.pt` is currently P2's checkpoint — the 1m model whose
probability output is uncalibrated noise (§1.4) — and must not be promoted.** The
checkpoints you may actually want:

| run | key |
|---|---|
| **seed 2 — promote this one** (§2, Q0) | `checkpoints/m2_multi_20260819T142759Z_a186182b.pt` |
| seed 1 (O2) | `checkpoints/m2_multi_20260818T185438Z_8c4b2a03.pt` |
| seed 3 | `checkpoints/m2_multi_20260820T025723Z_a186182b.pt` |
| F4 (prior baseline) | `checkpoints/m2_multi_20260817T221811Z_94614795.pt` |
| O3 (do not promote) | `checkpoints/m2_multi_20260819T021020Z_8c4b2a03.pt` |
| **P2 (do not promote)** | `checkpoints/m2_multi_20260820T100042Z_a186182b.pt` = `latest.pt` |

**C13 shipped (2026-08-21)**, so `gcp_promote.sh` now requires `--checkpoint <key>` and
refuses the bare form; `--list` prints the table above from the bucket. It also pins serve
code to the sha in the checkpoint's filename. Remember that every key listed here predates
C13 and therefore carries no `served_gate`: promoting one without an override serves it at
the config fallback of 0.58, which §1.5 shows loses money in all three seeds. Q0 in §2 is
the two-step fix.

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
GATE_THRESHOLD SERVE_TARGET_COVERAGE
FEE_RATE_BPS SLIPPAGE_BPS MAKER_FEE_RATE_BPS MAKER_SLIPPAGE_BPS
```

`EARLY_STOP_PATIENCE` and `SEED` were added by C8 (2026-08-18); `SERVE_TARGET_COVERAGE` by C13 (2026-08-21).

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

Worth keeping in view — **this paragraph was rewritten by the P-wave and is now measured on
three seeds.** Through F4 the only positive cells in the project appeared at maker cost
(F4's best: +6.5 gross, +1.5 net at maker, −7.5 at taker), which made execution work the
single largest sign-flipping lever available. The 5m family's pooled top-2% slice is
**+22.0 gross bps/trade over 1,783 trades — +17.0 net at maker, +8.0 net at taker** (§1.3),
so the signal now clears full taker cost at ~1.5σ and maker cost comfortably. Execution work
is still worth ~9 bps/trade and is still not an ML change, and it is M3's problem regardless.
Do not let it block the model queue. What the replication also says: the *serial* P&L
magnitude was seed luck (§1.5), so size any downstream expectation off the fixed-coverage
table, never off a single run's `net_ret` line.

### Where things live

- Checkpoints: `gs://fluxtrader-train-artifacts/checkpoints/` (+ `latest.pt`)
- Logs: `gs://fluxtrader-train-artifacts/logs/<RUN_ID>.log`
- Walk-forward compares: `…/walkforward/<run_id>.compare.txt`
- GBT reports: `…/gbt/<run_id>.json`
- Status markers: `…/status/latest.json`

### Related docs

- `docs/archive/TRAINING_HISTORY.md` — the full session narrative, 2026-07-23 → 2026-08-21,
  including the O-wave as written before seed replication corrected three of its claims.
- `docs/DATA_COLLECTION_AUDIT.md` — what the collector captures vs silently drops.
- `docs/QUANT_AB_HANDOFF.md` — quantile-head A/B and its deferral.
- `MODEL.md` — architecture contract; §4.3 labels, §4.4 architecture options.
- `AGENTS.md` — Docker-only workflow, data-lives-on-the-VM rule.
