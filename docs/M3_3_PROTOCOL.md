# M3-3 — the pre-registered protocol for the learned policy

**Status:** ✅ **COMMITTED 2026-08-27, before any model was fitted.**
**Applies to:** M3-3 only. [M3_PROTOCOL.md](./M3_PROTOCOL.md) stays frozen and unamended; this file sits *under* it.
**Related:** [M3_PROTOCOL.md](./M3_PROTOCOL.md) §4.4 (the promotion bar this inherits) · [M3_2_RESULTS.md](./M3_2_RESULTS.md) (the baseline to beat) · [M3_PLAN.md](./M3_PLAN.md) §2 M3-3, §3.4, §4

---

## §0 — Why a second protocol exists at all

[M3_PROTOCOL.md](./M3_PROTOCOL.md) §4.4 already fixes what M3-3 must **achieve**: pass all six
Tier-1 criteria and beat **+0.25 bps worst-window net at taker**. It does not fix how M3-3 is
**built or measured**, because when it was written no learned policy existed to describe.

That gap is not cosmetic. M3-2 scored *fixed rules*, so scoring them on all four calendar
windows was defensible — a rule with no fitted parameter has no training error. A fitted model
scored on the windows it was fitted on has nothing but training error, and its worst-window
number would be a number about itself. M3_PROTOCOL §1 says outright that **there is no
held-out time period and pretending otherwise would be the dishonest move.** M3-3 cannot
inherit that sentence unchanged; it has to buy a hold-out, and §2 below is how.

**The rule, identical to M3_PROTOCOL §0: this file is not edited after the first fit runs.**
An observation that a different feature, model or metric would have been better is a proposal
for a future pre-registration, never a re-scoring of this run.

### 0.1 🔴 The honest caveat about this document's status

M3-1's protocol was written when *no policy result existed*. This one is not in that position:
it is written with [M3_2_RESULTS.md](./M3_2_RESULTS.md) fully in view. The author knows that
24h holds lose in w4, that 1h holds never cover fees, that the concurrency cap costs money in
every pairing, and that the regime observable works as a size multiplier and not as a filter.

**The response to that is to FIX those choices rather than search them.** Every one of them
appears below as a constant with a citation to the M3-2 row that fixed it — not as a knob
M3-3 may tune. A parameter inherited from a completed, published run is evidence; the same
parameter re-tuned against the same evidence is the overfit M3_PLAN §4 ranks as risk #1. The
only things M3-3 is allowed to search are the ones §4 enumerates, and there are fourteen
scored runs in total.

Everything below is reproducible in a clean session with:

```sh
./scripts/m3.sh -m m3 validate     # the harness is unchanged and trustworthy (must pass first)
./scripts/m3.sh -m m3 fitprep      # every count quoted in §1 and §3 — no P&L, no target touched
```

`m3 fitprep` deliberately never touches `y_bps`. Not a correlation, not a mean, not a sign.
The relationship between an observation and the target *is* the result, and this file is
written before it exists.

---

## §1 — THE SPLIT: leave-one-window-out, refit four times

**Population is unchanged from M3_PROTOCOL §1** — the three banked 5m/seq384 seeds over the
eight-pair BASE8 universe, pooled by concatenation with the seed as a key, over the same four
calendar windows. Changing the population and the policy class in the same step would make
the comparison to M3-2 meaningless.

**What changes is that the model is fitted four times.** For each window *w*: fit on the other
three, score *w*, keep only those out-of-fold scores. The four held-out scorings concatenate
into one ledger in which **every trade was chosen by a model that never saw the window it was
placed in.** The per-window criteria P2, P3 and P4 — and therefore the worst-window number the
whole promotion decision turns on — are then out-of-sample.

The fold sizes, from `m3 fitprep` §C. Rows are not the sample size (M3_PROTOCOL §2); the
cluster count — distinct exit calendar days — is the capacity budget:

| held out | fit rows | fit clusters | held rows | held clusters |
|---|---:|---:|---:|---:|
| w1 | 143,739 | 199 | 27,951 | 53 |
| w2 | 109,488 | 193 | 62,202 | 60 |
| w3 | 138,119 | 191 | 33,571 | 62 |
| w4 | 123,724 | 173 | 47,966 | 79 |

