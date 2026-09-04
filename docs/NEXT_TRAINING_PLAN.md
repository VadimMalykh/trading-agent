# Training plan — what M2 measured, and the rules that govern a training run

**This is a reference, not a status page.** M2 is frozen as a research object, §2's run queue
is empty, and nothing here is waiting on anyone. Two things live in this file and nowhere
else: **§0's standing rules**, which govern every training run this project will ever launch,
and **§1's reference numbers**, which are what the served model actually measures.

👉 **[BACKLOG.md](./BACKLOG.md) is the entry point** for everything open, parked or closed.
For the policy and what runs live, read [M3_PLAN.md](./M3_PLAN.md) and
[M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md); for the rules that govern a promotion,
[M3_PROTOCOL.md](./M3_PROTOCOL.md) §9.

**The served model** is seed 2, `m2_multi_20260819T142759Z_a186182b.pt`, **served on twelve
pairs** since 2026-08-29 (it was eight until then — the eight were a conservative default held
while four pairs lacked a measured crossing cost, never a decision against twelve). Its serving
constants were re-derived on repaired candles on 2026-09-04: coverage cut
`0.6296127438545227`, ladder p80 `0.025596268475055695`.

🔴 **Every number below §1 was measured PRE-REPAIR.** Candles stored between 2026-07-18 and
2026-09-03 were partial bars ([CANDLE_POLL_DEFECT.md](./CANDLE_POLL_DEFECT.md)); the data is
repaired and the three checkpoints were re-scored ([M3_2_RESULTS_REPAIRED.md](./M3_2_RESULTS_REPAIRED.md)).
The re-score moved the headline numbers by about a bar's width and changed no conclusion, but
quote the repaired file, not this one, for a current figure.

**Where the rest of this document went.** On 2026-09-04 (RULES_REVIEW §6.3) everything that was
narrative rather than reference moved to [archive/TRAINING_HISTORY.md](./archive/TRAINING_HISTORY.md):
§1.0/§1.2/§1.4–§1.7/§1.9/§1.10 (the wave-by-wave readings), §3 (what to bring back), §4 (the
results ledger) and §6 (the completed code batches). Citations to those section numbers resolve
there. What follows is §0, §1.1/§1.3/§1.8, §2, §5 and §7 — unchanged.

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
— that is the number every arm is ranked against, not 0.5219. Nothing ever beat it: R1 0.4979,
Q3 0.5000, R2 0.5058, R3a 0.5185, R3b 0.5199, O8 0.5222 (≈0.512 pair-mix-corrected). 🔴 **The
plateau length is part of the read, not a footnote** — R3b's 36-epoch plateau and R3a's
26-epoch one are trustworthy; a run under ~15 epochs is not comparable at all (§1.6).

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
| **O8** (12 pairs — *12-pair val population, not comparable, §1.9*) | 30 | 0.5126 | 0.0208 | 0.5431 | +1.47 sd |
| **R2** (`DIR_MAG_WEIGHT=1`) | 37 | 0.5102 | 0.0108 | 0.5345 | +2.25 sd |
| **R3a** (`HIDDEN_SIZE=128`) | 58 | 0.5182 | 0.0131 | 0.5432 | +1.91 sd |
| **R3b** (`HIDDEN_SIZE=32`) | 37 | 0.5194 | 0.0133 | 0.5459 | +1.99 sd |

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
| `Feature groups:` | the groups **and** the column count you intended — a knob that did not reach the VM shows up here and nowhere else (C18) | — |
| `DEGENERATE SPIKE` | **absent on any NEW column.** A column flagged here is near-constant with a few odd rows rendered as a huge z; the CONSTANT detector missed it because its raw std clears `NORM_DEGENERATE_STD`. `heavy tail … N rows beyond — a populated tail` is fine (C15). ⚠️ **`hl_range` is a known standing exception** — it flags on ~6 of 8 pairs at 66–364σ with 2–4 rows, it is a *legacy* column present identically in the §1.3 baseline, and it is **not** a reason to void a run (C19) | would have caught Q3's `beta_btc_1d` |

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


---

## §1 — REFERENCE NUMBERS

