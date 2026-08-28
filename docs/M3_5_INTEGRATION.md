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

Every five minutes the model scores each of the eight pairs we trade. Each score is written
down. Once a week of scores has accumulated, the system takes **the most confident 2% of
them**, goes long or short as the model says, sizes the trade between **one third and five
thirds** of a base position depending on how violent the last 24 hours of Bitcoin have been,
holds for **four hours**, and closes. Every trade is charged the **real** cost of crossing the
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

1. **It will not trade for at least a week after any fresh deployment.** Entry is by rank —
   "the top 2% of recent bars" — so it needs a population to rank against. The rank window
   needs 2,016 bars (seven days) before the policy will place anything. `/api/health` says
   `"warm": false` until then.
2. **It may then not trade for weeks more.** The strategy only fires in volatile markets, and
   the market has been the calmest of the whole evaluation period since July — **the served
   checkpoint has produced no gated signal since 2026-06-29**. That is the strategy correctly
   sitting out, and it is exactly why `/api/health` now reports bars seen and time since the
   last gated signal: so that correct silence is visible as correct.

---

## §1 — What runs

| module | what it is |
|---|---|
| `Trading.Policy` | The rule, pure and stateless: the coverage cut, the quintile edges, the 1/3..5/3 size ladder, the 4h hold, and `decide/3`. **The rule exists here and nowhere else.** |
| `Trading.ExecCost` | M3-4's measured per-pair crossing cost. No maker branch, no queue model — see §3. |
| `Trading.Regime` | `btc_absret_1d` and its trailing 30-day quintile edges, rebuilt from Binance klines so a redeploy costs no warmup. |
| `Trading.Ledger` | `policy_bars` (the ranking population and the forward evidence) and `paper_trades` (both arms of the A/B), plus the scoring. |
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

The control arm branches off after `Policy.decide_signal_only/3` and goes straight to the
ledger: it is a measurement arm and never produces an order (§4).

---

## §2 — How to run it, and how to read it

⚠️ **It is verified locally and NOT deployed.** Everything below runs against the local stack,
whose Postgres is a throwaway dev DB. The forward test only starts accumulating evidence once
this is on the always-on VM `fluxtrader-1`, where the real data lives — and **B4's collector
fixes are awaiting the same deploy** ([BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) §2 B4), so send
them together rather than restarting the collector twice. The migrations run at boot.

```sh
docker compose up -d postgres ml_inference app     # the whole stack; migrations run at boot
curl -s http://localhost:4001/api/health | jq      # host port 4001, container 4000
docker compose logs -f app | grep -E "OPEN|CLOSE|RiskManager"
```

Tests — including the parity tests that pin the Elixir rule to `ml/train/m3/backtest.py`:

```sh
docker compose run --rm -e MIX_ENV=test -e POSTGRES_HOST=postgres app mix test
```

### Reading `/api/health`

| field | what it tells you |
|---|---|
| `signal_liveness.bars_last_24h` | Is the model being scored at all? Should be ~288 x pairs. |
| `signal_liveness.seconds_since_last_gated` | How long the system has been silent. `null` means never gated in the retained window — check it against §0's "no gated signal since 2026-06-29". |
| `policy.warm` | `false` means the rank window is still filling; the policy cannot trade. |
| `policy.confidence_threshold` | The live top-2% cut. Watch it drift — that is the thing a fixed threshold would have got wrong. |
| `policy.skips` | Named reasons bars were not traded: `warming_up`, `below_coverage`, `position_open`, `no_regime`, `no_side`. **A silent system with a populated `skips` map is working.** |
| `policy.risk_rejections` | Counted refusals by reason. A non-empty map means a hard limit is binding and the A/B is being throttled on one side only. |
| `regime.p80_edge` vs `published_p80` | The live top quintile cut against §1.8's 4.31%. A large gap means the market is in a different volatility regime from the one the policy was measured in — as of 2026-08-28 the live p80 is **1.77%**, i.e. less than half. |
| `ab` | Both arms: trades, net bps per trade, net bps per unit of notional, win rate, drawdown, trades/day. |

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
policy enforces independently — eight slots is a real 8-pair portfolio, not leverage.

It also has to be 8 for the A/B to mean anything: the control arm is a ledger and cannot be
refused, so a cap that throttles only the policy arm would show up as the policy losing.

### 3.4 Serial-per-pair is enforced in the database, not only in the decision.

A partial unique index on `(arm, pair) WHERE status = 'open'` refuses a second open position.
The decision code checks too, but a race between a poll and a restart must not be able to book
two overlapping four-hour holds on one pair — that is the mechanism by which a backtest books
the same move twice and the P&L becomes fiction.

---

## §4 — The A/B (this part IS pre-registered)

**Question.** What does the M3-2 rule add over trading M2's raw gated signal?

**Arms.** Both paper, both live at once on the same bars, both charged M3-4's measured per-pair
crossing cost, both held four hours, both serial per pair.

| | `policy` | `signal_only` |
|---|---|---|
| entry | top 2% by confidence rank over the trailing 14 days | every bar M2's serve gate approves |
| side | the model's 240m direction | the same |
| size | 1/3..5/3 by BTC 24h-move quintile | flat 1.0 |
| risk path | through `RiskManager` | none — a measurement arm, never an order |

**Metrics**, committed here before any live number exists, and matching M3_PROTOCOL §4 so the
live table can sit next to `docs/M3_2_RESULTS.md`: trades, net bps/trade, net bps per unit of
notional, win rate, cumulative net bps, max drawdown, trades/day. Reported per arm by
`/api/health`'s `ab` block and by `Ledger.ab_summary/1`.

**What would count as the policy working:** the `policy` arm's net bps per unit of notional
above the `signal_only` arm's, on a trade count large enough to resolve the difference. It will
be a long time before that count exists — §5 sizes it.

🔴 **Read this before quoting any live number.** The forward test cannot be certified any
faster than the offline one could. M3-2's pooled per-trade standard deviation is 259 bps; at
2.3 trades/day the arms will not separate at 15 bps for a very long time. The A/B's near-term
value is **that the pipeline is provably running and obeying its limits**, not its P&L column.

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