**≈188 independent trading days back each fit.** That number, not the six-figure row count, is
what §4.1 sizes the model class against.

### 1.1 Three things this hold-out is not

1. **It is not out-of-time.** Every fold is trained on windows that both precede *and* follow
   the one it scores. This is cross-validation over a shared period, not walk-forward
   deployment. It removes *training error*; it does not remove the fact that all four windows
   come from one 253-day regime. M3_PROTOCOL §1's third point still stands unchanged: forward
   paper-sim is the only genuinely out-of-time evidence available and it still does not exist.
2. **It does not make the comparison to M3-2 symmetric.** The learned numbers are out-of-fold;
   the baseline's +0.25 was selected in-sample from 40 configurations. **The asymmetry runs
   against M3-3**, which is the conservative direction, and the bar stays where §4.4 put it.
   §6's control C1 re-scores the baseline under M3-3's own machinery so the size of that
   handicap is visible rather than argued about.
3. **It does not launder the feature ranks.** §3.2 declares exactly what those see.

---

## §2 — THE POLICY CLASS

**PLAN.md locks the family and this does not move it:** offline / bandit-style on logged
rollouts, not end-to-end price RL.

One simplification is worth stating because it makes everything downstream easier and is a
property of the evidence rather than a choice: **the logged rollouts carry full feedback, not
bandit feedback.** The dumps hold `fwd_ret` for *every* bar, not only for bars some behaviour
policy happened to trade, so the counterfactual "what would this trade have earned" is known
everywhere. There is no propensity to model, no importance weighting, and no unobserved arm.
The direct method is not an approximation here; it is exact. What remains genuinely offline is
the *constraint* structure — serial positions and the fee — which the M3-0a simulator imposes.

So the learned object is a **value function**, and the policy is derived from it:

> **ŝ(x) = the model's estimate of E[ side × fwd_ret(240m) | x ], in bps** — the gross edge of
> opening the trade M2's side calls for, at this bar, in this market state.

The side is **not** learned. M2 supplies it, M3-2 §D3 measured what it is worth (+36.9 bps over
a momentum side on the same bars), and re-deriving it from nine features on 188 clusters would
be throwing away the one part of the system that has three-seed replication behind it.

The target is **gross**, not net. The fee is a known constant per unit of size, applied at
decision time, so the same fitted model answers the maker question without a re-fit — and
M3_PLAN §3.3 ranks that measurement above any further knob.

---

## §3 — THE OBSERVATION VECTOR

**Nine features, fixed.** The list is code — `features.FEATURES`, in a fixed order — so a later
session re-derives it rather than trusting this table. A feature added later is a new protocol,
not a new run.

| # | feature | what it is | why it is here |
|---|---|---|---|
| 1 | `conf_rank` | percentile of the 240m confidence | §1.3.3: the continuous form of M3-2's coverage knob |
| 2 | `conf_rank_60` | percentile of the 60m head's confidence | **new** — M3-2 never read another head |
| 3 | `conf_rank_1440` | percentile of the 1440m head's confidence | **new** |
| 4 | `agree_60` | ±1: does the 60m head take the same side? | **new** — horizon agreement, free in the same dump |
| 5 | `agree_1440` | ±1: does the 1440m head take the same side? | **new** |
| 6 | `btc_absret_rank` | percentile of `btc_absret_1d` | §1.8's observable, **continuous** per M3_2_RESULTS §F |
| 7 | `rv_rank` | percentile of the pair's trailing-1d realised vol | M3_PLAN §3.4 step 1: the analytic vol proxy, cheapest first |
| 8 | `vol_expansion` | percentile of `rv_1d / rv_7d` | is volatility rising or falling |
| 9 | `xs_disp_rank` | percentile of cross-sectional dispersion of 4h moves | market-wide dislocation |

**Features 2–5 are the reason to expect a learned policy might win at all.** Everything else is
a continuous restatement of something M3-2 already searched: feature 1 is its coverage knob and
feature 6 is the observable its winner buckets on, so **the M3-2 sizing winner is a step
function of feature 6 and lives inside this policy class rather than outside it.** If M3-3 does
not beat it, the finding is that the extra observations carry nothing — a real result, and §7
pre-registers it as one.

### 3.1 What is absent, and why

