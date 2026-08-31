# M3 fidelity — the served policy is not the policy that was scored

**Status:** 🟢 **RESOLVED 2026-08-31 by option 1 of §5 — the cut and the ladder are frozen.**
The finding below is unchanged and is the evidence for the fix; §6 records what was changed
and what is still open. The forward paper test's first twelve trades are discarded.
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

🟢 **Resolved the same day.** Both quantities are now constants derived on the served run, the
served universe was chosen as the population to derive them on, and the forward clock restarts.
See **§6**.

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

### 4.1 🟢 The A/B has no B — resolved

🟢 **RESOLVED 2026-08-31 in the same change — see §6.6.** The finding, unchanged:

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

1. ✅ **CHOSEN 2026-08-31, at exactly this value — see §6.1.** Freeze the cut and make live match
   what was scored. Coverage stays 0.02 — this is *not* re-picking a searched dimension, it is
   making the implementation compute the dimension the way the scoring code did, so
   M3_PROTOCOL §0 is not engaged. **Consequence, stated honestly: the policy goes silent until
   volatility returns** — that is precisely the "correct silence" the dashboard was built to
   render, and it lengthens the calendar the forward test needs.
2. ❌ **Not taken.** Pre-register the floating cut as a deliberate new rule and serve it knowingly. It is
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

---

## §6 — What was changed, 2026-08-31

### 6.1 The decision, and the wrong turn taken on the way to it

**The constants in force:**

| | value | derived from |
|---|---|---|
| **cut** | **0.6318973898887634** | `coverage_threshold(conf, 0.02)` over seed 2's whole split |
| **ladder** | **[0.00391214806586504, 0.008861115202307701, 0.015078878961503506, 0.025166796520352364]** | `btc_absret_1d.quantile([.2,.4,.6,.8])` over BARS |

Run `20260819T142759Z` — **seed 2, the served checkpoint**
(`m2_multi_20260819T142759Z_a186182b.pt`) — 579,539 bars in the 240m head over the eight pairs
it was evaluated on. Recomputing both reproduces that seed's **arm A exactly: 483 trades, mean
size 1.362, entry confidence 0.6320 .. 0.7820.** That reproduction is the check that these are
the validated rule's constants and not merely plausible ones.

This is §5's option 1, at the value §5 named.

#### 🔴 The wrong turn, recorded because it is the same defect one level down

The first attempt froze at **0.5992**, O8's 12-pair cut, on the reasoning that the served
*universe* is twelve pairs so the constant should be derived over twelve. That reasoning is
half right and the conclusion is wrong: **O8 (`20260822T012619Z`) is a different trained
model.** The served checkpoint is seed 2, which has only ever been evaluated on eight pairs —
no 12-pair dump of it exists.

A confidence cut is a statement about **one model's confidence scale**, and
[NEXT_TRAINING_PLAN](./NEXT_TRAINING_PLAN.md) §1.5 already closed absolute-threshold-across-
checkpoints as *"not a lever, a defect"*: the same probability is 1.2% / 2.5% / 1.7% coverage
across three seeds of one configuration. Measured directly here:

| | |
|---|---|
| O8's cut **0.5992** applied to seed 2's bars | **4.01% coverage** — double the searched 0.02 |
| seed 2's cut **0.6319** applied to O8's bars | 0.95% coverage |
| median / p98 confidence | seed 2 **0.5194 / 0.6319** · O8 **0.5225 / 0.5992** |

Serving O8's cut would have roughly **doubled the trade rate** against the validated rule — a
smaller instance of the very defect this freeze exists to remove. The lesson generalises past
this incident: **a cut belongs to a checkpoint first and a universe second**, and "the served
universe" is not sufficient provenance for one.

#### ⚠️ The gap that remains, stated rather than papered over

The constants come from an **8-pair** split; **twelve** pairs are served. A fixed threshold
stays well-defined on a wider universe — it describes the model's confidence scale, which pairs
do not change — but the *realized coverage* will not be exactly 2%, and the four added pairs
were never scored on this checkpoint at all.

