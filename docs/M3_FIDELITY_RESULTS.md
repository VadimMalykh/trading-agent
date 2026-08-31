# M3 fidelity — the served policy is not the policy that was scored

**Status:** 🔴 **BLOCKER, found 2026-08-31.** Measured, reproducible, and it invalidates the
forward paper test's first twelve trades.
**GPU required:** No. **Keys required:** No. **Command:** `./scripts/m3.sh -m m3 fidelity`
**Logs:** `logs/fidelity_8pair.log`, `logs/fidelity_12pair.log`
**Code:** `ml/train/m3/livemode.py` (new; `backtest.py` deliberately untouched)
**Related:** [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) · [M3_PLAN.md](./M3_PLAN.md) §0.6 ·
[BACKLOG.md](./BACKLOG.md) · [NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) §1.5

---

## §0 — In plain language, and the bottom line

M3-2 chose a rule: **trade the top 2% of bars by the model's confidence, size by the volatility
regime, hold four hours.** "The top 2%" has to be measured against *something*, and the
backtest measured it against the whole 253-day evaluation period — one fixed confidence number
per model, about **0.62**.

A live trader cannot do that: on any given day it does not know what the rest of the year looks
like. So `Ledger.coverage_threshold/3` measures the top 2% against **the last 14 days** instead,
and `Regime` does the same thing to the sizing ladder over the last 30 days. Both substitutions
are deliberate, both are documented where they are made, and **neither was ever scored.**

They are not a small approximation of the same rule. A trailing rank admits 2% of bars in
*every* window **by construction** — including a window the fixed rule would have sat out
completely. And August 2026 is exactly such a window: it is the calmest stretch of the whole
period, and the model's confidence never rises above **0.569** all month
([NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) §0). The fixed cut is **0.6319**.

🔴 **So the validated policy would have taken ZERO trades in August. The served policy took
twelve.** The live cut had drifted down to **0.5560**, and all twelve entries sit between
0.5565 and 0.5616 — every one of them below every seed's fixed cut. The forward paper test is
running, and it is not running the rule anybody scored.

**The bottom line:** this does not mean the strategy is broken, and it does not mean the twelve
losing trades are evidence of anything (they are not — see §3). It means the clock that the
whole phase exists to run has been accumulating the wrong evidence for two days, and the fix
resets it. That is much cheaper now than in three months.

### The jargon, defined once

* **bps** — basis point, 0.01%. A +20 bps trade on a $1,000 position makes $2.
* **gross / net** — before and after trading costs. **Taker** = crossing the spread (expensive,
  what the executor does); **maker** = resting a limit order (cheaper, not built).
* **the cut / the threshold** — the confidence number above which a bar is tradeable. The whole
  finding is about how that number is computed.
* **the ladder** — the five size buckets (1/3 .. 5/3) the policy scales positions by, keyed off
  BTC's trailing 24-hour move.

---

## §1 — What was measured

`m3 fidelity` scores the served spec four ways, so the two substitutions can be blamed
separately, on the same dumps every published M3 number came from:

| arm | coverage cut | sizing ladder | |
|---|---|---|---|
| **A** | fixed, whole split | fixed, whole split | the **validated** policy |
| **B** | rolling 14d | fixed | |
| **C** | fixed | rolling 30d | |
| **D** | rolling 14d | rolling 30d | what **`fluxtrader-1` serves** |

🔴 **This is a fidelity check, not a search.** It re-picks no knob: coverage stays at the 0.02
M3-2 selected, the ladder stays 1/3..5/3. [M3_PROTOCOL.md](./M3_PROTOCOL.md) §0 forbids
re-choosing a searched dimension after seeing results; it does not forbid asking whether the
served code computes that dimension the way the scoring code did. **Arm D is not a candidate
policy. It is the incumbent, finally measured.**

**Acceptance test, and it passed.** With the window widened to the whole split, `livemode.py`
reproduces `backtest.run()`'s ledger **row for row** — 1,773 trades on the 8-pair baseline, 869
on O8, every `signed_ret` identical. That is what licenses reading the A-vs-D gap as the
windowing and nothing else, rather than as a bug in a re-implementation.

