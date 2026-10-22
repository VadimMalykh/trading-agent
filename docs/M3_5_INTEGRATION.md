# M3-5 — the rule, wired to the executor

*Written 2026-08-28, when the integration was built. This is the record of **what runs**,
**how to run it**, **how to read what it produces**, and — the part that matters most —
**every place the live rule differs from the backtested one**. It is not a protocol: M3-5 is
an integration step, not a search, and M3_PROTOCOL §0 forbids re-tuning the policy against
the evidence that chose it. The one thing here that IS pre-registered is §4, the A/B, because
that produces new numbers.*

**Related:** [M3_PLAN.md](./M3_PLAN.md) §2 M3-5 (the specification) · §3.1 (where the gate
lives) · §0.8 (why signal liveness is on `/health`) · [M3_2_RESULTS.md](./M3_2_RESULTS.md) §D1
(the rule that was selected) · [M3_4_RESULTS.md](./M3_4_RESULTS.md) (the costs it is charged) ·
[BACKLOG.md](./BACKLOG.md)

---

## §0 — In plain language, before any jargon

A **basis point (bps)** is one hundredth of one percent, so 100 bps is 1%. **Crossing the
spread** means taking whatever price is on offer for an instant fill; **resting** means posting
an order and waiting for someone to come to it. **Gross** is before trading costs, **net** is
after. A **paper trade** is a trade we write down and score but never send to an exchange.

### What was built

Before this, M3's output was a rule in a Python file. Nothing in the running system called it,
so we could not tell whether it obeyed the risk limits, and we were not accumulating any new
evidence about whether it works. Now:

Every five minutes the model scores each of the twelve pairs we trade (eight until 2026-08-29).
Each score is written down. Any score at or above **0.6319** — a fixed number, which is where
the most confident 2% of the evaluation period began — is traded: long or short as the model
says, sized between **one third and five thirds** of a base position depending on how violent
the last 24 hours of Bitcoin have been, held for **four hours**, then closed. Every trade is charged the **real** cost of crossing the
spread on that specific pair, as measured in M3-4 — 8.0 bps round trip on Bitcoin, 14.1 on
WLDUSDT. Nothing is sent to Binance: it is all paper.

Alongside it, a second paper ledger runs the **control**: trade every signal the model's own
gate approves, at flat size, same four-hour hold, same costs. Comparing the two says what the
policy's coverage-and-sizing rule is worth over the raw signal.

### Can it trade profitably? — still the same answer, and it has not changed

**Not certifiably, and this milestone was never going to change that.** The offline edge is
real (+15.0 bps per trade net of the 14-bps cost that was assumed at the time, and better now
that the true cost is measured at 9.84), but 253 days of history holding roughly 220
independent trading days cannot establish a 15-bps-per-trade effect, and re-analysing those
same days never will. **Only forward time produces new independent days**, and this is the
machine that collects them. What M3-5 delivers is the collection, not the verdict.

### Two things to expect that look like faults and are not

*Rewritten 2026-08-31 by the freeze — the first item used to say the opposite.*

1. **It trades from its first bar; there is no warmup.** Entry is by a **fixed** confidence
   cut (0.6319), derived offline over the served checkpoint's whole evaluation split, so it needs no
   population to rank against. `/api/health` reports `"warm": true` immediately and always.
   ⚠️ Until 2026-08-31 entry was by a *trailing* rank and the policy did sit out its first
   ~2,016 bars; that rule was measured, cost the edge its sign, and was retired
   ([M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md)). Any document still describing a
   warmup is stale.
2. **It may then not trade for weeks.** The strategy only fires in volatile markets, and the
   market has been the calmest of the whole evaluation period since July — **the served
   checkpoint has produced no gated signal since 2026-06-29**, and August's confidence never
   exceeded 0.569 against the 0.6319 cut, so the validated rule takes **nothing** all month.
   That is the strategy correctly sitting out. It is exactly why `/api/health` and the
   dashboard report the cut in force beside a trailing diagnostic: so that correct silence is
   visible as correct, and so a reader can see *how far* below the cut the market is rather
   than guessing.

---

## §1 — What runs

