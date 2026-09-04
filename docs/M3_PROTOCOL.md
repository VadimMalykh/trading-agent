# M3-1 — The pre-registered evaluation protocol

**Status:** ✅ **COMMITTED 2026-08-27, before any policy search was run.**
**Applies to:** M3-2 (the rules baseline) and M3-3 (the learned policy).
**Related:** [M3_PLAN.md](./M3_PLAN.md) §M3-1 (why this file exists) · §1.3 (the constraints) · §4 (risk #1)

---

## §0 — What this document is, and the one rule that makes it worth anything

This is a **pre-registration**: the split, the metric, the decision rule and the exact list
of configurations that will be tried, all written down and committed **before** the first
search was run. No policy result existed when this file was written. The only numbers in it
are sample sizes, calendar spans, and a standard-error calibration on a table M2 already
published — never a candidate policy's P&L.

**The rule: this file is not edited after the search begins.** If M3-2's results suggest a
different metric would have been better, that observation goes in M3-2's write-up as a
*proposal for a future pre-registration*, and the original decision still stands for the
run that was made. Amending a protocol after seeing the results is how a search over 36
configurations turns into a result that does not replicate — which M3_PLAN §4 ranks as risk
#1 for this whole milestone, and §0.4 names as the thing that ends M3 badly.

Everything below is reproducible in a clean session with one command:

```sh
./scripts/m3.sh -m m3 validate     # the harness is trustworthy (must pass first)
./scripts/m3.sh -m m3 power        # every fact quoted in §2 and §3
```

---

## §1 — THE SPLIT

**Population.** The three banked 5m/seq384 seeds (`20260818T185438Z`, `20260819T142759Z`,
`20260820T025723Z`) over the eight-pair BASE8 universe, pooled by concatenation with the
seed carried as a key. Seed 2 is the served checkpoint, so a policy that is ever deployed is
deployed on seed 2; seeds 1 and 3 exist to show the choice was not seed luck.

**Splits are the four calendar windows** of NEXT_TRAINING_PLAN §1.2, already coded as
`dumps.WINDOWS`. They are **not equal**, and two are truncated by where the dump starts and
ends — this is a fact about the evidence, not a rounding detail:

| window | nominal range | bars (3 seeds) | actual span | truncated? |
|---|---|---:|---:|---|
| w1 | 2025-12-01 → 2026-02-01 | 366,418 | 53.6d | **yes** — dump starts 2025-12-09 |
| w2 | 2026-02-01 → 2026-04-01 | 407,808 | 59.0d | no |
| w3 | 2026-04-01 → 2026-06-01 | 421,632 | 61.0d | no |
| w4 | 2026-06-01 → 2026-10-01 | 542,616 | 79.1d | **yes** — dump ends 2026-08-19 |

**There is no held-out time period, and pretending otherwise would be the dishonest move.**
All four windows are used for selection. What stands in for a hold-out is:

1. **Per-seed replication** — three independently initialised models over the same window.
   This is replication across *model*, not across *time*.
2. **O8's 12-pair dump** (`20260822T012619Z`) — replication across *instruments*. It is
   **excluded from the search population** and the selected policy is re-run on it once,
   reported, and never selected on. Same calendar period, so it is not out-of-sample in time.
3. **Forward paper-sim** — the only genuine out-of-time evidence available, and it does not
   exist yet. §6 says why this matters more than it looks.

---

## §2 — WHAT THE SAMPLE CAN AND CANNOT SUPPORT

Read this before reading any result, including your own.

**Per-trade standard deviation is 258.6 bps** against an effect measured in tens of bps. The
signal-to-noise here is brutal, and the naive standard error makes it look far better than
it is.

**The pooled trade count is not the sample size.** Clustering the cov05 slice on the exit
calendar day — every trade closing on the same day, any seed, any pair, is one cluster —
gives 220 clusters behind 3,718 trades, and a standard error **2.35× the iid one**:

| §1.3's published cov05 slice | mean | iid SE | clustered SE | 95% CI (clustered) |
|---|---:|---:|---:|---|
| gross | +8.91 | 4.24 | **9.97** | **[−10.63, +28.45]** |
| net @ taker 14bps | −5.09 | 4.24 | **9.97** | **[−24.63, +14.45]** |

Two structural dependencies cause this, and both are made *worse*, not better, by the regime
policy: three seeds gating the same bar are three views of one market moment, and a 4h hold
across eight correlated perpetuals during one BTC move is one bet expressed eight times. The
regime rule deliberately concentrates entries into exactly such moves.

**The consequence, stated plainly: this dataset cannot certify a policy at taker fees.** An
8-month window holding ~220 independent trading days does not contain enough information to
prove a 15-bps-per-trade edge net of a 14-bps round trip. §4 is built around that fact
instead of around a hope that a tighter metric will dissolve it.

---

## §3 — THE SEARCH SPACE: EXACTLY WHAT WILL BE RUN

**40 scored runs in total.** The list is code, not prose — `cli.primary_grid()` generates it
in a fixed order, so a later session re-derives it rather than trusting this paragraph.

### 3.1 The primary grid — 36 configurations

| knob | values | why these |
|---|---|---|
| `coverage` | 0.01, 0.02, 0.05 | §1.3.1: coverage is a first-class decision variable. 0.10/0.20 are excluded — they are 0.0 to +1.9 gross, dead before fees |
| `hold_horizon` | 60, 240, 1440 | the only exits the dump can honestly book (M3_PLAN §M3-0a constraint 1) |
| `regime_quantile` | none, 0.80 | the §1.8 finding, as a hard filter, with the threshold re-derived per seed as a quantile of **bars** |
| `max_concurrent` | none, 3 | unbounded is not a tradeable portfolio; 3 is the cap the §0.0 first-look used |

`signal_horizon` is fixed at 240 (the optimised and served primary). `sides` is fixed at
`both`.

### 3.2 The three additions — 4 more runs

- **1 sizing variant.** The primary winner re-run with `size_by_regime` and the hard regime
  filter **off** — size scaled 1/3…5/3 by the bar-quintile of `btc_absret_1d`. This is the
  soft version of the regime idea: trade small out-of-regime instead of not at all. It is
  *not* in the grid because combined with a hard `regime_quantile=0.8` filter every
  surviving trade is already in bucket 5 and sizing degenerates to a flat 5/3.
- **2 baselines**, which the winner must beat:
  - **buy-and-hold**, equal-weight across BASE8, per window;
  - **a momentum-side control** — the winner's own entry bars, but with the side taken from
    `sign(trailing 240m return)` instead of from the model. This isolates the one question
    that matters: is the model's *side* worth anything over a trivial one? (§M3-1 records
    trailing-48-bar momentum at dir_acc 0.469, i.e. mildly anti-predictive.)
