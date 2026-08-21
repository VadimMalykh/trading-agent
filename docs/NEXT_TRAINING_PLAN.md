# Training plan — what is true, what to run next

**Last updated: 2026-08-22** (after the Q-wave: Q0 gate derivation, Q1 regime analysis,
Q2 ensemble, Q3 feature expansion).

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
§1.1 (one paragraph on where we are) → §2's R0 (a 5-minute promote) → §2's R1 (the
next experiment) →
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

🔴 **Refinement, new 2026-08-22 (Q3): the all-epoch mean is only comparable between runs
whose overfitting starts at the same time.** Every 19-column run sits on a long plateau
(`loss_tr` ≈ 1.72, `loss_va` ≈ 1.041) for 21–26 epochs and *all* of its edge lives there;
Q3's 30-column run left that plateau at epoch 5, so its 28-epoch mean averages 5 plateau
epochs against 23 degraded ones while the baseline's averages ~24 against ~10. **Report the
mean restricted to plateau epochs** — those whose `loss_va` is within 0.02 of the run's
minimum — alongside the all-epoch mean, and treat a plateau shorter than ~15 epochs as a
sign the arms are not comparable at all (§1.6). Compute both from any log with:

```sh
grep -oE 'epoch [0-9]+  loss_tr=[0-9.]+ loss_va=[0-9.]+.*lb=[0-9.]+' logs/X.log | \
  sed -E 's/epoch 0*([0-9]+)  loss_tr=([0-9.]+) loss_va=([0-9.]+).*lb=([0-9.]+).*/\1 \2 \3 \4/' | \
  awk '{e[NR]=$1;va[NR]=$3;lb[NR]=$4;n=NR}
  END{m=99;for(i=1;i<=n;i++)if(va[i]<m)m=va[i];t=m+0.02;
      for(i=1;i<=n;i++){s+=lb[i]; if(va[i]<=t){np++;sp+=lb[i];last=e[i]}}
      printf "all: n=%d mean=%.4f | plateau: n=%d lastEp=%d mean=%.4f\n",n,s/n,np,last,sp/np}'
```

The plateau means for the baseline family are **0.5235 / 0.5273 / 0.5209 (pooled 0.5239)**
— that is the number R1 must beat, not 0.5219.

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
`13/30 CONSTANT` for BTC and `12/30` for the others, not the old 12/19. **Q3 measured
`13/30` for BTC *and* for every other pair, and `14/30` for 1000PEPE** — `has_market` is
constant for the non-BTC pairs while `btc_rel_ret_1h` is constant for BTC, so each pair
loses one column, just not the same one. That is expected. What is *not* expected, and is a
defect, is `beta_btc_1d` escaping this list on the BTC row despite being identically 1
there (§6 C15).

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

## §1 — WHERE WE ARE (2026-08-22)

### 1.1 The one-paragraph summary

**The 5m/seq384 3-seed baseline is still the model, the feature expansion failed, and the
one thing the Q-wave found worth building on belongs to M3, not M2.** Q3 gave the model 30
columns instead of 19 and came back at mean-of-epochs cov05 LB **0.5003** against the
family's **0.5219 ± 0.0014**, with an *inverted* calibration table — a rejection on two
independent pre-registered criteria. But the diagnostic (§1.6) says the run was
mis-specified rather than that the lever is dead: the extra columns did not add signal,
they added *fitting speed*. The baseline sits on a 21–26 epoch plateau where all of its
edge lives; Q3 left that plateau at **epoch 5** and its selected checkpoint is already
outside it. Q2 tested the 3-seed ensemble against seed 2 on a matched split and it is not
better — +0.002 dir_acc and −0.0005 brier are noise, and it is worse on gross bps at four
of five coverages — so the pre-registered verdict fires: **drop the ensemble, promote seed
2** (§2 R0; Q0 measured its gate at 0.6311). Q1 is the wave's positive result: of nine
candidate regime observables, exactly one separates consistently across all three seeds —
**BTC's trailing-24h absolute return**. Its top quintile (|ret| ≥ 4.31%, 5.2% of bars)
holds trades worth **+35.5 gross bps/trade at cov 0.05 and +54.9 at cov 0.02**, against
+8.8 / +22.0 overall, with close per-seed agreement (+34.8 / +32.5 / +38.7). That is a
*when to be in the market* observable, which M3 owns — M2's job is to emit it, not to act
on it (§1.8). The next GPU run (R1) retests the well-conditioned half of the feature set;
two of C12's eleven columns are numerically defective and must be fixed first (§6 C15).

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