| module | what it is |
|---|---|
| `Trading.Policy` | The rule, pure and stateless: the coverage cut, the quintile edges, the 1/3..5/3 size ladder, the 4h hold, and `decide/3`. **The rule exists here and nowhere else.** |
| `Trading.ExecCost` | M3-4's measured per-pair crossing cost. No maker branch, no queue model — see §3. |
| `Trading.Regime` | `btc_absret_1d`, rebuilt from Binance klines so a redeploy costs no warmup. ⚠️ Since 2026-08-31 the quintile edges it serves are **frozen constants**, not its trailing 30-day ones; the trailing ones remain as a drift diagnostic. |
| `Trading.Ledger` | `policy_bars` (the forward evidence, and the population the drift diagnostic ranks over — no longer the rule's own population) and `paper_trades` (both arms of the A/B), plus the scoring. |
| `Trading.PolicyEngine` | The loop: bar → rank → decide → risk check → order → 4h timer → close. |
| `Trading.RiskManager` | The hard limits, rewritten. Position cap, notional ceiling, daily loss, leverage. |
| `Trading.Executor` | The order path. Crossing only. Paper in `simulation` mode. |
| `GET /api/health` | Signal liveness, the current coverage cut, named skip reasons, both arms of the A/B. |
| `mix flux.fee_tier` | Checks the account's real commission rate against what every M3 number assumes. |

### The path a bar takes

```
SignalEngine polls inference every 30s
  -> PolicyEngine tick (30s)
     -> key the signal on the CLOSED bar it scored (bar_open_time)   one decision per bar, on the tick it is first served (§4.5; until 2026-10-21 the wall clock floored to the grid)
     -> INSERT into policy_bars (idempotent)                the population the 2% cut is taken over
     -> Ledger.coverage_threshold/3                         the k-th largest of the trailing 14 days
     -> Policy.decide/3                                     the rule
     -> RiskManager.check/1                                 hard limits, never bypassed
     -> Executor.open/3                                     crossing; a paper row in simulation
     ... 48 bars later, on the tick the EXIT bar (bar_ts + 240 min) is first served ...
     -> Executor.close/2 at that bar's close -> RiskManager.release/0 + record_close/1
```

The control arm branches off after `Policy.decide_flat/3` and goes straight to the
ledger: it is a measurement arm and never produces an order (§4).

---

## §2 — How to run it, and how to read it

✅ **Deployed to `fluxtrader-1` on 2026-08-28. The forward test is running and the clock has
started.** B4's collector fixes went out with it and are verified
([BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) §2 B4). The migrations ran at boot.

⚠️ **The host port differs between the two stacks.** Locally compose maps the app to **4001**;
on `fluxtrader-1` it maps to **4000**. Both are container port 4000. Using 4001 on the VM gets
a bare `Connection refused`, which reads exactly like a dead app.

```sh
# on fluxtrader-1
curl -s localhost:4000/api/health | jq
docker compose logs -f app | grep -E "OPEN|CLOSE|RiskManager"

# on the local stack
docker compose up -d postgres ml_inference app     # migrations run at boot
curl -s http://localhost:4001/api/health | jq
```

⚠️ **Every `docker compose restart app` triggers the full historical kline backfill** (four
intervals × every collected pair, `handle_info(:backfill_history, …)`), and while it runs it
shares the collector's mailbox with the book poll: expect roughly **ten minutes** of degraded
`orderbook_snapshots` cadence after any restart. Measure collection health only after
`Historical backfill complete`, or you will diagnose the backfill as a regression.

Tests — including the parity tests that pin the Elixir rule to `ml/train/m3/backtest.py`:

```sh
docker compose run --rm -e MIX_ENV=test -e POSTGRES_HOST=postgres app mix test
```

### Reading `/api/health`

| field | what it tells you |
|---|---|
| `signal_liveness.bars_last_24h` | Is the model being scored at all? Should be ~288 x pairs. |
| `signal_liveness.seconds_since_last_gated` | How long the system has been silent. `null` means never gated in the retained window — check it against §0's "no gated signal since 2026-06-29". |
| `policy.warm` | Always `true` since the 2026-08-31 freeze — a fixed cut has no warmup. Kept in the payload because the dashboard and this checklist read it; `false` now means only that the engine has not ticked yet. |
| `policy.confidence_threshold` vs `policy.frozen_threshold` | The cut the running engine is deciding with, beside this build's constant. 🔴 **They must be equal.** A difference means the VM is running a pre-freeze binary or the trailing rank has been wired back in, and its trades belong to neither rule. This is the single most important line on the page. |
| `policy.rolling_threshold` | 🟢 DIAGNOSTIC, decides nothing. What the retired trailing-14d rank would say today. Read it *against* the cut: below it means even the top 2% of recent bars does not clear the bar, so the policy is correctly taking nothing; above it means bars are clearing. Not an alarm in either direction. |
| `policy.served_pairs` | The twelve pairs the policy may rank and trade (eight until 2026-08-29). **This is not the collector's whitelist** — see §3.4; the two now hold the same twelve but remain separate settings, and the whitelist stays free to be wider. The invariant to check is not a count: **if this ever shows a pair `ExecCost` has not measured, the coverage cut is being taken over a population containing a trade we cannot price.** `exec_cost.measured_pairs` is the list to compare against, and `config_test.exs` asserts it. |
| `policy.checkpoint_bound`, `policy.served_candle_interval` vs `policy.expected_candle_interval` | The binding guard (M3_PROTOCOL §9.5). `checkpoint_bound` must be `true`, and it is only `true` when **both** the served checkpoint hash equals `frozen_checkpoint` **and** the candle interval `ml_inference` builds features on equals `5m`. 🔴 Added 2026-09-10: from the 08-24 promotion to 09-10 the VM served the right weights from **1m** candles, the hash matched throughout, and every live confidence sat ~0.05 below the offline value on the same bars — the forward test took no trades ([M3_FIDELITY_RESULTS §7.5](./M3_FIDELITY_RESULTS.md)). `served_candle_interval: null` means the running `serve.py` predates that fix. 🔴 Added 2026-09-11: the guard also requires `policy.served_closed_bars_only: true` — `serve.py` reporting that its features end on a **closed** candle. Before that it scored the still-forming bar and re-scored it every 30 s as the bar moved; the forward test's first trade opened on such a re-score ([M3_FIDELITY_RESULTS §7.6](./M3_FIDELITY_RESULTS.md)). `null` means an old `serve.py`. |
| `policy.skips` | Named reasons bars were not traded: `below_coverage`, `position_open`, `no_regime`, `no_side`, `not_served`, and the guard's five: `checkpoint_mismatch`, `checkpoint_unverified`, `interval_mismatch`, `interval_unverified`, `forming_bar_unverified`. **`bar_already_recorded` is the largest count on a healthy system** (2026-09-11): the engine ticks every 30 s but decides each `(pair, bar_ts)` once, on the tick that put it in `policy_bars`, so roughly nine of every ten evaluations of a 5m bar land here by design. `bar_not_recorded` (the ledger insert failed, so the bar was not decided either) should be zero. **Added 2026-10-21 (§4.5):** `signal_unusable` — a signal with no 240m head, no price or no `bar_open_time` (a `serve.py` predating `last_closed_bar_open_time`); should be zero. Under `policy.decisions`: `closed` (the timer close at the exit bar's close), `close_deferred_bar_pending` (due on the clock, the exit bar not yet served — a few per close is normal), `closed_at_mark` (no exit bar within 15 min of its open; closed at the mark — should be zero on a healthy system), `close_deferred_no_price`.
 ⚠️ `warming_up` should **never appear again** — if it does, the running binary predates the freeze. **A silent system with a populated `skips` map is working.** `not_served` counts bars for collected-but-not-traded pairs; since 2026-08-29 the collector and the served set hold the same twelve, so it should now be **zero** — a non-zero value means the two lists have drifted apart. |
| `policy.risk_rejections` | Counted refusals by reason. A non-empty map means a hard limit is binding and the A/B is being throttled on one side only. |
| `regime.quintile_edges` / `regime.frozen_p80` | The sizing ladder in force. Constants since 2026-08-31; `frozen_p80` is **0.0252**. ⚠️ Not §1.8's published 4.31% — that was measured on an earlier window. |
| `regime.trailing_p80` vs `frozen_p80` | 🟢 DIAGNOSTIC. The trailing-30d top quintile against the frozen one. A trailing value far below means nearly everything sizes into the bottom buckets — correct in a calm market, and worth being able to see rather than infer. It no longer affects sizing. |
| `ab` | Both arms: trades, net bps per trade, net bps per unit of notional, win rate, drawdown, trades/day. |

### The empty-state doctrine — the one design rule the dashboard inherited

Moved here from `M3_UI_PLAN.md` when that document was archived, because it is the reason the
panel looks the way it does and it outlives the build plan.

🔴 **The panel's job is to make CORRECT SILENCE legible**, for the same reason `/api/health`
exists. The served checkpoint produced no gated signal between 2026-06-29 and the forward test's
restart, because the edge lives in volatile bars and the market was calm. That is the strategy
working — but *a system that has been silent for two months is indistinguishable from a broken
one*, and a panel that renders that state as a grey box reading "0 trades" is **worse than no
panel**: it will be read as a fault, and someone will "fix" a working system.

So every empty state says **why** it is empty and **what would change it** — "The policy trades
any bar at or above a fixed confidence of 0.630; right now even the top 2% of recent bars only
reaches 0.548, so it is correctly taking nothing" — and never *"No data"* on its own. The
corollary is the `nil` rule: with no trades yet `gross_bps` / `net_bps` / `win_rate` come back
`nil` and render as `—`, **never** as `0.00`, which would read as "measured, and it is zero".
The panel also degrades rather than 500s: with Postgres down the M3 block says the bar log cannot
be read and the rest of the dashboard still renders.

`net_bps` and `net_bps_per_notional` are **two different readings** and both are reported for
the same reason M3_2_RESULTS §D1 reports both: the policy arm varies size, so its per-trade
mean is size-weighted. Offline the same policy is +15.03 per trade and +11.24 per unit of
notional deployed. Quoting only the first flatters a policy that sizes up on its good bars.

---

## §3 — Decisions this integration made, and the evidence behind each

### 3.1 It crosses. There is no limit-order path at all.

