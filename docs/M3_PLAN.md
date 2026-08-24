# M3 Implementation Plan — the trading policy

**Status:** Not started. Blocked only on §2 R0 of [NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) (a 5-minute promote).
**GPU required:** **No — not for any step in this document.** See §0.3.
**Keys required:** No.
**Related:** [PLAN.md](./PLAN.md) Phase M3 · [NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) §1.3/§1.5/§1.8 (the evidence M3 consumes) · [SIMULATION.md](./SIMULATION.md) (the live paper-sim stack)

*Written 2026-08-24, at the moment M2 froze. This document is the plan for the whole
milestone; it holds only what is currently true and actionable. When a step's conclusions
are superseded, move the narrative to `docs/archive/TRAINING_HISTORY.md` and carry the
surviving conclusion forward — do not append a contradicting section.*

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

### 1.4 🔴 What M2 does NOT hand over — the Q1 harness was never committed

`btc_absret_1d` appears **only in `docs/`**. The script that computed the regime observables,
ran the AUC and quintile tables, and produced §1.8's numbers is not in the repository —
`git log` shows the closing wave committed `reaggregate_preds.py` and nothing else.

**M3-0a therefore has to rebuild it, and rebuilding it is the first task, not a preliminary.**
The construction is documented well enough to reproduce: `fwd_ret` at horizon *h*, shifted
back *h* minutes, is a lookahead-free trailing return, and the three horizons compound
exactly (verified to 3.2e-7), so every observable Q1 tested was derived from the dump itself
with no DB round-trip.

⚠️ **Re-validate it against the published table before trusting it**, exactly the way
`reaggregate_preds.py --validate` earns its keep: the rebuilt harness must reproduce
§1.8's cov05 quintile ladder for `btc_absret_1d` (−3.4 / −15.3 / +10.1 / +17.4 / +35.5,
`dir_acc` 0.517 / 0.494 / 0.545 / 0.579 / 0.618) and the +24.50 / +22.11 / +3.50 fixed-
coverage figures. If it does not, fix the harness before believing any policy number
built on top of it.

---

## §2 — THE SEQUENCE

Strictly ordered. Each step's output is the next step's input, and the ordering is the
protection against the failure mode in §0.4.

### M3-0a — Rebuild the regime harness and turn it into a policy backtester

**No new data. No GPU. Pure `pandas`.**

Extend `ml/train/reaggregate_preds.py`'s approach (it already has `wilson_lower_bound`,
`serial_pnl`, `report`, and fixed-coverage logic) into an event-driven simulator over the
three prediction dumps.

Must support, because these are the policy's actual degrees of freedom:

- **Entry by coverage rank**, not absolute confidence (§1.3.3).
- **Per-pair serial positions** — `simulate_pnl`'s existing rule: ignore new signals while a
  position is open, so overlapping entries are not double-counted.
- **Explicit exits.** At this step: time-based only (hold N bars). Barrier exits are M3-0b.
- **Fees at both 5bps maker and 14bps taker**, reported side by side. Never one number.
- **Concurrent-position caps** across pairs — the current `simulate_pnl` is per-pair and
  unbounded in aggregate, which is not a tradeable portfolio.
- **Regime conditioning** on the rebuilt observables.
- **Reporting:** net bps/trade, trades/day, max drawdown, daily Sharpe, and a **per-calendar-
  window breakdown** (§M3-1 depends on this).

🔴 **Acceptance test, and it is not optional:** with the trivial policy "enter when gated at
coverage *c*, hold 48 bars, exit", it must reproduce NEXT_TRAINING_PLAN §1.3's fixed-
coverage table **to the digit**. That reproduction is the only evidence the harness has not
drifted from `eval_m2.py`/`gate.py`, whose definitions it deliberately duplicates. It is the
same discipline that made Q1 and `reaggregate_preds.py` credible, and it costs one afternoon.

### M3-0b — The price/funding side-table (only when barrier exits are actually wanted)

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

**Do not start here.** A fixed-hold policy that works is worth more than a barrier policy
that cannot be validated, and M3-0a's acceptance test is only expressible in fixed-hold terms.

### M3-1 — Pre-register the evaluation protocol, before searching anything

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

### M3-2 — The rules baseline. Ship this before anything learned.

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

### M3-3 — A learned policy, only if it beats M3-2

PLAN.md already locks the family: **offline / bandit-style on logged rollouts, not
end-to-end price RL.** Keep it there.

**Observation vector** (from NEXT_TRAINING_PLAN §2):

- M2's per-horizon probabilities and confidences — as **coverage rank**, per §1.3.3;
- trailing market-move magnitude (BTC |ret| over 24h, or the pooled-universe equivalent);
- position state: side, age, unrealized PnL;
- optionally realized-vol context (see §3.4).

Promote it over M3-2 only on the pre-registered rule from M3-1, judged on the **worst**
calendar window.

---

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