- **1 O8 replication.** The winner, re-run once on the 12-pair dump. Reported, never selected on.

### 3.3 What is reported but never selected on

**Long/short split.** §1.3 records that side balance is not seed-stable (seed 3's short side
is a coin flip). Every table breaks the sides out, but choosing a side on the strength of
four windows would be fitting the noisiest thing in the dataset. If one side looks better,
that is a hypothesis for a future pre-registration, not a knob to turn now.

---

## §4 — THE DECISION RULE

### 4.1 Eligibility, fixed in advance (rule P4)

A configuration is **eligible for promotion only if every one of the four windows holds
≥ 100 pooled trades.** Below that a window's mean is noise: at 23 trades the clustered
standard error exceeds 50 bps, and a "worst window" computed from it measures nothing.

This rule is deliberately fixed **from trade counts alone, before any P&L was computed**, and
it prunes hard. `m3 power` prints the full table; the outcome is **16 of 36 eligible**:

- every `cov0.05` config except the two `hold1440 + rq0.8` ones (w3 = 83 / 79);
- the four ungated `cov0.02` configs at `hold60` and `hold240`;
- the two ungated `cov0.01 hold60` configs.

**All in-regime configs below cov0.05 are ineligible**, because w3 starves: the top-quintile
filter leaves only 23–87 trades there. That is not a defect in the rule, it is the rule
catching the thing §1.8's caveat warned about — the regime fires very unevenly across time.
The ineligible 20 are still scored and reported; they simply cannot win.