Closing that needs seed 2 re-evaluated over twelve pairs. That was **deliberately not done**,
for a protocol reason rather than a cost one: deriving a 12-pair cut for seed 2 would settle
the parked **"coverage at twelve pairs"** question (T6's count-matched cut is 0.01288) as a
side effect, and [M3_PROTOCOL.md](./M3_PROTOCOL.md) §0 says that needs its own pre-registration.
It is left open rather than answered by accident. `config_test.exs` asserts the direction that
matters — the eight derivation pairs must remain a **subset** of what is served.

⚠️ The frozen ladder's p80 is **0.0252**, not §1.8's published **0.0431**. Both are correct —
§1.8 measured on an earlier window — but every future comparison should be against 0.0252,
because that is the ladder in force. `/api/health` was changed to say so. 🟢 Note the ladder,
unlike the cut, **is** near-transferable: it is a quantile of Bitcoin's own trailing move, a
fact about the market rather than about a checkpoint, and O8's split puts the same four edges
within 2% of these.

### 6.2 The code

| where | change |
|---|---|
| `Trading.Policy` | New `frozen_threshold/0` and `frozen_regime_edges/0`, with provenance. `coverage_threshold/2` and `quintile_edges/1` stay — they are how the constants were derived — re-documented as derivations, not as the rule. |
| `Trading.Ledger` | `coverage_threshold/3` **renamed** `rolling_coverage_threshold/3`. Deliberate: a future reader must not be able to wire it back in believing it is "the" threshold. |
| `Trading.Regime` | Serves the frozen ladder. Still computes trailing quintiles, now reported as `trailing_quintile_edges` / `trailing_p80`. **Cold start dropped from 8 days of klines to 24 hours** — the edges are constants, so only the *value* needs a lookback. |
| `Trading.PolicyEngine` | Decides against the constant. `refresh_threshold/2` → `refresh_rolling_threshold/2`, which writes only the diagnostic and carries a note saying so. |
| `/api/health` | `confidence_threshold` (in force) beside `frozen_threshold` (this build's constant) and `rolling_threshold` (diagnostic); regime reports frozen and trailing side by side. |
| dashboard | The "Rank window" badge — a progress bar toward being allowed to trade — is replaced by **Cut (frozen)** and **Confidence vs cut**. The warmup explainer is replaced by a plain-language drift sentence. |
| `config/config.exs` | `served_pairs` carries the warning that editing it invalidates both constants. |

**There is now no warmup.** A constant cut needs no population to rank against, so the policy
is live from its first bar and `warm` is always true. The old ~14-hour wait is gone.

### 6.3 What is asserted, so this cannot regress quietly

* `config_test.exs` pins **both constants as literals** — not ranges, because O8's 0.5992
  looks entirely plausible beside 0.6319 and only an exact literal catches a constant taken
  from the wrong checkpoint. It also asserts the eight derivation pairs remain a subset of
  `served_pairs`. 🔴 If either fails, **re-derive — do not relax it.**
* It also asserts the ladder is monotone and spans all five buckets, so the SIZED variant
  cannot silently degenerate to a flat multiplier.
* `regime_test.exs` (new) pins that the ladder served is the frozen one even when the trailing
  quintiles are absent, and that readiness needs 24 hours rather than a week.
* `policy_engine_test.exs` asserts the **opposite** of the test it replaced: the first bar can
  trade. A second test seeds bars that rank to ~0.89 and checks a 0.70 bar still trades — i.e.
  the constant decided, not the window.
* `dashboard_live_test.exs` asserts the retired warmup vocabulary cannot come back, and that a
  running cut differing from the build's constant renders as a fault.

### 6.4 🔴 The forward clock restarts — the operational step

🔴 **Deploying is not enough.** The database still holds twelve trades taken under the retired
rule, and `Ledger.arm_summary/2` has no date filter — it aggregates **every** closed row for an
arm, forever. Left in place they would permanently blend two rules into every future A/B number
with no way to separate them.

**All four steps run on `fluxtrader-1`, in this order.**

```sh
# 1. Back up. Cheap insurance rather than a critical step: it is twelve rows, and §3 already
#    quotes every number that mattered. What it preserves is the raw per-trade detail.
docker compose exec postgres psql -U fluxtrader -d fluxtrader -c \
  "\copy (SELECT * FROM paper_trades) TO '/tmp/paper_trades_prefreeze_20260831.csv' CSV HEADER"
docker compose cp postgres:/tmp/paper_trades_prefreeze_20260831.csv ~/

# 2. Stop the app BEFORE truncating. RiskManager keeps its open-position count and daily P&L
#    in memory; deleting rows underneath a running app leaves those two out of sync with the
#    table. Stopping also means no bar is ever decided by a half-applied change.
docker compose stop app

# 3. Discard both arms. REQUIRED, not advisory: those trades ran a retired rule, and
#    `PaperTrade.@arms` no longer accepts the old `signal_only` arm name (§6.6).
docker compose exec postgres psql -U fluxtrader -d fluxtrader -c "TRUNCATE paper_trades"

# 4. Bring the app up on the new code. The restart clears the in-memory daily P&L (-26.78)
#    and the open-position count along with it.
git pull && docker compose up -d --build app
```

🟢 **`policy_bars` is NOT reset, and that is a change from 2026-08-29.** It was reset then
because the bar log *was* the rule — an 8-pair era inside the 14-day window would have made the
live cut a mixture of two rules. The cut no longer reads from it, so the log is now pure
forward evidence plus the drift diagnostic, and keeping it preserves the record of what the
model said during the twelve trades.

**Verify after restart** — `/api/health`:

* `policy.confidence_threshold == policy.frozen_threshold == 0.6318973898887634`;
* `policy.warm` is `true` **immediately**, not in fourteen hours;
* `regime.quintile_edges` is the frozen four, `regime.frozen_p80` is 0.025166796520352364;
* `policy.rolling_threshold` is present and **below** the cut (August's confidence tops out
  near 0.569) — that is the calm market, and the expected reading;
* `skips.below_coverage` climbs while `decisions` stays empty. 🟢 **That is the system
  working.** `skips.warming_up` should never appear again;
* `ab` lists the arms as **`policy`** and **`flat_size`**, both at zero trades. `signal_only`
  must not appear — if it does, the old binary is still running.

### 6.5 Still open — not fixed by the freeze

* 🟢 **§4.1, the A/B has no B — RESOLVED, see §6.6.** The control is re-registered as *the same
  bars as the policy, at flat size*.
* 🟡 **§4.2, the daily loss limit biases the mean upward** by truncating losing days. Not
  addressed here. Either document the bias or record suppressed entries as counterfactual bars.
* 🟡 **Coverage at twelve pairs.** Still 0.02, still un-re-registered. T6's count-matched cut is
  0.01288. Freezing did not touch coverage and deliberately does not settle this.
* ⚠️ **The freeze cannot survive a checkpoint change on its own.** `served_pairs` is guarded by
  a test; the served *checkpoint* is not. Swapping `m2_multi.pt` for a retrained model silently
  invalidates both constants, and nothing currently fails when that happens.

---

## §6.6 — The control arm, re-registered in the same change

**Decided 2026-08-31**, alongside the freeze and before the restart, because both need the same
clock reset and doing them separately would cost two.

### What changed

`signal_only` — *every bar M2's own serve gate approves, flat size* — becomes **`flat_size`**:
**the same bars as the policy arm, at size 1.0.**

| | before | after |
|---|---|---|
| arm name | `signal_only` | `flat_size` |
| entry | `bar.gated` from M2's serve gate | the policy's own entry decision, delegated |
| size | 1.0 | 1.0 |
| what the A/B measures | the rule vs M2's raw gate | **the regime size ladder** |

### Why

The old control **could not produce data.** No bar had been gated across all 8,184 bars since
the 2026-08-29 reset; the served checkpoint has emitted no gated signal since **2026-06-29**.
It stood at 0 trades against the policy arm's 12 and would have stayed there for as long as the
calm lasted — which nobody controls and nobody can date.

The new control measures the policy's own central claim. M3-2 holds the entry set constant bar
for bar and finds the ladder worth **+8.6 bps on the worst window** — the whole difference
between failing Tier 1 and passing it. That claim has never been checked forward, and now is.

### How the one-variable property is enforced

`Policy.decide_flat/3` **delegates to `Policy.decide/3`** and overrides only `size`. There is
one entry rule, in one function, so the arms cannot drift apart under a later edit into a
two-variable comparison. It deliberately keeps the `:no_regime` skip even though a flat size
needs no regime value — dropping it would let the control enter bars the policy refuses.

`policy_test.exs` asserts the arms agree on **every skip reason** (`below_coverage`, `no_side`,
`position_open`, `no_regime`, `warming_up`) and on every entry field except `size`;
`policy_engine_test.exs` asserts the same end to end through the ledger.

### 🔴 Read the right column

Compare the arms on **net bps per unit of notional**, not per trade. The policy arm varies size,
so its per-trade mean is size-weighted and is flattered by exactly the quantity under test.
Offline the same policy is +15.03 per trade against +11.24 per unit of notional.

### The acknowledged divergence

The policy arm passes through `RiskManager`; the control does not, because a control that could
be refused for lack of a slot would flatter the policy by throttling only its competitor. So a
risk refusal leaves a pair held on one arm and not the other until both are flat.
`risk_rejections` on `/api/health` is where that shows, and a non-empty map is the signal to
discount the comparison over that period. `policy_engine_test.exs` pins the behaviour: with
`max_positions: 0` the policy arm opens nothing and the control opens anyway.

### Protocol note

This is a **re-registration**, recorded with its date and with the original preserved verbatim
in [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) §4.2. It passes M3_PROTOCOL §0's test — it was
not chosen after seeing which control looked better — because the control had **zero** trades
when it was made, the policy arm's twelve are discarded in the same change for an unrelated
reason, and the trigger is a structural fact (`last_gated_at: null`) rather than a result.

⚠️ **The renamed arm is why `TRUNCATE paper_trades` is now required rather than merely
advisable.** `PaperTrade.@arms` no longer accepts `signal_only`, so leaving the old rows in
place would leave twelve rows whose `arm` value the schema rejects.