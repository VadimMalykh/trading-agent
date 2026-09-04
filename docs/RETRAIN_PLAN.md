# The retrain plan — how fresh should the model be, and how do we find out cheaply

**Status: 🔵 PHASE 0 DONE 2026-09-04 — Phase 1 is unblocked and is the next thing to run.**
Phase 1 is already required by the candle repair, so the first real answer costs **no extra
compute**. Phases 3+ are gated on what Phase 2 reads. Indexed in [BACKLOG.md](./BACKLOG.md); the
promotion rule this plan must satisfy is [M3_PROTOCOL.md](./M3_PROTOCOL.md) §8.3–8.6.

| phase | state |
|---|---|
| **0.1** verify the repair | ✅ **PASSED 2026-09-04** — 36/36, see §3 |
| **0.2** checkpoint-binding guard | ⚪ not started — gates **Phase 4 only** (§8 Q4 answered (a)) |
| **0.3** plumb `VAL_FRACTION` | ✅ **DONE 2026-09-04** — see §3 |
| **1** re-baseline on repaired data | ✅ **DONE 2026-09-04** — 3 runs, all DONE; see §4 |
| **2** read the decay curve | 🟡 **NEXT** — no GPU |
| **3** paired freshness test | ⚪ gated on what Phase 2 reads |
| **4** what gets served, on what cadence | ⚪ gated on 0.2 and on Phase 3 |

*Holds only what is currently true and actionable. When a phase's conclusions are superseded,
move the narrative to `docs/archive/TRAINING_HISTORY.md` and carry the surviving conclusion
forward — do not append a contradicting section.*

---

## §0 — In plain language, and the bottom line

### 0.1 The jargon, defined once

* **Train / validation split.** The model is fitted on the older part of history ("train") and
  scored on the newer part it never saw ("validation", "val"). This ordering is not a style
  choice — using future data to predict the past inflates every number.
* **The train boundary.** The date the training data stops. Today: **~2025-12-10**.
* **Staleness.** How old the newest training example is. Today: **~253 days ≈ 8.3 months**.
* **bps** — a basis point, 0.01%. A round trip costs **14 bps as a taker** (crossing the spread:
  4 bps exchange fee + 3 bps assumed slippage, doubled for entry and exit) and **5 bps as a
  maker** (resting a limit order). "Gross" is before those costs, "net" after.
* **Coverage / the cut.** The policy trades only the model's most confident bars. "cov 0.02" is
  the top 2%. The **cut** is the confidence value that selects them, and it is frozen in
  `policy.ex` as `@frozen_threshold`.
* **w1..w4.** The four calendar blocks the validation window is broken into
  (`ml/train/m3/dumps.py:53`). Every M3 table reports the **worst** one, because a policy that is
  good on average and loses money in one regime is not servable.

### 0.2 The identity that frames the whole problem

The split is a **fraction** of time-ordered samples (`VAL_FRACTION = 0.2`,
`dataset.py:time_split_indices`). So:

```
train boundary = start + 0.8 x span
staleness      = today - boundary = 0.2 x span = exactly the val window's length
```

**The model's staleness and the validation window are the same number.** M3-2 reports a
252.7-day span, so the model is ~253 days stale *because* 253 days were reserved for holdout.
Every day of holdout demanded costs one day of training freshness, one for one.

Two consequences nobody chose:

1. **Staleness grows on its own**, at 0.2 days per calendar day — ~7 months when M2 froze,
   ~8.3 now, ~11 a year from now, with no decision taken anywhere.
2. **Adding older history makes it worse.** The boundary is `start + 0.8 x span`, so extending
   `start` backwards moves the boundary *earlier*. This is already recorded in
   [BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) §5 and it remains true.

### 0.3 Why val is too long — it is doing two jobs with opposite appetites

| job | wants |
|---|---|
| pick the training epoch (best is **2–5**, with val loss already rising) | a **short recent** window |
| derive the served cut and regime ladder (§8.3 **C4**) | a **short recent** window |
| M3 policy evaluation — the `worst window` discipline, M3-2 / M3-3 / T6 | a **long multi-regime** window |