**Position state — side, age, unrealised P&L — is not in the vector.** It needs a price path
between entry and exit, which the dumps do not carry (M3_PLAN §M3-0a constraint 1). Under
fixed-hold serial entries it is also not decision-relevant: there is no exit decision to make.
It arrives with M3-0b's side-table, alongside the barrier exits that would give it something to
decide. Not a deferral for convenience — a deferral until it means something.

**A learned risk model is not here either.** M3_PLAN §3.4 orders that branch cheapest-first and
step 1 is the analytic vol proxy, which is features 7 and 8. A detached quantile head is step 2
and is justified only if the proxy turns out to be the binding limit.

### 3.2 🔴 The rank approximation, declared

Every feature is a percentile **within its own seed's full 240m bar population, computed over
the whole 253 days — including the held-out fold.**

This is a monotone transform estimated on the whole period, and it is **target-free**: no
`fwd_ret` enters a rank, so no P&L can leak into a fold. It is also the identical assumption
M3-2 already makes — `backtest.coverage_threshold` ranks each seed's whole population to derive
a coverage threshold — and keeping the two consistent is what makes the learned policy and the
baseline comparable at all. It is an approximation, it flatters both sides equally, and it is
declared here rather than discovered later.

### 3.3 Completeness: bars are dropped, never imputed

4,120 bars per seed (12,360 pooled) carry an incomplete 24h or 7d lookback and are dropped.
**All of them lie in 2025-12-09..12**, the warm-up at the very start of the dump, all in w1.
An imputed feature value is a made-up market state; §1.8's own rebuild drops the same class of
bar (validate.py TEST 2 loses 24 pooled trades to it), so the populations stay comparable.

### 3.4 The candidate pool

The model is fitted, and the policy acts, on **the top 10% of each seed's bars by 240m
confidence** — 171,690 pooled rows.

| | w1 | w2 | w3 | w4 | total |
|---|---:|---:|---:|---:|---:|
| pool rows (3 seeds) | 27,951 | 62,202 | 33,571 | 47,966 | 171,690 |

Two reasons for a pool rather than all 1.7M bars or only the top 2%. Fitting on everything
would drown the ~2% of bars the policy ever acts on in the 98% it never will; fitting on the
top 2% would pin coverage, and §1.3.1 makes coverage a first-class decision variable. 10% is a
superset of every coverage the M3-2 grid scored (0.01 / 0.02 / 0.05) with headroom.

**Two consequences, both pre-registered rather than discovered:**

1. **The learned policy cannot exceed 10% coverage.** A real cap. On M3-2's evidence nothing
   above 5% was close to viable, so the cap is not expected to bind — but if a config wants to
   sit at it, that is reported as the cap binding, not as a chosen coverage.
2. 🔴 **The fit is unweighted, so w2 carries 36% of it** (62,202 of 171,690 rows) — the window
   §1.8's regime rule *fails* in, and where 47% of its trades live. Confidence is not
   stationary, so a whole-period top-10% cut lands unevenly in time. Equal-weighting the
   windows would be a defensible alternative; it is **not taken**, because choosing between
   two weightings after seeing which one wins is exactly the move this document exists to
   prevent. Unweighted is the simpler default, it is declared, and the alternative is logged
   in §7 as a proposal for a future pre-registration.

---

## §4 — THE SEARCH SPACE: exactly what will be fitted and run

**14 scored runs in total.** As in M3_PROTOCOL §3, the list is code (`cli.learned_grid()`), so
a later session re-derives it rather than trusting this prose.

### 4.1 Two model classes, both linear-in-parameters, both closed-form

| | terms | what it is |
|---|---:|---|
| **A** | 9 | the nine features, linear |
| **B** | 26 | the nine, plus each squared, plus the eight products of `conf_rank` with the others |

Against **≈188 training clusters per fold**. That ratio is the whole argument:

- **B is not a full quadratic** (which would be 54 terms). The restriction is a pre-registered
  prior: the only interaction worth degrees of freedom here is *does the confidence signal's
  value depend on market state* — precisely `conf_rank × context`. Everything else is capacity
  we cannot pay for.
