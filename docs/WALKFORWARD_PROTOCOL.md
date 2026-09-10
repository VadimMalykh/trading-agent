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

⚠️ **Three edits have been made since a fold was first launched, and all three are recorded here
rather than made quietly. All three are to §5, which is an operating instruction; nothing that
decides anything has moved.** The fold design (§1), what is scored (§2), the five criteria (§3), the
confirmatory status of each fold (§4) and the twelve-pair universe (§6) are untouched, and **no
fold number has ever been read** — the registry has been empty at every point below.

1. **2026-09-05, the recipe.** §5 was rewritten and §6.1 added, because the 2026-09-04 launch
   attempt was void (it trained the wrong recipe — §6.1) and §5's command was the cause. §5 was
   brought into line with the recipe §1 already specified.
2. **2026-09-05, the eval window.** §5.1 gained a **sixth** check, because the four runs it
   already passed were scored on the wrong window (§6.1) — `eval_m2.py` took the newest
   `VAL_FRACTION` of history regardless of the fold, and §5.1's five checks all read the training
   `Split` line, so none of them looked at the eval. The sixth check reads the eval block.
3. **2026-09-09, a path only.** `docs/RULES_REVIEW.md` in §5's recipe comment became
   `docs/archive/RULES_REVIEW.md`, because that file was archived on 2026-09-09 once its §6.1
   and §6.2 were both complete (its own §6.3 item 6 asked for the move). **No value, knob,
   criterion or number changed.** This entry exists only so that no edit to this file is silent.
   Unlike the first two it was made *after* all twelve runs were banked and scored, which is why
   it is confined to a file path.

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

🔴 **The command states the WHOLE recipe, every time.** This is not verbosity. `scripts/gcp_env`
is machine-local and gitignored and still holds the M2-era defaults (8 pairs, 1m candles, seq 128,
horizons 5/30/60, primary 30m), so a command that sets only the split variables inherits a recipe
nobody chose. That is exactly what voided the first fold attempt on 2026-09-04 — see §6.1. The
lines below carry §1's recipe explicitly; **`VAL_OFFSET` and `SEED` are the only parts that vary
between the twelve runs.**

```sh
# ---- the recipe, identical in all twelve runs (docs/archive/RULES_REVIEW.md §6.2, §1 above) ----
export FEATURE_GROUPS=legacy CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 EARLY_STOP_PATIENCE=20
export TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240
export TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,XRPUSDT
export VAL_FRACTION=0.125 TRAIN_FRACTION=0.5

# ---- F2 (untouched, run first) — three seeds, strictly serial ----
VAL_OFFSET=0.250 SEED=1 ./scripts/gcp_train.sh --gpu 60 384
./scripts/gcp_status.sh && ./scripts/gcp_logs.sh <run_id> > logs/WF-F2-s1.log
VAL_OFFSET=0.250 SEED=2 ./scripts/gcp_train.sh --gpu 60 384
./scripts/gcp_status.sh && ./scripts/gcp_logs.sh <run_id> > logs/WF-F2-s2.log
VAL_OFFSET=0.250 SEED=3 ./scripts/gcp_train.sh --gpu 60 384
./scripts/gcp_status.sh && ./scripts/gcp_logs.sh <run_id> > logs/WF-F2-s3.log
# F3, F1, F0: the same three lines with VAL_OFFSET=0.375, 0.125, 0.000
#   -> logs/WF-F3-s{1,2,3}.log, logs/WF-F1-s{1,2,3}.log, logs/WF-F0-s{1,2,3}.log
```

**Recommended order: F2 first, then F3, then F1, then F0.** F2 and F3 are the folds §3 decides
on; if the budget is interrupted, the untouched evidence exists before the control does.

`gcp_train.sh` refuses to launch a run that moves the split (`VAL_OFFSET` / `TRAIN_FRACTION` set)
unless every recipe knob matches the incumbent, and it refuses any *extra* forwarded knob
(`HIDDEN_SIZE`, `LR`, `FEE_RATE_BPS`, …) that would make the fold non-comparable. It prints
`recipe: incumbent (T1) exactly …` when the command is right — **that line is the go/no-go before
the VM is created**, and it costs nothing to read. A fold that deliberately departs from the
recipe needs a fresh pre-registration (M3_PROTOCOL §0) and then `ALLOW_RECIPE_DRIFT=1`.

### 5.1 Verify every run from its own log BEFORE recording it

🔴 All five must be true. A run failing any of them is **void**: do not record it, and do not
promote its checkpoint (every training run overwrites `checkpoints/latest.pt`, so after a void
run `gcp_promote.sh --checkpoint latest` would ship the wrong model — promote by explicit run id).

| # | log line | required value |
|---|---|---|
| 1 | `Split walkforward_window \| val_frac=… val_offset=… train_frac=…` | `0.125` / the fold's offset / `0.5`. **`Split global_time` means the fold variables never arrived — void.** |
| 2 | `=== resolved knobs: …` | `SEQ_LEN=384 HORIZONS=60,240,1440 PRIMARY=240`, and `PAIRS_FLAG` listing **twelve** pairs |
| 3 | `knob CANDLE_INTERVAL=…` | `5m` — its absence means 1m, a different model on ~5× the samples |
| 4 | `knob FEATURE_GROUPS=` / `knob PAIR_EMBED_DIM=` / `knob EARLY_STOP_PATIENCE=` | `legacy` / `8` / `20` |
| 5 | `Training pairs: [...]` | the twelve, not `dumps.BASE8` |
| 6 | `Val samples=… \| [c → d]`, in the **eval** block below `Checkpoint primary=…` | **the same span as check 1's `val [c → d]`.** These are two different code paths — the trainer splits, then `eval_m2.py` splits again — and until 2026-09-05 the second ignored the fold entirely and always scored the newest `VAL_FRACTION` of history. A fold scored there is still out-of-sample, so nothing else in the log looks wrong; this line is the only place the defect is visible |

The checkpoint's `meta` also carries `val_offset`, `train_fraction`, `run_id` and the four
boundary timestamps, so a fold can be verified after the fact as well.

**Bring back per run:** the `Split` line; the `resolved knobs` line; the `Fixed-coverage P&L`
table for the **240m** head; the `SERVED GATE (C13)` line; the run id; and the
`eval_preds_<run>.parquet` fetched into `ml/train/output/eval_dumps/`. Then, once all twelve
exist:

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

✅ **§2 left the pair universe unspecified; it is pinned here on 2026-09-04, before any fold was
trained: §3 is decided on TWELVE** — every pair present in each fold's own dump, the universe
actually served since 2026-08-29. `--universe 8` restricts to `dumps.BASE8` and is a diagnostic.

🔴 **The cost of that choice, and what it obliges every reading to do.** HYPE, WLD, ZEC and
1000PEPE are late listings, so older folds hold fewer pairs and a pooled number across the four
mixes universes — part of any fold-to-fold difference is the pair list moving, not the market.
§1.1 already required the pair count on every table and the pooled statistic restricted to the
pairs present in all four folds; under twelve that restricted table is **not optional garnish, it
is the control**, and it is read before any fold-to-fold difference is interpreted.


### 6.0 Notes carried with the recorded runs (observations, not decisions)

Recorded 2026-09-06 when F2 s1 and s2 were entered in the table below. None of these change
anything §1–§5 fixed; they exist so that whoever reads §3's verdict knows what was visible at
the time the runs were banked.

* **The val window drifts by hours between seeds of one fold.** F2 s1's val starts 2025-04-15
  14:05, s2's 21:30 — 7h25m later, same length. §6.1 already named the cause: the training dump
  grows between runs, so the same `val_offset` maps to a slightly later window. It is drift in the
  data, not a mis-recorded run. `dumps.WALKFORWARD_SPLITS["F2"]` holds the **first seed's** span,
  as the registry's own rule says; nothing that decides §3 reads it (`walkforward.fold_table`
  groups trades by seed → fold, never by the window tag).
* **F2's model is close to long-only on this window.** At the served gate s1 places 741 long
  trades against 7 short, s2 834 against 7; at fixed-cov 0.05 the up/down split is 26,102/2,887
  and 27,526/1,473. F2's val is 2025-04 → 2025-10, a rising market. So F2's per-fold P&L cannot
  distinguish "the rule has an edge" from "the rule was long in an up-market" on its own — which
  is exactly why §3 decides on **F2 + F3 pooled** and vetoes per fold. Read F3 (2024-11 → 2025-04)
  with this in mind; it is the fold that carries the different market.
