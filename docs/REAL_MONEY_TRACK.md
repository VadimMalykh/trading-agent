# The real-money track — the three blockers, in the order they must be done

**Status: ✅ ALL THREE STEPS DONE 2026-09-10 — the mechanical blockers are cleared; the
evidence blocker (§4) is not, and this document still does not authorise real money.**
Opened 2026-09-01. Owner of the detail for the three rows filed under
"🔴 Open — blockers on trading anything but paper" in [BACKLOG.md](./BACKLOG.md).

## §-1 — Where this stands on 2026-09-10, and what to run next

| step | state |
|---|---|
| 1 fee tier | ✅ **VERIFIED — and the assumption was wrong.** `mix flux.fee_tier` on `fluxtrader-1` with a read-only key: **taker 5.000 / maker 2.000 bps per side** (BTCUSDT). M3-4 assumed 4.0. The correction is +2.0 bps per round trip on every measured cost; `Trading.ExecCost` now charges it (§5 below). The ETHUSDT control was run on 2026-09-10 (Vadim, on the VM): **MATCH** — the tier is account-level as expected, and the verified constant holds for every pair |
| 2 stop/target | ✅ **DECIDED: (a) keep.** The brake is now actually placed on the exchange on the auto path — until this build it was computed and dropped |
| 3 signing | ✅ **BUILT AND DEMONSTRATED, 2026-09-10** — on the demo exchange from the VM (§6.1: signed open, reconciled fill, both brakes as algo orders, reduce-only close, flat after) **and** against a running `auto` executor on the local stack (§6.2: listenKey, fills, positions, ledger mismatch, brake-fill matching). 123/123 tests |

**Q1 (a)** — the read-only key lives in `fluxtrader-1`'s `.env`. **Q2 (a)** — keep.
**Q3 (a)** — build it all now. All three answered by Vadim on 2026-09-10.

🔴 **Nothing here authorises production trading.** The exit criterion is a testnet run, with
`TRADING_MODE` on the VM left at `simulation`. §4 stands unchanged: zero forward trades.

---

## §0 — In plain language, and the bottom line

**What this track is.** Three things stand between the project and being *able* to place a
real order. None of them is research, none needs a GPU, none needs the market to do anything,
and none of them depends on the paper test producing a single trade. They are: (1) we have
never checked what Binance actually charges us, (2) we have never decided what to do about the
stop-loss brake, and (3) the code physically cannot place an order because it does not sign
its requests.

**What this track is NOT.** 🔴 **Finishing it does not mean going live, and this document does
not authorise going live.** It removes the *mechanical* blockers. The *evidence* blocker is
separate and is not addressed here: as of 2026-09-01 the forward paper test has taken **zero
trades under the frozen rule**, so there is no forward evidence that the policy works at all.
Completing this track and then trading real money on today's evidence would be
unjustified. See §4.

**Why do it now.** The forward paper test is regime-blocked (see §1). This track is the only
work whose progress does not depend on the market cooperating, so it is what the waiting time
is for.

### The jargon, defined once

* **basis point (bps)** — 0.01%. On a $10,000 position, 1 bps = $1.
* **taker / maker** — a *taker* order crosses the spread and executes now; a *maker* order
  rests in the book and waits. Takers pay a higher fee. The policy is taker-only (M3-5 §3.1).
* **fee tier** — Binance charges less as your 30-day volume rises. Every M3 number assumes
  **VIP-0: 4.0 bps taker per side**, which nobody has read off the account.
* **round trip** — entry plus exit. The published 14 bps taker round trip is
  4.0 (entry fee) + 4.0 (exit fee) + ~3.0 + ~3.0 (assumed slippage each way).

---

## §1 — Why this track, and why now

🔴 **Superseded in part, 2026-09-03.** The bullets below conclude "it is not a defect". It is one:
every stored candle since 2026-07-18 is a partial first-minute bar (~10% of true volume), which is
why the model did not respond on 08-20/21. See [CANDLE_POLL_DEFECT.md](./CANDLE_POLL_DEFECT.md).
This track's *steps* stand — they never depended on the market — but its premise that the
forward test is unboundedly regime-blocked does not, and the candle repair outranks it.

The forward paper test cannot generate evidence at the moment. Measured 2026-09-01 on the
served checkpoint's own dump (`20260819T142759Z`) and on the live bar log:

* The frozen cut **0.6318973898887634** was last exceeded on **2026-06-29**. That is a dry
  spell of **~64 days and counting** — already the longest in the 252-day evaluation split,
  where the previous maximum was 50 days (the same, still-running spell).
* It is not a defect. Live median confidence is **0.5197** against the split's **0.5194**;
  the live distribution is a clean continuation of the split's own July–August tail.
* It is not the book features going out-of-distribution either: `NORM_DEGENERATE_MODE=zero`
  pins constant-in-train columns to zero in train, val **and** serve, so the model is
  candle-only and never sees live book values.
* It is not seed-specific. **All six** checkpoints on disk show daily-max confidence falling
  from ~0.62–0.66 pre-July to ~0.55–0.59 after, and each stops firing its own cut between
  2026-06-29 and 2026-08-22.