One split serves all three. The long requirement wins by default, and **that is the entire reason
the model is 8 months stale.** No one traded freshness for rigour on purpose; the fraction did it.

### 0.4 The bottom line

**Can we just retrain on the latest data?** Not as a plain refit-on-everything — that deletes the
held-out data that **C4** requires the served cut be derived from, and deriving a cut in-sample
is exactly the failure [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) records (a cut that
realised 4.01% coverage against a searched 2%). The workable form is a **rolling holdout**:
shrink the holdout to what it actually needs, roll it forward, re-derive the constants each time.

**Is staleness actually costing us anything?** *Unknown, and the best evidence is contaminated.*
In M3-2's table `worst in` is **w4 in 14 of 20 configs**, including the winner
(`cov0.02_hold240_rqnone_mcnone`: w1 +8.2, w2 +16.8, w3 +6.8, **w4 −3.6** net at taker). w4 is
the newest window — months 5.7–8.7 past the train boundary — so this is the shape decay predicts.
**But w4 is also where the partial-candle defect lives** ([CANDLE_POLL_DEFECT.md](./CANDLE_POLL_DEFECT.md)),
roughly 40% of its calendar. Decay and the defect are perfectly confounded, and the repair's
re-eval separates them at no extra cost.

**So the order is: measure, then decide, then retrain.** Phase 1 is already owed to the candle
repair. Phase 2 is free. Only Phase 3 spends GPU, and only if Phase 2 earns it.

---

## §1 — What w1..w4 already is, and why it was never read this way

Train ends ~2025-12-10, so the four windows are *also* a distance-from-training axis:

| window | calendar | months past the train boundary |
|---|---|---|
| w1 | 2025-12-01 → 2026-02-01 | 0.0 – 1.7 |
| w2 | 2026-02-01 → 2026-04-01 | 1.7 – 3.7 |
| w3 | 2026-04-01 → 2026-06-01 | 3.7 – 5.7 |
| w4 | 2026-06-01 → (dump end) | 5.7 – 8.7 |

Every M3 table already prints the decay curve. It has only ever been read as a regime axis.

🔴 **The confound that Phase 3 exists to break.** w1..w4 varies *time-since-training* and *market
regime* together. A monotone decline could be either. The only clean separation is a model with a
**different train boundary scored on the same calendar rows** — which is exactly what a shorter
`--val-frac` produces, and it is why Phase 3 is a paired comparison on w4, not a new search.

---

## §2 — The plumbing gap, and the two hard blockers

**Gap (one line).** `train_m2.py` accepts `--val-frac` / `--val-offset` (args at :161–:180,
consumed at :546–:552), but `scripts/gcp_train.sh` forwards neither, and `VAL_FRACTION` is absent
from `FLUX_TRAIN_ENV_KEYS` (:176). **The split is unreachable from the launcher today.** Adding
`VAL_FRACTION` to that list is the whole enabler. Note `--val-offset 0` is *identical* to the
default trailing split, so `--val-frac` is the only real lever.

**Blocker 1 — the checkpoint-binding guard does not exist.** *(Answered 2026-09-04: §8 Q4 =
**(a) blocks Phase 4 only**. Phases 1–3 swap no checkpoint, so nothing can be mis-served.)* §8.4: swapping `m2_multi.pt`
silently invalidates the served cut and ladder and **nothing fails**. The protocol says so
itself — *"This, not the protocol, is what blocks fast iteration today."* Any retrain **cadence**
is unsafe until a mismatch refuses to serve, loudly, at boot. This is Phase 0.

**Blocker 2 — §8.6 Q3's recommended retrain trigger was the candle defect.** Q3 recommends
triggering on "the served checkpoint going N days without exceeding its own cut", noting it "is
measurable today and is exactly the condition now in force". That condition was **caused by
partial candles**. The trigger would have fired in July for the wrong reason and must be
re-specified against a repaired baseline before adoption.

---

## §3 — Phase 0: unblock (no GPU)

**0.1 Confirm the candle repair actually finished.** ✅ **PASSED 2026-09-04.** Its watcher process
was killed, so this had to be checked after the fact rather than trusted.