### 1.4 Resolution is closed at 5m — the surviving statement

P2 ran 1m/seq768 as the next rung and came back flat-to-worse on every axis that matters:
`dir_acc` at cov05 **0.561 against the 5m family's 0.559**, gross bps/trade at cov 0.01 /
0.02 of **+2.6 / +8.5** against **+19.4 / +22.0**, **brier 0.323 vs 0.250** with
`emp_up ≈ 0.48` in every probability bin, and 20h16m of wall clock against 2.5–3h. Its
headline LB (0.5256, the highest in the ledger) is the §0.6 trap: 2.9M val rows narrow the
Wilson interval without adding independent observations.

**Verdict, per the pre-registered rule: 5m is the resolution sweet spot. Frozen (§5).**
The full P2 tables and the untested-variant argument are in
`docs/archive/TRAINING_HISTORY.md`. Read O2 / O3 / P2 together and the shape is settled:
**finer observations helped once, from 15m to 5m, and then stopped; more window never
helped.**

### 1.5 The served gate is a coverage target — shipped, and seed 2's is 0.6311

C13 shipped this and Q0 exercised it. The finding that forced it: the same absolute
confidence threshold is 1.2% / 2.5% / 1.7% coverage across three seeds of one
configuration, 0.8% on O3 and 80% on P2, so **a global `GATE_THRESHOLD` constant is not a
well-defined operating point across checkpoints and never was** (§5). `eval_m2.py` now
measures the threshold realizing `SERVE_TARGET_COVERAGE` (default 0.02) and writes it into
the checkpoint; `serve.py` reads it and reports `gate_source`.

**Seed 2's measured gate is `conf >= 0.6311`**, realizing dir_acc 0.578, +18.68 gross
bps/trade, **+4.68 net at 14bps taker** (`logs/Q0.log`). ⚠️ `--eval-only` never pushes a
checkpoint, so that gate lives only in the log — the bucket copy still carries none, and
the promote must pass it explicitly (§2 R0).

### 1.6 🔴 The feature expansion failed, and the reason is fitting speed, not signal

Q3 was the one-variable test of §1.6-as-it-stood (the model sees six live columns per bar).
It added eleven candle-derived columns — `ret_1h/4h/1d`, `vol_1h/4h/1d`, `btc_rel_ret_1h`,
`beta_btc_1d`, `xs_rank_1h`, `xs_disp_1h`, `has_market` — and lost:

| | 5m family (3 seeds, 19 cols) | Q3 (30 cols) |
|---|---:|---:|
| mean-of-epochs cov05 LB | **0.5219 ± 0.0014** | **0.5003** (n=28) |
| brier (240m, moved bars) | 0.250 | **0.2897** |
| calibration bin table | monotone in `emp_up` | **inverted** (0.495 → 0.465 as `mean_pred` 0.35 → 0.75) |
| ungated 3-class accuracy | 0.472 / 0.473 | 0.4553 |
| gross bps/trade @cov 0.01 / 0.02 | +19.4 / +22.0 | +19.7 / +17.6 |