---

## §2 — The result

### 2.1 Three banked seeds, 8 pairs — the population M3-2 chose on

| arm | trades | net bps (taker) | 95% CI, day-clustered | worst window | /day |
|---|---:|---:|---|---:|---:|
| **A** validated | 1,773 | **+15.03** | [−33.0, +63.1] | w3 **+0.25** | 2.71 |
| B rolling cut | 2,316 | +9.60 | [−18.3, +37.5] | w1 −7.04 | 3.07 |
| C rolling ladder | 1,773 | +13.54 | [−34.7, +61.8] | w3 −1.16 | 2.71 |
| **D served** | 2,316 | **+8.62** | [−19.5, +36.7] | w1 **−8.88** | 3.07 |

At maker: A +27.07 → D +19.41.

**The cut does the damage, not the ladder.** B loses 5.4 bps, C loses 1.5.

🔴 **The line that matters is the worst window, because that is the number M3-1 scores on.**
It goes from **+0.25** — already marginal — to **−8.88**. The served rule fails the criterion
the policy was selected against.

### 2.2 O8, 12 pairs, single seed — the universe actually served

| arm | trades | net bps (taker) | 95% CI, day-clustered | /day |
|---|---:|---:|---|---:|
| **A** validated | 869 | **+21.44** | [−37.7, +80.5] | 3.61 |
| B rolling cut | 1,343 | −17.68 | [−48.0, +12.6] | 5.10 |
| **D served** | 1,343 | **−18.43** | [−49.1, +12.2] | 5.10 |

**On the served universe the edge does not shrink — it changes sign.** +21.44 → −18.43.

⚠️ O8 is one seed, and T6 already records that its worst-window column does not replicate.
Do not quote O8's *absolute* numbers. The A-vs-D **gap** is measured on one population under
one change and is what this table is for.

### 2.3 Why — the cut floats, and the trades barely overlap

| | 8 pairs (s1/s2/s3) | O8 |
|---|---|---|
| fixed cut | 0.6091 / 0.6319 / 0.6153 | 0.5992 |
| rolling cut, mean | 0.5971 / 0.6126 / 0.6036 | 0.5814 |
| rolling cut, range | up to [0.5499, 0.7263] | [0.5358, 0.6953] |
| below the fixed cut on | 66% / 72% / 69% of warm bars | 72% |
| D's trades on bars A rejects | **56%** | **68%** |
| shared (pair, bar) | 394 of 1,773 | 164 of 869 |

The rolling cut is not uniformly looser — it rises above the fixed cut in volatile stretches
too. It is **regime-adaptive in the wrong direction**: it lowers the bar precisely when the
model has nothing to say, which is when the edge is known to be absent (§1.8: the edge lives in
volatile bars).

### 2.4 Conformance — what each rule *does*

|  | A validated (8 pairs) | D served (8 pairs) |
|---|---|---|
| trades/day | 2.71 | 3.07 |
| long / short | 80% / 20% | 71% / 29% |
| top pair | BTCUSDT 21% | HYPEUSDT 21% |
| entry confidence (min / med / max) | 0.6092 / 0.6239 / 0.7820 | 0.5504 / 0.6103 / 0.7879 |
| mean size | 1.337 | 1.199 |

**This table is the weekly check.** The forward test cannot resolve P&L for months, but a
served policy whose trade rate, side mix and entry-confidence band sit outside its arm's row is
not running that arm, and no amount of calendar time repairs that.

---

## §3 — The live ledger, and what it is *not* evidence of

`/api/health` on `fluxtrader-1`, 2026-08-31 13:41 UTC: **12 closed trades in 1.78 days**,
**−55.58 net bps/trade**, cumulative −667 bps, max drawdown −794 bps, daily P&L −26.78 against
a −50 limit.

