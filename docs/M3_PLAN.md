# M3 Implementation Plan — the trading policy

**What this document is.** The plan for the M3 milestone — the trading policy — and the
record of what each of its steps established. **Every build item is complete.** It is not a
status page: [BACKLOG.md](./BACKLOG.md) is the entry point for everything open, parked or
closed, and §0.0 below says which four documents hold the live state.

**Status in one line:** the rules baseline is M3's policy, it is wired to a crossing executor
and paper-trading on `fluxtrader-1`, and the next investment is the walk-forward folds.

*Written 2026-08-24, at the moment M2 froze. This document is the plan for the whole
milestone; it holds only what is currently true and actionable. When a step's conclusions
are superseded, move the narrative to `docs/archive/TRAINING_HISTORY.md` and carry the
surviving conclusion forward — do not append a contradicting section.*

---

## §0.0 — STATUS: START AT THE BACKLOG

**Every M3 build item is done — M3-0a, M3-0b, M3-1, M3-2, M3-3, M3-4, M3-5.** The rules
baseline `cov0.02_hold240_rqnone_mcnone_SIZED` cleared the pre-registered Tier-1 bar, the
learned policy did not beat it, so that rule is M3's policy; it is wired to a crossing
executor and paper-trading on `fluxtrader-1`. What is left is not work in this document.

👉 **[BACKLOG.md](./BACKLOG.md) is the entry point** — the single index of every open, parked
and closed item across every wavefront, with the revival trigger for each. This file no longer
carries a running status; it carries what M3 *is*, what each step established, and the
decisions behind the design.

**The four documents that hold the live state:**

| for | read |
|---|---|
| everything open, parked or closed, with triggers | [BACKLOG.md](./BACKLOG.md) |
| the rules that govern a promotion, and Amendment 2 | [M3_PROTOCOL.md](./M3_PROTOCOL.md) §9 |
| what actually runs live, and how to read `/api/health` | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) |
| the next investment — walk-forward folds, pre-registered | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) |

**Two things a reader of this file needs to know before quoting any number in it:**

🔴 **The candle-poll defect.** Every stored candle between 2026-07-18 and 2026-09-03 was a
partial bar ([CANDLE_POLL_DEFECT.md](./CANDLE_POLL_DEFECT.md)). The data is repaired and the
three checkpoints were re-scored on it: the incumbent still passes Tier 1 (worst window
−4.61 bps, pooled +13.82 net at taker), and 0 of 8 learned runs pass
([M3_2_RESULTS_REPAIRED.md](./M3_2_RESULTS_REPAIRED.md),
[M3_3_RESULTS_REPAIRED.md](./M3_3_RESULTS_REPAIRED.md)). **Numbers below this line that were
measured before 2026-09-04 are pre-repair** — they are kept because they are what the
decisions were taken on, and the repaired re-score moved them by about a bar's width, not by
a conclusion.

🔴 **The served constants belong to a checkpoint, not to this document.** Cut
`0.6296127438545227`, ladder p80 `0.025596268475055695`, checkpoint
`m2_multi_20260819T142759Z_a186182b.pt`. The policy refuses to trade unless `ml_inference`
reports that checkpoint's sha256 (M3_PROTOCOL §9.5). Do not copy a constant out of a results
file into a config.

**New to this document?** **§0.5** explains what M3 is in plain language — every term defined,
the strategy in dollars, and a direct answer to "can it trade profitably yet?".
**GPU required:** no, for any step in this document (§0.3). **Keys required:** no.

**Where the per-step record lives:** each step's own entry in **§2**, and the three sections
other documents cite as **§0.6** (the traded universe), **§0.7** (the M3-4a audit) and
**§0.8** (the execution-cost result) are now at the end of §2, with those headings unchanged.

