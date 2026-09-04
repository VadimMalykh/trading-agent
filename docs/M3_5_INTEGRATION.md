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
     -> floor the signal's timestamp to the 5-minute grid   one decision per bar, not per poll
     -> INSERT into policy_bars (idempotent)                the population the 2% cut is taken over
     -> Ledger.coverage_threshold/3                         the k-th largest of the trailing 14 days
     -> Policy.decide/3                                     the rule
     -> RiskManager.check/1                                 hard limits, never bypassed
     -> Executor.open/3                                     crossing; a paper row in simulation
     ... four hours later, on a later tick ...
     -> Executor.close/2 -> RiskManager.release/0 + record_close/1
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
| `policy.skips` | Named reasons bars were not traded: `below_coverage`, `position_open`, `no_regime`, `no_side`, `not_served`. ⚠️ `warming_up` should **never appear again** — if it does, the running binary predates the freeze. **A silent system with a populated `skips` map is working.** `not_served` counts bars for collected-but-not-traded pairs; since 2026-08-29 the collector and the served set hold the same twelve, so it should now be **zero** — a non-zero value means the two lists have drifted apart. |
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

---

## §5 — Where the live rule differs from the backtested one

Every one of these is a deliberate choice, and each is a place a future discrepancy will come
from. None of them is a re-tune of the policy.

| # | difference | why, and which way it cuts |
|---|---|---|
| 1 | **The coverage cut comes from a trailing 14-day window, not the whole split.** | The backtest can afford lookahead because it is scoring, not trading. Trailing-only is strictly more conservative, and it is what §1.3.3 actually wants: it holds coverage at 2% while the model's confidence scale drifts. The live cut will not equal any number in M3_2_RESULTS, and it is not supposed to. |
| 2 | **Regime quintile edges come from a trailing 30 days of BTC klines**, not from the split's bar distribution. | Same reason, plus it is re-derivable from the exchange after a restart. As of 2026-08-28 the live p80 edge is 1.77% against §1.8's published 4.31%, so **the whole size ladder is currently calibrated to a calm market** — sizes will be 5/3 on moves that would have been mid-bucket during the evaluation period. This is the intended behaviour of a relative ladder, but it means live sizing is not comparable to backtest sizing bar-for-bar. |
| 3 | **The ranking population is bars actually observed**, not a complete 5-minute grid. | A slow or failed inference cycle simply produces no bar. It stays an honest sample of market states, but it means "2% of bars" is 2% of *seen* bars. `signal_liveness.bars_last_24h` is how you check the grid is not full of holes. |
| 4 | **Entry price is the signal's price, up to ~30 seconds stale.** | The signal engine polls on its own 30-second cycle and the policy decides on its own. The backtest enters at the bar. |
| 5 | **`RiskManager` attaches a stop and a target; the paper arms ignore them.** | The M3-2 policy has neither — it was scored on a fixed four-hour hold, and a barrier exit scored against a fixed-horizon return is precisely the policy mismatch C4b was filed for. On the `auto` path they are attached as a catastrophe brake, and **that brake is an unmeasured deviation** which must be priced (M3-0b's price path is what would let us price it) before real money. |
| 6 | **The cost charged is the measured one, and it is measured in the wrong regime.** | M3-4's window is the calmest month of the period and holds none of the policy's trades. Cost rises with volatility (9.77 → 10.09 bps across BTC-vol quintiles) and this policy trades the high end. Treat live net numbers as the optimistic end by a few tenths of a bp. |

---

## §6 — What M3-5 does NOT deliver

Stated plainly so nobody assumes otherwise:

- 🔴 **The fee tier is still unverified.** Every M3 cost decomposes to a taker fee of 4.0 bps
  per side, which is the published Binance USDⓈ-M VIP-0 rate and **has never been read off the
  account**. `mix flux.fee_tier` performs the check and is written to fail loudly rather than
  print an unverified number; it needs `BINANCE_API_KEY` / `BINANCE_API_SECRET` in the app
  container, which this environment does not have. A wrong tier shifts every published M3
  number by a constant. This remains M3_4_PROTOCOL §2.5's open precondition.
- 🔴 **`auto` mode cannot actually place an order.** `Binance.Client.post/2` sends neither the
  `X-MBX-APIKEY` header nor the HMAC-SHA256 signature that every Binance TRADE endpoint
  requires, so a real order returns 401. The executor now logs this loudly at boot rather than
  looking like it is trading. **Request signing is out of M3-5's scope** — M3-5 is the paper
  A/B — but it is a hard prerequisite for anything beyond paper, and it is filed in
  [BACKLOG.md](./BACKLOG.md).
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