* ⚠️ **Volatility is not the trigger we assumed.** BTC's 1-day absolute return reached
  **0.080 / 0.075 on 2026-08-20/21** — the largest in the whole export, a level that fired on
  **100%** of days historically — and the model did not respond.

**So the calendar cost of the forward test is unbounded and cannot be planned around.** This
track can be.

---

## §2 — The ordered checklist

🔴 **Do them in this order.** Step 1 can change published numbers, which is an input to
step 2's decision; step 3 is the largest and is pointless if step 1 says the economics are
different from what was assumed.

### Step 1 — Verify the Binance fee tier

**Why it is first:** every M3 number rests on 4.0 bps taker/side, unverified. A wrong tier
shifts *every published M3 result* by a constant, in a direction nobody has established. It is
also the cheapest of the three — one command, once the credentials exist.

🔴 **Use a READ-ONLY API key.** `GET /fapi/v1/commissionRate` is a signed **USER_DATA**
endpoint, not a TRADE endpoint. Create the key with *Enable Reading* only and **no** futures
trading permission, so this step cannot place an order even by accident. Do not reuse a key
that has trading rights, and do not commit it — `.env` is gitignored (see `.gitignore`).

```sh
# on fluxtrader-1
cd ~/trading_agent
# put BINANCE_API_KEY / BINANCE_API_SECRET in .env and recreate app (docker compose up -d app),
# or pass them for one run — `exec` does NOT forward host env vars, so use -e:
docker compose exec app mix flux.fee_tier
docker compose exec -e BINANCE_API_KEY=... -e BINANCE_API_SECRET=... app mix flux.fee_tier --symbol ETHUSDT
```

The task is already written (`apps/fluxtrader/lib/mix/tasks/flux.fee_tier.ex`) and signs the
request itself. It **exits non-zero and prints nothing reassuring** if the credentials are
absent — an unverified constant that looks verified is worse than a missing one.

**Bring back:** the full stdout of both invocations, verbatim.

**If it reports MISMATCH:** the task prints the per-round-trip delta. This does **not** require
re-running M3-4 — the study reports gross components, so the correction is a constant — but it
**does** require correcting `docs/M3_4_RESULTS.md` §2 and the economics in `docs/M3_PLAN.md`
§0.8 before anything else in this track proceeds.

### Step 2 — Decide the `auto` path's stop/target

**Why it is second:** it is a decision, not a build, and step 1's outcome is an input to it.

The facts, from [M3_0B_RESULTS.md](./M3_0B_RESULTS.md) §4:

* `RiskManager` attaches `stop_loss_pct: 0.02` / `take_profit_ratio: 2.0` to every `auto`
  entry. The validated policy exits at a fixed four hours and has no barriers at all.
* The brake costs **~10.5 gross bps/trade** (+33.76 → +23.24), roughly **a third of the edge**
  on a policy netting ~20. The stop fires three times as often as the target (34.1% vs 11.2%).
* 🟢 It does **not** affect the running paper test — the paper arms ignore both barriers and
  close on the timer, and the `auto` path cannot trade anyway (step 3).
* 🔴 **The measurement prices the premium, not the insurance.** A fixed-hold backtest over this
  period contains no catastrophe. The 2% stop bounds single-position loss, and the offline
  number cannot tell you what that is worth, because nothing in the sample tested it.

**See §3 for the decision, stated as a question.**

### Step 3 — Implement request signing, then order reconciliation

**Why it is last:** it is the biggest piece, and steps 1–2 can change whether it is worth doing
at all.

`Binance.Client.post/2` (`apps/fluxtrader/lib/fluxtrader/binance/client.ex`) sends neither the
`X-MBX-APIKEY` header nor the HMAC-SHA256 signature that every Binance TRADE endpoint requires,
so `place_order/1` returns **401**. The executor logs this loudly at boot rather than looking
like it is trading (`executor.ex`, the `mode == "auto"` branch).

🟢 **The signing is already written and working, in the fee-tier task** — lift it, do not
reinvent it:

```elixir
# apps/fluxtrader/lib/mix/tasks/flux.fee_tier.ex, defp fetch/3
ts    = System.system_time(:millisecond)
query = URI.encode_query(symbol: symbol, timestamp: ts, recvWindow: 5000)
sig   = :crypto.mac(:hmac, :sha256, secret, query) |> Base.encode16(case: :lower)
# ... then the X-MBX-APIKEY header on the request
```

For a POST the signed payload is the **form body**, not the query string; the signature is
appended as a `signature=` parameter to that same body.

**Scope, in order within the step:**

1. Signed `post/2` + `X-MBX-APIKEY`, with credentials read from the environment and a loud
   startup failure if `TRADING_MODE=auto` and they are absent.
2. **Order-status reconciliation.** A `MARKET` order can partially fill or be rejected after a
   200. The ledger currently assumes the fill. Reconcile against the order's actual status
   before the paper row is written, or the `auto` ledger is fiction.
