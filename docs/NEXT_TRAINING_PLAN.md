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
| `[norm] <pair>: max\|z\|=` | must NOT say `BROKEN SCALE` — with one traced exception: `ETHUSDT … on 'spread_bps'` on any run whose val window contains **2026-09-01 18:30 UTC**. That is a single 8.2-bps bar against a spread pinned at one tick for the whole era (train std 0.013 bps), clipped to ±50 and absent from training; BOOK_ERA_PLAN §R.2. Any *other* pair or column saying it is still a void | all pre-`2e7b272` runs |
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
10. **`gcp_gbt.sh` restores `dumps/latest.sql.gz` (cache ≤ 30 min), so a "seed-fixed"
    re-run is not a reproduction unless the dump is the same.** B3b's 5m re-emit got a dump
    made 105 min after B3's: the val window moved 21 bars, the fit saw 0.4% different rows,
    and the 2.7-day fold LBs moved by up to 0.06 (BOOK_ERA_PLAN §R.3). Each run's dump *is*
    snapshotted as `dumps/<RUN_ID>.sql.gz`; a digit-for-digit reproduction needs a knob to
    restore a named one, which does not exist yet. Also the general form of trap 7 — `VAL_FRACTION`
    was another config.py knob the GBT launcher did not forward until 2026-09-11.
11. 🔴 **The staleness caps have never fired (found 2026-09-24).** `features._align_with_age`
    turns the grid-minus-source difference into minutes by dividing `.asi8` by 6e10 — nanoseconds.
    Every training image since T1 and the VM's inference image run pandas 3.0.x (3.0.5 / 3.0.6 in
    the logs), where DB-loaded and parsed timestamps are `datetime64[us]`, so every age is 1000×
    too small: a bar 8 hours from the last funding row reads as 0.48 minutes. `BOOK_MAX_AGE_MIN`,
    `TRADES_MAX_AGE_MIN` and `FUNDING_OI_MAX_AGE_MIN` therefore never trip; a source is "stale"
    only before its first row, and `has_book` / `has_trades` / `has_funding_oi` are 1 from that
    row onward whatever the gap. Training and serving share the code and the pandas version, so
    the served model sees exactly what it was trained on — this is a recipe property, not a
    train/serve skew, and every banked number (folds, X0–X8, U12) carries it uniformly. Exposure
    on the served path is small: the book/trade columns are forced to zero anyway (CONSTANT in
    train), so only `funding`, `oi`, `oi_chg` and `has_funding_oi` are live, and the collector
    rarely gaps. **The fix is built as `ALIGN_AGE_FIX=1`** (config.py; unit-aware Timedelta
    arithmetic; recorded in the checkpoint `meta`, bound at serve time from that meta, shown on
    `/health`, forwarded by `gcp_train.sh`, reported as recipe drift and refused on folds without
    `ALLOW_RECIPE_DRIFT=1`; regression test `ml/train/tests/test_flow_features.py` pins both
    behaviours). **Default OFF**, and off for X8-F and X8b, which reuse banked controls; it goes
    ON together with X5's `SPLIT_EMBARGO` in the first family whose control is retrained from
    scratch. Found by X8b's synthetic alignment test, which asserted minutes and got thousandths.