* **Seed 1's checkpoint is epoch 1.** `epoch LB series @cov0.05: n=21 … selected=epoch 1
  (lb=0.5866)`; s2 selected epoch 11 of 31. Early selection is normal for the fold recipe (half
  the training samples, `EARLY_STOP_PATIENCE=20`) and the void 2026-09-05 F2 s3 run selected epoch
  1 too. It is recorded because a one-epoch checkpoint is worth knowing about when the fold's
  numbers are read, not because any rule bars it.
* **The two seeds ran different commits** (`30b2dae` and `a3657c7`). The diff between them is
  `config/runtime.exs` and `docker-compose.yml` only — the Elixir app's log rotation. No file under
  `ml/` changed, so both seeds trained and were scored by identical code.

### 6.1 Void runs — attempted, thrown away, not part of any statistic

| when | run id | intended | why void |
|---|---|---|---|
| 2026-09-04 | `20260904T172905Z` | F2 seed 1 | Trained the **M2-era defaults**, not the incumbent recipe: 8 pairs, 1m candles, `seq 128`, horizons `5,30,60`, primary 30m, `EARLY_STOP_PATIENCE` 10, `FEATURE_GROUPS`/`PAIR_EMBED_DIM` unset. The fold variables *did* arrive (`Split walkforward_window … val_offset=0.25`); only the recipe was wrong. Cause: §5's command set the split variables and let every other knob fall back to the gitignored `scripts/gcp_env`. Log kept at `logs/archive/VOID-WF-F2-s1-20260904T172905Z.log`. |
| 2026-09-05 | `20260904T213815Z` | F2 seed 1 | **Scored on the wrong window.** Training was correct — all five §5.1 checks pass, `Split walkforward_window … val_offset=0.25 train_frac=0.5`, val `[2025-04-15 00:50 → 2025-10-03 14:05]`, twelve pairs, 5m, repaired candles — but the eval block reports `Val samples=579424 \| [2026-03-20 05:50 → 2026-09-03 21:35]`: the newest 12.5% of history, i.e. **F0's window**, not F2's. Cause: `eval_m2.py` split with `time_split_indices(times, VAL_FRACTION)` and never read `val_offset` / `train_fraction`, and `gcp_train.sh` passes eval no split flags. Everything downstream of the eval is therefore on the wrong rows — the `SERVED GATE (C13)` cut (the C4 constants), the `Fixed-coverage P&L` tables, and `eval_preds.parquet`. Log kept at `logs/archive/VOID-WF-F2-s1-20260904T213815Z.log` |
| 2026-09-05 | `20260905T063602Z` | F2 seed 2 | Same defect. Eval window `[2026-03-20 13:50 → 2026-09-04 06:40]` against a fold val of `[2025-04-15 07:00 → 2025-10-03 20:55]`. Log kept at `logs/archive/VOID-WF-F2-s2-20260905T063602Z.log` |
| 2026-09-05 | `20260905T101852Z` | F2 seed 3 | Same defect. Eval window `[2026-03-20 17:00 → 2026-09-04 10:20]` against a fold val of `[2025-04-15 09:30 → 2025-10-03 23:40]`. Log kept at `logs/archive/VOID-WF-F2-s3-20260905T101852Z.log` |
| 2026-09-05 | `20260905T132644Z` | F3 seed 1 | Same defect. Eval window `[2026-03-20 19:45 → 2026-09-04 13:30]` against a fold val of `[2024-10-14 11:55 → 2025-04-15 11:40]`. Log kept at `logs/archive/VOID-WF-F3-s1-20260905T132644Z.log` |

Nothing was written into `dumps.WALKFORWARD_RUNS`, `validate.PUBLISHED_FIXED_COV_WALKFORWARD` or
the table below, so the registry never saw it. Two consequences were handled: §5 now states the
full recipe and lists the five lines that must be checked before a run is recorded, and
`gcp_train.sh` refuses a split-moving run whose recipe is not the incumbent's. Note also that the
void run overwrote `checkpoints/latest.pt` in the bucket, as every training run does — **promote
by explicit run id, never `--checkpoint latest`, until a valid run has replaced it.**

**On the second defect (the four 2026-09-05 runs).** It was not leakage: each fold's eval window
sits entirely after that fold's train end, so the predictions are honest out-of-sample. It voids
the runs because it voids the *design* — all four folds were scored on the **same calendar rows**,
so F2-versus-F3 is no longer a fold comparison and pooling F2+F3 for **W1** would pool the same
days twice. The four checkpoints were trained correctly and could have been re-scored eval-only
(`EVAL_ONLY_CKPT`, no retrain); the decision on 2026-09-05 was to **void and retrain** instead, so
that no fold in the record has a history of being measured twice.

Three consequences were handled. `eval_m2.py` now takes the val window from the **checkpoint's own
meta** (`split_from_meta`, selecting by the recorded `val_start` / `val_end` timestamps rather than
re-deriving the fraction, because the dump grows between runs and the same `val_offset` maps to a
window shifted by hours — the three F2 seeds' split lines already differed by ~9h); the fold
identity joined `_member_fingerprint`, so an ensemble of two different folds is refused instead of
being scored on member 0's window; and §5.1 gained check 6. Nothing was written into
`dumps.WALKFORWARD_RUNS`, `validate.PUBLISHED_FIXED_COV_WALKFORWARD` or the table below, and the
four dumps were never fetched into `ml/train/output/eval_dumps/`.

Left unfixed this would have surfaced only after all twelve runs: `WALKFORWARD_SPLITS` clips each
dump to its fold's val span, these dumps hold **zero** rows there, and every fold would have failed
**W3** with 0 trades — ~50 GPU-hours later.

| fold | seed | run id | split line (train → / val →) | pairs | status |
|---|---|---|---|---|---|
| F2 | 1 | `20260905T164940Z` | train [2023-03-31 16:30 → 2025-04-15 14:00] / val [2025-04-15 14:05 → 2025-10-04 04:35] | 12 | ✅ all six §5.1 checks pass; recorded |
| F2 | 2 | `20260906T034840Z` | train [2023-03-31 18:20 → 2025-04-15 21:30] / val [2025-04-15 21:30 → 2025-10-04 12:45] | 12 | ✅ all six §5.1 checks pass; recorded |
| F2 | 3 | `20260906T151425Z` | train [2023-03-31 20:15 → 2025-04-16 05:15] / val [2025-04-16 05:15 → 2025-10-04 21:20] | 12 | ✅ all six §5.1 checks pass; recorded |
| F3 | 1 | `20260907T004430Z` | train [2022-08-19 21:45 → 2024-10-15 07:10] / val [2024-10-15 07:10 → 2025-04-16 11:45] | 11 | ✅ all six §5.1 checks pass; recorded |
| F3 | 2 | `20260907T045358Z` | train [2022-08-19 21:45 → 2024-10-15 09:25] / val [2024-10-15 09:25 → 2025-04-16 14:35] | 11 | ✅ all six §5.1 checks pass; recorded |
| F3 | 3 | `20260907T075701Z` | train [2022-08-19 21:45 → 2024-10-15 11:10] / val [2024-10-15 11:10 → 2025-04-16 16:40] | 11 | ✅ all six §5.1 checks pass; recorded |
| F1 | 1 | `20260907T123158Z` | train [2023-10-15 01:20 → 2025-10-05 13:20] / val [2025-10-05 13:20 → 2026-03-22 13:00] | 12 | ✅ all six §5.1 checks pass; recorded |
| F1 | 2 | `20260907T145404Z` | train [2023-10-15 02:00 → 2025-10-05 15:15] / val [2025-10-05 15:15 → 2026-03-22 15:15] | 12 | ✅ all six §5.1 checks pass; recorded |
| F1 | 3 | `20260907T175833Z` | train [2023-10-15 02:45 → 2025-10-05 17:25] / val [2025-10-05 17:25 → 2026-03-22 17:45] | 12 | ✅ all six §5.1 checks pass; recorded |
| F0 | 1 | `20260908T045913Z` | train [2024-04-15 14:15 → 2026-03-23 03:25] / val [2026-03-23 03:25 → 2026-09-07 05:05] | 12 | ✅ all six §5.1 checks pass; recorded |
| F0 | 2 | `20260908T085950Z` | train [2024-04-15 15:50 → 2026-03-23 06:50] / val [2026-03-23 06:50 → 2026-09-07 09:00] | 12 | ✅ all six §5.1 checks pass; recorded |
| F0 | 3 | `20260908T141818Z` | train [2024-04-15 18:00 → 2026-03-23 11:30] / val [2026-03-23 11:30 → 2026-09-07 14:20] | 12 | ✅ all six §5.1 checks pass; recorded |

---

## §7 — THE RESULT (recorded 2026-09-09, after all twelve runs passed §5.1 and C3)

### 7.0 In plain language

**The trading rule held up on history it had never been tested on.** Four models were
retrained with the cut-off moved back in time, and the same rule was run on the months
right after each cut-off. On the two folds no policy search has ever looked at, the rule
made **+33.2 basis points per trade after costs** — a basis point is 0.01%, so that is
about **0.33% of the traded amount per round trip, net of the 14 bps taker fee-plus-slippage
assumption**. On a $1,000 position that is roughly **$3.30 a trade**, at about **4 trades a
day per model**.

**The number that decides is the lower end of the error bar, not the average**, because with
285 independent trading days the average alone could be luck. That lower bound is **+9.3 bps**
— still comfortably above zero. That is what "CONFIRMED" means here: **this is the first
result in the project that is positive evidence, rather than merely the absence of a
refutation.**

**Bottom line: the edge is real and now demonstrated out of sample — but this does not by
itself say "go trade real money."** Two things are unchanged by it. The fold models are
*handicapped* copies of the served model (see §7.2), so this measures the rule, not the
incumbent checkpoint; and nothing here touches the open real-money blockers, which are
about execution and operations, not about whether the signal exists.

### 7.1 §3's five criteria — the verdict

Command: `M3_ERA=walkforward ./scripts/m3.sh -m m3 folds`. Twelve pairs, taker 14 bps round
trip, day-clustered throughout.

| # | criterion | result |
|---|---|---|
| **W1** | pooled net at taker on F2+F3, clustered 95% **lower** bound | **+33.23 bps, CI [+9.28, +57.17]** — LB **+9.28 > 0** ✅ |
| **W2** | each decision fold's clustered **upper** bound > 0 | F2 +39.89 (hi +73.92) ✅ · F3 +25.26 (hi +58.74) ✅ |
| **W3** | ≥ 100 trades and ≥ 40 exit-day clusters per fold | F2 2318/144 · F3 1940/142 · F1 1406/93 · F0 2009/166 ✅ |
| **W4** | all three seeds pooled-positive on the decision folds | s1 +44.87 · s2 +29.78 · s3 +24.36 ✅ |
| **W5** | trade rate ≥ 0.5/day/seed on every fold | 4.48 · 3.53 · 2.79 · 3.98 ✅ |

**Verdict: CONFIRMED — W1 > 0 with W2–W5 holding.** Pooled n = 4,258 trades in 285
day-clusters. Under §3's readings this is the precondition for confirming any parked
finding (§4.3) on these folds.

### 7.2 🔴 §1.1's control fires — read this before quoting any fold number

**F0, the control, comes in at −0.66 net bps** (gross +15.51), against the incumbent's
+13.82 net pooled on the same era. F0 is the same calendar window as the published split
and differs from the incumbent only in training-set size (`TRAIN_FRACTION` 0.5 versus 0.8).
§1.1 pre-registered exactly this comparison and what it would mean: **the fixed-width train
window is costing real accuracy — on the order of 14 bps.**

Two consequences, and they point in opposite directions:

* **It makes W1 conservative, not suspect.** The confirmation was obtained with models
  handicapped by roughly half the training data. A fold family that clears zero *despite*
  that handicap is stronger evidence for the rule than the same result from full-size
  models would have been. The verdict stands as §3 wrote it.
* **It confounds the freshness reading (§4.1), as §1.1 warned.** Fold-to-fold differences
  now mix boundary age with a known ~14 bps training-size penalty. §4.1 must therefore be
  registered with that penalty as an explicit term, or on same-size models. **Do not read
  §4.1 off this table.**

Also as §1.1 required: **F3 holds 11 pairs, not 12** (HYPE is a late listing). The restricted
11-pair table is printed by `m3 folds` and is the control for any fold-to-fold comparison.
On it, F2's own CI is [−1.7, +69.1] — F2 alone is not significant at 11 pairs, which is why
§3 pools F2+F3 rather than vetoing on a per-fold lower bound.

### 7.3 One amendment was made to the harness, after C3 first failed

**Nothing that decides anything moved; the change is to a comparison, not to a criterion.**
On the first run, C3 reported FAIL on 3 of 60 cells, all in the `win` column, all off by
~0.0005 — F1s3 @0.01, F3s2 @0.05, F3s2 @0.20. `trades` and `gross_bps` matched digit-exact
in all 60 cells, then and now.

Cause: `eval_m2.py` stores `win_rate` as `round(float(wins.mean()), 4)` (line 359) and prints
it with `%5.3f` (line 1392) — a **double rounding**. `validate.py` compared a singly-rounded
value against that doubly-rounded reference with tolerance `< 0.0005`, which is precisely the
width at which a 4dp value sitting on a 3dp half-way point crosses. All three cells are
reproduced exactly by replaying the trainer's pipeline and by no other reading:

```
F1s3 0.01: raw=0.5874587459 -> round4=0.5875 -> "%.3f"=0.588 (log 0.588); single-round=0.587
F3s2 0.05: raw=0.5575146935 -> round4=0.5575 -> "%.3f"=0.557 (log 0.557); single-round=0.558
F3s2 0.20: raw=0.5225269344 -> round4=0.5225 -> "%.3f"=0.522 (log 0.522); single-round=0.523
```

The fix replicates that pipeline rather than widening a tolerance, so a genuine
one-in-last-place disagreement still fails. It was **put to the operator as an explicit
choice before any fold number was read**, because amending an acceptance test after seeing
it fail is the move a pre-registration exists to prevent; the alternatives offered were a
widened tolerance, dropping `win` from C3, and staying blocked. C3 then passed 12 of 12 with
no mismatches, and only then was `m3 folds` run.

---

## §8 — REGISTRATION: the retrain trigger's N (§4.2)

**Written 2026-09-09, before any dry-spell number was computed.** Registered under §4, which
requires each downstream use of the folds to be pre-registered separately. This one is
eligible now because §3 returned CONFIRMED, and it is the §4 item **not** confounded by the
§7.2 training-size penalty: a dry spell is a property of *when a fold's own cut is met*, and
each fold derives its own cut on its own window (C4), so a uniformly weaker model shifts the
cut down with it rather than lengthening the gaps.

### 8.1 What is being replaced

M3_PROTOCOL §9.1 Q3 (b) fixes the retrain trigger at **N = 65 days without a served bar
meeting the cut**, estimated from a single split. §4.2 restates it from the folds.

### 8.2 The statistic, fixed before it is read

* **Population:** all twelve `(fold, seed)` dumps, at the primary 240m head, twelve pairs —
  the same population and universe §3 decided on.
* **The cut, per dump:** that dump's own `backtest.coverage_threshold(conf, 0.02)`, exactly
  as §2/C4 defines it. Nothing is inherited across folds.
* **A dry spell:** the gap, in days, between consecutive *bar timestamps* whose confidence
  meets that dump's cut, pooled over pairs — i.e. the wait between one served-eligible bar
  anywhere in the universe and the next. Measured on bar timestamps, not on trades, because
  the trigger fires on bars (`Ledger.last_cut_exceeded_at` reads `policy_bars`), and a bar can
  meet the cut while the risk manager declines the trade.
* **Edge handling:** the interval from a fold's val start to its first qualifying bar, and
  from its last qualifying bar to its val end, are **censored** and excluded — neither is a
  completed spell, and including them would bias N by the arbitrary placement of the window.
* **N := the 95th percentile** of that pooled distribution, rounded up to a whole day.
* **Reported alongside, never in place of it:** the per-fold p95, the pooled p50/p90/p99 and
  max, the count of spells, and the same table restricted to the 11 pairs present in every
  fold (§1.1's control).

### 8.3 The readings, fixed now

* The folds' N **replaces** the 65-day estimate in M3_PROTOCOL §9.1 Q3 (b) whatever it comes
  out as — that is the point of restating it on more history, and a value that happens to be
  larger is not a reason to keep 65.
* If the per-fold p95s disagree by more than 2x, N is reported as **NOT DECIDABLE** on four
  folds and 65 stands, because a trigger whose value depends on which era measured it is not
  a trigger. The spread is printed before the pooled number.
* This registration reads **all four folds**, F0 and F1 included, and that is deliberate and
  permitted: §3's last bullet bars F0/F1 from *promotion or confirmation* arguments, and N is
  neither — it is an operational constant, and excluding the two most recent eras from a
  staleness estimate would bias it toward older market conditions.

### 8.4 Command

```sh
M3_ERA=walkforward ./scripts/m3.sh -m m3 dryspells      # §8's table and N
```

### 8.5 OUTCOME (2026-09-09) — N = 65 stands; §8's statistic was the wrong one

`M3_ERA=walkforward ./scripts/m3.sh -m m3 dryspells`, run once, against §8 as registered.

| fold | spells | p95 (days) |
|---|---|---|
| F2 | 34,796 | 0.00 |
| F3 | 34,823 | 0.01 |
| F1 | 34,833 | 0.00 |
| F0 | 34,856 | 0.01 |

Pooled: 139,308 spells, p50 0.00, p90 0.00, **p95 0.01**, p99 0.20, **max 21.49 days**.
Restricted to the 11 common pairs (§1.1): p95 0.01 days.

**§8.3's spread check fired and the verdict is NOT DECIDABLE, so — as pre-registered —
M3_PROTOCOL §9.1 Q3 (b)'s N = 65 days STANDS, unchanged.** Recorded as the registration
required, whatever the reason.

🔴 **But the honest reading is that §8.2 registered the wrong statistic, and the verdict
fired on rounding noise rather than on real disagreement.** Both facts are recorded here
rather than fixed by a quiet re-run:

* The "3.00x spread" is the ratio of 0.01 to 0.00 — two values that are both essentially
  zero after rounding to two decimals. It is an artifact of the printing precision, not a
  finding that the eras disagree.
* The deeper defect is the choice of **p95**. At 2% coverage over twelve pairs a qualifying
  bar arrives roughly seventy times a day, so 95% of consecutive gaps are minutes. The p95
  of that distribution measures **signal density, not silence** — it can never speak to a
  trigger denominated in months. §8.2 fixed this choice before the data was seen, and it was
  simply a bad choice.

**What the run does legitimately establish**, because §8.2 listed the maximum among the
statistics to report alongside N: across all twelve runs, ~2 years of history and four eras,
the **longest dry spell ever observed is 21.49 days** (per-run maxima range 2.00 → 21.49).
So **N = 65 sits at roughly 3x the longest silence any fold model ever produced.** It will
essentially never false-fire — and by the same token it is a very insensitive alarm.

**Not restated here.** A sharper N needs its own pre-registration, written by someone who has
not just read the table above; proposing one in this section would be choosing a statistic
after seeing the data, which is the move §8 exists to prevent. The parked item and its
revival trigger are in [BACKLOG.md](./BACKLOG.md).

🔴 **A discrepancy that matters more than N does, found while writing this up.** M3_PROTOCOL
§9.1 Q3 (b) calibrated N = 65 as ~1.25x **51.8 days**, the longest dry spell of the cut in the
*served* checkpoint's own repaired split (24.9 and 12.7 days on seeds 1 and 3). The folds'
longest spell, across four eras and twelve models, is **21.49 days** — less than half of it.

**The measurement code is validated against those published numbers.** Running
`walkforward.dry_spells` over the three repaired-era baseline dumps reproduces
M3_PROTOCOL §9.1 Q3 (b) exactly — s1 **24.9d**, s2 **51.8d**, s3 **12.7d**, against published
24.9 / 51.8 / 12.7 — so the 21.49-day fold maximum is a correctly measured number and the gap
below is real rather than an implementation artifact.

The two are not measuring the same thing, and the difference is diagnostic rather than
contradictory. **Each fold derives its own cut on its own window (C4), so a fold's qualifying
bars are ~2% of that window throughout.** The served checkpoint's cut is derived over its
whole split, and its qualifying bars are not spread evenly across it: they concentrate early
and thin out badly toward the end. A 51.8-day silence inside the very split the cut was
derived on means **the served model was already going quiet before it was ever deployed** —
which is the same phenomenon [M3_FIDELITY_RESULTS §7](./M3_FIDELITY_RESULTS.md) then measured
live, where 11 days have passed with the cut not merely unmet but never approached. Read §7
first; it is the live half of this observation and it is the more urgent one.

---

## §9 — REGISTRATIONS: confirming the parked findings on the folds (§4.3)

**Written 2026-09-09, before any of the numbers below were computed.** §4.3 requires each
parked finding to carry its own registration naming which folds it may read. These are those
registrations. §9.1 (closed at the F0+F1 gate), §9.2 (confirmed once on F2+F3: NOT
CONFIRMED) and §9.3 were run on 2026-09-10; §9.4's eligibility gate was pinned and run the
same day (FUNDABLE — end of §9.4), and the fitting registration it licensed, §9.5, was
written, explored and **closed at its exploration gate** the same day (end of §9.5).

### 9.0 🔴 Read before running any of these

1. **They are ranked below the live tail gap.** [M3_FIDELITY_RESULTS §7](./M3_FIDELITY_RESULTS.md)
   found that the served cut is above the live maximum confidence, so the forward test takes no
   trades. Every registration below is offline work that does not fix that, and the tail gap is
   the thing standing between this project and any new independent trading day. **Do that first.**
2. **The exploration/confirmation order is not optional.** §4.3: *none may read F2/F3 for
   exploration first.* Each finding is explored on **F0 + F1** (which §3 already bars from
   promotion arguments, so nothing is spent by looking) and only then confirmed on **F2 + F3**,
   once, with the confirmation statistic fixed beforehand. A finding explored on F2/F3 has
   burned the only untouched history this project has, and there is no second copy.
3. **The §7.2 training-size penalty applies to every one of these.** Fold models are ~14 bps
   weaker than the incumbent from the fixed-width train window alone. That is fine for a
   *relative* comparison (arm A versus arm B within the same fold) and fatal for any absolute
   claim. Every registration below is therefore written as a within-fold contrast.

### 9.1 Served coverage at twelve pairs

**The question.** The served cut comes from seed 2's **eight**-pair split while **twelve** are
served (`Policy` provenance, "KNOWN GAP"). T6's count-matched twelve-pair cut is 0.01288. Does
coverage at twelve pairs beat coverage at eight, on the same bars?

* **Arms:** the incumbent spec at `coverage=0.02` derived over the fold's twelve-pair
  population, against the same spec derived over its `dumps.BASE8` population and applied to
  the twelve. One variable: the population the cut is derived on.
* **Explore on F0+F1.** Confirm on F2+F3 only if the F0+F1 contrast is positive.
* **Statistic:** the day-clustered mean difference in net bps at taker, paired by fold-seed.
  **Confirmed iff** the F2+F3 clustered 95% lower bound of the difference > 0.
* **Reported with it:** realized coverage per arm per fold, because the whole defect this
  probes is that a threshold's realized coverage moves with the universe.
* **Fixed 2026-09-10, before the first run** — the harness is `walkforward.coverage12_report`,
  run as `M3_ERA=walkforward ./scripts/m3.sh -m m3 coverage12 --stage explore|confirm`. These
  resolve what the 09-09 text left open; none was chosen with a number in view:
  * **Sign.** The difference is *twelve-derived minus eight-derived*. Positive means the cut
    derived over the population actually served beats the cut derived the way the served
    constant was — over the eight-pair population — and applied to twelve.
  * **Fee.** "At taker" is `metrics.TAKER_COST_BPS` = 14, as in W1 and every registration in
    this file. The account's taker fee was corrected to 5.0/side on 2026-09-10
    ([REAL_MONEY_TRACK §5](./REAL_MONEY_TRACK.md)) and the published constant deliberately
    kept; the same contrast at the verified 11.84 line is printed beside it for information
    and decides nothing. In a within-fold contrast the fee enters only through the two arms'
    mean size, so it cannot move the sign.
  * **"Positive" for the explore gate** = the pooled F0+F1 point estimate of the difference
    > 0. Not its lower bound: §9.0 says looking at F0+F1 spends nothing, and a lower-bound
    gate on the exploration folds would make the confirmation redundant.
  * **The regime ladder is held fixed.** Both arms use the fold-seed's own bar-quintile edges
    over its full dump, so the population the cut is derived on is the only variable. The
    eight-derived arm is run through `backtest.run`'s fixed-threshold path
    (`score_col="conf", score_min=<cut>`); the harness checks on every fold-seed that this
    path reproduces the derived path exactly at the same cut, so the two arms differ in the
    cut and in nothing else.
  * **Realized coverage** = share of the fold-seed's *twelve-pair* 240m bars at or above the
    arm's cut. Also reported: the eight-derived cut's realized coverage on the four added
    pairs alone, because that is where an eight-pair cut mis-sizes.
  * **F3 holds 11 pairs and 7 of `dumps.BASE8`** (HYPE is a late listing); its "eight" arm is
    derived over the seven present. F0–F2 hold all eight.
  * **Order.** `--stage explore` reads F0+F1 only. `--stage confirm` reads F2+F3, refuses
    without `--exploration-recorded`, and is run **once**, after the explore table has been
    written into this section.

**EXPLORATION (F0+F1), run 2026-09-10 — NOT POSITIVE; F2/F3 not read; §9.1 closes here.**
Log: `logs/coverage12_explore_20260910.log`. The self-check passed on all six fold-seeds
(the fixed-threshold path reproduces the derived path exactly at the same cut).

| unit | trades A (12-derived) | net A | trades B (8-derived) | net B | diff A − B | clusters | 95% CI of diff |
|---|---|---|---|---|---|---|---|
| F0s1 | 562 | −1.81 | 556 | −2.90 | +1.09 | 107 | [−1.11, +3.28] |
| F0s2 | 825 | +3.36 | 821 | +3.48 | −0.12 | 159 | [−0.86, +0.61] |
| F0s3 | 622 | −4.96 | 610 | −5.17 | +0.21 | 145 | [−1.72, +2.13] |
| F1s1 | 455 | +35.20 | 433 | +41.80 | −6.60 | 58 | [−16.97, +3.77] |
| F1s2 | 477 | +80.88 | 432 | +77.64 | +3.24 | 69 | [−16.78, +23.26] |
| F1s3 | 474 | +66.36 | 440 | +127.49 | −61.12 | 78 | [−176.40, +54.16] |
| F0 pooled | 2,009 | −0.66 | 1,987 | −0.96 | +0.29 | 166 | [−0.67, +1.26] |
| F1 pooled | 1,406 | +61.20 | 1,305 | +82.55 | −21.35 | 94 | [−59.87, +17.17] |
| **F0+F1 pooled** | 3,415 | +24.81 | 3,292 | +32.15 | **−7.34** | 260 | [−21.85, +7.17] |

At the verified 11.84 line the pooled difference is −7.34 [−21.84, +7.17] — identical to two
decimals, as the fee bullet above predicted.

Realized coverage, the column the registration asked for: the eight-derived cut is **tighter**
on every fold-seed (cut B ≥ cut A), so on the twelve it realizes 1.77–1.99% instead of 2.00%,
and on the four added pairs alone 1.30–1.97%. The served "KNOWN GAP" is therefore an
under-trading of the added pairs by at most 0.7 percentage points of coverage, not a
mis-sizing of the whole book.

**Reading, with the same scrutiny a positive result would get.** The pooled point estimate is
negative, so the explore gate is not met and the confirmation is not run — that is the whole
of what §9.1 decides. It is *not* evidence that the twelve-derived cut is worse: the interval
is wide and includes zero, and the point estimate is carried by F1s3, where the ~34 marginal
trades that arm A adds happen to be very bad (net +66 against +127 on a base of 440). F0, the
fold with the tightest intervals, is +0.29 [−0.67, +1.26] — nil. What the table does say is
directionally consistent with T6: since B ⊂ A on every fold-seed, the difference *is* the
marginal trades a looser cut admits, and on these folds they earn nothing. Consequence for the
parked "Re-pre-register the served coverage" item: re-deriving the served cut over twelve is
not a lever worth a registration; the lever T6 pointed at — the cut *level* — is untouched by
this test and stays parked on its own terms.

### 9.2 The hour-of-day probe

**The question.** Does restricting entries by UTC hour improve net bps, or is the hour effect
seen on the published split an artifact of it?

* **Arms:** the incumbent unrestricted, against the incumbent restricted to the hour set
  chosen **on F0+F1 alone**. The hour set is chosen once, written into this section before
  F2/F3 is touched, and never revised.
* **Statistic:** as §9.1. **Confirmed iff** the F2+F3 clustered 95% lower bound of the
  difference > 0 **and** the chosen hour set retains ≥ 60% of trades — a filter that confirms
  by discarding most of the sample is a coverage change wearing a costume.
* 🔴 **The hour set MUST be recorded here before F2/F3 is read.** Chosen set: *(see
  "Exploration" below once run).*
* **Fixed 2026-09-10, before the first run** — harness `walkforward.hourofday_report`, run as
  `M3_ERA=walkforward ./scripts/m3.sh -m m3 hourofday --stage explore` and then
  `--stage confirm --exploration-recorded --hours <set>`, the set transcribed from this section:
  * **There is no published-split hour effect to confirm.** The probe was filed in
    CANDLE_POLL_DEFECT §(exploratory lane) and archive/RULES_REVIEW notes the lane was never
    used; §9.2's "hour effect seen on the published split" does not exist in the record. So
    F0+F1 is the first look, and the choice rule below is the whole of the exploration.
  * **The hour** of a trade is the UTC hour of its entry bar's timestamp (`entry_ts`).
  * **The choice rule, mechanical.** Run the incumbent unrestricted on F0+F1 (six seeds
    pooled). Rank the 24 UTC hours by mean net bps at taker of the trades entered in that
    hour. Take hours in descending order until the cumulative share of F0+F1 unrestricted
    trades reaches ≥ 60%. That set, and no other, is the hour set. No contiguity is imposed
    and no hour is hand-added or hand-removed.
  * **The restricted arm** keeps the incumbent's cut — derived over the fold-seed's full
    population exactly as `m3 folds` — and drops selected bars whose hour is outside the
    set *before* the serial-per-pair simulation, so a freed pair may take a later bar. It is
    re-simulated, not sub-sampled: this is what a served hour filter would do.
  * **Sign.** diff = restricted − unrestricted. Positive means the filter helps.
  * **Retention** = restricted-arm trades ÷ unrestricted-arm trades on the re-simulated arms,
    checked on F2+F3 at confirmation (the registered ≥ 60%); reported on F0+F1 too.
  * **Fee** as §9.1: `metrics.TAKER_COST_BPS` = 14 decides; the verified 11.84 line is
    printed for information.
  * **Power.** The confirmation report prints the F2+F3 clustered SE of the difference and
    1.96 × SE as the minimum detectable effect, so "not confirmed" is read against what the
    test could have seen. The F0+F1 SE is printed at exploration as a forecast.
  * **Order.** `explore` reads F0+F1 only and has no gate: the in-sample contrast is positive
    by construction and decides nothing. `confirm` reads F2+F3 once, refuses without
    `--exploration-recorded`, and takes the hour set only from `--hours`, so the recorded set
    is the one that is run.

**EXPLORATION (F0+F1), run 2026-09-10.** Log: `logs/hourofday_explore_20260910.log`. The
unrestricted F0 arm reproduces §7.2's −0.66, so the backtester's new `entry_hours` field is a
no-op when unset.

The 24 UTC entry hours, F0+F1 unrestricted, six seeds pooled (3,415 trades), mean net bps at
taker 14 — the ranking input of the choice rule:

| hour | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| trades | 144 | 143 | 125 | 139 | 125 | 147 | 139 | 150 | 140 | 119 | 119 | 128 |
| net | +165.0 | +41.3 | +16.3 | +83.2 | +15.8 | +6.8 | +2.1 | +26.9 | −48.5 | +11.9 | +68.3 | +36.4 |

| hour | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| trades | 130 | 169 | 157 | 154 | 162 | 143 | 134 | 180 | 170 | 139 | 120 | 139 |
| net | +71.7 | +29.6 | +26.9 | −49.3 | −125.5 | −85.2 | +31.8 | −0.2 | −20.1 | +314.7 | +42.0 | −9.1 |

🔴 **CHOSEN HOUR SET (UTC), by the rule, recorded before F2/F3 is read:**
**{0, 1, 2, 3, 4, 5, 7, 9, 10, 11, 12, 13, 14, 18, 21, 22}** — 16 hours, 64.1% of the
unrestricted F0+F1 trades by entry hour. Excluded: 6, 8, 15, 16, 17, 19, 20, 23. Read as a
texture only: the excluded block is mostly the US afternoon (15–17, 19–20 UTC).

In-sample contrast on F0+F1 (restricted − unrestricted, day-clustered, taker 14):

| unit | n restricted | net restricted | n unrestricted | net unrestricted | diff | clusters | 95% CI |
|---|---|---|---|---|---|---|---|
| F0 pooled | 1,716 | +3.42 | 2,009 | −0.66 | +4.08 | 167 | [−2.58, +10.73] |
| F1 pooled | 1,207 | +89.83 | 1,406 | +61.20 | +28.63 | 94 | [+0.51, +56.74] |
| F0+F1 pooled | 2,923 | +39.10 | 3,415 | +24.81 | +14.29 | 261 | [+1.51, +27.08] |

Re-simulated retention 85.6% (the by-hour share is 64.1%; freed pairs take later bars).
Power forecast for F2+F3 from the F0+F1 clustered SE of 6.52 bps: minimum detectable effect
≈ 12.8 bps per trade. The in-sample +14.29 is selected on these very trades and is not
evidence of anything.

**CONFIRMATION (F2+F3), run once 2026-09-10 — NOT CONFIRMED.** Log:
`logs/hourofday_confirm_20260910.log`, hour set passed verbatim from above. The unrestricted
F2+F3 arm reproduces W1's +33.23 on 4,258 trades, so the two harnesses agree.

| unit | n restricted | net restricted | n unrestricted | net unrestricted | diff | clusters | 95% CI |
|---|---|---|---|---|---|---|---|
| F2s1 | 585 | +37.42 | 747 | +49.26 | −11.83 | 110 | [−34.63, +10.96] |
| F2s2 | 652 | +37.18 | 830 | +36.37 | +0.81 | 135 | [−21.25, +22.87] |
| F2s3 | 606 | +35.05 | 741 | +34.40 | +0.65 | 105 | [−20.95, +22.25] |
| F3s1 | 631 | +50.13 | 725 | +40.35 | +9.79 | 87 | [−13.79, +33.37] |
| F3s2 | 498 | +34.54 | 567 | +20.14 | +14.41 | 92 | [−10.99, +39.80] |
| F3s3 | 549 | +26.08 | 648 | +12.87 | +13.21 | 137 | [−7.57, +33.99] |
| F2 pooled | 1,843 | +36.56 | 2,318 | +39.89 | −3.34 | 144 | [−22.03, +15.36] |
| F3 pooled | 1,678 | +37.64 | 1,940 | +25.26 | +12.38 | 143 | [−5.88, +30.64] |
| **F2+F3 pooled** | 3,521 | +37.07 | 4,258 | +33.23 | **+3.84** | 286 | **[−9.50, +17.19]** |

Retention 82.7% (passes the 60% floor). At the verified 11.84 line: +3.89 [−9.46, +17.23].
Clustered SE of the difference 6.81 bps; **minimum detectable effect 13.3 bps per trade.**

**Reading.** The registered criterion — lower bound > 0 — is not met, so the hour filter is
**not confirmed** and does not enter the served rule. The in-sample +14.29 on F0+F1 shrank to
+3.84 out of sample, which is the ordinary fate of a 24-way selection. The two decision folds
split in sign (F2 −3.3, F3 +12.4). Under the negative-results discipline this is **"not
detectable at this power"**, not "hours do not matter": an effect under ~13 bps per trade is
invisible to this test, and the point estimate sits inside that band. Closed on these folds;
🔴 the hour set may not be re-chosen or re-tested on F2/F3 — those folds have now been read
for this question. **Revival trigger:** a larger untouched sample (more folds under a new
registration, or forward paper days), scored against the *same* recorded set.

### 9.3 The market-neutral probe

**The question.** Does netting concurrent long and short exposure across pairs improve net bps
per unit of notional?

* **Arms:** the incumbent as served, against the same entries with per-bar exposure netted
  across the universe.
* **Statistic:** day-clustered mean net bps **per unit of notional**, not per trade — the
  arms deploy different notional by construction, and per-trade would reward the arm that
  simply trades smaller. (This is the same trap M3_5_INTEGRATION §4 recorded for the
  `flat_size` control.)
* **Confirmed iff** the F2+F3 clustered 95% lower bound of the difference > 0.
* **Fixed 2026-09-10, before the first run** — harness `walkforward.marketneutral_report`,
  run as `M3_ERA=walkforward ./scripts/m3.sh -m m3 marketneutral --stage explore|confirm`.
  The 09-09 text names the arms and the statistic but not the construction; these resolve
  it, and none was chosen with a number in view:
  * **What "netted across the universe" is, operationally.** Two different pairs cannot be
    netted into one position; what nets is their *market* exposure. So the market-neutral
    arm holds the incumbent's positions and a hedge in the market proxy sized to hold the
    book's net directional exposure at zero. The proxy is **BTCUSDT** — the deepest book
    and the cheapest crossing in M3-4 — and the hedge ratio is **1.0 (dollar-neutral)**:
    the only parameter-free choice, and the one a "market-neutral book" ordinarily means.
    Beta-neutral needs a fitted beta and a lookback, which is a second variable.
  * **Netting is at the instrument level, per event.** The hedge target at any moment is
    minus the sum of `side × size` over open non-BTC positions. It changes only at entries
    and exits; changes falling on the same bar net before anything is traded (a long entry
    and a short entry on one bar need no hedge); the notional traded is the sum of the
    absolute changes, and one round trip is two changes. An incumbent entry **on BTC
    itself** nets against its own hedge to zero: the market-neutral arm never opens it, and
    its count is reported.
  * **P&L.** Each non-BTC trade earns `size × side × (r_pair − r_BTC)` over its own 240m
    window, `r_BTC` being BTC's `fwd_ret` at the entry bar in the same fold-seed dump. That
    is exactly the P&L of a per-entry hedge leg; netting changes what is *traded*, not what
    is *held*, so the held P&L is the same, up to the second-order term from re-sizing a
    simple-return position (O(r²), well under a basis point on a 4h window; ignored).
  * **Notional** = the sum of `size` over the arm's entered trades plus, for the
    market-neutral arm, half the hedge turnover. **Net bps per unit of notional** =
    (Σ gross P&L − c × Σ notional) ÷ Σ notional, `c` the round-trip cost line. Because the
    fee is `c` per unit of notional in **both** arms, **the difference between the arms
    does not depend on the fee line at all** — the hedge's cost enters through the extra
    notional in the denominator, not through `c`. The two lines are printed anyway; they
    show the same difference.
  * **Sign.** diff = market-neutral − incumbent, per unit of notional. Positive means the
    hedged book earns more per unit deployed.
  * **Interval.** The cluster-robust standard error of a difference of two ratios, by the
    usual linearisation, with the same G/(G−1) correction and the same cluster key as
    `paired_diff_bps`: a trade clusters on its exit day, a hedge change on the day it is
    traded. The explore stage prints the F0+F1 SE and 1.96 × SE as the forecast minimum
    detectable effect; the confirm stage prints its own.
  * **Explore gate** as §9.1: the pooled F0+F1 point estimate > 0 authorises one
    confirmation run; nothing is chosen at exploration, so no lower-bound gate there.
  * **Reported with it:** the hedge notional as a share of the trade notional, netted and
    un-netted (what the netting buys), and the un-netted variant's per-notional line for
    information; the incumbent's BTC entries that the neutral arm never opens; the realised
    beta of the incumbent's non-BTC legs to BTC over their own hold windows (the
    exposure-weighted slope of `side × r_pair` on `side × r_BTC`), so the residual exposure
    the 1.0 hedge leaves is visible; and the incumbent's per-trade pooled net, which must
    reproduce §7's numbers (−0.66 on F0, +33.23 on F2+F3) or the harness is wrong.
  * **An entry whose bar has no BTC row** cannot be hedged at that bar and is dropped from
    **both** arms, with the count printed; if that exceeds 1% of entries the run refuses
    and this registration is revisited before anything is read.
  * **Order** as §9.1: `--stage explore` reads F0+F1 only; `--stage confirm` reads F2+F3,
    refuses without `--exploration-recorded`, and is run **once**, after the explore table
    has been written into this section.

**EXPLORATION (F0+F1), run 2026-09-10 — NOT POSITIVE; F2/F3 not read; §9.3 closes here.**
Log: `logs/marketneutral_explore_20260910.log`. No entry lacked a BTC row on any fold-seed.
The incumbent's per-trade net reproduces §7 exactly (−0.66 on F0, +61.20 on F1, +24.81
pooled), so the two harnesses agree.

The books (section A of the log). "Share netted" is the hedge's round-trip notional as a
fraction of the trade notional it hedges; per-leg hedging would be 1.000.

| seed | entries | on BTC (not opened) | hedged trades | trade notional | hedge notional, netted | share netted | realised beta to BTC |
|---|---|---|---|---|---|---|---|
| F0s1 | 562 | 123 | 439 | 533.7 | 410.7 | 0.770 | 1.35 |
| F0s2 | 825 | 141 | 684 | 763.3 | 678.3 | 0.889 | 1.32 |
| F0s3 | 622 | 130 | 492 | 564.7 | 448.7 | 0.795 | 1.18 |
| F1s1 | 455 | 93 | 362 | 516.3 | 302.3 | 0.586 | 1.27 |
| F1s2 | 477 | 104 | 373 | 508.7 | 316.7 | 0.623 | 1.78 |
| F1s3 | 474 | 91 | 383 | 548.7 | 335.7 | 0.612 | 2.25 |

The contrast (section B), net bps **per unit of notional** at taker 14, day-clustered,
diff = market-neutral − incumbent:

| unit | n inc | notional inc | net inc | n mn | notional mn | net mn | diff | clusters | 95% CI of diff |
|---|---|---|---|---|---|---|---|---|---|
| F0s1 | 562 | 686.3 | −1.48 | 439 | 944.3 | −10.24 | −8.76 | 112 | [−23.99, +6.48] |
| F0s2 | 825 | 923.3 | +3.00 | 684 | 1,441.7 | −11.02 | −14.02 | 163 | [−24.37, −3.68] |
| F0s3 | 622 | 711.7 | −4.33 | 492 | 1,013.3 | −15.40 | −11.06 | 147 | [−21.70, −0.42] |
| F1s1 | 455 | 645.0 | +24.83 | 362 | 818.7 | +0.46 | −24.37 | 64 | [−66.64, +17.90] |
| F1s2 | 477 | 650.7 | +59.29 | 373 | 825.3 | +19.99 | −39.30 | 78 | [−85.47, +6.87] |
| F1s3 | 474 | 679.7 | +46.28 | 383 | 884.3 | +27.08 | −19.20 | 83 | [−74.05, +35.65] |
| F0 pooled | 2,009 | 2,321.3 | −0.57 | 1,615 | 3,399.3 | −12.11 | −11.53 | 167 | [−19.81, −3.26] |
| F1 pooled | 1,406 | 1,975.3 | +43.56 | 1,118 | 2,528.3 | +16.15 | −27.42 | 98 | [−73.40, +18.57] |
| **F0+F1 pooled** | 3,415 | 4,296.7 | +19.72 | 2,733 | 5,927.7 | −0.06 | **−19.77** | 265 | [−42.22, +2.67] |

At the verified 11.84 line both arms move up by 2.16 and the difference is −19.77
[−42.22, +2.67] to the digit, as the fee bullet derived. Hedged leg by leg instead of
netted the book is −1.97 per unit (diff −21.69), so the netting is worth under 2 bps per
unit here. Clustered SE of the difference 11.45 bps; the F2+F3 minimum detectable effect
would have been ≈ 22 bps per unit of notional.

**After-the-fact diagnostic, F0+F1 only** (`logs/marketneutral_explore_diag_20260910.log`;
computed after the gate was read, decides nothing — recorded because the reading below
needs it): the hedge halves the day-clustered SE per unit of notional (18.06 → 9.41, ratio
0.52; 0.64 on F0, 0.54 on F1). The incumbent's non-BTC legs earn +40.14 bps gross per unit
of trade notional, **of which +16.08 is the BTC component `side · r_BTC`** — the part a
dollar hedge removes — leaving +24.06 residual (F0: +13.83 gross, +10.38 market, +3.45
residual; F1: +71.26, +22.82, +48.44). The incumbent's own BTC trades, which the neutral
arm never opens, earn +8.11 gross per unit over 682 trades.

**Reading, with the same scrutiny a positive result would get.** The pooled point estimate
is negative, so the explore gate is not met and the confirmation is not run — that is the
whole of what §9.3 decides. The interval includes zero, so the folds do not *prove* the
neutral book is worse; but the sign is the same on all six fold-seeds and F0's own interval
sits below zero. The mechanism is visible in the diagnostic and is not noise: **on these
folds the incumbent's edge is substantially a market-direction call expressed through the
alts** — two-fifths of its gross per unit is the BTC move its sides agree with — so
neutralising the market throws that part away, and the hedge then costs almost a full
second trade because offsetting long/short positions are rare at 2% coverage (netted share
0.59–0.89). What the hedge does buy is variance: the daily SE per unit halves. Under the
registered statistic — mean per unit of notional — that is worth nothing, and even as a
mean-over-SE reading the neutral book is not ahead at taker 14 (+19.72/18.06 against
−0.06/9.41). The realised beta of the alt legs to BTC is 1.2–2.3, so a beta-neutral hedge
would remove *more* of the market component and more notional, not less; it is not the
un-tried variant that would rescue this. Closed on these folds; 🔴 the construction may not
be re-chosen or re-tested on F2/F3 for this question. **Revival trigger:** a checkpoint
whose non-BTC legs carry most of their gross in the residual after `side · r_BTC` is removed
(measured on new untouched folds or forward paper days, never on F2/F3), or a registered
*risk* objective — a drawdown or daily-loss constraint the forward test shows to be binding —
under which a partial hedge is a risk tool rather than an edge claim.

### 9.4 A learned or sequential (RL) policy

**The question.** M3_PROTOCOL §9.3 records RL as "not forbidden but unfundable on ~220
independent days". The folds roughly triple that. Is it fundable now?

* **Shape:** M3_3_PROTOCOL's leave-one-out design with **folds as the units** — fit on three
  folds, score the held-out one, four times. Seeds stay within their fold.
* **Eligibility gate, checked BEFORE any fitting:** the pooled fold sample must clear
  M3_3_PROTOCOL's minimum-detectable-effect bar against the incumbent's edge. **If it does
  not, the answer is "still unfundable" and no model is fitted** — that is a real answer and
  it costs nothing.
* **Statistic:** the learned arm must beat the incumbent by a clustered 95% lower bound > 0 on
  the held-out folds, under M3_PROTOCOL §8.3's champion–challenger rule (a single-seed win is
  not a win).
* 🔴 **0 of 8 learned runs have ever passed on the published split**
  ([M3_3_RESULTS_REPAIRED.md](./M3_3_RESULTS_REPAIRED.md)). This registration does not
  re-open that; it asks the narrower question of whether more history changes it.
* **Fixed 2026-09-10, before the first run** — harness `walkforward.rlgate_report`, run as
  `M3_ERA=walkforward ./scripts/m3.sh -m m3 rlgate`. The bullet above says "M3_3_PROTOCOL's
  minimum-detectable-effect bar", but that document never wrote one down as a number — it
  sized the model class against a *capacity* budget (≈188 clusters per fit, its §4.1) and
  M3_PROTOCOL §2 made the fundability argument in words (220 independent days cannot certify
  a 15-bps edge net of a 14-bps round trip). So the bar is pinned here, in the same form §4
  item 1 already uses for freshness: **the reading is NOT DECIDABLE if the minimum detectable
  effect exceeds the incumbent's pooled edge.** Everything below is fixed before the command
  exists.
  * **The gate asks one question:** could the registered statistic — a day-clustered 95%
    lower bound of (learned − incumbent) on the held-out folds — detect a challenger that
    beats the incumbent by less than the incumbent's own edge? If not, a "win" would require
    the challenger to roughly *double* the edge, and fitting is not funded.
  * **E, the edge:** the incumbent's pooled net at taker 14 over **all four folds**, day-
    clustered, exactly as `m3 folds` computes it — the leave-one-out shape holds every fold
    out once, so all four are the challenger's sample. Every per-fold input is already public
    in §7.1 (F2 +39.89, F3 +25.26, F1 +61.20, F0 −0.66); pooling them reads nothing new. The
    F2+F3-only figure (W1, +33.23) is printed beside it for the confirmation-only shape.
  * **SE, the contrast's standard error — forecast from F0+F1 only.** No learned arm exists,
    so the SE of (challenger − incumbent) is calibrated on **fitting-free stand-ins** that
    bracket how much a challenger's trade set can overlap the incumbent's, run on the
    exploration folds F0+F1 (which §9.0 rule 2 lets anything read) and never on F2/F3:
    * **stand-in (i), same entries:** the flat-size anchor `cov0.02_hold240_rqnone_mcnone`
      against the incumbent — identical bars, only the ladder differs. The smallest SE a
      challenger can plausibly have.
    * **stand-in (ii), different entries:** M3-1's `cov0.05_hold240` slice (flat size, the
      candidate pool M3_3_PROTOCOL §3.4 fitted over) against the incumbent — a superset
      entry set with 2.5× the trades. The least overlap a learned arm on the same
      observation vector has shown.
    * The contrast SE is `universe.paired_diff_bps` on F0+F1 pooled, the estimator every
      §9 probe used. **The larger of the two is the calibration** — the gate is conservative
      by construction, so a "fundable" reading is not an artefact of picking the tight one.
  * **The forecast to four folds** scales the F0+F1 SE by
    `sqrt(D_F0+F1 / D_all)`, where D is the incumbent's own exit-day cluster count on those
    folds (public: 166 + 93 = 259 versus 545 over four). The F2+F3-only forecast uses
    D_F2+F3 = 286 the same way. Both are printed.
  * **MDE** = 1.96 × forecast SE, the convention §9.2 and §9.3 printed and read against; the
    80%-power figure, 2.80 × SE, is printed for information and decides nothing.
  * **The reading, fixed now:** **FUNDABLE iff MDE (at the larger calibration, four-fold
    shape) < E.** Otherwise **STILL UNFUNDABLE**, no model is fitted, and the row closes with
    the revival trigger "more independent days" — forward paper days or further folds under
    a new registration. FUNDABLE does **not** start any fitting: it licenses writing the
    fitting registration, which must also settle how the leave-one-out shape (fitting on
    F2/F3 to score F0/F1) squares with §9.0 rule 2, a question this gate does not answer.
  * **For information only, printed and not part of the gate:** the ladder's own
    contribution on F0+F1 (stand-in (i) with the sign reversed, sized − flat), because it is
    the size of the last improvement that actually passed and the natural scale for what a
    challenger could plausibly add. It is not the bar, because the bullet at the top of
    this section names the incumbent's edge, and that was written before any of this.
  * **Fee** as §9.1: taker 14 decides; the verified 11.84 line is printed for information.

**OUTCOME (2026-09-10) — FUNDABLE under the registered bar, by a margin that deserves a plain
reading.** Log: `logs/rlgate_20260910.log`. Section A reproduces §7.1 line for line (F2 +39.89,
F3 +25.26, F1 +61.20, F0 −0.66), so the gate's harness agrees with the fold verdict. Nothing
was fitted; F2/F3 entered no contrast.

| quantity | value |
|---|---|
| **E**, incumbent pooled over four folds, taker 14, day-clustered | **+29.48 bps/trade** [+5.59, +53.37], 7,673 trades, 544 clusters (545 summed per fold; one exit day is shared at the F2/F3 boundary) |
| W1, F2+F3 only | +33.23 [+9.28, +57.17], 285 clusters |
| contrast SE on F0+F1, stand-in (i) flat anchor − incumbent | 8.72 bps (diff −13.04 [−30.14, +4.05], 260 clusters) |
| contrast SE on F0+F1, stand-in (ii) cov0.05 flat − incumbent | **13.10 bps** (diff −25.53 [−51.20, +0.14], 317 clusters) — the calibration |
| forecast SE, four-fold shape (D 259 → 545) | 9.03 bps |
| **MDE, four-fold shape (1.96 × SE)** | **17.70 bps/trade** (80% power: 25.30) |
| MDE, F2+F3-only shape (D 259 → 286) | 24.43 bps/trade (80% power: 34.92) |
| ladder's own contribution on F0+F1, sized − flat (information) | +13.04 bps/trade |

**The gate: MDE 17.70 < E +29.48 → FUNDABLE.** The confirmation-only shape would also pass
(24.43 < 33.23).

**Reading, in plain terms.** The folds hold enough independent days that a learned challenger
adding *at least ~18 bps per trade* on top of the incumbent — roughly 60% more edge — could be
seen at the conventional bar, and ~25 bps could be seen with 80% power. That is what "fundable"
means here and all it means. Two things it does not mean. (1) A challenger the size of the
last improvement that actually passed — the regime ladder, worth +13 bps on these same folds —
would still be **invisible**: 13 < 17.7. So this gate funds a search for a *large* improvement,
not an incremental one, and the bar was set that way in the bullet at the top of this section
before any of this was measured. (2) It does not re-open M3-3's result: 0 of 8 learned runs
passed on the published split, and the extra observations there *cost* money
(M3_3_RESULTS_REPAIRED §F). More history makes a win detectable; it does not make one likely.

**What FUNDABLE licenses: writing the fitting registration, and nothing else.** That
registration has to settle, before any fit, at least: (a) the leave-one-out shape — fitting on
F2/F3 to score F0/F1 uses the untouched folds as training data, which §9.0 rule 2 did not
anticipate; the clean alternative is fit on F0+F1 (the folds anything may read), confirm once
on F2+F3, at MDE 24.4; (b) whether the class is M3_3_PROTOCOL §4's two ridge models unchanged
(the honest replication) or one of §7.1's logged proposals; (c) the per-fold training-size
penalty of §7.2, which makes every comparison within-fold only. **Whether to spend on this at
all is a decision, not a consequence**: the expected payoff is low (M3-3's history), the cost is
a protocol plus CPU only, and it competes with nothing that needs the market. It is filed in
BACKLOG.md as parked with that framing. **Revival trigger for a larger effect window:** forward
paper days, or further folds under a new registration, both of which lower the MDE.

### 9.5 The learned challenger on the folds — the fitting registration

**Written 2026-09-10, after §9.4's gate read FUNDABLE and before any fit ran.** Vadim decided
the same day to fund it. Harness `learnfolds.py`, run as
`M3_ERA=walkforward ./scripts/m3.sh -m m3 learnfolds --stage explore` and then, only if the
exploration gate passes and its table is recorded here,
`--stage confirm --exploration-recorded --config <label>` with the label transcribed from
this section. **CPU only, closed-form, inside the analysis container; no training instance is
involved** — the "training" is a ridge solve on a few hundred thousand rows.

**What is fitted: M3_3_PROTOCOL §4, unchanged.** Two ridge classes — **A** (the nine rank
features of `features.FEATURES`, linear) and **B** (the nine plus squares plus the eight
`conf_rank × context` products, 26 terms) — under entry rules **R1** (score ≥ 14 bps) and **R2**
(top 2% of each fold-seed's bars) and sizings **S1** (flat) and **S2** (`clip(s/s_ref, 1/3,
5/3)`): the same **8 configurations**, on the same top-10%-by-confidence candidate pool, with
every rank computed within its own fold-seed's bar population. Nothing is added, for the
reason M3_3_PROTOCOL §4.1 gave: the confirmation fit sees ~400 exit-day clusters (F0 166 +
F1 93 + one of F2/F3), which is twice M3-3's 188 and still nowhere near what a tree ensemble
or a network needs. **The "sequential (RL)" half of §9.4's question is closed on
representation, not on power:** the dumps carry no price path inside a trade
(`features.py`, rule 4), so under a fixed 240-minute hold there is no exit decision for a
sequential policy to learn. Its revival trigger is a price/funding side-table over the fold
era, which does not exist.

**The unit is the fold.** A fold's three seeds are pooled into one fit and one held-out
scoring, as M3-3 pooled its three seeds; `dumps.add_window` already tags every bar with its
fold in this era. **Every held-out score is therefore out-of-fold *and* out-of-checkpoint** —
the bars being scored come from checkpoints the fit never saw — which is a stricter test than
M3-3 could run and is exactly what the rank-only observation vector (rule 1) was built for.

**The shape, under §9.0 rule 2:**

* **`explore` — F0 + F1, two-unit leave-one-out.** Fit on F1, score F0; fit on F0, score F1.
  Both F0 and F1 scores are out-of-fold. Every one of the 8 configurations is scored, plus the
  four **C2 confidence-only ablations** (a ridge on `conf_rank` alone under each rule pairing)
  for information: whether the eight other observations add anything is the question M3-3
  asked, and it is re-asked here at no cost to F2/F3.
* **`confirm` — F2 + F3, once.** Fit on F0 + F1 + F3, score F2; fit on F0 + F1 + F2, score F3.
  F2's and F3's *outcomes* are each read once. Using F3 as training data to score F2 (and vice
  versa) happens at confirmation only, which rule 2 — "none may read F2/F3 for exploration
  first" — permits; it is stated here so nobody later reads it as a leak. Only the one
  configuration chosen at exploration is run.

**The ridge penalty**, M3_3_PROTOCOL §4.2's grid {0.003 … 3.0} and rule (highest inner metric,
ties to the larger λ), selected **inside the training folds only**. The inner units cannot be
seeds (three seeds of one fold overlap the same calendar days) and a single training fold has
no inner folds otherwise, so the inner units are the **calendar halves of each training fold**
(split at the midpoint of the fold-seed's bar timestamps), leave-one-half-out; the inner metric
is `learn._inner_metric` unchanged (raw per-bar mean net at taker under R2, budget 2% of each
seed-half's bars). The outer held-out fold is never consulted.

**The R2 budget at the outer stage is 2% of each fold-seed's bars** — the same budget the
incumbent's cut spends on the same dump, so R2 arms are matched in trade count to the
incumbent by construction. **`s_ref` for S2** comes from the training folds' fitted values
under the configuration's own entry rule (`learn.apply_rules`, unchanged).

**The contrast** is learned − incumbent, where the incumbent is `m3 folds`' SIZED spec scored
on the *same* dump (§7.2: within-fold only), by `universe.paired_diff_bps` — day-clustered on
the union of exit days, taker 14 bps, **per trade** (the registered statistic in §9.4). Net per
unit of notional is printed for information because both arms vary size; it decides nothing.
The verified 11.84 line is printed for information.

**The choice rule at exploration, mechanical:** of the 8 configurations, the one with the
**highest pooled F0+F1 out-of-fold diff** against the incumbent. Its label, its two chosen λ
and the full table are recorded here before `confirm` is run. **Exploration gate, as §9.3:**
if that best diff is ≤ 0, the registration closes here and F2/F3 are not read. The chosen
configuration's matched C2 ablation is recorded beside it for information — if the ablation
is within the noise of the winner, the eight extra observations have again added nothing.

**The confirmation criterion, fixed now.** **CONFIRMED iff** the pooled F2+F3 clustered 95%
lower bound of the diff is **> 0** **and** the diff is positive on the **median seed-number**
(s1, s2, s3 each pooled across F2+F3 — M3_PROTOCOL §8.3: a single-seed win is not a win).
Read against §9.4's forecast MDE for this shape, **24.4 bps/trade**: NOT CONFIRMED means "not
detectable at this power" unless the interval excludes the ladder-sized effect too.

**What each outcome licenses.** CONFIRMED licenses a registration to *serve* the challenger
under M3_PROTOCOL §8.3 C1–C5 on the served checkpoint's own split — it is not itself a change to
anything served, and the training-size handicap (§7.2) means its absolute level on the folds is
not the level it would run at. NOT CONFIRMED closes the learned challenger on these folds:
🔴 no configuration may be re-chosen or re-run on F2/F3; the revival trigger is more
independent days (forward paper days, or further folds under a new registration).

**EXPLORATION (F0+F1), run 2026-09-10 — GATE NOT PASSED; §9.5 CLOSES HERE, F2/F3 NOT READ.**
Log: `logs/learnfolds_explore_20260910.log`. Pools: F0 171,138 rows, F1 173,591 (top 10% per
fold-seed, complete observations). Every score below is out-of-fold *and* out-of-checkpoint.

**The harness check first (M3_3_PROTOCOL §6 C2's falsifiable prediction).** The
confidence-only ablation under R2 + S1 must reproduce the flat grid winner up to the
completeness filter. It does, on both folds: F0 2,011 trades at −4.68 against the flat
anchor's 2,025 at −4.07 (§9.4 stand-in (i)); F1 1,403 at +34.87 against 1,406 at +34.57. The
fold machinery scores what it says it scores.

**The fits.** λ chosen by leave-one-half-out inside the single training fold:

| held | fit on | model | λ | largest standardised terms |
|---|---|---|---|---|
| F0 | F1 (93 clusters) | A | 3.0 | conf_rank_1440 +4.53, conf_rank +4.12, rv_rank +3.75, btc_absret_rank +3.44, agree_1440 +2.50 |
| F0 | F1 | B | 3.0 | rv_rank² +3.15, btc_absret_rank² +2.88, conf_rank_1440² +2.77, conf_rank×conf_rank_1440 +2.72 |
| F1 | F0 (166 clusters) | A | 0.01 | btc_absret_rank +9.06, vol_expansion −7.07, agree_1440 +4.14, conf_rank_1440 −3.04, rv_rank −2.98 |
| F1 | F0 | B | 0.3 | btc_absret_rank² +5.15, xs_disp_rank² −4.09, rv_rank² −3.28, conf_rank×vol_expansion −2.90 |

Read by M3-3's own criterion — *a term that changes sign between folds has not been learned,
it has been fitted*: `conf_rank_1440` (+4.53 / −3.04) and `rv_rank` (+3.75 / −2.98) flip;
only `btc_absret_rank` (the ladder's observable) and `agree_1440` keep their sign. The inner
metric itself says which era each fit lives in: +49 to +59 bps inside F1, −20 to −25 inside F0.

**The contrast, pooled F0+F1, diff = learned − incumbent (+24.81 on 3,415 trades), taker 14,
day-clustered on the union of exit days:**

| configuration | n learned | net learned | diff | 95% CI | F0 diff (CI) | F1 diff (CI) |
|---|---:|---:|---:|---|---|---|
| learnA_R1_S1 | 4,242 | −6.95 | −31.76 | [−74.66, +11.14] | −9.08 [−20.77, +2.61] | −58.30 [−157.18, +40.58] |
| learnA_R1_S2 | 4,242 | −5.17 | −29.98 | [−72.82, +12.85] | −7.07 [−18.50, +4.37] | −57.36 [−156.25, +41.52] |
| learnA_R2_S1 | 4,134 | −8.37 | −33.18 | [−73.50, +7.14] | −8.59 [−18.18, +1.00] | −68.86 [−162.56, +24.85] |
| learnA_R2_S2 | 4,134 | −4.00 | −28.81 | [−69.89, +12.27] | −6.30 [−16.02, +3.42] | −62.81 [−158.20, +32.58] |
| learnB_R1_S1 | 3,534 | −4.68 | −29.49 | [−71.79, +12.81] | −9.14 [−20.28, +2.01] | −48.19 [−144.57, +48.18] |
| **learnB_R1_S2** (chosen by the rule) | 3,534 | −3.30 | **−28.11** | [−70.32, +14.10] | −6.62 [−17.81, +4.56] | −50.72 [−147.06, +45.62] |
| learnB_R2_S1 | 4,075 | −8.99 | −33.79 | [−74.13, +6.54] | −10.65 [−21.23, −0.08] | −68.34 [−161.62, +24.94] |
| learnB_R2_S2 | 4,075 | −4.37 | −29.18 | [−70.08, +11.73] | −6.36 [−17.10, +4.38] | −63.47 [−157.95, +31.02] |
| C2 ablation learnconf_R2_S1 (information) | 3,414 | +11.57 | −13.24 | [−30.19, +3.72] | −4.02 [−9.14, +1.10] | −26.33 [−65.74, +13.08] |
| C2 ablation learnconf_R1_S1 (information) | 5,089 | −12.60 | −37.41 | [−81.25, +6.43] | −11.94 [−26.91, +3.03] | 0 trades on F1 |

At the verified 11.84 line the chosen configuration's diff is −29.25 [−71.52, +13.01]; per unit
of notional −49.35 [−103.99, +5.29]. R1 under the confidence-only fit entered **no bar on F1**
(coefficient +0.36 — the score never reaches 14 bps), the same collapse of an absolute
threshold M3_3_RESULTS §F item 2 recorded.

**The choice rule** picks `learnB_R1_S2` at −28.11; **the gate requires > 0, so it is not
passed.** Its matched ablation is −36.35, so the eight extra observations are worth +8.2
bps/trade over confidence alone *here* — and both are far below the rule.

**Reading, in plain terms.** Every one of the eight learned policies loses to the hand-written
rule on both exploration folds, by 28 to 34 bps per trade pooled. The uncertainty is large
(pooled SE ≈ 21 bps, dominated by F1's +61 era, where the learned arms keep +3 to +13 of it),
so the pooled intervals do not exclude a small positive effect — **but F0 does**: on the fold
with 166 clusters the tighter intervals put the upper bound at +1.0 to +4.6 bps for every
configuration, which excludes an improvement of the §9.4 MDE's size (17.7) and of the ladder's
size (13) outright. This is the third independent look at a linear learned policy on this
observation vector — M3-3 on the published split, M3-3 repaired, and now the folds
out-of-checkpoint — and all three land on the same side. Under the negative-results discipline
that is not "not detectable": on F0 it is a detected loss.

**What closes and what would revive it.** 🔴 Closed on these folds: no configuration may be
re-chosen, and F2/F3 stay unread for this question. The one caveat worth carrying is that a
two-unit exploration fits on *one* fold (93 or 166 clusters) where the confirmation shape would
have fitted on three (~400), so the closure rests on the weaker fit — the registration accepted
that trade before the run, and reopening on it now would be the move §9.0 exists to prevent.
**Revival trigger: not more days, new observations.** The linear class on ranks of what the
dumps carry has now been tried three ways; what has not been tried is an observation vector
the dumps cannot supply — the price/funding side-table or book features over the fold era
(BOOK_ERA_PLAN, the parked book-era wave) — under a fresh registration. §9.4's fundability
reading stands as a statement about power; §9.5 is the statement about this class.