3. **`listenKey` / user-data stream** for fills and liquidations, so position state is not
   inferred from our own optimism.

🔴 **Test against the Binance USDⓈ-M testnet first** (`https://demo-fapi.binance.com`),
never against production with a small size. `@base_url` is a module attribute in two places
(`client.ex` and the fee-tier task) and must become configurable for this.

---

## §3 — The decisions, each stated as its own question

Each needs an explicit answer before the step that depends on it proceeds.

**Q1. Will you provision a read-only Binance API key for the fee-tier check, and where do the
credentials live?** — Options: (a) read-only key in `fluxtrader-1`'s `.env`, (b) read-only key
passed inline for a single one-shot run and never stored, (c) not yet, leave the constant
unverified and keep every M3 number flagged as resting on an unchecked assumption. **A blocks
nothing else in this track; it blocks the credibility of every published number.**

**Q2. What happens to the 2% stop / 4% target on the `auto` path?** — Options: (a) **keep it**
and accept ~10.5 gross bps/trade as an insurance premium, (b) **widen it** so the premium
falls, accepting a larger single-position loss bound, (c) **make it regime-conditional**, (d)
**drop it**. 🔴 **Do not choose (d) because the backtest says it costs money** — that is the
one reasoning the evidence does not support, since a fixed-hold backtest over this period never
had to survive a 60% overnight move. If (b) or (c), the new setting is a **new rule** and needs
its own pre-registration before it is scored, per M3_PROTOCOL §0.

**Q3. Is step 3 worth building now, or deferred until there is forward evidence?** — Signing is
a hard prerequisite for real money, but real money is not justified on today's evidence (§4).
Options: (a) build it now so the capability is ready when evidence arrives, (b) build only the
signing and defer reconciliation and `listenKey`, (c) defer the whole step and revisit when the
forward test has produced trades. **This is a sequencing preference, not a technical
question** — all three are defensible.

---

## §4 — What finishing this track does NOT do

🔴 **It does not make the system ready to trade real money, and it must not be read that way.**

* The forward paper test has **zero trades under the frozen rule**. There is no forward
  evidence for the policy, only the 253-day backtest.
* The `-50/day` daily loss limit still biases any forward mean **upward** by truncating losing
  days ([M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §4.2). Unresolved.
* The binding statistical constraint on all of M3 remains **~220 independent trading days**,
  and only forward time produces them.

**Exit criteria for this track, and nothing beyond them:** Q1–Q3 answered and recorded; the
fee tier verified or explicitly recorded as unverifiable; the stop/target decision written down
with its reasoning; and — if Q3 is (a) or (b) — a signed order path demonstrated **against
testnet**, with the `auto` path still switched off in production.

---

## §5 — Step 1's result, 2026-09-10: taker 5.0, not 4.0

Verbatim from the VM:

```
Account rate for BTCUSDT:
  taker 5.000 bps/side   maker 2.000 bps/side
MISMATCH — the taker fee is 1.000 bps/side away from the assumption, i.e.
2.000 bps per round trip on EVERY published M3 number, in the
pessimistic-was-too-optimistic direction.
```

4.0 bps is the USDⓈ-M taker rate **with the BNB fee discount**, which this account has never
enabled; the undiscounted VIP-0 rate is 5.0. What changes and what does not:

* **What the paper ledger charges** — corrected in code. `ExecCost.round_trip_bps/1` returns
  M3-4's measured per-pair round trip **plus 2.0 bps** (BTC 8.017 → 10.017, WLD 14.060 →
  16.060, pooled 9.842 → 11.842). The measured table is untouched so it still matches
  M3_4_RESULTS §1 line for line; `measured_round_trip_bps/1` returns it uncorrected. Made
  before any forward trade existed (`paper_trades` was empty), so no row was re-scored.
* **The published offline numbers at "taker 14 bps"** — unchanged and still conservative.
  14 = 4 + 4 + 3 + 3 assumed; the true line is now 5 + 5 + measured slippage ≈ **11.84**
  pooled, so every net-at-14 number (M3-2, the walk-forward W1 +33.23) is still ~2 bps
  *below* the truth rather than ~4. Nothing flips.
* **M3_4_RESULTS §7's re-score, RE-RUN at the corrected fee (2026-09-10, probe
  `ml/train/output/probe/rescore_fee.py`, both eras, re-score only — nothing re-searched):**

  | era | winner worst window @14 | @measured 4.0 (as published) | **@measured 5.0** | pooled @5.0 | eligible configs clearing +0.25 |
  |---|---|---|---|---|---|
  | pre-repair (§7 as published) | +0.25 | +2.43 | **+0.38** | +18.37 | 3 → **1** (the winner only) |
  | repaired (the era in force) | −4.61 | −2.38 | **−4.43** | +17.06 | 0 → 0 |

  So on the published era the winner still clears the +0.25 promotion bar, by 0.13 bps —
  a coin toss, not a margin. On repaired data the verdict is what M3_2_RESULTS_REPAIRED
  already says: it fails the +0.25 bar and passes Tier 1's −5 floor, and the true cost
  (−4.43) lands *between* the published −4.61 at 14 and −2.38 at the too-optimistic fee.
  Nothing flips in either direction; the "measured cost moved things in our favour" reading
  of M3_PLAN §0 item 2 is now worth about +2 bps a trade rather than +4.