- **No tree ensemble, no neural network, and this is a decision, not an omission.** 188
  clusters cannot support one. If the linear classes fail, **that is not evidence that a larger
  model would have succeeded**, and §7 forbids reading it that way. Stating this before the run
  is what stops "try a GBM" from becoming the conclusion of a disappointing result.
- Both classes are ordinary ridge — closed-form, deterministic, no seed, no early stopping, no
  optimiser. Nothing about a fit depends on when it ran.

The features are standardised using **training-fold** mean and sd only. The intercept is
unpenalised.

### 4.2 The ridge penalty, selected without looking at the held-out window

λ ∈ **{0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0}**, in scale-free units (the penalty enters as
λ·n·I on standardised features, so λ is a shrinkage factor, not a data-scale quantity).

Selected by an **inner leave-one-window-out inside the three training windows**: for each inner
window, fit on the other two, score it, and take the mean net-at-taker bps of the resulting
top-2%-per-window selection pooled over the three inner held-out windows. **Highest wins; ties
go to the larger λ.** The outer held-out window is never consulted.

The inner selection uses the raw per-bar mean, **not** the simulated ledger — it is a
hyper-parameter heuristic, not a reported number, and the serial-position constraint would only
add noise to a choice among seven values. Every λ actually selected is reported per fold.

Collinearity is why this is per-fold rather than fixed: the strongest feature pair is
`rv_rank` / `vol_expansion` at 0.51 (`m3 fitprep` §D).

### 4.3 Two entry rules

| | rule | what it tests |
|---|---|---|
| **R1** | enter iff **ŝ ≥ 14 bps** (the taker round trip) | the model's *absolute* calibration — it sizes its own coverage, with no coverage knob at all |
| **R2** | enter on the **top 2% of each seed-window's bars** by ŝ | the model's *ranking* against the baseline at a matched trade budget |

**Why R2 cuts per window rather than over the whole period.** The four folds are four different
fits, so their ŝ values are four different rulers; a single whole-period cut on them would silently
allocate the trade budget by which fold happened to have the larger intercept. Cutting within
each held-out window compares each model's scores only against its own. This is a departure
from the baseline, which takes the top 2% of the whole period per seed and therefore lands
unevenly across windows — the departure mildly helps rule P4, so **every run reports its
per-window trade counts** and §6's control C1 re-scores the baseline under the identical
per-window discipline.

R1 keeps a raw absolute threshold precisely because that is what it is testing: ŝ is in bps by
construction, and whether the four fits agree about *level* — not just order — is a real
property worth measuring once.

### 4.4 Two sizing rules

| | rule |
|---|---|
| **S1** | flat, size 1.0 |
| **S2** | size = `clip(ŝ / s_ref, 1/3, 5/3)`, `s_ref` = the mean ŝ over the **training folds'** selected bars |

The 1/3..5/3 clip is **copied from M3-2's sizing variant**, not tuned, so the comparison
isolates *what* is being sized on rather than *how hard*. `s_ref` comes from training folds
only: a normaliser computed over the held-out window would carry that window's own scale back
into its score.

### 4.5 Everything else is fixed, with the row that fixed it

| constant | value | fixed by |
|---|---|---|
| `signal_horizon` | 240 | the optimised and served primary |
| `hold_horizon` | 240 | M3_2_RESULTS §B pattern 1 and 2 — every `hold1440` config loses 61–198 bps in w4; every `hold60` config is net-negative at taker |
| `max_concurrent` | none | §B pattern 3 — the cap is worse than its uncapped twin in **every** pairing |
| `sides` | both | M3_PROTOCOL §3.3 — side balance is not seed-stable and is never selected on |
| side source | the model | §D3 — worth +36.9 bps/trade over a momentum side |

**2 classes × 2 entry rules × 2 sizings = 8 learned configurations.**

---

## §5 — THE DECISION RULE

**Unchanged and inherited, verbatim, from [M3_PROTOCOL.md](./M3_PROTOCOL.md) §4.2 and §4.4.**
It is not restated in a form that could drift: Tier 1 is P1–P6 evaluated at taker, eligibility
is P4, and the code path is the same `search.tier1()` M3-2 was scored by.

> **A learned configuration is promoted over the M3-2 winner only if it passes all six Tier-1
> criteria AND beats +0.25 bps worst-window net at taker.**