*§1.0, §1.2 and §1.4–§1.10 moved to [archive/TRAINING_HISTORY.md](./archive/TRAINING_HISTORY.md)
on 2026-09-04. The three subsections kept here are the ones other documents read numbers out
of: the summary, the family's reference table, and the regime finding M3's policy is built on.*

### 1.1 The one-paragraph summary

🔴 **Updated 2026-08-24 — the conditional has been discharged.** The paragraph below ended by
naming encoder capacity as the one untested structural knob and O8/R2 as the remaining
information levers. All three have now run and all three are flat or negative (§1.9): O8's
pair-mix-corrected plateau mean is ≈0.512 against the family's 0.5239, R2 lost economics at
every coverage while driving brier from 0.250 to 0.316, R3a memorized (`loss_tr` → 0.888,
brier 0.419) and R3b at half the width reproduced the baseline exactly. **§2's pre-registered
exit condition fired on every clause, so M2 is frozen at §1.3 and the queue is now one
promote.** The paragraph below stands as written for the reasoning that got us here.

**Per-timestep candle features are closed, M2 is finished as a research object, and the
largest measured lever in the project belongs to M3.** R1 was the clean retest Q3 was
supposed to be — the well-conditioned six-column half (`ret_1h/4h/1d`, `vol_1h/4h/1d`),
`FEATURE_GROUPS` verified at 25 columns, every §0.4 line green — and it came back
**plateau-mean cov05 LB 0.4979 against the family's 0.5239** (between-seed sd 0.0032, so
≈8σ down), all-epoch mean 0.4889 vs 0.5219, `brier` 0.286 vs 0.250, and a calibration table
that is flat at `emp_up ≈ 0.48` across every bin from 0.10 to 0.80. It is worse than Q3.
🔴 **The decisive new fact is that R1 never reaches the baseline's validation loss at any
epoch, including epoch 1** (best `loss_va` 1.0451 vs the family's 1.0398–1.0404). Q3 could
be dismissed as "overfits too fast, needs regularization"; R1 cannot, because no amount of
regularization recovers a level the model never touched. §1.6 has the mechanism, and it is
a simple one: at `seq 384` every one of the six columns is an **exact function of bars
already inside the window** at the timestep the prediction is made from, so they add no
information while adding six smooth, strongly autocorrelated channels that are far easier
to memorize than `ret_1` — `loss_tr` duly collapses 1.70 → 1.13 from epoch 12 while
`loss_va` climbs to 1.45. Two feature waves, two rejections, and the second one rules out
the escape hatch the first one left open. **The 3-seed 5m/seq384 baseline (§1.3) is the
final M2.** What remains genuinely untested is not features and not model family but
**encoder capacity on the current baseline** — never once swept, and newly measurable now
that the plateau-restricted mean resolves ~0.01 (§2 R3). That is one cheap probe, not a
wave. Everything else moves to M3, where Q1's `btc_absret_1d` turns the top-5% slice from
+8.8 to **+35.5 gross bps/trade** (§1.8) — a 4× that no M2 change has come within an order
of magnitude of.


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

**The queue is empty.** T5 and T6 are done, R0 was promoted 2026-08-26, and M2 is frozen at the
§1.3 baseline: no new M2 run without a new *kind* of data (§5). Every open and parked item is in
[BACKLOG.md](./BACKLOG.md), which is the list to read — not this section.

**Two things are queued elsewhere and are not M2 runs:**

* **The walk-forward folds** — twelve serial `gcp_train.sh` runs, pre-registered in
  [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md). They retrain the §1.3 recipe with the
  split boundary moved back; they are not a change to M2 and they do not reopen §5.
* **B3**, below, which is blocked.

### 🔴 B3 — the book-era GBT. BLOCKED, not refused (2026-08-31)

**This is the only training run any current plan calls for, and it is not runnable.** It is one
LightGBM run on its own throwaway CPU VM (`scripts/gcp_gbt.sh`), pre-registered in
[BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) §B3, and it happens **if and only if** B1 clears §4.1.

B1 ran on 2026-08-31 (`./scripts/m3.sh -m m3 bookaudit`) and returned **`NOT EVALUABLE`**: §4.1
requires `n >= 2,000` in a top-5% slice, which needs ≥ 40,000 usable held-out rows, and the book
era supplies 39,740. The gate is short by ~1% and could not be run as written.

🔴 **`NOT EVALUABLE` is not `FAIL`, and B3 must not be launched as though the gate were merely
close.** The measured evidence, offered as texture only: the best sign-agreeing slice is
`trade_vol` at 60m, **+12.47 bps in excess of the period's drift, day-clustered 95% CI
[−6.06, +30.99]** on 12 clusters. It is indistinguishable from zero. Naively it looked like six
sigma; overlapping 60m windows on a 5m grid are why.

**What un-blocks it — two routes, and only these two:**

1. **Calendar.** The book window grows past the n floor on its own. §4.4's own trigger is ≥90
   days of continuous book history on the 8 main pairs, ≈**2026-10-15**, which clears the floor
   with room to spare. Re-run `m3 bookaudit`, then read §4.1.
2. **A fresh pre-registration of the floor, written BEFORE the numbers are looked at again.**
   Legitimate — 2,000 was a round number, not a power calculation — but it must be a document
   written in advance, not a decision taken while the current table is on screen.

⚠️ **Do not "fix" this by widening the coverage to 10% to reach n.** §4.1 names top-5%. Changing
the coverage to make the n floor reachable is re-picking a searched dimension after seeing
results, which [M3_PROTOCOL.md](./M3_PROTOCOL.md) §0 forbids.

**Nothing else in the B-wave needs a GPU or a training run.** B0, B1 and B2 are all done and all
ran on the laptop's `ml_analysis` container.

---

## §5 — CLOSED LEVERS (do not re-propose without new evidence)

| Lever | Status | Why |
|---|---|---|
| **Cost-aware checkpoint selection (`SEL_NET_WEIGHT`)** | **Closed (new, 2026-08-18)** | N3 ran it at the horizon where R5's objection no longer applies. The term is alive but ranks a statistic with ~600 effective samples and ~5bps standard error against a 19bps range, at ~88% effective weight. Chosen epoch was no more profitable than F4's. §1.5. Reopen only with a fixed range (`SEL_NET_SCALE≈0.04`) *and* a reason to believe per-epoch net/trade is estimable. |
| **The book ON/OFF walk-forward *design*** | **Retired (new, 2026-08-18)** | Three attempts, zero decidable verdicts. The book-OFF arm's modal failure (collapse to an all-flat predictor) is exactly what pushes `n_dir` under the reliability floor, so the design is least able to decide precisely when the book helps most. The book question is not closed — it moves to within-model attribution (**O5**). Do not launch `gcp_walkforward.sh` for it again. 🔴 **The archive records a trigger to re-run this at ≥30d book history (≈2026-08-25); that trigger is superseded, not live** — 30 days does not repair a design that cannot decide. The question is picked up instead by `docs/BOOK_ERA_PLAN.md`, which measures in bps before training anything, and O5's attribution finally arrives there as B3's feature importances. |
| **Context length / sequence window** | **Closed (new, 2026-08-19)** | O3 ran seq 128→256 at 15m as a clean one-variable test and it is *worse* on mean-of-epochs (0.4925±0.023 vs F4's 0.5058±0.016), with a collapsing confidence distribution and a coin-flip up side. The LSTM already uses all the window it can. Do not sweep seq 512. Note this is about *window*, not *resolution* — finer bars at the same window (O2) is a separate and live lever. §1.4 |
| **Encoder capacity / layers / hidden** | 🔴 **CLOSED ON MEASUREMENT, 2026-08-23 — R3a and R3b both ran** | It was reopened once, on the one legitimate basis (the plateau-restricted mean resolves ~0.01, so a single run can now decide), and the bracket was run as designed. **Both arms are flat on the low side**: 128 units → plateau mean 0.5185, 32 units → 0.5199, against 0.5239 (between-seed sd 0.0032). Neither approaches the +0.011 the pre-registration required. The bracket also refutes the *shape* of the hypothesis, not just its size: going up produces pure memorization (`loss_tr` 1.72 → 0.888 with `loss_va` never reaching baseline, brier 0.419), and going *down* to a quarter of the parameters changes nothing. There is no monotone curve to climb, so **no third run is justified and this is closed for good.** §1.9 |
| **Training data volume / pair count** | **Closed (new, 2026-08-22)** | O8 added ADA/AVAX/LINK/XRP for 4.59M samples, +58%, the largest data increase available without new *kinds* of data. Re-aggregated onto the original 8 pairs it is inside the 3-seed family's spread at every coverage (+23.9 / +21.3 / +6.8 vs +19.4 / +22.0 / +8.9), and the pair-mix-corrected plateau mean is ≈0.512 vs 0.5239. Crypto pairs are highly correlated, so 58% more *rows* is far less than 58% more independent observations — the effective-sample gain was small and the measured gain is zero. Do not start a pair-count ladder *as a data experiment*. 🟢 **Amended 2026-08-27; both halves are now closed.** Pair count as *traded universe* is a genuinely different lever from pair count as *training data*, and it was tested on its own: the T-wave ran two more 12-pair seeds and the single-seed "+7.5 net bps/trade" **did not replicate**, then T6 ran the fair comparisons — trade-count-matched, cut-matched, cap-re-tuned — and put the effect within a couple of bps of zero in every one, against a data-resolution limit of ±37 bps. **The traded-universe question is closed as *undecidable on this evaluation period*, not as decided against.** ⚠️ This row read "the incumbent 8-pair universe stands" until 2026-08-29; it no longer does — **the served universe is twelve**, once every added pair carried its own measured crossing cost. What stays closed is the *question*, not the universe. §1.9 and §1.10 in [archive/TRAINING_HISTORY.md](./archive/TRAINING_HISTORY.md), `docs/T6_RESULTS.md` |
| **Magnitude / cost-shaped training losses (`DIR_MAG_WEIGHT`)** | **Closed (new, 2026-08-23)** | R2 was the second and better-designed attempt at teaching M2 about economics rather than accuracy (N3's selection-time cousin was the first, closed 2026-08-18). It ran correctly — `at_clip` under 1%, `scale` ≈ 0.98, `mean\|r\|` rising with horizon — and it lost gross bps/trade at every coverage while driving brier from 0.250 to 0.316 and flattening `emp_up` to ≈0.48 in all ten bins. The mechanism generalizes past this one knob: **up-weighting large moves teaches the head that "confident and large" is the same axis as "confident and correct", and it is not.** Position sizing by expected move magnitude is M3's job and belongs in the policy, where it can be applied without corrupting the probability M2 exists to emit. §1.9 |
| **M2 as a research object** | 🔴 **FROZEN, 2026-08-24 — the exit condition fired** | Written down in advance on 2026-08-22: "if O8 and R3 both come back flat (within ±0.005 plateau-mean LB of 0.5239) **and** R2 does not move gross bps/trade at cov 0.02 by more than +5, M2 is frozen at the §1.3 baseline and every remaining hour goes to M3." O8 −0.0017, R3b −0.0040, R3a −0.0054, R2 −3.2 bps. **Every clause fired.** Eight levers have now been tested one variable at a time against the same baseline — two feature sets, bar resolution, context length, model family, ensembling, loss shaping, data volume, and encoder capacity in both directions — and exactly one (15m → 5m) ever moved. The single reopening condition is §1.7's: order-book history deep enough to sit inside the *training* window, ≈2027. Do not queue an M2 run before then. §1.9, §2. **`docs/BOOK_ERA_PLAN.md` tests whether a *short-horizon* model on the book era can be decided early; it does not reopen this row, and §4.3 there forbids promoting anything on a 7-day validation window.** |
| Full architecture swap (transformer / TCN) | **Closed, and reaffirmed 2026-08-22** | Was gated behind O3; O3 came back negative. The reopening condition written in 2026-08-19 was "if richer per-timestep features saturate and the residual failure looks like a modelling limit rather than an input limit" — Q3 and R1 have now *both* run and the failure looks like the opposite: the model already memorizes the training set the moment it is handed anything easy (`loss_tr` 1.70 → 1.13 in R1), while its validation loss never improves. That is an **input** limit and an SNR floor, not a modelling limit. A higher-capacity family would make it worse, not better. **Do not write a transformer.** 🔴 **Reaffirmed again 2026-08-23: R3a ran the two-run bracket's upward arm and produced exactly this prediction** — `loss_tr` 1.72 → 0.888 with `loss_va` never once reaching the baseline's level, and the worst calibration in the ledger. More capacity of any kind makes this problem worse. There is no remaining capacity question. |
| Confidence calibration / temperature / focal loss | **Closed** | F4's head is *over*-confident (`[0.60,0.70)` bin mean_pred 0.636 vs empirical 0.547; N3's is 0.609 vs 0.521). Sharpening an over-confident head is the wrong direction. |
| Raising `GATE_THRESHOLD` as an experiment | **Superseded by C1+C2** | The served gate is 0.58 and eval now reports there. Derive the operating point from the fixed-coverage P&L table, not from another sweep. |
| Quantile head | **Deferred** | Regressed direction ~0.014; band coverage unstable. Revisit at M3, detached. |
| `liquidations` feed | **Dropped** | 0 rows; Binance gates WS market data from datacenter egress (verified from 3 hosts). |
| More candle *history* | **Closed** | Adds more of the pre-book regime we already fit. Note this is about *history*, not *resolution*. |
| **Bar resolution — 15m → 5m** | **🟢 BANKED and frozen (2026-08-21)** | Replicated across three seeds: pooled mean-of-epochs 0.5219 ± 0.0014 vs F4's 0.5058, and pooled +22 gross bps/trade at the top 2% (§1.3). `5m / seq 384` is the permanent baseline. Nothing further to test here — do not run a fourth seed. |
| **Bar resolution — finer than 5m** | **Closed (new, 2026-08-21)** | P2 ran 1m/seq768 as a direction probe: flat `dir_acc` (0.561 vs 0.559), materially worse economics, **destroyed calibration** (`emp_up ≈ 0.48` in every bin, brier 0.323 vs 0.250), 20h wall clock. The ladder has one rung and we are standing on it. The untested variant (1m at a 32h window, seq 1920) is unaffordable and context length is separately closed. §1.4 |
| **Multi-checkpoint ensembling (probability averaging)** | **Closed (new, 2026-08-22)** | Q2 averaged three seeds of one configuration and compared against the best member on a matched split (Q0). Ranking improved by noise (+0.002 dir_acc), calibration by noise (−0.0005 brier), and **gross bps/trade got worse at four of five coverages**. The mechanism: averaging pulls every bar toward the consensus, which preserves the directional *order* but compresses exactly the outlier-confident bars where the large moves are. Reopen only if calibration — not P&L — becomes the binding constraint on M3. §1.1 |
| **Per-timestep candle features (own-pair)** | **Closed (new, 2026-08-22)** | Two arms, both rejected. Q3 added 11 columns (30 total) and R1 added the well-conditioned 6 (25 total) with every §0.4 line green. R1's plateau mean is 0.4979 vs 0.5239, and — the fact that closes it — **R1's best validation loss (1.0451) is worse than the baseline's (1.0398–1.0404) at every epoch including epoch 1**, so no regularization arm can recover it. At `seq 384` (32h) every multiscale column is an exact function of bars already inside the window at the prediction timestep: zero information, six smooth channels that are far easier to memorize than `ret_1`. **Redundant re-parameterizations of the input are pure overfitting surface.** Reopen only for genuinely *external* information, and note Q1 already measured the informative member of that family and assigned it to M3. §1.6 |
| **"Add regularization and retry the feature set"** | **Withdrawn before it ran (2026-08-22)** | It was §2's pre-registered branch for a collapsed plateau, and R1 falsified its premise. Regularization lengthens a plateau; it cannot lower a model onto a validation loss it never reached in its single best epoch. Do not spend 3h GPU on a `DROPOUT` arm at 25 columns. |
| **Gating M2 on a regime observable** | **Barred (new, 2026-08-22)** | Q1's `btc_absret_1d` finding is real and worth +26bps/trade of conditioning (§1.8), and it still must not be built into M2. Deciding *when to be in the market* is M3's job by the design in this document's preamble; building it into the signal model is the cost-aware-selection mistake in a new costume. M2 emits the observable, the policy acts on it. |
| **Absolute `GATE_THRESHOLD` as a serving constant** | **Closed (new, 2026-08-21)** | Not a lever, a defect. The same probability is 1.2% / 2.5% / 1.7% coverage across three seeds of one configuration and 80% on P2 (§1.5). The gate must be a per-checkpoint coverage target chosen from the fixed-coverage P&L table. C13. |
| **"Flat training loss proves nothing" — and now "one seed proves nothing"** | **Reinforced (2026-08-21)** | Of the four claims the O-wave made from one seed, three did not survive replication (§1.2, §1.5). Any result quoted from a single run is provisional until a second seed agrees. |
| **"Flat `loss_tr` proves the model is not data-starved"** | **Falsified (new, 2026-08-19)** | O2's loss was as flat as F4's through the region its selected epoch lives in, and it still improved materially. On a near-noise-floor task the training loss is dominated by the irreducible term. Judge data levers on the validation-selection metric only. §1.5 |
| Tuning any single hyperparameter on one run | **Closed by §0.3** | The measurement cannot resolve effects below ~0.04 LB from a single run. Any such sweep is reading noise. |

---


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
CANDLE_INTERVAL FEATURE_GROUPS NORM_DEGENERATE_STD NORM_CLIP NORM_LEGACY_BROKEN_STD
BOOK_MAX_AGE_MIN TRADES_MAX_AGE_MIN FUNDING_OI_MAX_AGE_MIN
GATE_THRESHOLD SERVE_TARGET_COVERAGE
FEE_RATE_BPS SLIPPAGE_BPS MAKER_FEE_RATE_BPS MAKER_SLIPPAGE_BPS
```

`EARLY_STOP_PATIENCE` and `SEED` were added by C8 (2026-08-18); `SERVE_TARGET_COVERAGE` by
C13 (2026-08-21); `FEATURE_GROUPS` by C18 (2026-08-22).

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
- **Per-bar prediction dumps: `…/eval/<RUN_ID>/eval_preds.parquet`** (C9, written by every
  run) — `ts, pair, horizon, side, conf, p_up, fwd_ret, y3, has_book`. This is what makes
  after-the-fact analysis cheap: Q1's whole regime study and O8's 8-pair re-aggregation were
  done from these dumps with no GPU, no DB and no checkpoint.

### Re-aggregating a run onto a different pair set — `ml/train/reaggregate_preds.py`

When an arm changes the **validation population** (a different pair set, a different bar
interval), its logged `cov05` slice is not selecting from the same universe as §1.3's, so the
headline LB and P&L are not comparable (§0.6, §1.9). Re-derive them on the baseline's pairs:

```sh
gsutil cp gs://fluxtrader-train-artifacts/eval/<run_id>/eval_preds.parquet /tmp/
python ml/train/reaggregate_preds.py /tmp/eval_preds.parquet --validate --split-new
```

🔴 **Always pass `--validate` and read its first table before anything else.** It recomputes
the metrics on the *full* population, which must reproduce the run's logged `Fixed-coverage
directional edge` and `Fixed-coverage P&L` blocks **exactly** — that is the only proof the
harness has not drifted from `eval_m2.py`/`gate.py`, whose definitions it deliberately
duplicates so it can run locally without torch. It reproduced O8's table to the digit
(+24.76 / +23.63 / +6.85). If it ever does not, fix the script before believing any subset
number it prints.

Needs only `pandas pyarrow numpy` and never runs on the VM — but it runs in Docker like
everything else here, via `./scripts/m3.sh reaggregate_preds.py …` (M3_PLAN §0.0). Nothing
is installed on the host.

**This script answers the M2 question** — what does the run score at fixed coverage on a
given pair set. For the M3 question — what does the *policy* earn on a given traded universe
— use `./scripts/m3.sh -m m3 universe` instead (§1.10). They are not interchangeable: the
first re-aggregates bars, the second re-runs entries, holds, sizing and fees.

### Related docs

- `docs/BACKLOG.md` — **the index of every open, parked and closed item. Start there.**
- `docs/M3_PLAN.md` — **the policy milestone.** M2's
  handover, the constraints it imposes on the policy, and the ordered sequence.
- `docs/archive/TRAINING_HISTORY.md` — the full session narrative, 2026-07-23 → 2026-08-21,
  including the O-wave as written before seed replication corrected three of its claims.
- `docs/archive/DATA_COLLECTION_AUDIT.md` — what the collector captures vs silently drops.
- `docs/archive/QUANT_AB_HANDOFF.md` — quantile-head A/B and its deferral.
- `docs/archive/MODEL.md` — architecture contract; §4.3 labels, §4.4 architecture options.
- `AGENTS.md` — Docker-only workflow, data-lives-on-the-VM rule.