* **An exchange-filled row** is charged **10.0 bps** (two taker fees) and nothing else,
  because slippage is already inside a real fill price — `ExecCost.fee_only_round_trip_bps/0`.

`mix flux.fee_tier` now compares the account against the *verified* constant, so re-running
it is a standing check: MATCH means the correction still holds.

**The ETHUSDT control, 2026-09-10 — MATCH.** Run by Vadim on `fluxtrader-1` with `--symbol
ETHUSDT` after the constant was corrected; reported as MATCH (the stdout was not transcribed
here). It confirms what the USDⓈ-M fee schedule says — the tier is per account, not per
symbol — so the 5.0/2.0 line applies to all twelve served pairs and step 1 is closed on both
symbols.

---

## §6 — Step 3 as built, 2026-09-10, and the testnet runbook

**What exists now** (`apps/fluxtrader/lib/fluxtrader/`):

| piece | where | what |
|---|---|---|
| signing | `binance/auth.ex` | HMAC-SHA256 over the payload, `recvWindow` + `timestamp` appended; verified against `openssl dgst` |
| signed client | `binance/client.ex` `signed_get/post/put/delete` | `X-MBX-APIKEY` header; **signed calls go to `trade_url/0`, market data stays on production** |
| the exchange surface | `binance/trade.ex` (behaviour), `binance/trade/rest.ex` | order, order status, cancel-all, leverage, positionRisk, commissionRate, listenKey |
| filters | `binance/filters.ex` | lot step (rounds **down**), tick, min notional — refused before sending |
| the order logic | `trading/exchange_orders.ex` | open → reconcile → brake; close → cancel brakes → `reduceOnly` → on `-2022` read which brake filled |
| the executor's auto path | `trading/executor.ex` | writes the row from `avgPrice`/`executedQty`, `fill_source: "exchange"`, order ids; refuses `auto` without credentials and says so on `/api/health` |
| the user-data stream | `binance/user_stream.ex` | `listenKey` lifecycle; `ORDER_TRADE_UPDATE` brake fills → `Executor.brake_filled/2`; `ACCOUNT_UPDATE` positions → ledger mismatch on `/api/health` |
| ledger | migration `20260910000001` | `fill_source`, four order ids, `exit_reason` (`timer` / `stop` / `target` / `position_missing`) |
| config | `config/runtime.exs` | 🔴 **found on the way:** `TRADING_MODE` and the credentials were read only under `MIX_ENV=prod`, and the container runs `dev` — so the VM's `.env` values never reached the app. Now read in every env but test. `BINANCE_TESTNET=true` selects the testnet for signed calls |

