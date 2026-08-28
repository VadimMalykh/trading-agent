# T6 — the fair 8-vs-12 comparison

runs: 20260827T050701Z, 20260827T114122Z, 20260822T012619Z  (seeds s1, s2, s3)
universe: 12 pairs, 8 of them the baseline; beyond it: ADAUSDT, AVAXUSDT, LINKUSDT, XRPUSDT
policy:   PolicySpec(coverage=0.02, signal_horizon=240, hold_horizon=240, regime_col='btc_absret_1d', regime_min=None, regime_quantile=None, size_by_regime=True, max_concurrent=None, sides='both', side_from='model', score_col=None, score_min=None, size_col=None, label='winner')
calendar span: 270.9 days;  costs: taker 14bps, maker 5bps round trip

## 0. The coverage-matched comparison, for reference

What `m3 universe` reports and what §1.10 published. It is NOT the fair test: at a fixed 2% coverage the wider universe takes ~50% more trades, so it is spending a bigger budget rather than picking better trades.

| arm | trades | tr/day | gross | net @14 | worst window | Sharpe | maxdd | clusters |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 pairs, cov 0.02 | 1,645 | 2.02 | +27.99 | **+9.29** | -22.09 (w3) | 0.67 | -2.8317 | 169 |
| 12 pairs, cov 0.02 | 2,475 | 3.05 | +27.71 | **+9.00** | -18.23 (w3) | 0.55 | -4.5265 | 187 |

**wide − narrow, coverage-matched: -0.29 bps**, 95% CI [-12.04, +11.46] (cluster-robust SE 5.99 over 189 exit days, 167 of them shared; day-bootstrap SE 5.82 on 2,000 draws, as an independent check on the analytic one). At 80% power this comparison resolves effects of about ±16.8 bps and nothing smaller.

### 0b. §1.10's published interval, re-derived — and it is a different estimand

§1.10 reports this same comparison as **−0.85 bps, 95% CI [−6.79, +5.09] across 167 shared days**, and concludes from it that the original single-seed "+7.5 bps from 12 pairs" is excluded. That number is reproduced exactly below — but by a **day-weighted, shared-days-only** estimator, while the table it sits beside reports **trade-weighted** means. The two answer different questions and they do not agree about the +7.5.

| estimator | estimand | diff | 95% CI | is +7.5 excluded? |
|---|---|---:|---|---|
| trade-weighted, cluster-robust (`paired_diff_bps`) | the difference in net bps **per trade** — the statistic the table above reports | -0.29 | [-12.04, +11.46] | **NO** |
| day-weighted, shared days only — **§1.10's** | the average **daily** difference in net bps per trade, over days both universes traded | -0.85 | [-6.79, +5.09] | yes |
| day-weighted, all days | the same, but not dropping the 22 days only one universe traded | -1.73 | [-8.30, +4.84] | yes |

**The claim under test is a per-trade claim, so the first row governs it.** Equally weighting days is a different estimand — it coincides with the per-trade difference only if every day carries the same number of trades in both arms, which is precisely what changing the universe breaks — and restricting to shared days discards the days on which the two policies most differ. On the estimator that matches the published statistic, **+7.5 bps is inside the interval**: the T-wave did not exclude it either. The +7.5 remains an unreplicated single-seed point estimate, which is reason enough not to bank it, but §1.10 should not be read as having refuted it.

## 1. TEST 1 — the trade-count-matched comparison (the fair one)

The 8-pair arm books **1,645** pooled trades at cov 0.02. Bisecting coverage on the 12-pair universe to the same budget lands at **cov 0.01288** and 1,652 trades — the wide arm is now 1.55x more selective, which is exactly the hypothesis: a deeper cross-section should let the policy pick better trades, not more of them.

| arm | trades | tr/day | gross | net @14 | worst window | Sharpe | maxdd | clusters |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 pairs, cov 0.02 | 1,645 | 2.02 | +27.99 | **+9.29** | -22.09 (w3) | 0.67 | -2.8317 | 169 |
| 12 pairs, cov 0.01288 (count-matched) | 1,652 | 2.03 | +38.70 | **+19.51** | -20.81 (w3) | 1.00 | -4.2445 | 153 |

**wide − narrow, TRADE-COUNT-MATCHED: +10.21 bps**, 95% CI [-15.60, +36.03] (cluster-robust SE 13.17 over 182 exit days, 140 of them shared; day-bootstrap SE 12.95 on 2,000 draws, as an independent check on the analytic one). At 80% power this comparison resolves effects of about ±36.9 bps and nothing smaller.

### 1b. The selectivity control — is the gain the universe, or just a tighter cut?