### 4.2 The promotion bar (Tier 1) — all six must hold

Selection is at **taker (14 bps)**, the conservative assumption. Maker is always reported
alongside, never selected on, because §3.3 of the plan flags the maker assumption as
untested.

| # | criterion |
|---|---|
| P1 | pooled net at taker **> 0** |
| P2 | net at taker **> 0 in ≥ 3 of the 4 windows** |
| P3 | **worst-window net at taker ≥ −5 bps** |
| P4 | every window holds **≥ 100 pooled trades** (§4.1) |
| P5 | **all three seeds individually** pooled-positive at taker |
| P6 | trade rate **≥ 0.5 trades/day/seed**, and max drawdown reported |

Among configurations that pass all six, **rank by worst-window net at taker**; ties broken by
pooled net at taker.

**Why P3 tolerates −5 rather than demanding > 0 in every window.** Demanding a positive point
estimate in all four windows, on samples of 100–1,000 trades with a 259-bps per-trade
spread, selects for luck rather than for robustness. What we actually want is *no window
loses badly*, and −5 bps — about a third of the taker round trip — is where that line is
drawn. It is a judgement call, and it is being made now, in the open, rather than after
seeing which configurations it admits.

**This bar is not a formality: the incumbent fails it.** The candidate M3_PLAN §0.0 flags
from M3-0a — cov05 + top-quintile regime + max 3 concurrent — is +18.5 / **−13.7** / +39.9 /
+73.3 net at taker per window. It passes P1, P2, P4 and P6, and it **fails P3 at −13.7**.
That is the intended behaviour: the pooled +16.04 looks like a strategy, and the window that
holds 47% of its trades loses money.

### 4.3 The certification bar (Tier 2) — reported, expected to fail

For the Tier-1 winner only: **is the clustered 95% lower bound of pooled net at taker > 0?**

§2 says the answer is almost certainly no, for every candidate. **That is a pre-registered
expectation, not a failure of the search**, and it must not be used to argue the metric is
wrong. Its purpose is to keep the distinction visible between *"the best rule this evidence
supports"* (Tier 1 — enough to be M3-3's benchmark and to justify paper trading) and
*"a rule proven to make money"* (Tier 2 — which this dataset cannot deliver at any setting).

### 4.4 M3-3's bar

A learned policy is promoted over the M3-2 winner only if it passes all of Tier 1 **and**
beats the winner on worst-window net at taker. Re-run `m3 validate` first; a learned policy
compared against a baseline computed by a changed harness is not a comparison.

---

## §5 — WHAT EVERY RESULT MUST REPORT

Pooled-only numbers are not a result. For each configuration:

- net bps/trade at **both** 5 bps and 14 bps;
- **per calendar window**, with the worst window called out;
- **per seed**, so P5 is checkable;
- trades, trades/day/seed, max drawdown, daily Sharpe;
- long/short split (§3.3);
- for the winner: the clustered SE and 95% CI (Tier 2), and the O8 replication.

---

## §6 — WHAT HAPPENS IF NOTHING PASSES

Pre-registered, so that it cannot later be argued away:

**If no configuration clears Tier 1, that is M3-2's result and it gets written up as one.**
The protocol is not loosened, the grid is not widened, and a 37th configuration is not tried.

The next step in that case is **not** a better policy search — it is the two things that
would change the evidence rather than re-slice it:

1. **The maker-fee study (M3_PLAN §3.3).** At cov05 the same slice is +3.91 at maker and
   −5.09 at taker. Whether 5-bps fills are actually obtainable for these pairs and sizes is
   currently an untested assumption underwriting half the published economics. It is ranked
   risk #2 and is measurable cheaply on the paper-sim stack.
2. **M3-0b's price/funding side-table**, which unlocks barrier exits and the funding term —
   i.e. genuinely new degrees of freedom, rather than new combinations of the four we have.

