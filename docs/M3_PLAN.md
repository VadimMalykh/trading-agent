# M3 Implementation Plan — the trading policy

**Status:** In progress — **M3-0a, M3-1, M3-2 and M3-3 are complete** (§0.0). A rules baseline clears the pre-registered Tier-1 bar and the learned policy did not beat it, so that rule stands as M3's policy. **The traded-universe question is closed** (T6, 2026-08-27): 8-vs-12 is not decidable on this evaluation period — the effect is within a couple of bps of zero in every framing and the data resolves ±37 bps at best — so the served 8-pair universe stands and no further work is queued on it (§0.6). **T5, the serving bug it uncovered, is fixed.** **M3-4a is committed** ([M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md), 2026-08-28) and it changed the shape of the question: the touch spread is **0.01 bps on BTC**, so the maker upside is a *fee* rebate worth ~4 bps round trip at most, while the **14-bps taker assumption looks far too pessimistic** and may be the larger error (§0.7). **Three items remain: M3-4 (run the study — next), M3-0b (price/funding side-table), and M3-5 (wire the rule to the executor).** Unblocked: R0 promoted 2026-08-26.
**New to this document?** **§0.5** explains what we have in plain language — every term defined, the strategy in dollars, and a direct answer to "can it trade profitably yet?" (short version: the edge is real, but it is unproven at this size, half its economics rests on an untested fee assumption, and nothing is wired to the executor).
**GPU required:** **No — not for any step in this document.** See §0.3.
**Keys required:** No.
**Related:** [M3_PROTOCOL.md](./M3_PROTOCOL.md) (**the pre-registration — read before running any search**) · [M3_3_PROTOCOL.md](./M3_3_PROTOCOL.md) (**M3-3's own pre-registration — the fold structure and the 14 learned runs**) · [M3_2_RESULTS.md](./M3_2_RESULTS.md) (**M3-2's full generated results — all 40 runs**) · [M3_3_RESULTS.md](./M3_3_RESULTS.md) (**M3-3's full generated results — all 14 runs**) · [PLAN.md](./PLAN.md) Phase M3 · [NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) §1.3/§1.5/§1.8 (the evidence M3 consumes) · [SIMULATION.md](./SIMULATION.md) (the live paper-sim stack) · [BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) (the parallel B-wave — shares M3-0b's side-table, and its B2 may hand M3 a new regime observable)

*Written 2026-08-24, at the moment M2 froze. This document is the plan for the whole
milestone; it holds only what is currently true and actionable. When a step's conclusions
are superseded, move the narrative to `docs/archive/TRAINING_HISTORY.md` and carry the
surviving conclusion forward — do not append a contradicting section.*

---

## §0.0 — STATUS: RESUME HERE

*This block is the session-to-session handoff. It holds only what is true **now**: what is
done, what the next command is, and what to bring back. When a step closes, its narrative
moves down into the step's own section or into `docs/archive/TRAINING_HISTORY.md` — it is
never left here contradicting a later result.*

**Last updated: 2026-08-27 (M3-3 complete — the learned policy did not beat the rules
baseline. Later the same day the traded universe looked like a policy lever worth +7.5 net
bps/trade; the T-wave ran two more seeds and **it did not replicate**, and T6 then showed the
comparison **cannot be resolved on this evaluation period at all**. M3 stays on 8 pairs and
the universe question is **closed** — §0.6.)**

👉 **New here, or want this without the jargon?** Read **§0.5** — it defines every term
(what a "basis point" is, what "14 bps" means, maker vs taker), says what the strategy is
worth in dollars, and answers "can it trade profitably yet?" directly. The rest of this
block assumes you have.

### Where the work stands

| step | state |
|---|---|
| **R0** (the blocker) | ✅ promoted 2026-08-26 — seed 2 served at gate 0.6311 |
| **M3-0a** — regime harness + policy backtester | ✅ **built, and both acceptance tests pass** |
| **M3-1** — pre-registered protocol | ✅ **committed 2026-08-27 as [M3_PROTOCOL.md](./M3_PROTOCOL.md)**, before any search ran |
| **M3-2** — rules baseline | ✅ **run 2026-08-27, all 40 configurations** — [M3_2_RESULTS.md](./M3_2_RESULTS.md). A baseline passes Tier 1 |
| **M3-3** — learned policy | ✅ **run 2026-08-27, all 14 configurations** — [M3_3_RESULTS.md](./M3_3_RESULTS.md). **None beat the baseline; M3-2's rule stands as M3's policy** |
| **T-wave + T6** — the 12-pair universe | 🟢 **Closed 2026-08-27, as unresolvable on this data.** The +7.5 did not replicate; T6's fair tests (trade-count-matched, cut-matched, cap-re-tuned) put the effect within a couple of bps of zero in every framing against a ±37 bps resolution limit, and what a count-matched test made look like a pair gain is the *confidence cut*. Served universe stays 8. [T6_RESULTS.md](./T6_RESULTS.md), §0.6 |
| **T5** — `/predict_all` served untrained pairs | 🟢 **fixed 2026-08-27** — `serve.py` now intersects the DB whitelist with the checkpoint's own pair list and reports both on `/health` |
| **M3-4a** — the maker study's pre-registration | ✅ **committed 2026-08-28 as [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md)**, before any fill number. It closes M3-4a's open cadence question and turns up **two data defects and one structural fact** that M3_PLAN had wrong — see §0.7 |
| **M3-4** — the execution-cost study (§3.3) | 🔴 **the next M3 step, and now a two-sided one** — it measures what *crossing* costs as well as what *resting* gets. Ranked risk #2. **Scope: the 8 baseline pairs.** Pre-registered in [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) |
| **M3-0b** — price/funding side-table | ⬜ not started — the only item that adds *new* evidence rather than re-slicing the same 253 days |
| **M3-5** — wire the rule to the executor | ⬜ not started — the policy exists only offline; the live executor is an 86-line stub (§0.5.4) |

### How to run anything in M3

🔴 **Everything runs in Docker — nothing is installed on the host, including for
"just a pandas script".** M3 uses its own torch-free image (`ml/train/Dockerfile.analysis`,
compose service `ml_analysis`, ~200MB, builds in seconds) because it needs no torch, no DB
and no GPU. `scripts/m3.sh` wraps it and builds it on first use:

```sh
./scripts/m3.sh -m m3 validate          # the two acceptance tests — run first, always
./scripts/m3.sh -m m3 power             # the pre-registration facts (M3_PROTOCOL §2/§3/§4)
./scripts/m3.sh -m m3 search            # M3-2: all 40 pre-registered runs, scored (~4 min)
./scripts/m3.sh -m m3 fitprep           # M3-3's pre-registration facts (counts only)
./scripts/m3.sh -m m3 learn             # M3-3: fit and score the 14 learned runs (~3 min)
./scripts/m3.sh -m m3 universe          # T3: M3-2's winner on 8 pairs vs 12, same dumps
./scripts/m3.sh -m m3 universe-fair     # T6: the fair version — matched, re-tuned, with CIs
./scripts/m3.sh -m m3 policy --help     # score one policy spec
./scripts/m3.sh --shell                 # interactive
```

`ml/train` is bind-mounted into the container, so host edits take effect with no rebuild.
The four prediction dumps live in `ml/train/output/eval_dumps/` (gitignored, ~125MB); if
they are missing, re-fetch them:

```sh
mkdir -p ml/train/output/eval_dumps
for RUN in 20260818T185438Z 20260819T142759Z 20260820T025723Z 20260822T012619Z; do
  gcloud storage cp "gs://fluxtrader-train-artifacts/eval/$RUN/eval_preds.parquet" \
    "ml/train/output/eval_dumps/eval_preds_$RUN.parquet"
done
```

### What M3-0a established (2026-08-26)

**Both acceptance tests pass, so the harness is trustworthy and §1.4's risk #6 is closed.**

1. **Fixed-coverage reproduction: 15 of 15 cells match to the digit.** Every seed at every
   coverage reproduces the trainer's own logged `trades / gross_bps / win` — and the pooled
   trade-weighted table reproduces §1.3 exactly (1,081 / 1,783 / 3,718 / 7,104 / 13,462
   trades at +19.38 / +22.03 / +8.91 / +1.89 / −0.00 bps).
2. **The regime ladder is rebuilt and reproduces §1.8.** Quintiles of `btc_absret_1d` over
   the pooled cov05 trades: **−1.9 / −13.9 / +10.2 / +18.0 / +34.2** bps against the
   published −3.4 / −15.3 / +10.1 / +17.4 / +35.5, with `dir_acc`
   0.521 / 0.499 / 0.547 / 0.580 / 0.616 against 0.517 / 0.494 / 0.545 / 0.579 / 0.618.
   The rebuild derives the Q5 boundary at **0.0432** (published 0.0431), selecting **5.218%**
   of bars (published 5.2%). Per-seed Q5: +32.6 / +30.8 / +38.7 against +34.8 / +32.5 / +38.7.
   The residual ≈1bps gap is 24 pooled trades whose 24h lookback is incomplete at the start
   of the validation window; they are dropped rather than zero-filled.
3. **`fwd_ret` compounding re-verified** at 6.34e-09 max abs difference (§1.8 reported 3.2e-7),
   which is what licenses building every trailing observable from the dump instead of the DB.
4. **A tie-handling decision, made explicitly.** `torch.topk` breaks confidence ties at the
   coverage boundary in an order that is a kernel artifact and is not reproducible from
   numpy — it is why `reaggregate_preds.py` books 1,222 trades / +9.43 where seed 3's log
   says 1,223 / +9.60. The new harness selects **every bar at or above the k-th largest
   confidence** (tie-inclusive, deterministic) and reproduces that cell too. Exactly one
   boundary in 15 is contended, so this is a 1-trade-in-1,223 question — but it is now a
   documented definition rather than an accident of which library ran.

### What M3-1 established (2026-08-27)

**The protocol is committed as [M3_PROTOCOL.md](./M3_PROTOCOL.md), before any search ran.**
It fixes the split, the metric, the decision rule and the exact 40 configurations. Three
things came out of writing it that change how every later number must be read:

1. 🔴 **The pooled trade count is not the sample size.** Clustering on the exit calendar day,
   §1.3's cov05 slice has **220 clusters behind 3,718 trades** and a standard error **2.35×**
   the iid one: +8.91 gross carries a 95% CI of **[−10.63, +28.45]**. The "≈9.5bps SEM" this
   plan quoted was an iid figure and was optimistic by that factor. The consequence is
   pre-registered in §2 of the protocol: **this dataset cannot certify a policy at taker
   fees**, so the decision rule is built around robustness, not significance.
2. **A trade-count floor prunes the grid before any P&L was seen.** Requiring ≥100 pooled
   trades in *every* window leaves **16 of 36** configurations eligible. All in-regime configs
   below cov0.05 fail it, because w3 starves — the top-quintile filter leaves only 23–87
   trades there. The regime fires very unevenly across time, and the floor catches it.
3. **Two definitional defects in the M3-0a harness were fixed** before they could be baked
   into a search (both re-validated, TEST 1 and TEST 2 still pass):
   - `size_by_regime` bucketed by a quantile of *selected trades*, contradicting the
     "quantile of BARS" rule the hard threshold obeys. It now uses bar-level quintile edges.
   - `regime_col` with no threshold used to be an error; it now means "condition without
     filtering", which is what makes a sizing-only policy expressible at all.

### What M3-2 established (2026-08-27) — the headline, in plain language

