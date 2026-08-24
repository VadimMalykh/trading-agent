# Training plan — what is true, what to run next

**Last updated: 2026-08-24** (after the closing wave — O8, R2, R3a, R3b. All four flat or
negative, the pre-registered exit condition fired, and **M2 is frozen at the §1.3 baseline**.
Preceded by R1, and by the Q-wave: Q0 gate derivation, Q1 regime analysis, Q2 ensemble,
Q3 feature expansion).

🔴 **If you are picking this up cold: there is one open action (§2 R0, a re-run of the
promote — the 2026-08-24 attempt shipped seed 2 at gate 0.55 instead of its measured
0.6311) and then all work moves to M3.** There are no M2 experiments left to run, and
M3 is planned in **`docs/M3_PLAN.md`**, not here.

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
**§1.0 (plain-language state of play — no jargon, no §0 required)** → §2's R0 (the promote)
→ **`docs/M3_PLAN.md`**, which is where the work continues. Read §1.1, §0.3 and §0.6 when you need to know *why* the numbers are read
the way they are, or before you rank two runs against each other. §1.9 is the wave that
closed M2; §0 exists to stop a future session re-running what it already refuted.

- §0 — standing rules. Read before touching anything. Every rule cost us a real run.
- §1 — where we are, in numbers. The current reference points.
- §2 — **the run queue.** This is the "what do I type" section. It is now one promote.
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

## §1 — WHERE WE ARE (2026-08-24)

### 1.0 Plain-language state of play — readable without §0

*If you read one section, read this one. §1.1 says the same thing in the document's own
vocabulary; everything below §1.1 is the evidence.*

**What the model is.** A small recurrent network (2-layer LSTM, 64 hidden units — about
56k parameters) that reads the last **384 five-minute candles (32 hours)** for one trading
pair and outputs, for each of three horizons (1h / 4h / 24h), a probability that price goes
up, down, or stays flat. 4h is the horizon we optimise. It does **not** decide trades —
that is M3's job (see the preamble).

**What it is worth.** Take the 5% of bars where it is most confident: it is right about
direction **55.9%** of the time, and those trades are worth about **+9 basis points each
before fees**. Narrow to the most confident 2% and it is **+22 bps**. A round trip costs
**14 bps** as a taker and **5 bps** as a maker. So: comfortably profitable at maker fees on
the top 2%, thin but positive at taker fees, and not usable at all if you trade more than
about the top 5% of bars. This is measured on three independently seeded models that agree
with each other, which is why we trust it.

**What the input actually is — this is the surprising part.** The feature list has 19
columns, but **12 of them are dead**. Order-book and trade-flow data only began being
collected in July 2026, which is entirely inside the *validation* period, so across the
training window they are constant and get zeroed out. The model is genuinely learning from
**seven live columns**: 1-bar return, high–low range, open–close range, log volume, funding
rate, a 15-bar return volatility, and one availability mask. That is it. Essentially price
and volume.

**What we have tried, and what happened.**

| tried | outcome |
|---|---|
| Finer bars (15m → 5m) | ✅ **worked** — the one real improvement, +0.016, replicated on 3 seeds |
| Finer still (1m) | ❌ no better at ranking, worse economics, broke the probabilities |
| Longer memory (32h → 64h) | ❌ worse |
| A gradient-boosted tree instead of the LSTM | ❌ much worse — sequence structure genuinely matters |
| Averaging 3 models together | ❌ compresses exactly the confident bars where the money is |
| Choosing the checkpoint by profit instead of accuracy | ❌ the profit estimate is too noisy to rank on |
| Adding 11 new derived columns (Q3) | ❌ rejected |
| Adding the best-behaved 6 of them (R1) | ❌ rejected, worse than Q3 — **§1.6, and this closes features** |
| Hyperparameter tuning (dozens of runs, the R/E waves) | ❌ the whole spread was inside the noise |
| **More pairs — 12 instead of 8, 58% more data (O8)** | ❌ **no better.** Free to adopt, but it buys coverage, not edge — §1.9 |
| **A loss that cares about move size (R2)** | ❌ **worse.** Made the model wildly overconfident and broke the probabilities — §1.9 |
| **A bigger encoder — 128 units (R3a)** | ❌ **worse.** Memorized the training set; worst calibration in the project — §1.9 |
| **A smaller encoder — 32 units (R3b)** | ❌ **identical.** Half the size, same result — the model was never capacity-limited — §1.9 |

**The one big thing that did work, and it is not a model change.** Q1 found that when
**Bitcoin has moved more than ~4.3% in the past 24 hours** — which happens on about 5% of
bars — the same model's top-5% trades are worth **+35 bps instead of +9**, and **+55
instead of +22** at the top 2%. Three seeds agree closely. That is a **4×**, and no change
we have ever made to the model itself has produced more than a few percent. It is a
statement about *when to be in the market*, so it belongs to the trading policy (M3), not
to the signal model.

**Where that leaves us — and this is now settled rather than provisional.** The last three
experiments were the ones the previous session queued to decide whether M2 was finished, and
they all said yes. More data did nothing. A loss aimed squarely at the economic weakness made
it worse. Making the network bigger made it worse; making it *smaller* changed nothing at all,
which is the clearest possible statement that the network was never the bottleneck. Seven
columns of price and volume support a small real edge, we have found it, and there is nothing
further to extract from these inputs.

**So M2 is done.** The recommendation is: promote the model we have (§2 R0, five minutes),
then spend everything on M3 — the trading policy — where the one big measured effect lives.
That effect is worth restating: conditioning on *whether the market has been moving* takes the
same model's top-2% trades from +22 to **+55 basis points**, roughly a 4× improvement, versus
the few-percent noise that every model change produced. The only thing that would reopen M2 is
**new data** — order-book history deep enough to fall inside the training window — and that is
a calendar problem, not a modelling one (§1.7). Expect it around 2027.