**Related:** [M3_0B_RESULTS.md](./M3_0B_RESULTS.md) · [M3_PROTOCOL.md](./M3_PROTOCOL.md) ·
[M3_3_PROTOCOL.md](./M3_3_PROTOCOL.md) · [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) ·
[M3_2_RESULTS.md](./M3_2_RESULTS.md) · [M3_3_RESULTS.md](./M3_3_RESULTS.md) ·
[M3_4_RESULTS.md](./M3_4_RESULTS.md) · [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) ·
[T6_RESULTS.md](./T6_RESULTS.md) · [NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) §1.3/§1.5/§1.8 ·
[BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) · [PLAN.md](./PLAN.md) Phase M3

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
./scripts/m3.sh -m m3 bookprep         # M3-4a: the data-quality audit (no fill number)
./scripts/m3.sh -m m3 execcost         # M3-4: the execution-cost study itself
./scripts/m3.sh -m m3 sidetable        # M3-0b: the price/funding table, its acceptance
                                        #        test, the funding term and the live brake
./scripts/m3.sh -m m3 bookera          # B0: the book-era table, on the same alignment
./scripts/m3.sh -m m3 policy --help     # score one policy spec
./scripts/m3.sh --shell                 # interactive
```

`ml/train` is bind-mounted into the container, so host edits take effect with no rebuild.
🔴 **The M3-4 book/tape export is ~2 hours of Postgres work and is easy to lose.**
`\copy ... TO PROGRAM` writes inside the **postgres container**, so killing the script locally
does NOT stop it and the finished file survives there. After an interruption, check the
container (`docker compose exec postgres ls -lh /tmp/m3_export`), verify it with `gzip -t`, and
re-run with `COLLECT=1 ONLY=<slice>` — never re-issue the COPY. `ONLY=` restricts the run to
named slices so the cheap ones can be re-pulled without the ladder.

The four prediction dumps live in `ml/train/output/eval_dumps/` (gitignored, ~125MB); if
they are missing, re-fetch them:

```sh
mkdir -p ml/train/output/eval_dumps
for RUN in 20260818T185438Z 20260819T142759Z 20260820T025723Z 20260822T012619Z; do
  gcloud storage cp "gs://fluxtrader-train-artifacts/eval/$RUN/eval_preds.parquet" \
    "ml/train/output/eval_dumps/eval_preds_$RUN.parquet"