**The testnet runbook.** Testnet keys are created on the testnet web UI
(https://testnet.binancefuture.com — a separate login; not the production keys); the API host
they work against is `https://demo-fapi.binance.com`, which `BINANCE_TESTNET=true` selects. Then, on the VM or locally:

```sh
# 1. one tiny round trip, entirely on the testnet, without the trading app running
# ⚠️ After a pull, compile FIRST. A `mix <task>` that compiles on the way in still runs the
# task module it had already loaded from the old beam — seen twice on 2026-09-10 (stale
# line numbers, an ignored flag). Running the task twice also works; this is cleaner.
docker compose exec app mix compile
# ⚠️ `docker compose exec` does not forward host env vars: pass each with -e
docker compose exec -e BINANCE_TESTNET=true \
  -e BINANCE_API_KEY=<testnet key> -e BINANCE_API_SECRET=<testnet secret> \
  app mix flux.testnet_smoke
#    expect: filters, OPEN with a reconciled fill and two brake ids, HOLD, CLOSE with
#    reason=timer, position flat before and after, and the last line TESTNET_OK

# 2. the same through the running executor (local stack only — NOT on fluxtrader-1):
#    put BINANCE_TESTNET=true, TRADING_MODE=auto and the testnet keys in .env, then
docker compose up -d --build app
curl -s localhost:4001/api/health | jq '{mode, executor, user_stream}'
#    expect mode "auto", executor.testnet true, executor.auto_refused null,
#    user_stream.status "connected"
```

**Bring back:** the full stdout of `flux.testnet_smoke`, verbatim, and the `/api/health`
excerpt. If the smoke fails at `open`, the message names the step and the exchange's error
code; `-2019` is testnet margin (top up the testnet wallet), `-4164` is min notional (raise
`--notional`), `-1022` is a signature problem and is a bug here, not there. A failed run can
leave a position behind (the first one did, unbraked); `--flatten` closes it through the same
close path before the smoke proceeds.

### §6.1 — The testnet run, 2026-09-10 (from `fluxtrader-1`, demo keys)

```
Trading host: https://demo-fapi.binance.com  symbol: BTCUSDT  leverage: 5
filters: step 0.0001 tick 0.1 min_notional 50.0
  position (before): amt=0.0000 entry=0.0 mark=78126.37161232 upnl=0.00000000 lev=5
mark price (premiumIndex): 78126.35856884

OPEN  BUY ~7.68e-4 @ ~78126.35856884 (notional ~60.0 USDT)
  filled qty=0.0007 avg=78128.9 order=28579013634
  stop=1000000200223304 target=1000000200223309

HOLD 10s
  position (during): amt=0.0007 entry=78128.90000000001 mark=78124.17423194 upnl=-0.00330803 lev=5

CLOSE SELL reduceOnly 0.0007
  filled qty=0.0007 avg=78069.5 order=28579013806 reason=timer
  round trip: -7.6 bps before fees
  position (after): amt=0.0000 entry=0.0 mark=78123.18329710 upnl=0.00000000 lev=5

TESTNET_OK — open, brake, close and reconcile all succeeded on BTCUSDT
```

Three things the runs before this one taught, all fixed the same day:

* **A `FILLED` response can carry no fill.** The demo answered the first market order
  `status: FILLED, avgPrice: 0, executedQty: 0`; only the read-back had the numbers.
  `ExchangeOrders` now polls a FILLED order with empty fill fields like a NEW one. That first
  run left a 0.0007 BTC position open and unbraked on the demo; by the time `--flatten` ran
  it was already flat (not closed by us — noted, not explained).
* **Conditional orders are refused on `/fapi/v1/order` (`-4120`).** `STOP_MARKET` and
  `TAKE_PROFIT_MARKET` go through `POST /fapi/v1/algoOrder` (`algoType=CONDITIONAL`,
  `triggerPrice`); the row stores **algo ids**, a triggered brake creates a normal order whose
  id is the algo's `actualOrderId`, and both the `-2022` read-back and the user-stream match
  go through that id. The smoke now **fails** (`TESTNET_UNBRAKED`) if either brake is missing.
* **Compile before running a task after a pull.** A `mix <task>` that compiles on the way in
  still runs the already-loaded old beam; both "stale" failures of the day were this.

⚠️ The −7.6 bps slip on 0.0007 BTC is the **demo book**, which is thin; it says nothing about
production slippage, which M3-4 measured. Likewise the demo charges **4.0 bps** commission
(0.0218762 on 54.69 USDT), not the 5.0 the production account pays.

### §6.2 — The user-data stream against a running `auto` executor, 2026-09-10 (local stack)

Local `app` started with `BINANCE_TESTNET=true TRADING_MODE=auto` and the demo keys in the
shell environment (never in a file); `ml_inference` locally serves a different checkpoint, so
the policy guard (`checkpoint_bound: false`) kept real signals from trading — the executor
and the stream were live, the rule was not. Then `flux.testnet_smoke --hold-seconds 45` drove
a demo position through while `/api/health` was read:

```
user_stream (before):  status connected, listen_key_present true, positions {}, mismatches []
user_stream (during):  positions {BTCUSDT: amount 0.0007, entry 78129.3}
                       mismatches [{symbol BTCUSDT, on exchange_only}]   <- correct: the smoke bypasses the ledger
                       recent_fills: 28579020761 MARKET BUY NEW, then FILLED qty 0.0007 @78129.3 fee 0.0218762
user_stream (after):   positions {}, mismatches [], 4 fills (BUY NEW/FILLED, SELL reduceOnly NEW/FILLED)
app log:               [AUTO] fill on BTCUSDT order 28579021315 is not an open row's brake — ignored
```

So: the listenKey lifecycle, `ORDER_TRADE_UPDATE`, `ACCOUNT_UPDATE`, the exchange-vs-ledger
mismatch, and the brake-fill matcher (which correctly declined a reduce-only fill that no row
owned) all ran against the real stream. **Not exercised live, by construction:** a brake
actually triggering on the exchange and being booked onto a row. That path is
`executor_auto_test.exs` ("a brake fill reported by the user stream closes the row") against
the fake; exercising it live needs a position opened *by the executor* with a trigger price
inside the noise, which is a deliberate test to design, not a smoke to run. The local `app`
was recreated back in `simulation` afterwards.

### §6.3 — Where to continue from here

1. Nothing on this track is pending. The forward test runs; see BACKLOG "Right now".
2. If a brake-trigger live test is wanted: give `flux.testnet_smoke` a `--stop-pct` option
   *and* have it write a ledger row through `Executor.open/3` (needs the app's node, so it
   would be an HTTP or remote-shell entry point, not a Mix task) — then watch
   `exit_reason: stop` appear on the row. Design it before running it.
3. Going live is BACKLOG "Right now" row 3: a trading-enabled production key, `TRADING_MODE=auto`,
   `BINANCE_TESTNET` unset, and — first — a recorded decision resting on forward evidence.

**Not built, on purpose:** limit orders (M3-4 §3) — *until 2026-10-21: the pilot arm's maker
path, BOOK_WAVE2_PLAN §M2 (`LIVE_PILOT_MAKER_PATH`, `flux.testnet_smoke --maker`); the paper
arms still cross* — hedge-mode position sides (the account is
one-way), and any automatic switch to production. `TRADING_MODE=auto` on `fluxtrader-1`
without `BINANCE_TESTNET=true` would trade real money on the next signal — it is a deliberate
act, and §4 says the evidence for it does not exist yet.

## §7 — The micro-pilot: real orders at ~$100 a trade, paper test untouched (built 2026-09-21)

**Needed from Vadim: a Binance API key with futures-trading rights (no withdrawal rights,
IP-restricted to the VM if possible) and ~$500 USDT in the USDⓈ-M futures wallet. Then say
"turn the pilot on" — Claude runs the steps below over `gcloud compute ssh`.** Decided by
Vadim 2026-09-21: build now, $500 budget for now, revisit the amount later (every number
below is an env var, changed with a restart).

**In plain language.** Each time the paper policy opens a trade, the app also places the same
trade on Binance with real money, small and at a fixed size, holds it the same four hours
behind the same 2% stop / 4% target, and books the exchange's real fill prices under arm
**`live`**. The paper test (arms `policy` and `flat_size`) keeps running exactly as registered
— the executor stays in `simulation`, so §4's objection to `TRADING_MODE=auto` (real fills
landing in the registered ledger) does not apply. **What it is for:** proving real fills,
slippage, the brake and the account plumbing. **What it is not:** evidence. At $100 a trade
the backtested edge (+33 bps, 1 bp = 0.01%) is ~$0.33 a trade; R0–R5 never read this arm.