🔴 **That P&L is not evidence of anything.** Per-trade sd is 161.5 bps, so the naive 95%
interval is about **[−158, +47] bps** — it contains zero, it contains the +20 the policy claims,
and a day-clustered interval would be wider still. One WLDUSDT trade at −450 bps is two-thirds
of the cumulative loss. Twelve trades resolve nothing, in either direction.

What the ledger *is* evidence of is **structural**, and needs no statistics:

1. **All twelve entries are below every fixed cut** (0.5565–0.5616 against 0.6091/0.6319/0.6153).
   The validated rule takes none of them.
2. **6.73 trades/day** against T6's 3.05 for this universe, and against arm D's own 5.10 — the
   live market is calmer than anything in the evaluation period, so the divergence is *larger*
   live than the historical replay shows.
3. **10 of 12 trades are WLDUSDT and 12 of 12 are long.** WLD has been held effectively
   continuously since 2026-08-30 13:25, rolled five times at 14.06 bps a roll — it is the most
   expensive pair in the universe. 🟢 The roll itself is **faithful**: `_simulate_seed` frees a
   pair on its own exit bar, so the backtest scores immediate re-entry too. This is
   concentration, not a second defect.

---

## §4 — Two further findings, filed separately

### 4.1 🔴 The A/B has no B

`Policy.decide_signal_only/3` requires `bar.gated`, and **no bar has been gated** across all
8,184 bars since the 2026-08-29 reset (`last_gated_at: null`). The control arm has 0 trades
against the policy arm's 12, and it will stay at 0 while M2's own gate stays shut — which
§0 of the training plan expects to last as long as the calm does.

M3-5's deliverable was described as a paper A/B. In practice **there is one arm.** That needs
a decision: either accept that the comparison is against the offline baselines rather than a
live control, or redefine the control to something that actually fires (the obvious candidate:
same bars as the policy arm, flat size — which isolates sizing, the thing the policy claims).
Not urgent, but it should not be discovered again in three months.

### 4.2 The daily loss limit biases the estimate upward

`RiskManager`'s −50/day limit suppresses entries after a bad day. That truncates the left tail
of the *recorded* sample, so the forward test's mean net bps is a biased estimator of the
policy's unconditional per-trade edge. Today's P&L reached −26.78 against it. Either accept and
document the bias, or record suppressed entries as counterfactual bars so it can be removed.

---

## §5 — What to do, and what NOT to do

**The decision is which rule is the policy, and it is not a technical question.** Two coherent
answers, and one incoherent one:

1. 🟢 **Freeze the cut at the served seed's banked value (s2 = 0.6319)** and make live match
   what was scored. Coverage stays 0.02 — this is *not* re-picking a searched dimension, it is
   making the implementation compute the dimension the way the scoring code did, so
   M3_PROTOCOL §0 is not engaged. **Consequence, stated honestly: the policy goes silent until
   volatility returns** — that is precisely the "correct silence" the dashboard was built to
   render, and it lengthens the calendar the forward test needs.
2. 🟡 **Pre-register the floating cut as a deliberate new rule** and serve it knowingly. It is
   a defensible rule — it trades a constant budget rather than betting on a regime returning —
   but arm D is what it is worth, and arm D's worst window is negative. It needs its own
   pre-registration on the population it will be served from, written before anything else is
   scored.
3. 🔴 **Do not leave it running undecided.** Every day it accumulates trades that belong to
   neither rule, and the A/B spans two policies the moment it is changed — the same
   comparability break M3_4_PROTOCOL §7 records for the trade-tape change.

**Either way the forward clock restarts**, and the twelve trades are discarded. Doing that at
twelve trades costs two days. Doing it at two hundred costs the phase.

⚠️ **The ladder is the same class of defect and should be fixed in the same change**, not
separately: live quintiles are trailing-30-day, so `p80_edge` reads **0.0179** against the
published **0.0431**, and a bar at `btc_absret_1d` 0.0134 is sized **1.33×** where the ladder
that measured the regime effect would put it mid-pack. It costs only ~1.5 bps (arm C), but a
second restart to fix it would cost another clock reset.
