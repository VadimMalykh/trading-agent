# Walk-forward folds — the pre-registered protocol

**Status:** ✅ **COMMITTED 2026-09-04, before any fold was trained.** No fold checkpoint, no fold
dump and no fold P&L existed when this was written. The only numbers in it are sample counts,
calendar estimates and the constants inherited from completed, published runs.
**Sits under:** [M3_PROTOCOL.md](./M3_PROTOCOL.md) §9.3 (why the folds exist), §9.4 (the ranking
axis this protocol is the first to use), §8.3 (the champion–challenger rule a fold family must
satisfy). **Owner of the plumbing:** [RETRAIN_PLAN.md](./RETRAIN_PLAN.md) §2–§3.

**The rule, identical to M3_PROTOCOL §0: this file is not edited after the first fold is
launched.** A better fold shape, a better statistic or a different k is a proposal for a future
pre-registration, never a re-scoring of these runs.

---

## §0 — In plain language

**What a fold is.** Today's model was trained on everything up to 2025-12-10 and judged on the
nine months after. A *fold* is the same recipe trained with the cut-off moved back — to mid-2025,
to early 2025, and so on — and judged on the months right after *its* cut-off, which that model
never saw. Each fold hands the trading rule a fresh stretch of out-of-sample predictions on a
period **no policy search has ever looked at**, because every M3 number so far was measured on
2025-12 → 2026-09 only.

**Why it matters.** The binding limit on this whole project is ~220 independent trading days
(M3_PROTOCOL §2). Folds do not manufacture new market history, but they let the rule be scored on
years of it instead of nine months, which roughly triples the independent days and halves the
error bars. That is what makes three things decidable that are not decidable today: whether a
fresher model is better, whether any parked idea (served coverage, a learned or RL policy, a book
observable) is real, and how long a dry spell is "too long" (the retrain trigger).

**What it costs.** One training run per fold per seed, strictly serial on the GCP box: 4 folds ×
3 seeds ≈ 12 runs ≈ 40–55 hours of wall clock, spread over as many sessions as needed.

---

## §1 — THE FOLD DESIGN

**The recipe is the incumbent's, unchanged:** 5m bars, `seq 384`, horizons 60/240/1440, primary
240, the twelve collected pairs, every knob at the banked default. **One thing changes per fold:
where the split falls.** Two split parameters are fixed here and are not searched:

| parameter | value | why |
|---|---|---|
| `VAL_FRACTION` | **0.125** of time-ordered samples | ≈ 160 days at today's 12-pair density; long enough for the two calendar halves §3 needs, short enough for four non-overlapping folds |
| `TRAIN_FRACTION` | **0.5** of samples, **rolling fixed-width** | every fold trains on the same number of samples, so boundary age is the only thing that moves. Anchored folds (train on all earlier data) would mix boundary age with training-set size — the confound RETRAIN_PLAN §7 B named and that this design removes. Decided 2026-09-04 |
| `VAL_OFFSET` | 0.000 / 0.125 / 0.250 / 0.375 | four non-overlapping val windows; the oldest fold's train window ends exactly at the start of history (0.375 + 0.125 + 0.5 = 1.0) |

**The folds**, with calendar spans *estimated* from the T1 run's split line (train 3.68M samples
over 2022-08-19 → 2025-12-02; val 0.92M over 267 days). ⚠️ The estimate is approximate because
sample density rises as pairs were listed; **the actual boundaries are read from each run's own
`Split walkforward_window | … | train [a → b] | val [c → d]` line and recorded in §6, never from
this table.**

| fold | `VAL_OFFSET` | val window (est.) | train window (est.) | note |
|---|---|---|---|---|
| F0 | 0.000 | ~2026-03 → 2026-09 | ~2023-12 → 2026-03 | overlaps the published split's second half; **not** untouched — reported, never used for confirmation (§4) |
| F1 | 0.125 | ~2025-10 → 2026-03 | ~2023-06 → 2025-10 | straddles the current train boundary; its val is partly inside today's model's training data but **outside this fold model's** |
| F2 | 0.250 | ~2025-04 → 2025-10 | ~2022-12 → 2025-04 | untouched by every M3 search |
| F3 | 0.375 | ~2024-11 → 2025-04 | 2022-08 → 2024-11 | untouched; fewest pairs (HYPE/WLD/ZEC/1000PEPE are late listings and may be absent) |

**Seeds.** Three per fold (`SEED=1,2,3`), so every fold statistic is a family statistic
(M3_PROTOCOL §8.3: a single-seed win is not a win). **12 runs.**

**Constants per fold (C4).** Each fold checkpoint's coverage cut and regime ladder are derived
from **its own** val window by `backtest.coverage_threshold` and the bar-quintile rule, exactly as
for the served checkpoint. Nothing is inherited from the incumbent.

### 1.1 What this design does not separate, stated now