One small free win worth taking separately: the 12-pair run was no better, but it was no
*worse* either, so a 12-pair model covers four more instruments at the same edge and the same
serving cost. That is a product improvement, not a research result (§2).

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

⚠️ **"Passing it explicitly" means the VM's `.env`, not your shell.** `ML_GATE_THRESHOLD`
on the launcher was a no-op until 2026-08-24 — compose interpolates it on the *remote*
host — and the VM's `.env` value silently won. `gcp_promote.sh` now writes the value into
that file and fails the promote if `/health` disagrees, but if you ever change the gate by
hand, change it there and recreate **both** `ml_inference` and `app`: the Elixir
`Predict.gate_threshold/0` reads the same variable and gates independently.

### 1.6 🔴 Per-timestep candle features are closed — two arms, two rejections

Two runs tested the same lever from different sides. Both lost, and together they close it.
(Family columns are in O2 / seed2 / seed3 order throughout.)

| | 5m family (3 seeds, 19 cols) | Q3 (30 cols) | **R1 (25 cols)** |
|---|---:|---:|---:|
| plateau-restricted mean cov05 LB | **0.5239** (0.5235 / 0.5273 / 0.5209) | 0.5000 (n=5) | **0.4979** (n=11) |
| all-epoch mean cov05 LB | 0.5219 ± 0.0014 | 0.5003 (n=28) | **0.4889** (n=38) |
| plateau length (epochs) | 24 / 21 / 26 | 5 | **11** |
| **best `loss_va` ever reached** | **1.0404 / 1.0398 / 1.0401** | 1.0431 | **1.0451** |
| `brier` (240m, moved bars) | 0.250 | 0.2897 | **0.2863** |
| calibration bin table | monotone in `emp_up` | inverted | **flat — `emp_up` 0.48 in every bin 0.10→0.80** |
| gross bps/trade @ cov 0.01 / 0.02 | +19.4 / +22.0 | +19.7 / +17.6 | **+8.0 / +11.7** |
| selected epoch | inside its plateau | ep 8 (outside) | ep 18, `loss_va` 1.157 = **+0.11 above its own min** |

**R1 was a valid run.** Every §0.4 line is green: `Feature groups: legacy,multiscale ->
25 columns`, `Feature columns: 25`, `12/25 CONSTANT` with **no new column** in the list (all
six multiscale columns are live), `Samples: 2,902,678`, `hold=48 bars`, `Pair embedding: ON
dim=8`, split recorded, `Early stop at epoch 38` (not `1 + patience`). The knob reached the
VM and the run tested exactly what it was supposed to test.

🔴 **What R1 proves that Q3 could not.** Q3's short plateau supported a benign reading —
"the extra columns are informative, the run just overfits before it can use them, add
regularization and retry." R1 kills that reading, because **R1 never matches the baseline's
validation loss at any epoch, starting at epoch 1** (1.0451 vs 1.0398–1.0404, and its
epoch-1 value *is* its minimum). Regularization can lengthen a plateau; it cannot lower a
model onto a level it never reached in its best epoch, before capacity has been consumed at
all. The pre-registered "plateau collapses ⇒ run a `DROPOUT` arm at 25 columns" branch is
therefore **withdrawn, not executed** — it would spend 3h GPU to reach, at best, the
baseline.

🔴 **The mechanism, and it explains both runs.** At `seq_len 384` on 5m bars the window is
**32h**. Every multiscale column looks back at most a day: `ret_1d` and `vol_1d` need 288
bars, `ret_4h`/`vol_4h` 48, `ret_1h`/`vol_1h` 12 — all inside 384. So at the final timestep,
*the one the prediction is made from*, all six are **exact deterministic functions of the
`ret_1` and `hl_range` values already in the window**. They carry no information the encoder
did not already have. Only the earlier timesteps of the sequence reach further back (up to
56h) — and longer context is separately closed by O3 (§5). What they do add is six smooth,
strongly autocorrelated channels, which are enormously easier to memorize than noisy
`ret_1`: `loss_tr` sits at 1.70 through epoch 11 and then falls to 1.13 by epoch 38 while
`loss_va` climbs to 1.45. **Redundant re-parameterizations of the input are not free; they
are pure overfitting surface.** Q3 fits the same story with eleven columns instead of six.

**What is and is not closed.** *Own-pair* per-timestep candle features are closed —
there is nothing left to derive from a pair's own OHLCV inside a 32h window that the
encoder cannot already compute. *Cross-pair / external* information is the one thing
neither run tested cleanly (Q3's market-context group had a 590σ defect and no
regularization change), but Q1 independently measured the informative member of that family
— BTC trailing-move magnitude — and found it to be a *when to trade* observable that M3
owns, while the dispersion family C12 actually shipped ranks least informative of nine
(§1.8). So there is no arm here worth 3h of GPU.

🔵 **One incidental finding, recorded so it is not rediscovered.** C15's new spike detector
fires on `hl_range` for six of eight pairs (max|z| 66–364, 2–4 rows beyond 50σ out of
~420k), and `hl_range` is a **legacy** column — so the 3-seed baseline has carried this
since forever and R1 did not introduce it. The values are byte-identical to Q3's. It is 2–4
rows per pair, winsorized at ±50, so the practical impact is nil; it is logged as **C19**
(§6) at low priority. SOL and HYPE get the benign "populated tail" message at the same
`max|z|` because the detector is correctly rate-based, not count-based.

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

### 1.9 🔴 The closing wave — O8, R2, R3a, R3b all flat or negative. M2 is frozen.

Four runs, one variable each, all against the §1.3 baseline. **The exit condition
pre-registered in §2 on 2026-08-22 fired exactly as written**, so M2 is closed on
measurement rather than on fatigue. Every run passed every §0.4 verification line — the
knobs reached the VM, the pair sets and column counts are the intended ones, `hold=48`,
splits recorded, no `BROKEN SCALE`, no new `DEGENERATE SPIKE`.