A negative M3-2 would be a real finding: it would say the M2 signal is not tradeable at
taker fees on a fixed-hold policy, and would redirect the milestone toward execution cost
and exit machinery instead of toward more knobs.

---

## §7 — AMENDMENTS

Every amendment must be dated, must state what was known at the time it was made, and must
say explicitly whether any search output had been seen.

| # | date | what it changes | search output seen when written? |
|---|---|---|---|
| 1 | 2026-09-01 | Adds §8: an exploratory lane, and a standing champion–challenger promotion rule. **Governance only — changes no bar and no completed verdict.** | 🔴 **YES, extensively** |
| 2 | 2026-09-04 | Adds §9: answers §8.6 (Amendment 1 is now **in force**), the data-correction clause, the standing confirmatory dataset (walk-forward folds), the ranking axis for *future* protocols, the checkpoint-binding guard, and the forward ledger's persistence across swaps. **Governance and data sources only — lowers no bar; the re-executed M3-2/M3-3 verdicts of §9.2 are the same rule on corrected data.** | 🔴 **YES** — including the repaired-data re-score |

---

## §8 — AMENDMENT 1, 2026-09-01: the two lanes, and the standing promotion rule

### 8.0 🔴 Disclosure, first, because §7 requires it

**Search output had been seen when this was written — a great deal of it.** M3-2 and M3-3 are
complete, all 40 runs are scored, T6 and the B-wave have reported, and the forward test is
deployed. This amendment is therefore written by someone who knows the answers.

**What follows from that, and it is the whole safeguard:**

1. 🔴 **This amendment is PROSPECTIVE ONLY. It cannot and does not alter any completed
   verdict.** M3-2's winner, M3-3's rejection of the learned policy, Tier 1, Tier 2, and every
   number in §§1–6 stand exactly as they were. Nothing here re-opens them.
2. 🔴 **It lowers no bar.** Tier 1's six criteria are reproduced by reference, unchanged. If
   anything below appears to relax a threshold, the threshold wins and this section is wrong.
3. It changes **who may look at what, and when** — governance — not **what counts as a pass**.

**What was known and prompted it (2026-09-01):** the frozen cut has not been exceeded since
2026-06-29, ~64 days, longer than the 252-day split's worst dry spell; the collapse is present
in all six checkpoints and is not a serve defect; and the forward test therefore cannot be
costed in calendar terms. See BACKLOG.md, "The arrival-rate finding".

### 8.1 The problem this fixes

The protocol bans one narrow thing — re-choosing a knob after seeing its result and reporting
the outcome as if it had been chosen in advance. **In practice it has come to gate everything**,
because there is only one lane, so every idea must enter through the confirmatory door. As of
2026-09-01 the queue reads: B3 blocked, the served-coverage re-registration blocked, the 240m
book-feature question blocked — all of them "pending someone writes a pre-registration first."

That is an activation barrier, not a safeguard. A rule that makes exploration cost a committed
document produces less thinking, not more rigour.

### 8.2 Two lanes

**EXPLORATORY.** No pre-registration. Look at anything, as often as you like, on any slice.
Three requirements, all cheap:

* its output says **`EXPLORATORY`** on it;
* it is **never cited in a promotion argument**, in any document, in any form;
* its conclusions are recorded as *"a reason to run a confirmatory test"*, never as findings.

**CONFIRMATORY.** Exactly as today: written before it runs, run once, reported whatever it says.

🔴 **The bright line, and the only thing that makes the loosening safe: a number produced in
the exploratory lane may never appear in a promotion argument.** To promote on an exploratory
result you must re-establish it confirmatorily **on data the exploration did not touch.**

⚠️ **This is expensive here and pretending otherwise would defeat the purpose.** The 253-day
split has been looked at repeatedly; it is not untouched data for almost any question. The one
genuinely untouched source is **forward time** — which is precisely the resource §2 says is
binding. So the honest reading of this lane split is: *explore freely, and expect the
confirmatory step to wait on forward data.* It buys thinking speed, not promotion speed.

### 8.3 The standing promotion rule (champion–challenger)

**Registered once, here, applying to every future challenger.** This is what removes the need
for a fresh pre-registration per retrain: the criterion is fixed **before any challenger
exists**, which is what pre-registration was ever protecting.