**The result: `36/36 checks passed`** — twelve pairs × three days at 5m, every one
`288/288 bars, exact vol=1.000 close=1.000 high=1.000 low=1.000, median vol ratio=1.000`.

🟢 **2026-08-20 is what makes this decisive.** That is the exact day §2 of
[CANDLE_POLL_DEFECT.md](./CANDLE_POLL_DEFECT.md) recorded at a **median 11% of true volume with
0/288 matching closes**. It now reports 1.000 across the board. The pre-deploy days (07-21, 08-20)
verify the **repair**; the post-deploy day (09-02) verifies the **collector fix**; they are
therefore established separately, as this step required.

Supporting checks the same day: the systemd guard's last run wrote
`{"ok": true, "summary": "24/24 checks passed"}` to `/var/tmp/candle_guard_status.json` — but note
that `--since-yesterday` only ever covers **post-deploy** days, so the guard alone could never have
closed this step. `gcp_backfill_status.sh` shows all twelve pairs complete through 2026-09-04 on
1m/5m/1h, which is coverage, not correctness — the defect was never missing rows.

The commands that were run:

```sh
./scripts/gcp_backfill_status.sh
gcloud compute ssh fluxtrader-1 --zone me-central1-b \
  --command "cat /var/tmp/candle_guard_status.json"
# authoritative: one pre-deploy day (proves the repair) and one post (proves the collector fix)
gcloud compute ssh fluxtrader-1 --zone me-central1-b --command \
  "cd ~/trading_agent && docker compose --profile ml run --rm ml_trainer \
     python verify_candles.py --intervals 5m --days 2026-07-21,2026-08-20,2026-09-02"
```
**Pass:** every pair `exact vol=1.000 close=1.000 high=1.000 low=1.000`, no `MISSING`.

**0.2 Build the checkpoint-binding guard** (Blocker 1). The served cut and ladder must be stamped
with the checkpoint identity they were derived from, and the app must refuse to boot on a
mismatch. Sized in BACKLOG; it is a precondition for Phase 4, not for Phases 1–3.