M3-4 measured resting against crossing on 23 days of book history. Resting looks 3.60 bps
cheaper round trip on the fee arithmetic — but the adverse-selection panel is negative in
**16 of 16** (pair, direction) cells, from -0.07 bps at best to -1.69 on ZECUSDT sell. A
resting buy fills *because* the price came down through it and then keeps going, and the touch
spread on BTC is 0.01 bps, so there is essentially no spread to capture in the first place. The
saving is a fee-rebate accounting gain, not a trading gain.

So: no queue model, no fill probability, no chase logic, no partial fills. That is days of work
M3-5 did not have to do, and M3_PLAN §0.8 item 3 called it in advance. Building the maker arm
later is a new study with a new protocol, not an edit to `Trading.Executor`.

*2026-10-21: that study happened — BOOK_WAVE2_PLAN §M1 priced the maker path on this policy's
own trades with an uncensored tape (+3.1 bps net a round trip on the quoted leg) and §M2 built
it into the executor **for the pilot arm only**, off until `LIVE_PILOT_MAKER_PATH=true`. The
paper arms still cross and still book the bar price: this section stands for them, and R0–R5
never read the pilot's arm. The pilot's rows record each leg (`entry_order_type` …), and S2 is
read by `m3 makerpath live`.*

### 3.2 The policy owns coverage; the serve gate is a diagnostic.

M3_PLAN §3.1 framed this as architectural and it is. `serve.py` gates, and the app used to gate
again; if the policy gated too there would be **three gates in series** and the policy could
only ever see bars M2 had already approved — it could never *widen* coverage, which §1.3.1
makes a first-class decision variable. It is now settled: the policy owns coverage, and
`gated` is recorded on every bar as a diagnostic and as the control arm's entry condition.

`RiskManager`'s old hard-coded `confidence < 0.65` refusal was a **fourth** gate and is gone.
It survives as `min_confidence`, defaulting to `0.0`, as an operator override. A confidence
floor is not a risk limit: it could only narrow what the policy chose.

### 3.3 The position cap is 8, not 3.

M3-2 searched this exact knob over 36 configurations and `max_concurrent=3` was **worse than
its uncapped twin in every one**, on both pooled and worst-window net. The cap does not select
trades, it drops whichever ones arrive while three are open. Held serially per pair — which the
policy enforces independently — one slot per served pair is a real portfolio, not leverage. The cap moved 8 → 12 with the universe on 2026-08-29; it must track `served_pairs`, because a cap below the universe size is the binding concurrency constraint T6 measured as costing net bps.

It also has to be 8 for the A/B to mean anything: the control arm is a ledger and cannot be
refused, so a cap that throttles only the policy arm would show up as the policy losing.

### 3.4 Serial-per-pair is enforced in the database, not only in the decision.

A partial unique index on `(arm, pair) WHERE status = 'open'` refuses a second open position.
The decision code checks too, but a race between a poll and a restart must not be able to book
two overlapping four-hour holds on one pair — that is the mechanism by which a backtest books
the same move twice and the P&L becomes fiction.

---

### 3.5 The served universe is separate from the collection whitelist — found by deploying

🔴 **This was a live defect for the first ~35 minutes of the forward test, and it is the kind
that would have quietly invalidated the evidence rather than announcing itself.**

`Trading.Policy` ranks whatever `SignalEngine` serves, and `SignalEngine` follows
`Settings.get_whitelist/0` — which is the **collector's** pair list, stored in `app_settings`.
On `fluxtrader-1` that row still held the twelve pairs of the 8-vs-12 era, so on deploy the
policy was:

* taking its **top-2% coverage cut over a 12-pair population**, when M3-2 selected the rule on
  eight. "The top 2%" is a rank, so widening the population silently changes the rule; and
* able to **enter AVAX/ADA/LINK/XRP**, which M3-4 never measured a crossing cost for. Those
  fall back to `ExecCost`'s pooled 9.842 bps — a number pooled over the *other* eight pairs.

The fix is a second, separate list: `config :fluxtrader, :trading, served_pairs`, filtered
**before** `record_bars/2` so an unserved bar never joins the ranking population, and surfaced
as `policy.served_pairs` with a `not_served` skip counter.

⚠️ **The obvious fix is the wrong one and it was tried first.** Narrowing the *whitelist* to the
served eight does make the policy correct — and stops the collector, which halted
`orderbook_snapshots` on the four dropped pairs for ~18 minutes before it was caught. **Book
history never backfills.** Collecting a pair is cheap; not collecting it is permanent. The two
lists exist precisely so that the narrow one can be narrowed without touching the wide one.

🟢 **Postscript, 2026-08-29: the served list was widened to those same twelve — deliberately
this time.** It is worth being precise about why that is not a reversal, because the two look
identical from the outside and are opposite in kind. On deploy day the policy ranked twelve
pairs **by accident**, following the wrong list, charging four of them a cost pooled from the
other eight. The fix was not "eight is correct" — it was "the policy must own its universe, and
may only serve a pair it can price." The second condition has since been met: M3-4 had already
measured all twelve, ADAUSDT at 13.733 bps against the pooled 9.842 (so the accidental version
really was mispricing it by 40%), and promoting those four constants is what made the deliberate
widening safe.

The two lists still exist and still mean different things. What changed is that the narrow one
is no longer narrower. The invariant that replaced "it must be the eight" is the one that was
doing the real work all along: **every served pair carries its own measured crossing cost**,
now asserted in `config_test.exs` rather than maintained by hand.

## §4 — The A/B (this part IS pre-registered)

**⚠️ RE-REGISTERED 2026-08-31.** The original registration is kept verbatim in §4.2 below,
because a pre-registration that can be edited without trace is not one. §4.1 is what runs.

### 4.1 The registration in force, from 2026-08-31

**Question.** **Is the regime sizing worth anything?** M3-2 says the 1/3..5/3 ladder is worth
**+8.6 bps on the worst window** — the whole difference between failing Tier 1 and passing it
(M3_PLAN §0 item 4, which holds the entry set constant bar for bar and is the strongest form of
that claim). It has never been checked forward.

**Arms.** Both paper, both live at once, both charged M3-4's measured per-pair crossing cost,
both held four hours, both serial per pair, **and both taking their entry decision from the
same function** — `Policy.decide_flat/3` delegates to `Policy.decide/3` and overrides the size.

| | `policy` | `flat_size` |
|---|---|---|
| entry | confidence ≥ the frozen cut 0.6319 | **identical, by delegation** |
| side | the model's 240m direction | the same |
| size | 1/3..5/3 by BTC 24h-move quintile | **flat 1.0** |
| risk path | through `RiskManager` | none — a measurement arm, never an order |

🟢 **The two ledgers differ in exactly one dimension.** That is enforced structurally rather
than by discipline: there is one entry rule, in one function, and the control cannot drift away
from it under a later edit. `policy_test.exs` asserts the arms agree on every skip reason and on
every entry field except `size`.

**Metrics**, unchanged from §4.2 and matching M3_PROTOCOL §4: trades, net bps/trade, net bps per
unit of notional, win rate, cumulative net bps, max drawdown, trades/day. Reported per arm by
`/api/health`'s `ab` block and by `Ledger.ab_summary/1`.

**What would count as the sizing working:** the `policy` arm's net bps **per unit of notional**
above the `flat_size` arm's, on a trade count large enough to resolve it. Per-trade net bps is
the wrong column for this comparison and will mislead — the policy arm varies size, so its
per-trade mean is size-weighted and is flattered by exactly the thing under test. Offline the
same policy is +15.03 per trade against +11.24 per unit of notional.