A challenger checkpoint or policy replaces the incumbent **only if all of the following hold**:

| # | criterion |
|---|---|
| C1 | it passes **all six Tier-1 criteria (§4.2)** on its own split, unchanged |
| C2 | it beats the incumbent on **worst-window net at taker** (§4.4's axis) |
| C3 | `./scripts/m3.sh -m m3 validate` passes **first** — a challenger scored by a changed harness is not a comparison (§4.4) |
| C4 | the served constants — coverage cut **and** regime ladder — are **re-derived from the challenger's own split**, never inherited |
| C5 | the checkpoint-binding guard (§8.4) is in place, so the swap cannot silently serve mismatched constants |

**C4 is not a formality — it is the 2026-08-31 defect promoted to a rule.** Serving one
checkpoint's cut against another checkpoint's model is exactly what
[M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) records: O8's 12-pair cut realised 4.01%
coverage on the served checkpoint against a searched 2%. **A cut belongs to a checkpoint first,
a universe second.**

🔴 **A single-seed win does not satisfy C2.** At a 259-bps per-trade spread and ±37 bps
resolution (§2), one seed beating one seed is indistinguishable from luck — T2 is the worked
example: +4.91 net bps on 8 pairs, −2.70 on 12, cluster-robust CI **[−37.3, +31.9]**. A
challenger is a **family of ≥ 3 seeds**, and C2 is evaluated on the family's **median** seed
against the incumbent family's median. This mirrors P5, which already refuses to let one seed
carry a result.

### 8.4 Operational preconditions — this rule cannot be used until both exist

1. 🔴 **The checkpoint-binding guard.** The served cut and ladder are currently not tied to the
   checkpoint in code; swapping `m2_multi.pt` silently invalidates both and **nothing fails**
   (M3_FIDELITY_RESULTS §6.5, and the backlog row). Until a mismatch refuses to serve — loudly,
   at boot — "swap the model on the go" is unsafe regardless of what this protocol permits.
   **This, not the protocol, is what blocks fast iteration today.**
2. ⚠️ **A swap restarts the forward clock.** A new checkpoint with new constants is a different
   rule, so the A/B spans two policies from that moment (M3_4_PROTOCOL §7). Promotion is
   therefore never free, and the cost must be stated in the promotion record.

### 8.5 What this amendment deliberately does NOT do

* It does **not** authorise re-picking a searched dimension after seeing results. §0 stands in
  full. The served-coverage question remains blocked and still needs its own registration.
* It does **not** lower Tier 1 or retire Tier 2. §4.3's expectation — that this dataset cannot
  certify a policy at taker fees — is unchanged and is not repaired by iterating faster.
* It does **not** make a challenger's existence evidence that the incumbent is stale.
* 🔴 It does **not** solve the current problem. A promotion pipeline needs a challenger that is
  actually better; today's evidence is that **every** checkpoint went quiet in the same regime
  at the same time. Faster iteration lets you respond once you have something to promote — it
  does not produce the something.

### 8.6 🔴 Open — three decisions this amendment does not make

**It is not in force until these are answered**, because each changes what the rule means.

**Q1. Must a challenger show FORWARD evidence, or is backtest Tier-1 plus beating the incumbent
enough?** — (a) backtest only: fast, and repeats the mistake of promoting on a window that the
2026-06-29 collapse shows can go stale; (b) require N forward trading days: safe, but the
arrival-rate finding says N may never arrive; (c) backtest to promote, forward to *keep* — swap
on backtest evidence, then revert automatically if forward performance fails a stated bar.
**(c) is the recommendation**, since it is the only option that stays live in a regime where
forward data is scarce.

**Q2. What margin must C2 clear?** — a bare `>` is noise at this signal-to-noise ratio, and §8.3
already requires a median-of-family comparison rather than a single seed. Options: (a) any
positive margin on the family median, (b) a margin exceeding the between-seed spread, (c) a
margin plus a win on ≥ 2 of {worst-window, pooled, trade rate}. **(b) or (c) recommended; (a) is
too weak to mean anything.**

**Q3. Retrain on a cadence or on a trigger?** — (a) fixed schedule (e.g. monthly), (b) triggered
by a stated staleness signal, such as the served checkpoint going N days without exceeding its
own cut — which is measurable **today** and is exactly the condition now in force. **(b) is the
recommendation**; it is the one that would have fired in July.


---

## §9 — AMENDMENT 2, 2026-09-04: Amendment 1 in force, the data-correction clause, and the confirmatory dataset

### 9.0 🔴 Disclosure

**Search output had been seen when this was written**, including the repaired-data re-execution
of M3-2 and M3-3 (§9.2) that this amendment makes the verdict of record. The same safeguard as
§8.0 applies: nothing here re-chooses a searched dimension, lowers a Tier-1 criterion, or retires
Tier 2. Where it changes how *future* protocols rank (§9.4), that rule binds only protocols
registered after this date and never re-reads a completed one. The review that produced it,
with the reasoning in full, is [RULES_REVIEW.md](./RULES_REVIEW.md).

### 9.1 §8.6 answered — Amendment 1 is in force

Decided 2026-09-04 by Vadim, against the options §8.6 listed:

| | decision | consequence |
|---|---|---|
| **Q1** | **(c) promote on backtest, keep on forward.** A challenger is swapped in on C1–C5. It is **reverted automatically** if its forward ledger, on its own rows, fails a stated bar: pooled net at taker below zero **and** its day-clustered upper bound below the incumbent family's pooled backtest net, evaluated once the challenger holds ≥ 60 forward exit-day clusters. Fewer clusters than that is "not yet decidable", not a revert | the champion–challenger rule can be used |
| **Q2** | **(c) margin plus breadth.** C2 is met only if the challenger family's median beats the incumbent family's median on worst-window net at taker by more than the between-seed spread of the incumbent family **and** wins on at least two of {worst-window net, pooled net at taker, trade rate} | a bare `>` never promotes |
| **Q3** | **(b) a staleness trigger.** Retrain when the served checkpoint has gone **N = 65 days** without a served bar meeting its own cut — calibrated as ~1.25× the longest dry spell of the cut in the served checkpoint's own repaired split (51.8 days on seed 2; 24.9 and 12.7 on seeds 1 and 3). ⚠️ One eight-month split is a thin basis for N; it is **re-calibrated from the walk-forward folds** (§9.3) once they exist, and RETRAIN_PLAN §8 Q3's interim quarterly cadence is **superseded** by this. The trigger is measured live: `/api/health` → `policy.retrain_trigger` | a retrain has a defined start condition |

**§8.4's preconditions.** (1) The checkpoint-binding guard is **built** (§9.5) — it ships with this
amendment and is a hard precondition for any swap. (2) A swap no longer restarts the forward
clock by truncation; see §9.6.

### 9.2 The data-correction clause

**When an input defect is found, the pre-registered protocol is re-executed in full on the
corrected data** — every sub-protocol, the full grid, the same bar, the same folds — with
eligibility (P4) recomputed mechanically from the new trade counts before any P&L is read. The
re-executed verdict replaces the original; both are kept; nothing is re-chosen. This is not an
amendment of a protocol, it is running it on the data it was written for. A pre-registration is
a rule about *decisions*, not a warranty on *data*.

**Applied 2026-09-04 to the candle-poll defect** ([CANDLE_POLL_DEFECT.md](./CANDLE_POLL_DEFECT.md)):
`M3_ERA=repaired` `validate` (PASS/PASS) → `power` (16 of 36 eligible, the same sixteen) →
`search` → `learn`. **Verdicts of record:**

* **M3-2:** 1 of 36 primary configurations clears Tier 1, `cov0.02_hold240_rqnone_mcnone`
  (worst −4.98, pooled +7.24); the §3.2 sizing variant also clears and outranks it (worst
  **−4.61** w3, pooled **+13.82**, seeds +8.41 / +11.94 / +21.97, Tier 2 CI [−34.9, +62.6]).
  **The incumbent stands.** [M3_2_RESULTS_REPAIRED.md](./M3_2_RESULTS_REPAIRED.md).
* **M3-3:** 0 of 8 learned configurations pass Tier 1 (best worst-window −6.6); the
  confidence-only ablation beats both fitted models in 3 of 4 pairings, as before.
  [M3_3_RESULTS_REPAIRED.md](./M3_3_RESULTS_REPAIRED.md).
* **§4.4's bar for a learned policy is restated at −4.61 bps** worst-window net at taker.
* **C4:** the served constants are re-derived from the same checkpoint's repaired split —
  cut **0.6296127438545227**, ladder `[0.003956599626690149, 0.00888611190021038,
  0.015089680440723896, 0.025596268475055695]` — reproducing seed 2's arm A exactly (490 trades,
  mean size 1.367). Same checkpoint, same rule, corrected data.

