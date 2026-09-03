# The real-money track — the three blockers, in the order they must be done

**Status: 🔵 ACTIVE, and it is the recommended next session's work.**
Opened 2026-09-01. Owner of the detail for the three rows filed under
"🔴 Open — blockers on trading anything but paper" in [BACKLOG.md](./BACKLOG.md).

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

🔴 **Test against the Binance USDⓈ-M testnet first** (`https://testnet.binancefuture.com`),
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