| setting (env var) | default | meaning |
|---|---|---|
| `LIVE_PILOT` | `false` | the switch; also needs credentials and a non-`auto` executor |
| `LIVE_PILOT_NOTIONAL_USD` | 100 | position size per trade, flat (the 1/3..5/3 ladder is not mirrored) |
| `LIVE_PILOT_LEVERAGE` | 1 | exchange leverage setting |
| `LIVE_PILOT_MAX_POSITIONS` | 4 | concurrent `live` positions → at most $400 deployed at 1x |
| `LIVE_PILOT_DAILY_LOSS_USD` | 10 | realised loss since 00:00 UTC after which entries stop for the day |
| `LIVE_PILOT_MAX_TOTAL_LOSS_USD` | 100 | **kill level**: cumulative realised loss after which the pilot stays off until raised |
| `LIVE_PILOT_CAPITAL_USD` | 500 | informational (reported on `/api/health`), the budget decided above |
| `LIVE_PILOT_STOP_PCT` | unset → `STOP_LOSS_PCT` (0.02) | **added 2026-10-19:** the pilot's own stop as a fraction; the target is `TAKE_PROFIT_RATIO` × it. The VM is to run **0.10** (below) |

Limits are computed from the `live` rows in `paper_trades` on every entry, so a restart cannot
reset them (`Trading.LivePilot`). ⚠️ **BTCUSDT cannot trade at $100**: its minimum order is
0.001 BTC (> $100), so BTC signals are counted as `live_open_failed` and skipped; every other
served pair's minimum is $5–20. Raise the notional to ~150 (and drop max positions to 3) if BTC
matters. ⚠️ With four slots, a fifth simultaneous policy trade is not mirrored
(`live_refused_max_positions`) — acceptable for an operations pilot.

🔴 **The account is shared with Vadim's manual trades** (preflight 2026-09-21: one-way mode,
`canTrade`, wallet $437, manual positions on WLDUSDT, ASTERUSDT, ADAUSDT and one resting
order). The pilot's brakes are `closePosition` and its close cancels every order on the symbol,
so **it refuses any symbol on which the exchange already shows a position**
(`live_refused_foreign_position`; an unreadable position counts as one). What code cannot
guard: **opening a manual position or order on a symbol while the pilot holds it** — the
pilot's stop would close both and its timed close would cancel the manual orders. Check the
dashboard's open `live` positions before trading a served pair by hand, or move the pilot to a
sub-account (the clean fix: new key in `.env`, nothing else changes).

**Turn it on (Claude, on `fluxtrader-1`):**
1. Vadim puts the trading key into `~/trading_agent/.env` as `BINANCE_API_KEY` /
   `BINANCE_API_SECRET` (replacing the read-only key; `mix flux.fee_tier` keeps working) and
   adds `LIVE_PILOT=true`. Account must be in **one-way** position mode.
2. Wait until no paper position is open (`/api/health` → `ab[].open == 0`), then
   `docker compose up -d app` (recreate — `restart` does not re-read `.env`).
3. Verify `/api/health`: `live_pilot.enabled: true`, `executor.mode: "simulation"`,
   `executor.live_orders: true`, `user_stream.status: "connected"`, policy block unchanged
   (`checkpoint_bound: true`, 12 pairs). Boot log carries `[LIVE] MICRO-PILOT IS ON … (PRODUCTION)`.