Ranking among passers is by worst-window net at taker, ties broken by pooled net at taker —
again the same `search.rank()`. Selection is at taker; maker is reported alongside and never
selected on. Tier 2 (§4.3 of the protocol: is the clustered 95% lower bound above zero?) is
reported for the winner and is expected to fail for the reasons M3_PROTOCOL §2 gives; it must
not be used to argue the metric is wrong.

`m3 validate` must pass before any of this is believed, per M3_PROTOCOL §4.4 — a learned policy
compared against a baseline computed by a changed harness is not a comparison.

---

## §6 — THE CONTROLS: 6 more runs

Reported, and — except C3 — allowed to win if they win, because each is a legitimate policy.

- **C1 — the M3-2 winner, re-scored under M3-3's machinery.** `cov0.02_hold240_rqnone_mcnone_SIZED`
  re-run with the per-window coverage discipline of §4.3 and the pool and completeness
  restrictions of §3.3–3.4. It measures the size of the §1.1(2) handicap. The published +0.25
  remains the bar regardless of what C1 prints.
- **C2 — the confidence-only ablation, 4 runs** (one per entry-rule × sizing combination, so a
  matched ablation exists whatever the winner's settings turn out to be). A ridge fit on
  `conf_rank` alone. It answers the one question that decides whether M3-3 was worth building:
  **do the eight other observations add anything over the coverage rank M3-2 already used?**
  - 🔴 **A falsifiable prediction, written before the run.** A one-feature fit with a positive
    coefficient orders bars identically to `conf`, so **C2 under R2 + S1 must reproduce the
    M3-2 grid winner's ledger** up to the warm-up bars §3.3 drops and the per-window cut of
    §4.3. If it does not, the harness is wrong and the whole run is void rather than
    interesting. If the coefficient comes out **negative** — confidence anti-predictive *within
    the top 10%* — that is a genuine finding about the signal and is reported as one.
- **C3 — the O8 replication, 1 run.** The winner's four fold-models applied to the 12-pair O8
  dump (`20260822T012619Z`), each window scored by the model that held it out. Same calendar
  period, so it is replication across **instruments**, not across time. **Reported, never
  selected on**, exactly as M3_PROTOCOL §1 requires.

**8 learned + C1 + 4×C2 + C3 = 14 scored runs.**

---

## §7 — WHAT HAPPENS IF NOTHING WINS

Pre-registered, so it cannot be argued away afterwards.

**If no learned configuration clears Tier 1, or none beats +0.25 bps worst-window net at taker,
then the M3-2 rules baseline stands as M3's policy and that is M3-3's result.** It is written
up as one. The grid is not widened, a fifteenth run is not tried, the feature list is not
extended, and — per §4.1 — a larger model class is **not** proposed as the remedy.

That outcome would say something specific and useful: that on 188 independent trading days, a
continuous, fitted use of nine observations does not beat bucketing one of them into fifths.
Given the sample, that is a completely ordinary thing for the evidence to say.

The next steps in that case are the two that change the evidence rather than re-slice it,
unchanged from M3_PROTOCOL §6:

1. **The maker-fee study** (M3_PLAN §3.3, ranked risk #2). Every M3-2 candidate roughly doubles
   at 5 bps. Whether those fills are obtainable is an untested assumption underwriting half the
   published economics, and it is measurable cheaply on the paper-sim stack.
2. **M3-0b's price/funding side-table**, which unlocks barrier exits, the funding term, and the
   position-state observations §3.1 defers — genuinely new degrees of freedom rather than new
   combinations of the ones we have.

### 7.1 Proposals already logged for a future pre-registration

Recorded here, before the run, so they cannot be presented afterwards as things the results
suggested:

- **Window-equalised fitting weights** (§3.4, consequence 2). The unweighted fit gives w2 36%
  of the say.
- **Per-notional normalisation of a size-varying policy** (carried over from M3_2_RESULTS §D1,
  still unresolved and still not the ranking metric).
- **Whether R2's per-window coverage cut should also be the baseline's rule** (§4.3). C1
  measures the difference; changing the baseline's definition on the strength of it would be an
  amendment, not a measurement.

---

## §8 — AMENDMENTS

None. If this file ever acquires an amendment it must be dated, must state what was known at
the time it was made, and must say explicitly whether any fitted result had been seen.