| run | lever | plateau mean LB (n) | best `loss_va` | brier | cov0.02 gross bps | verdict |
|---|---|---|---:|---:|---:|---|
| **baseline (3 seeds)** | — | **0.5239** (sd 0.0032) | 1.0398–1.0404 | 0.250 | **+22.0** | reference |
| **O8** | 12 pairs (+58% samples) | 0.5222 (17) †  | 1.0454 † | 0.2495 | +21.3 ‡ | ❌ flat — data volume is not the constraint |
| **R2** | `DIR_MAG_WEIGHT=1` | 0.5058 (12) | 1.0419 | **0.3156** | +18.8 | ❌ rejected — no economic gain, calibration destroyed |
| **R3a** | `HIDDEN_SIZE=128` | 0.5185 (26) | 1.0440 | **0.4187** | +12.0 | ❌ rejected — memorizes, calibration destroyed |
| **R3b** | `HIDDEN_SIZE=32` | 0.5199 (36) | 1.0420 | 0.2507 | +16.2 | ❌ flat — capacity is not the constraint |

† O8's LB and `loss_va` are measured on a **12-pair validation population** and are not
directly comparable to the baseline's — see the re-aggregation below.
‡ O8's P&L figure is the honest 8-pair re-aggregation, not its logged 12-pair number.

#### O8 — more data buys nothing, but 12 pairs is free

The re-aggregation §2 pre-registered was performed locally on O8's `eval_preds.parquet`
(`gs://fluxtrader-train-artifacts/eval/20260822T012619Z/`) with
**`ml/train/reaggregate_preds.py`** — committed this time, so the next session does not
rebuild it a third time (§7). **The harness was validated first by reproducing O8's logged
12-pair table exactly** — cov 0.01/0.02/0.05 gross came
back +24.76 / +23.63 / +6.85 and `dir_acc` 0.547 / 0.563 / 0.548 against the logged
+24.76 / +23.63 / +6.85 and 0.547 / 0.563 / 0.548 — so the 8-pair numbers below are on the
same footing as §1.3's.

| slice | cov | dir_acc | wilson_lb | trades | gross bps/trade |
|---|---:|---:|---:|---:|---:|
| **8 baseline pairs (the honest comparison)** | 0.01 | 0.561 | 0.546 | 291 | **+23.93** |
| | 0.02 | 0.566 | 0.556 | 608 | **+21.32** |
| | 0.05 | 0.540 | 0.533 | 1,340 | +6.81 |
| *§1.3 family, pooled 3 seeds* | 0.01 / 0.02 / 0.05 | — | — | — | *+19.38 / +22.03 / +8.91* |
| all 12 pairs, as served | 0.01 | 0.547 | 0.535 | 429 | +24.76 |
| | 0.02 | 0.563 | 0.555 | 871 | +23.63 |
| | 0.05 | 0.548 | 0.543 | 2,019 | +6.85 |
| the 4 new pairs alone | 0.02 | 0.560 | 0.546 | 266 | +28.31 |
| | 0.05 | 0.565 | 0.556 | 681 | +9.69 |

**Read it as: 58% more training data moved nothing.** On the original 8 pairs one seed of
O8 lands inside the 3-seed family's spread at every coverage — +23.9/+21.3/+6.8 against
+19.4/+22.0/+8.9 — which is what "no effect" looks like on this measurement. The verdict
metric confirms it: the 12-pair plateau mean is 0.5222, and at the selected epoch the
12-pair aggregation runs **+0.010 above** the 8-pair one (0.543 vs 0.533) because the four
new pairs happen to score better, so the pair-mix-corrected 8-pair plateau mean is ≈**0.512**
— inside §2's pre-registered "**≤ 0.527 → data volume is not the constraint either**" band.
Combined with R1, that is the strong statement §2 asked for: **M2 on OHLCV is finished.**

🟢 **One genuinely useful negative, though: adding four pairs costs nothing.** The majors'
edge did not degrade, the new pairs are individually as good as the old ones (LINK cov05
`dir_acc` 0.599, XRP 0.606, AVAX 0.557 against BTC's 0.612 and ZEC's 0.515), brier is 0.2495
and the calibration table is monotone. A 12-pair model is a strictly better *product* at the
same measured edge, and it is free at serve time. That is a deployment fact, **not** a
research result, and it should not be counted as an improvement.

#### R2 — the magnitude-weighted loss ran correctly and did the opposite of its job

The instrumentation is green: `scale` 0.982–0.989, `at_clip` 0.56–0.77% (well under the 10%
that would have made it a step function), `mean|r|` rising 100.5 → 201.9 → 501.3 bps with the
horizon. So this is a clean measurement of the lever, not of a bug.

It **lost** economics at every coverage — +1.75 / +18.79 / +5.27 gross bps at cov 0.01/0.02/
0.05 against the family's +19.38 / +22.03 / +8.91 — while dropping the plateau mean to
0.5058. §2's pre-registered branch is **"no movement in either → the aux head's weighting is
not the constraint. Closed."**