* A fold model differs from the incumbent in **training-set size** (0.5 of samples versus 0.8)
  as well as in boundary. F0 is the control for that: same era as the published split, smaller
  train window. If F0's family is far below the incumbent on the same rows, the fixed width is
  costing accuracy and §5's freshness reading is confounded; that comparison is reported first.
* Older folds see fewer pairs. Every per-fold table therefore reports its pair count, and the
  pooled statistics are also given restricted to the pairs present in all four folds.

---

## §2 — WHAT IS SCORED

The **incumbent policy**, `cov0.02_hold240_rqnone_mcnone_SIZED` (M3_PROTOCOL §9.2), with each
fold's own cut and ladder — the rule as served. Alongside it, **reported and never selected on**,
the flat-size anchor `cov0.02_hold240_rqnone_mcnone`, so the ladder's contribution is visible
per fold as it was in M3_3_RESULTS §D2.

**No grid.** This protocol scores one rule to measure the evidence; it searches nothing. A
search over folds is a future pre-registration.

**Harness.** `ml/train/m3/` scores fold dumps under a new era, `M3_ERA=walkforward`, whose
population is the twelve `(fold, seed)` dumps and whose *window* is the fold (`w := F0..F3`) in
place of `dumps.WINDOWS`. `m3 validate` is extended with a third test — each fold dump reproduces
its own trainer log's `Fixed-coverage P&L` 240m table digit-exact — and **must pass before any
fold number is read** (C3). This harness change is code that exists before the first fold
finishes training, and is committed as such.

---

## §3 — THE DECISION RULE, UNDER M3_PROTOCOL §9.4

Reported for the family (three seeds pooled, seed as a key) on the **untouched folds F2 + F3**
pooled, and separately per fold:

| # | criterion | role |
|---|---|---|
| W1 | day-clustered 95% **lower bound** of pooled net at taker on F2 + F3 | **the ranking statistic** (§9.4) |
| W2 | each of F2, F3 individually: clustered **upper** bound of net at taker > 0 | **veto** — a fold that is significantly negative fails the rule; a merely negative point estimate does not |
| W3 | every fold holds ≥ 100 pooled trades **and** ≥ 40 exit-day clusters | eligibility, fixed from counts before P&L is read (the P4 rule, restated in clusters) |
| W4 | all three seeds pooled-positive at taker on F2 + F3 | P5, unchanged |
| W5 | trade rate ≥ 0.5 / day / seed on every fold | P6, unchanged |

**Readings, fixed now:**

* **W1 > 0 with W2–W5 holding** → the rule is confirmed out of sample on untouched history. This
  is the first result in the project that would be evidence rather than absence-of-refutation,
  and it is the precondition for any exploratory finding to be confirmed on the same folds.
* **W1 ≤ 0 with W2–W5 holding** → not decidable at four folds; the interval is reported and the
  next step is more folds (a fifth and sixth at 0.5/0.625 need `TRAIN_FRACTION` < 0.5 and are a
  new registration), not a wider rule.
* **Any W2 veto** → the rule fails on that era. That is a finding about the rule, recorded as one;
  it is not grounds to drop the fold.
* **F0 or F1 numbers never enter a promotion or confirmation argument.** They are reported for
  the §1.1 control and for continuity with the published split.

**Tier 2 for the folds:** W1 *is* Tier 2's statistic used as an axis. Whether it clears zero is
the headline, and §9.4 says in advance that it may not.

---

## §4 — WHAT THE FOLDS ARE THEN USED FOR

Once §3 has reported, in this order and each as its own short registration written before its
numbers are read:

1. **Freshness** (RETRAIN_PLAN §6's redesign): each fold's val window scored by *that* fold's
   model against the same rows scored by the *previous* fold's model (older boundary, same
   calendar). Paired by day-cluster. The freshness effect is the family-median difference with
   its clustered interval; the minimum detectable effect is printed with it and the reading is
   `NOT DECIDABLE` if it exceeds the incumbent's pooled edge.
2. **The retrain trigger's N** (M3_PROTOCOL §9.1 Q3): the distribution of dry spells of each
   fold's own cut across all folds and seeds. N is restated as the 95th percentile of that
   distribution, replacing the 65-day estimate from one split.
3. **Confirmation of parked findings** (M3_PROTOCOL §9.3): served coverage at twelve pairs, the
   hour-of-day and market-neutral probes, a learned or sequential (RL) policy under
   M3_3_PROTOCOL's leave-one-out shape with folds as the units. Each needs its own registration
   naming which folds it may read, and none may read F2/F3 for exploration first.

---

## §5 — THE RUN QUEUE

⚠️ **Strictly serial — one `gcp_train.sh` at a time.** Launch the next only after
`./scripts/gcp_status.sh` reports the previous DONE. ⚠️ **Delete the dump cache first** if it is
older than the candle repair (`rm -f /var/tmp/fluxtrader_dump_cache.sql.gz` on the VM); every fold
must be trained on repaired candles — the `cache miss` line in the launcher log confirms it.