Two independent pre-registered criteria reject it: LB ≤ 0.525 (§2's Q3 rule) and a
non-monotone `emp_up` (§3 item 3c).

🔴 **But the training trajectory says the run was mis-specified, not that the lever is
dead.** Every baseline run sits on a long plateau — `loss_tr` ≈ 1.72, `loss_va` ≈ 1.041 —
and *every good epoch lives inside it*. Q3 left the plateau at epoch 5:

| run | cols | plateau epochs | `loss_tr` first → last | mean LB, plateau | mean LB, all |
|---|---:|---:|---|---:|---:|
| O2 (s1) | 19 | 24 | 1.7284 → 1.2625 | 0.5235 | 0.5248 |
| P0-seed2 | 19 | 21 | 1.7288 → 1.4043 | 0.5273 | 0.5206 |
| P0-seed3 | 19 | 26 | 1.7286 → 1.2070 | 0.5209 | 0.5203 |
| **Q3** | **30** | **5** | **1.7210 → 1.0971** | **0.5000** | **0.5003** |

(plateau = epochs whose `loss_va` is within 0.02 of that run's minimum.) With 19 columns
the model *cannot* fit the train set — 1.72 flat for 25 epochs. With 30 it fits it, down to
1.10, while `loss_va` climbs monotonically from epoch 5 onward. Q3's selected epoch 8 is
already outside its own plateau, which is exactly why its ranking survives (top-5% dir_acc
0.551) while its probabilities do not. **Nothing in the run's configuration was changed to
absorb a 58% wider input** — same `DROPOUT`, `WEIGHT_DECAY`, `LR`, `HIDDEN_SIZE`.

Note this cuts both ways and neither reading is free: extra columns enable memorization
whether they carry signal or not, so the fast overfit is *not* evidence that the features
are informative — it is only evidence that the test did not measure what it intended to.

🔴 **Two of the eleven columns are numerically defective** (§6 C15), and both are in the
market-context group:

- **`beta_btc_1d` is degenerate for BTCUSDT.** Beta of BTC against itself is identically
  1.0. The column is 1.0 everywhere except a handful of warm-up / sub-floor-variance bars
  set to 0.0, which makes its raw std ~1e-3 — above the `1e-8` CONSTANT detector, so it is
  *not* zeroed — and the per-pair normalizer then turns those few bars into a **590σ**
  spike, winsorized at ±50. BTC's worst tail was 66σ (`hl_range`) before C12. The
  `ok_var = b_var > 1e-12` guard at `ml/train/data/features.py:436` is ~6 orders of
  magnitude below a real `var(ret_1)` (~2.3e-6 at 5m), so it floors nothing in practice.
- **`xs_disp_1h` carries a 122σ tail** and is identical for every pair at a given bar, so
  the same spike enters all eight pairs at once. It became the worst column for ETH, SOL
  and ZEC (was 75 / 81 / 85σ on `hl_range`). Q1 independently ranks cross-sectional
  dispersion the *least* informative of nine observables tested (§1.8) — C12 added the
  dispersion family, which is noise, and omitted the market-move-magnitude family, which
  is the one thing that separates.

The legacy columns are byte-identical between O2 and Q3 (`hl_range` tails 212.8 → 212.9,
363.5 → 363.8), confirming the change is isolated to the new columns.

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

### 1.8 🟢 Q1 — one regime observable separates, and it belongs to M3

Q1 ran locally on the three 5m seed dumps (`eval_preds.parquet` for runs
`20260818T185438Z` / `20260819T142759Z` / `20260820T025723Z`). All observables were built
from the dumps themselves: `fwd_ret` at horizon *h* shifted back *h* minutes is a
lookahead-free trailing return, and the three horizons compound exactly (verified,
max abs diff 3.2e-7), so no DB round-trip was needed. The harness reproduces the published
fixed-coverage tables exactly — O2's cov 0.01/0.02/0.05 gross came back +24.50 / +22.11 /
+3.50 against the logged +24.5 / +22.1 / +3.5 — so these numbers are on the same footing as
§1.3's.

**Test 1 — AUC against "this gated trade was correct", per seed. Nothing passes.** The
pre-registered bar was ≥0.60 in all three seeds; the largest deviation from 0.50 anywhere in
the table is 0.06.

| observable | seed 1 | seed 2 | seed 3 |
|---|---:|---:|---:|
| `btc_absret_1d` | 0.538 | 0.549 | 0.557 |
| `xs_corr_7d` | 0.525 | 0.511 | 0.564 |
| `xs_corr_1d` | 0.523 | 0.525 | 0.563 |
| `rv_30d` | 0.521 | 0.507 | 0.559 |
| `btc_ret_7d` | 0.501 | 0.530 | 0.510 |
| `btc_sign_1d` | 0.492 | 0.502 | 0.489 |
| `xs_disp_4h` | 0.488 | 0.489 | 0.491 |
| `mean_conf_1d` | 0.480 | 0.471 | 0.499 |
| `rv_7d` / `rv_1d` | 0.481 / 0.472 | 0.462 / 0.460 | 0.486 / 0.495 |
| `btc_ret_1d` | 0.469 | 0.469 | 0.449 |

Worth noting in passing: `mean_conf_1d` — the model's own trailing-1d confidence — is
*anti*-predictive in all three seeds. A confident recent stretch is not a good stretch.

**Test 2 — conditional lift, which is the test that matters.** Pooled cov05 trades across
the three seeds (n=3,717; per-trade sd 259bps, so a quintile's SEM is ≈9.5bps), bucketed
into quintiles by each observable, reported as gross bps/trade:

| observable | Q1 | Q2 | Q3 | Q4 | Q5 | per-seed Q5 |
|---|---:|---:|---:|---:|---:|---|
| **`btc_absret_1d`** | −3.4 | −15.3 | +10.1 | +17.4 | **+35.5** | **+35 / +33 / +39** |
| `xs_corr_1d` | −8.6 | −3.7 | +12.5 | +12.7 | +31.5 | +16 / +36 / +46 |
| `xs_corr_7d` | +20.1 | −7.5 | −1.8 | +11.4 | +26.1 | +10 / +36 / +34 |
| `rv_30d` | +26.2 | +15.7 | −11.6 | +4.2 | +25.4 | +11 / +32 / +36 |
| `rv_7d` | +21.9 | +9.3 | +28.6 | −29.0 | +17.5 | +10 / +21 / +21 |
| `btc_ret_1d` | +33.9 | +17.2 | −4.7 | −3.7 | +1.5 | −10 / +21 / −5 |
| `rv_1d` | +7.2 | −4.5 | +38.3 | +1.8 | +1.6 | −7 / +1 / +11 |
| `btc_ret_7d` | −10.7 | +14.4 | +18.1 | +25.7 | +0.4 | +1 / +3 / −2 |
| `xs_disp_4h` | +17.0 | +8.2 | +3.2 | +6.8 | +9.1 | −6 / +22 / +11 |

**`btc_absret_1d` is the only one with a monotone ladder in both bps and `dir_acc`**
(0.517 / 0.494 / 0.545 / 0.579 / **0.618**) *and* close agreement across three independently
seeded models. The others are U-shaped (`xs_corr_7d`, `rv_30d`), seed-unstable
(`xs_corr_1d`: +16/+36/+46), or flat (`xs_disp_4h`, spread 13.9bps — the least informative
of the nine, and the family C12 chose to add).

**The rule, and what it is worth.** BTC trailing-24h |return| ≥ **4.31%**, which is **5.2%
of val bars**:

| slice | trades | gross bps/trade | net @14bps taker | dir_acc |
|---|---:|---:|---:|---:|
| cov 0.05, in-state | 742 | **+35.5** (SEM 10.5) | **+21.5** | 0.618 |
| cov 0.05, all | 3,710 | +8.8 | −5.2 | 0.559 |
| cov 0.02, in-state | 493 | **+54.9** | **+40.9** | — |
| cov 0.02, out-of-state | 1,288 | +9.1 | −4.9 | — |
| cov 0.01, in-state | 339 | **+45.9** | **+31.9** | — |
| cov 0.01, out-of-state | 741 | +7.2 | −6.8 | — |

The lift at cov05 is +26.6bps, ≈2.5σ on the pooled SEM — but the per-seed agreement
(+34.8 / +32.5 / +38.7 on three independent models) is the stronger evidence, and it is the
kind §0.3 asks for. It is direction-free: Q5 on BTC-up days is +36.9 (n=109), on BTC-down
days +35.2 (n=633), so this is about the *magnitude* of the market move, not its sign.

⚠️ **Two honest caveats, both binding.**
1. **It is partly a calendar effect.** 47% of the Q5 trades fall in window 2 and only 2% in
   window 3. Computed *within* calendar windows the ladder holds in three of four — w1 Q5
   +74, w4 Q5 +74, w3 Q5 +103 (n=13, ignore) — but **fails in window 2 (Q5 = −10)**, which
   is where nearly half its trades live. So the rule is not uniformly good; it is very good
   in three windows and bad in the one where it fires most often.
2. **Sharpening past the quintile does not help.** The top *decile* is +27.1bps with
   per-seed +19 / +16 / +45 — worse and less stable than the quintile.

🔴 **Verdict: it is an M3 observable, not an M2 feature, and the distinction is the whole
point of this document's preamble.** "BTC has moved 4%+ in the last day, so trade more
here" is a statement about *when to be in the market and how large* — M3's job. M2 should
**emit** trailing market-move magnitude as an observation and let the policy condition on
it. Do not add a gate to M2 for it; that is the cost-aware-selection mistake (§5) in a new
costume. As an M2 *input* column it is a reasonable candidate for a later feature wave, but
it is not what R1 tests, because R1 has one variable already.

---

## §2 — THE RUN QUEUE

The Q-wave is complete: Q0 and Q2 ran, Q3 came back negative, Q1 is done (§1.8). **Do not
re-launch any Q item.** The R-wave below is what follows. Training runs are strictly serial
(§7), so this is an ordered list and the wall clock is the sum.

| item | what | cost | needs a GPU? |
|---|---|---|---|
| **R0** | promote seed 2 with its measured gate — **do this first, it is 5 minutes** | promote only | no |
| **C15/C18** | fix the defective columns + add the `FEATURE_GROUPS` knob (§6) — **blocks R1** | local, free | no |
| **C16** | `max_dd` is sorted by value, not by date — every logged drawdown is an artifact (§6) | local, free | no |
| **R1** | feature retest, well-conditioned half only — **the experiment** | ~3h GPU | **yes** |
| **R2** | O6 — magnitude-weighted directional loss (needs C3) | ~3h GPU | **yes** |

R0 is unblocked and independent — do it first. C15 and C18 block R1; C16 blocks nothing but
is a two-line fix. R2 is unchanged from the P-wave queue and stays behind R1.

### R0 — promote seed 2. Unblocked, do it now.

Q2 settled which checkpoint: the ensemble is **not** better than its best member (§1.1,
archive), so the pre-registered "drop the idea, promote seed 2" branch fires. Q0 already
measured seed 2's gate, and because `--eval-only` never pushes a checkpoint that gate is
**not** in the bucket copy — it must be passed explicitly.

```sh
./scripts/gcp_promote.sh --list
ML_GATE_THRESHOLD=0.6311 \
  ./scripts/gcp_promote.sh --checkpoint m2_multi_20260819T142759Z_a186182b.pt
```

**Verify on the `/health` line the promote prints:** `gate_source` must be `env-override`
with threshold 0.6311 — **never `config-fallback`**, which serves 0.58 and loses money in
3 of 3 seeds (§1.5). ⚠️ `checkpoints/latest.pt` is still **Q3's** checkpoint now (it
finished last) — the 30-column model with inverted calibration. Never promote `latest`.

### R1 — feature retest, own-pair multi-scale columns only. **The main event.**

**Why this and not "the feature lever is closed".** Q3's pre-registered verdict was
"≤0.525 ⇒ the per-timestep story is wrong too", and taken literally that closes M2. It
should not be taken literally, for three reasons that are all measurements, not opinions:
Q3 left its training plateau at epoch 5 against the baseline's 21–26 and selected a
post-overfit checkpoint (§1.6); two of its eleven columns are numerically defective and one
of those injects a 590σ spike (§6 C15); and Q1 independently shows the column family C12
*did* add (cross-sectional dispersion) is the least informative observable of nine tested,
while the family it *omitted* (market-move magnitude) is the only one that separates
(§1.8). Q3 tested one particular 11-column set at unchanged regularization and it lost.
That is a real result about that set. It is not a result about per-timestep features.

**The one variable: `FEATURE_DIM` 19 → 25, own-pair multi-scale only.** Keep `ret_1h`,
`ret_4h`, `ret_1d`, `vol_1h`, `vol_4h`, `vol_1d`. **Drop all five market-context columns** —
that group contains both defects, `has_market` is a dead constant by construction (§0.4),
and Q1 gives no reason to want dispersion or rank. This is the well-conditioned half and it
is a genuine one-variable test against §1.3.

Blocked on **C15 and C18** (§6) — C18 is what makes the column set selectable at all;
without it there is no way to run a subset except by editing source. Then, everything else
identical to §1.3:

```sh
FEATURE_GROUPS=legacy,multiscale \
  CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 \
  EARLY_STOP_PATIENCE=20 SEED=1 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 384
./scripts/gcp_status.sh
./scripts/gcp_logs.sh > logs/R1.log
```

**Verify** (§0.4 plus these): `Feature columns: 25`; the `WARNING [norm]` block reports
**12/30 → 12/25 CONSTANT** with *no new column* in it (if `vol_1d` or any `ret_*` appears
there, the run tested less than it looks); `max|z|` back under ~100 for BTC/ETH/SOL/ZEC —
if `beta_btc_1d` or `xs_disp_1h` still appears, C15 did not land; `Samples:` ≈ 2.9M;
`hold=48 bars`; split recorded.

**Verdict, pre-registered — and note the metric has changed (§0.3).** Rank on
**mean-of-epochs cov05 LB restricted to plateau epochs** against the family's plateau means
(0.5235 / 0.5273 / 0.5209, pooling to **0.5239**), and report the all-epoch mean alongside
it. Also required: a **monotone `emp_up`** bin table (§3 item 3c) and a **plateau of at
least ~15 epochs** — a run that leaves the plateau before epoch 10 has not been compared
fairly to the baseline, whatever its LB says.

- **≥ 0.537 plateau mean LB, plateau ≥15 epochs, calibration monotone** → features are the
  live lever. Replicate at two more seeds, then add the market-context group back (fixed).
- **0.527–0.537** → real but small; bank it and widen the column set once more.
- **≤ 0.527 with a healthy ≥15-epoch plateau** → this is the clean negative Q3 was supposed
  to be. **Per-timestep candle features are closed**, and the milestone conclusion stands:
  stop tuning M2, ship seed 2 to M3, and let the policy do the work M2 cannot.
- **Plateau still collapses (<10 epochs)** → the result is again uninterpretable and the
  next run is a regularization arm (`DROPOUT` 0.1→0.3 at 25 columns), not another feature
  set. Say so explicitly rather than reading the LB.

### R2 — O6, magnitude-weighted directional loss. Unchanged, still next after R1.

Blocked on **C3** (§6). It attacks the failure §7's cost arithmetic describes — the model is
systematically right on smaller-than-average moves — and it does so with per-sample weights
over 2.3M training bars rather than over a ~600-effective-sample validation statistic, which
is why N3's selection-time cousin failed. Cheap, one variable, one run.

### Still queued behind that

- **O8 — 12 pairs.** Cheap (§1.7): ADA/AVAX/LINK/XRP have full 4-year history at 5m. One
  variable, one run. Do it after R1 so it tests the *final* feature set.
- **O7 — triple-barrier redo.** Blocked on C4b, wider barriers (target ~30–40% flat), and a
  pinned dataset.
- **O5 — L2 ladder feature audit. Still demoted.** Book-derived columns are constant across
  99% of the train window and get zeroed. Revisit when book coverage passes ~6 months; the
  60-day milestone for BTC/ETH/SOL is ≈2026-09-15, so this is a 2027 item.

### For M3, not for M2

§1.8's `btc_absret_1d` finding is an **input to the policy milestone**, not a run in this
queue. When M3 starts, its observation vector should carry trailing market-move magnitude
(BTC |ret| over 24h, or the pooled-universe equivalent) alongside M2's per-horizon
probabilities, because conditioning on it moves the top-2% slice from +22.0 to +54.9 gross
bps/trade. Do **not** implement it as an M2 gate (§1.8, §5).

---

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
grep -n  'Feature columns:' $L              # the count you intended (25 for R1)
grep -nE 'max\|z\|' $L                     # no new column above ~100 sigma (C15)
```

**Also compute the plateau-restricted mean (§0.3)** — with C17 unshipped this is manual, and
since Q3 it is the metric that decides the run:

```sh
grep -oE 'epoch [0-9]+  loss_tr=[0-9.]+ loss_va=[0-9.]+.*lb=[0-9.]+' $L | \
  sed -E 's/epoch 0*([0-9]+)  loss_tr=([0-9.]+) loss_va=([0-9.]+).*lb=([0-9.]+).*/\1 \2 \3 \4/' | \
  awk '{e[NR]=$1;va[NR]=$3;lb[NR]=$4;n=NR}
  END{m=99;for(i=1;i<=n;i++)if(va[i]<m)m=va[i];t=m+0.02;
      for(i=1;i<=n;i++){s+=lb[i]; if(va[i]<=t){np++;sp+=lb[i];last=e[i]}}
      printf "all: n=%d mean=%.4f | plateau: n=%d lastEp=%d mean=%.4f\n",n,s/n,np,last,sp/np}'
```

If a log predates C10 and has no `epoch LB series` line, compute it:

```sh
grep -oE 'epoch [0-9]+.*lb=[0-9.]+' $L | grep -oE 'lb=[0-9.]+' | cut -d= -f2 | \
  awk '{n++;s+=$1;q+=$1*$1;if($1>m)m=$1}END{printf "n=%d mean=%.4f sd=%.4f max=%.4f\n",n,s/n,sqrt(q/n-(s/n)^2),m}'
```

**What the next session will read, in order:**
1. The §0.4 verification lines — is the run valid at all.
2. **The per-epoch LB mean ± sd (§0.3), plateau-restricted AND all-epoch** — this is the
   verdict metric now, not the max. **Read the plateau length first:** under ~15 epochs and
   the run is not comparable to the baseline at all, whatever its LB says (§1.6, Q3). Pool
   across seeds when a wave has replicates.
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
| **Q3** `20260821T…` | **30 candle-derived columns** (C12) vs the 19-col baseline — the feature expansion | 240m | mean 0.5003±0.018 (n=28); **plateau mean 0.5000, n=5** | ✅ valid, **decisive negative for THIS column set** | −0.022 against the family. **Calibration inverted** (`emp_up` 0.495→0.465 as `mean_pred` 0.35→0.75; brier 0.2897 vs 0.250) ⇒ rejected by §3.3c independently. Left its training plateau at **epoch 5** vs the baseline's 21–26 and selected a post-overfit epoch, so it is not a fair test of the lever — see §1.6. Two columns numerically defective (C15). Retest = R1. |
| **Q2** `20260821T…` | **3-seed probability ensemble** (C14) | 240m | cov05 LB 0.561 | ✅ valid, **lever closed** | Matched against Q0 on the same split: dir_acc +0.002, brier −0.0005 (both noise), gross bps **worse at 4 of 5 coverages** (cov02 +10.6 vs +18.7; cov05 +11.9 vs +15.1; cov10 +0.6 vs +6.7). Pre-registered "no better than the best member" ⇒ dropped. §5 |
| **Q0** `20260821T083737Z` | eval-only re-score of seed 2 under C13 | 240m | cov05 LB 0.559 | ✅ | Derived seed 2's coverage-targeted gate: **`conf >= 0.6311`**, dir_acc 0.578, +18.68 gross bps/trade, **+4.68 net at taker**. Gate written to the VM's local copy only — pass it explicitly on promote (§2 R0). |
| **Q1** *(local, no run)* | regime analysis on the three 5m dumps | 240m | — | ✅ **positive** | 9 observables × 3 seeds. Nothing clears the 0.60-AUC bar (max deviation 0.06), but **`btc_absret_1d`** has a monotone quintile ladder in bps *and* dir_acc with three-seed agreement: top quintile (BTC 24h \|ret\| ≥ 4.31%, 5.2% of bars) = **+35.5 gross bps/trade at cov05, +54.9 at cov02** vs +8.8 / +22.0 overall. Direction-free. **An M3 observable, not an M2 feature.** §1.8 |
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
| **Multi-checkpoint ensembling (probability averaging)** | **Closed (new, 2026-08-22)** | Q2 averaged three seeds of one configuration and compared against the best member on a matched split (Q0). Ranking improved by noise (+0.002 dir_acc), calibration by noise (−0.0005 brier), and **gross bps/trade got worse at four of five coverages**. The mechanism: averaging pulls every bar toward the consensus, which preserves the directional *order* but compresses exactly the outlier-confident bars where the large moves are. Reopen only if calibration — not P&L — becomes the binding constraint on M3. §1.1 |
| **Gating M2 on a regime observable** | **Barred (new, 2026-08-22)** | Q1's `btc_absret_1d` finding is real and worth +26bps/trade of conditioning (§1.8), and it still must not be built into M2. Deciding *when to be in the market* is M3's job by the design in this document's preamble; building it into the signal model is the cost-aware-selection mistake in a new costume. M2 emits the observable, the policy acts on it. |
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

### The C-batch — OPEN, blocking the R-wave

- 🔴 **C15 — fix the two defective C12 columns. BLOCKS R1.** Both are in the market-context
  group, and R1's chosen fix is simply to drop that group (`FEATURE_DIM` 19 → 25, own-pair
  multi-scale only), which sidesteps both. The underlying defects still need fixing before
  the market-context columns are ever reintroduced:
  1. **`beta_btc_1d` is degenerate for the BTC row.** `cov(r_btc, r_btc)/var(r_btc)` is
     identically 1.0, so the column is constant-by-construction for BTCUSDT and carries no
     information. It escapes the degenerate handler because the warm-up and
     sub-floor-variance bars are set to `0.0`, lifting its raw std to ~1e-3, above the
     `1e-8` CONSTANT threshold — and the normalizer then renders those few bars as a
     **590σ** spike (winsorized at ±50; BTC's worst tail was 66σ before C12). Fix: skip the
     self-beta (emit 0 with `has_market` semantics for the BTC row).
  2. **The variance floor floors nothing.** `ok_var = b_var > 1e-12` at
     `ml/train/data/features.py:436` sits ~6 orders of magnitude below a real `var(ret_1)`
     (≈2.3e-6 at 5m). Make it relative — a fraction of the column's own rolling median
     variance — not an absolute constant. This is trap §0.5.5 again: an absolute threshold
     is not a floor when it is not on the data's scale.
  3. **The CONSTANT detector is absolute where it should be relative.** `raw std <= 1e-8`
     misses any column that is constant-in-meaning but takes two distinct values (the case
     above). Flag a column when it takes ≤2 distinct values, or when `std/|mean|` is below
     a tolerance, in addition to the current absolute test.
  4. **`xs_disp_1h` carries a 122σ tail** and is identical across all eight pairs at a bar,
     so one spike enters every pair at once. Winsorize or log-scale it before normalizing —
     and note Q1 ranks dispersion the least informative of nine observables (§1.8), so
     "drop it" is also a defensible fix.
- 🔴 **C16 — `max_dd` is computed on daily returns sorted by VALUE, not by date.**
  `ml/train/eval_m2.py:266` does `day_list = np.array(sorted(day_net.values()))` and then
  `eq = np.cumsum(day_list)`. Sorting the values puts every losing day first, so the
  reported `maxdd` is just "the sum of all negative days" — a deterministic artifact, not a
  drawdown, in **every table in every log to date**. Should be
  `[day_net[k] for k in sorted(day_net)]`. `daily_sharpe` is unaffected (mean and std are
  order-invariant); every `maxdd` printed so far should be ignored, not re-interpreted.
- 🔴 **C18 — a `FEATURE_GROUPS` knob. ALSO BLOCKS R1.** The column groups are already
  cleanly separated in `ml/train/data/features.py` — `LEGACY_FEATURE_COLS` (19),
  `OWN_PAIR_MULTISCALE_COLS` (6), `MARKET_CONTEXT_COLS` (5) — but `FEATURE_COLS` is their
  unconditional concatenation and `FEATURE_DIM` is asserted equal to `len(FEATURE_COLS)`, so
  **there is no way to run a subset without editing source.** Add
  `FEATURE_GROUPS` (default `legacy,multiscale,market`, i.e. today's behaviour) that
  composes `FEATURE_COLS` from the named groups and derives `FEATURE_DIM` from it rather
  than asserting against a separate env var. R1 then runs
  `FEATURE_GROUPS=legacy,multiscale`.
  ⚠️ **Add it to `FLUX_TRAIN_ENV_KEYS` in the same commit** (§7) — trap §0.5.7 is exactly
  this: a knob that exists in `config.py` but not in the allowlist is a silent no-op on the
  GPU VM, and R1 would then quietly re-run Q3 while its log claims otherwise. The §0.4 check
  for R1 (`Feature columns: 25`) is what catches it if this is forgotten.
- ⬜ **C17 — print the plateau-restricted epoch-LB mean.** C10 prints the all-epoch mean,
  which §0.3 now shows is not comparable between runs whose overfitting onset differs. Add
  `plateau: n=… lastEp=… mean=…` (epochs whose `loss_va` is within 0.02 of the run's
  minimum) to the same summary line, and warn when the plateau is under ~15 epochs.

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

⚠️ Every new training run overwrites `checkpoints/latest.pt`. **`latest.pt` is currently
Q3's checkpoint — the 30-column model whose calibration is inverted (§1.6) — and must not be
promoted.** C13 made `--checkpoint <key>` required, so naming a key explicitly is now the
only way to promote at all. The checkpoints you may actually want:

| run | key |
|---|---|
| **seed 2 — promote this one** (§2, Q0) | `checkpoints/m2_multi_20260819T142759Z_a186182b.pt` |
| seed 1 (O2) | `checkpoints/m2_multi_20260818T185438Z_8c4b2a03.pt` |
| seed 3 | `checkpoints/m2_multi_20260820T025723Z_a186182b.pt` |
| F4 (prior baseline) | `checkpoints/m2_multi_20260817T221811Z_94614795.pt` |
| O3 (do not promote) | `checkpoints/m2_multi_20260819T021020Z_8c4b2a03.pt` |
| P2 (do not promote — uncalibrated 1m model) | `checkpoints/m2_multi_20260820T100042Z_a186182b.pt` |
| **Q3 (do not promote — inverted calibration) = `latest.pt` now** | the 30-column run; it finished last and overwrote the key |

**C13 shipped (2026-08-21)**, so `gcp_promote.sh` now requires `--checkpoint <key>` and
refuses the bare form; `--list` prints the table above from the bucket. It also pins serve
code to the sha in the checkpoint's filename. Remember that every key listed here predates
C13 and therefore carries no `served_gate`: promoting one without an override serves it at
the config fallback of 0.58, which §1.5 shows loses money in all three seeds. Q0 measured
seed 2's gate (**0.6311**) and §2's R0 is the one-line promote that uses it.

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