12. 🔴 **Binance's archive labels a 5-minute bucket by its START and stores the value at its
    END (found 2026-09-24, X8b's identity check).** The collector stamps the account ratios
    with the exchange's bucket timestamp (the end) and open interest with its poll time. Unshifted,
    archive and collector disagreed on the two account ratios by exactly one bucket's move (p99
    1.3–3.1 %, medians ≈ the series' own 5-minute median change); re-labelled +5 min they are
    identical (median 0.011 %, p99 0.02–0.03 %, all twelve pairs). The taker ratio, a bucket
    aggregate, aligns unshifted. Open interest shows the same direction: nearest-match p99
    0.36–0.96 % unshifted vs 0.08–0.28 % shifted. **Consequence for X8:** its training data
    carried, at bar T, the open interest of T+5 min — the value at the bar's close — while serving
    forward-fills the collector's last poll at or before T, the value at the bar's open. One bar
    of freshness on a slow variable; `oi_chg` is the same series one bar earlier. Not a lookahead
    past the decision instant (the bar is acted on after it closes), but a train/serve
    difference. The loader now re-labels the archive's account ratios unconditionally
    (`db.ARCHIVE_FLOW_ACCOUNT_SHIFT_MIN = 5`, pinned to `m3/archiveoi.py`'s copy by the test) and
    open interest under `ARCHIVE_OI_SHIFT_MIN` (default 0 = X8 exactly; 5 = the served
    convention), recorded in the checkpoint meta and reported as launcher drift. Whether X8 is
    re-run under the served convention before X8-F is a decision for Vadim (BACKLOG X8-F).
13. 🟡 **Unpinned pip dependencies change between image builds (found 2026-09-25, X8′ seed 3).**
    `gcp_train.sh` builds `ml_trainer_gpu` from scratch on every fresh VM, so a release on PyPI
    between two seeds of one family changes the image under it. SQLAlchemy 2.1.0 shipped between
    the seed-2 build (2026-09-24 ≈15:30 UTC) and the seed-3 build (2026-09-25 02:30 UTC); 2.1
    resolves `postgresql://` to the psycopg 3 driver, which the image does not carry, and the run
    died at `DB table counts` with `No module named 'psycopg'` before loading anything. Fix: both
    requirement files hold `SQLAlchemy>=2.0.0,<2.1` (resolves to 2.0.54 — the exact version seeds
    1 and 2 trained under; nothing numeric depends on it). The failed log is kept as
    `logs/X8p_s3_failed.log`; seed 3 is relaunched unchanged. Go/no-go for any run: the
    `Successfully installed` line should name the same versions as the family's earlier seeds —
    a new major of pandas, numpy, torch or SQLAlchemy there is a recipe change, not noise.

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

**U12 is done: seed 2 (`20260916T164212Z`) was promoted 2026-09-20 as the twelve-pair served
checkpoint, certified by the walk-forward folds after failing one-split Tier 1 (record below).
Nothing is queued.** It is not a lever and
it does not reopen §5: no knob changes, only the pair set, and the pair set it moves to is the
one the walk-forward folds already train on. X0/X1 and X2, the two levers the freeze *was*
reopened for, both ran and both closed WORSE (below); §5's freeze stays sealed and its only
reopening condition is still §1.7's (≈2027). Everything else open or parked is in
[BACKLOG.md](./BACKLOG.md), which is the list to read — not this section.

### 🔵 U12 — a twelve-pair checkpoint for the served universe. REGISTERED 2026-09-16, RUN 2026-09-16→17, READ AND **PROMOTED 2026-09-20** (failed one-split Tier 1; certified by the folds)

🔴 **This registration is written before any U12 number exists. Nothing below may be edited
once the first log is read** (M3_PROTOCOL §0).

**The defect that forces it, found 2026-09-16.** The served checkpoint
`m2_multi_20260819T142759Z_a186182b.pt` (sha `882cd41…`) was trained on **eight** pairs, but
the live path serves **twelve**. `serve.py:314` `_servable_pairs()` — the T5 fix — intersects
the whitelist with the checkpoint's own `meta["pairs"]` and is applied only on `/predict_all`
(`serve.py:636`). The engine does not use that endpoint: `signal_engine.ex:146` loops
`active_pairs()` and calls `/predict?symbol=` per pair, which has no ceiling. Verified live on
`fluxtrader-1`: `/predict_all` returns 8 pairs, `/predict?symbol=XRPUSDT` returns a prediction.
So ADA / AVAX / LINK / XRP resolve to `pair_oov_id` — an `nn.Embedding` row no pair ever
trained (`config.py:189`, `PAIR_EMBED_DIM=8`) — which is precisely the T5 defect
(M3_PLAN §0.6), still live on the single-symbol path. Measured on the forward test's own
untouched `policy_bars` (2026-09-11 → 09-16, 17,349 bars): **84 of the 109 bars above the
frozen cut (77%), and 7 of the 12 closed policy trades, come from those four OOV pairs**;
XRP alone is 50, and five of the eight *trained* pairs never cleared the cut at all.

**Why twelve and not eight.** The twelve walk-forward folds are trained on the twelve
(`WALKFORWARD_PROTOCOL.md` §5, and §5.1 check 5 requires "the twelve, not `dumps.BASE8`"),
and `gcp_train.sh:234` defines `FLUX_INCUMBENT_PAIRS` as the twelve. **W1 = +33.23 net bps,
CI [+9.28, +57.17] — the CONFIRMED verdict this project rests on — is a twelve-pair result.**
Promoting a twelve-pair checkpoint puts the served model back onto the recipe the folds
validated. Decided by Vadim 2026-09-16.

**Why fresh seeds and not the three that exist.** O8 `20260822T012619Z`, T1 `20260827T050701Z`
and T2 `20260827T114122Z` are already a three-seed twelve-pair family on this exact recipe
(verified from their logs: `SEQ_LEN=384`, `CANDLE_INTERVAL=5m`, `PAIR_EMBED_DIM=8 n_pairs=12`,
`HORIZONS=60,240,1440 PRIMARY=240`, `FEATURE_GROUPS=legacy`, `EARLY_STOP_PATIENCE=20`,
`Split global_time val_frac=0.2`). They are not used: all three were trained *and* scored
before the 2026-09-04 candle repair, so every T6 number about them is on partial bars. Vadim
chose fresh training over a re-score on 2026-09-16.

**The recipe — identical to the incumbent in every knob, pair set excepted.**
`FEATURE_GROUPS=legacy CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 EARLY_STOP_PATIENCE=20`,
`TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240`, `TRAIN_PAIRS` = the twelve, `60 384`, no
`VAL_OFFSET` / `TRAIN_FRACTION` so the split is `global_time val_frac=0.2 val_offset=0.0`.
`SPLIT_EMBARGO` stays **off**. X5's row reserves the right to switch it on "in the recipe of
the next registered M2 family" — but the whole point of U12 is recipe identity with the folds,
which ran before the knob existed, so turning it on here would break the one property being
bought. It is deferred to the §1.7 family, unchanged.

**The selection rule, fixed in advance.** Three seeds, `SEED=1,2,3`, one shared snapshot.
The served checkpoint is the **median of the three by plateau-restricted mean LB** (§0.3's
statistic, with §0.3's documented fallback if a plateau is shorter than 15 epochs) — a
selection statistic, never P&L. Ranking the three on net bps would be exactly the shopping §0
forbids. Chosen by Vadim 2026-09-16 over "highest LB".

**The acceptance bar, fixed in advance.** The chosen checkpoint must pass **Tier 1 under
M3_PROTOCOL §9.2 on repaired dumps**, the same bar the incumbent clears (worst window −4.61
against the −5 bps floor, pooled net positive at taker). ⚠️ This is a real risk, not a
formality: T6 §3 found P3, the −5 worst-window floor, failing on *both* universes on
pre-repair data. **If the chosen seed fails Tier 1, nothing is promoted.** The fallback,
pre-committed by Vadim 2026-09-16, is to close the defect the other way — apply the T5 ceiling
on the `/predict` path too, narrow `served_pairs` to the eight trained pairs, void and restart.
Either branch ends with no pair served through the OOV row.

**Then, and only if Tier 1 passes:** derive the served gate under C13 and the ladder p80 under
C4 over the chosen checkpoint's own split; `gcp_promote.sh --checkpoint <key>` with
`ML_GATE_THRESHOLD` set to the derived gate; update the constants in `policy.ex`; back up and
void `paper_trades` + `policy_bars` on the VM; restart the forward clock (**fourth start**);
run the `accept_76.py` replay. M3_5 §4.3's forward registration (R0–R5) is restated against the
new checkpoint — R1's cut levels are per-checkpoint and change with it.

**Expectation, recorded so the result cannot be rationalised afterwards:** the twelve-pair
family lands inside the eight-pair family's between-seed spread on LB (O8 did, §1.9), and
Tier 1 is genuinely uncertain because of T6 §3. U12 is not expected to earn more. It is
expected to make the served universe legitimate.

**Commands: `docs/BACKLOG.md`, the U12 row.** Three serial GPU runs, ~2–3 h and ≈$1.5 each,
plus the fresh dump on the first — about 8–10 h of serial wall clock.

**Bring back, per run (§0.4's checklist):** the `Split …` line; the `=== resolved knobs` block
and `Feature groups: … -> 19 columns`; `Training pairs: [...]` showing **twelve**;
`Pair embedding: ON dim=8 n_pairs=12`; `Early stop at epoch N`; the
`epoch LB series @cov0.05: n=… mean=… sd=… max=… selected=…` line; the `Fixed-coverage
directional edge` and `Fixed-coverage P&L` tables **for the 240m head** (the 60m block is what
produced the retracted "repair bought back edge" headline, RETRAIN_PLAN §4); and the run id.
The read happens in a fresh session — bring the three logs, not a summary of them.

**Result, read 2026-09-20** (`logs/U12_s1.log`, `logs/U12-s2.log`, `logs/U12-s3.log`; dumps in
`ml/train/output/eval_dumps/`). Nothing above this line was edited. All three pass §0.4: twelve
pairs, `Pair embedding: ON dim=8 n_pairs=12`, 19 legacy columns, seq 384, patience 20, and the
identical `Split global_time | val_frac=0.2 val_offset=0.0 | train=3724724 val=931182 | val
[2025-12-14 09:35 → 2026-09-09 20:05 UTC]`.

| run | run id | epochs | all-epoch mean LB | plateau n / mean | selected | cov 0.02 gross bps/trade, 240m |
|---|---|---:|---|---|---|---:|
| U12 s1 | `20260916T070245Z` | 31 | 0.5255 | 17 / **0.5305** | ep 11 (0.5508) | +9.29 |
| **U12 s2** | **`20260916T164212Z`** | 45 | 0.5192 | 26 / **0.5276** ← median | ep 25 (0.5680) | +21.11 |
| U12 s3 | `20260917T023537Z` | 27 | 0.5266 | 27 / **0.5266** | ep 7 (0.5492) | +4.24 |

- **Selection: seed 2, `20260916T164212Z`** — the median by plateau-restricted mean LB. Every
  plateau is ≥ 15 epochs, so the fallback did not fire. The order is the same at four decimals
  (0.53038 / 0.52761 / 0.52665); the s2–s3 gap is 0.001, i.e. the rule picked mechanically
  between two statistically indistinguishable seeds, which is what it is for.
- **The recorded expectation held:** pooled 0.5282 against the eight-pair family's 0.5239
  (0.5209–0.5273) and X0's 0.5258 — inside or at the top of the between-seed spread. Not an
  improvement claim.
- ⚠️ **Deviation 1 — the snapshot is shared but not fresh.** The val window still ends
  2026-09-09: `DUMP_MAX_AGE_MIN=100000` was exported before run 1, so the launcher reused
  `dumps/latest.sql.gz` and BACKLOG's "rm the cache" step bought nothing. The registration
  asks for "one shared snapshot", which holds. Side effect worth keeping: val ends before the
  forward test's first bar (2026-09-11), so C13/C4 constants derived on this split cannot
  touch forward data.
- ⚠️ **Deviation 2 — U12 is X0's recipe on X0's snapshot, and training is near-deterministic.**
  U12 s3 is **bit-identical to X0 s3** (`20260914T193920Z`) on all 27 epoch lines; s1 and s2
  differ from X0 s1/s2 only by GPU nondeterminism. So "three fresh seeds" is in practice a
  second draw of X0, not independent of it. Harmless for the selection rule; it means a
  future "fresh family" needs new seed numbers, not a new launch.
- The 240m fixed-coverage P&L rows are texture, not Tier 1 (no regime ladder, no sizing):
  net at the 14-bps taker line, cov 0.02 → −4.71 / **+7.11** / −9.76.

**Tier 1, run 2026-09-20 — FAIL as registered. Nothing is promoted yet.**
Pinned with Vadim before any policy P&L was read: the incumbent's spec only (`WINNER_SPEC`, the
§3.2 sized variant of `cov0.02_hold240_rqnone_mcnone`), twelve pairs, P1–P6 at the 14-bps taker
line, no grid; the stale snapshot accepted. Command (existing code, nothing changed):
`M3_ERA=repaired ./scripts/m3.sh -m m3 universe --runs 20260916T070245Z,20260916T164212Z,20260917T023537Z`
→ `logs/U12_tier1_20260920.log`. Confidence cuts reproduce each log's cov-0.02 `conf_thr`
(0.694 / 0.671 / 0.591), so the dumps are the runs.

| | trades | pooled net | w1 | w2 | w3 | w4 | s1 / s2 / s3 | P1–P6 |
|---|---:|---:|---:|---:|---:|---:|---|---|
| **U12, 12 pairs, sized** | 2,723 | **+4.95** [−41.6, +51.5] | −0.38 | +17.80 | +3.93 | **−4.64** | −1.85 / +24.35 / −4.83 | Y **N** Y Y **N** Y |
| U12, 8-pair subset, sized | 1,864 | +6.86 | −8.53 | +19.80 | −1.08 | +2.82 | — | Y N N Y N Y |
| U12, 12 pairs, unsized (texture) | 2,729 | −3.34 | −20.87 | +12.63 | +4.19 | −10.70 | −4.71 / +7.11 / −9.76 | fails P1,P2,P3,P5 |
| incumbent of record (8-pair ckpt, repaired) | — | +13.82 | | | | −4.61 (w3) | +8.41 / +11.94 / +21.97 | all Y |

- **Fails P2** (two of four windows positive, three needed) **and P5** (seeds 1 and 3 are
  negative). P3 passes by a hair (−4.64 against −5). Chosen seed 2 alone is +24.35 pooled with
  w3 at −14.3 on 53 trades — one good seed, which is exactly what the family test is there to
  catch.
- **What this does and does not say.** It says this family does not clear the bar the
  registration fixed, so the fallback fires. It does **not** say twelve pairs are worse than
  eight: the pooled interval is ±47 bps, the four new pairs earn +5.69 against the base eight's
  +4.57 inside the same run, and T6 measured P5 failing ~54% of the time on the incumbent's own
  bootstrap. The standing intent to trade twelve is unchanged; the route back is a twelve-pair
  family in the next registered M2 wave (§1.7), or a registration that certifies a fresh
  checkpoint on the walk-forward folds (M3_PROTOCOL §9.3 item 2) — written before its data is read.
- 🔴 **The registered fallback ("serve the eight") is rejected, and the bar is contested —
  2026-09-20.** Vadim: twelve pairs is the decided universe; a failure branch that reinstates
  eight should never have been registered. Two facts on record *before* U12 ran show the
  acceptance bar could not do its job: (1) T6_RESULTS' power table — the **incumbent itself
  fails "all six" in 98.7% of day-resamples** (P3 97.8%, P2 74.7%, P5 52.4%), so one-split
  Tier 1 cannot arbitrate a checkpoint swap; passing at −4.61 and failing at P2/P5 are the same
  coin. (2) RETRAIN_PLAN §8 Q2 chose **(B) walk-forward certification** as how a fresh
  checkpoint is certified, and it came back **CONFIRMED on twelve pairs on this recipe** (W1
  +33.23, CI [+9.28, +57.17], all three seeds positive). This is a defect in the criterion,
  named from prior records, not a threshold lowered after a result; the Tier 1 table above
  stays as the record.
- **Amendment accepted by Vadim 2026-09-20, and the promotion record.** U12 seed 2 — chosen by
  median LB *before* any P&L was read — is served as the full-window instance of the
  fold-certified recipe. **This artefact failed one-split Tier 1 (P2, P5) and is certified by
  the walk-forward folds, not by Tier 1.** Checkpoint `m2_multi_20260916T164212Z_ace3ae5e.pt`,
  sha256 `30e6ac1e0e9233cd88b4ba9fdddba5cefca16a0311c66b34a54d27990977d6cf`. C13/C4 from its
  own split (931,182 bars, twelve pairs): cut **0.6708709597587585** (the trainer's SERVED GATE
  line reads 0.6709), ladder `[0.003849…, 0.008731…, 0.014943…, 0.025370502844452858]`;
  recomputing reproduces 847 trades, mean size 1.295. Deployed 2026-09-20 (`e5e3d12`): promote
  script green at the requested gate, `/predict` ceiling fix live, old ledgers backed up and
  cleared, **forward clock's fourth start 08:15:10 UTC**, health `checkpoint_bound: true` with
  twelve served. R0–R5's per-checkpoint constants restated in M3_5 §4.3 with the ledger empty.
  Still owed: the `accept_76.py` replay of the new start (BACKLOG row 1).
- **Rule carried forward:** no registration may name "serve eight" as a failure branch, and an
  acceptance bar's power on the incumbent is checked before it is registered.

### 🟢 X0 / X1 — the cross-sectional block, separated. CLOSED 2026-09-15: **WORSE** (−0.021)

**Result, read 2026-09-15 in a fresh session** (`logs/X0_s1..3.log`, `logs/X1_s1..3.log`; all
six on `4c2794d`, all six on the identical `Split` line `train=3724724 val=931182 | val
[2025-12-14 09:35 → 2026-09-09 20:05 UTC]`).

| run | run id | recipe check (§0.4) | epochs | all-epoch mean LB | plateau n / mean | selected | cov 0.02 gross bps/trade, 240m |
|---|---|---|---:|---|---|---|---:|
| X0 s1 | `20260913T050118Z` | ✅ 19 cols | 28 | 0.5247 | 21 / 0.5245 | ep 8 (0.5500) | +11.61 |
| X0 s2 | `20260913T094329Z` | ✅ 19 cols | 32 | 0.5248 | 31 / 0.5264 | ep 12 (0.5489) | +18.43 |
| X0 s3 | `20260914T193920Z` | ✅ 19 cols (re-run; the first attempt `20260913T183049Z` was launched at seq 128 and is void, its log overwritten) | 27 | 0.5266 | 27 / 0.5266 | ep 7 (0.5492) | +4.24 |
| X1 s1 | `20260914T020907Z` | ✅ 24 cols, market 12/12 | 26 | 0.4816 | 7 / 0.5174 | ep 6 (0.5424) | +15.44 |
| X1 s2 | `20260914T062650Z` | ✅ 24 cols, market 12/12 | 24 | 0.5189 | 7 / 0.5287 | ep 4 (0.5582) | +11.00 |
| X1 s3 | `20260914T114407Z` | ✅ 24 cols, market 12/12 | 35 | 0.5130 | 4 / 0.4993 | ep 15 (0.5328) | −5.51 |

- **The pre-registered fallback fired:** every X1 plateau is shorter than 15 epochs (7 / 7 / 4),
  so both families are read on the all-epoch mean. X0 = **0.5254** (between-seed sd 0.0011);
  X1 = **0.5045** (sd 0.020). **Contrast X1 − X0 = −0.021**, ≈ 8σ on the registered SE of
  0.0026, every X1 seed below the X0 mean → **WORSE.** The plateau-mean read (the non-fallback
  column) gives −0.011 — every reading is past the −0.008 line.
- **Mechanism — the same one Q3 and R1 showed:** the 24-column runs leave the plateau at epoch
  6–7 (`loss_tr` 1.73 → 1.14 while `loss_va` climbs 1.04 → 1.40); the 19-column controls hold
  it for 21–31 epochs. Five *external* columns were enough new surface to memorise, so
  "external information" was not the exception §5 hoped for. X1 s3's selected epoch (15) sits
  deep in that regime: brier 0.3665, served gate 0.9967, and its 60m head fires the §0.4
  "gates ZERO bars" warning.
- **Secondary reading (not deciding):** pooled cov-0.02 gross on the 240m head, X0 **+10.9**
  over 3,231 trades vs X1 **+5.4** over 2,648 — same direction as the primary, and both well
  inside one SE (~5 bps) of each other.
- **Two `DEGENERATE SPIKE` flags on new columns**, recorded per §0.4 and not a void: `has_market`
  on BTC (1 row of 427k at 591σ) and `xs_disp_1h` on ETH/SOL/ZEC (one shared row at 118σ). A
  single clipped row cannot carry a 0.02 effect.
- **X0 as the repaired-era baseline (banked, three seeds):** all-epoch means 0.5247 / 0.5248 /
  0.5266, pooled **0.5254**, on the banked family's level (§1.3: 0.5248 / 0.5207 / 0.5203).
  Cov-0.02 gross is lower and noisier (+11.6 / +18.4 / +4.2, pooled +10.9 vs +22) on a val
  window that now runs 2025-12-14 → 2026-09-09 over twelve pairs and contains the calm spring —
  walk-forward window 3 (04-28 → 07-04) is 0.50–0.52 at cov 0.05 in every seed, the offline
  face of the forward test's silence. Side counts at cov 0.05 are long-skewed in s1 (43k up /
  3.5k down), balanced in s2 and s3; check per checkpoint, as §1.3 already says.

**What this licenses (as pre-registered):** the lever closes; §5's feature row carries its
second entry; the M2 freeze is re-sealed with its original reopening condition. X0 is banked as
the control family for X2 — same snapshot (`dumps/20260913T050118Z.sql.gz` and its three
copies in the bucket), its three `eval_preds.parquet` under `gs://…/eval/<run_id>/`.

*The registration as written on 2026-09-13 follows, unchanged, as the record of what was
fixed before the logs were read.*

**The question.** Does the five-column market block — `btc_rel_ret_1h`, `beta_btc_1d`,
`xs_rank_1h`, `xs_disp_1h`, `has_market` — move the 240m directional head when it is the
**only** addition to the served recipe?

**Why this is not a re-proposal of a closed lever.** §5's feature row closed the *own-pair*
multiscale channels and says "reopen only for genuinely *external* information". The market
block is external — it is built from the other pairs' returns — and it was never tested on its
own: Q3 carried it inside a 30-column bundle whose six own-pair channels R1 later showed were
the memorisation surface, so Q3's verdict is the bundle's, not the block's. The new evidence
since the freeze is B3's O5 (BOOK_ERA_PLAN §R.3): a tree model given every candle and book
scalar over the book era puts 33–38% of its gain on `xs_disp_1h`, more than any other
feature, at both 5m and 15m. That is evidence the block carries information at short horizons;
whether it carries *directional* information at 240m is exactly what X1 asks. Honest caveat,
written before the run: dispersion is plausibly a magnitude proxy, which would make it M3's
business (the regime row of §5) and not M2's — `xs_rank_1h` and `btc_rel_ret_1h` are the
members with a directional reading (cross-sectional momentum or reversal).

**Why a control family is needed (§0.2).** The banked §1.3 family was trained pre-repair on
a snapshot ending 2026-08-19. A run today trains on repaired candles and a month more history,
so comparing X1 to §1.3 would change data *and* features in one step. X0 retrains the served
recipe, unchanged, on the same snapshot X1 uses; X1 − X0 is then one change. X0 is also the
repaired-era baseline every later lever (X2, BACKLOG) will reuse, so its cost is shared.

**The recipe.** The launcher's pinned incumbent (`FLUX_INCUMBENT_*`, `scripts/gcp_train.sh`):
twelve pairs, `CANDLE_INTERVAL=5m`, seq 384, 60 epochs, horizons 60/240/1440, primary 240,
`PAIR_EMBED_DIM=8`, `EARLY_STOP_PATIENCE=20`, `VAL_FRACTION` default 0.2, labels and loss
unchanged. X0: `FEATURE_GROUPS=legacy` (19 columns). X1: `FEATURE_GROUPS=legacy,market`
(24 columns) — **and nothing else differs**. Three seeds each: 1, 2, 3.

⚠️ **Code prerequisite, done 2026-09-13, must be on `main` before the first X1 run:**
`FEATURE_GROUPS=legacy,market` used to crash the dataset build, because
`data.features.market_context_inputs` sliced a multiscale column (`ret_1h`) the frame no
longer carried. It now derives `ret_1h` from `close` when absent, with the same formula
`build_feature_frame` uses — verified bit-identical over 2,000 synthetic 5m bars, and
`apply_market_context` verified end-to-end on legacy+market frames. The two callers
(`dataset.py`, `serve.py`) pass the candle interval. A checkpoint with the market block
serves through the existing `_fill_market_context` path; nothing on the served path changes
for the 19-column checkpoint.

**One snapshot for all six runs.** The split is a fraction of a growing history (§0.5 trap
10), so six runs hours apart would have six different val windows. Clear the always-on VM's
dump cache **once** before the first run, then pin `DUMP_MAX_AGE_MIN=100000` on every run so
the cache hits and `dumps/latest.sql.gz` is reused; the launcher copies it to
`dumps/<run_id>.sql.gz` each time. **Acceptance:** all six logs print an identical
`Split global_time | … | train [… → …] | val [… → …]` line. If they do not, the run whose line
differs is void — re-run it with the cache intact, do not "correct" for it.

**Order.** Serial, one at a time, each launched after the previous reports DONE (§0.5 — a
second `gcp_train.sh` destroys the live one): X0 s1, X0 s2, X0 s3, X1 s1, X1 s2, X1 s3. If a
run fails, re-run the same seed before moving on.

**The statistic, fixed now (§0.3).** Per run: the **plateau-restricted mean of the per-epoch
cov 0.05 Wilson-LB series on the 240m head** (plateau = epochs whose `loss_va` is within 0.02
of the run's minimum). Per family: the mean of its three seeds; error bar = the between-seed
sd of that mean. The contrast is **X1 family mean − X0 family mean**. From the banked family's
between-seed sd of 0.0032, the SE of a family-mean difference is ≈ 0.0026. Fallback, stated
now: if any run's plateau is shorter than 15 epochs, that arm is read on the all-epoch mean
for *both* families (the §0.3 table's other column), and the verdict says so.

**The gate.**

| contrast X1 − X0 | verdict |
|---|---|
| ≥ **+0.008** *and* every X1 seed above the X0 family mean | **MOVED** |
| in (−0.008, +0.008), or ≥ +0.008 with a seed below | **FLAT** — the lever closes, with the number |
| ≤ −0.008 | **WORSE** — closes, and the §5 feature row gains a second entry |

+0.008 is ≈ 3σ on the difference and half of the one effect that ever moved (15m → 5m,
+0.016). It is deliberately below R3's +0.011 because this is a *family* contrast, not a
single run against a family.

**The secondary reading, reported but not deciding:** the pooled `Fixed-coverage P&L` at cov
0.02 on the 240m head, gross bps/trade, X1 vs X0. With per-trade sd ≈ 150 bps its SE is
~5 bps, so it can only sanity-check: a MOVED verdict whose cov-0.02 gross is more than 5 bps
*below* X0's is reported as MOVED-BUT-NOT-EARNING and licenses nothing.

**Expectation, recorded before the run: FLAT.** Seven of eight levers were flat; the block's
strongest member by O5 is plausibly a magnitude proxy. A FLAT result is a useful result: it
closes the last untested feature family and leaves X0 as the repaired-era baseline.

**What each verdict licenses.** MOVED → fetch both families' `eval_preds`, register `x0` and
`x1` eras in `m3/dumps.py`, and run the *incumbent* rule (not a search) on the X1 family under
M3_PROTOCOL §9 — Tier 1, C3, cut derived on X1's own split — as a promotion candidate. It does
**not** touch the served checkpoint or the running forward test; a promotion is its own
registered clock restart. FLAT / WORSE → close the lever in §5 and BACKLOG; X0 remains banked
for X2. Nothing in the read licenses a fourth seed, a second feature subset, or a re-run with
a different band.

**Commands.** Run from the laptop, in this order. `<12>` is the launcher's incumbent list:
`BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,XRPUSDT`.

```sh
# 0. the features.py fix must be pushed to main first (the train VM clones GIT_REF=main)
git log --oneline -1 -- ml/train/data/features.py      # should show the 2026-09-13 commit

# 1. fresh snapshot, once
gcloud compute ssh fluxtrader-1 --zone me-central1-b --project fluxtrader \
  --command "rm -f /var/tmp/fluxtrader_dump_cache.sql.gz"

# 2. the six runs — serial; wait for DONE (./scripts/gcp_status.sh) before the next
export CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 EARLY_STOP_PATIENCE=20
export TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 TRAIN_PAIRS=<12>
export DUMP_MAX_AGE_MIN=100000

FEATURE_GROUPS=legacy        SEED=1 ./scripts/gcp_train.sh --gpu 60 384   # X0 s1
FEATURE_GROUPS=legacy        SEED=2 ./scripts/gcp_train.sh --gpu 60 384   # X0 s2
FEATURE_GROUPS=legacy        SEED=3 ./scripts/gcp_train.sh --gpu 60 384   # X0 s3
FEATURE_GROUPS=legacy,market SEED=1 ./scripts/gcp_train.sh --gpu 60 384   # X1 s1
FEATURE_GROUPS=legacy,market SEED=2 ./scripts/gcp_train.sh --gpu 60 384   # X1 s2
FEATURE_GROUPS=legacy,market SEED=3 ./scripts/gcp_train.sh --gpu 60 384   # X1 s3

# 3. after each DONE: the log (never --save) and the dump
./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> > logs/X0-s1.log        # X0-s2, X0-s3, X1-s1, X1-s2, X1-s3
gcloud storage cp gs://fluxtrader-train-artifacts/eval/<run_id>/eval_preds.parquet \
  ml/train/output/eval_dumps/eval_preds_<run_id>.parquet
```

Each GPU run is ~2–3 h and ≈ $1.5 (n1-standard-4 + T4 in us-central1-a, §7); six runs are
~15 h of serial wall clock. The first run also waits on the fresh dump.

**Bring back, per run (§0.4's checklist):** the `Split …` line; the `=== resolved knobs` block
and `Feature groups: … -> N columns` (19 for X0, 24 for X1); `Training pairs: [...]`; `Early
stop at epoch N`; the `epoch LB series @cov0.05: n=… mean=… sd=… max=… selected=…` summary;
the `Fixed-coverage directional edge` and `Fixed-coverage P&L` tables for the 240m head; the
run id. The read happens in a fresh session (§0.3's `grep`/`awk` for the plateau mean, then
the table above) — bring the six logs, not a summary of them.

**Two things are queued elsewhere and are not M2 runs:**

* **The walk-forward folds** — twelve serial `gcp_train.sh` runs, pre-registered in
  [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md). They retrain the §1.3 recipe with the
  split boundary moved back; they are not a change to M2 and they do not reopen §5.
* **B3c**, the book-era 15m re-test — one CPU run on `gcp_gbt.sh`, parked until 2026-11-02 (below and in BACKLOG.md).

### 🟢 X2 — volatility-normalised training labels. CLOSED 2026-09-15: **WORSE** (−0.010)

**In plain terms.** The idea was to stop calling every calm-market move "flat", so the model
would learn direction on calm days too. It did not help: the model trained this way memorised
its training data within 4–9 epochs (X0 holds out for 21–31), and its accuracy on the same
validation period, scored the same way, is lower in all three seeds. Its best top-2% trades
earned +8.7 bps gross (before costs) against the control's +10.9 — no better, within noise.
Nothing served changes; M2 stays frozen.

**Result, read 2026-09-15** (`logs/X2_s1..3.log`; s1/s2 on `03d7a22`, s3 on `150d37f` — no
change under `ml/` or `scripts/` between them). All three pass §0.4 acceptance: `Split` line
identical to X0's (`train=3724724 val=931182 | val [2025-12-14 09:35 → 2026-09-09 20:05 UTC]`),
`Feature groups: legacy -> 19 columns`, `Pair embedding: ON dim=8`, the four label knobs
resolved, and the `Labels:` line with k = 0.4076 / 0.4047 / 0.4019 and flat volnorm within
0.0002 of flat fixed at every horizon (0.4153/0.4155, 0.4103/0.4105, 0.3745/0.3747).

| run | run id | epochs | all-epoch mean LB | plateau n / mean | selected | cov 0.02 gross bps/trade, 240m |
|---|---|---:|---|---|---|---:|
| X2 s1 | `20260915T015514Z` | 24 | 0.5117 | 6 / 0.5287 | ep 4 (0.5444) | +9.73 (931) |
| X2 s2 | `20260915T051139Z` | 28 | 0.5144 | 7 / 0.5313 | ep 8 (0.5477) | +4.12 (846) |
| X2 s3 | `20260915T121504Z` | 24 | 0.5212 | 3 / 0.5243 | ep 4 (0.5479) | +11.55 (973) |

- **The pre-registered fallback fired:** every X2 plateau is shorter than 15 epochs (6 / 7 / 3),
  so both families are read on the all-epoch mean. X2 = **0.5158** (between-seed sd 0.0049);
  X0 = **0.5254** (sd 0.0011). **Contrast X2 − X0 = −0.0096**, ≈ 3.3σ on the two families'
  own spread (≈ 3.7σ on the registered 0.0026), every X2 seed below the X0 mean → **WORSE.**
  It lands 0.0016 past the −0.008 line, under one SE — but FLAT and WORSE license the same
  thing, and MOVED (+0.008) is excluded by ≈ 6σ, so the decision does not hang on that margin.
- **Not deciding, reported for completeness:** the plateau-mean read gives +0.002 (0.5281 vs
  0.5258), on 3–7 early epochs that §1.6 says are not comparable with X0's 21–31; the selected
  (max) epoch is below X0's in all three seeds (0.544–0.548 vs 0.549–0.550).
- **Mechanism — memorisation, earlier than any 19-column run:** `loss_tr` leaves 1.78 at epoch
  7 / 9 / 4 and falls to ≈ 1.25 by the stop, and the fixed-label cov-0.05 LB decays with it to
  ≈ 0.50–0.52. This is a training-set fact, not an artefact of `loss_va` being scored on the
  fixed labels: X0 s2/s3 end at `loss_tr` 1.65 / 1.73. A plausible reading (a hypothesis, not
  tested): dividing by a calm day's small σ turns noise-sized moves into directional labels,
  which are easy to memorise and carry no forward information.
- **Secondary reading (not deciding):** pooled cov-0.02 gross on the 240m head, X2 **+8.65**
  over 2,750 trades vs X0 **+10.90** over 3,231 — same direction, well inside one SE (~5 bps).
- **Class mix (`3cls_pred`, reported as registered):** the hoped-for "fewer flats" did not
  appear while the head was useful — over the plateau epochs X2 predicts flat on 80–90% of val
  bars vs X0's ≈ 62%; the mix only turns to ≈ 30% flat once memorisation starts. The checkpoints
  are long-skewed at their served gates (s2: 52 longs / 0 shorts; s3: 3 trades at gate 0.769).
- **Expectation recorded before the run was FLAT;** it came back one bucket lower.

**What this licenses (as pre-registered):** the label row joins §5 and the M2 freeze is
re-sealed with §1.7's reopening condition. Nothing licenses a fourth seed, another k rule,
another window or a second label mode. The X2 checkpoints and dumps stay in the bucket
unregistered; no `x2` era is added to `m3/dumps.py`.

*The registration as written on 2026-09-15 follows, unchanged, as the record of what was fixed
before the logs were read.*

**The question.** The 3-class label calls a 4-hour move "flat" when it is inside a fixed
±0.6% band (`FLAT_TH_4H`) in every regime. In calm months almost every bar is therefore flat
and the directional head learns direction mostly from volatile bars — which is one candidate
reason the served model goes silent in calm markets (M3_5 §4.2; the forward test's three quiet
days). **If the band is measured in units of each pair's own trailing volatility — so a calm
month has as many directional labels as a volatile one — does the 240m directional head move?**

**Why this is not a re-proposal.** §5 closes *magnitude-weighted losses* (`DIR_MAG_WEIGHT`,
R2): up-weighting large moves taught the head that "confident and large" is one axis. X2 does
the opposite — it *removes* the volatility scale from the target, so calm and volatile bars
contribute equally. The only vol-scaled label ever tried was E3's triple-barrier (`E3-tb`),
voided by the pair-embedding rule (§0.2) and never redone; it also changed *what* is labelled
(a path event). X2 keeps the fixed-Δt endpoint sign and changes only the band's shape. The M2
freeze (§5) is reopened for this one lever by Vadim's decision on 2026-09-15, as the last
offline M2 lever with a rationale; its result re-seals the freeze either way.

**The change (§0.2: one).** `LABEL_MODE=volnorm` (built 2026-09-15, `config.py`,
`data/features.py`, `data/dataset.py`): z = fwd_ret / (σ₁ × √h_bars), σ₁ the rolling std of
1-bar returns over `VN_VOL_WINDOW=288` bars (one day of 5m) ending at the bar, floored at
`VN_MIN_SIGMA=1e-5`. UP if z > k, DOWN if z < −k, FLAT otherwise. **k is derived, not chosen:**
per horizon it is the |z| quantile, pooled over all pairs on bars before `VN_CALIB_END`, at the
*fixed* label's own flat share on those bars — the recipe's average band, reshaped per pair and
per time. `VN_CALIB_END=2025-12-14T09:35:00Z` is X0's split boundary, so no validation-window
return enters k. Bars without a full trailing window keep the fixed label, so the valid-sample
set — and therefore the `Split` line — is identical to X0's. Synthetic check (2026-09-15):
fixed labels 89% flat in a calm half and 26% in a volatile half; volnorm 64% / 67%; validity
mask identical; fallback exact.

🔴 **Selection and evaluation stay on the FIXED labels.** The dataset carries both label sets
(`PairSeries.labels_eval`); the validation loader and `eval_m2` read the fixed ones
(`label_set="eval"`). So every printed `dir_acc` / `lb` / `n_dir`, the `sel@cov0.05` early-stop
score and the dump's `y3` are on exactly X0's definition — the contrast below compares like with
like, and X0's own runs are unchanged by the code (fixed == fixed). `loss_va` is cross-entropy
against the fixed labels in both families; for X2 it is not the training objective, so read
the plateau rule as relative-to-its-own-minimum, as §0.3 already does.

**The recipe.** X0's exactly — twelve pairs, 5m, seq 384, 60 epochs, horizons 60/240/1440,
primary 240, `PAIR_EMBED_DIM=8`, `EARLY_STOP_PATIENCE=20`, `FEATURE_GROUPS=legacy` (19
columns) — plus the four label knobs above. **Same snapshot as X0**: `DUMP_MAX_AGE_MIN=100000`
with the cache untouched. Three seeds: 1, 2, 3. **Control = X0, banked** (§2 above: all-epoch
means 0.5247 / 0.5248 / 0.5266, pooled **0.5254**; plateau means 0.5245 / 0.5264 / 0.5266).

**Acceptance, per run (§0.4):** the `Split global_time` line **identical to X0's**
(`train=3724724 val=931182 | val [2025-12-14 09:35 UTC → 2026-09-09 20:05 UTC]`); the line
`Labels: mode=volnorm vol_window=288 calib_end=2025-12-14T09:35:00Z | 60m: k=… flat fixed=…
volnorm=… 240m: … 1440m: …` present, with `flat volnorm` within 0.01 of `flat fixed` at each
horizon; `knob LABEL_MODE=volnorm` and the three `VN_*` knobs in the resolved block;
`Feature groups: legacy -> 19 columns`; `Pair embedding: ON dim=8`. A run missing any of these
is void and is re-run.

**The statistic — X0/X1's, unchanged.** Per run: the plateau-restricted mean of the per-epoch
cov-0.05 Wilson-LB series on the 240m head (plateau = `loss_va` within 0.02 of the run's
minimum); per family the mean of three seeds; contrast **X2 − X0**. Fallback as before: any
plateau shorter than 15 epochs → both families on the all-epoch mean, and the verdict says so.
Gate: **≥ +0.008 with every X2 seed above the X0 mean → MOVED; (−0.008, +0.008) → FLAT;
≤ −0.008 → WORSE.** Secondary, reported not deciding: pooled cov-0.02 gross bps/trade on the
240m head (X0: +10.9 over 3,231 trades). Also reported: the class-prediction mix
(`3cls_pred`) — a volnorm-trained head should predict fewer flats in calm stretches.

**Expectation, recorded before the run: FLAT.** Nine levers, one moved. The head is still
selected and scored on the fixed labels, so a reshaped training signal has to improve a
fixed-band objective it was not trained on; the plausible outcome is a different confidence
profile (fewer silent calm days) with the same directional edge, which this statistic would
read as FLAT and the served policy might still care about — that is the one thing to look at
in the dumps if FLAT lands, as an exploratory observation only.

**What each verdict licenses.** MOVED → fetch the three `eval_preds`, register an `x2` era in
`m3/dumps.py`, and run the *incumbent* rule on the X2 family under M3_PROTOCOL §9 (Tier 1, C3,
cut and ladder derived on X2's own split) as a promotion candidate; nothing served changes here.
FLAT / WORSE → the label row joins §5 and the freeze is re-sealed. Nothing in the read licenses
a fourth seed, another window, another k rule or a second label mode.

**Commands — Vadim runs these; serial, one at a time, each after the previous reports DONE.**
(The pair list is spelled out: a `<12>` placeholder is a zsh redirection and aborts the
whole pasted block — 2026-09-15.)

```sh
# 0. the volnorm code must be on main first (the train VM clones GIT_REF=main)
git push                                            # commit 2026-09-15 "X2 registered…" and later
git log --oneline -1 -- ml/train/data/dataset.py    # must show the volnorm commit

# 1. do NOT clear the dump cache — X2 must train on X0's snapshot
export CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 EARLY_STOP_PATIENCE=20
export TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240
export TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,XRPUSDT
export DUMP_MAX_AGE_MIN=100000
export LABEL_MODE=volnorm VN_VOL_WINDOW=288 VN_MIN_SIGMA=1e-5 VN_CALIB_END=2025-12-14T09:35:00Z

FEATURE_GROUPS=legacy SEED=1 ./scripts/gcp_train.sh --gpu 60 384   # X2 s1
FEATURE_GROUPS=legacy SEED=2 ./scripts/gcp_train.sh --gpu 60 384   # X2 s2
FEATURE_GROUPS=legacy SEED=3 ./scripts/gcp_train.sh --gpu 60 384   # X2 s3

# 2. after each DONE
./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> > logs/X2_s1.log      # X2_s2, X2_s3
```

~2.5 h and ≈ $1.5 each, ~8 h serial. **Bring back the three logs** (never a summary); the read
happens in a fresh session with §0.3's awk over the epoch lines, then the gate above.

### 🟢 X8 — open-interest history inside the training window, from Binance's public archive. REGISTERED 2026-09-23, RUN 2026-09-23→24, READ 2026-09-24: **MOVED** (+0.011 plateau-mean LB, 4σ, every seed above the control; cov-0.02 gross +18.2 vs +10.9)

**Result, read 2026-09-24 in a fresh session** (`logs/X8_s1..3.log` against `logs/X0_s1..3.log`;
all six on the identical `Split` line `train=3724724 val=931182 | val [2025-12-14 09:35 →
2026-09-09 20:05 UTC]`, 19 columns, X0's numbers below reproduced exactly from the logs).

**Plain reading first.** The score is the Wilson lower bound of directional accuracy on the 5%
most confident bars of the 4-hour head — a conservative "share of correct calls". Filling the
two open-interest columns with the archive's history moved it from **0.526 to 0.537**, about one
more correct call per hundred confident bars, in the same direction on all three seeds and
well outside the noise the design was built to resolve. In money terms, at the served top-2%
cut, one trade now earns **+18.2 basis points gross** (0.01% each; ≈ $0.91 on the $500 size
unit) instead of +10.9, so at the 14-bps taker round trip the pooled result is **+4.2 net
per trade against −3.1** for the control. The expectation was FLAT; it was wrong. This is one
validation split, not a certification: what it licenses is the fold run that could certify it.

| run | run id | recipe check (§0.4) | epochs | all-epoch mean LB | plateau n / mean | selected | cov 0.02 gross bps/trade, 240m (trades) |
|---|---|---|---:|---|---|---|---:|
| X0 s1 | `20260913T050118Z` | ✅ 19 cols, 12/19 constant | 28 | 0.5247 | 21 / 0.5245 | ep 8 (0.5500) | +11.61 (981) |
| X0 s2 | `20260913T094329Z` | ✅ | 32 | 0.5248 | 31 / 0.5264 | ep 12 (0.5489) | +18.43 (1,007) |
| X0 s3 | `20260914T193920Z` | ✅ | 27 | 0.5266 | 27 / 0.5266 | ep 7 (0.5492) | +4.24 (1,243) |
| X8 s1 | `20260923T160559Z` | ✅ 19 cols, twelve `Archive OI` sha8 83c85bd7, `oi`/`oi_chg` off the CONSTANT list | 37 | 0.5265 | 26 / **0.5341** | ep 17 (0.5521) | +19.93 (1,102) |
| X8 s2 | `20260923T204303Z` | ✅ same | 36 | 0.5276 | 22 / **0.5366** | ep 16 (0.5581) | +22.38 (640) |
| X8 s3 | `20260924T024247Z` | ✅ same | 34 | 0.5330 | 24 / **0.5393** | ep 14 (0.5553) | +12.29 (767) |

- **Primary, as registered (no fallback — every plateau ≥ 15 epochs: 26 / 22 / 24):** plateau
  means X8 **0.5367** (between-seed sd 0.0026) vs X0 **0.5258** (sd 0.0012). **Contrast
  X8 − X0 = +0.0108**, ≈ 4σ on the registered SE of 0.0026 (≈ 6.5σ on the two families' own
  spread); every X8 seed (lowest 0.5341) above the X0 family mean and above X0's best seed
  (0.5266) → **MOVED.**
- **Honest footnote on the other column:** the all-epoch means differ by only +0.0037 (0.5290
  vs 0.5254), because each X8 run holds its plateau longer *and then* runs 10–14 degraded
  epochs before patience fires (early stops 37 / 36 / 34 vs 28 / 32 / 27). The registered
  statistic is the plateau mean precisely so that this does not decide; the plateau series
  itself sits at 0.53–0.55 for X8 against 0.52–0.53 for X0 on nearly every epoch.
- **Secondary reading — the arm earns, it does not merely rank:** pooled cov-0.02 gross on the
  240m head **+18.2 bps over 2,509 trades vs +10.9 over 3,231** (per seed +19.9 / +22.4 / +12.3
  vs +11.6 / +18.4 / +4.2; SE ≈ 5 bps). Not MOVED-BUT-NOT-EARNING. Net at the 14-bps line per
  seed +5.9 / +8.4 / −1.7 vs −2.4 / +4.4 / −9.8; dir_acc at cov 0.02 0.600 / 0.581 / 0.594 vs
  0.576 / 0.562 / 0.570 on the identical 18,624 gated bars (§0.6 does not apply). At cov 0.05,
  gross +10.0 / +5.6 / +6.2 vs +0.7 / +7.9 / +0.3. Fewer serialised trades at cov 0.02 (2,509 vs
  3,231): the confident bars cluster more, so the one-position-per-pair sim merges more of them.
- **The plateau-length reading that decides X8b: plateaus held.** 26 / 22 / 24 epochs with a
  filled column, against X1's 7 / 7 / 4 and X2's 6 / 7 / 3; `loss_tr` leaves 1.72 at epoch
  25–27 vs X0's 19–22. So the memorisation mechanism is about *redundant or noisy added*
  columns, not about any change to the input — **X8b may be launched** (per the licence list).
- **Integrity check a positive result deserves (done, passes — with one refinement found
  later the same day, §0.5 trap 12):** the archive rows are forward-filled onto the bar's
  `open_time` by the same `_align_with_age` join the collector's rows use, and serve only ever
  reads collector rows (the archive stops where the collector starts). The archive's
  `create_time`, however, is the bucket's *start* while its value is the bucket's *end*, so a
  training bar T saw the open interest of T+5 min — the value at that bar's close, i.e. at the
  instant the bar is acted on. Not a lookahead past the decision, but one bar fresher than
  serving provides (the collector's last poll at or before T). The identity check matched
  values at 0.03–0.19% median unshifted and 3–4× tighter shifted. The read stands as a
  measurement that OI history helps; the served configuration differs from it by one bar of
  OI freshness. **Resolved 2026-09-24, Vadim: option (2) — X8′.** The same three commands as
  X8 with `ARCHIVE_OI_SHIFT_MIN=5` added (launcher log: two drift items, `ARCHIVE_OI` and
  `ARCHIVE_OI_SHIFT_MIN`; run log: every `Archive OI:` line ending `shift_min=5`, `git_sha` at
  or after `198cc4f`; everything else in X8's acceptance unchanged). Read as X8 was read —
  §0.3's awk against X0's plateau means, X8's gate, X8's secondary — with the expectation now
  MOVED; result block goes here. X8′'s family-median seed becomes WALKFORWARD §10's promotion
  candidate; X8 s1–s3 stay banked as the unshifted record. Logs: `logs/X8p_s{1,2,3}.log`.
- **Norm flags, per §0.4, none a void:** the hl_range `DEGENERATE SPIKE` lines and WLD's
  `has_funding_oi` spike are X0's own; new are two *heavy-tail* notes on `oi_chg` (HYPE 3 rows,
  ZEC 23 rows beyond ±50, winsorised — a populated tail, not a spike). Class mix at the selected
  epochs is X0-like (flat 0.53–0.60); the up-share of directional calls is lower in s2/s3 (0.23 /
  0.20 vs X0's 0.27–0.36) — check side balance per checkpoint before any promotion, as §1.3 says.

**What this licenses, exactly as pre-registered, and nothing more:** (i) the incumbent rule on
the three X8 checkpoints under M3_PROTOCOL §9 (Tier 1, C3) — U12's precedent is
`M3_ERA=repaired ./scripts/m3.sh -m m3 universe --runs 20260923T160559Z,20260923T204303Z,20260924T024247Z`
after `m3 validate`; recall from U12 that one-split Tier 1 could not arbitrate a checkpoint
swap (the incumbent itself fails it in 98.7% of resamples), so it is texture; (ii) **the
walk-forward folds for this recipe under their own pre-registration** — **funded by Vadim and
registered 2026-09-24 as [WALKFORWARD_PROTOCOL §10](./WALKFORWARD_PROTOCOL.md)** (era
`walkforward_x8`; `ARCHIVE_OI` set, `ALLOW_RECIPE_DRIFT=1`, `SPLIT_EMBARGO` and `ALIGN_AGE_FIX`
off so the fold control stays the banked one; 12 runs, launched by Vadim) — promotion only
through §3's W1–W5 plus §10's contrast veto, never by this read; the full-window instance that
a pass would promote is fixed there as X8 s2; (iii) X8b (below, three runs ≈ $4.5, control =
X8) — funded 2026-09-24, with one pre-launch question open (its identity acceptance). Nothing
served changes on this read. §5's freeze row carries the entry. *Tier 1 texture, run 2026-09-24
(`logs/X8_tier1_20260924.log`, `m3 validate` PASS first):* twelve pairs, sized, 2,504 trades,
pooled net at taker **+11.61** (U12: +4.95), windows w1 −10.08 / w2 +21.04 / w3 −5.46 / w4
+17.30, **P2 and P3 fail** (two windows negative; worst −10.08 against −5), P1/P4/P5/P6 pass —
the same shape as U12's failure, and per U12's record one-split Tier 1 arbitrates nothing.

*The registration as written on 2026-09-23 follows, unchanged, as the record of what was fixed
before the logs were read.*

**Written before any number was read. Nothing below this block is to be edited after a log
comes back; the result block goes above it.**

**The question.** The served model carries `oi` and `oi_chg` in its 19 legacy columns, but the
collector's `open_interest` table starts 2026-07-18 and X0's train window ends 2025-12-14, so
both columns are constant zero in train and are forced to zero in train, val **and serve**
(`NORM_DEGENERATE_MODE=zero`; X0's log: `12/19 features are CONSTANT in the train window ->
forcing them to 0`). Binance's public archive (`data.binance.vision`, USDⓈ-M `metrics`, one row
per 5 minutes) carries the same quantity, `sum_open_interest`, from 2020-09 for every pair the
collector trades. **Does filling these two existing columns over the whole training window
move the 240m head?**

**Why this is not a re-proposal.** §5's feature row closes *added* columns: own-pair
re-parameterisations (R1) and the external market block (X1) both memorised. X8 adds no column
— 19 in, 19 out, `LEGACY_FEATURE_COLS` unchanged, no serve-side feature code touched. It is the
freeze's own reopening condition, "history deep enough to sit inside the *training* window",
for the one legacy quantity where the archive and the collector are literally the same series.
The "≈2027" attached to that condition was the date at which the **collector** would have
supplied it; the archive supplies it today. (The archive's existence and coverage were measured
by the fluxtrader2 project on 2026-09-15 — a fact about Binance, not a fluxtrader2 conclusion,
and nothing else from that project is used.)

**Why one lever, and which.** The archive offers three things: OI (an existing served column;
no serve change), the long/short and taker ratios (new columns; the collector's
`long_short_ratios` table since 2026-08-24 would be the serve source) and depth within ±1..5 %
of mid (new columns; **no live counterpart** — the collector's snapshot holds the top levels
only, so a serve path needs a collector change first). §0.2: one change per run. **X8 is OI
only.** The ratio block is written below as **X8b**, with its own gate, and is *run* only on a
decision taken after X8 is read. Depth bands are not registered here.

**The control — X0, banked, reused.** Same snapshot `dumps/20260913T050118Z.sql.gz`,
`FEATURE_GROUPS=legacy`, seeds 1/2/3 (`20260913T050118Z`, `20260913T094329Z`,
`20260914T193920Z`): plateau means 0.5245 / 0.5264 / 0.5266 (plateaus 21 / 31 / 27 epochs),
all-epoch 0.5254, between-seed sd 0.0011; cov-0.02 gross +10.9 over 3,231 trades. Reusable
because X8 changes neither the snapshot nor the split: the fill is a side file, not a new dump.

**The recipe — X0 plus exactly one thing.** `ARCHIVE_OI=<bucket path>` set. With it,
`db.load_open_interest` returns, per pair, the archive rows for every timestamp **before the
collector's first row for that pair**, followed by the collector's own rows; without it the
loader is byte-for-byte the current one. Everything else is X0's: 12 pairs, seq 384, 60 epochs,
horizons 60/240/1440, primary 240, 5m, `PAIR_EMBED_DIM=8`, `EARLY_STOP_PATIENCE=20`,
`FEATURE_GROUPS=legacy`, `SPLIT_EMBARGO` **off** — X5's row says it turns on "in the next
registered family", but X8 reuses X0 as its control and a second recipe difference would break
the pairing; X5 goes on in the first family whose control is retrained (X8b, if run). Three
seeds: 1, 2, 3.

**Code prerequisite on `main`, built before launch; none of it reads a model number:**

1. `scripts/fetch_archive_metrics.sh` → runs `m3 archiveoi fetch` (`ml/train/m3/archiveoi.py`)
   in the `ml_analysis` image (Docker; nothing on the host). Downloads
   `data/futures/um/daily/metrics/{SYMBOL}/{SYMBOL}-metrics-{YYYY-MM-DD}.zip` from
   `https://data.binance.vision/` for the twelve pairs, 2022-08-01 → 2026-09-13 (the snapshot's
   date), verifying each `.CHECKSUM` (sha256), retrying, resumable. Keeps all seven columns
   (X8b needs the ratios) and writes one parquet `(symbol, ts, open_interest, oi_value,
   top_ls_count, top_ls_sum, global_ls, taker_ratio)` at 5-minute cadence, ~4.7 M rows, then
   uploads it as `gs://fluxtrader-train-artifacts/archive/metrics_um_5m_<sha8>.parquet`. The
   sha is the file's identity and goes into every run's `meta`.
2. `ml/train/data/db.py::load_open_interest`: the `ARCHIVE_OI` union above, and one log line
   per pair — `Archive OI: <pair> <n> archive rows <first> -> <last>, collector from <ts>` —
   plus `meta["archive_oi"] = <sha8>`.
3. `scripts/gcp_train.sh`: `ARCHIVE_OI` on `FLUX_TRAIN_ENV_KEYS` (§7 "Env knob passthrough")
   and the parquet copied from the bucket to the train VM next to the dump; on the fold
   allowlist it is **not** — a fold run with it set needs `ALLOW_RECIPE_DRIFT=1` and its own
   registration.
4. 🔴 **Identity acceptance, before the first launch** (`./scripts/archive_oi_check.sh
   <parquet>` → `m3 archiveoi check`, `ml_analysis` image): over the overlap 2026-07-18 → 2026-09-09, join each archive row to the nearest
   collector `open_interest` row within 5 minutes; per pair, report median and 99th-percentile
   relative difference and the matched count. **Pass:** median < 0.5 % and p99 < 2 % on every
   pair. Fail on any pair → X8 is **void before it runs** — the two series are not the same
   quantity and the serve path would feed the checkpoint something it never saw. (Funding, the
   one archive series already compared, matched the collector 99.94–100 %.)

**Prerequisites 1–4 done 2026-09-23, before launch, no model number read.** Fetch: 18,060
daily files, 16,391 present, 1,669 absent (all pre-listing except one day each for WLD
2023-12-16 and ZEC 2023-12-13); 4,718,594 rows, 2 duplicate keys dropped; every pair from
2022-08-01 or its listing (1000PEPE 2023-05-05, WLD 2023-07-24, HYPE 2025-05-30) to
2026-09-13 23:55. File `metrics_um_5m_83c85bd7.parquet` (253 MB) →
`gs://fluxtrader-train-artifacts/archive/`. Identity check over 2026-07-17 21:13 → 09-23
16:02 (770,979 collector rows): **PASS on all twelve** — median relative difference 0.026 %
(BTC) to 0.186 % (HYPE), p99 0.36–0.96 %, worst single row 5.9 %; ADA/AVAX/LINK/XRP match
~8.9k rows against the others' ~15–16k because the collector added them on 2026-08-29.
Loader union verified in the trainer image: archive rows precede the collector's first row,
the frame stays monotonic, `since` applies, `sha8=83c85bd7` on every line.

**One snapshot, three identical `Split` lines.** `DUMP_MAX_AGE_MIN=100000` with the pinned
dump; every X8 log must print X0's line exactly: `Split global_time | val_frac=0.2
val_offset=0.0 train_frac=0.0 | train=3724724 val=931182 | train [2022-08-19 21:45 UTC →
2025-12-14 09:35 UTC] | val [2025-12-14 09:35 UTC → 2026-09-09 20:05 UTC]`. Also required in
each log: `Feature groups: legacy -> 19 columns`; twelve `Archive OI:` lines with the same
sha8; and the norm block now reporting **10/19** constant features — `oi` and `oi_chg` gone
from the list. A run missing any of these is void, not read.

**Serial order:** X8 s1 → s2 → s3. One `gcp_train.sh` at a time.

*Launch log, no epoch read.* **s1 = `20260923T160559Z`**, launched 2026-09-23 16:15 UTC on an
L4 (`us-central1-b`), git `54a5fff`, cache hit at 16,666 min (the pinned dump; bucket
`latest.sql.gz` crc32c-identical to `20260913T050118Z.sql.gz`). Acceptance on the log:
`Split` line identical to X0's ✓; `Feature groups: legacy -> 19 columns` ✓; twelve
`Archive OI:` lines, 120,011 (HYPE) to 424,418 rows each, all `sha8=83c85bd7` ✓; **`oi` and
`oi_chg` are gone from every CONSTANT list** ✓. ⚠️ The count is **11/19 on the long pairs
and 10/19 on WLD and the global fit**, not 10 everywhere: the eleventh is `has_funding_oi`,
which the archive fill makes 1 on every train bar of a pair listed before the window (X0 had
it at 1 with a few gaps — WLD's z = 501 "degenerate spike" in both logs), so it is now forced
to 0 on those pairs in train, val and serve. A presence flag that is always 1 carries nothing
either way; recorded as the one side effect of the fill, not a deviation. The `hl_range`
spike warnings are X0's too.
**s1 DONE 2026-09-23 20:37 UTC** (early stop at epoch 37, checkpoint
`m2_multi_20260923T160559Z_54a5fff4.pt`; `logs/X8_s1.log`, `eval_preds_20260923T160559Z.parquet`
fetched; no epoch line read). **s2 = `20260923T204303Z`**, launched 20:43 UTC, same cache hit. **s2 DONE 2026-09-24 01:02 UTC** (early stop at epoch 36, git
`d88f350`, checkpoint `m2_multi_20260923T204303Z_d88f3506.pt`; `logs/X8_s2.log`,
`eval_preds_20260923T204303Z.parquet` fetched). Acceptance on the s2 log identical to s1's:
same `Split` line, 19 columns, twelve `Archive OI:` lines sha8 83c85bd7, `oi`/`oi_chg` absent
from every CONSTANT list, 11/19 on the long pairs and 10/19 on WLD and the global fit. ⚠️ One
grep for the pairs/horizons line also matched three checkpoint-save lines carrying epoch
`sel_score` values; they were not recorded or used, the read still happens in a fresh session.
**s3 = `20260924T024247Z`**, launched 2026-09-24 02:42 UTC on an L4 (`us-central1-a`), same
cache hit, same env, `SEED=3`. Acceptance verified on the live log at 03:15 UTC (git `0a83a0e`): identical `Split` line, 19 columns, twelve `Archive OI:` lines sha8 83c85bd7, same CONSTANT lists (11/19 long pairs, 10/19 WLD and global); no epoch line read. **s3 DONE 2026-09-24 06:51 UTC** (early stop at epoch 34, git `0a83a0e`, checkpoint
`m2_multi_20260924T024247Z_0a83a0eb.pt`; `logs/X8_s3.log`, `eval_preds_20260924T024247Z.parquet`
fetched; bucket log re-checked: one identical `Split` line, twelve `Archive OI:` lines).
**All three logs are on disk: `logs/X8_s1.log`, `logs/X8_s2.log`, `logs/X8_s3.log`; nothing read.**
Early stops 37 / 36 / 34. **Next, in a fresh session:** §0.3's awk over the epoch lines of the
three logs and X0's three, then the gate above; the plateau length decides X8b.

**The statistic** (X1's, unchanged): per run, the plateau-restricted mean of the per-epoch
cov 0.05 Wilson-LB series on the 240m head (plateau = epochs whose `loss_va` is within 0.02 of
the run's minimum); per family, the mean of its three seeds, error bar the between-seed sd.
**Fallback, stated now:** if any run's plateau is shorter than 15 epochs, both families are
read on the all-epoch mean (X0 = 0.5254) and the verdict says so.

**The gate:** X8 − X0 ≥ **+0.008** *and* every X8 seed above the X0 family mean → **MOVED**;
in (−0.008, +0.008), or ≥ +0.008 with a seed below → **FLAT**; ≤ −0.008 → **WORSE**.

**Secondary reading:** pooled cov-0.02 gross bps/trade on the 240m head against X0's +10.9
(SE ≈ 5 bps). A MOVED whose cov-0.02 gross is more than 5 bps below X0's is
**MOVED-BUT-NOT-EARNING** and licenses nothing.

**Recorded expectation: FLAT.** Open interest is a slow positioning variable; its information
about the next four hours' direction is small, and the X1/X2 pattern is that the LSTM
memorises whatever it is handed. **The reading that matters beyond the gate is the plateau
length.** If the three plateaus stay ≥ 15 epochs with a filled column, the memorisation
mechanism is about *redundant* columns and not about any column, and X8b is worth running. If
they collapse under 15 (X1: 7 / 7 / 4; X2: 6 / 7 / 3), even a FLAT closes the filled-column
route and X8b is not run.

**What each verdict licenses — and nothing more:**

* **MOVED:** (i) register the era in `m3/dumps.py` and run the incumbent rule on the X8
  checkpoints under M3_PROTOCOL §9 (Tier 1, C3); (ii) the walk-forward folds for this recipe
  under their own pre-registration with `ALLOW_RECIPE_DRIFT=1`, promotion only through W1–W5
  (WALKFORWARD §3, §5.1), never by this read; (iii) X8b may be launched.
* **FLAT with plateaus ≥ 15:** a decision for Vadim on X8b (three more runs); nothing served
  changes.
* **FLAT with a short plateau, or WORSE:** the filled-column route is closed. §5's reopening
  condition is then rewritten to say the fill of an existing column does not reopen M2 and only
  a genuinely new observation with history could — which, on the evidence of X1, is unlikely
  to survive either. X8b is not run.
* Nothing licenses a fourth seed, a different fill window, a different OI transform, or
  re-reading with the ratios "since the data is there".

**Commands** (after the four prerequisites are on `main` and the identity check has passed):

```sh
export CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 EARLY_STOP_PATIENCE=20
export TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 TRAIN_PAIRS=<12>
export DUMP_MAX_AGE_MIN=100000                      # the pinned 20260913T050118Z snapshot
export ARCHIVE_OI=gs://fluxtrader-train-artifacts/archive/metrics_um_5m_<sha8>.parquet

FEATURE_GROUPS=legacy SEED=1 ./scripts/gcp_train.sh --gpu 60 384   # X8 s1
FEATURE_GROUPS=legacy SEED=2 ./scripts/gcp_train.sh --gpu 60 384   # X8 s2  (after s1 is DONE)
FEATURE_GROUPS=legacy SEED=3 ./scripts/gcp_train.sh --gpu 60 384   # X8 s3

./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> > logs/X8_s1.log      # X8_s2, X8_s3 — never --save
gcloud storage cp gs://fluxtrader-train-artifacts/eval/<run_id>/eval_preds.parquet \
  ml/train/output/eval_dumps/eval_preds_<run_id>.parquet
```

~2.5 h and ≈ $1.5 each, ~8 h serial. **Bring back the three logs** (never a summary); the read
happens in a fresh session with §0.3's awk over the epoch lines, then the gate above.

#### X8b — the flow ratios as a feature group. WRITTEN 2026-09-23, NOT REGISTERED FOR LAUNCH

Run only on the decision X8's read leaves for Vadim; the text is fixed now so that the decision
cannot shape it. **The change:** `FEATURE_GROUPS=legacy,flow`, a new group `flow` of four
columns appended after `legacy` — `ls_global` (log of the global long/short account ratio),
`ls_top` (log of the top-trader long/short position ratio, the `sum` variant), `taker_ratio`
(log of the taker buy/sell volume ratio), `has_flow` — all as-of-joined to the candle grid with
`FUNDING_OI_MAX_AGE_MIN`'s 480-minute cap and zero when stale, exactly as `funding`/`oi` are.
Training source: the same archive parquet; serve source: the collector's `long_short_ratios`
(top / global / taker families at 5m since 2026-08-24), with the same identity acceptance as
X8's over 2026-08-24 → 09-09 before launch. Serve-side: `features.py`, `serve.py` and the
checkpoint guard learn the 23-column layout; `LEGACY_FEATURE_COLS == FEATURE_COLS[:19]` holds.
**Control:** X8 (so both arms carry `ARCHIVE_OI`); `SPLIT_EMBARGO=1` on **both** arms would need
X8 re-run — so it stays off here too, and X5 waits for a family that retrains its control from
scratch. Same statistic, fallback, gate and secondary as X8. **Recorded expectation: WORSE or
FLAT with short plateaus** — X1 is the precedent for five added external columns. Three runs.

**Funded by Vadim 2026-09-24 ("2. Yes"). Built the same day, before any X8b number exists —
three pre-launch amendments, each a fact found while building, none shaped by a result:**

1. **`ls_top` is the top-trader long/short *account* ratio, not the position ratio.** The
   collector polls `topLongShortAccountRatio` only (`collector.ex`; the position endpoint is not
   collected), so the archive column with a live counterpart is `count_toptrader_long_short_ratio`
   (`top_ls_count`), not the `sum_*` position variant the text above named. Adding the position
   endpoint to the collector would give it no history to accept against. The group is therefore
   `ls_global` = log(global long/short account ratio), `ls_top` = log(top-trader long/short
   **account** ratio), `taker_ratio` = log(taker buy/sell volume ratio), `has_flow`.
2. **The identity acceptance — FAILED as first run, then PASSED at the original bar once the
   archive's timestamps were understood** (`logs/X8b_identity_flow_20260924.log`, both runs;
   `./scripts/archive_flow_check.sh`). First run, archive timestamps as published: FAIL on 5 of
   36 series at p99 (DOGE top, HYPE both, ZEC both: 2.05–3.14% against 2%), every median
   passing, the taker series exact. Vadim chose to amend the bar to 3% ("X8b — (A)"); before
   applying it the tail was diagnosed and the amendment turned out to be **unnecessary and is
   withdrawn**: the disagreement equalled each series' own one-bucket move to within 1% at
   every pair — the signature of a one-bucket label offset, not of noise — and shifting the
   archive's account-ratio rows by +5 min makes the two sources identical (**median 0.011%,
   p99 0.02–0.03% on both series, all twelve pairs; PASS at the original 0.5% / 2% bar**). The
   taker ratio is a bucket aggregate and aligns unshifted (§0.5 trap 12 for the mechanism and
   its consequence for X8). The loader applies the +5 min re-labelling to the two account series
   unconditionally, so a timestamp means the same instant in training and serving; nothing about
   the bar changed. One more archive fact, a note not a blocker: the **top-trader ratio is absent
   for the first ~136 days (2022-08-01 → ~2022-12-14) on the nine pairs listed then** (39,130 rows
   each; global and taker present), so `ls_top` is 0 there with `has_flow` still 1 — it will not
   be CONSTANT, and the run's norm block should be read with that in mind.
3. **Serve-side:** `features.py` gains the `flow` group (appended after `market` in
   `_GROUP_ORDER`, so `FEATURE_GROUPS=legacy,flow` is 23 columns with `LEGACY_FEATURE_COLS ==
   FEATURE_COLS[:19]` intact and `ALL_FEATURE_COLS` unchanged in its first 30); `db.load_long_short_ratios`
   (collector `long_short_ratios`, 5m period; under `ARCHIVE_OI` the archive's three series
   before the collector's first row, logged as `Archive flow: …`); `serve.py` binds by the
   checkpoint's `feature_cols` as before and now reports `n_features` on `/health`; the Elixir
   binding guard checks sha / interval / closed-bars and needs no change. The staleness cap on
   the ratios is `FUNDING_OI_MAX_AGE_MIN` — which, per §0.5 trap 11, does not fire with
   `ALIGN_AGE_FIX` off; X8b keeps it off, like its control. Tests: `tests/test_flow_features.py`
   (groups, alignment under the fix, the legacy pin, empty source) and `tests/test_serve_universe.py`
   both PASS in the trainer image (plus `test_archive_flow_shift`, which pins the +5 min
   re-labelling and the OI knob); an end-to-end `build_feature_frame` with the archive attached
   is in `logs/x8b_e2e_local_20260924.log`.
4. **X8b's control is X8′ (decided 2026-09-24, Vadim: option (2)).** X8 is re-run under the
   served convention (`ARCHIVE_OI_SHIFT_MIN=5`, three seeds; registration = X8's, read = X8's
   statistic against X0, expectation now MOVED) and X8b carries the same knob with X8′ as its
   control, so both arms of the contrast share one OI convention. **X8b launches after X8′ is
   read** — its control's plateau means do not exist before that.

**Acceptance, per run (§0.4), in addition to X8's lines:** `Feature groups: legacy,flow -> 23
columns (…, has_funding_oi, ls_global, ls_top, taker_ratio, has_flow)`; twelve `Archive flow:`
lines **and** twelve `Archive OI:` lines, all `sha8=83c85bd7`; the `Split` line identical to
X0/X8's; `Align age: ALIGN_AGE_FIX=0`; **none of the four flow columns in any CONSTANT list**
(they carry archive history from 2022-08 on every pair; `has_flow` will be constant 1 on the
long pairs like `has_funding_oi` — record it, it is the same side effect). A run missing any of
these is void.

**Commands (after X8′ is read; serial, one at a time, before or after X8-F's twelve — the
GPU is the only shared resource):**

```sh
export CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 EARLY_STOP_PATIENCE=20
export TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240
export TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,XRPUSDT
export DUMP_MAX_AGE_MIN=100000                      # the pinned 20260913T050118Z snapshot — same as X0 and X8
export ARCHIVE_OI=gs://fluxtrader-train-artifacts/archive/metrics_um_5m_83c85bd7.parquet
export ARCHIVE_OI_SHIFT_MIN=5                       # the served convention — same as X8′, its control
unset VAL_OFFSET VAL_FRACTION TRAIN_FRACTION ALLOW_RECIPE_DRIFT SPLIT_EMBARGO ALIGN_AGE_FIX   # not a fold

FEATURE_GROUPS=legacy,flow SEED=1 ./scripts/gcp_train.sh --gpu 60 384   # X8b s1
FEATURE_GROUPS=legacy,flow SEED=2 ./scripts/gcp_train.sh --gpu 60 384   # X8b s2  (after s1 is DONE)
FEATURE_GROUPS=legacy,flow SEED=3 ./scripts/gcp_train.sh --gpu 60 384   # X8b s3

./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> > logs/X8b_s1.log     # X8b_s2, X8b_s3 — never --save
```

The launcher's go/no-go line: `recipe differs from the incumbent (T1) in:` with exactly two
items, `FEATURE_GROUPS: incumbent='legacy' this run='legacy,flow'` and `ARCHIVE_OI: …83c85bd7…`
(three, with `ARCHIVE_OI_SHIFT_MIN: incumbent='0' this run='5'`, under the served convention).
Acceptance adds: twelve `Archive flow:` lines ending `account_shift_min=5`, and every
`Archive OI:` line ending `shift_min=<the decided value>`.
**Bring back the three logs**; the read (X8's statistic against X8's plateau means 0.5341 /
0.5366 / 0.5393, family 0.5367; gate ±0.008; secondary against +18.2 over 2,509) happens in a
fresh session.

### 🟢 B3b — CLOSED 2026-09-11. Both runs done; the book-era wave closed on their verdict

`logs/b3b_gbt_5m_20260911.log`, `logs/b3b_gbt_15m_20260911.log`; reading in
[BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) §R.3. 15m at cov 5%: gross +5.29, **net at maker +0.29
vs a +5 gate, day-clustered band ±8.4 → FAIL as written, gate inside the band**; 5m re-emit
confirmed FAIL (not digit-identical: the dump refreshed, trap 10 below). O5 filed there. The one
follow-up is **B3c** — the identical 15m registration on a ~53-day val window, **on or after
2026-11-02**, parked in [BACKLOG.md](./BACKLOG.md) with the exact command in §R.3; it uses the
new `GBT_VAL_FRACTION` launcher passthrough. No third setting, no sweep.

**Nothing else in the B-wave needs a GPU or a training run.** B0, B1 and B2 all ran on the
laptop's `ml_analysis` container.

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
| **Volatility-normalised training labels (`LABEL_MODE=volnorm`)** | **Closed (new, 2026-09-15) — WORSE** | X2 replaced the fixed ±0.6% flat band with a band in units of each pair's trailing one-day σ (k derived from the fixed label's flat share on the train window, so the class balance was unchanged), while selection and evaluation stayed on the fixed labels. Against a same-snapshot 3-seed control: **−0.0096** all-epoch mean LB (fallback read, every plateau under 15 epochs), every seed below the control, cov-0.02 gross +8.7 vs +10.9. `loss_tr` collapses from epoch 4–9, earlier than any 19-column run. The mechanism is the opposite of the hope: rescaling by a calm day's σ makes noise-sized moves directional, which the model memorises. It is the training-target cousin of the magnitude-loss row above — both try to change *what* M2 learns from calm vs volatile bars, and both lose. Do not try another k rule, vol window or label mode; the voided triple-barrier (`E3-tb`) is not reopened by this either. §2 |
| **M2 as a research object** | 🔴 **FROZEN, 2026-08-24 — the exit condition fired.** ⚠️ *Amended 2026-09-13, resolved 2026-09-15:* reopened for **one** lever, X0/X1 in §2, under the feature row's own "genuinely external information" clause and on new evidence (B3's O5). **X1 came back WORSE (−0.020, §2) and the freeze is re-sealed.** ⚠️ *Amended again 2026-09-15, resolved the same day:* reopened for **one** further lever, X2 (§2, volatility-normalised training labels), funded by Vadim as the last offline M2 lever with a rationale. **X2 came back WORSE (−0.010, §2) and the freeze is re-sealed.** Eleven levers tested one at a time, one moved. The only reopening condition is §1.7's. ⚠️ *Amended 2026-09-23:* **that condition is met today for one served column** — Binance's public archive holds open interest at 5 minutes from 2020-09, i.e. inside the whole training window, for the two legacy columns (`oi`, `oi_chg`) that are currently zeroed. Reopened for **one** lever under it: **X8** (§2, registered, not launched), which adds no column. The "≈2027" was the date the *collector* would have supplied that history; it is not the condition. 🟢 *Resolved 2026-09-24:* **X8 came back MOVED** (+0.011 plateau-mean LB, every seed above, cov-0.02 gross +18.2 vs +10.9, plateaus intact at 22–26 epochs — §2) — the second lever in the project's history to move, and the first since 15m → 5m. The freeze is **not** re-sealed on this row's old terms: history inside the training window does reopen M2, and the archive supplies it. What stays closed is everything §5 closed on measurement (added columns, labels, losses, capacity, context, resolution, ensembling). Open under X8's licence list only: the fold certification of the `ARCHIVE_OI` recipe and X8b — both spend decisions for Vadim, both pre-registered before launch | Written down in advance on 2026-08-22: "if O8 and R3 both come back flat (within ±0.005 plateau-mean LB of 0.5239) **and** R2 does not move gross bps/trade at cov 0.02 by more than +5, M2 is frozen at the §1.3 baseline and every remaining hour goes to M3." O8 −0.0017, R3b −0.0040, R3a −0.0054, R2 −3.2 bps. **Every clause fired.** Eight levers have now been tested one variable at a time against the same baseline — two feature sets, bar resolution, context length, model family, ensembling, loss shaping, data volume, and encoder capacity in both directions — and exactly one (15m → 5m) ever moved. The single reopening condition is §1.7's: order-book history deep enough to sit inside the *training* window, ≈2027. Do not queue an M2 run before then. §1.9, §2. **`docs/BOOK_ERA_PLAN.md` tests whether a *short-horizon* model on the book era can be decided early; it does not reopen this row, and §4.3 there forbids promoting anything on a 7-day validation window.** |
| Full architecture swap (transformer / TCN) | **Closed, and reaffirmed 2026-08-22** | Was gated behind O3; O3 came back negative. The reopening condition written in 2026-08-19 was "if richer per-timestep features saturate and the residual failure looks like a modelling limit rather than an input limit" — Q3 and R1 have now *both* run and the failure looks like the opposite: the model already memorizes the training set the moment it is handed anything easy (`loss_tr` 1.70 → 1.13 in R1), while its validation loss never improves. That is an **input** limit and an SNR floor, not a modelling limit. A higher-capacity family would make it worse, not better. **Do not write a transformer.** 🔴 **Reaffirmed again 2026-08-23: R3a ran the two-run bracket's upward arm and produced exactly this prediction** — `loss_tr` 1.72 → 0.888 with `loss_va` never once reaching the baseline's level, and the worst calibration in the ledger. More capacity of any kind makes this problem worse. There is no remaining capacity question. |
| Confidence calibration / temperature / focal loss | **Closed** | F4's head is *over*-confident (`[0.60,0.70)` bin mean_pred 0.636 vs empirical 0.547; N3's is 0.609 vs 0.521). Sharpening an over-confident head is the wrong direction. |
| Raising `GATE_THRESHOLD` as an experiment | **Superseded by C1+C2** | The served gate is 0.58 and eval now reports there. Derive the operating point from the fixed-coverage P&L table, not from another sweep. |
| Quantile head | **Deferred** | Regressed direction ~0.014; band coverage unstable. Revisit at M3, detached. |
| `liquidations` feed | **Dropped** | 0 rows; Binance gates WS market data from datacenter egress (verified from 3 hosts). |
| More candle *history* | **Closed** | Adds more of the pre-book regime we already fit. Note this is about *history*, not *resolution*. |
| **Bar resolution — 15m → 5m** | **🟢 BANKED and frozen (2026-08-21)** | Replicated across three seeds: pooled mean-of-epochs 0.5219 ± 0.0014 vs F4's 0.5058, and pooled +22 gross bps/trade at the top 2% (§1.3). `5m / seq 384` is the permanent baseline. Nothing further to test here — do not run a fourth seed. |
| **Bar resolution — finer than 5m** | **Closed (new, 2026-08-21)** | P2 ran 1m/seq768 as a direction probe: flat `dir_acc` (0.561 vs 0.559), materially worse economics, **destroyed calibration** (`emp_up ≈ 0.48` in every bin, brier 0.323 vs 0.250), 20h wall clock. The ladder has one rung and we are standing on it. The untested variant (1m at a 32h window, seq 1920) is unaffordable and context length is separately closed. §1.4 |
| **Multi-checkpoint ensembling (probability averaging)** | **Closed (new, 2026-08-22)** | Q2 averaged three seeds of one configuration and compared against the best member on a matched split (Q0). Ranking improved by noise (+0.002 dir_acc), calibration by noise (−0.0005 brier), and **gross bps/trade got worse at four of five coverages**. The mechanism: averaging pulls every bar toward the consensus, which preserves the directional *order* but compresses exactly the outlier-confident bars where the large moves are. Reopen only if calibration — not P&L — becomes the binding constraint on M3. §1.1 |
| **Per-timestep candle features (own-pair)** | **Closed (new, 2026-08-22)** | Two arms, both rejected. Q3 added 11 columns (30 total) and R1 added the well-conditioned 6 (25 total) with every §0.4 line green. R1's plateau mean is 0.4979 vs 0.5239, and — the fact that closes it — **R1's best validation loss (1.0451) is worse than the baseline's (1.0398–1.0404) at every epoch including epoch 1**, so no regularization arm can recover it. At `seq 384` (32h) every multiscale column is an exact function of bars already inside the window at the prediction timestep: zero information, six smooth channels that are far easier to memorize than `ret_1`. **Redundant re-parameterizations of the input are pure overfitting surface.** Reopen only for genuinely *external* information, and note Q1 already measured the informative member of that family and assigned it to M3. §1.6. 🔴 *Second entry, 2026-09-15:* the five-column **market block** (`btc_rel_ret_1h`, `beta_btc_1d`, `xs_rank_1h`, `xs_disp_1h`, `has_market`) — the external information this row reserved an exception for — was tested on its own as X1 against a same-snapshot 3-seed control and came back **WORSE, −0.020** on the registered read (§2), with the identical signature: plateau gone by epoch 6–7. The model memorises *any* added column, own-pair or external. **The feature route into M2 is closed in both directions**; what the block carries (O5's `xs_disp_1h` gain) is magnitude, and magnitude is M3's — BACKLOG's X3 |
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
X2 s3's checkpoint (`m2_multi_20260915T121504Z_150d37f5.pt`, volnorm labels, closed WORSE in
§2) and must not be promoted.** C13 made `--checkpoint <key>` required, so naming a key explicitly is now the
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
VN_VOL_WINDOW VN_MIN_SIGMA VN_CALIB_END
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


`ARCHIVE_OI` (X8) is on the list and is special-cased: on the launcher it is a `gs://` path; the
remote job copies the file to `ml/train/output/archive/` on the train VM and re-points the
variable at the container path (`/workspace/train/output/archive/<file>`) before either
passthrough loop reads it. It is not on the fold allowlist.

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