4. First real trade: compare the `live` row's `entry_price` with the `policy` row's — that gap
   is the slippage paper assumes — and confirm both brakes exist on the exchange.

**Rehearsal before real money (optional, local stack only, never the VM):**
`BINANCE_TESTNET=true LIVE_PILOT=true` with demo keys; same code path against the demo exchange.

**Turn it off:** set `LIVE_PILOT=false`, recreate `app`. Open `live` rows still close on the
exchange at their timer (an exchange-filled row closes on the exchange in every mode).

**Reinstall on another instance:** nothing beyond the repo and `.env` — the pilot is app
config, the `live` rows live in `paper_trades`, no timer or service is installed.

**Read 2026-10-19 — what the pilot is running, and why its ledger differs from the three paper
arms' (Vadim's question).** The pilot runs the same model, cut and decision as the paper
`policy` arm — checkpoint `d4621b0f…` (X8″ seed 3) bound, cut 0.5860595703125, twelve pairs,
`executor.mode: simulation`, `live_orders: true`, user-data stream connected, no mismatches,
app code `88d1d11` on the VM (the commits after it touch `ml/` and `docs/` only). It is not a
different algorithm. Its 38 closed trades (10-07 → 10-18) read **−2.4 net bps a trade, −$0.83
realised**, against `policy` +42.3 (57 trades), `flat_size` +32.1 (61), `explore_cov05` +7.3
(152). Three structural differences account for it, measured on `paper_trades` (fifth start):

1. **The exchange brake — about 80 % of the gap.** `LivePilot.check` attaches the 2 % stop and
   4 % target `RiskManager` would (`STOP_LOSS_PCT` / `TAKE_PROFIT_RATIO`); the three paper arms
   have no exit but the four-hour timer (M3_5 §5 row 5 — every one of their 270 closed rows is
   `exit_reason: timer`). **13 of the 38 live trades stopped, 2 hit the target.** On the 38
   entries both arms took: the 13 stopped were −1,444 bps gross on the policy arm and −2,350 on
   the pilot (gap **−906** — four were policy winners by the timer: SOL 10-13 +499 against −161
   stopped, AVAX 10-08 +73 / −283, WLD 10-11 +48 / −242, ZEC 10-12 −25 / −247); the 2 targets
   +1,158 / +741 (**−417**, the cap); the 23 timer exits +2,237 / +1,898 (**−339**, fills).
   Total −1,662 bps gross over 38 trades, −1,323 of it the brake — ≈ 35 bps a trade against
   X6's offline price of ~30 per notional for the same brake. Policy net on the 38: +1,438;
   live −91.