The mechanism is worth recording because it is the third instance of one failure mode. The
weighting made the head **wildly overconfident**: the coverage-targeted gate landed at
`conf ≥ 0.9797` (the baseline's is 0.6311), 84% of bars clear 0.55, and the calibration table
is **flat at `emp_up` ≈ 0.47–0.51 in every bin from 0.05 to 0.95** with brier 0.3156 vs 0.250.
By §3 item 3c that rejects the run on its own, independent of P&L. Up-weighting large moves
teaches the head that confident-and-large is the same axis as confident-and-correct; it is
not, and the probability output — which is M2's entire deliverable to M3 — stops meaning
anything.

#### R3a / R3b — capacity is not the constraint, in either direction

**R3a (128 units) is the clearest memorization result in the project.** `loss_tr` falls to
**0.888** against the baseline's ~1.72 floor while `loss_va` never gets below **1.0440** —
worse than the family's 1.0398–1.0404 at *every* epoch. That is R1's mechanism reproduced
with parameters instead of columns, and it is why §5's transformer bar stands. Its brier is
**0.4187**, the worst in the ledger: 110,628 bars predicted at p(up)=0.023 and 106,168 at
p(up)=0.976, with `emp_up` flat at 0.47–0.50 across all ten bins. The confidence distribution
has collapsed to the corners while carrying no information. It also inverts §1.2's regime
pattern (window 3 becomes its *best* at 0.585, window 1 its worst at 0.500), which is the
signature of a model fitting something other than the shared structure.

**R3b (32 units) is the more interesting arm and it is a clean null.** Plateau mean 0.5199
over a **36-epoch plateau** — the longest in the project — brier 0.2507 against the
baseline's 0.2501, a monotone calibration table, and §1.2's window pattern reproduced almost
exactly (w1 0.549 / w2 0.621 / w3 0.457 / w4 0.622, against seed 3's 0.593/0.592/0.491/0.621).
Its economics are +20.07 / +16.20 / +4.74, inside single-seed spread of the family. **Half the
width, ~15k parameters instead of ~56k, and it matches.**

Both arms land below 0.5239 — R3b by 0.0040, R3a by 0.0054 — and neither comes near the
+0.011 that §2 required for "capacity is live". **Be precise about which branch fires:** R3b is
inside the pre-registered ±0.005 "flat" band; R3a is 0.0004 outside it, on the *negative* side.
So the literal reading is "one arm flat, one arm marginally worse", which lands in the same
place as "both flat" and more strongly — a lever cannot be live when its upward arm is the
losing one. The bracket also says something the ledger did not have before: 64 units is not a
tuned choice, it is **over-parameterized**, and the encoder is sitting on a flat top between 32
and 64 with a cliff into memorization above it.

#### What did NOT change, and should not be over-read

- **The book-era split is still underpowered, not alarming.** O8's book-era cov05 `dir_acc`
  of 0.476 looks bad next to pre_book's 0.552, but the three baseline seeds span
  0.571 / 0.486 / 0.624 on `n_dir` ≈ 1,500–2,000. O8 is inside that spread. This split has
  never had the power to say anything and still does not.
- **All four beat the momentum baseline**, which sits at `dir_acc` ≈ 0.47 (i.e. trailing-48-bar
  momentum is mildly *anti*-predictive at 4h). No run is a repackaged momentum rule.

---

## §2 — THE RUN QUEUE

🔴 **The queue is empty of M2 experiments, and that is the finding, not an oversight.**
O8, R2, R3a and R3b have all run (§1.9); the exit condition pre-registered here on
2026-08-22 fired on every clause. **M2 is frozen at the §1.3 baseline.** The superseded
queue text, with the verdict bands each run was judged against, is in
`docs/archive/TRAINING_HISTORY.md`.

| item | what | cost | needs a GPU? |
|---|---|---|---|
| **R0** | 🔴 **re-run the promote — the 2026-08-24 attempt shipped seed 2 at gate 0.55 instead of 0.6311; script fixed, still the only open action** | promote only | no |
| ~~O8~~ | ❌ ran 2026-08-22, flat — data volume is not the constraint (§1.9) | — | — |
| ~~R2~~ | ❌ ran 2026-08-23, negative — economics worse, calibration destroyed (§1.9) | — | — |
| ~~R3a / R3b~~ | ❌ ran 2026-08-23, both flat — capacity is not the constraint (§1.9) | — | — |
| ~~R1~~ | ❌ ran 2026-08-22, decisive negative (§1.6) | — | — |

**Do not queue another M2 run without new *data*.** Six levers have now been tested one
variable at a time on the same baseline — two feature sets, resolution, context length, loss
shaping, model family, ensembling, data volume, and encoder capacity in both directions — and
the only one that ever moved was 15m → 5m. The single condition that reopens M2 is §1.7's:
order-book history deep enough to sit inside the *training* window, which is a calendar
problem (≈2027, see §5's O5 row), not a modelling one.

### R0 — promote seed 2. Ran 2026-08-24, shipped at the WRONG GATE, must be re-run.

Q2 settled which checkpoint: the ensemble is **not** better than its best member, so the
pre-registered "drop the idea, promote seed 2" branch fires. Q0 already measured seed 2's
gate, and because `--eval-only` never pushes a checkpoint that gate is **not** in the
bucket copy — it must be passed explicitly.

🔴 **What actually happened on 2026-08-24.** The command below was run as written and the
checkpoint *did* land, but `ML_GATE_THRESHOLD=0.6311` never reached the VM: it was set in
the Mac's shell, while the remote `docker compose` interpolates `${ML_GATE_THRESHOLD}` from
the **VM's own `.env`**, which carries `0.55`. Seed 2 therefore went live gating at **0.55**
— not 0.6311, and not even the 0.58 fallback §1.5 warns about. The promote also aborted
before printing `/health` (`curl: (56)`): `serve.py` binds its port before finishing
`torch.load`, and `curl --retry` does not treat a connection reset as transient.

Both defects are fixed in `scripts/gcp_promote.sh`: the gate is now **persisted into the
VM's `.env`** (so it also survives the next unrelated `docker compose up`), `app` is
recreated alongside `ml_inference` when the gate changes because the Elixir signal gate
reads the same variable, `/health` is polled rather than raced, and the script **exits
non-zero unless the served `gate_threshold` equals the value you asked for.**

```sh
./scripts/gcp_promote.sh --list
ML_GATE_THRESHOLD=0.6311 \
  ./scripts/gcp_promote.sh --checkpoint m2_multi_20260819T142759Z_a186182b.pt
```

**Verification is now the script's exit code**, not an eyeballed line: a clean exit means
`/health` came back `ok=true` with `gate_threshold=0.6311`. ⚠️ Do **not** wait for
`gate_source` on this promote — that field was added by C13 (commit `5b8a5e2`), and the
promote deliberately pins serve code to the *checkpoint's own* commit, which for seed 2 is
`a186182b` and predates it. On this deployment the number is the only evidence there is.
⚠️ `checkpoints/latest.pt` is now **R3b's** checkpoint
(`m2_multi_20260823T135748Z_da7ef975.pt`, the 32-unit arm). Never promote `latest`.

**Anything the simulator logged between the 2026-08-24 promote and the re-run was produced
at gate 0.55.** Seed 2's coverage at 0.55 has not been measured, but it is by construction
*wider* than the 2% that 0.6311 realizes, and §1.3's table turns negative at taker cost
somewhere between cov 0.02 and cov 0.05. Treat that stretch of sim output as void; do not
let it become M3's first training data. (One `eval_m2.py --eval-only` on seed 2 would pin
the exact coverage if it ever matters.)

**Why seed 2 and not O8's 12-pair model,** even though 12 pairs is free (§1.9): O8 is a
single seed, its gate has not been derived under C13 against a held-out re-score the way
Q0 derived seed 2's, and it is not the checkpoint any of §1.3's banked numbers describe.
Promote the banked model now; **adopting 12 pairs is a separate, later, deployment change**
(next section) and it should not be bundled into the promote that unblocks M3.

### The only M2 work left, and it is deployment, not research

Both items are optional, neither is on M3's critical path, and neither is an experiment.

1. **Adopt the 12-pair config for the served model** (§1.9). Cheap and a better product:
   four more instruments at an unchanged measured edge. Do it by re-running O8's exact
   command at seeds 2 and 3 (~8h GPU, serial) so the served model has the same 3-seed
   evidence §1.3 has, deriving the C13 gate on the chosen seed. **This buys coverage, not
   edge — do not report it as an improvement, and do not do it before R0.**
2. **Consider `HIDDEN_SIZE=32` as the served encoder** (§1.9). R3b matched the baseline on
   one seed with a quarter of the parameters and the longest plateau in the project. That
   is a real inference-cost and robustness argument, but it is one seed against three, and
   the current model is the one whose numbers are banked. **Default: keep 64.** Revisit only
   if serving cost ever becomes a live constraint.

### For M3 — the work has moved to `docs/M3_PLAN.md`

🔴 **M3 is planned in its own document now. Do not restate it here** — a second M3 narrative
in the training plan is exactly how this file grew to 2,400 lines the last time.

The handover in one line: §1.8's `btc_absret_1d` is the largest measured effect in the
project (top-2% slice from +22.0 to **+54.9** gross bps/trade), it is an **input to the
policy**, and it must **not** be implemented as an M2 gate (§1.8, §5).

`docs/M3_PLAN.md` carries the rest: the three M2 findings that constrain the policy
(coverage is a decision variable; calibration is fragile; confidence thresholds do not
transfer between checkpoints), the ordered sequence, the fee assumption that underwrites
half the published economics, and what to bring back at each step. It also records that
**the Q1 harness was never committed** — `btc_absret_1d` exists only in prose — so M3's
first task is rebuilding it against §1.8's published table.

---

## §3 — WHAT TO BRING BACK (for the next session)

⚠️ **No M2 run is queued (§2), so this section is dormant** — it is kept because it is the
protocol that made the last four waves decidable, and because the 12-pair adoption runs in §2
(if they are ever done) must follow it. If you are here to analyze a *new* run, something has
gone wrong with §2's freeze; check §5's "M2 as a research object" row before spending GPU.

🔴 **One addition the closing wave earned, and it is now the fastest way to kill a bad run:**
read the `SERVED GATE (C13, coverage-targeted)` line first. The baseline's is `conf ≥ 0.6311`.
**A gate above ~0.90 means the confidence distribution has collapsed to the corners and the
calibration table will be flat**, whatever the LB says — R2 (0.9797) and R3a (0.9999) were both
diagnosable from that single line before any other number was read.

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
L=logs/R3a.log                             # repeat for each run in the wave
grep -nE 'resolved knobs|knob |Pair embedding|Training pairs|primary=|Split global_time' $L
grep -nE 'WARNING \[norm\]|max\|z\||BROKEN SCALE' $L
grep -n  'P&L sim:' $L                     # hold must be horizon_min / bar_min (5m/240m ⇒ 48)
grep -n  'Early stop at epoch' $L           # must NOT be 1 + patience
grep -n  'Samples:' $L                      # 5m/8 pairs ⇒ ~2.90M
grep -n  'epoch LB series' $L               # the §0.3 verdict metric, printed by C10
grep -n  'Feature columns:' $L              # the count you intended (19 for R3)
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
   🔴 **This check has now rejected four runs on its own — P2 (0.323), R1 (0.286), R2 (0.316)
   and R3a (0.419), against a baseline of 0.250 — and it caught all four *before* the P&L
   table did.** Three of them were changes that had nothing to do with calibration (a
   resolution change, a loss weighting, a width change), which is the point: on this problem
   the probability scale is the first thing to break and the last thing anyone thinks to look
   at. Treat `brier > ~0.27` as a rejection, not a caveat.
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
| **O8** `20260822T012619Z` | **12 pairs** (+ADA/AVAX/LINK/XRP), 4.59M samples (+58%) vs the 8-pair baseline | 240m | **plateau mean 0.5222 (n=17) on the 12-pair population; ≈0.512 pair-mix-corrected to the 8-pair universe** | ✅ valid, **flat — closes data volume** | 58% more training data moved nothing. Re-aggregated locally on `eval_preds.parquet` (harness validated by reproducing the logged 12-pair table exactly): on the **original 8 pairs** gross bps +23.9 / +21.3 / +6.8 at cov 0.01/0.02/0.05 vs the 3-seed family's +19.4 / +22.0 / +8.9 — one seed inside the family spread at every coverage. The 12-pair aggregation reads +0.010 higher than the 8-pair one at the selected epoch (0.543 vs 0.533) purely from pair mix, which is why the headline LB is not the verdict. Inside §2's pre-registered "≤ 0.527 ⇒ data volume is not the constraint" band. 🟢 **But adopting 12 pairs is free:** brier 0.2495, monotone calibration, majors undegraded, new pairs individually good (LINK cov05 0.599, XRP 0.606). A product win, not a research result. §1.9 |
| **R2** `20260822T170844Z` | **`DIR_MAG_WEIGHT=1`** — directional CE weighted by realized \|forward return\|, normalized per (pair, horizon) | 240m | **plateau mean 0.5058 (n=12); all-epoch 0.5102±0.011 (n=37)** | ✅ valid, **negative — closes the lever** | Instrumentation green (`scale` 0.982–0.989, `at_clip` 0.56–0.77%, `mean\|r\|` 100.5/201.9/501.3bps rising with horizon), so this measures the lever and not a bug. It **lost** economics at every coverage: +1.75 / +18.79 / +5.27 gross bps at cov 0.01/0.02/0.05 vs +19.4 / +22.0 / +8.9. §2's "no movement in either ⇒ closed" branch. 🔴 **Calibration destroyed** — coverage-targeted gate at `conf ≥ 0.9797` (baseline 0.6311), 84% of bars above 0.55, `emp_up` flat at 0.47–0.51 in all ten bins, brier 0.3156 vs 0.250 ⇒ also rejected by §3.3c. Up-weighting large moves conflates "confident and large" with "confident and correct". §1.9 |
| **R3a** `20260823T053017Z` | **`HIDDEN_SIZE=128`** — double width, all else byte-identical to §1.3 | 240m | **plateau mean 0.5185 (n=26); all-epoch 0.5182±0.013 (n=58)** | ✅ valid, **negative** | The project's clearest memorization result: `loss_tr` → **0.888** against the baseline's ~1.72 floor while best `loss_va` = **1.0440**, worse than the family's 1.0398–1.0404 at *every* epoch — R1's mechanism reproduced with parameters instead of columns. Gross bps +13.4 / +12.0 / +3.5. 🔴 **brier 0.4187, the worst in the ledger**: 110,628 bars at p(up)=0.023 and 106,168 at 0.976 with `emp_up` flat at 0.47–0.50 — the confidence distribution collapsed to the corners carrying no information. Inverts §1.2's window pattern (w3 becomes its best at 0.585). §1.9 |
| **R3b** `20260823T135748Z` | **`HIDDEN_SIZE=32`** — half width, all else byte-identical to §1.3 | 240m | **plateau mean 0.5199 (n=36 — the longest plateau in the project); all-epoch 0.5194±0.013 (n=37)** | ✅ valid, **a clean null — with R3a this closes capacity for good** | −0.0040 vs 0.5239, i.e. flat. brier **0.2507** vs the baseline's 0.2501, calibration monotone, §1.2's window pattern reproduced almost exactly (0.549/0.621/0.457/0.622 vs seed 3's 0.593/0.592/0.491/0.621), gross bps +20.1 / +16.2 / +4.7 — inside single-seed family spread. **A quarter of the parameters (~15k vs ~56k) and it matches.** With R3a, the encoder sits on a flat top between 32 and 64 with a cliff into memorization above: `hidden_size=64` is not tuned, it is over-parameterized. §1.9 |
| **R1** `20260821T182844Z` | **25 columns** = 19 legacy + the 6 own-pair multi-scale (`ret_1h/4h/1d`, `vol_1h/4h/1d`); the well-conditioned half of C12 | 240m | **plateau mean 0.4979 (n=11); all-epoch 0.4889±0.016 (n=38)** | ✅ valid, **decisive negative — closes the lever** | −0.026 vs the family's plateau 0.5239 (between-seed sd 0.0032) ≈ 8σ. Worse than Q3 on every axis. 🔴 **Best `loss_va` = 1.0451, above the family's 1.0398–1.0404 at *every* epoch including epoch 1** — so this is not an overfitting story a `DROPOUT` arm could rescue, and that branch is withdrawn. Calibration flat (`emp_up` ≈ 0.48 in every bin 0.10→0.80; brier 0.286) ⇒ also rejected by §3.3c. Gross bps +8.0 / +11.7 at cov 0.01 / 0.02 vs +19.4 / +22.0. Selected ep 18 sits +0.11 `loss_va` above its own minimum. Mechanism: at seq 384 all six columns are exact functions of bars already in the window ⇒ zero information, six easy-to-memorize channels. §1.6 |
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
| **Encoder capacity / layers / hidden** | 🔴 **CLOSED ON MEASUREMENT, 2026-08-23 — R3a and R3b both ran** | It was reopened once, on the one legitimate basis (the plateau-restricted mean resolves ~0.01, so a single run can now decide), and the bracket was run as designed. **Both arms are flat on the low side**: 128 units → plateau mean 0.5185, 32 units → 0.5199, against 0.5239 (between-seed sd 0.0032). Neither approaches the +0.011 the pre-registration required. The bracket also refutes the *shape* of the hypothesis, not just its size: going up produces pure memorization (`loss_tr` 1.72 → 0.888 with `loss_va` never reaching baseline, brier 0.419), and going *down* to a quarter of the parameters changes nothing. There is no monotone curve to climb, so **no third run is justified and this is closed for good.** §1.9 |
| **Training data volume / pair count** | **Closed (new, 2026-08-22)** | O8 added ADA/AVAX/LINK/XRP for 4.59M samples, +58%, the largest data increase available without new *kinds* of data. Re-aggregated onto the original 8 pairs it is inside the 3-seed family's spread at every coverage (+23.9 / +21.3 / +6.8 vs +19.4 / +22.0 / +8.9), and the pair-mix-corrected plateau mean is ≈0.512 vs 0.5239. Crypto pairs are highly correlated, so 58% more *rows* is far less than 58% more independent observations — the effective-sample gain was small and the measured gain is zero. Do not start a pair-count ladder; the remaining whitelist pairs are shorter-history and would be worse. **This does not bar adopting 12 pairs at serve time** — it is free, it just is not an improvement (§2). §1.9 |
| **Magnitude / cost-shaped training losses (`DIR_MAG_WEIGHT`)** | **Closed (new, 2026-08-23)** | R2 was the second and better-designed attempt at teaching M2 about economics rather than accuracy (N3's selection-time cousin was the first, closed 2026-08-18). It ran correctly — `at_clip` under 1%, `scale` ≈ 0.98, `mean\|r\|` rising with horizon — and it lost gross bps/trade at every coverage while driving brier from 0.250 to 0.316 and flattening `emp_up` to ≈0.48 in all ten bins. The mechanism generalizes past this one knob: **up-weighting large moves teaches the head that "confident and large" is the same axis as "confident and correct", and it is not.** Position sizing by expected move magnitude is M3's job and belongs in the policy, where it can be applied without corrupting the probability M2 exists to emit. §1.9 |
| **M2 as a research object** | 🔴 **FROZEN, 2026-08-24 — the exit condition fired** | Written down in advance on 2026-08-22: "if O8 and R3 both come back flat (within ±0.005 plateau-mean LB of 0.5239) **and** R2 does not move gross bps/trade at cov 0.02 by more than +5, M2 is frozen at the §1.3 baseline and every remaining hour goes to M3." O8 −0.0017, R3b −0.0040, R3a −0.0054, R2 −3.2 bps. **Every clause fired.** Eight levers have now been tested one variable at a time against the same baseline — two feature sets, bar resolution, context length, model family, ensembling, loss shaping, data volume, and encoder capacity in both directions — and exactly one (15m → 5m) ever moved. The single reopening condition is §1.7's: order-book history deep enough to sit inside the *training* window, ≈2027. Do not queue an M2 run before then. §1.9, §2 |
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

### The C-batch — DONE 2026-08-22 (unblocks R1)

- ✅ **C15 — the two Q3 conditioning defects.** Three changes, all in the market-context
  path, plus a detector that would have caught the first one:
  1. **`beta_btc_1d` no longer computes BTC's beta against itself.** It is `cov(r,r)/var(r)`
     = 1 identically, so it carried no information for that row; it was emitted as 1.0
     everywhere except a handful of warm-up / sub-floor bars at 0.0, giving a raw std of
     ~1e-3 — above the `1e-8` CONSTANT threshold, so it was never zeroed, and the
     normalizer rendered those few bars as a **590σ** spike. The BTC row now emits a clean
     constant and the existing degenerate handler zeroes it, exactly as it already did for
     `btc_rel_ret_1h` on that row. Verified: BTC's column is now single-valued and
     `std <= 1e-8`; other pairs' betas are unchanged and still computed.
  2. **The beta variance floor is relative, not absolute.** `b_var > 1e-12` sat ~6 orders
     of magnitude below a real `var(ret_1)` (≈2.3e-6 at 5m), so it floored nothing — trap
     §0.5.5 in yet another costume. It is now a fraction of BTC's own median rolling
     variance (`BETA_VAR_FLOOR_FRAC`, default 0.01), so it means the same thing at 1m, 5m
     and 15m and for a quiet pair as for a loud one. Verified: on normal data it masks
     exactly the one warm-up row, and on a deliberately dead 24h stretch it masks that
     stretch instead of dividing by ~1e-14.
  3. **`norm_range_report` now distinguishes a degenerate spike from a fat tail.** `max|z|`
     alone cannot: in test, a genuine heavy-tailed column reached **694σ** and a degenerate
     one only **573σ**. The discriminating signal is how *populated* the tail is. The report
     now counts rows beyond the clip and prints either
     `<== DEGENERATE SPIKE (7 of 2300000 rows beyond 50 sd)` or
     `(heavy tail … 69 rows beyond — a populated tail, not a spike)`. Add this to the §0.4
     scan; it is the check that would have caught `beta_btc_1d` from Q3's log alone.
  4. 🔵 **`xs_disp_1h` is NOT a defect — that claim in the first Q-wave writeup was wrong
     and is withdrawn.** Measured on the val window, cross-sectional dispersion has a
     genuinely *populated* tail (347 rows beyond 5σ, 44 beyond 10σ), which is the same class
     as `hl_range`'s long-accepted 212–364σ and is what a real market-wide volatility event
     looks like. Its 122σ is a fat tail, correctly winsorized at ±50. **No change made.**
     Q1 separately shows dispersion carries no economic signal (§1.8), so the reason to drop
     it is uselessness, not breakage — and R1 drops the whole group anyway.
- ✅ **C16 — `max_dd` is a drawdown again.** `eval_m2.py` built its equity curve from
  `sorted(day_net.values())` — the daily P&L sorted by **value**, so every losing day came
  first and `max_dd` was simply "the sum of all negative days", a deterministic artifact in
  **every log written before 2026-08-22**. Now `[day_net[d] for d in sorted(day_net)]`,
  which is chronological (`_ns_to_day` emits `YYYY-MM-DD`). **Bundled fix:** the running
  peak started at day 1's equity rather than at 0, so a strategy that lost from the first
  day was measured against its own first loss; the curve is now prepended with 0.
  `daily_sharpe` was never affected (mean and std are order-invariant). Verified against
  four hand-computed sequences. ⚠️ **Every `maxdd` printed before this fix should be
  ignored, not re-interpreted** — including those in §4's ledger and in the archive.
- ✅ **C18 — the `FEATURE_GROUPS` knob.** `FEATURE_COLS` was the unconditional
  concatenation of the three groups and `FEATURE_DIM` was asserted equal to its length, so
  running a subset meant editing source. `FEATURE_GROUPS` (default
  `legacy,multiscale,market`) now composes the list and `features.FEATURE_DIM_EFFECTIVE` is
  derived from it; the model, the checkpoint meta and the empty-bundle placeholders all
  follow the derived value. Details that matter:
  - **The default is byte-identical to the 30-column set** — verified — so this is a no-op
    unless set.
  - **Group order is canonical, never the order typed.** `market,legacy` resolves to
    `legacy,market`, because `LEGACY_FEATURE_COLS == FEATURE_COLS[:19]` is a serving
    contract.
  - **It raises rather than falling back** on an unknown group, on an empty spec, and on
    dropping `legacy` — a silent fallback on a feature-set knob would make a run
    un-attributable, which is the whole reason the knob exists (trap §0.5.3).
  - **`ALL_FEATURE_COLS` is new and is what reconstructs old checkpoints.** Rebuilding the
    columns of a checkpoint that recorded none is *positional*, so it must index the
    canonical 30, not whatever subset this process is configured for — otherwise a
    30-column checkpoint re-scored under `FEATURE_GROUPS=legacy,multiscale` would be
    rebuilt from a 25-entry list. `eval_m2.py` and `serve.py` both use it now.
  - **`FEATURE_GROUPS` is in `FLUX_TRAIN_ENV_KEYS`** (§7) — without that it would be a
    silent no-op on the GPU VM and R1 would quietly re-run Q3 (trap §0.5.7).
  - Training logs now echo `Feature groups: legacy,multiscale -> 25 columns (…)` next to
    `Training pairs:`.

### Later

- ⬜ **C17 — print the plateau-restricted epoch-LB mean.** C10 prints the all-epoch mean,
  which §0.3 now shows is not comparable between runs whose overfitting onset differs. Add
  `plateau: n=… lastEp=… mean=…` (epochs whose `loss_va` is within 0.02 of the run's
  minimum) to the same summary line, and warn when the plateau is under ~15 epochs. Until
  it ships, §3 has the one-liner that computes it.

- ⬜ **C19 — triage `hl_range`'s spike-shaped tail (low priority, no run blocked).** C15's
  detector fires on `hl_range` for six of eight pairs with `max|z|` 66–364 and only 2–4 rows
  beyond 50σ out of ~420k, which its rate-based rule correctly calls a spike rather than a
  populated tail (SOL at 6 rows and HYPE at 2-of-128k fall the other side and are labelled
  benign). `hl_range` is a **legacy** column, so the 3-seed baseline in §1.3 has carried this
  from the beginning and R1 did not introduce it — the values are byte-identical to Q3's.
  Handful-of-rows scale, winsorized at ±50, so the practical impact is nil. Worth one query
  on the VM to confirm those rows are real flash candles rather than a bad bar, and then
  either whitelist the column in the detector or drop the offending bars. **Do not treat a
  `DEGENERATE SPIKE` on `hl_range` as a reason to void a run** — update §0.4's row to say so
  when this is resolved.

- ✅ **C3 — magnitude-weighted directional loss. DONE 2026-08-22. Unblocks R2.**
  `DIR_MAG_WEIGHT=1` weights each moved bar's directional CE by its realized
  `|forward return|`, so being right on a large move counts for more than being right on a
  small one. Two design points carry the weight of the change:
  - **The weight is normalized per (pair, horizon)** against that cell's train-window mean
    `|r|`. 1000PEPE's typical move is ~10× BTC's and a 24h move is an order of magnitude
    larger than a 1h one, so a raw `|r|` weight would silently reweight the *pair mix* and
    the *horizon mix* rather than the move sizes — trap §0.5.8 in a new costume. Measured on
    a 3-pair fixture whose pairs differ 10× in `|r|`: per-pair mean weight comes out
    0.998 / 1.002 / 1.000, a 0.4% spread. Within a pair, top-quintile moves outweigh
    bottom-quintile by **25.7×**.
  - **`scale` renormalizes E[w] to exactly 1.0 on the train window** after the power and the
    clip, so `DIR_LOSS_WEIGHT` keeps its meaning and the printed loss stays comparable to an
    unweighted run. Verified `mean=1.000000`.
  - Knobs: `DIR_MAG_WEIGHT` (default **off**), `DIR_MAG_WEIGHT_POWER` (default 1.0 =
    P&L-proportional; 0.5 is the gentler arm), `DIR_MAG_WEIGHT_CLIP` (default 5.0 — one
    20σ bar must not own a batch's gradient). All three are in the launcher allowlist and
    are echoed by the generic `knob K=V` loop, on both the GPU and CPU paths.
  - **Off is byte-identical to the incumbent** — asserted, not assumed: the weighted
    reduction `sum(cw·w·ce)/sum(cw·w)` reduces exactly to
    `nn.CrossEntropyLoss(weight=dw)`'s `sum(cw·ce)/sum(cw)` when every `w` is 1, and the
    check compares the two to 12 decimal places.
  - A degenerate pair (all-zero returns) falls back to the global mean with a relative
    floor rather than dividing by ~0 — §0.5.5 applied to a divisor.
  - **Regression check:** `docker compose --profile ml run --rm --no-deps ml_trainer python
    check_c3_dir_mag.py` (7 groups, all passing). Re-run it if the directional loss or the
    class-weighting path is touched.
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

Needs only `pandas pyarrow numpy`; a throwaway venv is fine. It never runs on the VM.

### Related docs

- `docs/M3_PLAN.md` — **the policy milestone, which is where the work goes now.** M2's
  handover, the constraints it imposes on the policy, and the ordered sequence.
- `docs/archive/TRAINING_HISTORY.md` — the full session narrative, 2026-07-23 → 2026-08-21,
  including the O-wave as written before seed replication corrected three of its claims.
- `docs/DATA_COLLECTION_AUDIT.md` — what the collector captures vs silently drops.
- `docs/QUANT_AB_HANDOFF.md` — quantile-head A/B and its deferral.
- `MODEL.md` — architecture contract; §4.3 labels, §4.4 architecture options.
- `AGENTS.md` — Docker-only workflow, data-lives-on-the-VM rule.
