# The real-money track — the three blockers, in the order they must be done

**Status: 🔵 ACTIVE — steps 1 and 2 DONE, step 3 BUILT on 2026-09-10; the testnet run is
what remains.** Opened 2026-09-01. Owner of the detail for the three rows filed under
"🔴 Open — blockers on trading anything but paper" in [BACKLOG.md](./BACKLOG.md).

## §-1 — Where this stands on 2026-09-10, and what to run next

| step | state |
|---|---|
| 1 fee tier | ✅ **VERIFIED — and the assumption was wrong.** `mix flux.fee_tier` on `fluxtrader-1` with a read-only key: **taker 5.000 / maker 2.000 bps per side** (BTCUSDT). M3-4 assumed 4.0. The correction is +2.0 bps per round trip on every measured cost; `Trading.ExecCost` now charges it (§5 below). Only BTCUSDT was read; the fee is account-level on USDⓈ-M, so the ETHUSDT control is a formality — run it when convenient |
| 2 stop/target | ✅ **DECIDED: (a) keep.** The brake is now actually placed on the exchange on the auto path — until this build it was computed and dropped |
| 3 signing | 🟢 **BUILT, 122/122 tests pass, not yet demonstrated on the testnet.** Signed order path, filters, reconciliation, brake, user-data stream, health block, and a one-shot testnet task (§6 below) |

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
# put BINANCE_API_KEY / BINANCE_API_SECRET in the app container's env, then:
docker compose exec app mix flux.fee_tier
docker compose exec app mix flux.fee_tier --symbol ETHUSDT   # a second symbol, as a control
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
* **M3_4_RESULTS §7's re-score at measured cost** — every net number there is ~2.0 bps × mean
  size too high. The winner's worst window was +2.43 against the +0.25 bar; ~+0.4 after
  the correction, still above it, but close enough that it should be re-read off a re-run,
  not inferred. Filed in BACKLOG as a one-command follow-up, not done here.
* **An exchange-filled row** is charged **10.0 bps** (two taker fees) and nothing else,
  because slippage is already inside a real fill price — `ExecCost.fee_only_round_trip_bps/0`.

`mix flux.fee_tier` now compares the account against the *verified* constant, so re-running
it is a standing check: MATCH means the correction still holds.

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
BINANCE_TESTNET=true BINANCE_API_KEY=<testnet key> BINANCE_API_SECRET=<testnet secret> \
  docker compose exec app mix flux.testnet_smoke
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
`--notional`), `-1022` is a signature problem and is a bug here, not there.

**Not built, on purpose:** limit orders (M3-4 §3), hedge-mode position sides (the account is
one-way), and any automatic switch to production. `TRADING_MODE=auto` on `fluxtrader-1`
without `BINANCE_TESTNET=true` would trade real money on the next signal — it is a deliberate
act, and §4 says the evidence for it does not exist yet.