**Full results: [M3_2_RESULTS.md](./M3_2_RESULTS.md) — all 40 pre-registered runs, both fee
assumptions, per window, per seed, per side.** The short version, no statistics required:

1. **There is a tradeable rule, and it is worth about +15 bps a trade after taker fees.**
   Enter on the top **2%** of bars by model confidence, hold **4 hours**, size the position
   by how much BTC has moved in the last 24h (a third of normal size in the calmest fifth of
   the market, up to five thirds in the wildest), no concurrency cap. Over 253 days and three
   seeds that is 1,773 trades, +33.8 bps gross, **+15.0 net at a 14-bps taker round trip**,
   Sharpe 0.93, ~2.3 trades a day per seed. It is positive in all four calendar windows.
2. 🔴 **The finding the whole milestone was built on did not survive in the form we expected.**
   "Only trade when BTC has moved >4.3% in a day" — §1.8's 4× effect, used as a hard on/off
   filter — **fails the bar in every one of its twelve configurations.** Not because it loses
   money: the two best versions are +18.3 and +9.4 bps net pooled. One fails because the
   filter leaves only 45 trades in an entire two-month window, the other because it is
   negative on one of the three seeds. Those two floors were fixed in advance, in M3-1, from
   trade counts alone.
3. **The soft version is what works.** Using the same market-move observable to *size* the
   trade, while still trading out of regime, passes everything the hard filter failed. This
   is the concrete, actionable result of M3-2: **the regime signal is a dial, not a switch.**
4. **The model's direction call is doing the work.** The same entries with the side taken
   from trailing momentum instead of from the model earn **−21.8 bps** instead of +15.0 — a
   **+36.9 bps** gap. Buy-and-hold on the same universe lost 13% over the period. The policy
   is not a repackaged beta bet.
5. **It still cannot be certified, exactly as pre-registered.** The clustered 95% interval on
   the winner is [−33.0, +63.1]. M3_PROTOCOL §2 said in advance that 253 days holding ~162
   independent trading days cannot prove a 15-bps edge net of a 14-bps round trip, and §4.3
   pre-registered that Tier 2 would fail. It did. **This is enough to be M3-3's benchmark and
   to justify paper trading; it is not enough to justify size.**

Two caveats that belong next to the headline: the sizing variant's mean size is 1.34, so per
unit of *notional deployed* it earns +11.2 rather than +15.0 bps; and its worst window (w3,
192 trades) is **+0.25 bps** — an absence of a loss, not a profit. Its max drawdown is also
larger than the flat-size version's (−4.59 against −2.76).

Three structural facts hold across the whole grid and should shape M3-3: **24-hour holds are
untradeable** (every one loses 61–198 bps in w4), **1-hour holds never cover fees**, and
**capping at 3 concurrent positions costs money in every single pairing** — on eight pairs
held serially the uncapped policy is already a real 8-slot portfolio, not leverage.

### What M3-3 established (2026-08-27) — the learned policy lost, and usefully

**Full results: [M3_3_RESULTS.md](./M3_3_RESULTS.md) — all 14 runs, both fee assumptions,
per window, per seed, per side. Protocol: [M3_3_PROTOCOL.md](./M3_3_PROTOCOL.md), committed
before the first fit ran.** The short version, no statistics required:

1. **Nothing learned beat the hand-written rule. Nothing learned even passed Tier 1.** The
   best of the eight fitted configurations reaches **−7.18 bps** on its worst window against
   the baseline's **+0.25**. M3_3_PROTOCOL §7 pre-registered this outcome and what follows
   from it: **M3-2's rule is M3's policy**, the grid is not widened, and a bigger model is
   not the remedy.
2. 🔴 **The extra observations did not just fail to help — they cost money.** The
   confidence-only ablation, fitted by the identical machinery on the one observation M3-2
   already used, **beats both fitted models in three of the four rule pairings.** Nine
   observations on ~188 independent trading days is over-specification, and running the
   ablation is what makes that visible rather than arguable.
3. 🔴 **The size of the edge does not hold still.** The mean gross edge available in the top
   decile of bars is **+7.6 / +18.4 / +3.7 / −7.5 bps** across the four windows — a **25.9
   bps swing, larger than the entire edge any policy here is chasing.** This is a fact about
   the evidence, not about a model. It is why the entry rule that thresholds an *absolute*
   predicted edge collapses (it simply stops firing in the low windows), and it is the
   strongest argument yet for keeping every condition **rank-based** (§1.3.3): an ordering
   survives what a level does not.
4. **M3-2's central finding replicated, in a stronger form.** Holding the entry set constant
   **bar for bar** — the ablation and the re-scored baseline enter the identical 1,796 trades
   — sizing by the regime observable is worth **+8.6 bps on the worst window** and **+8.5
   pooled**, and is the whole difference between failing Tier 1 and passing it. M3-2 reached
   that conclusion by comparing two grid rows; this holds everything else fixed.
5. **A harness check passed that was written to be able to fail.** §6 of the protocol
   predicted, before the run, that a one-feature fit with a positive coefficient must select
   exactly the bars the baseline selects. It did: 34,772 entry bars, identical. Had it not,
   the run would have been void rather than interesting.

The honest reading of why: the learned policy was given four genuinely new observations (the
60m and 1440m heads and whether they agree with the 240m side) and could not turn them into
anything. That is a real answer to a real question, and it cost one afternoon of laptop time
rather than a wave of GPU runs.

### What was measured on 2026-08-27, after M3-3 closed — the universe is NOT a policy lever

🔴 **Read the amendment at the end of this section before quoting any number in it.** The
+7.5 bps below is a single seed and **it did not replicate**. But the follow-up did **not**
show 12 pairs is worse either — that question is open. The section is kept in full because how
a clean-looking measurement turned out to be noise is the most useful thing in it.

**M3-2 and M3-3 both ran on the 8 pairs every published M2 number is measured on. That was
never a decision; it is the experimental control the E-wave froze in place** (NEXT_TRAINING_PLAN
§1.9). The collector and the app whitelist have carried **12** pairs for some time. Nobody had
asked what the extra four are worth *to the policy*, because §1.9 had answered the adjacent
question — are they worth anything to the *model* — and the answer there was no.

They are worth a lot. M3-2's winner, scored twice on the same O8 dump, changing nothing but
the traded universe (`./scripts/m3.sh -m m3 universe`):

| universe | trades | tr/day | gross | **net @14 taker** | net @5 maker | Sharpe | maxdd |
|---|---:|---:|---:|---:|---:|---:|---:|
| the 8 baseline pairs | 606 | 2.28 | +33.31 | **+13.93** | +26.71 | 0.96 | −1.13 |
| **all 12 pairs** | 869 | 3.27 | +40.89 | **+21.44** | +33.94 | 1.23 | −1.67 |

**Why this is not the same claim §1.9 refuted.** §1.9 asked whether 58% more training *rows*
make a better model, and measured no. This asks whether more *instruments* make a better
policy. The model is byte-identical in both rows above — the only difference is how many
things the top-2% selection gets to choose between. Rows and instruments are not the same
quantity, and only one of them was ever tested.

**The validity check.** The 8-pair restriction of O8 reproduces the published 3-seed result
(+13.93 against +15.0, at 2.28 trades/day against 2.3), so O8's single seed behaves like the
family on the 8 pairs and the 12-pair row is the four extra instruments talking, not the seed.
The confidence threshold barely moves (0.5996 → 0.5992), so the wide run is the narrow run's
trades plus 260 new ones, and those 260 earn **+43.07 net against the base-8 trades' +12.21**
inside the same run.

🔴 **Three things this does NOT do, and the third is the one that matters most here.**

1. **It does not fix window 3.** Trade count there goes 30 → 32 and net stays near −52; **P4
   still fails**. The w3 hole is a shortage of confident *bars*, not of instruments.
2. **It does not buy independent days.** Clustering is on the exit calendar day, so extra
   pairs add trades inside existing clusters. The clustered interval *widens* (se 25.7 → 30.2)
   and max drawdown grows. **The certification problem of §0.5.4 item 1 is untouched** — only
   forward time fixes that.
3. **It is one seed, and per-pair numbers do not replicate** (NEXT_TRAINING_PLAN §1.3). The
   per-pair table `m3 universe` prints is texture, never a reason to keep or drop an
   instrument. Two more seeds is exactly what the T-wave buys.

🔴 **AMENDMENT, the same evening — caveat 3 was the fatal one, and the T-wave collected on
it.** T1 (`20260827T050701Z`) and T2 (`20260827T114122Z`) ran O8's recipe at two more seeds
and the winner was re-scored on all three:

| seed | base-8 net@14 | 12-pair net@14 | universe effect |
|---|---:|---:|---:|
| O8 (the table above) | +13.93 | +21.44 | **+7.5** |
| T1 | +7.81 | +5.94 | −1.9 |
| T2 | +4.91 | **−2.70** | −7.6 |
| **pooled** | **+9.29** | **+9.00** | **−0.3** |

O8 reproduces exactly, so nothing above is a bug — it is one draw from a distribution wider
than the effect. **The +7.5 claim is dead:** paired on the exit-day cluster the difference is
−0.85 bps, 95% CI [−6.8, +5.1], which excludes it. Reproduce with
`./scripts/m3.sh -m m3 universe --runs 20260827T050701Z,20260827T114122Z,20260822T012619Z`.

🔴 **SECOND AMENDMENT, and it retracts a rejection.** For a few hours this section and
NEXT_TRAINING_PLAN §2 recorded 12 pairs as *rejected*, on the grounds that the wide pool fails
Tier-1 **P5** (all three seeds individually pooled-positive) where the narrow pool passes.
**That was wrong on two counts, and both are checkable:**

- **P5 has no power here.** Day-bootstrapped 2,000 times, the **8-pair** universe — the one
  that "passed" — fails P5 in **53.8%** of resamples, against the 12-pair universe's **58.6%**.
  A criterion the incumbent fails more often than not cannot separate two options. Per-seed
  cluster-robust SEs are 17.6–30.2 bps on 102–161 clusters, so a per-seed *sign* test is
  nearly uninformative. P5 is a sound screen against configurations that only work on one seed
  during a 40-config **search**; it is not an instrument for arbitrating a deployment choice.