The 2026-08-27 originals ([M3_2_RESULTS.md](./M3_2_RESULTS.md), [M3_3_RESULTS.md](./M3_3_RESULTS.md))
are kept as the record of what the corrupt tail looked like.

### 9.3 The standing confirmatory dataset: walk-forward folds

§8.2 says an exploratory result is promoted only by re-establishing it on data the exploration
did not touch, and names forward time as the only such source. **That is no longer the only
source.** A checkpoint trained with its boundary stepped back in time, scored on the months it
never saw, yields out-of-sample predictions on a period no M3 search has looked at (every M3
number to date was measured on 2025-12 → 2026-09). Those folds are:

1. the **confirmatory dataset** for any exploratory finding — a parked pre-registration
   (served coverage, the 240m book question, a learned policy) is confirmed on the folds;
2. the **certification path for a fresh checkpoint** (RETRAIN_PLAN §8 Q2 (B));
3. the population on which §9.1 Q3's N and §9.4's statistics are calibrated.

The fold design is its own pre-registration, [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md),
committed before any fold is trained. **Rolling fixed-width** train windows, decided 2026-09-04,
so boundary age is the only thing that moves between folds.

### 9.4 The ranking axis for protocols registered after this date

Tier 1 ranks on worst-window net at taker. RETRAIN_PLAN §5.3–5.4 established that a single
window's day-clustered interval on this population is ±50–100 bps against a ~15 bps edge, so
no ordering of four windows is resolvable — and the 2026-09-04 re-score put the incumbent at
−4.61 against a −5 floor, a 0.4-bps margin on a ±50-bps number. **Completed and already-registered
protocols keep their axis; they are not re-read.** Every protocol registered after this date
ranks instead on **the day-clustered 95% lower bound of pooled net at taker**, keeps the
worst-window (or worst-fold) criterion as a **veto only**, and calibrates that veto to the
window's own error: a window vetoes when its clustered *upper* bound is below zero, not when its
point estimate is. WALKFORWARD_PROTOCOL §3 is the first protocol under this rule.

### 9.5 The checkpoint-binding guard (C5) — built

`ml_inference` reports the sha256 of the weights it loaded on `/health` (`checkpoint_sha256`);
`Policy.frozen_checkpoint_sha256/0` names the checkpoint the served cut and ladder belong to;
`PolicyEngine` compares the two every tick and **enters no bar on either arm** on a mismatch
(`skips.checkpoint_mismatch`; `checkpoint_unverified` when the hash cannot be read), while still
recording bars and closing due positions. `/api/health` → `policy.checkpoint_bound`. Promotion
is therefore: derive the new cut and ladder from the challenger's own split, update the three
constants, deploy — and nothing trades in between against the wrong constants.

### 9.6 The forward ledger persists across swaps

A swap no longer truncates `paper_trades`. Every row is stamped with the checkpoint hash and the
ladder p80 in force (`checkpoint`, `ladder_p80`; the cut was already on the row as `threshold`),
so the ledger is a walk-forward record: the **recipe** is scored pooled across checkpoints, and
any single checkpoint's rows can be scored alone. The forward evidence therefore accumulates
under a retrain trigger instead of being reset by it. Rows taken before 2026-09-04 carry no
checkpoint tag; the table held none at the time.