done
```

### What M3-3 says NOT to do

Do not widen the learned grid, extend the feature list, or reach for a larger model class —
M3_3_PROTOCOL §4.1 and §7 pre-registered that a linear failure is not evidence a bigger model
would succeed, and §D2's ablation is evidence in the opposite direction. Do not re-tune the M3-2
winner against the same evidence either. The binding constraint is ~220 independent trading days,
and no rearrangement of them fixes that — **only forward time does**, and as of 2026-08-28 that
clock is running (item 3). The right response to "the numbers are not significant yet" is now to
let the paper arms accumulate, not to re-analyse the same 253 days.

---

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
| **the 5 bps** | the **maker** equivalent: 2 bps fee + 0.5 bps slippage, doubled = 5 bps = 0.05% per trade. 🟢 **Measured, and superseded** — see §0.5.5: resting is not worth it. 🔴 The *fee* half of both numbers (4 bps taker / 2 bps maker per side) is still an unverified assumption about our VIP tier — `mix flux.fee_tier` checks it and needs account keys. |
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
2. 🟢 **This one is now MEASURED, and it moved in our favour** (M3-4, 2026-08-28 — §0.8).
   It used to read "half the economics rests on an untested assumption". Both assumptions were
   tested and both were wrong. **Crossing costs 9.84 bps round trip, not 14** — so the edge
   after costs is nearer **+19 bps than +15**. And resting limit orders turn out **not** to be
   worth it: the fills you get are the ones where price is running through you, and the
   adverse move is larger than the fee rebate in every pair and direction tested. The
   remaining caveat is that the cost was measured in the calmest month of the period, so treat
   9.84 as the optimistic end (§0.8).
3. 🟢 **It is connected and deployed** (M3-5, built 2026-08-28, live on `fluxtrader-1` since
   2026-08-28 — [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md)).
   This used to read "nothing is connected: the policy exists only inside the offline
   backtester". The live executor now crosses the spread, holds four hours, sizes on the live
   BTC-volatility quintiles, charges the **measured** per-pair cost, and passes every entry
   through the hard risk limits. A signal-only control arm runs beside it. It is **paper** —
   nothing is sent to Binance, and the `auto` order path is unsigned so nothing could be.

**The honest verdict: we have a credible, well-tested candidate strategy, slightly better
economics than we thought, and a paper harness ready to collect the evidence it needs.** The
bottleneck is no longer engineering; it is **deploying it and then calendar time**. Nothing on
the list buys as much as getting the forward test running.

⚠️ **And a fact that changes what "paper-trade forward" will look like:** the served model has
emitted **no gated signal since 2026-06-29**, because the market has been unusually calm and
this strategy only fires in volatile conditions (§0.8). A forward test started today may sit
idle for weeks. That is the strategy working as designed, but it means **the calendar cost of
accumulating independent days is longer than the trade rate suggests** — 2.3 trades/day is an
average over a period that included volatile months.

#### 0.5.5 🟢 ANSWERED 2026-08-28 — what the fills actually cost

**This subsection was the open question. M3-4 closed it; the result is §0.8 and the full
workings are [M3_4_RESULTS.md](./M3_4_RESULTS.md).** The answer, in one line: **crossing is
much cheaper than we assumed (9.84 bps, not 14) and resting is not worth it (the fills you get
are the bad ones).** The reasoning below was written *before* the measurement and predicted
both halves correctly, so it is kept as the argument — but read §0.8 for what was actually
found.

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

🟢 **Both were measured, and the prediction above held.** Crossing a $10,000 order costs
**9.84 bps round trip** — the assumed 3 bps/side of slippage was indeed almost entirely
fictional on the majors. Resting saves 3.60 bps on the fee arithmetic, but the fills are
adversely selected in **16 of 16 pair/direction cells**, so that saving is an accounting
artifact rather than money.

**The 22-day worry turned out not to bind, for a structural reason worth remembering:** a
*cost* is nearly a deterministic function of the order book, while an *edge* is a return. The
realized minimum detectable effect was **0.13 bps**, not the several bps §4 feared. Measuring
what trading costs on 23 days is simply not the same statistical problem as measuring whether
a strategy makes money on 220.

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

### M3-0b — ✅ DONE (2026-08-29). The price/funding side-table exists and is proven.

**Result: [M3_0B_RESULTS.md](./M3_0B_RESULTS.md).** Implemented as `ml/train/m3/sidetable.py`;
run with `./scripts/m3.sh -m m3 sidetable`. The 5m price path plus the funding rate, over
2025-11-15 .. 2026-08-30 for all twelve pairs, on the dumps' own `(pair, ts)` grid — and,
built by the same module in the same alignment, `BOOK_ERA_PLAN.md`'s **B0**
(`./scripts/m3.sh -m m3 bookera`). One alignment, two consumers, exactly as planned.

**The acceptance test is what makes it usable, and it passed on all four dumps:** 2,655,988
bar-comparisons, **every one exact** after a float32 round-trip (the dumps store `fwd_ret` as
float32, so exactness is a sharper test than any tolerance), with nothing unmatched. B0's
table passes the same test independently over the book-era overlap.

**What the four consumers turned out to be worth** is in §0.0 and in the results document.
The short form: the live 2%/4% brake costs **10.5 gross bps/trade**; funding is **+0.14
bps/trade**, a rounding error; **C4b is answered** — barrier exits all lose to the fixed 4h
hold; and position-state observations are now buildable but gated on a pre-registration.

**Two things this step corrected in this document:**

* ⚠️ **"The data is already on disk" was false.** The M3-4 export is the 23-day book era,
  because the ladder does not exist before 2026-08-05 — but M3-0b's price path must span the
  eval validation window, and **96% of the policy's trades fall outside the book era**. The
  price/funding slice is now its own export into `ml/train/output/m3_0b/`, and
  `scripts/gcp_m3_export.sh` documents the two windows and the two invocations.
* ⚠️ **Funding is not "a real term in the P&L, not a rounding error"** at a 4h hold, which is
  what this section asserted. It is +0.14 bps/trade. The assertion was reasonable and it was
  wrong; measuring it is what settled it.

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

### M3-4 — 🟢 DONE 2026-08-28. The execution-cost study, measured offline from data we already hold.

*Result: [M3_4_RESULTS.md](./M3_4_RESULTS.md), read via §0.8. Crossing costs 9.84 bps round
trip, not 14; the maker arm is not worth building. The rest of this section is kept because it
documents the data sources and their measured defects, which the next study will need — not
because anything in it is still to be run.*

**The question in one line:** is the 5-bps maker round trip that doubles every published number
actually obtainable, for these pairs, at these sizes?

**Why it is ranked above every remaining knob.** It does not add a result — it can *invalidate*
results already published. At taker the whole cov05 slice is −5.09 net; at maker it is +3.91. The
M3-2 winner is +15.0 taker / +27.1 maker. No other open item can move numbers already in
[M3_2_RESULTS.md](./M3_2_RESULTS.md) in both directions.

**The data source, and why it was not the paper-sim stack.** §3.3 originally said to measure
this live on the paper-sim stack. That was not viable at the time and the reason was concrete:
`Trading.Executor` was an 86-line stub with no fee model, no fill logic and no hold timer, so
building order simulation first would have put days of work in front of the first number.
Measuring offline was the right call twice over — the answer it produced (**cross, always**)
then removed the whole limit-order path from what M3-5 had to build.

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

### M3-5 — Wire the rule to the executor 🟢 DONE 2026-08-28

**Result: [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md)** — read that for what runs, how to read
`/api/health`, and the six places the live rule differs from the backtested one. This section
records what was asked for and what was delivered against it, and nothing more.

PLAN.md's M3 row listed two work items no earlier step had touched: **"Integrate — Elixir
Executor + hard RiskManager always on"** and **"A/B — signal-only vs signal+policy in
simulation"**. §6's last open box — *the policy never bypasses hard `RiskManager` limits* —
could not be checked while nothing called the policy. All three are now closed.

| what M3-5 had to add | delivered |
|---|---|
| **1. The M3-2 rule, expressed once** — top-2% confidence rank, side from M2, the ⅓..5/3 regime multiplier, a 4-hour hold, no concurrency cap. ⚫ *This row read "§1.3.3 binds: the coverage condition is **rank-based**, so it needs a trailing distribution, never a fixed threshold." **That inference was wrong and is corrected below.*** | `Trading.Policy`, pure and stateless. ⚫ *As built, the cut was ranked over a trailing 14 days of `policy_bars` and the ladder over trailing klines; **both were frozen to constants on 2026-08-31** ([M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md)).* Parity with `ml/train/m3/backtest.py` is pinned by fixtures generated from that file |

🔴 **The correction to row 1, because the reasoning matters more than the line of code.**
§1.3.3 says a *condition* must be rank-based rather than thresholding an absolute predicted
edge — the level of the edge swings 25.9 bps across windows, so an ordering survives what a
level does not. That is right, and it is why the cut is *derived* as a rank instead of guessed.
It does **not** follow that the rank must be re-taken live over a trailing window. `backtest.py`
takes it **once, over the whole split**, and that single number is what every published M3
figure measures. Re-ranking live produces a different rule: a trailing rank admits 2% of bars in
every window **by construction**, including windows the scored rule sits out entirely. The
lesson is narrower than "rank, never level" — it is **rank over the scoring population, then
freeze**, and the population is part of the rule.
| **2. The coverage decision from §3.1** — the policy owns coverage, the serve gate becomes a diagnostic | Done, and one gate more than §3.1 counted: `RiskManager`'s hard-coded `confidence < 0.65` was a **fourth** gate and is now `min_confidence`, default `0.0` |
| **3. A real fill and fee path**, using whatever M3-4 measured | `Trading.ExecCost` carries the measured per-pair round trips. **No maker branch, no queue model, no fill simulation** — M3-4's adverse-selection panel removed all of it |
| **4. The A/B**, scored on M3_PROTOCOL §4's metrics | Both arms live on the same bars; `Ledger.ab_summary/1` and `/api/health`'s `ab` block. Pre-registered in [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) §4 — ⚫ *re-registered 2026-08-31; the original is kept verbatim at §4.2 there* |
| **5. The risk-limit assertion** | `risk_manager_test.exs` (refusal on each hard limit) and `policy_engine_test.exs` (the engine opens nothing when refused). 65 tests, all passing |

**Why this mattered beyond tidiness, and still does:** §0.5.4 and risk #4 land on the same wall —
~220 independent trading days is not enough to certify a 15-bps edge, and no re-analysis of the
same 253 days relieves it. **Paper trading forward is the only mechanism that manufactures new
independent days.** That clock is running, and it was **reset on 2026-08-31** when the twelve
trades it had collected turned out to belong to a different rule. It will run slowly — not
because of a warmup (the frozen cut has none) but because the market has been the calmest of the
period since July and the validated rule takes nothing in a calm market. An idle month is the
strategy working rather than failing.


### What the completed steps established — the sections cited elsewhere as §0.6, §0.7, §0.8

*Moved here from the status block on 2026-09-04 (RULES_REVIEW §6.3). The headings and the
numbering are unchanged, because other documents cite them; only their position moved.*

### §0.6 — What was measured on 2026-08-27, after M3-3 closed — the universe is NOT a policy lever

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


### §0.8 — What M3-4 established (2026-08-28) — both assumptions were wrong, in opposite directions

**Full results: [M3_4_RESULTS.md](./M3_4_RESULTS.md) — all nine items §6 of the protocol
requires. Implementation: `ml/train/m3/execcost.py`, run with `./scripts/m3.sh -m m3 execcost`.**
The short version, no statistics required:

1. 🟢 **Crossing the spread costs 9.84 bps round trip, not 14.** Measured over 51,398
   decisions on 23 day-clusters, walking the real 20-level ladder for a $10,000 order instead
   of assuming 3 bps/side of slippage. The 95% interval is **[+9.75, +9.93]** and it excludes
   14 by a wide margin, so the assumption is **MIS-STATED** in the pre-registered sense — and
   it is wrong in the direction that made **every published M3 number too pessimistic**.
   §1.6(b) predicted exactly this before the study ran.
2. 🔴 **The maker arm is not worth building, and the reason is not the fee.** On the cost
   arithmetic alone, resting saves +3.60 bps [+3.34, +3.86] against a ~5.6 bps ceiling — which
   reads like a win. **§3's adverse-selection panel contradicts it in 16 of 16 (pair,
   direction) cells.** The half-spread earned is 0.007–1.42 bps; the 60-second adverse drift
   is 0.66–2.13 bps. A resting buy fills *because* the price came down through it, and it
   keeps going. **The +3.60 is a fee-rebate accounting gain, not a trading gain.** §3 made
   that panel a precondition of publishing a maker verdict precisely so this could not be
   missed.
3. 🟢 **This simplifies M3-5 rather than complicating it.** The conclusion is the one §5.2
   named as "the outcome that lets M3-5 build a simple crossing executor and stop there" — a
   useful result, not a failure. **No limit-order machinery, no queue modelling, no fill
   logic.** That is days of work M3-5 does not have to do.
4. 🔴 **The study was far better powered than the protocol feared, and the reason is
   structural.** §4 worried that 22 day-clusters could not resolve a 4 bps effect. The
   realized MDE is **0.13 bps for Q1 and 0.37 for Q2**. A *cost* is a nearly deterministic
   function of the book — spread plus a constant fee — while a *P&L* is a return. Measuring a
   cost on 23 days is not the same statistical problem as measuring an edge on 220, and the
   stopping condition §5.3 pre-registered never came close to binding.
5. 🔴 **The re-score re-orders the grid, and nothing may be promoted on it.** At the measured
   cost `cov0.01_hold240_rq0.8_mcnone` shows a **+17.49** bps worst window against the
   winner's **+2.43**. It remains **ineligible**: its thinnest window holds **23** trades
   against P4's floor of 100, and a trade count does not move when the fee does. This is the
   finding §5.4 says to report and pre-register, never to act on — *the hard regime filter
   looks better at a truer cost and is still starved in window 3.* The winner's own worst
   window improves **+0.25 → +2.43**, so it still clears the bar with more room.

#### 🔴 The validity problem the run surfaced, which no protocol section anticipated

**The M3-2 winner books ZERO trades inside the 22-day ladder window.** §2.4 had sized L3 at
"~18 per pair". The winner's last entry anywhere is **2026-07-16**, three weeks before the
ladder begins.

The cause is not a bug, and it is the most operationally important thing in this section:
**the model stops being confident when the market goes quiet, and the market has been quiet
since July.** `btc_absret_1d` averages **0.0070** in August against 0.011–0.027 in every
earlier month — the calmest stretch of the whole 253 days — and confidence dispersion collapses
in step (sd **0.0127** in August against 0.023–0.047 earlier). No bar after 2026-07-16 reaches
the top-2% cut on **any** of the three seeds, and

> 🔴 **the served checkpoint (seed 2, gate 0.6311) has produced no gated signal since
> 2026-06-29.**

That is the policy correctly sitting out a regime it has no edge in — §1.8's whole finding is
that the edge lives in volatile bars — but it has two consequences worth carrying forward:

* **M3-4's cost is measured in the one regime the policy never trades in.** The study sizes
  that gap rather than waving at it: cost by BTC-volatility quintile runs **9.77 → 10.09 bps**
  from the calmest fifth to the most violent. The extrapolation is worth about **0.3 bps**
  against a 4 bps gap to 14, so **the Q1 direction survives comfortably** — but treat 9.84 as
  the optimistic end, not as the number to re-publish M3-2's economics with. (Note the maker
  saving *shrinks* to 2.74 in the top quintile, which points the same way as the adverse
  selection panel.)
* **A live system that has been silent for two months is indistinguishable from a broken
  one.** 🟢 **Done 2026-08-28 (M3-5):** `GET /api/health` now reports bars seen, bars and
  seconds since the last gated signal, the live coverage cut, and a named count of every reason
  the policy skipped a bar — so silence is visibly *correct* rather than merely quiet.



## §3 — DESIGN DECISIONS TO SETTLE BEFORE WRITING CODE

### 3.1 Where the gate lives — 🟢 SETTLED 2026-08-28: the policy owns coverage

Today `serve.py` gates and the Elixir app gates again, both off `ML_GATE_THRESHOLD`. If the
policy *also* gates, there are three gates in series and **the policy only ever sees bars M2
already approved** — it can never choose to widen coverage, which §1.3.1 makes a first-class
decision variable.

`/predict` already returns raw confidences next to `gated`, so the app can ignore the serve
gate with no serve-side change. **Decided and implemented: the policy owns coverage; `serve.py`'s
gate is a reported diagnostic, not a filter** — it is recorded on every bar. ⚠️ It was *also*
the A/B control arm's entry condition until 2026-08-31, when the control was re-registered
because that gate had not fired since 2026-06-29 and the arm could not produce data; `gated`
is now purely a diagnostic. M3-5 also found a **fourth** gate this section had not counted:
`RiskManager` refused anything under `confidence < 0.65`. That is not a risk limit — it could
only ever narrow what the policy chose — and it is now `min_confidence`, defaulting to `0.0`.

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

`docs/archive/QUANT_AB_HANDOFF.md` closed the quantile head with an explicit **"defer, don't
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
| 7 | 🟢 **CLOSED 2026-08-28 — the policy is connected.** Was: the milestone's output lived only in `ml/train/m3/` and the live executor had no fees, no fill logic and no hold timer, so §6's last exit criterion could not be tested | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md). Sequencing it after M3-4 paid off exactly as intended: the fee study removed the entire limit-order path from the build. **What replaces it as a live risk is narrower and is filed in [BACKLOG.md](./BACKLOG.md):** the fee tier is unverified, and the `auto` order path is unsigned |
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
- [x] **The maker-fee assumption is measured rather than assumed** (M3-4) — done 2026-08-28.
      [M3_4_RESULTS.md](./M3_4_RESULTS.md) §1 publishes the per-pair round trip and §5 re-scores
      the grid at it: the winner's worst window is +2.43 bps against the +0.25 promotion bar.
      Crossing costs 9.84, not 14; the maker arm is not worth building.
- [x] The policy never bypasses the hard `RiskManager` limits — closed 2026-08-28 by M3-5.
      Every policy entry goes `Policy.decide/3 -> RiskManager.check/1 -> Executor.open/3`, in
      **every** mode including `simulation`, so the risk path is exercised continuously rather
      than only on the day someone flips to `auto`.
      `apps/fluxtrader/test/fluxtrader/trading/risk_manager_test.exs` asserts refusal on each
      hard limit and `policy_engine_test.exs` asserts the engine opens nothing when refused.
- [x] **The A/B runs in paper simulation** — started 2026-08-28, ⚠️ **re-registered and its
      clock reset on 2026-08-31.** The control was *signal-only* and could not fire (M2's gate
      has been shut since 2026-06-29, so it stood at 0 trades against 12); it is now
      **flat-size on the policy's own bars**, which measures the regime ladder — the policy's
      own central claim. Compare the arms on net bps per unit of NOTIONAL, not per trade.
      Both arms are live on the same bars, charged the same measured per-pair cost, held the
      same four hours; `GET /api/health`'s `ab` block and `Ledger.ab_summary/1` score them on
      M3_PROTOCOL §4's metrics. The pre-registration is
      [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) §4. ⚠️ **Running is not the same as
      answered:** at 2.3 trades/day against a 259-bps per-trade sd, the arms will not separate
      at 15 bps for a long time — risk #4's constraint is unchanged, it is just now being
      worked against instead of waited on.

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

*Updated: 2026-08-29 — **every M3 build item is complete**: M3-0a, M3-1, M3-2, M3-3, M3-4a,
M3-4, M3-5 and M3-0b. The learned policy did not beat the rules baseline, so M3-2's rule is
M3's policy; it is wired to a crossing executor and paper-trading on `fluxtrader-1`. **No
build item remains — the milestone now advances on calendar time**, because the binding
constraint is independent trading days and only forward time manufactures them. The open
items are decisions and preconditions, not construction: the price of the live 2%/4% brake
([M3_0B_RESULTS.md](./M3_0B_RESULTS.md) §4), the unverified fee tier, and the unsigned order
path — all indexed in [BACKLOG.md](./BACKLOG.md). All existing protocols stay frozen. §0.0 is the live status block and the only
place that needs reading to resume; **§0.5 is the same thing in plain language, with the
vocabulary defined and the "can it trade profitably yet?" question answered directly.***

---

## §8 — The twelve-pair widening, 2026-08-29

*Moved here from `BACKLOG.md` on 2026-09-04 (RULES_REVIEW §6.3): the backlog is an index, and this is a decision record that belongs with the universe question it settles (§0.6).*

### The twelve-pair widening, 2026-08-29

**The served universe is now twelve.** This is not a reversal of T6 and not a new result. T6's
verdict was **"UNDECIDED — the incumbent 8-pair universe stands by default"**: the cleanly
separated universe effect is **−2.51 bps, 95% CI [−17.85, +12.83]**, on a period that resolves
nothing under ±37 bps. Eight was the conservative default while the four extras had no measured
crossing cost. That reason is now gone, and the standing intent has always been twelve for the
long run — so the default was retired rather than left to be re-derived from a results file that
reads like a closed decision.

🔴 **The case for twelve is throughput and diversification, NOT per-trade edge.** T6's point
estimate for the universe term is slightly negative. What twelve buys is more trades per day
against a milestone whose binding constraint is the number of independent trading days. Do not
quote this widening as evidence that twelve earns more.

**What made it safe, and what it cost:**

1. **Every served pair now carries its own measured crossing cost.** M3-4's run had in fact
   measured all twelve; the protocol reported the four added 2026-08-14 as "texture only" and
   excluded them from Q1's verdict, because pooling 14 days of ladder with 23 into a decision
   quantity is what M3_4_PROTOCOL §1.5 forbids. **That exclusion governs the verdict, not the
   charging** — a cost used to charge a trade is not a decision quantity, and a pair's own
   14-day number beats a constant pooled from eight *other* pairs. The study was re-run
   2026-08-29 and reproduced byte-identically before any constant was copied.
2. **ADAUSDT is why this was a real blocker and not a formality:** it measures **13.733 bps**
   against the pooled **9.842** it would otherwise have been charged — 3.89 bps light, about
   40%. Its spread alone (4.901 bps) is 1.7× the widest of the original eight.
   Full table: XRP 9.075, LINK 10.754, AVAX 11.401, ADA 13.733, each on 14 days / ~3,960 obs.
3. **`@pooled` was deliberately NOT re-pooled over twelve.** It stays the eight-pair,
   23-day number, per §1.5. Nothing served is charged it any more; it survives only as the
   flagged fallback for a pair that has never been measured at all.
4. **`max_positions` went 8 → 12.** T6 re-tuned the concurrency cap on both universes and
   `max_concurrent=none` won on both — every cap tried cost net bps. On twelve pairs a cap of 8
   is no longer "one slot per pair"; it is the binding cap T6 measured at **+13.21** against
   **+19.51** uncapped. Widening the universe without widening the cap would have silently
   imposed the constraint T6 said not to use.
5. **The bar log was reset.** The top-2% cut is a rank over whatever population is recorded, so
   an 8-pair era sitting inside the 14-day window would have made the live cut a mixture of two
   rules. 1,161 bars and **zero trades in either arm** were discarded — which is exactly why the
   change was made now. Backed up first to `~/policy_bars_8pair_20260829.csv` on the VM.

**Deployed and verified on `fluxtrader-1`, 2026-08-29 05:00 UTC** (commit `5815789`):

* `policy.served_pairs` and the new `policy.collector_pairs` both show the twelve;
* `exec_cost.measured_pairs` shows twelve, split `long_window_pairs` (8, 23d) /
  `short_window_pairs` (4, 14d);
* `risk.max_positions` is 12;
* `skips` holds only `warming_up` — **`not_served` is gone**, which is the expected reading now
  that the collector and the served set coincide, and is the signal to watch: a non-zero
  `not_served` from here means the two lists have drifted apart again;
* `orderbook_snapshots` kept flowing evenly on all twelve pairs across the restart (36 rows per
  pair in the following 8 minutes) — the deploy-day-defect-#2 failure mode did **not** recur;
* the rank window restarted at 0 and refills at **12 pairs x 288 = 3,456 bars/day**, so
  `warm: true` is expected around **2026-08-29 19:00 UTC**, ~14 hours after the reset.

🔴 **Coverage was deliberately NOT changed, and that is an open pre-registration.** At a fixed
cov 0.02 a wider universe takes **more** trades, not better ones — T6 measured **3.05/day at
twelve against 2.02 at eight**. Whether the served coverage should instead tighten to hold the
trade count fixed (T6's count-matched cut is **0.01288**) is a separate question. M3_PROTOCOL §0
forbids re-picking a searched dimension after seeing results, so it needs its own
pre-registration on the population it will be served from. It was not bundled into the universe
change. **Filed as parked below.**

🔴 **Do not change `served_pairs` again while the forward test is accumulating trades.** It
changes the rule, so the A/B would span two different policies — the same comparability break
M3_4_PROTOCOL §7 records for the trade-tape change. This widening was done deliberately in the
window before the first trade fired, and that window is now closing.

**Two defects found and fixed on the way, both latent:**

1. **"Seven days" was never true.** `Ledger.@min_rank_bars` is `7 * 288 = 2016` **bars**, and
   the count is pooled across served pairs — so it clears in ~21 hours at eight pairs and ~14 at
   twelve, never in seven days. Every document repeated the seven-day reading and the
   2026-08-28 deploy was mis-forecast on it. Corrected in `ledger.ex`, M3_PLAN §0.0, PLAN.md,
   M3_5_INTEGRATION §2 and this file.
2. **The collector whitelist fallback was narrower than what was being collected.** The DB row
   held twelve, but `config/config.exs` and `runtime.exs` both defaulted to eight (and
   `Settings.@default_pairs` to three). One lost row and collection on XRP/LINK/AVAX/ADA would
   have stopped, unrecoverably — deploy-day defect #2's failure mode with a different trigger.
   Both defaults now hold twelve, and `config_test.exs` asserts the fallback can never be
   narrower than the served universe.

**New invariant tests** (`apps/fluxtrader/test/fluxtrader/trading/config_test.exs`) assert the
three relationships that were individually plausible and jointly wrong: every served pair has
its own measured cost, the position cap is not narrower than the universe, and the whitelist
fallback is not narrower than the served set. 74 tests green.

---