2. **Four slots and a shared account — the other 20 %, and a selection effect.** 19 of the 57
   policy entries were not mirrored: 14 at `max_positions` (signal clusters of 6–9 inside
   twenty minutes on 10-07, 10-08 and 10-17; BTC 10-14 14:55 with four open), and **all 5 ADA
   entries** as a foreign position — the account holds Vadim's manual ADA (`[LIVE] ADAUSDT: the
   account already holds a position the pilot does not own … not mirrored`, 10-12 14:55; the
   only rule that fits 10-08 15:25 and 10-13 00:50, when slots were free). The 19 missed were
   +973 bps net on the policy arm (+51 a trade, the arm's own average; ADA 10-13 +668 the
   largest single trade of the ledger).
3. **Fills — not the cause.** Mean entry slippage against the policy row's price −2.5 bps over
   the 38 (+10.8 adverse on the timer exits, −30.6 favourable on the stopped — they were filled
   better and stopped anyway); cost 10 bps (two taker legs) against paper's 12.4 measured; BTC
   fills at 0.001 BTC ($84 notional, as recorded 10-07).

Nothing is broken: the pilot does what this section says — mirror, brake, cap — and the brake's
mechanics are now proven on 15 exchange exits, which was one of its four stated jobs. What the
read shows is that the brake it inherited from `RiskManager` is a different policy from the one
the paper test scores and §4.3 reads, so the `live` arm cannot be read against the paper arms
while it is on. **Decision for Vadim (BACKLOG handoff E2):** (a) keep the brake — the pilot
stays an operations test and its P&L is not compared to the paper arms; (b) **remove the stop
and target from the pilot so it mirrors the scored timer-only rule** (recommended now that the
brake is proven: `LivePilot.check` returns no `stop_loss` / `take_profit`, the timed close
stays, the daily / total loss limits remain the real-money cover; a code change, tests, and an
app recreate with no `live` row open); (c) with either, raise `LIVE_PILOT_MAX_POSITIONS` so
clusters are mirrored — 8 × $100 exceeds the $500 budget, so it means a smaller notional or
more capital. Until (b) is done, do not quote the `live` arm's numbers beside the paper arms'.

**Decided 2026-10-19, Vadim's word: "increase stop to 8–10 % (measure first what's better). Also
allow more than 4 positions."** Measured first, on the VM's 1-minute candles against every closed
paper trade of the fifth start (57 `policy`, 152 `explore_cov05`; the worst intrabar move against
the entry inside the four hours):

| stop | policy trades it fires on (of 57) | gross change vs the timer | explore trades (of 152) |
|---:|---:|---:|---:|
| 2 % | 19 | −1,825 bps | 41 |
| 3 % | 10 | −659 | 24 |
| 5 % | 3 | −399 | 11 |
| 6 % | 3 | −699 | 5 |
| 7 % | 1 | −223 | 5 |
| **8 %** | **0** | 0 | 2 (both WLD shorts, −8.9 / −10.0 %) |
| **10 %** | **0** | 0 | **0** |

Median worst move −1.05 % (policy) / −1.16 % (explore); worst −7.9 % (WLD short, 10-10) / −10.0 %.
Every stop that fires loses against the timer at every level, as M3_0B §5 found offline (the
barrier ladder is monotone: the wider, the closer to the fixed hold). **10 % chosen**: nothing in
209 trades reached it, 2 % beyond the worst; the target at `TAKE_PROFIT_RATIO` × 10 % = 20 %
never fires (best move +10.7 %). The pilot therefore mirrors the scored timer exit and keeps a
catastrophe cover. **Code (`1ee6302`):** `LIVE_PILOT_STOP_PCT` → `LivePilot` config `stop_pct`,
the brake reads it, `/api/health` `live_pilot.stop_pct` / `take_profit_pct` report it; tests
green (146 + 18). **Slots:** the account's USDT wallet is $434 (available $513 with the manual
ADA long's unrealised +$93; ADA 1,326 at 20x, $293 notional — the position that blocks ADA for
the pilot), so at 1x only four $100 slots fit; **8 slots at 2x** ($50 margin each, $400 — the
same $100 notional and the same P&L per trade; clusters of up to nine signals were seen) is the
setting. Leverage is set per symbol at order time and never touches the manual ADA position.
Next divergence to watch, not changed: the pilot's `$10/day` entry stop is 1.25 % of $800
deployed where the paper arm's is 5 % of $1,000; it has not fired yet.

**Deploy — Vadim runs it (the session's deploy step was refused by the tool's production
guard), with no `live` or A/B row open (`/api/health` → `live_pilot.open` 0 and `ab[].open` 0):**
```sh
gcloud compute ssh --zone me-central1-b fluxtrader-1 --project fluxtrader
cd ~/trading_agent && git pull origin main && git log --oneline -1          # expect 1ee6302 or later
curl -s localhost:4000/api/health | python3 -c 'import json,sys; h=json.load(sys.stdin); print("open:", h["live_pilot"]["open"], [a["open"] for a in h["ab"]])'
cp .env .env.bak_20261019
printf 'LIVE_PILOT_STOP_PCT=0.10\nLIVE_PILOT_MAX_POSITIONS=8\nLIVE_PILOT_LEVERAGE=2\n' >> .env
docker compose up -d app            # recreate — `restart` does not re-read .env; ~10 min of degraded book cadence follows (M3_5 §2)
sleep 90 && curl -s localhost:4000/api/health | python3 -c 'import json,sys; h=json.load(sys.stdin); print(h["live_pilot"]); print("bound:", h["policy"]["checkpoint_bound"], h["policy"]["frozen_threshold"])'
docker compose logs app | grep "MICRO-PILOT IS ON"      # expect "… 2x, max 8 open"
```
Expected on `/api/health`: `live_pilot.stop_pct 0.1`, `take_profit_pct 0.2`, `max_positions 8`,
`leverage 2`, `enabled true`, `refusal null`, the policy block unchanged (`checkpoint_bound true`,
cut 0.5860595703125 — the forward clock is untouched by this; the pilot is not the registered
test).

**DEPLOYED 2026-10-19 on Vadim's "Deploy", by Claude over `gcloud compute ssh`.** First recreate
07:35:08 UTC with nothing open: the app came up with 8 slots at 2x but `stop_pct 0.02` — the
compose service passes an explicit list of `LIVE_PILOT_*` variables and the new one was not in
it (`0710e1d` adds `LIVE_PILOT_STOP_PCT: ${LIVE_PILOT_STOP_PCT:-}`); second recreate 07:38 UTC,
again with nothing open. Verified 07:40:36 UTC: `live_pilot.stop_pct 0.1`, `take_profit_pct 0.2`,
`max_positions 8`, `leverage 2`, `enabled true`, `refusal null`, `open 0`; `checkpoint_bound true`,
`served_candle_interval 5m`, `served_closed_bars_only true`, cut 0.5860595703125, `last_error`
null, inference ok, `executor.mode simulation`, `live_orders true`, user stream connected; boot
log `MICRO-PILOT IS ON … 2x, max 8 open`; `.env` backed up as `.env.bak_20261019`. The forward
clock is untouched (same start, same checkpoint). The `live` arm's rows before 07:38 UTC carry
the 2 % brake and are not read beside the paper arms; from the next `live` entry on they are. The first `live` trade after the deploy: its `stop_order_id` order on the exchange sits
10 % from the fill. From that trade on the `live` arm can be read beside `policy` on shared entries.