```sh
# F0 (control) — three seeds
VAL_FRACTION=0.125 VAL_OFFSET=0.000 TRAIN_FRACTION=0.5 SEED=1 ./scripts/gcp_train.sh
./scripts/gcp_status.sh && ./scripts/gcp_logs.sh <run_id> > logs/WF-F0-s1.log
VAL_FRACTION=0.125 VAL_OFFSET=0.000 TRAIN_FRACTION=0.5 SEED=2 ./scripts/gcp_train.sh
./scripts/gcp_status.sh && ./scripts/gcp_logs.sh <run_id> > logs/WF-F0-s2.log
VAL_FRACTION=0.125 VAL_OFFSET=0.000 TRAIN_FRACTION=0.5 SEED=3 ./scripts/gcp_train.sh
./scripts/gcp_status.sh && ./scripts/gcp_logs.sh <run_id> > logs/WF-F0-s3.log
# F1, F2, F3: the same three lines with VAL_OFFSET=0.125, 0.250, 0.375
#   -> logs/WF-F1-s{1,2,3}.log, logs/WF-F2-s{1,2,3}.log, logs/WF-F3-s{1,2,3}.log
```

**Recommended order: F2 first, then F3, then F1, then F0.** F2 and F3 are the folds §3 decides
on; if the budget is interrupted, the untouched evidence exists before the control does.

🔴 **Verify every run from its own log before recording it:** the `Split walkforward_window |
val_frac=0.125 val_offset=<x> train_frac=0.5 | train [a → b] | val [c → d]` line, and the
`resolved knobs` block. A run whose split line reads `global_time` did not receive the fold
variables and is void. The checkpoint's `meta` carries `val_offset`, `train_fraction`, `run_id`
and the four boundary timestamps, so a fold can also be verified after the fact.

**Bring back per run:** the `Split` line; the `Fixed-coverage P&L` table for the **240m** head;
the `SERVED GATE (C13)` line; the run id; and the `eval_preds_<run>.parquet` fetched into
`ml/train/output/eval_dumps/`. Then, once all twelve exist:

```sh
M3_ERA=walkforward ./scripts/m3.sh -m m3 validate     # C3, the third test must PASS
M3_ERA=walkforward ./scripts/m3.sh -m m3 folds        # §3, all five criteria, per fold and pooled
```

---

## §6 — THE RECORD (filled in as folds complete; nothing above this line changes)

**The harness §2 requires exists and is committed (2026-09-04), before the first fold was
launched:** `ml/train/m3/walkforward.py` (the five criteria), the `walkforward` era in
`dumps.py`, `m3 folds` in the CLI, and validate's **TEST 3**. Both entry points run today
against an empty registry and say so:

```sh
M3_ERA=walkforward ./scripts/m3.sh -m m3 validate   # C3 — must pass before any fold is read
M3_ERA=walkforward ./scripts/m3.sh -m m3 folds      # §3; refuses a verdict until all twelve exist
```

**To record a finished run, three places, from that run's own log — never from §1's estimates:**

1. `dumps.WALKFORWARD_RUNS["F2s1"] = "<run_id>"`, and `dumps.WALKFORWARD_SPLITS["F2"]` from the
   `Split walkforward_window …` line's `val [c → d]`;
2. `validate.PUBLISHED_FIXED_COV_WALKFORWARD["F2s1"]` — the **Horizon 240m** `Fixed-coverage P&L`
   block, as `{0.01: (trades, gross_bps, win), …}`;
3. the row in the table below.

A run whose split line reads `global_time` did not receive the fold variables and is **void** —
do not record it. `m3 folds` prints every criterion against a partial registry so the queue can be
steered, but marks the whole block **PROVISIONAL** and produces no verdict until all twelve exist.

⚠️ **One thing §2 left unspecified and the harness had to choose: the pair universe.** It defaults
to the served eight (`dumps.BASE8`), the universe the rule was chosen on; `--universe 12` scores
every pair in each fold's dump, and §1.1's restriction to the pairs present in all four folds is
reported either way. If the twelve are meant to decide, say so **before the first fold is read**.


| fold | seed | run id | split line (train → / val →) | pairs | status |
|---|---|---|---|---|---|
| F2 | 1 | | | | ⚪ |
| F2 | 2 | | | | ⚪ |
| F2 | 3 | | | | ⚪ |
| F3 | 1 | | | | ⚪ |
| F3 | 2 | | | | ⚪ |
| F3 | 3 | | | | ⚪ |
| F1 | 1 | | | | ⚪ |
| F1 | 2 | | | | ⚪ |
| F1 | 3 | | | | ⚪ |
| F0 | 1 | | | | ⚪ |
| F0 | 2 | | | | ⚪ |
| F0 | 3 | | | | ⚪ |
