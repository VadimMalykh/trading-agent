# The retrain plan — how fresh should the model be, and how do we find out cheaply

**Status: 🔴 PHASE 2 DONE 2026-09-04 — the decay question is `NOT DECIDABLE`, and Phase 3 as
written cannot decide it either.** The w1..w4 axis does not have the power to rank its own
windows: w4's 95% interval contains all three other windows' means on every policy, in every
era, at every scope. Phase 3's gate, priced against that same precision, could only resolve a
freshness effect **~7–12× larger than the model's entire edge**, so three GPU runs would buy
another `NOT DECIDABLE`. **Do not run Phase 3 in its current form.**

🟢 **§8 was answered 2026-09-04 (all five questions — see §8).** The decisions: re-score the
incumbent against Tier 1 on repaired data **first** (Q0 a); **buy precision before touching the
split** (Q1 d); and certify by **walk-forward folds** rather than by refreshing an uncertified
checkpoint (Q2 B). Q1 and Q2 converge on one piece of work — folds bought for precision are the
same folds that certify a fresh checkpoint — and `VAL_OFFSET` was plumbed the same day to make
it launchable (§3, 0.3). Indexed in [BACKLOG.md](./BACKLOG.md); the promotion rule this plan must satisfy is
[M3_PROTOCOL.md](./M3_PROTOCOL.md) §8.3–8.6.

| phase | state |
|---|---|
| **0.1** verify the repair | ✅ **PASSED 2026-09-04** — 36/36, see §3 |
| **0.2** checkpoint-binding guard | ✅ **BUILT 2026-09-04** — `ml_inference` reports `checkpoint_sha256`, `Policy.frozen_checkpoint_sha256/0` names the bound checkpoint, `PolicyEngine` skips every bar on a mismatch (M3_PROTOCOL §9.5). Deploy pending |
| **0.3** plumb `VAL_FRACTION`, `VAL_OFFSET` | ✅ **DONE 2026-09-04** — both; walk-forward is now launchable, see §3 |
| **1** re-baseline on repaired data | ✅ **DONE 2026-09-04** — 3 runs, all DONE; see §4. 🔴 **its headline was read off the wrong horizon and does not survive §5's controls** |
| **2** read the decay curve | ✅ **DONE 2026-09-04** — verdict `NOT DECIDABLE`; see §5 |
| **3** paired freshness test | 🔴 **BLOCKED — underpowered by construction**, see §5.4. Needs a redesign, not a launch |
| **4** what gets served, on what cadence | 🔵 **decided 2026-09-04**: walk-forward certification ([WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md)), a 65-day staleness trigger (§8 Q3 (b)), promote-on-backtest / keep-on-forward (M3_PROTOCOL §9.1). The served constants are re-derived on repaired data (§8 Q0) and await deploy |

*Holds only what is currently true and actionable. When a phase's conclusions are superseded,
move the narrative to `docs/archive/TRAINING_HISTORY.md` and carry the surviving conclusion
forward — do not append a contradicting section.*

### The order of work, as the §8 answers leave it

1. **Q0 — re-score the incumbent against Tier 1 on repaired data.** No GPU, eval-only, and every
   other item assumes its answer. Commands and the pre-registered reading: §8 Q0.
2. **Phase 0.2 — the checkpoint-binding guard.** The plan's single most valuable open item
   (§7): the served rule and the validated rule now differ by the entire edge, and the guard is
   what makes that fail loudly instead of silently. Gates Phase 4 and M3_PROTOCOL §8.3 **C5**.
3. **Settle the walk-forward fold shape** — anchored versus rolling fixed-width train window
   (§7 B). A design decision, no runs, and it must precede them.
4. **Then the folds themselves** (Q1 d + Q2 B, one investment). k serial training runs per
   recipe per seed; `VAL_OFFSET` is plumbed as of 2026-09-04, so they are launchable.