- **The test was tilted toward the incumbent.** M3-2's winning spec — including
  `max_concurrent=None` — was searched on `dumps.BASE8` (`cli.py`'s `cmd_search`) and applied
  verbatim to 12 pairs. Part of what was measured is "does an 8-pair-tuned policy transfer",
  not "is a wider universe better".

🟢 **SECOND AMENDMENT, 2026-08-27 — T6 ran those tests and the question is now CLOSED.**
Full report: **[T6_RESULTS.md](./T6_RESULTS.md)**; the reading is in
[NEXT_TRAINING_PLAN §1.10](./NEXT_TRAINING_PLAN.md). Three things changed:

- **The trade-count-matched test looked like a big 12-pair win (+10.2 bps) and is not one.**
  Matching the trade count also makes the wide arm 1.55x more *selective*. Scoring the 8-pair
  universe at that same cut separates the levers: **+12.7 bps comes from tightening the cut**,
  and the pairs are worth **−2.5** at a matched cut. It was the coverage, not the universe.
- **The cap re-tune bought nothing.** Over the pre-registered cap set `max_concurrent=None`
  wins on **both** universes; every cap in the wider ladder costs net bps. The drawdown
  argument below stands as a description and not as a fix.
- **The comparison is under-powered by a wide margin, and that is what closes it.** The
  cluster-robust SE on the fair difference is 13.2 bps over ~180 exit days: at 80% power this
  data resolves **±37 bps**. The +7.5 was always about a third of what could be seen. More
  seeds cannot help — extra seeds and extra pairs both add correlated trades inside days
  already counted. **Only a longer evaluation period can, and that is calendar, not compute.**

⚠️ **And the first amendment's own interval was the wrong estimand.** "−0.85 bps, CI
[−6.8, +5.1]" is day-weighted and shared-days-only, reported next to trade-weighted means; the
matching trade-weighted interval is **[−12.0, +11.5]**, which *contains* +7.5. **The T-wave
failed to replicate the +7.5; it did not refute it.** Both estimators are now committed in
`ml/train/m3/universe.py` and every interval is cross-checked against a day-bootstrap SE.

🟡 **The one structural finding, and it is a risk result rather than a verdict.** Widening
8 → 12 raised the trade count 50% (1,645 → 2,475) but independent exit days only 11%
(169 → 187), while max drawdown grew −2.83 → −4.53 and the clustered SE widened 20.5 → 23.2.
Correlated instruments gated on a BTC-derived regime column fire together, and the winner spec
has no concurrency cap. **That argues for re-tuning sizing on a wider universe, not for
dropping the instruments** — and inside the wide run the four new pairs are the profitable
half (+15.99 net on 841 trades against the base-8's +5.41 on 1,634), with §1.3's
no-cherry-picking rule still in force.

🟢 **Two transferable lessons, and they point in opposite directions — keep both.** The
comparison in the table above was methodologically clean — same checkpoint, same seed, same
calendar, only the universe varying — and still wrong, because M3's per-trade sd is 259 bps
and a one-seed difference of 7 bps is inside the noise: **a within-run comparison on one seed
is a hypothesis, not a result.** And then the correction over-reached: **a negative result
needs the same scrutiny as a positive one.** Report the CI on the *difference*, and check a
criterion's power on both arms, before letting it close a direction. M3-4 should be designed
with both in mind.

🟢 **The live defect this uncovered is fixed (T5, 2026-08-27).** `serve.py`'s
`/predict_all` iterated the app whitelist — 12 pairs — while the served checkpoint is the
8-pair seed 2, so ADA / AVAX / LINK / XRP resolved to `pair_oov_id`, an embedding row never
trained on any pair, and the system emitted live signals for four instruments the model had
never seen. `_servable_pairs()` now intersects the whitelist with the checkpoint's own
`meta["pairs"]`, logs what it drops, and `/health` reports `trained_pairs` and `served_pairs`.
The whitelist can still only narrow the universe; the checkpoint is a hard ceiling.

### §0.7 — What M3-4a established (2026-08-28) — the execution assumptions are both wrong

[M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) is committed before any fill number, the same order
M3-1/M3-2 and M3-3a/M3-3 used. Writing it required auditing the data first, and that audit
found more than it was sent to find. Reproduce all of it with:

```sh
./scripts/gcp_m3_export.sh            # pulls the book/tape/price slice off fluxtrader-1
./scripts/m3.sh -m m3 bookprep        # the audit — no fill number, by design
```

**1. The cadence question is closed: it is scheduler drift, nothing is being dropped.**
`collector.ex` schedules the next `:poll_book` 5 s *after* walking every pair with a
synchronous REST call, so the true period is 5 s **plus the whole universe's fetch time**.
Median gap is **7.6 s in the 8-pair era and 9.0 s in the 12-pair era**, stepping exactly on
2026-08-14 when four pairs were added, by ~0.35 s per pair — which is the per-pair fetch
latency visible in the staggered write timestamps inside one loop. No conditional write, no
dropped poll. (M3_PLAN's "~10.7 s" was the mean across both eras, and the mean is misleading
here: p95 is 16 s / 23 s and the tail runs to 294 s.)

**2. 🔴 The trade tape is right-censored, and nobody knew.** `collect_trades/2` calls
`agg_trades` with `limit: 200`, and Binance returns the **most recent** 200 — so on a busy
pair the *oldest* trades in the poll interval are silently discarded, and `high`/`low`/
`volume` describe only what survived. Share of windows at the cap: **BTC 30.6%**, ZEC 29.2%,
ETH 28.0%, HYPE 15.2%, PEPE 10.8%. Censoring concentrates in exactly the busy windows where a
resting order would fill, so a naive fill rate is biased **downward and not at random**. The
protocol turns this into an asset by arranging every approximation to point the same way
(§0.2 there): **a maker verdict is safe, a taker verdict is not.** Fixing it going forward —
raise the limit, or move the tape to the uncapped WebSocket stream — is a collector change
worth doing regardless of what M3-4 concludes.

**3. 🔴 The touch spread is ~0.01 bps on the majors, and that changes the question.** Median
touch spread and median notional resting at the touch:

| | BTC | ETH | ZEC | HYPE | PEPE | XRP | LINK | SOL | DOGE | AVAX | WLD | ADA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| spread (bps) | **0.01** | 0.04 | 0.13 | 0.12 | 0.26 | 0.70 | 0.85 | 0.96 | 1.13 | 1.34 | 2.45 | 4.69 |
| touch ($k) | 402 | 238 | 3.0 | 4.2 | 0.8 | 23 | 2.7 | 65 | 14 | 4.2 | 2.9 | 28 |

Two things follow by arithmetic, before a single fill is measured:

* **The maker upside is a fee rebate, not a spread capture.** A resting order gains
  `(taker_fee − maker_fee) + 2 × half_spread` per side, so the round-trip ceiling is
  `4 bps + 4 × half_spread` — **4.02 bps on BTC**, against 13.4 on ADA. The 9 bps that 14-vs-5
  implies is **unreachable on six of the eight served pairs however good the fills are.** The
  "every candidate roughly doubles at maker fees" line throughout this document was never
  achievable at these spreads.
* **The 14-bps taker assumption is the bigger error, and it is pessimistic.** It is
  `2 × (4 bps fee + 3 bps slippage)`. A $10k order against BTC's $402k touch crosses for
  0.005 bps, not 3. If that holds up under measurement, **M3-2's published economics are too
  low**, and the winner's +15.0 net@14 is nearer +21 — which moves a number in
  [M3_2_RESULTS.md](./M3_2_RESULTS.md) further than any maker finding could.

So M3-4 is pre-registered as a **two-sided** study: Q1 measures the taker cost against the
assumed 14, Q2 measures the maker saving against 0 and against its per-pair ceiling. Slippage
is **walked from the ladder** rather than assumed.

**4. The export is deep on purpose.** `scripts/gcp_m3_export.sh` defaults to **20 ladder
levels a side**. The audit above needs only the touch, but the study walks the ladder to price
slippage, and five levels cannot hold a $10k order on 1000PEPE, whose touch holds **$823**.
Depth is nearly free — the server cost is detoasting the 100-level jsonb whatever we project
out of it — so the deep pull is taken once rather than twice.

**5. The power problem is real and is pre-registered as a stopping condition.** The raw ladder
starts 2026-08-05, so the study has **22 day-clusters**, against the ~220 independent days
M3-2 was scored on. The protocol requires the minimum detectable effect to be computed *before*
either verdict may be applied, and — given a ~4 bps maker ceiling — says explicitly that if the
MDE exceeds it, the honest output is "22 days cannot resolve this" and the remedy is calendar
time, not a bigger model. The ladder grows a day per day at no cost.

### The plan from here, in order

*Item 0 is closed and is kept only as the record of why; item 1 can invalidate published
numbers; item 2 adds evidence item 1 cannot; item 3 is worthless until we know what a fill
actually costs. Everything below is scoped to the 8 baseline pairs, which is what is served —
and as of T6 that is a settled scope, not a placeholder.*

#### 0. The 12-pair universe 🟢 **CLOSED 2026-08-27 — nothing further to run**

Two 12-pair seeds ran (T1, T2; ~8h GPU, serial) and T3 re-scored M3-2's winner on all three
12-pair dumps under the adoption rule pre-registered in
[NEXT_TRAINING_PLAN §2](./NEXT_TRAINING_PLAN.md): *adopt 12 pairs iff the wide run still
passes every Tier-1 criterion the narrow run passes and its worst window does not degrade.*

**Outcome: the +7.5 did not replicate, and T6 then closed the question as unresolvable.**
The adoption rule's P5 clause fired against adoption — but P5 is a coin flip at this sample
size, failing on the *incumbent* 8-pair universe 52.4% of the time, so it could not have
decided anything. T6 ran the three fair tests and found the effect within a couple of bps of
zero in every framing, against a resolution limit of ±37 bps (§0.6's second amendment).
**The served 8-pair universe stands. No further GPU and no further offline work.**

🔴 **What T6 found instead, and it is the more useful result:** the criterion that
actually binds this policy is **P3, the −5 bps worst-window floor**, which fails on *both*
universes in 88–98% of day-bootstraps. **Window 3 is the constraint, and no pair-set change
touches it.**

Two things this did close cleanly, both worth keeping:

- **The grid was not re-searched.** T3 scored the already-chosen winner spec, transcribed, on
  both universes of the same dumps, exactly as pre-registered. Re-running the 40 configs on a
  new pair population and taking the best is the shopping
  [M3_PROTOCOL §0](./M3_PROTOCOL.md) forbids — and T6 held the same line: it re-tuned
  *sizing* on a fixed policy and did not re-search the grid. Where T6 noticed that a tighter
  coverage looked better on these checkpoints, it recorded the observation and explicitly
  declined to act on it, because coverage is a searched dimension of the M3-2 grid.
- **A single-seed headline was killed by replication.** That part worked exactly as intended,
  and it is why the T-wave was worth the GPU.

🔴 **The lesson the retraction added:** a pre-registered criterion protects against shopping
for a favourable result; it does **not** make an underpowered test informative. Before letting
any Tier-1 clause close a direction, bootstrap its failure rate on **both** arms.

#### 1. M3-4 — the execution-cost study 🔴 **THE NEXT M3 STEP** (§2 M3-4, ranked risk #2)

**M3-4a is done** — [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) is committed, before any fill
number, and `./scripts/m3.sh -m m3 bookprep` reproduces every fact it rests on. What remains is
running the study it pre-registers. **Read §0.7 before doing so: the protocol's audit changed
what the study is asking, and this sub-section's original framing is preserved below only for
the parts that survived.**

**The question, as M3_PLAN originally put it:** if we rest a limit order instead of crossing
the spread, do we actually get filled — and at what real cost? Every M3-2 candidate roughly
doubles at maker fees (the winner is **+27.1 at maker against +15.0 at taker**), so this
untested assumption underwrites half the published economics.

🔴 **That framing is now known to be too narrow, and the "roughly doubles" is not reachable.**
The touch spread is **0.01 bps on BTC** and 0.04 on ETH — one tick — so a resting order's
entire advantage there is the 2 bps/side fee rebate, capping the maker gain at about **4 bps
round trip**, not the 9 bps that 14-vs-5 implies. Meanwhile the *taker* side assumes 3 bps of
slippage per side, and a $10k order against BTC's **$402k resting at the touch** crosses for
0.005 bps. **The 14 is the more suspicious of the two numbers, and it is wrong in the
direction that makes every published M3 result too pessimistic.** §0.7 has the detail; the
protocol pre-registers both as decision quantities.

🔴 **Do it offline, from data we already have — not on the live paper-sim stack.** §3.3 used to
say "measure it on the paper-sim stack"; that is now known to be wrong, because
`apps/fluxtrader/lib/fluxtrader/trading/executor.ex` cannot place a limit order at all (§0.5.4).
Standing that up first would be days of order-simulation work before the first number arrives.

The data to answer it is **already collected**: the collector has written raw L2 order-book
ladders (`orderbook_levels` — best-first `[price, qty]` arrays, 100 levels a side) plus trade
aggregates with `high`/`low`/`buy_volume`/`sell_volume` (`market_trades`). It supports all
three questions directly: **fill probability** (did the tape trade at or through our resting
price inside the window), **queue position** (resting depth at our level against subsequent
same-side volume), and **adverse selection** (which way the mid moved right after the fills we
did get). It runs in the existing `ml_analysis` image via `scripts/m3.sh` — no GPU, no new
stack, no orders.

🔴 **Two corrections to what this section used to claim, both measured on the VM 2026-08-27,
and both change how M3-4a must be scoped.** It previously said "5-second ladders since
2026-07-17, ~40 days". Neither half is right:

| table | actual coverage |
|---|---|
| `orderbook_snapshots` (derived features) | from **2026-07-17** for BTC/ETH/SOL — this is the 40-day figure, and it is the *wrong table*, it carries no ladder |
| `orderbook_levels` (**the raw L2 ladder M3-4 needs**) | from **2026-08-05** for the 8 served pairs (**22 days**) · from **2026-08-14** for ADA/AVAX/LINK/XRP (**13 days**) |
| observed cadence | ~**10.7 s** per row, not 5 s — 8,037 rows/pair/day against the 17,280 a true 5-second poll would write, while `collector.ex` sets `@book_interval_ms 5_000` |

The cadence gap is not cosmetic: **fill probability is measured against how much of the tape
we can see, and a 10-second sampling interval sees half the book states a 5-second one does.**
M3-4a must resolve whether the collector is dropping polls or the write is conditional, and
state the sampling interval it assumes, before any fill number is quoted.

**Scope it to the 8 baseline pairs — that is what is served** — but produce per-pair numbers
for all 12 wherever the stored ladders allow at no extra cost, though with the universe closed nothing depends on it and re-running
this study would be expensive (§0.6). If 12 pairs were adopted, the four new ones
have 13 days of ladder against the majors' 22. Export all 12, but **pre-register the primary
result on the pairs with the full window and report the short-window four separately** — do
not silently pool two depths of evidence, and do not let a 13-day sample decide a pair's cost.

Take it in the milestone's established two-step order:

- **M3-4a** — export the book/tape slice for the served pairs, then **pre-register** the
  study: the sampling interval, the fill definition, the queue model, the adverse-selection
  horizon, and the number that decides whether maker economics are real. Commit it before any
  measurement, exactly as M3-1 and M3-3a did.
- **M3-4** — run it, and publish the **realized effective round-trip cost per pair** next to
  the assumed 5 and 14 bps, then re-score the M3-2 grid at the measured cost.

**This is also the gate on any universe wider than 12.** The 14 bps is a single number applied
to every pair, and §0.6's gain is carried by mid-caps whose spreads are not the majors'. Until
M3-4 produces per-pair costs, adding instruments is buying edge against an unpriced liability.
The one thing worth doing *before* then is starting **collection** on any candidate pair, since
candles backfill four years on demand and order-book history does not — it begins the day the
collector is pointed at the pair, which is why the four newest pairs have 13 days and not 22.
Budget the disk first: `orderbook_levels` runs ~24 MB per pair per day (5.3 GB for the 1.78M
rows currently held), so 12 pairs is ~8.6 GB/month against 55 GB free on `fluxtrader-1` — about
six months of headroom, under four if the universe grows to twenty.

#### 2. M3-0b — the price/funding side-table (§2 M3-0b)

The only remaining item that adds **degrees of freedom** rather than re-slicing the 253 days we
have already spent. It unlocks barrier exits (the open C4b mismatch), the funding term — signed,
and a real term in the P&L at a 4h hold — and the position-state observations M3-3 had to leave
out of its vector for want of a price path.

**Build it in one pass with the book columns `BOOK_ERA_PLAN.md` B0 needs**, so the two wavefronts
share one alignment rather than risking two. M3-4a's export overlaps this one, so pulling the 5m
candles and `funding_rates` in the same pass costs almost nothing extra.

#### 3. M3-5 — wire the rule to the executor (§2 M3-5)

The M3-2 rule exists only inside `ml/train/m3/`. PLAN.md's M3 row has always listed "Elixir
Executor + hard RiskManager always on" and "signal-only vs signal+policy A/B in simulation", and
the last unchecked exit criterion (§6) is "the policy never bypasses hard `RiskManager` limits" —
which cannot be checked while nothing calls the policy. See §2 M3-5 for what the stub is missing.

**Sequence it last** because the fee study decides what the executor should even try to do
(rest a maker quote versus cross), and building the order path twice is the expensive mistake.

### What M3-3 says NOT to do

Do not widen the learned grid, extend the feature list, or reach for a larger model class —
M3_3_PROTOCOL §4.1 and §7 pre-registered that a linear failure is not evidence a bigger model
would succeed, and §D2's ablation is evidence in the opposite direction. Do not re-tune the M3-2
winner against the same evidence either. The binding constraint is ~220 independent trading days,
and no rearrangement of them fixes that — **only forward time does**, which is a further argument
for getting to paper trading (item 3) rather than re-analysing.

---

## §0 — READ THIS FIRST (plain language, no §0-of-the-training-plan required)

### 0.1 What M3 is

M2 produced a **signal**: for any bar, for any of three horizons, a probability that price
goes up, down, or stays flat. It does not decide anything. M3 is the part that **decides** —
whether to be in the market at all, on which side, how large, and when to get out.

The action space (from PLAN.md) is `flat` / `long` / `short` / `hold` / `exit`, with size
buckets later. The reward is PnL net of fees, funding, and penalties for drawdown and
overtrading.

### 0.2 Why M3 is where the money is

Every change we ever made to the *model* moved the edge by a few percent or not at all. One
observation about **when to trade** moved it by 4×:

| | top 5% of bars | top 2% of bars |
|---|---:|---:|
| all bars | +8.9 gross bps/trade | +22.0 |
| **only when BTC has moved >4.31% in the last 24h** | **+35.5** | **+54.9** |

Net of a 14bps taker round trip, that is the difference between **−5.2 bps (a losing
strategy)** and **+21.5 bps (a working one)** at 5% coverage. Three independently seeded
models agree closely (+34.8 / +32.5 / +38.7). This is the largest measured effect in the
project, and it is a statement about market state, not about the model — which is exactly
why it belongs here and not in M2 (NEXT_TRAINING_PLAN §1.8).

**M3's job is to turn that observation into a policy that survives contact with fees,
funding, position limits, and the fact that the effect is not uniform in time.**

### 0.3 The thing to internalise: M3 is a laptop project

All of this project's infrastructure is training-shaped — self-deleting GPU VMs, a status
bucket, log-fetching scripts. **None of it is on M3's critical path.**

Every eval run already dumps per-bar decision records to
`gs://fluxtrader-train-artifacts/eval/<run_id>/eval_preds.parquet`, and
`ml/train/reaggregate_preds.py` already reproduces `eval_m2.py`'s published numbers from
those dumps using nothing but `pandas`, `pyarrow` and `numpy` — no torch, no DB, no VM. Q1
found the 4× effect entirely that way.

A policy search is a search over *decisions made on already-computed predictions*. It needs
no model training. Budget zero GPU hours for §2 M3-0 through M3-2, and do not spin up a
train VM to do arithmetic.

### 0.4 The one-paragraph plan

Build the backtester before the policy; pre-register how it will be scored before searching
anything; ship an explicit rules baseline before anything learned; and only then ask whether
a learned policy beats it. The risk that ends M3 badly is not "the policy is not clever
enough" — it is **overfitting a five-knob policy to 3,700 trades and believing the number**.

### 0.5 What we actually have right now — in plain words

*This subsection assumes nothing. It defines the vocabulary the rest of the document uses,
says what the system is worth in money terms, and answers the bottom-line question directly.
If you read only one part of this file, read this one.*

#### 0.5.1 The words, defined once

| term | what it means |
|---|---|
| **basis point (bp)** | one hundredth of one percent. **1 bp = 0.01%**, so 100 bps = 1%. Everything here is quoted per trade: "+15 bps" means a trade returns 0.15% of the money put into it. |
| **gross** | the price move the trade captured, **before** paying anything to trade. |
| **net** | what is left **after** trading costs. This is the only number that matters. |
| **taker** | you cross the spread and take the price on offer — instant fill, higher fee. |
| **maker** | you rest a limit order and wait for someone to trade against it — cheaper, but **you might never get filled**. |
| **round trip** | the full cost of one trade: getting in *and* getting out. |
| **the 14 bps** | our **taker** round-trip cost assumption: 4 bps exchange fee + 3 bps slippage, **doubled** because you pay it on entry and again on exit = 14 bps = **0.14% per trade**. |
| **the 5 bps** | the **maker** equivalent: 2 bps fee + 0.5 bps slippage, doubled = 5 bps = 0.05% per trade. 🔴 **This one is an assumption we have never verified** — see §0.5.5. |
| **coverage** | what fraction of all available bars we actually trade. "Top 2%" = we sit out 98% of the time and only act on the 2% of moments the model is most confident about. |
| **a window** | one of the four consecutive calendar chunks the 253-day test period is cut into. A rule has to work in *all four*, not just on average — that is how we catch a rule that only worked during one lucky stretch. |
| **the worst window** | the score in whichever of the four chunks went worst. We rank policies on this, not on the average, deliberately. |

#### 0.5.2 The one-sentence version of the whole milestone

**The model finds a real edge of about +34 bps per trade before costs; trading costs eat
roughly 14 of those; what survives is about +15 bps — 0.15% per trade — and that is a
genuine profit but too thin, on too few independent days, to prove it will persist.**

#### 0.5.3 What "+15 bps a trade" actually means in money

The policy is: watch eight crypto pairs; on the 2% of moments the model is most confident,
open a position in the direction it calls; hold for **4 hours**; size it by how violently BTC
has been moving over the past day (a third of normal size when the market is calm, up to
five thirds when it is wild); then close, regardless of what happened.

That fires about **2.3 trades per day**. So with **$10,000** committed per trade:

| | per trade | per day (2.3 trades) | over the 253-day test |
|---|---:|---:|---:|
| gross (before costs) | +$33.80 | +$78 | ≈ +$20,000 |
| **net at taker (14 bps)** | **+$15.00** | **+$34** | **≈ +$8,900** |
| net at maker (5 bps) | +$27.10 | +$62 | ≈ +$16,000 |

Two honest deductions from that table. First, the sizing rule means the *average* position is
1.34× the base size, so per dollar actually deployed it is **+11.2 bps, not +15.0**. Second,
this is the result of three separately-trained copies of the model pooled together over
1,773 trades — it is not a live track record, and no order has ever been placed.

#### 0.5.4 So — can it trade profitably or not?

**Not yet. Three separate things are missing, and only one of them is about the edge.**

1. **The edge is real but unproven at this size.** +15 bps per trade is positive in all four
   calendar windows, on all three model seeds, and the direction genuinely comes from the
   model (swapping in a momentum-based direction turns +15 into −22). But the statistical
   error bar on it runs from **−33 to +63 bps**. The reason is not sloppiness: 253 days of
   eight correlated pairs is only about **220 genuinely independent days**, and that is
   nowhere near enough to prove a 0.15% edge against a 0.14% cost. This was written down in
   advance (M3_PROTOCOL §2) as something this dataset *cannot* do, and it turned out exactly
   as predicted. **More analysis of the same 253 days will not fix it — only more time will.**
2. 🔴 **Half the economics rests on an untested assumption.** Every number roughly doubles at
   maker fees (+15 → +27). We have never once checked whether a resting limit order on these
   pairs actually gets filled at that price, or how often the fills we do get are the ones we
   would rather not have had. That is the next piece of work (§0.5.5).
3. 🔴 **Nothing is connected.** The policy exists only inside the offline backtester in
   `ml/train/m3/`. The live executor (`apps/fluxtrader/lib/fluxtrader/trading/executor.ex`)
   is an 86-line stub: it logs a mock position and has **no fees, no limit orders, no fill
   logic, no 4-hour hold timer, and no position sizing**. Even in paper mode, the system
   cannot currently execute the rule we just spent the milestone finding.

**The honest verdict: we have a credible, well-tested candidate strategy and no way to run
it.** The realistic next milestone is not "make the edge bigger" — it is "find out what the
fills really cost, then wire the rule to the executor and let it paper-trade forward long
enough to accumulate the independent days the statistics need."

#### 0.5.5 The one thing that could still change the picture — and it is not what we thought

Until 2026-08-28 the answer here was "whether **maker fills are real**": rest limit orders,
get filled at 5 bps instead of 14, and the strategy roughly doubles. **That hope is now
arithmetically dead, and something better replaced it.**

Here is the whole thing in plain terms. When you buy, you can either **cross the spread**
(take the best price someone is already offering — a *taker* order, which fills instantly) or
**rest** an order and wait for someone to come to you (a *maker* order, which is cheaper per
the exchange's fee schedule but might never fill). The cost of each has two parts: the
exchange's **fee**, and the **spread** — the gap between the best buy price and the best sell
price, which you pay half of when you cross and earn half of when you rest.

We had assumed crossing costs **14 bps** round trip (0.14% of the trade) and resting costs
**5 bps** (0.05%). On a $10,000 trade that is $14 versus $5. The strategy earns about 15 bps a
trade after the 14, so halving the cost really would roughly double it.

**Then we looked at the actual order books, and the spread on Bitcoin is 0.01 bps.** One tick.
Effectively zero. So:

* **Resting saves almost nothing extra.** With no spread to earn, the only maker advantage is
  the fee difference — about 4 bps round trip, not 9. And you take real risk to get it: your
  order may not fill, and while you wait the price moves.
* **But crossing costs almost nothing either — and that is the good news.** The 14 assumed
  3 bps per side of "slippage", the extra you pay for pushing the price when your order is big
  relative to what is available. A $10,000 order on Bitcoin is nothing against the **$402,000**
  sitting at the best price. **The real cost of crossing looks closer to 8 bps than 14.**

If that survives measurement, the strategy is **better than published** — the 15 bps a trade
was computed against a cost roughly 6 bps too high — and it gets there by crossing the spread
like a normal order, with no limit-order machinery to build. That is the outcome that most
simplifies M3-5.

Both numbers are now pre-registered as things to measure, in
[M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md). **The honest caveat: the order-book history only
starts 2026-08-05, so there are 22 days to measure on, and the protocol says up front that if
22 days cannot resolve the question, the answer is "wait" — not "guess".** See §0.7 and
**M3-4** in §2, which is the next step.

---

## §1 — WHAT M2 HANDS OVER

### 1.1 The served signal

- **Checkpoint:** `m2_multi_20260819T142759Z_a186182b.pt` (seed 2 of the 5m/seq384 family).
- **Served gate:** `conf >= 0.6311`, realizing ~2% coverage, dir_acc 0.578, +18.68 gross
  bps/trade, +4.68 net at 14bps taker.
- **Shape:** 2-layer LSTM, 64 hidden, ~56k params. Reads 384 five-minute bars (32h) for one
  pair. Emits per-horizon 3-class direction for **60 / 240 / 1440 minutes**; the optimised
  and served primary is **240m (4h) = 48 bars**.
- **Live endpoint:** `GET /health`, `GET /predict?symbol=…`, `GET /predict_all` on
  `ml_inference:8001`. `/predict` returns raw per-horizon confidences **alongside** the
  `gated` boolean, so a policy can ignore the serve-side gate without a serve change.

### 1.2 The offline artifacts M3 actually builds on

`eval_preds.parquet`, one row per (bar × horizon), written by `eval_m2.py --dump-preds`:

| column | meaning |
|---|---|
| `ts` | epoch **nanoseconds** UTC — the bar the decision is made **on**, not the exit |
| `pair` | categorical |
| `horizon` | 60 / 240 / 1440 (minutes) |
| `side` | −1 short / +1 long (the same signal the gate and every published P&L uses) |
| `conf` | gate confidence |
| `p_up` | softmax P(up) |
| `fwd_ret` | the return realized by a trade opened at this bar and held the full horizon |
| `y3` | realized class: 0 down / 1 flat / 2 up |
| `has_book` | whether this bar is in the order-book era |

Three seeds are available (`20260818T185438Z`, `20260819T142759Z`, `20260820T025723Z`).
**Use all three.** Pooling them is what turned Q1's finding from "2.5σ on a pooled SEM" into
"three independent models agree", and it is the only cheap source of replication M3 has.

🔴 **What the dump does NOT contain: price.** There is no OHLC path and no funding rate —
only `fwd_ret` at a fixed horizon. This is the single most important structural fact for
§2, because it means **fixed-hold policies can be backtested from the dumps alone, and
barrier/stop policies cannot.** Anything involving a stop-loss, a take-profit, a trailing
exit, or a funding charge needs a price/funding side-table joined on `(pair, ts)`. Plan for
that as a distinct step (M3-0b), not as an afternoon's work inside M3-0a.

### 1.3 The three findings that are *constraints*, not context

Each of these is a rule the policy must obey. They are not suggestions and each was paid
for with a wave of runs.

1. **The signal is only cost-viable in a narrow confidence band.** +19.4 / +22.0 gross
   bps/trade at the top 1% / 2% of bars, +8.9 at 5%, +1.9 at 10%, 0.0 at 20%. **Coverage is
   therefore a first-class decision variable of the policy**, not a threshold to tune away.
   The full table:

   | cov | trades | gross bps | net @5bps maker | net @14bps taker |
   |---|---:|---:|---:|---:|
   | 0.01 | 1081 | +19.38 | +14.38 | +5.38 |
   | 0.02 | 1783 | +22.03 | +17.03 | +8.03 |
   | 0.05 | 3718 | +8.91 | +3.91 | −5.09 |
   | 0.10 | 7104 | +1.89 | −3.11 | −12.11 |
   | 0.20 | 13462 | −0.00 | −5.00 | −14.00 |

2. **Calibration is fragile and over-confident.** In the `[0.60,0.70)` bin the model says
   0.640 / 0.626 and reality is 0.576 / 0.578. Three separate levers (P2, R2, R3a) improved
   or held *ranking* while destroying the probability *scale*. **If the policy consumes
   `p_up` as a probability — for Kelly-style sizing, for an expected-value calculation, for
   anything beyond an ordering — it must re-check brier and the bin table on the specific
   checkpoint it was handed.** Do not assume a model that ranks well is calibrated.

3. **Absolute confidence thresholds do not transfer between checkpoints.** The same
   probability is 1.2% / 2.5% / 1.7% coverage across three seeds of one configuration, 0.8%
   on O3 and 80% on P2. **The policy must condition on coverage rank, never on a raw
   confidence constant.** A policy written against `conf > 0.63` is a policy that silently
   breaks on the next checkpoint.

Two smaller ones worth carrying:

- **The model's own trailing confidence is anti-predictive** (`mean_conf_1d` AUC 0.480 /
  0.471 / 0.499). A confident recent stretch is not a good stretch. Do not build a
  "the model is hot right now" term.
- **Side balance is not seed-stable** — seed 3's short side is a coin flip (0.502 vs 0.563
  long) while seeds 1 and 2 are balanced. Check long/short separately on whatever checkpoint
  is served; do not assume symmetry.

### 1.4 ✅ The Q1 harness was never committed — so M3-0a rebuilt it, and it is committed now

For the whole of M2, `btc_absret_1d` existed **only in `docs/`**: the script that computed
the regime observables and produced §1.8's numbers was never in the repository. That was
this milestone's risk #6, because every policy in M3 is built on top of it.

It is now `ml/train/m3/regime.py`, and it is pinned by an acceptance test rather than by
trust: `ml/train/m3/validate.py` reproduces §1.8's published quintile ladder and the 4.31%
threshold from the dumps alone (see §0.0 for the numbers). The construction is the one §1.8
describes — `fwd_ret` at horizon *h*, shifted back *h* minutes, is a lookahead-free trailing
return, and the horizons compound to 6.34e-09, so no DB round-trip is needed.

⚠️ **Only `btc_absret_1d` is pinned.** `regime.py` also rebuilds `btc_ret_1d`, `btc_ret_7d`,
`btc_sign_1d`, `rv_1d/7d/30d`, `xs_disp_4h` and `mean_conf_1d` so the AUC table can be
re-derived as a cross-check, but their definitions are reconstructions and no test holds
them in place. **`xs_corr_1d` and `xs_corr_7d` are not rebuilt at all.** Do not condition a
policy on any of them without first reproducing §1.8's AUC column for it. §1.8's own reading
is that none of them is worth conditioning on anyway — they were U-shaped, seed-unstable or
flat — so this is a gap in the cross-check, not in the policy's toolkit.

---

## §2 — THE SEQUENCE

Strictly ordered. Each step's output is the next step's input, and the ordering is the
protection against the failure mode in §0.4.

### M3-0a — ✅ DONE (2026-08-26). The harness exists and is validated.

**What was built,** all of it in the torch-free `ml_analysis` container (§0.0 says how to
run it):

| file | what it is |
|---|---|
| `ml/train/m3/dumps.py` | loading and **pooling** the per-seed dumps; the calendar windows; the BASE8 universe |
| `ml/train/m3/regime.py` | the rebuilt Q1 observables (§1.4) and the compounding check |
| `ml/train/m3/backtest.py` | the event-driven simulator — `PolicySpec` is the full list of the policy's degrees of freedom |
| `ml/train/m3/metrics.py` | P&L at both fee levels, drawdown, daily Sharpe, per-window and long/short splits |
| `ml/train/m3/validate.py` | **the two acceptance tests.** Run before believing any number |
| `ml/train/m3/cli.py` | `python -m m3 validate` / `python -m m3 policy` |
| `ml/train/Dockerfile.analysis`, `scripts/m3.sh` | the container everything runs in |

**Every degree of freedom §M3-0a called for is supported**: entry by coverage rank (never by
a confidence constant), serial positions per (seed, pair), time-based exits, both fee levels
side by side, a portfolio-wide concurrency cap, regime conditioning with the threshold
derived as a quantile of *bars*, and regime-scaled sizing.

**Three constraints the implementation makes explicit**, each of which a future session
should not have to rediscover:

1. 🔴 **Exits can only land on 60 / 240 / 1440 minutes**, because those are the horizons the
   dump carries `fwd_ret` for. `--hold-horizon` selects among them (a 4h signal held 1h is a
   legitimate policy). Any other hold length — and every stop, take-profit or trailing exit —
   needs M3-0b's price table. The simulator refuses rather than approximating, because a
   barrier policy scored against a fixed-horizon return is exactly the C4b mismatch.
2. **Pooling is concatenation keyed on the seed, never a merge.** Two seeds gating the same
   bar are two observations, and one seed's open position must not block another's entry.
3. **Coverage selection is tie-inclusive** — every bar at or above the k-th largest
   confidence — so the slice is deterministic and re-derivable instead of depending on
   `torch.topk`'s kernel-level tie order (§0.0, point 4).

**Acceptance test result: both pass.** 15/15 fixed-coverage cells to the digit, the pooled
§1.3 table exactly, and §1.8's regime ladder within ≈1bps. Numbers are in §0.0.

**Still open inside M3-0a's scope, and deliberately deferred:** `xs_corr_1d` / `xs_corr_7d`
are not rebuilt (§1.4). The 12-pair dumps were never folded into a pooled *search* population,
and 2026-08-27 settled that they should not be: §5 now records that their extra trades are
correlated with the existing ones rather than additive, so they are a replication check across
instruments and not added power.

### M3-0b — The price/funding side-table (item 2 of the remaining three)

Export **once** from the always-on VM to local parquet: 5m candles and `funding_rates` for
the eight served pairs over the validation window. Join on `(pair, ts)`.

This unlocks three things that are impossible in M3-0a:

- **Barrier-aware exits** — walk forward to the first take-profit/stop-loss touch, else time
  out. This is the already-open task **C4b** in NEXT_TRAINING_PLAN §6, filed there as
  "under triple-barrier labels the model predicts a TP/SL outcome but `simulate_pnl` books
  `fwd_ret` at a fixed `hold_bars` — a policy mismatch". M3 is where that mismatch stops
  being theoretical.
- **Funding cost.** `funding_rates` is the one microstructure source with real history
  (2y9mo–3y11mo). At a 4h primary horizon, funding is a real term in the P&L, not a rounding
  error, and it is *signed* — it can pay you.
- **Slippage / fill realism** beyond a flat per-trade constant.

**Do not start here — but it is no longer far off.** A fixed-hold policy that works is worth
more than a barrier policy that cannot be validated, and M3-0a's acceptance test is only
expressible in fixed-hold terms. That condition is now met: M3-2 produced a fixed-hold policy
that works, so this is item 2 of the three remaining (§0.0), behind M3-4 only.

🔴 **Do the export in the same pass as M3-4a's.** M3-4 needs the book/tape slice, M3-0b needs
5m candles and `funding_rates`, and `BOOK_ERA_PLAN.md` B0 needs the 11 microstructure scalars —
all on the same `(pair, ts)` grid with the same staleness caps. One pass, three consumers, one
alignment.

**When you do build it, add the book columns in the same pass.** `docs/BOOK_ERA_PLAN.md` B0
needs exactly this export plus the 11 microstructure scalars over the book era, joined on the
same `(pair, ts)` grid with the same staleness caps. Building it once serves both wavefronts;
building it twice risks two different alignments and neither being evidence about the other.

### M3-1 — ✅ DONE (2026-08-27). The protocol is pre-registered.

**It is [M3_PROTOCOL.md](./M3_PROTOCOL.md), committed before any search ran.** §0.0 carries
what writing it established. The rest of this section is kept as the *rationale* for why the
step existed — the binding document is the protocol, and it is not edited once a search has
begun.

Write down, **and commit, before running a single search**: the split, the metric, the
decision rule, and the number of configurations that will be tried.

Why this is a step and not a paragraph:

- A policy has far more knobs than the model did — entry rank, hold length, exit rule,
  sizing curve, regime condition, per-pair and portfolio caps. The model waves could get
  away with "one change per run" because each run cost 3 GPU-hours. A policy search costs
  seconds per configuration, so the only thing standing between you and an overfit is a
  written-down protocol.
- The sample is small: **3,717 pooled cov05 trades across three seeds, per-trade sd 259bps.**
  A quintile's standard error is ≈9.5bps. Many plausible policies will differ by less than
  that.
- 🔴 **§1.8's caveat is a live warning, not a footnote.** `btc_absret_1d`'s ladder holds in
  three of four calendar windows and **fails in window 2 (Q5 = −10 bps), which is where 47%
  of its trades live.** A pooled number will tell you the rule is worth +35 bps. It is worth
  +35 bps in three windows and −10 in the one it fires hardest in. **Score walk-forward
  across calendar windows and report the worst window, not the mean.**
- Also pre-register the trivial baselines the policy must beat: buy-and-hold (≈−35 over the
  val window), trailing-48-bar momentum (dir_acc 0.469 — mildly *anti*-predictive), and
  M2's own ungated fixed-coverage table from §1.3.

### M3-2 — ✅ DONE (2026-08-27). The rules baseline, and it is M3's policy.

Under five parameters, all of them interpretable:

1. Enter only when confidence is in the **top-k% by coverage rank** (k the first parameter).
2. Only when the **regime observable is in its top quintile** (the threshold, ~4.31% BTC
   trailing-24h |return|, is the second — and it must be re-derived per split, not hard-coded).
3. **Size** flat, or scaled by regime quintile (third).
4. **Hold** to the 4h primary (48 bars), with an optional stop (fourth/fifth).

Two reasons this comes first rather than after a learned policy:

- Given a 4× effect that is already visible in a quintile table, a rules baseline may capture
  most of the value that exists. It would be an expensive way to find that out afterwards.
- Without it, a learned policy has no honest benchmark. You would have no way to distinguish
  "the policy learned something" from "the policy rediscovered the rule, and I fitted a
  neural network to do a comparison".

**Note the direction-free property:** Q1's Q5 effect is +36.9 on BTC-up days and +35.2 on
BTC-down days. The regime term is about the **magnitude** of the market move, not its sign.
A baseline that accidentally makes it directional is a bug.

**Outcome (2026-08-27): done, and the result is in [M3_2_RESULTS.md](./M3_2_RESULTS.md).**
Parameters 1 and 3 carried the milestone; parameter 2 — the hard top-quintile filter — did
not. Of the 36 pre-registered grid configurations exactly one clears Tier 1 and it uses
coverage alone; the twelve that apply the regime as an on/off filter all fail, two of them on
a single criterion each (an under-sampled window, and one seed going negative). The §3.2
sizing variant, which applies the same observable as a **size multiplier** rather than a
filter, also clears Tier 1 and outranks it. §0.0 carries the plain-language summary.

The direction-free property held: nothing in the winning configuration conditions on the sign
of the BTC move, and the momentum-side control (§3.2) confirms the *direction* comes from the
model — its side is worth +36.9 bps/trade over `sign(trailing 240m)` on the same entry bars.

### M3-3 — ✅ DONE (2026-08-27). The learned policy did not beat M3-2, and the rule stands.

**Protocol: [M3_3_PROTOCOL.md](./M3_3_PROTOCOL.md), committed before the first fit ran.
Results: [M3_3_RESULTS.md](./M3_3_RESULTS.md), 14 runs.** §0.0 carries the plain-language
summary. The rest of this section is kept as the *rationale* — what was built and why it was
built that way — because the next session's question will be "was this done properly?" and
the answer has to be inspectable.

PLAN.md locks the family and M3-3 stayed inside it: **offline / bandit-style on logged
rollouts, not end-to-end price RL.** One simplification is worth carrying forward, because it
is a property of the evidence rather than a choice: **the logged rollouts carry full feedback,
not bandit feedback.** The dumps hold `fwd_ret` for every bar, not only for bars a behaviour
policy happened to trade, so the counterfactual is known everywhere. There is no propensity to
model and no unobserved arm — the direct method is exact here, and any future policy work over
these dumps inherits that.

**What was fitted.** A value function ŝ(x) = the estimated gross edge in bps of taking M2's
side at this bar, over nine rank-valued observations; the policy is derived from it by an
entry rule and a sizing rule. The side is **not** learned — M2 supplies it and M3-2 §D3 measured
it at +36.9 bps over a momentum side, which is the one part of the system with three-seed
replication behind it.

**The two things that made the result trustworthy**, both of which a future step should copy:

1. 🔴 **Leave-one-window-out, refit four times.** M3-2 could score fixed rules on all four
   calendar windows because a rule with no fitted parameter has no training error. A fitted
   model scored on the windows it was fitted on has nothing but training error. Every learned
   number in M3-3 was produced by a model that never saw the window it was placed in.
2. **A matched ablation on the one observation M3-2 already used**, run at all four rule
   settings. It is the number that decides whether the exercise was worth anything — and it
   is what turned "the learned policy lost" into "the extra observations cost money", which
   is a far more useful finding.

**What was deliberately left out and is still waiting:** position state (side, age, unrealised
P&L) needs a price path between entry and exit, so it needs M3-0b. Under fixed-hold serial
entries it was not decision-relevant anyway — there is no exit decision to make. It arrives
with the barrier exits that would give it something to decide.

**Do not re-run this with more knobs.** M3_3_PROTOCOL §4.1 and §7 pre-registered that a linear
failure is not evidence a bigger model would succeed, and the ablation is evidence pointing the
other way.

### M3-4 — 🔴 NEXT. The maker-fee study, measured offline from data we already hold.

**The question in one line:** is the 5-bps maker round trip that doubles every published number
actually obtainable, for these pairs, at these sizes?

**Why it is ranked above every remaining knob.** It does not add a result — it can *invalidate*
results already published. At taker the whole cov05 slice is −5.09 net; at maker it is +3.91. The
M3-2 winner is +15.0 taker / +27.1 maker. No other open item can move numbers already in
[M3_2_RESULTS.md](./M3_2_RESULTS.md) in both directions.

🔴 **The data source, and why it is not the paper-sim stack.** §3.3 originally said to measure
this live on the paper-sim stack. **That is not viable and the reason is concrete:**
`apps/fluxtrader/lib/fluxtrader/trading/executor.ex` is an 86-line stub with no fee model, no
limit orders, no fill logic and no hold timer (§0.5.4, and see M3-5). Building order simulation
first would put days of work in front of the first number.

Instead, measure it **offline** from what the collector has already stored:

| source | what it gives | cadence / depth — **measured 2026-08-28, not assumed** |
|---|---|---|
| `orderbook_levels` | raw L2 ladder, `bids`/`asks` as best-first `[price, qty]` arrays **stored as jsonb**, 100 levels a side, joined to `orderbook_snapshots` on `(symbol, ts)`; also carries `event_time` / `transaction_time`, the exchange clocks | **irregular, median 7.6s (8-pair era) / 9.0s (12-pair era), p95 16s / 23s** — *not* the 5s `@book_interval_ms` suggests. Since **2026-08-05** (8 pairs) / **2026-08-14** (the other 4) |
| `market_trades` | per-window `high`, `low`, `volume`, `buy_volume`, `sell_volume`, `vwap` — **right-censored at 200 aggTrades per poll**, which is 30.6% of BTC's windows | rows ~10s apart, labelled `floor_to_5s(last trade)`; the label is **not** the span |
| `orderbook_snapshots` | `mid`, `spread`, `microprice`, `imbalance`, near/far depth | same rows as the ladder, same irregular cadence |

**22 days** for the served eight, 13 for the other four, **entirely inside the validation
window**, which is the same era every M3 number is scored on. §0.7 has what the audit found and
why it re-shaped the study; [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) is the pre-registration.
Three measurable quantities fall out, all of them now pre-registered rather than sketched:

1. **Fill probability** — for a limit order resting at the touch at the decision bar, did the
   tape trade at or through that price within the fill window? `market_trades.low` / `.high`
   answer it, subject to the censoring above, which biases the answer **downward**.
2. **Queue position** — resting quantity at our level from the ladder, against subsequent
   same-side volume. A crude drain model, **declared** crude in protocol §2.3 with each of its
   five approximations and the direction each one biases.
3. **Adverse selection** — where the mid went after the fills that did arrive. A maker fill
   that only happens when the market is about to run you over is not a 5-bps fill, whatever
   the fee schedule says.

…and a fourth the original framing missed, which §0.7 argues may matter more than all three:
**what crossing actually costs**, walked from the ladder for a real order size instead of
assumed at 3 bps/side.

**Done in two commits, the way M3-1/M3-2 and M3-3a/M3-3 were:**

- ✅ **M3-4a — pre-register first.** `scripts/gcp_m3_export.sh` exports the slice off the VM;
  `./scripts/m3.sh -m m3 bookprep` audits it; [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) fixes the
  fill definition, the queue model and its stated crudeness, the adverse-selection horizon, the
  sampling layers and staleness rule, the size ladder, and **the two numbers that decide the
  verdict** — all committed before any of them was computed.
- ⬜ **M3-4 — then run it.** Publish `docs/M3_4_RESULTS.md` with the eight panels protocol §6
  fixes, ending in the **re-score of the M3-2 grid at the measured cost**. That re-score is the
  deliverable that changes what we do next, not the fill rate on its own.

It runs in the existing torch-free `ml_analysis` image through `scripts/m3.sh` — **no GPU, no new
stack, no orders placed** — as the `bookprep` subcommand next to `search` / `learn`.

**The export is combined with M3-0b's**, as planned: the same pass pulls the 5m candles and
`funding_rates` M3-0b needs and the book columns `BOOK_ERA_PLAN.md` B0 needs. One alignment,
three consumers.

### M3-5 — Wire the rule to the executor (the last unchecked exit criterion)

PLAN.md's M3 row lists two work items that no step so far has touched: **"Integrate — Elixir
Executor + hard RiskManager always on"** and **"A/B — signal-only vs signal+policy in
simulation"**. §6's last open box — *the policy never bypasses hard `RiskManager` limits* —
cannot be checked while nothing calls the policy.

**What exists today.** `Trading.Executor` is 86 lines. In `simulation` mode it logs
`[SIM] Signal: …` and appends a mock position built by `build_mock_position/1`. It has **no fee
model, no limit orders, no fill logic, no hold timer, no exit path, and no sizing** — the mock
position carries `pnl: 0.0` and is never updated. `Trading.RiskManager` is 98 lines alongside it.

**What M3-5 has to add**, and nothing more — this is an integration step, not a new search:

1. **The M3-2 rule, expressed once.** Entry on the top-2% confidence rank, side from M2, the
   regime size multiplier (⅓ to 5/3 on trailing BTC 24h move), a **4-hour hold**, no concurrency
   cap. §1.3.3's constraint binds here: the coverage condition is **rank-based**, so the policy
   needs a trailing confidence distribution to rank against, not a fixed threshold.
2. **The coverage decision from §3.1.** `serve.py` gates and the app gates again. If the policy
   gates too there are three gates in series and it can never *widen* coverage. **The policy owns
   coverage; the serve gate becomes a reported diagnostic.** `/predict` already returns raw
   confidences next to `gated`, so this needs no serve-side change.
3. **A real fill and fee path**, using whatever M3-4 measured — including the maker-vs-taker
   decision, which is exactly why M3-5 is sequenced after M3-4.
4. **The A/B.** Signal-only against signal+policy, both paper, scored on the same metrics
   M3_PROTOCOL §4 uses so the live numbers are comparable to the backtest ones.
5. **The risk-limit assertion.** A test that the policy's orders are refused by `RiskManager`
   when they breach a hard limit — that is what closes §6's last box.

**Why this matters beyond tidiness:** §0.5.4 and risk #4 both land on the same wall — ~220
independent trading days is not enough to certify a 15-bps edge, and no re-analysis of the same
253 days relieves it. **Paper trading forward is the only mechanism that manufactures new
independent days.** Every week M3-5 is not running is a week of evidence not being collected.

## §3 — DESIGN DECISIONS TO SETTLE BEFORE WRITING CODE

### 3.1 Where the gate lives — decide this first, it is architectural

Today `serve.py` gates and the Elixir app gates again, both off `ML_GATE_THRESHOLD`. If the
policy *also* gates, there are three gates in series and **the policy only ever sees bars M2
already approved** — it can never choose to widen coverage, which §1.3.1 makes a first-class
decision variable.

`/predict` already returns raw confidences next to `gated`, so the app can ignore the serve
gate with no serve-side change. **Recommendation: the policy owns coverage; `serve.py`'s
gate becomes a reported diagnostic, not a filter.** Make this an explicit decision rather
than something that happens by accident.

### 3.2 The objective — net bps/trade is not the exit criterion

PLAN.md's exit criterion is "controlled max DD and non-pathological trade rate", which is a
*different* objective from the bps/trade every M2 table reports. With ~5% of bars in-regime
the trade rate collapses and the equity curve gets lumpy: a policy can win on bps/trade and
still be untradeable. Decide up front whether M3 optimises net PnL, drawdown-adjusted PnL,
or PnL subject to a drawdown constraint — and score every candidate on all three.

### 3.3 🔴 The fee assumption may dominate every modelling decision

At taker (14bps) the whole cov05 slice is **−5.09** net and only the top 1–2% clears. At
maker (5bps) it is **+3.91**. In-regime at cov05 it is **+21.5** at taker. So the regime
condition is what makes taker viable — and conversely, *whether maker fills are actually
obtainable at 5bps for these pairs and sizes* is currently an **untested assumption that
silently underwrites half the published economics.**

**Measure it early.** Quoted vs filled, queue position, adverse selection on the fills you do
get — this is cheap and could reorder the entire milestone. Do not let it stay an assumption
until after a policy is built on it.

🔴 **Corrected 2026-08-27 — measure it offline, not on the paper-sim stack.** This section used
to say "a short live study on the paper-sim stack". That is not viable: `Trading.Executor` cannot
place a limit order at all (§0.5.4), so there is nothing to measure the fills *of*. The stored
5-second L2 ladders and trade aggregates answer the same question with no orders and no new
infrastructure. **§2 M3-4 is the step**, and it is the next thing to do.

### 3.4 Sizing needs a distribution — and there is a deferred branch waiting here

`docs/QUANT_AB_HANDOFF.md` closed the quantile head with an explicit **"defer, don't
discard"**: what it disproved is that a quantile head *sharing the directional trunk* pays
for itself (it steals encoder capacity and dents direction even at weight 0.2). It did not
disprove that quantiles are informative — the head calibrated fine.

Its stated condition for revisiting was "a healthy direction signal to size". That condition
is now **met** (§1.3 is banked, and the book-era collapse that handoff worried about was
later traced to the 2026-08-17 normalization bug plus a window far too short to read).

So M3 is precisely where that branch fires — but take it in the handoff's own order,
cheapest first:

1. **An analytic vol proxy** (realized vol / ATR-style bands) as the day-one risk context.
   The handoff's own advice: the policy may not need a *learned* distribution at all.
2. A **detached** quantile head (stop-gradient into the shared encoder) — the direct test of
   the capacity-theft failure mode — only if the analytic proxy is the binding limit.
3. A **standalone risk model** only if 2 justifies the infrastructure.

⚠️ `QUANT_AB_HANDOFF.md` is otherwise **stale** in its premises (its "Task 1 / book-era
collapse" framing was superseded). Read it for the quantile decision and its rationale only.

---

## §4 — RISKS, RANKED

| # | risk | why it is ranked here | mitigation |
|---|---|---|---|
| 1 | **Overfitting the policy to 3,717 trades** | seconds per configuration, ≈9.5bps quintile SEM, and five interacting knobs | M3-1's pre-registered protocol, scored on the **worst** window. 🔴 **M3-3 measured this risk rather than reasoning about it:** fitting nine observations on ~188 independent trading days produced a policy that loses to a fit on one of them (M3_3_RESULTS §D2). The mitigation worked — the leave-one-window-out refit is what made the overfit visible instead of publishable |
| 2 | 🔴 **BOTH execution-cost assumptions are untested** (§3.3, §0.7) — **the top open item** | 14-vs-5 is the difference between −5.09 and +3.91 at cov05 — it can invert conclusions already published. 🔴 **Widened 2026-08-28:** the audit shows the *taker* 14 is the likelier large error, and it is wrong in the direction that makes published results too pessimistic | **M3-4**, pre-registered in [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) — measure both arms **offline** from the stored ladders and tape (§2 M3-4), walking slippage from the book rather than assuming 3 bps/side. 🔴 Corrected 2026-08-27: the earlier mitigation said "on the paper-sim stack", but `Trading.Executor` cannot place a limit order, so there would be nothing to measure |
| 2b | 🟡 **The tape the study reads is right-censored** — new 2026-08-28 | `agg_trades(limit: 200)` drops the oldest trades in 30.6% of BTC's poll windows, concentrated in the busy ones where fills happen | Protocol §0.2 arranges every approximation to bias **against** maker, so a maker verdict is safe and a null one is inconclusive. Fixing it forward (raise the limit, or use the uncapped WebSocket tape) is a collector change worth doing regardless |
| 3 | **The regime rule is not uniform in time** | fails in window 2, where 47% of its trades live (§1.8) | never report pooled; require it to survive walk-forward. **M3-3 found the more general version of this**: the mean edge in the top decile swings 25.9 bps across the four windows, so any *level* is unstable and only *orderings* survive |
| 4 | **Sample size is the binding constraint** | ~3,700 cov05 trades is thin for a policy search, and the honest count is ~220 independent trading days, not the trade count | 🔴 **Escalated 2026-08-27 — §5's "free power" is now known to be mostly illusory.** Extra pairs add trades *inside existing exit-day clusters*, so the clustered se widened 20.5 → 23.2 when the universe was widened: more trades, not more independent days. **M3-3 is what this risk looks like when it binds**, and neither more pairs nor any rearrangement of the same 253 days relieves it — **only forward time does** |
| 7 | 🔴 **The policy is not connected to anything** — new 2026-08-27 | the milestone's output currently lives only in `ml/train/m3/`; the live executor has no fees, no limit orders, no fill logic and no hold timer, so §6's last exit criterion cannot even be tested | **M3-5** (§2). It is sequenced after M3-4 because the fee measurement decides what the order path should do, and building it twice is the expensive mistake |
| 5 | **Calibration drift on a future checkpoint** | policy consumes `p_up`; three levers have already broken the scale | rank-based conditioning (§1.3.3); re-check brier on any new checkpoint |
| ~~6~~ | ~~**The Q1 harness is unrecoverable / mis-rebuilt**~~ | ✅ **closed 2026-08-26** — rebuilt as `ml/train/m3/regime.py` and pinned by an acceptance test that reproduces §1.8's ladder (§1.4, §0.0) | — |

---

## §5 — SAMPLE SIZE: THE 12-PAIR DUMP IS NOT THE FREE POWER IT LOOKED LIKE

🔴 **Rewritten 2026-08-27, after the T-wave.** This section used to argue that the 12-pair
dumps were "free power" against risk #4 — four more instruments, ~50% more trades to search a
policy on, at unchanged measured edge, for no GPU. Three seeds of evidence now say the power
is largely fake, and the reason is worth understanding rather than just recording.

**More trades are not more information here.** The extra pairs trade the *same market moments*
as the existing ones — crypto majors and mid-caps are highly correlated, and the policy gates
on a BTC-derived regime column, so it fires across the universe at once. M3's clustering is on
the exit calendar day precisely to catch this, and it did: widening 8 → 12 pairs took the
pooled trade count from 1,645 to 2,475 while the clustered standard error **widened** from
20.5 to 23.2 bps and max drawdown grew from −2.83 to −4.53. Independent days went from 169 to
187 — an 11% gain in what actually counts, for a 50% gain in what looks like it counts.

🟢 **T6 turned this into a number that ends the argument.** The cluster-robust SE on the
8-vs-12 *difference* is 13.2 bps over ~180 exit days, so the comparison resolves **±37 bps at
80% power**. Any effect worth adopting is far smaller than that, which is why the universe
question closed as undecidable rather than as decided ([T6_RESULTS.md](./T6_RESULTS.md)).

**What remains true:** the dumps are real, they cost no GPU, and the harness reads them
(`reaggregate_preds.py` was validated against O8, reproducing its fixed-coverage table to the
digit — NEXT_TRAINING_PLAN §7). Using them as a **replication check across instruments** is
legitimate and is what M3_PROTOCOL §1 already does with O8. Using them as **added statistical
power for a policy search** is not, and any future analysis that pools them should report the
cluster count, not the trade count.

**The three T-wave dumps** are `20260822T012619Z` (O8), `20260827T050701Z` (T1) and
`20260827T114122Z` (T2), all present under `ml/train/output/eval_dumps/`.

🟢 **The only thing that relieves risk #4 is forward time.** That is not a defeat — it is the
argument for M3-5 and for starting the paper-trading clock, since every day served is an
independent day that no re-slicing of the existing 253 can manufacture.

---

## §6 — EXIT CRITERIA

From PLAN.md, sharpened with what M2 measured:

- [x] The backtester reproduces §1.3's fixed-coverage table to the digit under a trivial
      fixed-hold policy (M3-0a acceptance test) — **done 2026-08-26, 15/15 cells** (§0.0).
- [x] The rebuilt regime harness reproduces §1.8's published quintile ladder (§1.4) —
      **done 2026-08-26** (§0.0).
- [x] The evaluation protocol is pre-registered and committed before any search ran (M3-1) —
      **done 2026-08-27**, [M3_PROTOCOL.md](./M3_PROTOCOL.md).
- [x] A rules baseline (M3-2) clears the pre-registered Tier-1 bar — in particular
      **worst-window net at taker ≥ −5 bps**, not just a positive pooled number
      (M3_PROTOCOL §4.2) — **done 2026-08-27**, [M3_2_RESULTS.md](./M3_2_RESULTS.md).
      1 of 36 grid configs passes (`cov0.02_hold240_rqnone_mcnone`, worst window −3.56),
      and so does the §3.2 sizing variant (worst window +0.25), which outranks it.
- [x] Any learned policy beats that baseline on the pre-registered rule, judged on the worst
      window — **answered 2026-08-27, and the answer is no** ([M3_3_RESULTS.md](./M3_3_RESULTS.md)).
      0 of 8 learned configurations pass Tier 1; the best reaches −7.18 worst-window against
      the baseline's +0.25, and the confidence-only ablation beats both fitted models in
      three of four rule pairings. M3_3_PROTOCOL §7 pre-registered this as a result: **the
      M3-2 rule stands as M3's policy.** The criterion is closed, not outstanding.
- [x] Max drawdown is controlled and the trade rate is non-pathological (PLAN.md) — the
      M3-2 winner runs 2.34 trades/day/seed at a −4.59 max drawdown; rule P6 makes the trade
      rate a promotion criterion and every table reports the drawdown next to it.
- [x] Long and short sides are reported separately — every table in
      [M3_2_RESULTS.md](./M3_2_RESULTS.md) §G breaks them out (the winner is +18.1 long /
      +2.7 short at taker, i.e. the long side carries it, which is why §3.3 forbids
      selecting on the split).
- [ ] **The maker-fee assumption is measured rather than assumed** (M3-4) — the realized
      effective round-trip cost per pair is published, and the M3-2 grid is re-scored at it.
      Added as an explicit criterion 2026-08-27: half the published economics rests on the
      5-bps number, and the milestone should not close with it untested (risk #2, §3.3).
- [ ] The policy never bypasses the hard `RiskManager` limits — **blocked on M3-5**, because
      nothing currently calls the policy at all. `Trading.Executor` is an 86-line stub with no
      fees, no limit orders, no fill logic and no hold timer (§2 M3-5).
- [ ] **The signal-only vs signal+policy A/B runs in paper simulation** (PLAN.md's M3 row,
      never yet started; M3-5). This is also the only mechanism that produces *new* independent
      trading days, which risk #4 identifies as the binding constraint on certifying the edge.

---

## §7 — WHAT TO BRING BACK (for the next session)

*Results are deliberately analyzed in a fresh session for token hygiene, so a step is not
finished until the artifacts below exist.*

**M3-0a is done** — its artifacts are in the repository and its numbers are in §0.0. Nothing
to fetch. The dumps are already in `ml/train/output/eval_dumps/` and §0.0 carries the
re-fetch command if that directory is ever empty.

Any session that changes the harness must re-run and bring back:

```sh
./scripts/m3.sh -m m3 validate
```

If either test stops passing, **that is the only finding that matters** — stop and fix it
before touching a policy number.

**M3-1 is done** — the artifact is [M3_PROTOCOL.md](./M3_PROTOCOL.md) and every fact it
quotes is reproducible with `./scripts/m3.sh -m m3 power`. Nothing to fetch.

**M3-2 is done** — the artifact is [M3_2_RESULTS.md](./M3_2_RESULTS.md), regenerated in
one command and never hand-edited:

```sh
./scripts/m3.sh -m m3 validate
./scripts/m3.sh -m m3 search
cp ml/train/output/m3/M3_2_RESULTS.md docs/M3_2_RESULTS.md
```

⚠️ The protocol is **still frozen**. M3_PROTOCOL §0 applies to everything downstream: an
observation that a different metric would have been better goes into a *future*
pre-registration, never into a re-scoring of this run. Two such observations are already
logged in M3-2's write-up and must be treated that way — the per-notional normalisation of
the sizing variant (§D1), and the fact that §3.2/§4.2 do not say whether an addition may win
the §4.2 ranking (§A reports both readings rather than choosing one after the fact).

**M3-3 is done** — the artifacts are [M3_3_PROTOCOL.md](./M3_3_PROTOCOL.md) (frozen, written
before the first fit) and [M3_3_RESULTS.md](./M3_3_RESULTS.md), regenerated in one command and
never hand-edited:

```sh
./scripts/m3.sh -m m3 validate
./scripts/m3.sh -m m3 learn
cp ml/train/output/m3/M3_3_RESULTS.md docs/M3_3_RESULTS.md
```

⚠️ **Both protocols stay frozen.** M3_3_PROTOCOL §7.1 logged three proposals for a future
pre-registration *before* the run — window-equalised fitting weights, per-notional
normalisation of a size-varying policy, and whether the per-window coverage cut should also be
the baseline's rule. They are proposals for a *next* pre-registration, never a re-scoring of
this one.

**M3-4a is done** — the artifacts are [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) (frozen, written
before any fill number), `scripts/gcp_m3_export.sh`, and the `bookprep` subcommand. Every fact
the protocol rests on is reproducible with:

```sh
./scripts/gcp_m3_export.sh            # pulls book/tape/candles/funding off the VM (~2h, ~300MB)
./scripts/m3.sh -m m3 bookprep        # the audit tables — no fill number, by design
```

**The next step is M3-4 itself, and what to bring back from it** is not a table from this
harness. It is a measurement — made **offline from the stored ladders and trade aggregates,
not on the live paper-sim stack** (which cannot place a limit order; §0.5.4) — of both
execution arms: what crossing actually costs, and what resting actually gets. Two prerequisites
and one artifact:

```sh
./scripts/gcp_m3_export.sh            # 20 ladder levels by default — protocol §2.5 walks them
./scripts/m3.sh -m m3 validate        # the harness is unchanged and trustworthy
./scripts/m3.sh -m m3 fills           # (to be added next to `search` / `learn` / `bookprep`)
cp ml/train/output/m3/M3_4_RESULTS.md docs/M3_4_RESULTS.md
```

⚠️ **The export takes ~3–4 hours and killing it locally does not stop it.** `\copy … TO
PROGRAM` writes inside the postgres container, so psql outlives the ssh channel and keeps
going. After an interruption, check what is staged
(`docker compose exec -T postgres ls -l /tmp/m3_export` on the VM), wait for the COPY backend
to disappear from `pg_stat_activity`, and then **collect rather than re-run**:

```sh
COLLECT=1 ONLY=book_top20 ./scripts/gcp_m3_export.sh                   # fetch the finished ladder
ONLY=snapshots,trades,candles_5m,funding ./scripts/gcp_m3_export.sh    # the four cheap slices
```

Every download is checked with `gzip -t`, because an interrupted COPY leaves a plausible-looking
`.gz` with a truncated last member — and `bookprep` caches a parquet on first read, so a
truncated export would be silently baked into every table.

`docs/M3_4_RESULTS.md` must carry the **eight panels protocol §6 fixes** — per-pair effective
round-trip cost for **both** arms next to the assumed 5 and 14; Q1 and Q2 with intervals **and
their MDEs**; fill rates split by censoring and by fill branch; the adverse-selection panel;
L1/L2/L3 side by side; the ladder-exhaustion rates; the exclusion counts; and **the M3-2 grid
re-scored at the measured cost**, which is the deliverable that changes what happens next.

🔴 **The question is no longer "is a 5-bps round trip obtainable".** §0.7 shows it is not — the
touch spread caps the maker gain near 4 bps round trip on the majors. The question is now
**two-sided**, and the taker side is the one more likely to move a published number: if the
measured cost of crossing is ~8 bps rather than the assumed 14, M3-2's economics are better
than published and M3-5 can be built without limit orders at all.

⚠️ **And it may not be answerable yet.** 22 day-clusters against a ~4 bps effect is thin;
protocol §5.3 requires the MDE before either verdict may be applied, and pre-commits to
reporting *"22 days cannot resolve this"* rather than a point estimate if it cannot. The ladder
grows a day per day at no cost — that is the remedy, not a bigger model.

---

*Updated: 2026-08-28 — M3-0a, M3-1, M3-2, M3-3 and **M3-4a** complete. The learned policy did
not beat the rules baseline, so M3-2's rule is M3's policy. M3-4a's audit found the touch
spread to be ~0.01 bps on the majors, which kills the "maker roughly doubles it" hope and
raises a better one: the 14-bps taker assumption looks ~6 bps too pessimistic (§0.7). Three
items remain, in order: **M3-4** (run the pre-registered study — next), **M3-0b** (the
price/funding side-table), and
**M3-5** (wiring the rule to the executor, which is what starts producing new independent
trading days). Both existing protocols stay frozen. §0.0 is the live status block and the only
place that needs reading to resume; **§0.5 is the same thing in plain language, with the
vocabulary defined and the "can it trade profitably yet?" question answered directly.***