Matching the trade count makes the wide arm **more selective as well as wider**, and those are two different levers. Scoring the 8-pair universe at the SAME coverage separates them: whatever a tighter cut is worth on its own shows up in the narrow arm too.

| arm | trades | tr/day | gross | net @14 | worst window | Sharpe | maxdd | clusters |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 pairs, cov 0.02 | 1,645 | 2.02 | +27.99 | **+9.29** | -22.09 (w3) | 0.67 | -2.8317 | 169 |
| 8 pairs, cov 0.01288 (same cut, fewer trades) | 1,101 | 1.35 | +41.11 | **+22.02** | -10.24 (w3) | 1.41 | -2.2087 | 139 |
| 12 pairs, cov 0.01288 (count-matched) | 1,652 | 2.03 | +38.70 | **+19.51** | -20.81 (w3) | 1.00 | -4.2445 | 153 |

- **tightening the cut alone** (8 pairs, cov 0.02 → 0.01288): +12.72 bps, 95% CI [-3.39, +28.84]
- **widening the universe at that same cut** (8 → 12 pairs, both at cov 0.01288): -2.51 bps, 95% CI [-17.85, +12.83]
- **the two together**, which is the count-matched headline: +10.21 bps

⚠️ **Read TEST 1's headline through this decomposition, not on its own.** The count-matched comparison confounds a wider universe with a tighter confidence cut, and the second is a lever the 8-pair universe can pull too — at the cost of trading less often, which is why the M3-2 grid did not choose it.

## 2. TEST 2 — re-tuning the concurrency cap

⚠️ A **sizing re-tune on a fixed policy**, over the cap values the M3-2 grid already contains (`GRID_MAX_CONC = (None, 3)`). It is not a re-search of the 40-config grid on a new pair population, which M3_PROTOCOL §0 forbids. The wider ladder below is texture and nothing is chosen from it.

**Pre-registered cap set — the decision is taken over these rows only.**

| arm | trades | tr/day | gross | net @14 | worst window | Sharpe | maxdd | clusters |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 pairs, cap none | 1,645 | 2.02 | +27.99 | **+9.29** | -22.09 (w3) | 0.67 | -2.8317 | 169 |
| 12 pairs, cap none (count-matched) | 1,652 | 2.03 | +38.70 | **+19.51** | -20.81 (w3) | 1.00 | -4.2445 | 153 |
| 8 pairs, cap 3 | 1,423 | 1.75 | +19.25 | **+0.89** | -22.44 (w3) | 0.08 | -2.1844 | 169 |
| 12 pairs, cap 3 (count-matched) | 1,177 | 1.45 | +13.89 | **-4.80** | -29.65 (w3) | -0.32 | -2.5602 | 153 |

*Texture only — the wider ladder. Not eligible to be chosen (M3_PROTOCOL §0).*

| arm | trades | tr/day | gross | net @14 | worst window | Sharpe | maxdd | clusters |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 pairs, cap 2 | 1,242 | 1.53 | +11.59 | **-6.57** | -30.29 (w4) | -0.62 | -2.2069 | 169 |
| 12 pairs, cap 2 (count-matched) | 984 | 1.21 | +20.03 | **+1.56** | -32.19 (w3) | 0.13 | -1.5403 | 153 |
| 8 pairs, cap 4 | 1,530 | 1.88 | +20.98 | **+2.43** | -22.18 (w3) | 0.19 | -2.8690 | 169 |
| 12 pairs, cap 4 (count-matched) | 1,321 | 1.63 | +20.32 | **+1.48** | -23.21 (w3) | 0.09 | -2.9584 | 153 |
| 8 pairs, cap 6 | 1,626 | 2.00 | +25.54 | **+6.88** | -22.09 (w3) | 0.51 | -2.7966 | 169 |
| 12 pairs, cap 6 (count-matched) | 1,496 | 1.84 | +27.43 | **+8.44** | -20.81 (w3) | 0.50 | -3.1730 | 153 |
| 8 pairs, cap 8 | 1,645 | 2.02 | +27.99 | **+9.29** | -22.09 (w3) | 0.67 | -2.8317 | 169 |
| 12 pairs, cap 8 (count-matched) | 1,592 | 1.96 | +32.35 | **+13.21** | -20.81 (w3) | 0.73 | -3.7040 | 153 |

Best pre-registered cap by worst-window net at taker: **8 pairs → `max_concurrent=none`**, **12 pairs → `max_concurrent=none`**.

## 3. TEST 3 — the fair difference, its interval, and each criterion's power