*Not on this list, deliberately:* Phase 3 as written (§6, underpowered by ~10×), and any redesign
that reads a per-window mean of this population (§5.6's tombstone).

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

**Is staleness actually costing us anything?** 🔵 **Asked and answered as UNMEASURABLE on this
data, 2026-09-04 (§5).** The evidence this plan was built on is M3-2's table, where `worst in`
is **w4 in 14 of 20 configs**, including the grid winner (`cov0.02_hold240_rqnone_mcnone`: w1
+8.2, w2 +16.8, w3 +6.8, **w4 −3.6** net at taker) — the shape decay predicts, in the newest
window. Phase 2 removed the candle defect from that picture and the shape survives (repaired:
+18.6 / +15.2 / +5.5 / **−1.9**), **but it cannot be distinguished from noise**: w4's 95%
interval contains the means of all three other windows. Three seeds over one market give ~35–52
day-clusters per window and ±50–100 bps intervals on a ~15 bps edge. The answer is not "no
decay" and not "decay" — it is that **this population cannot tell**, and no reshuffling of the
split changes that (§5.4).

**So the order was: measure, then decide, then retrain — and the measurement came back empty.**
What Phase 2 found instead is nearer home: on repaired data the **incumbent's worst window is
below its own promotion bar**, its **regime ladder has flattened by half**, and the **rule
actually in production scores at zero** (§5.5). Those three, plus the checkpoint-binding guard
(0.2), are the live work. Freshness is ranked fourth — because it is unmeasurable here, not
because it is fine.

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

🔴 **The confound Phase 3 was designed to break — and the one that turned out to bind.** w1..w4
varies *time-since-training* and *market regime* together, and a monotone decline could be
either. The clean separation is a model with a **different train boundary scored on the same
calendar rows**, which is what a shorter `--val-frac` produces; that is still the right shape.
But §5.3 shows the prior question was never the confound, it was **precision**: the per-window
means cannot be ranked against each other at all, so breaking their confound resolves nothing.
Any revival of this axis has to buy clusters first (§6's redesign note).

---

## §2 — The plumbing gap, and the two hard blockers

**Gap — ✅ CLOSED 2026-09-04, both halves.** `train_m2.py` accepts `--val-frac` /
`--val-offset`, but neither was reachable from `scripts/gcp_train.sh`. Both are now env-plumbed
the same way every other knob is:

* `VAL_FRACTION` — `config.py:187` → `train_m2.py:546`, forwarded at `gcp_train.sh:180`.
* `VAL_OFFSET` — `config.py:188` → `train_m2.py:548`, forwarded at `gcp_train.sh:180`.
  `--val-offset`'s argparse default moved `0.0 → None` so the env var is actually reachable; a
  hard-coded default would have silently outranked it. The resolved value now prints in the
  `Split ...` line and is written to `meta["val_offset"]`, so a checkpoint records the fold it
  was trained on. Out-of-range offsets **exit** rather than clamp (`train_m2.py:549`) — the
  window helper clamps silently, which is the failure mode `config.py:180` and `gcp_train.sh:157`
  each record having voided an experiment.

`VAL_OFFSET=0.0` reproduces the trailing split bar for bar, so the default is a genuine no-op and
nothing published changes. **This is what unblocks §7 option B**, the walk-forward now chosen at
§8 Q2.

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


### Phase 1 result, 2026-09-04, **as corrected by Phase 2**

Three eval-only runs, all `finish: DONE`, val window ending **2026-09-03** so the repaired tail
is included. The dump cache was cleared first and the launcher logged `cache miss`, so a fresh
post-repair dump was built rather than the corrupt one silently re-scored.

| seed | checkpoint | new run id | new dump |
|---|---|---|---|
| s1 | `m2_multi_20260818T185438Z_8c4b2a03.pt` | `20260904T061948Z` | `eval_preds_20260904T061948Z.parquet` |
| s2 (served) | `m2_multi_20260819T142759Z_a186182b.pt` | `20260904T051921Z` | `eval_preds_20260904T051921Z.parquet` |
| s3 | `m2_multi_20260820T025723Z_a186182b.pt` | `20260904T073714Z` | `eval_preds_20260904T073714Z.parquet` |

🔴 **RETRACTED: "the repair bought back real edge, on every seed" (commit `3308651`).** That
headline, and the `median +2.14 bps` it rested on, were read off the eval log's **Horizon 60m**
block. **M3's primary head is 240m** — it is what the served gate is derived on
(`SERVED GATE (C13, coverage-targeted): ... on the primary 240m head`) and what every M3 policy
sets `signal_horizon=240` to. `eval_m2.py` prints a `Fixed-coverage P&L` table for each of
60m/240m/1440m and the wrong one was transcribed. On the primary head the same paired cells are:

| seed | gross bps pre | gross bps post | Δ | net@14 pre | net@14 post |
|---|---:|---:|---:|---:|---:|
| s1 | +22.11 | +20.89 | **−1.22** | +8.11 | +6.89 |
| s2 (served) | +16.83 | +20.00 | **+3.17** | +2.83 | +6.00 |
| s3 | +26.23 | +22.72 | **−3.51** | +12.23 | +8.72 |
| **median** | +22.11 | +20.89 | **−1.22** | +8.11 | +6.89 |

**The sign is not consistent — it is 1 up, 2 down.** And even that table is uncontrolled: §5.1
shows the two eras are not the same calendar rows, so it also contains a moved validation
window. Under §5's controls the repair's effect on the primary head is **not measurable in
either direction**.

**Three things do survive, and they matter.**

1. **The 240m head is net-positive at taker on all three repaired seeds** at cov 0.02
   (+6.89 / +6.00 / +8.72). §4's original red note — *"net@14bps remains negative at every
   coverage on every seed"* — was likewise a 60m artifact and is withdrawn. The caution it was
   attached to still stands for a different reason: this is `eval_m2.py`'s whole-val pooled
   table, not `m3 policy`'s windowed one, and §5 is where the M3-comparable numbers live.
2. **The C4 cut moved.** The served seed's re-derived cut is **0.6296** against the frozen
   `0.6318973898887634` in `policy.ex` (s1 0.6095, s3 0.6137). Unchanged by the correction —
   the cut is derived on the 240m head in both eras.
3. **The harness reproduces the trainer on the repaired dumps, digit-exact, 15/15 cells**
   (§5.2). That is what makes §5 a comparison rather than a claim.

Working extract with the full tables: `logs/R1-repair-EXTRACT.md` (gitignored). The three run
logs are `logs/R1-repair-s{1,2,3}.log`; the 240m blocks are the ones to read.

---

## §5 — Phase 2: read the decay curve — ✅ **DONE 2026-09-04, verdict `NOT DECIDABLE`**

```sh
./scripts/m3.sh -m m3 validate                            # C3, prerepair — still PASS/PASS
M3_ERA=repaired ./scripts/m3.sh -m m3 validate            # C3 on the new dumps
./scripts/m3.sh -m m3 decay                               # the w1..w4 reading, both eras
M3_ERA=repaired ./scripts/m3.sh -m m3 fidelity --universe 8   # arm A -> the re-derived cut (C4)
```

Logs: `logs/P2-decay.log`, `logs/P2-validate-repaired.log`,
`logs/P2-fidelity-{prerepair,repaired}.log` (gitignored).

### 5.1 The confound §5 did not anticipate, found before any number was read

**The two eras are not the same calendar rows.** The split is a fraction of a *growing*
history, so re-dumping two weeks later moved **both** edges of the validation window:

| | val starts | val ends | w1 bars | w4 bars |
|---|---|---|---:|---:|
| pre-repair | 2025-12-09/10 | 2026-08-17/19 | 121–123k | 179–182k |
| repaired | 2025-12-22 | 2026-09-03 | 93k | 217k |

w2 and w3 are **bar-for-bar identical** (135,936 / 140,544 in both). w1 and w4 — the two windows
the entire decay question is about — are not: w1 lost its first twelve days, w4 gained sixteen.
A raw before/after on w4 therefore mixes *(repaired candles) + (sixteen days of newer market) +
(whatever decay there is)*, three changes at once.

So every table is reported twice: over each era's own full window, and clipped to
`dumps.REPAIR_OVERLAP` (2025-12-22 → 2026-08-17), the span both eras cover. **Only the clipped
one is a before/after.** This is the identity in §0.2 biting a second time — the same mechanism
that makes the model stale also makes two dumps of it non-comparable.

### 5.2 C3 — the harness reproduces the trainer on *both* datasets

`m3 validate` is now era-aware (`M3_ERA=prerepair|repaired`, default `prerepair`), because a
reproduction test compared against constants from a *different* dataset is not a test.

* **prerepair: TEST 1 PASS, TEST 2 PASS** — unchanged, every published M3 number still reproduces.
* **repaired: TEST 1 PASS, 15/15 cells digit-exact** against the trainer's own 240m tables in
  `logs/R1-repair-s{1,2,3}.log`. C3 is satisfied on the population §5 reads.

TEST 2 (the §1.8 regime ladder) is **informational** in the repaired era — same code, different
candles, different span — and what it shows is a **finding, not drift**:

| quintile | published bps | repaired bps | published dir_acc | repaired dir_acc |
|---|---:|---:|---:|---:|
| Q1 | −3.4 | +1.8 | 0.517 | 0.525 |
| Q2 | −15.3 | +1.9 | 0.494 | 0.554 |
| Q3 | +10.1 | +13.8 | 0.545 | 0.556 |
| Q4 | +17.4 | +19.0 | 0.579 | 0.588 |
| **Q5** | **+35.5** | **+17.4** | 0.618 | 0.589 |

🔴 **The ladder has flattened by more than half at the top.** Q5 per seed goes
`[+34.8, +32.5, +38.7]` → `[+12.3, +8.3, +32.3]`. The incumbent policy is
`size_by_regime=True` on exactly this ladder, so this is its edge mechanism weakening — and it
is a *bigger* effect than anything the decay reading below can resolve.

### 5.3 The decay curve — `NOT DECIDABLE`, on every policy, era and scope

Read on **two** policies, because §0.4 and `WINNER_SPEC` are not the same rule and only one of
them has the negative w4 the decay question was raised about:

* **`cov0.02_hold240_rqnone_mcnone`** — M3-2's primary-grid winner, the `+8.2/+16.8/+6.8/−3.6`
  row §0.4 quotes.
* **`..._SIZED`** — the same policy with the regime sizing overlay, which is what `m3 fidelity`
  replays and what M3-3's bar was set against.

Net bps/trade at taker, **restricted to the shared span** (the honest before/after):

| policy | era | w1 | w2 | w3 | w4 | worst |
|---|---|---:|---:|---:|---:|---|
| grid winner | pre-repair | +21.6 | +16.8 | +6.8 | **−3.6** | w4 |
| grid winner | repaired | +18.6 | +15.2 | +5.5 | **−1.9** | w4 |
| SIZED | pre-repair | +29.5 | +19.2 | **+0.3** | +15.1 | w3 |
| SIZED | repaired | +24.6 | +17.7 | **−4.6** | +19.3 | w3 |

Per-window deltas (repaired − pre-repair) are **−4.9 / −1.6 / −4.9 / +4.2 bps** — every one of
them well inside its interval, and **every pair of CIs overlaps**. Pooled, the repair moved the
grid winner by −0.8 bps and the incumbent by −0.5 bps. **On the primary head, over the same
calendar, the repair did not measurably change the P&L in either direction.**

⚠️ **The power check vetoes the whole reading, exactly as §5 said it must.** w4's day-clustered
95% interval is `[−57.3, +53.5]` (grid winner) and `[−43.2, +81.9]` (SIZED) — each contains the
means of **all three** other windows. No ordering of w1..w4 is resolvable at this sample size,
so the honest verdict is `NOT DECIDABLE`, not "no decay". This holds on the full window too.

For the record, had it been decidable: the grid winner's repaired sequence
`+18.6 / +15.2 / +5.5 / −1.9` is monotone and w4 is still worst — §5's row 2, "decay plausible".
That reading is **not available**, and is recorded only so nobody re-derives it later and treats
it as a result.

**What the defect actually did**, now that it can be seen: it did not degrade w4 evenly, it
**deleted the end of the dump**. In the pre-repair era, across 2026-08-01..17, **zero** bars in
any of the three seeds cleared the top-2% cut (s1 0, s2 0, s3 0 of ~40k bars each) against
1,139 / 478 / 277 in the repaired era's full August. The last pre-repair entry is
**2026-07-16**, a month before its own dump ends. Inside the shared span that stretch is worth
only **7 trades**, which is why the before/after deltas above are so small — the defect's P&L
footprint sits mostly *outside* the span the two eras share.

### 5.4 🔴 Phase 3 cannot decide this either — the design is underpowered by ~10×

§5's rule is that a criterion must be shown to have the power to decide **before** it decides.
Applying that same rule to Phase 3's own gate (§6: the fresh family's w4 must beat the stale
family's w4) — the arithmetic is in `m3/decay.py:phase3_power` and prints with the reading:

| | grid winner | SIZED incumbent |
|---|---:|---:|
| stale w4 day-clustered SE | 28.3 bps | 31.9 bps |
| fresh family SE (§6's own ±54 bps, a **lower** bound) | ≥27.6 bps | ≥27.6 bps |
| SE of the difference | ≥39.5 bps | ≥42.2 bps |
| **smallest resolvable freshness effect** (95%, 80% power) | **~111 bps/trade** | **~118 bps/trade** |
| the policy's entire pooled edge | +9.0 bps | +16.6 bps |

**Phase 3 as written could only detect a freshness effect 7–12× larger than the model's whole
edge.** Three serial GPU runs would return `NOT DECIDABLE` whatever the truth is. §6 is
therefore **blocked pending redesign**, not scheduled.

### 5.5 C4 — the served rule, re-derived on repaired data

`m3 fidelity --universe 8`, arm A is the validated fixed-cut policy, arm D is what actually
runs in production. Net bps/trade at taker, whole val window:

| arm | pre-repair | repaired | worst window (repaired) |
|---|---:|---:|---|
| A fixed cut + fixed ladder (validated) | +15.03 | **+13.82** | w3 −4.61 |
| B rolling cut + fixed ladder | +9.60 | +0.50 | w4 −10.25 |
| C fixed cut + rolling ladder | +13.54 | +12.67 | w3 −3.18 |
| **D rolling cut + rolling ladder (SERVED)** | **+8.62** | **−0.29** | w4 −9.54 |

🔴 **Two things here are decision-grade, and neither is a decay question.**

1. **The served rule (arm D) scores −0.29 bps at taker on repaired data**, down from +8.62.
   Its clustered CI is `[−29.0, +28.4]`, so this is *also* not a measured decline — but the
   point estimate of the thing that is running in production is now **at zero, before slippage
   surprises**, and its worst window is −9.5 bps. Arm A, the *validated* rule, is at +13.82:
   the gap between what was certified and what is served is now the entire edge.
2. **Arm A's worst window is −4.61 bps**, against the **+0.25 bps** that M3_2_RESULTS §D fixed
   as M3-3's promotion bar. On repaired data **the incumbent no longer clears its own bar.**
   This is not something Phase 2 was asked to test and it is not certified here — re-running
   Tier 1 against the repaired dumps is the check, and it is filed as **§8 Q0** below.

Arm D also drifts further from arm A after the repair: 61% of its trades are on bars the fixed
cut rejects (was 56%), and its top pair changes (HYPEUSDT → ZECUSDT).

### 5.6 What Phase 2 closed, and what it opened

**Closed.** The w1..w4 axis is **not** a decay detector at this sample size — three seeds over
one market give ~35–52 day-clusters per window and ±50–100 bps intervals on a ~15 bps edge.
Do not re-open the decay question with any design that reads a per-window mean of this
population; that is the tombstone, and §5.4 is the arithmetic behind it.

**Opened, and ranked.**

1. **The incumbent's worst window is below its own promotion bar on repaired data** (§5.5).
   Outranks freshness: it is about what is servable *today*, needs no GPU, and is a Tier-1
   re-score of an existing checkpoint.
2. **The regime ladder flattened by half at Q5** (§5.2). The incumbent's sizing overlay is
   built on it. Also no GPU.
3. **The served rule scores at zero** (§5.5) — a Phase 4 question, and one more reason the
   checkpoint-binding guard (0.2, M3_PROTOCOL §8.4) is the real blocker: it is what would make
   a served-vs-validated divergence this large fail loudly instead of silently.

Freshness is now **fourth**, and it is fourth because it cannot be measured on this population,
not because it was answered.

## §6 — Phase 3: the paired freshness test — 🔴 **BLOCKED, needs a redesign before it is run**

**Phase 2 ran and its gate did not open.** §5.3's verdict is `NOT DECIDABLE`, and §5.4 prices
this section's own gate at a **~111–118 bps/trade** minimum detectable effect against a ~9–17
bps edge. The design below is kept because it is the right *shape* — a paired comparison on the
same calendar rows is still the only thing that breaks the regime confound — but **running it
as written buys nothing.** Do not launch it.

**What a redesign has to fix, in order.** Precision, not the split. The binding constraint is
~35–52 day-clusters per window; a shorter holdout makes that *worse*, not better. Anything that
un-blocks this has to add clusters — more seeds, more pairs (the 12-pair universe is already
banked, see `traded-universe`), a walk-forward that accumulates folds (§7 option B), or a
statistic that is not a per-window mean of overlapping 4h trades.

🟢 **§8 Q1 chose exactly that (option d), and Q2 chose the walk-forward (option B).** So this
section's redesign is no longer hypothetical: the folds being bought for precision are the same
folds §7 B certifies on, and `VAL_OFFSET` is now plumbed to launch them (§2). Freshness stays
ranked fourth *as a question* (§5.6) — what changed is that the instrument which would make it
answerable is now being built for an independent reason.

<details>
<summary>The original design, retained for whoever redesigns it</summary>

One recipe, one changed dimension, three seeds.

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

🔴 **Caveat (b) is what killed this design.** It was written down as a limitation on Tier 1 and
never carried through to the gate three paragraphs above it — §5.4 does that arithmetic and the
gate does not survive it. The lesson is filed in §5.6: price a criterion's power in the same
document that pre-registers it, not in the phase that consumes it.

</details>

---

## §7 — Phase 4: what actually gets served, and on what cadence

**Gated on Phase 0.2 (the binding guard) alone.** It was also gated on Phase 3, but Phase 3
cannot report (§5.4), so that gate is removed rather than left to block indefinitely. 🔵 **Phase
2 promoted 0.2 from "a precondition for Phase 4" to the plan's single most valuable open item**:
§5.5 shows the served rule (arm D) and the validated rule (arm A) now differ by the entire edge
(−0.29 vs +13.82 bps at taker), and the guard is what makes that divergence *fail loudly*
instead of silently.

🔴 **The structural problem Phase 3 was going to expose. It is now reached by arithmetic instead
of by experiment (§5.4), and it is worse than stated: the ±54 bps resolution does not merely
fail C1/C2, it fails to resolve the challenger's own w4 at all.** §8.3 **C1** requires a challenger
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
* **(B) Walk-forward certification.** ✅ **CHOSEN, §8 Q2, 2026-09-04.** Score the recipe across
  k rolling folds (`VAL_OFFSET` stepped by `VAL_FRACTION`, split helper at
  `ml/train/data/dataset.py:656`, launcher plumbing closed in §2), giving long effective
  coverage with fresh boundaries throughout. Statistically the right answer, and the only option
  under which the **served artefact is itself certified**. Costs k serial training runs per
  recipe per seed — and runs are strictly serial on the GCP box, so k is a wall-clock decision,
  not a budget one. Read a real training log for the per-run duration before fixing k.

  ✅ **Settled 2026-09-04: rolling fixed-width**, `TRAIN_FRACTION=0.5`, plumbed the same day
  (`config.py`, `train_m2.py --train-frac`, `gcp_train.sh`), and pre-registered as
  [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) — four folds × three seeds, the run queue
  in its §5. *The original question follows for the record.* 🔴 **Open design question before k folds are burned: the fold shape.** The implemented split is
  **anchored** — train always starts at the beginning of history — so older folds train on
  progressively less data (at `val_frac=0.2`, the fourth-oldest fold sees a quarter of the
  samples). A score across folds therefore mixes *boundary age* with *training-set size*, which
  are the same two effects §6's caveat (a) already says this family cannot separate. Either
  state it as a known confound in the protocol, or switch to a **rolling fixed-width** train
  window so every fold trains on the same number of samples. This must be decided before the
  runs, not after.

**Cadence (§8.6 Q3, re-answered, and Phase 2 settles it for now).** Q3's recommended staleness
trigger was void — it was the candle defect. A repaired baseline now exists, and §5.6 says this
population **still cannot calibrate a trigger**: it cannot resolve a per-window change of the
size a trigger would need to fire on. So the answer stays **(a) a fixed cadence**, chosen to
bound the identity in §0.2 rather than to react to a signal: retrain when staleness exceeds a
stated ceiling. A **quarterly** cadence holds staleness under ~1 year given a 120-day holdout.
Revisit only if a design that adds clusters (§6's redesign note) makes a trigger calibratable.

---

## §8 — The decisions, each as its own question

✅ **All five answered 2026-09-04.** Q0 (a), Q1 (d), Q2 (B), Q3 (a), Q4 (a). The answers are
recorded inline below, each next to the options it was chosen against, so the rejected options
stay visible and nobody re-derives them.

**Q0 — ✅ ANSWERED: (a), and ✅ RUN 2026-09-04.** `validate` PASS/PASS, eligibility unchanged at
16/36, and **the incumbent `cov0.02_hold240_rqnone_mcnone_SIZED` passes all six Tier-1 criteria on
repaired data**: worst window **−4.61 bps** (w3, 196 trades) against the −5 floor, pooled **+13.82**
net at taker, seeds +8.41 / +11.94 / +21.97, clustered CI [−34.9, +62.6]. Per the pre-registered
reading below it passes P3 but lands below +0.25, so **M3-3's bar is restated at −4.61**; the
learned runs were re-executed too and 0 of 8 pass (best −6.6). Records:
[M3_2_RESULTS_REPAIRED.md](./M3_2_RESULTS_REPAIRED.md), [M3_3_RESULTS_REPAIRED.md](./M3_3_RESULTS_REPAIRED.md);
logs `logs/Q0-repaired-all.log`, `logs/Q0-learn-repaired.log`. Whether this becomes the verdict of
record, and the C4 re-derivation of `policy.ex`'s constants that follows, is
[RULES_REVIEW.md](./RULES_REVIEW.md) §4 decision 3. *Original question follows.* **Does the incumbent still clear its own promotion bar
on repaired data?** §5.5 shows arm A's worst window at **−4.61 bps** against the **+0.25 bps**
M3_2_RESULTS §D fixed as M3-3's bar, and §5.2 shows the regime ladder its sizing overlay rests
on has flattened by half at Q5. Neither is certified — a Tier-1 re-score of the incumbent
against the repaired dumps is the check, it needs **no GPU**, and it decides whether anything
downstream is worth doing.
(a) ✅ **CHOSEN: re-score the incumbent against Tier 1 on the repaired dumps, before any other
phase.** It is cheap, it needs no GPU, it is about what is servable *today*, and every other
question in this document assumes an answer to it.
(b) treat §5.5 as noise on the strength of its interval `[−34.9, +62.6]` and carry on — rejected:
the interval argues the decline is unproven, not that the baseline is sound, and continuing to
rank challengers against an unverified champion is the failure it would hide.
(c) skip to Phase 0.2, on the grounds that nothing can be swapped safely anyway — rejected: 0.2
is the more valuable item (§7) but it does not answer whether today's rule is servable.

**What to run, and what to bring back.** The dumps and the harness both exist; this is eval-only.

```sh
M3_ERA=repaired ./scripts/m3.sh -m m3 validate   # C3 first — a re-score by an unvalidated
                                                 # harness is not a comparison (§8.3 C3)
M3_ERA=repaired ./scripts/m3.sh -m m3 search     # the 40 pre-registered configurations,
                                                 # scored against Tier 1 (M3_PROTOCOL §4.2)
```

Logs to `logs/Q0-validate-repaired.log` and `logs/Q0-search-repaired.log`. **Bring back:** the
Tier-1 pass/fail table (the `n / 36` line), the incumbent
`cov0.02_hold240_rqnone_mcnone_SIZED`'s six criteria individually, and its per-window net at
taker with the day-clustered interval. **The reading is pre-registered here, before the numbers:**
if the incumbent fails **P3** (worst window < −5 bps) it is not servable and Phase 4 becomes
urgent; if it passes P3 but its worst window sits below the **+0.25 bps** it set as M3-3's bar,
the bar is restated at the new number and every M3-3 comparison is re-read against it — the
challengers do not retroactively pass.

**Q1 — ✅ ANSWERED: (d). Do we shorten the holdout at all — accepting that it weakens every M3
per-window table — or keep the 253-day split and accept ~8.3 months of staleness, growing?**
🔵 **Phase 2 had already removed option (a) as stated.** A ~120-day split cannot be validated on this
population (§5.4), so "shorten for challengers" now means "shorten and have no way to score the
challenger". The live options are:
(b) keep 0.2 and accept growing staleness — this is what happens in the meantime either way,
and it is not a resolution: staleness grows at 0.2 days per calendar day whether or not anyone
looks at it.
(d) ✅ **CHOSEN: add precision before touching the split** — more seeds, the banked 12-pair
universe (`traded-universe`: 12 pairs is the standing long-run intent, the served 8 is a
conservative T6 default), or walk-forward folds — and revisit (a) once a per-window mean has an
interval narrower than the edge. **This is the only path that ever makes freshness measurable**,
and it is the same investment Q2 (B) requires, which is why the two were answered together.

**Q2 — ✅ ANSWERED: (B). If a fresh-boundary model cannot satisfy C1/C2 (§7), which resolution?**
The conflict is structural and is stated in §7: a fresher model has a shorter split, ~±54 bps
resolution and two windows, so it **cannot** pass C1 (all six Tier-1 criteria on its own split)
or C2 (beat the incumbent on worst-window). M3_PROTOCOL §8.5 refuses to lower Tier 1, correctly.
(A) certify the recipe and refresh the checkpoint — rejected as the *primary* route: cheap, but
the artefact actually served is never itself certified, and that is precisely the assumption
Phase 2 tried and failed to test. It remains available as an interim, provided the promotion
record says in plain words that the served checkpoint is uncertified.
(B) ✅ **CHOSEN: walk-forward certification.** §5.4 says accumulating folds is one of the few
things that actually buys the precision this plan lacks, so it is not merely the
expensive-but-correct option — it is a fix for the binding constraint, and it answers Q1 (d)
with the same runs. Its open sub-decision — anchored versus rolling fixed-width train window —
is recorded in §7 B and **must be settled before the folds are run.**
(C) never serve a fresh-boundary model — rejected, though it is the honest name for what happens
by default if (B) is not funded.

**Q3 — 🔵 RE-ANSWERED 2026-09-04 (later the same day): (b), a staleness trigger — see
[M3_PROTOCOL.md](./M3_PROTOCOL.md) §9.1.** Vadim chose the trigger over the cadence: retrain when
the served checkpoint has gone **65 days** without a served bar meeting its own cut, calibrated
as ~1.25× the longest dry spell in the served checkpoint's repaired split (51.8 days), and
re-calibrated from the walk-forward folds when they exist (WALKFORWARD_PROTOCOL §4 item 2). It is
measured live at `/api/health` → `policy.retrain_trigger`. The earlier (a) below is superseded
and kept for the record. *Original answer follows.* **~~✅ ANSWERED: (a).~~ Retrain on a cadence or on a trigger?**
(a) ✅ **CHOSEN: fixed cadence, quarterly**, and Phase 2 strengthens it;
(b) trigger, re-specified against the repaired baseline;
(c) both — cadence as a floor, trigger as an interrupt.
🔵 **Phase 2 closes the door on (b) for now.** §5.6 shows this population cannot resolve a
per-window change of the size a trigger would need to fire on, so a staleness trigger cannot be
calibrated here — the same reason §8.6 Q3's original trigger was void, arrived at from the
other direction. **(a) stands, on the same "bound the identity in §0.2 rather than react to a
signal" grounds, and (c) stays the end state whenever (b) becomes calibratable.**

**Q4 — ✅ ANSWERED: (a). Does Phase 0.2 (the checkpoint-binding guard) block Phases 1–3, or
only Phase 4?**
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

---

## §9 — The backlog's account: the freshness question, and the checkpoint-swap defect

*Moved here from `BACKLOG.md` on 2026-09-04 (RULES_REVIEW §6.3). Both belong to this document — the first is the plan's own centre of gravity, the second is the guard built in §0.2.*

## 🔵 New 2026-09-03 — how fresh should the model be, and how do we find out cheaply

**Owner: [RETRAIN_PLAN.md](./RETRAIN_PLAN.md).** The served model's training data stops
~2025-12-10, so it is **~253 days ≈ 8.3 months stale**, and *nobody chose that*: the split is a
fraction (`VAL_FRACTION = 0.2`), so `staleness = 0.2 × span = exactly the val window's length`.
Staleness therefore **grows on its own at 0.2 days per calendar day**, and adding older history
makes it *worse* (the boundary is `start + 0.8 × span`).

🔵 **ANSWERED 2026-09-04 (Phase 2): whether staleness costs anything is UNMEASURABLE on this
data.** The repair removed the candle defect from w4 and the decay-shaped curve survived
(+18.6 / +15.2 / +5.5 / **−1.9** net at taker) — **but w4's 95% interval contains the means of
all three other windows**, so the windows cannot be ranked at all. Three seeds over one market
give ~35–52 day-clusters per window and ±50–100 bps intervals on a ~15 bps edge. **Phase 3
cannot fix this**: priced against the same precision, its gate could only resolve a freshness
effect of ~111–118 bps/trade, 7–12× the model's entire edge. Freshness is now ranked **fourth**
— behind three things Phase 2 found on the way (see the table).

### ✅ Phase 0 closed 2026-09-04; Phases 1 and 2 done — the plan's centre of gravity has moved

| step | state |
|---|---|
| **0.1** verify the repair actually finished | ✅ **PASSED** — `verify_candles.py` returned **36/36**, twelve pairs × 07-21 / 08-20 / 09-02 at 5m, every one `288/288 exact vol=close=high=low=1.000`. 🟢 **2026-08-20 is the decisive one**: it is the day recorded at a median **11%** of true volume with **0/288** matching closes, and it is now 1.000 across the board. Pre-deploy days prove the repair, the post-deploy day proves the collector fix |
| **0.2** the checkpoint-binding guard | ⚪ **not started — and deliberately not blocking.** See the decision below |
| **0.3** plumb `VAL_FRACTION` and `VAL_OFFSET` into the launcher | ✅ **DONE — both halves.** `train_m2.py` always accepted `--val-frac` / `--val-offset`; the launcher forwarded neither. `VAL_FRACTION` was closed first; `VAL_OFFSET` followed 2026-09-04 (`config.py:188`, `train_m2.py:548`, `gcp_train.sh:180`), with the argparse default moved `0.0 → None` so the env var is reachable and an out-of-range fold now **exits** instead of clamping silently. `VAL_OFFSET=0.0` reproduces the trailing split bar for bar. **This is what makes walk-forward folds launchable** |

🟢 **All five §8 decisions taken 2026-09-04: Q0 (a), Q1 (d), Q2 (B), Q3 (a), Q4 (a).** In one
line each: **re-score the incumbent against Tier 1 on repaired data first** (it is cheap and
everything else assumes its answer); **buy statistical precision before touching the split**,
since a shorter holdout cannot score a challenger; **certify by walk-forward folds** rather than
by refreshing an uncertified checkpoint; **quarterly cadence**, no trigger — this population
cannot calibrate one; and the guard blocks **Phase 4 only**. Q1 and Q2 converge on a single
investment: the folds bought for precision are the folds that certify a fresh checkpoint.

**Decision taken 2026-09-04 — RETRAIN_PLAN §8 Q4 = (a): the checkpoint-binding guard blocks
Phase 4 only.** Phases 1–3 swap no checkpoint, so nothing can be mis-served. The guard remains a
hard precondition for Phase 4 and for M3_PROTOCOL §8.3 **C5**, and it is still the thing that
"blocks fast iteration today" — it is just not a reason to delay a read-only re-baseline.

| item | what | gated on | revival trigger / next command |
|---|---|---|---|
| ✅ **Phase 1 — re-baseline on repaired data** | **DONE 2026-09-04.** Three eval-only runs (`20260904T051921Z` / `061948Z` / `073714Z`), all DONE, on a verified-fresh post-repair dump. 🔴 **Its headline is RETRACTED**: "the repair bought back real edge, median +2.14 bps, 3/3 seeds" was read off the eval log's **Horizon 60m** block, not the **240m primary head** every M3 policy uses. On 240m the same cells are **−1.22 / +3.17 / −3.51** — 1 up, 2 down. What survives: the 240m head is net-**positive** at taker on all three seeds (+6.89 / +6.00 / +8.72), and the C4 cut re-derived to **0.6296** against the frozen `0.6318973898887634` | — | See [RETRAIN_PLAN.md](./RETRAIN_PLAN.md) §4. When reading `eval_m2.py`, **the 240m block is the one that counts** |
| ✅ **Phase 2 — read the decay curve** | **DONE 2026-09-04. Verdict `NOT DECIDABLE`** on both policies, both eras, both scopes — w4's clustered CI contains all three other windows' means. Also found: the two eras are **not the same calendar rows** (val start moved +12d, end +16d), so every before/after is clipped to the shared span; the defect did not degrade w4 evenly, it **deleted the last fortnight** (0 bars over the cut in 2026-08-01..17, all three seeds) | — | `./scripts/m3.sh -m m3 decay` reproduces it; `M3_ERA=repaired` switches any m3 command to the repaired dumps. Logs `logs/P2-*.log` |
| 🔴 **Phase 3 — the paired freshness test** | **BLOCKED — underpowered by construction, not scheduled.** §5.4 prices its gate at a **~111–118 bps/trade** minimum detectable effect against a ~9–17 bps edge. Running it as written returns `NOT DECIDABLE` whatever the truth is | A **redesign that adds day-clusters** — more seeds, the banked 12-pair universe, or walk-forward folds. A shorter holdout makes precision *worse*, not better. 🟢 **§8 Q1 = (d) funds exactly this**, so the revival trigger is now being built | Do **not** launch `VAL_FRACTION=0.095`. Revive only when a per-window mean has an interval narrower than the edge |
| ⚪ **Phase 4 — what gets served, and on what cadence** | Resolves a genuine conflict: a fresh-boundary challenger has a short split and cannot satisfy C1/C2 as written, and §8.5 refuses to lower Tier 1 | Phase 0.2 **only** — the Phase 3 gate is removed, since Phase 3 cannot report | ✅ **RESOLVED §8 Q2 = (B), walk-forward certification** at k× the compute — the only option under which the *served* artefact is itself certified, and the same runs Q1 (d) buys for precision. (A) stays available as an interim only if the promotion record states plainly that the served checkpoint is uncertified. 🔴 **One design question precedes the runs**: anchored versus rolling fixed-width train window (RETRAIN_PLAN §7 B) — the implemented split is anchored, so older folds train on less data and a fold score mixes boundary age with training-set size |

### 🔴 What Phase 2 found on the way — these outrank freshness

| # | finding | why it outranks | cost |
|---|---|---|---|
| 1 | **The incumbent's worst window is −4.61 bps** on repaired data, against the **+0.25 bps** M3_2_RESULTS §D fixed as M3-3's promotion bar | It is about what is servable **today**, and every other question assumes an answer to it | No GPU — a Tier-1 re-score of an existing checkpoint |
| 2 | **The regime ladder flattened by half at Q5** (+35.5 → +17.4 bps; per seed `[+34.8,+32.5,+38.7]` → `[+12.3,+8.3,+32.3]`) | The incumbent's `size_by_regime` overlay rests on exactly this ladder | No GPU |
| 3 | **The served rule (fidelity arm D) scores −0.29 bps** at taker, down from +8.62; the **validated** arm A is at +13.82 | The gap between what was certified and what runs in production is now the entire edge — which is what **0.2, the checkpoint-binding guard**, exists to catch | 0.2 is already sized |

🔴 **Phase 1 buys far more than this plan.** The same three re-scored dumps are what unblock
the arrival-rate re-answer, the C4 re-derivation of the frozen cut and ladder, and the M3-0b /
B1 / B2 re-runs — every one of which currently rests on corrupt candles. They are reachable
from any m3 command as `M3_ERA=repaired`.

🔴 **M3_PROTOCOL §8.6 Q3's recommended retrain trigger is void, and Phase 2 confirms it stays
void.** It proposed triggering on "the served checkpoint going N days without exceeding its own
cut", calling that "exactly the condition now in force" — but **that condition was the candle
defect**. A repaired baseline now exists and it **still cannot calibrate a trigger**: this
population cannot resolve a per-window change of the size a trigger would fire on. The answer
remains a fixed **quarterly** cadence, chosen to bound staleness rather than to react to a
signal.

**The open questions** (§8) — ✅ **all answered 2026-09-04**:
**Q0 = (a)** re-score the incumbent against Tier 1 on the repaired dumps, before any other
phase, no GPU;
**Q1 = (d)** add precision before touching the split — (a) "shorten for challengers" was already
**removed** as unscoreable, and (b) keep-and-accept is what happens meanwhile, not a resolution;
**Q2 = (B)** walk-forward certification, the same runs Q1 (d) buys;
**Q3 = (a)** quarterly cadence; a trigger is not calibratable here;
**Q4 = (a)** the guard blocks Phase 4 only.

**Next command, and the pre-registered reading** (RETRAIN_PLAN §8 Q0). Eval-only, in Docker:

```sh
M3_ERA=repaired ./scripts/m3.sh -m m3 validate   # C3 first, then
M3_ERA=repaired ./scripts/m3.sh -m m3 search     # Tier 1 over the 40 configurations
```

Bring back the `n / 36` Tier-1 line, the incumbent `cov0.02_hold240_rqnone_mcnone_SIZED`'s six
criteria individually, and its per-window net at taker with the clustered interval. **Fail P3
(worst window < −5 bps) → not servable, and Phase 4 becomes urgent. Pass P3 but land below
+0.25 → the bar is restated at the new number and M3-3's comparisons are re-read against it;
the challengers do not retroactively pass.**

---


## 🔴 New 2026-09-01 — swapping the served checkpoint silently breaks the policy

*Filed from [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §6.5, where it was recorded but never
indexed here. It is promoted to its own row because it is **the actual blocker on iterating models
quickly**, which is a standing goal — not a footnote to the freeze.*

The policy now serves two constants frozen from **one specific checkpoint's own split**: the
coverage cut `0.6318973898887634` and the regime ladder, both derived by `backtest.py` over seed 2
(`20260819T142759Z`). **Neither is tied to the checkpoint in code.** `served_pairs` is guarded by a
test; the served *checkpoint* is not. Dropping a new `m2_multi.pt` in place silently invalidates
both constants, and **nothing currently fails when that happens** — the policy would keep trading,
against a threshold belonging to a model that is no longer running. That is the served-vs-scored
defect of 2026-08-31 all over again, with a different trigger.

**Why it matters beyond correctness:** it is what makes "retrain and swap the model on the go"
unsafe today. The obstacle to fast iteration is this missing binding, **not** the protocol.

**What to do (not yet scheduled, needs a decision on approach):** record the checkpoint identity
alongside the constants and refuse to serve — loudly, at boot — when the loaded checkpoint is not
the one the constants were derived from. A promotion then becomes: derive the new cut and ladder
from the new checkpoint's split, update both, restart. ⚠️ It also **restarts the forward clock**,
since it is a different rule, so it cannot be done casually mid-test.

---