**One acknowledged divergence.** The policy arm passes through `RiskManager` and the control
does not, so a risk refusal leaves a pair held on one arm and not the other until both are flat.
That is deliberate: a control that could be refused for lack of a slot would flatter the policy
by throttling only its competitor. `risk_rejections` on `/api/health` is where it shows up, and
a non-empty map is the signal to discount the comparison over that period.

🔴 **Read this before quoting any live number.** The forward test cannot be certified any
faster than the offline one could. M3-2's pooled per-trade standard deviation is 259 bps; at
~2.7 trades/day the arms will not separate at 8.6 bps for a very long time. The A/B's near-term
value is **that the pipeline is provably running and obeying its limits**, not its P&L column.

### 4.2 ⚫ The original registration, 2026-08-28 — superseded, kept for the record

> **Question.** What does the M3-2 rule add over trading M2's raw gated signal?
>
> | | `policy` | `signal_only` |
> |---|---|---|
> | entry | top 2% by confidence rank over the trailing 14 days | every bar M2's serve gate approves |
> | side | the model's 240m direction | the same |
> | size | 1/3..5/3 by BTC 24h-move quintile | flat 1.0 |
> | risk path | through `RiskManager` | none — a measurement arm, never an order |
>
> **What would count as the policy working:** the `policy` arm's net bps per unit of notional
> above the `signal_only` arm's, on a trade count large enough to resolve the difference.

**Why it was replaced.** It could not produce data. `signal_only` required `bar.gated`, and
**no bar was gated across all 8,184 bars** from the 2026-08-29 reset onward — the served
checkpoint has emitted no gated signal since **2026-06-29**, because the edge lives in volatile
bars and the market has been the calmest of the whole period. The control stood at **0 trades
against the policy arm's 12**, and would have stayed there for as long as the calm lasted, which
nobody controls and nobody can date. An A/B with one arm is not an A/B.

The question it asked is not lost: *what the rule adds over M2's raw gate* is answered offline
in `docs/M3_2_RESULTS.md`. What was missing was any forward check of the policy's own central
claim, and §4.1 is that.

**Why this is a legitimate re-registration and not a result-driven edit** — the test
M3_PROTOCOL §0 exists to apply:

1. **No comparable evidence existed when it was made.** The control had zero trades. There was
   no "which control looks better" to choose between.
2. **The policy arm's twelve trades were discarded in the same change**, for an unrelated
   reason (they ran a different rule — [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md)), so
   no live P&L survives that could have motivated the choice.
3. **The change was forced by a structural defect, not by a number.** The trigger is "this arm
   cannot fire", which is verifiable from `last_gated_at: null` without reference to any result.
4. **It is dated, and the original is above.**

⚠️ **The `signal_only` comparison is not measured live any more.** If M2's gate ever starts
firing again, reviving it as a third arm is small — `decide_signal_only/3` was deleted rather
than left as dead code, and git has it — but it should not be revived on the assumption the
gate will reopen.

### 4.3 Pre-registered readings of the forward ledger — 2026-09-13, at 7 signal bars