| arm | trades | tr/day | gross | net @14 | worst window | Sharpe | maxdd | clusters |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 pairs, cap none | 1,645 | 2.02 | +27.99 | **+9.29** | -22.09 (w3) | 0.67 | -2.8317 | 169 |
| 12 pairs, cap none (count-matched) | 1,652 | 2.03 | +38.70 | **+19.51** | -20.81 (w3) | 1.00 | -4.2445 | 153 |

**THE FAIR TEST — wide − narrow, count-matched, each universe at its own best pre-registered cap: +10.21 bps**, 95% CI [-15.60, +36.03] (cluster-robust SE 13.17 over 182 exit days, 140 of them shared; day-bootstrap SE 12.95 on 2,000 draws, as an independent check on the analytic one). At 80% power this comparison resolves effects of about ±36.9 bps and nothing smaller.

⚠️ **Whose Tier 1 is this?** These three dumps are the 12-pair checkpoints T1, T2 and O8 — not the banked 8-pair family M3-2's winner was selected on. A Tier-1 failure in the table below is a statement about this checkpoint population, and is NOT the served policy failing its own certification.

**Bootstrap failure rate of each Tier-1 criterion**, 2,000 common day-resamples (`universe.criterion_power`, seed 20260827). Read the incumbent's row first: a criterion the incumbent also fails half the time cannot arbitrate between the two universes.

| arm | | P1 | P2 | P3 | P4 | P5 | P6 | all six |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 8 pairs (cap none) — the INCUMBENT | observed | Y | **N** | **N** | Y | Y | Y | **N** |
| | fails in | 33.1% | 74.7% | 97.8% | 5.5% | 52.4% | 0.0% | 98.7% |
| 12 pairs (cap none, count-matched) | observed | Y | Y | **N** | **N** | Y | Y | **N** |
| | fails in | 25.1% | 53.6% | 88.5% | 92.5% | 46.7% | 0.0% | 99.3% |

## Verdict, by the rule committed above before this ran

**UNDECIDED — the incumbent 8-pair universe stands by default.** The paired interval on the fair test spans zero, so this data cannot separate the two universes in either direction. Fair-test difference **+10.21 bps**, 95% CI [-15.60, +36.03], over 182 exit-day clusters.

**And the fair test's point estimate is not a universe effect anyway.** §1b decomposes it: tightening the confidence cut is worth +12.72 bps on the 8-pair universe by itself, while widening 8 → 12 pairs at that same cut is worth -2.51 bps, 95% CI [-17.85, +12.83]. Almost all of the +10.21 is the cut, not the pairs — and the universe term, cleanly separated, is a small NEGATIVE point estimate with an interval that still spans zero. Three comparisons (coverage-matched, count-matched, cut-matched) now put the universe effect within a couple of bps of zero in both directions.

**What the concurrency cap turned out to be worth: nothing, on either universe.** §1.10 read the widened drawdown (−2.83 → −4.53) as an argument for re-tuning the cap. Re-tuned over the pre-registered set it is not: `max_concurrent=none` wins on both universes, and every cap in the texture ladder costs net bps. A cap does cut drawdown, and it buys that by refusing profitable trades.

**The criterion-power table settles what §1.10 could only suspect.** P5 — the all-seeds-positive check an earlier draft used to reject 12 pairs — fails on the INCUMBENT in 52.4% of resamples against 46.7% on the challenger. It cannot decide anything. The criterion that actually bites is **P3, the −5 bps worst-window floor**, which fails on both arms in the observed data and in 97.8% / 88.5% of resamples. **Window 3 is the binding constraint on this policy, and it is not a universe problem** — widening the pair set does not touch it.

**What this test could have detected.** The cluster-robust SE on the difference is 13.17 bps, so at 80% power it resolves effects of about ±36.9 bps and nothing smaller. That bound is a property of the ~182 independent exit days this evaluation period contains, not of the policy or of the number of seeds — pooling more seeds adds correlated trades inside the same days and does not move it (§1.10). **A real universe effect of the size anyone cared about (+7.5 bps) is roughly a third of what this evaluation period can resolve.** No further offline work on these dumps, and no further seeds, can settle 8-vs-12: only a longer evaluation period can, and that is calendar, not compute.

### One observation that is NOT a recommendation

On these three checkpoints the 8-pair universe scores +22.02 net bps at cov 0.01288 against +9.29 at cov 0.02, with a better worst window (-10.24 vs -22.09) and a higher Sharpe (1.41 vs 0.67). **Do not act on that here.** Coverage is a searched dimension of the M3-2 grid, which chose 0.02 on the banked 8-pair family; re-picking it on a different checkpoint population after seeing the numbers is precisely the shopping M3_PROTOCOL §0 forbids. If coverage is to be revisited it goes through a fresh pre-registration on the population the decision will be served from.