**Measure it early.** A short live study on the paper-sim stack — quoted vs filled, queue
position, adverse selection on the fills you do get — is cheap and could reorder the entire
milestone. Do not let it stay an assumption until after a policy is built on it.

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
| 1 | **Overfitting the policy to 3,717 trades** | seconds per configuration, ≈9.5bps quintile SEM, and five interacting knobs | M3-1's pre-registered protocol, scored on the **worst** window |
| 2 | **The maker-fee assumption is untested** (§3.3) | it is the difference between +3.91 and −5.09 at cov05 — it can invert conclusions | measure fills on the paper-sim stack early |
| 3 | **The regime rule is not uniform in time** | fails in window 2, where 47% of its trades live (§1.8) | never report pooled; require it to survive walk-forward |
| 4 | **Sample size is the binding constraint** | ~3,700 cov05 trades is thin for a policy search | see §5 — the 12-pair dump is free power |
| 5 | **Calibration drift on a future checkpoint** | policy consumes `p_up`; three levers have already broken the scale | rank-based conditioning (§1.3.3); re-check brier on any new checkpoint |
| 6 | **The Q1 harness is unrecoverable / mis-rebuilt** | it is the foundation of the whole milestone and it is not in git (§1.4) | reproduce §1.8's published table before building on it |

---

## §5 — SAMPLE SIZE: THE 12-PAIR DUMP IS FREE POWER

NEXT_TRAINING_PLAN §2 files the 12-pair adoption as an optional deployment change that
"buys coverage, not edge". **That valuation was made for M2. It is worth more to M3**, where
risk #4 says sample size is the binding constraint: four more instruments is roughly 50% more
trades to search a policy on, at unchanged measured edge.

Crucially this costs **nothing**, and that is not a hope — it is already demonstrated.
O8 ran the 12-pair configuration and its dump exists: `reaggregate_preds.py` was validated
*against it*, reproducing O8's fixed-coverage table to the digit (+24.76 / +23.63 / +6.85,
NEXT_TRAINING_PLAN §7). So the extra trades are in the bucket today and the harness that
reads them already works.

**Pull O8's dump in M3-0a alongside the three baseline seeds.** Retraining is not required
to get more trades to *search* on; the ~8h of GPU that a proper 3-seed 12-pair adoption
costs buys the ability to *serve* twelve pairs, which is a separate decision belonging to
NEXT_TRAINING_PLAN §2.

---

## §6 — EXIT CRITERIA

From PLAN.md, sharpened with what M2 measured:

- [ ] The backtester reproduces §1.3's fixed-coverage table to the digit under a trivial
      fixed-hold policy (M3-0a acceptance test).
- [ ] The rebuilt regime harness reproduces §1.8's published quintile ladder (§1.4).
- [ ] A rules baseline (M3-2) is positive **net of taker fees in the worst calendar window**,
      not just pooled.
- [ ] Any learned policy beats that baseline on the pre-registered rule, judged on the worst
      window.
- [ ] Max drawdown is controlled and the trade rate is non-pathological (PLAN.md).
- [ ] The policy never bypasses the hard `RiskManager` limits.
- [ ] Long and short sides are reported separately (§1.3, side balance is not seed-stable).

---

## §7 — WHAT TO BRING BACK (for the next session)

*Results are deliberately analyzed in a fresh session for token hygiene, so a step is not
finished until the artifacts below exist.*

**Starting M3-0a — bring back:**

```sh
# the three seed dumps (no VM, no GPU; a throwaway venv with pandas pyarrow numpy is fine)
for RUN in 20260818T185438Z 20260819T142759Z 20260820T025723Z; do
  gcloud storage cp "gs://fluxtrader-train-artifacts/eval/$RUN/eval_preds.parquet" \
    "/tmp/eval_preds_$RUN.parquet"
done

# O8's 12-pair dump — free extra trades to search on, and it is known to exist (§5).
# `gcloud storage ls gs://fluxtrader-train-artifacts/eval/` gives the run id."
```

Then report:

1. The **acceptance-test output**: the harness's fixed-coverage table next to §1.3's, and
   whether they match to the digit. If they do not, that is the only finding that matters —
   stop and fix it.
2. The **rebuilt regime ladder** next to §1.8's published one (§1.4).
3. Which run ids have dumps in the bucket, and the trade count O8's 12-pair dump adds to
   the pooled cov05 sample (§5) — that number sets how much policy search the data can
   actually support.

**Finishing M3-1 — bring back** the committed protocol file: split definition, metric,
decision rule, and the number of configurations that will be searched. Before any search
output.

**Finishing M3-2 — bring back**, for the rules baseline: net bps/trade at **both** 5bps and
14bps, **per calendar window** with the worst window called out, trades/day, max drawdown,
daily Sharpe, and long/short split. Pooled-only numbers are not a result.

---

*Updated: 2026-08-24 — written at M2 freeze. Nothing in §2 has been started.*