**Why this section exists, and why now.** Four questions were parked offline as "needs
untouched data": the coverage cut *level* (BACKLOG "Re-pre-register the served coverage"), the
regime observable's sign (BACKLOG row 7), the §9.2 hour set (WALKFORWARD, NOT CONFIRMED on
F2+F3), and §4.2 of M3_FIDELITY_RESULTS (the daily-loss limit's bias). Every one of them can be
read off *this* ledger as a **subset or split of the trades already taken**, because a tighter
cut selects a subset of the bars the 0.02 cut trades, and every row records its confidence,
regime value and entry hour. No new arm is needed for any of them. What makes such a reading
legitimate under M3_PROTOCOL §0 is that the subsets, the constants and the statistics are
fixed **before** the ledger holds enough trades to suggest them — and on 2026-09-13 it holds
seven, all from one afternoon. This section is that fixing. The executable form is
`ml/train/m3/forward.py`; the constants below are transcribed there and checked against the
ledger on every run.

**What was known when this was written.** 7 policy-arm trades and their 7 flat-arm twins, all
entered 2026-09-11 15:25–22:15 UTC, all timer exits, every one below the frozen regime p80.
The tighter cuts were derived (logged, container run) *before* the ledger CSV was first
exported; the coverages are protocol-named levels, not chosen values. The hour set is §9.2's
recorded one, unchanged. Nothing in this section was tuned on the seven.

**The unit, for everything below.** Net bps **per unit of notional** = Σ `net_bps` / Σ `size`
over a set of trades (the ledger's `net_bps` is already size-weighted). On the flat arm that is
the plain mean; on the policy arm the size-weighted mean. Costs are the ledger's own
`cost_bps` — the measured per-pair crossing cost at the verified 5.0-bps fee. Intervals are
day-clustered on the UTC **entry** day; contrasts between two subsets are day-bootstrapped
(2,000 draws, seed 20260913, days drawn from the union of both subsets and both means
recomputed on the same draw).

**The readings.**

| # | question | population | statistic |
|---|---|---|---|
| **R0** | §4.1's A/B — is the size ladder worth anything? | `policy` vs `flat_size`, all closed rows | per-notional net of each arm; contrast policy − flat with bootstrap CI. Note this is Σnet/Σsize against a plain mean of the *same* returns — the ladder "works" iff size correlates positively with the trade's return |
| **R1** | the cut level — are the marginal trades worth anything? | policy arm split at each tighter cut: TIGHT = `confidence ≥ cut(c)`, MARGINAL = the rest | per-notional net of TIGHT and of MARGINAL; contrast TIGHT − MARGINAL. A subset is a sub-sample, not a re-simulation (a freed pair could have taken a later bar under serial-per-pair); stated, not corrected |
| **R2** | the regime split — which sign does `btc_absret_1d` carry forward? | policy arm, entry `regime ≥ 0.025596268475055695` (the frozen p80) vs below | per-notional net of each; contrast top − below. M3-2 says top is better (the ladder's premise); the book era says the opposite (BACKLOG row 7) |
| **R3** | §9.2's hour set, on untouched data | policy arm, UTC entry hour ∈ **{0, 1, 2, 3, 4, 5, 7, 9, 10, 11, 12, 13, 14, 18, 21, 22}** vs excluded | per-notional net of each; contrast in − excluded. Sub-sample, same caveat as R1 |
| **R4** | M3_FIDELITY §4.2 — how much does the −50/day limit bias the estimate? | flat-arm rows with no policy-arm row at the same (pair, entry_ts) — a refusal, or the divergence after one | reconstruct each as a policy trade at the frozen ladder size for its own `regime`; report the recorded arm, the counterfactual arm (recorded + reconstructed) and the reconstructed rows alone |

**R5 — added 2026-09-15, at 7 signal bars (unchanged since 09-11), before any further trade.**
WALKFORWARD §9.7 tested hold extension while the signal persists (`persist05`) on the folds:
positive on every fold and seed, NOT CONFIRMED at the registered bar (+25.7 [−23.2, +74.7] bps
per seed-day), not resolvable offline. The forward ledger can carry the same question at no
cost, because `policy_bars` stores the served model's side, confidence and the bar's price for
every closed 5-minute bar. **R5** reconstructs `persist05` as a counterfactual of the recorded
policy arm: at a trade's timer exit bar, if the bar's row for the same pair takes the **same
side with confidence ≥ 0.5500438213348389** — `coverage_threshold(conf, 0.05)` on the same
population as the cuts below, derived 2026-09-15, restated 2026-09-20 for the U12
checkpoint (0.6179307699203491) and 2026-10-04 for X8″ seed 3 — and the bar 240 minutes later exists, the
hold is extended to it and re-priced at its stored price; at most **two** extensions (12 h). A
later recorded policy trade on the same pair whose entry falls inside the extension is
**swallowed** (it could not have been taken; its P&L is what the extension replaces — the saved
crossing). Cost stays the row's own `cost_bps`, once. Statistic: the counterfactual arm vs the
recorded arm, **per unit of notional** as R0–R4, with the day-bootstrapped contrast, **and** the
Σ net difference (extension changes notional-time, not notional). Consistency, enforced before
it prints: every policy trade's `entry_price` equals the stored bar price at its entry bar.
Executable: `forward.py:reading_extension`, `--bars`; the export script now pulls
`policy_bars` too. Same schedule, same TEXTURE rule, same licence as R0–R4: a reading whose
interval excludes zero licenses *writing* the served-change registration §9.7 describes.

**The constants.** Coverage cuts are `backtest.coverage_threshold(conf, c)` over the served
checkpoint's own split — **since the 2026-10-04 promote (the forward clock's fifth start,
15:18:49 UTC): X8″ seed 3, eval run `20261003T191545Z`, the twelve served pairs, horizon 240**
(NEXT_TRAINING_PLAN §2 X8″; `logs/X8pp_c4_20261004.log`). R0–R5 are unchanged as readings;
only these per-checkpoint constants were restated, before the new ledger held a row. U12 seed
2's values (the fourth start, 2026-09-20 → 10-04, 14 closed policy trades, void and backed up)
were 0.6709 / 0.6958 / 0.7077 / 0.7253; the ladder is the same numbers (same split, same BTC
bars). The 0.02 entry reproduces
`Policy.frozen_threshold/0` to the digit, which is the check that the population is right.

| coverage | cut | why this level |
|---|---|---|
| 0.02 | 0.5860595703125 | the served cut; the full policy arm |
| 0.015 | 0.6075984835624695 | the round level between |
| 0.01288 | 0.6196200251579285 | T6's count-matched coverage on twelve pairs — the parked question's own number |
| 0.01 | 0.6390083432197571 | the round tighter level |

Ladder edges `[0.003849115688353777, 0.008730954490602016, 0.014942771755158901,
0.025370502844452858]`, size `(count of edges ≤ regime + 1) / 3` — `Policy.size_multiplier/2`.

**The schedule.** The first reading is at **50 closed policy-arm trades**, then at every
further 50. Before 50 the command prints every table under a TEXTURE banner and **nothing in
it may be quoted as a result** — not in a document, not in chat. At 50 the per-trade interval
is about ±72 bps (sd 259, §4.1), so the first two or three readings are texture in all but
name; ~290 trades resolve a +30 bps mean against zero. No reading is a stopping rule.

**What a reading licenses.** Nothing served changes on any of R0–R4. A reading whose interval
excludes zero licenses *writing* a pre-registration of a served change on the population it
would be served from — exactly what the parked coverage row already says — and a reading whose
interval includes zero is reported as such and re-read at the next 50. R4's counterfactual
arm is the number to quote for the policy's unconditional per-trade edge whenever
`risk_rejections` on `/api/health` has been non-empty over the span; when the reconstructed
set is empty, the recorded arm *is* the unbiased estimate and §4.2's bias is zero over that
ledger.

**Consistency, enforced before any table prints:** one checkpoint on every row, `threshold`
equal to the served cut, `ladder_p80` equal to the frozen p80, no row entered below the cut.
A failure prints the problems and no tables.

**Exact command** (read-only against the VM; writes the CSV under `ml/train/output/forward/`,
gitignored):

```sh
./scripts/gcp_forward_ledger.sh              # export today's ledger + policy_bars and run R0–R5
./scripts/m3.sh -m m3 forward --ledger output/forward/paper_trades_<YYYYMMDD>.csv \
    --bars output/forward/policy_bars_<YYYYMMDD>.csv                              # re-read
```

Run 2026-09-13 on the seven: consistency ok, TEXTURE banner, R4 empty (no refusals yet).
Run 2026-09-15 on the same seven with R5: consistency ok (entry prices match the bars), TEXTURE;
R5 fired one extension and swallowed one later trade — texture, not a number.

**Run 2026-10-19 — reading #1 of the schedule, at 57 closed policy trades**
(`logs/forward_ledger_20261019.log`; entries 10-07 → 10-18, 12 entry days; consistency ok;
one checkpoint, the served cut and the frozen ladder on every row). Per unit of notional,
day-clustered: **R0** policy +36.5 [−51.8, +124.8] vs flat_size +32.1 [−42.9, +107.2],
contrast +4.4 [−21.5, +46.3]. **R1** tight − marginal: cov 0.015 −40.6 [−121, +98] (n 15 / 42);
0.01288 +30.2 [−134, +154] (7 / 50); 0.01 +78.2 [−175, +381] (4 / 53). **R2** top quintile +161
(n 10, 3 days) vs below −5.6 (47), contrast +167 [−15, +362]. **R3** in-set +63 (41) vs excluded
−27 (16), +90 [−6, +325]. **R4** four suppressed trades (the −50/day limit on 10-08) at +116;
counterfactual arm +42.5 vs recorded +36.5. **R5** counterfactual +88.9 vs recorded +36.5,
**contrast +52.3 [+0.4, +117.3]**, Σ net +2,980 bps × size; 13 extensions, 5 later trades
swallowed, 52 counterfactual trades, mean hold 314 m. R5's is the only interval clear of zero,
by its lower edge, on twelve days. As registered that **licenses writing** §9.7's served-change
registration — writing it now with the served change gated on reading #2 at 100, or waiting for
#2, is Vadim's decision (BACKLOG handoff, E3). Nothing served changes on this reading. *Val
expectation, noted the same day (NEXT_TRAINING_PLAN §2 X8″-6):* wherever this ledger is set
against the served checkpoint's val numbers, X8″'s six-seed family — plateau LB 0.5323
(0.5242 all-epoch), cov-0.02 gross +17.5 bps — replaces the three-seed 0.5349 / +21.4.

---

### 4.4 Pre-registration of a served change: hold extension while the signal persists (`persist05`) — WRITTEN 2026-10-19 on Vadim's "E3 - ok", after reading #1 and before reading #2; NOT IN FORCE until its gate

**Why now, and what this is.** WALKFORWARD §9.7 tested `persist05` on the folds (positive on every fold and seed, NOT CONFIRMED at the bar) and named the forward ledger as its revival at zero cost; §4.3's R5 reconstructs it as a counterfactual on every reading. Reading #1 (57 trades, 2026-10-19) read R5 at **+52.3 [+0.4, +117.3] bps per unit of notional** — the interval clear of zero by its lower edge on twelve entry days — which, as §4.3 registered, licenses *writing* this section. It is written now so the served rule, the gate and what the gate licenses are fixed before reading #2 can suggest them. **Nothing changes on the VM until the gate below passes and Vadim says so.**

**The served rule, exactly `forward.py:reading_extension`'s counterfactual.** When an open `policy` or `flat_size` row reaches its `exit_after_ts`, the engine reads the pair's `policy_bars` row at that bar (the 240m head's side and confidence, the same row the ledger already stores). If **the side equals the trade's side and the confidence ≥ the explore cut `Policy.explore_threshold/0`** (0.5500438213348389 on X8″ s3 — `coverage_threshold(conf, 0.05)` on the served checkpoint's own split, restated at any promotion), the row's `exit_after_ts` moves forward by 240 minutes and the row is **not** closed; otherwise it closes on the timer as today. **At most two extensions** (12 h total); the third due is a close. A bar missing at the due tick (no `policy_bars` row for that `(pair, bar_ts)`) is a close, never a wait. The row records `extensions` (0 / 1 / 2) and `exit_reason` `timer` / `ext1_timer` / `ext2_timer`. **Entries are unchanged**: serial-per-pair means a pair under extension takes no new entry (the "swallowed" trade of R5 is exactly this), the cut, ladder, cost and brakes are as today. The `live` pilot mirrors `policy`'s exit as it mirrors its entry (its timed close moves with the row). `explore_cov05` is **not** extended (it is the exploratory arm at the cut the extension itself uses; extending it would conflate the two). R5 keeps running on the new ledger as a consistency check: on an extended ledger its counterfactual must equal the recorded arm (zero contrast) — the parity test for the implementation, in the spirit of `policy_test.exs`'s rule-parity tests against `backtest.py`.

**The gate, fixed now.** Reading #2 of §4.3 (at **100 closed policy trades** of the fifth start) must read R5 with **the same sign and the day-bootstrapped interval clear of zero**, on the ledger as it stands at 100 — the first 57 included, nothing excluded, nothing re-cut. Then the change is licensed; Vadim's word deploys it. If reading #2's interval includes zero the section stays written and the question moves to reading #3 at 150 (one more look, the last under this registration); two misses close it as NOT CONFIRMED FORWARD and nothing is served. 🔴 Not licensed by any reading: a different cut for the extension, a third extension, a flip exit, extending `explore_cov05`, or deploying before the gate.

**What deploying it means for the forward clock.** A served exit-rule change is a new registered start (the sixth): the fifth start's ledger is backed up and cleared with nothing open, `Policy.hold_minutes/0` stays 240 (the base hold), the constants restated in `policy.ex` / `config_test.exs` / `forward.py`, parity tests added for the extension (same side above the cut → extended; below the cut, opposite side, or a missing bar → closed; the third due → closed), `/api/health` shows the rule name with `_ext2`, and the acceptance replay is run as for the fifth start. R0–R5's readings restart their schedule on the sixth start's ledger; the fifth start's 100+ trades remain the record that licensed the change. **The cost of this is stated:** the fifth start's accumulation ends at the deploy; that is why the gate is at 100, not now.

**Recorded expectation.** Reading #2 at 100 **includes zero** (the first reading's lower edge is +0.4 on twelve days; the next ~43 trades are more days than trades, and the contrast's half-width at 57 is ~58). The section is written so that if it does clear, the change is not designed after the fact.

### 4.5 Served change: the row and the exit keyed on the served bar, and a 40 s settle — BUILT 2026-10-21 on Vadim's "Ok, go A plus B"; DEPLOYED 2026-10-21 15:02:33 UTC on his "push and deploy" (deploy record at the end of the section)

**What was wrong.** `serve.py` scores the last *settled* closed bar and reports it (`last_closed_bar_open_time`); `predict.ex` discarded that and stamped the wall clock; the engine floored the wall clock to the grid and recorded each `(pair, bar_ts)` once. In the first two minutes of every bar the served bar was the one that closed five minutes earlier, so the row stamped B carried the B − 10 min bar's close (99.7 % of 57,515 rows) and the order went out at the recording tick — **≈ 7 minutes after the price it was booked at**; the backtest trades at that close (BOOK_WAVE2_PLAN §M1 Result, "The 7-minute clock"). The paper arms were nevertheless bar-exact at both ends — entry at the scored close, exit at the mark, which the signal broadcast kept equal to the latest scored close — so arm-vs-arm readings (R0–R5) were never touched; paper-vs-backtest and paper-vs-pilot comparability were, and the real pilot paid the delay.

**The change, exactly.**
- **(A) The row is the bar.** `predict.ex` carries `last_closed_bar_open_time` as `bar_open_time`; `PolicyEngine.to_bar/2` stamps `bar_ts` with it. `bar_ts` now equals the dump's `ts` and `candles.open_time`; `price` is the close at `bar_ts` + 5 min. The row is recorded and decided on the first tick the bar is served. A signal without the stamp is dropped and counted `signal_unusable` — never keyed on the clock again.
- **(A′) The exit is a bar too.** `exit_after_ts` = `bar_ts` + 240 min is unchanged in code and is now the **exit bar's open**; the position closes on the tick that bar is first served, at **that bar's close** (`close_due/3`) — `fwd_ret_240`'s exit, bar for bar. Before that bar is served the trade is not due (`close_deferred_bar_pending`). If no bar comes within 15 min of `exit_after_ts` (`@exit_bar_grace_s`; a pair dropped from the served set, inference down) the close falls back to the mark and is counted `closed_at_mark`. Every arm, the `live` mirror included, closes through this path; the brakes are untouched.
- **(B) The settle — its premise corrected.** The registration said "the collector polls every 60 s, so 65–70 s". Measured on the VM 2026-10-21 (twelve consecutive poll stamps at 1-s resolution, 09:46–10:01 UTC): the candle poll walks four intervals over twelve pairs serially and reschedules itself after it finishes, so its period is **62–90 s, median 82 s** (eleven periods: 62, 81, 87, 81, 87, 83, 85, 82, 90, 89, 81), and `db.py`'s own 2026-09-11 measurement had the final row 7–93 s after the close. A 65–70 s settle would have scored the in-bar snapshot on a fraction of bars — the very defect of 2026-09-11, now unrepairable because the row is decided once. Built instead: the collector re-reads the **5m candles alone every 15 s** (`collector.ex` `:poll_candles_fast`, `CANDLE_FAST_POLL_MS`, twelve weight-1 calls → 48 weight a minute against the 2,400 cap; the 60 s poll unchanged beside it) and `docker-compose.yml` sets **`CANDLE_SETTLE_S=40`** on `ml_inference` (≤ ~20 s to the final row, 20 s margin; `db.py`'s default stays 120 for offline replays). With the fast poll off the settle must go back to 120.
- **Expected latency, close → real order:** 40 s settle + the pair's slot in the serial inference cycle (0–92 s, measured p50 of the cycle 92 s) + the 30 s tick → **≈ 1.5–2 min median**, against ≈ 7 before. The cycle is now the largest term and is not touched here.

**What does not change.** The rule, the cut, the ladder, the four arms, the 48-bar hold, the costs, the brakes, the paper arms' booked prices (the scored close in, the exit bar's close out — as before). `Policy.hold_minutes/0` 240; `policy_test.exs`'s parity tests unchanged; `config_test.exs` unchanged.

**The forward clock: NOT a new start.** §4.4's doctrine makes a served *exit-rule* change a new start because it changes which trades exist and how long they live; this changes neither — every arm takes the same bars at the same booked prices as before, only the row's name and the real order's timing move. The fifth start's ledger continues. The convention boundary is **2026-10-21 15:02:33 UTC** — the app's recreate on the VM, `forward.BAR_KEY_CHANGE_UTC`: rows with `bar_ts` before it are wall-clock-keyed (the scored bar's open + 10 min), rows from it are bar-keyed. Two transition artefacts, stated now: (i) the first one or two bars served after the deploy carry `bar_ts` values at which wall-clock rows already exist (the old rows for those stamps hold *earlier* bars' scores) — they land as `bar_already_recorded` and are not decided: ≤ 10 min without entries; (ii) trades open across the deploy keep their old `exit_after_ts` (the scored open + 250 min), which the new engine reads as an exit bar's open — they close at the close of the bar opening there, 10 min later than the old rule would have closed them, at that bar's close. Their ids are listed in the deploy record.

**R5 parity (forward.py).** `check_bars` (entry price = the stored bar price at `entry_ts`) holds under both conventions because the row and the trade move together. R5's lookup at `(pair, exit_after_ts)` names the **same informational bar** under both: before, the row at S + 250 carried the bar that opened at S + 240; now the row at S + 240 *is* that bar. So R0–R5 run unchanged on the mixed ledger; only the straddling trades of (ii) differ, by one bar. Added to `check_bars` for rows from the boundary: the **exit-bar parity line** — every timer close's `exit_price` must equal the stored price at `(pair, exit_after_ts)`; mismatches are `closed_at_mark` fallbacks or brakes and are printed, not blockers. `makerpath.py` shifts stratum B's signal bar by two bars only before the boundary.

**§4.4 under the new clock.** The hold-extension rule reads "the pair's `policy_bars` row at `exit_after_ts`" — that is now exactly the exit bar the engine waits for before closing, so the served rule, if its gate passes, is implementable bar for bar with no further convention. Its gate is unchanged.

**Acceptance after the deploy (Claude runs it, same day):** `/api/health` shows `signal_unusable` 0 and `closed_at_mark` 0 after the first closes; the VM's `/predict` `last_closed_bar_open_time` advances within ~45 s of each 5-minute close; new `policy_bars` rows are inserted 40–160 s after `bar_ts` + 5 min (before: 37–169 s after `bar_ts`, i.e. 337–469 s after the scored close); the first new trades' `inserted_at` − (`entry_ts` + 5 min) ≈ 1–2.5 min; the collector's request weight unchanged within noise; the ledger's open trades at the deploy listed with their ids. The first ledger reading after it (§4.3's #2 at 100) runs `forward.py` with the boundary set and quotes the parity line.

**Deploy record, 2026-10-21 (Claude ran the VM steps on Vadim's "push and deploy"; commits `d5bfcdb` … `3509b04` pushed, the VM at `3509b04`).** Sequence: `git pull` at 15:01 UTC; `docker compose up -d ml_inference` (recreated with `CANDLE_SETTLE_S=40`; `/predict` reports `candle_settle_s: 40`); `mix compile`; `docker compose up -d app` at **15:02:33 UTC — the boundary** (the container recreated so `CANDLE_FAST_POLL_MS` is in its environment; up by 15:02:50). **Open at the deploy: one paper trade, id 497** (`explore_cov05`, WLDUSDT short, entry bar 14:40, `exit_after_ts` 18:40, paper fill) — artefact (ii): the new engine closes it at the 18:40 bar's close on the tick that bar is served (≈ 18:46), where the old rule would have closed it at 18:40 at the mark. The pilot had no open position. Artefact (i) as stated: the old engine had recorded every pair's 15:00 row before the boundary (six at 15:00:43, six at 15:02:17, all carrying the 14:50 bar's scores), so the new engine's 15:00-bar signals landed as `bar_already_recorded` and no 15:00-keyed trade exists on either convention; the first bar-keyed rows are the 15:05 bar's.

**Acceptance, same day — what was checked and what it showed.** `signal_unusable` absent from `/api/health`'s skips through 15:24 (every served signal carries the stamp) ✅. `/predict`'s `last_closed_bar_open_time` showed the 15:05 bar at 15:10:56, 56 s after its close (the two earlier probes, at 15:10:26 and 15:10:41, timed out: `/predict` is serial and a probe queues behind the engine's own calls — **do not probe `/predict` during an acceptance window; it delays the engine**) ✅. The collector's 15 s poll is live: the forming 5m bar was in `candles` 26 s into the bar (under the 60 s poll alone it could lag up to 90 s) ✅; no Binance errors or rate-limit lines in the app log; the weight (48 a minute added against the 2,400 cap) not separately measured. **`policy_bars` insert latency after the scored bar's close, the first three bar-keyed bars (12 rows each):** 15:05 bar: all twelve at 217 s (contaminated by the probes above — discard); **15:10 bar: 132 … 224 s; 15:15 bar: 79 … 171 s** — against the registered 40–160 s and the old 337–469 s. The window as registered is missed at its top: the rows of one bar now arrive spread over ≈ 92 s (each pair's row is written on the tick its signal comes through, and the engine queries the twelve pairs serially at ≈ 7.7 s each), and when the serial cycle straddles the settle moment the pairs queried before it wait a whole further cycle — so the honest range is 40 … ≈ 230 s, median ≈ 2–2.5 min, a 5-minute improvement on the old clock, not the 1.5–2 min §4.5 expected. The cause is the serial inference cycle this section already named as the next largest term; it licenses nothing here (parallelising inference is its own registration). Still to read at the next look: `closed_at_mark` 0 after the first closes (trade 497's at ≈ 18:46, then the new trades'), and the first new trades' `inserted_at` − (`entry_ts` + 5 min), expected ≈ 1.5–4 min by the row numbers above; no trade had opened by 15:24 (`below_coverage`).

**Acceptance, continued (read 2026-10-22 01:30 UTC).** The first three closes under the new rule
(trades 497, 498, 499 — all `explore_cov05`) were booked by the timer at the exit bar's close,
`closed_at_mark` absent from the counters ✅: exits written 206 / 151 / 190 s after the exit
bar's close (18:48:26 for the 18:40 bar, 20:37:31 for 20:30, 22:48:10 for 22:40), i.e. on the
tick the bar was served; `close_deferred_bar_pending` counted 45 ticks waiting, as designed. The
first new trade's row (498, HYPE, the 16:30 bar) was inserted 134 s after the scored close —
inside the measured 79 … 224 s band. Nothing left to read for this section's acceptance.

**Forward-record note, 2026-10-21 16:13:46 UTC — M2 deployed (BOOK_WAVE2_PLAN §M2 "Deployed"): the pilot arm's entries and exits rest at the touch for 60 s before crossing; its rows from that instant carry the leg columns. Not a new start: the paper arms book exactly what they booked, and R0–R5 never read the pilot arm.**

**Licensed by this section:** the deploy on Vadim's word (done), the boundary constant (set), the parity line. 🔴 **Not licensed:** any change to the cut, hold, arms, costs or brakes; a shorter settle than the fast poll's worst case plus margin; touching the 60 s poll or any other collected table; parallelising inference (a separate change, if ever, with its own registration).

## §5 — Where the live rule differs from the backtested one

Every one of these is a deliberate choice, and each is a place a future discrepancy will come
from. None of them is a re-tune of the policy.

| # | difference | why, and which way it cuts |
|---|---|---|
| 1 | **The coverage cut comes from a trailing 14-day window, not the whole split.** | The backtest can afford lookahead because it is scoring, not trading. Trailing-only is strictly more conservative, and it is what §1.3.3 actually wants: it holds coverage at 2% while the model's confidence scale drifts. The live cut will not equal any number in M3_2_RESULTS, and it is not supposed to. |
| 2 | **Regime quintile edges come from a trailing 30 days of BTC klines**, not from the split's bar distribution. | Same reason, plus it is re-derivable from the exchange after a restart. As of 2026-08-28 the live p80 edge is 1.77% against §1.8's published 4.31%, so **the whole size ladder is currently calibrated to a calm market** — sizes will be 5/3 on moves that would have been mid-bucket during the evaluation period. This is the intended behaviour of a relative ladder, but it means live sizing is not comparable to backtest sizing bar-for-bar. |
| 3 | **The ranking population is bars actually observed**, not a complete 5-minute grid. | A slow or failed inference cycle simply produces no bar. It stays an honest sample of market states, but it means "2% of bars" is 2% of *seen* bars. `signal_liveness.bars_last_24h` is how you check the grid is not full of holes. |
| 4 | **Entry price is the scored bar's close; the real order goes out ≈ 2–2.5 min (median) after that close** (measured at §4.5's deploy: the rows 79 … 224 s after the close; the paper arms book the close itself). ⚠️ *Until the 2026-10-21 fix it was ≈ **7 minutes**, not the ~30 s this row claimed: the row stamped B carried the close of the bar that closed at B − 5 min on 99.7 % of 57,515 rows (BOOK_WAVE2_PLAN §M1 Result; the mechanism and the fix in §4.5).* | The engine keys the row and the exit on the served bar; the remaining gap is the collector's poll (≤ ~20 s), the 40 s settle, the serial inference cycle (~92 s over twelve pairs, the largest term) and the 30 s tick. Delaying the backtest's trades by 5 min costs −0.85 bps gross a trade [−3.4, +1.7], by 10 min −2.5 [−6.6, +1.6] (§M1 Result). |
| 5 | **`RiskManager` attaches a stop and a target; the paper arms ignore them.** | The M3-2 policy has neither — it was scored on a fixed four-hour hold, and a barrier exit scored against a fixed-horizon return is precisely the policy mismatch C4b was filed for. On the `auto` path they are attached as a catastrophe brake, and **that brake is an unmeasured deviation** which must be priced (M3-0b's price path is what would let us price it) before real money. *2026-10-19:* the micro-pilot (REAL_MONEY_TRACK §7) carries this brake on the exchange and it is now measured there: 13 of its 38 trades stopped and 2 hit the target, and the brake is ~80 % of the pilot's −1,662-bps gross gap to the `policy` arm on the shared entries (≈ 35 bps a trade; X6 priced it at ~30 offline). The `live` arm is therefore not a reading of the scored rule while the brake is on. |
| 6 | **The cost charged is the measured one, and it is measured in the wrong regime.** | M3-4's window is the calmest month of the period and holds none of the policy's trades. Cost rises with volatility (9.77 → 10.09 bps across BTC-vol quintiles) and this policy trades the high end. Treat live net numbers as the optimistic end by a few tenths of a bp. |

---

## §6 — What M3-5 does NOT deliver

Stated plainly so nobody assumes otherwise:

- ~~🔴 **The fee tier is still unverified.**~~ ✅ **Verified 2026-09-10 — and it was wrong:
  taker 5.0 bps/side, not 4.0.** Both paper arms are charged the measured per-pair cost **plus
  2.0 bps** from that day (`ExecCost`); no trade existed yet, so nothing was re-scored. This
  is an amendment to §4.1's cost clause, made before the first tagged row and recorded here.
  See [REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) §5.
- ~~🔴 **`auto` mode cannot actually place an order.**~~ ✅ **Signed, reconciled and braked
  as of 2026-09-10** — built after M3-5, under REAL_MONEY_TRACK step 3, and demonstrated
  against the testnet is the one thing still pending. `auto` on the VM stays **off**: the row
  an exchange fill writes is scored from the real `avgPrice` and charged the two fees only,
  which is a different ledger from the paper one, and §4.1's A/B is registered on paper.
- **No barrier exits, no funding term.** Both need M3-0b's price/funding side-table. The 4h
  hold is exactly what was scored.
- **No verdict.** See §0: this collects evidence, it does not conclude.

---

## §7 — One bug fixed on the way

`ml/train/config.py` did `float(os.environ.get("GATE_THRESHOLD", "0.58"))`, and
`docker-compose.yml` passes `GATE_THRESHOLD: ${ML_GATE_THRESHOLD:-}` **deliberately empty** —
an empty value there means "no operator override, serve at the checkpoint's own measured gate"
(C13). `float("")` raises, so `ml_inference` crash-looped at import **in the default
configuration**. It now treats an empty value as unset. Nothing about the served gate's
semantics changed; the service simply starts.

---

## §8 — Deploy day, 2026-08-28: three defects that only the real VM exposed

*Moved here from `BACKLOG.md` on 2026-09-04 (RULES_REVIEW §6.3). Each of these was invisible on the local stack, which is the reason to record them where the deploy is documented rather than in an index.*

**M3-4 completed 2026-08-28** — [M3_4_RESULTS.md](./M3_4_RESULTS.md), read via
[M3_PLAN.md](./M3_PLAN.md) §0.8. Risk #2 closed.

**Deploy day, 2026-08-28 — three defects were found and fixed by deploying.** Recorded here
because each was invisible on the local stack and only the real VM exposed it:

1. **The policy was ranking over 12 pairs, not 8.** `Settings.get_whitelist/0` is the
   *collector's* pair list and the VM's copy still held the 12-pair 8-vs-12 era list; the
   policy followed it, so the top-2% coverage cut was being taken over a population including
   four pairs `ExecCost` has never measured. Fixed by giving the policy its own universe
   (`config :fluxtrader, :trading, served_pairs`), reported at `policy.served_pairs`, with
   unserved bars counted as the named skip `not_served`. 🔴 **Do not "fix" a future mismatch
   by narrowing the collection whitelist** — see #2.
2. **Narrowing the whitelist stopped collection.** The first attempt at #1 set the whitelist to
   the served eight, which halted `orderbook_snapshots` on ADA/AVAX/LINK/XRP for ~18 minutes.
   Collection gaps do not backfill. Restored, and the code now separates the two concerns.
3. **The tape fix starved the book poll.** Raising the aggTrades limit ran inline in the same
   GenServer as the book poll and cost 2.5x of the book snapshot rate (55.2 → 22.2 rows/min).
   The sweep now runs under `Task.Supervisor`.

**M3-5 completed 2026-08-28** — [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md). The policy is
wired to a crossing executor, the hard `RiskManager` path is exercised on every entry, the
signal-only A/B control runs beside it, and `/api/health` reports signal liveness. Risk #7
closed; §6's last two exit criteria closed. It left two items open, both below.