**0.3 Plumb the split** (§2's gap). ✅ **DONE 2026-09-04.** `VAL_FRACTION` is now in
`FLUX_TRAIN_ENV_KEYS` in `scripts/gcp_train.sh`, so `VAL_FRACTION=0.095 ./scripts/gcp_train.sh`
reaches the container, where `config.py:187` reads it and `train_m2.py:546` uses it as the
`--val-frac` default. Needed only from Phase 3 on; landed early because it is one line and because
a silently-ignored flag is the failure mode §6 warns about.

🔴 **Still verify the boundary from the run's own `Split ...` log line.** The plumbing being
present is not evidence the value took effect, and §6's caveat stands unchanged.

---

## §4 — Phase 1: re-baseline on repaired data (3 serial eval-only jobs)

**This is [CANDLE_POLL_DEFECT.md](./CANDLE_POLL_DEFECT.md) §7 step 5 — already decided as Q2(a).
This plan adds no compute to it, only a second question to ask of its output.**

⚠️ **Delete the dump cache first.** `ensure_dump` reuses
`/var/tmp/fluxtrader_dump_cache.sql.gz` when younger than 30 minutes; a cache written before the
repair finished would silently re-score the corrupt data and look perfectly normal.

```sh
gcloud compute ssh fluxtrader-1 --zone me-central1-b \
  --command "rm -f /var/tmp/fluxtrader_dump_cache.sql.gz"
```

⚠️ **`gcp_train.sh` runs are strictly serial — one at a time.** Run these in order, each only
after `gcp_status.sh` reports the previous DONE:

```sh
# 1 of 3 — the served seed
./scripts/gcp_train.sh --eval-only m2_multi_20260819T142759Z_a186182b.pt
./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> > logs/R1-repair-s2.log

# 2 of 3
./scripts/gcp_train.sh --eval-only m2_multi_20260818T185438Z_8c4b2a03.pt
./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> > logs/R1-repair-s1.log

# 3 of 3
./scripts/gcp_train.sh --eval-only m2_multi_20260820T025723Z_a186182b.pt
./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> > logs/R1-repair-s3.log
```

Copy the three `eval_preds_<run>.parquet` into `ml/train/output/eval_dumps/` **under new run
ids** — do not overwrite the originals, which are the record of what the corrupt tail looked like.

**Bring back:** the three logs, and from each the `Fixed-coverage P&L` table and the
`SERVED GATE (C13, coverage-targeted)` line.


### ✅ Phase 1 result, 2026-09-04 — the repair bought back real edge, on every seed

Three eval-only runs, all `finish: DONE`, val window ending **2026-09-03** so the repaired tail
is included. The dump cache was cleared first and the launcher logged `cache miss`, so a fresh
post-repair dump was built rather than the corrupt one silently re-scored.

| seed | checkpoint | new run id | new dump |
|---|---|---|---|
| s1 | `m2_multi_20260818T185438Z_8c4b2a03.pt` | `20260904T061948Z` | `eval_preds_20260904T061948Z.parquet` |
| s2 (served) | `m2_multi_20260819T142759Z_a186182b.pt` | `20260904T051921Z` | `eval_preds_20260904T051921Z.parquet` |
| s3 | `m2_multi_20260820T025723Z_a186182b.pt` | `20260904T073714Z` | `eval_preds_20260904T073714Z.parquet` |

**The paired before/after at cov 0.02** — same checkpoint, same eval code, only the candles
differ (pre-repair rows from each checkpoint's own original run log in the bucket):

| seed | gross bps pre | gross bps post | Δ | net@14 pre | net@14 post | trades pre → post | win pre → post |
|---|---:|---:|---:|---:|---:|---:|---:|
| s1 | +0.81 | +1.41 | **+0.60** | −13.19 | −12.59 | 2490 → 2527 | 0.545 → 0.546 |
| s2 | +0.99 | +3.68 | **+2.69** | −13.01 | −10.32 | 1941 → 1983 | 0.545 → 0.554 |
| s3 | +5.87 | +8.01 | **+2.14** | −8.13 | −5.99 | 1948 → 2027 | 0.563 → 0.571 |
| **median** | +0.99 | +3.68 | **+2.14** | −13.01 | −10.32 | | |

**Four things survive as findings.** (1) Gross edge improved on **every seed at every coverage**,
median **+2.14 bps/trade** at cov 0.02, sign consistent 3/3. (2) **Trade counts rose on every
seed** — exactly the direction §5's power check predicted, since the defect suppressed confidence
and so suppressed the bars clearing a fixed-coverage cut. (3) Win rate rose on every seed.
(4) The **C4 cut moved**: the served seed's re-derived cut is **0.6296** against the frozen
`0.6318973898887634` (s1 0.6095, s3 0.6137).

🔴 **What Phase 1 does NOT say.** `net@14bps` remains **negative at every coverage on every
seed** in that table — and this must **not** be read as contradicting M3-2's winner row
(`+8.2 / +16.8 / +6.8 / −3.6`). They are different statistics, and their equivalence has not
been verified: the table above is `eval_m2.py`'s **whole-val pooled** fixed-coverage P&L with one
serial position per pair, whereas M3-2's row comes from `m3 policy`, which splits w1..w4 and ranks
across pairs. **This table has no window axis, so it cannot answer the decay question at all.**
That is Phase 2's job, and until it runs the M3-comparable numbers do not exist.

Working extract with the full tables: `logs/R1-repair-EXTRACT.md` (gitignored).

---

## §5 — Phase 2: read the decay curve (no GPU, laptop pandas)

```sh
./scripts/m3.sh -m m3 validate                 # C3 — must pass FIRST, or nothing below is a comparison
./scripts/m3.sh -m m3 policy --label winner    # per-window net bps for the incumbent policy
./scripts/m3.sh -m m3 fidelity --universe 8    # arm A -> the re-derived cut and ladder (C4)
```

Then compare the repaired `w1 w2 w3 w4` row against the published one (M3-2 §B, winner row:
`+8.2 / +16.8 / +6.8 / -3.6`), per seed and pooled.

### The pre-registered reading, written before the numbers are seen

| what the repaired w1..w4 shows | conclusion | next |
|---|---|---|
| w4 recovers to w1–w3's level | w4's weakness **was the defect**. No decay evidence. | **Stop. Do not run Phase 3.** Freshness is not the binding problem; record it and close the question with a tombstone. |
| w4 still worst, and the decline is monotone across w1→w4 | decay is **plausible**, still confounded with regime | Run Phase 3 — it is the only design that separates them. |
| w4 still worst but the curve is non-monotone (e.g. w3 also bad) | regime, not distance | Phase 3 **optional**, low priority. |

🔴 **Do not read a single seed.** At a 259-bps per-trade spread the between-seed spread swamps
this effect; use the family median and quote the clustered interval, per P5 and §8.3's
median-of-family rule.

⚠️ **Power check before letting this decide anything.** w4's trade count after repair will *rise*
(the defect suppressed confidence, hence trades, in exactly that window). Report `n_trades` on
every window row. If w4's clustered interval spans the other windows' means, the honest verdict
is `NOT DECIDABLE`, not "no decay" — a decision criterion must be shown to have the power to
decide before it is allowed to.

---

## §6 — Phase 3: the paired freshness test (3 serial training runs, GPU)

**Only if Phase 2 says decay is plausible.** One recipe, one changed dimension, three seeds.

**Design.** Train the incumbent recipe with a **shorter holdout**, which moves the train boundary
forward, then score both families **on the same calendar rows**. Stale-model-on-w4 versus
fresh-model-on-w4 is a paired comparison in which regime is held fixed and only distance-from-
training moves. That is the confound broken.

**The setting.** `val_frac 0.2` buys ~253 days, so ~12.6 days per 0.01. For a **~120-day**
holdout use **`VAL_FRACTION=0.095`**, which puts the boundary near **2026-05**, i.e. ~4.5 months
fresher. 120 days is the smallest holdout that still spans two calendar windows.

🔴 **Verify the boundary from the run's own log, never from this arithmetic.** `train_m2.py:556`
prints
`Split global_time | val_frac=... | train [... → ...] | val [... → ...]`.
Read it and record it. Sample density is not uniform in time (pairs were added over the years),
so the fraction→days map is approximate.

```sh
# serial, one at a time, each after the previous reports DONE
VAL_FRACTION=0.095 SEED=1 ./scripts/gcp_train.sh
./scripts/gcp_status.sh && ./scripts/gcp_logs.sh <run_id> > logs/R3-fresh120-s1.log
VAL_FRACTION=0.095 SEED=2 ./scripts/gcp_train.sh
./scripts/gcp_status.sh && ./scripts/gcp_logs.sh <run_id> > logs/R3-fresh120-s2.log
VAL_FRACTION=0.095 SEED=3 ./scripts/gcp_train.sh
./scripts/gcp_status.sh && ./scripts/gcp_logs.sh <run_id> > logs/R3-fresh120-s3.log
```

(Requires Phase 0.3. Without it `VAL_FRACTION` is silently ignored — which the log line above
will expose, so check it rather than trusting the flag.)

**Bring back:** the three `Split ...` lines, the three `Fixed-coverage P&L` tables, and the
w4-restricted net-at-taker figure for each family.

### Pre-registered gate, before the numbers

The fresh family is evidence that freshness matters **only if** its w4 net-at-taker beats the
stale family's w4 by a margin **exceeding the between-seed spread** (§8.6 Q2 option (b)),
evaluated on family medians over the shared w4 rows with a day-clustered interval.

⚠️ **Two honest caveats to state in the write-up, not to discover later.** (a) The fresh family
differs in *two* ways — a later boundary **and** ~5 more months of training data — and this design
cannot separate them. Both point the same way and both are part of what "retrain on newer data"
means, so this is a caveat on the mechanism, not on the decision. (b) A 120-day split yields
~282 cov-2% trades per seed, degrading §2's ±37 bps resolution to roughly **±54 bps**. It can
select an epoch and derive a cut; it **cannot** run Tier 1.

---

## §7 — Phase 4: what actually gets served, and on what cadence

**Gated on Phase 0.2 (the binding guard) and on Phase 3 passing its gate.**

🔴 **The structural problem Phase 3 will expose, stated now.** §8.3 **C1** requires a challenger
pass all six Tier-1 criteria **on its own split**, and **C2** requires it beat the incumbent on
**worst-window** net at taker. A fresh-boundary challenger has a short split with two windows and
±54 bps resolution, so **it cannot satisfy C1/C2 as written.** §8.5 explicitly refuses to lower
Tier 1. This is a genuine conflict between the promotion rule and freshness, and it needs a
decision (§8, Q2) rather than a workaround.

The two coherent resolutions:

* **(A) Certify the recipe, refresh the checkpoint.** Tier 1 certifies a *recipe* on the long
  split; the served checkpoint is that recipe refitted to a later boundary, with its cut and
  ladder re-derived from its own trailing holdout under C4. Cheap and honest, but the served
  artefact is never itself Tier-1 certified — that must be written into the promotion record.
* **(B) Walk-forward certification.** Score the recipe across k rolling folds
  (`--val-offset` stepped by `--val-frac`, already implemented at `dataset.py:656`), giving long
  effective coverage with fresh boundaries throughout. Statistically the right answer; costs
  k serial training runs per recipe per seed.

**Cadence (§8.6 Q3, re-answered).** Q3's recommended staleness trigger is void — it was the
candle defect. Until a *repaired* baseline exists there is no calibrated trigger, so the interim
answer is **(a) a fixed cadence**, chosen to bound the identity in §0.2 rather than to react to a
signal: retrain when staleness exceeds a stated ceiling. A **quarterly** cadence holds staleness
under ~1 year given a 120-day holdout. Revisit once §5's power check says a trigger can be
calibrated.

---

## §8 — The decisions, each as its own question

**Q1. Do we shorten the holdout at all — accepting that it weakens every M3 per-window table —
or keep the 253-day split and accept ~8.3 months of staleness, growing?**
(a) shorten to ~120 days for challengers, keep the long split for policy work on the incumbent
*(recommended — it is the only option that treats freshness as a chosen quantity)*;
(b) keep 0.2 and accept growing staleness;
(c) decide after Phase 2. **Note: (c) is free.** Phase 2 costs nothing beyond work already owed
to the candle repair, so deferring this question has no price and is the default if unanswered.

**Q2. If a fresh-boundary model cannot satisfy C1/C2 (§7), which resolution?**
(a) **(A) certify the recipe, refresh the checkpoint** *(recommended: affordable, and honest so
long as the promotion record says the served artefact inherits its certification)*;
(b) **(B) walk-forward certification** — right, but k× the compute, serial;
(c) leave C1/C2 as they are and never serve a fresh-boundary model.

**Q3. Retrain on a cadence or on a trigger?**
(a) **fixed cadence, quarterly** *(recommended for now — §8.6 Q3's trigger was the candle defect
and no calibrated trigger exists until Phase 2's power check)*;
(b) trigger, re-specified against the repaired baseline;
(c) both — cadence as a floor, trigger as an interrupt. **(c) is the likely end state**, but it
needs (b) to be calibratable first.

**Q4. Does Phase 0.2 (the checkpoint-binding guard) block Phases 1–3, or only Phase 4?**
✅ **ANSWERED 2026-09-04: (a) only Phase 4.** Phases 1–3 produce no swap, so nothing can be
mis-served; the guard remains a hard precondition for Phase 4 and for M3_PROTOCOL §8.3 **C5**.
*(b) block everything until the guard exists — rejected.*

---

## §9 — What this plan deliberately does not do

* It does **not** propose adding older history. §0.2 shows that moves the boundary the wrong way.
* It does **not** propose a short-window model. That is **B3**, it is LightGBM not an LSTM, and
  [BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) §5's clarification stands: short-window training is a way
  to get book features into a model, not a way to get a **servable** one.
* It does **not** re-open any searched dimension. Phase 3 changes `val_frac` only, and the
  comparison is scored under §8.3 unchanged.
* It does **not** assume decay exists. Phase 2 is allowed to close the question, and §5's table
  says in advance what reading ends it.
