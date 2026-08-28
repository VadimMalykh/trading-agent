# Backlog — every piece of planned work, and what would revive it

**Purpose:** one place that enumerates *all* open work, so a fresh session can see what exists
without reading five plan documents and inferring what is still alive. Requested 2026-08-28:
*"document everything clearly and carefully, so we don't lose any of planned stuff and return
back when it's needed."*

**This file is an index, not a plan.** Every row points at the document that owns the detail.
It carries no numbers and no conclusions — those live in the owning plan and would go stale
here. What it does carry, for each item, is the thing that is easiest to lose: **why it is not
being worked on right now, and what would change that.**

**Three states, three treatments** (the rule this file exists to enforce):

| state | meaning | treatment |
|---|---|---|
| 🔵 **active** | being worked on now | full detail in the owning plan's status block |
| 🟡 **parked** | planned, not done, still worth doing | **stays here with a revival trigger** — never archived |
| 🟢 **closed** | answered, *including* "answered as unresolvable" | one-line tombstone + link, so it is not re-opened by accident |
| ⚫ **superseded** | a later result invalidated it | moved to `docs/archive/TRAINING_HISTORY.md`, not listed here |

🔴 **A parked item without a revival trigger is how a plan quietly becomes a graveyard.** If
you defer something, write down what would un-defer it.

---

## 🔵 Active

| item | owner doc | state |
|---|---|---|
| **Deploy M3-5 to `fluxtrader-1`** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | 🔴 **This, and only this, starts the clock.** The code is built, tested (65 tests) and verified end to end on the local stack, but **the local Postgres is a throwaway dev DB** — a forward test that accumulates independent trading days has to run on the always-on VM. Until it is deployed, nothing is being collected. ⚠️ **B4's collector fixes are also awaiting deploy** ([BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) §2 B4) — send them together rather than restarting the collector twice |
| **The forward paper test** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | 🟡 **Ready, not started** — starts when the row above is done. Then it needs no work, only **calendar time**: it is the only mechanism that manufactures new independent trading days. Check it with `curl <host>:4001/api/health`. ⚠️ It will not trade for the first **seven days** (the rank window must fill) and may then idle for weeks (see the volatility note below). Both are the strategy working |
| **M3-0b** — price/funding side-table | [M3_PLAN.md](./M3_PLAN.md) §2 | 🔴 **The only remaining M3 build item**, and nothing blocks it: the data is already exported (`candles_5m.csv.gz`, `funding.csv.gz`, 2026-08-28). It is the only item that adds *new degrees of freedom* rather than re-slicing the same 253 days, and M3-5 added a fourth consumer — the `auto` path's stop/target brake is an unmeasured deviation from a fixed-hold policy and M3-0b's price path is what would price it. Build it on the existing `m3_4/` export, sharing one alignment with **B0** |

**M3-4 completed 2026-08-28** — [M3_4_RESULTS.md](./M3_4_RESULTS.md), read via
[M3_PLAN.md](./M3_PLAN.md) §0.8. Risk #2 closed.

**M3-5 completed 2026-08-28** — [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md). The policy is
wired to a crossing executor, the hard `RiskManager` path is exercised on every entry, the
signal-only A/B control runs beside it, and `/api/health` reports signal liveness. Risk #7
closed; §6's last two exit criteria closed. It left two items open, both below.

---

## 🔴 Open — blockers on trading anything but paper

*New 2026-08-28, from M3-5. Neither blocks the forward paper test; both block real money.*

| item | why it matters | what to do | source |
|---|---|---|---|
| **Verify the Binance USDⓈ-M VIP fee tier** | Every M3 cost uses taker 4.0 / maker 2.0 bps per side because that is what `metrics.py`'s 14 and 5 decompose to. It has **never been checked against the account.** A wrong tier shifts every published M3 number by a constant, in a direction nobody has established | `docker compose exec app mix flux.fee_tier` — the task is written and signs `/fapi/v1/commissionRate` itself. It needs `BINANCE_API_KEY` / `BINANCE_API_SECRET` in the app container, which is the only reason it is still open. It fails loudly rather than printing an unverified number | [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) §2.5, [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) §6 |
| **The `auto` order path is unsigned** | `Binance.Client.post/2` sends neither the `X-MBX-APIKEY` header nor the HMAC-SHA256 signature Binance requires on every TRADE endpoint, so a real order returns 401. Before M3-5 this failed silently; the executor now logs it at boot | Implement request signing (the same HMAC the fee-tier task already does) plus `listenKey` / order-status reconciliation. **Not M3 work** — M3-5's deliverable is the paper A/B — but it is a hard prerequisite for anything beyond paper | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) §6 |

---

## 🟡 Parked — M3

*M3-0b moved to Active above: nothing blocks it any more.*

⚠️ **A planning consequence worth keeping in view:** 2.3 trades/day is an average over a period
that included volatile months, and the served checkpoint has emitted **no gated signal since
2026-06-29** because the market has been calm since July. A forward paper test may idle for
weeks, so **the calendar cost of accumulating the independent days the statistics need is longer
than the trade rate suggests.** `/api/health` now makes that silence legible as correct rather
than as a fault.

---

## 🟡 Parked — the B-wave (book era)

🔴 **This wave is live parked work, not background reading.** It needs **no GPU at any step**,
blocks nothing and is blocked by nothing, and its most likely payoff is not a second model but
**one or two new regime observables for M3's policy** — which is where M3's largest measured
effect already lives. Owner: **[BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md)**.

| item | what | gated on | note |
|---|---|---|---|
| **B4** | Collection fixes — ✅ **code written 2026-08-24, ⚠️ NOT deployed** | nothing | 🔴 **The most time-sensitive item in this file.** Until it is deployed to `fluxtrader-1` nothing has changed about what we collect, and collection gaps are **unrecoverable** — order-book history begins the day the collector is pointed at it and backfills never. See BOOK_ERA_PLAN §2 B4 for the deploy steps and its three acceptance checks |
| **B0** | Book-era side-table → parquet | nothing | **Build as an extension of M3-0b, not separately** — one export, one alignment, two consumers. Has a mandatory acceptance test: `fwd_ret_240` must match the eval dump's `fwd_ret` on a `(pair, ts)` join, or nothing downstream is evidence |
| **B1** | Economic information check (the fixed audit) | B0 | Replaces re-running the 2026-08-04 audit unchanged. Reports **basis points, not Spearman rho** — the earlier audit escalated on rho and the run it triggered was inconclusive |
| **B2** | Book features as **M3 regime observables** | B0, M3-0a ✅ | 🔴 **The highest-expected-value item in the wave.** `spread_bps` was the earlier audit's strongest finding and was classified VOL-PROXY — useless to M2, which emits direction, but potentially very useful to M3, whose 4× effect *is* a volatility regime switch. A book-derived observable would be **contemporaneous** rather than trailing like `btc_absret_1d` |
| **B3** | One book-era GBT, pre-registered | **B1 passing §4.1** | One CPU run on its own throwaway VM, not a search |

**The wave's own exit condition (§4.4), so it cannot drift indefinitely:** if B1 fails §4.1 *and*
B2 fails §4.2, the book question closes until **≥90 days of continuous book history on the 8
main pairs (≈2026-10-15)**, and the plan is archived with that trigger recorded. **Do not open a
B5.**

⚠️ **B2's gate is deliberately hard to pass and that is not the same as the answer being no.**
§4.2 requires >+30 gross bps/trade because 38 days cannot resolve less; the plan states in
advance that a real +15 bps effect *would fail this gate* and must be recorded as **"not yet
decidable", never as a negative result.** This is the [negative-results](./M3_PLAN.md) discipline
applied in advance.

---

## 🟡 Parked — collector / data quality

| item | why it matters | source |
|---|---|---|
| **Raise the trade-tape `limit: 200`** (or move the tape to the uncapped WebSocket stream) | 🔴 M3-4a found the tape is **right-censored**: Binance returns the *most recent* 200 aggTrades, so on busy pairs the oldest are silently discarded and `high`/`low`/`volume` describe only what survived — **BTC 30.4%, ZEC 29.3%, ETH 28.0%** of windows. Censoring concentrates in exactly the busy windows where a resting order fills | [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) §1.2 |
| | **Worth doing regardless of what M3-4 concludes**, and it fixes the problem only *going forward* — the existing 22 days are censored for good. ⚠️ No number measured before the change may be compared to one measured after it (§7) | |
| **Disk budget** | `orderbook_levels` runs ~24 MB/pair/day → ~8.6 GB/month at 12 pairs, against 54 GB free on `fluxtrader-1`: about six months of headroom, under four if the universe grows to twenty | [M3_PLAN.md](./M3_PLAN.md) §2 M3-4 |

---

## 🟢 Closed — tombstones, so they are not re-opened by accident

| question | verdict | where |
|---|---|---|
| **The 12-pair traded universe (8-vs-12)** | **Closed as UNRESOLVABLE on this evaluation period** — not "12 is worse". The effect is within a couple of bps of zero in every fair framing and the data resolves ±37 bps at 80% power. More seeds cannot help; only a longer evaluation period can, and that is calendar, not compute. Served universe stays **8** | [T6_RESULTS.md](./T6_RESULTS.md), [M3_PLAN.md](./M3_PLAN.md) §0.6 |
| **T4 — promote a 12-pair seed** | **Cancelled**, not deferred. There is no verdict for it to wait on | [NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) §2 |
| **A learned M3 policy** | All 14 pre-registered runs lost to the hand-written rule; none passed Tier 1, and a one-feature ablation beat both fitted models. **Do not widen the grid, extend the feature list, or reach for a bigger model class** — pre-registered in advance as not-evidence-for-a-bigger-model | [M3_3_RESULTS.md](./M3_3_RESULTS.md), [M3_PLAN.md](./M3_PLAN.md) |
| **T5 — `/predict_all` served untrained pairs** | **Fixed and shipped** — `serve.py:_servable_pairs()` intersects the whitelist with the checkpoint's own pair list; `/health` reports both | [NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) §2 |
| **M2 experiments** | **Frozen as a research object.** Seven levers tested one at a time; only 15m→5m ever moved. 🔴 **Do not queue another M2 experiment without new *data*** | [NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) §2, §5 |

**The one condition that reopens M2:** order-book history deep enough to sit inside the
*training* window (not just the validation window). That is a **calendar** problem — ≈2027 —
not a modelling one.

---

## Standing constraints that outlive any single item

* **Everything runs in Docker.** No host virtualenv, no `pip install`, no `brew install` —
  including for "just a pandas script". `AGENTS.md` states this first. M3 has its own
  torch-free image (`ml/train/Dockerfile.analysis`, ~200 MB) wrapped by `./scripts/m3.sh`.
* **Only one `gcp_train.sh` run at a time.** Write run queues as serial, never "launch both in
  parallel".
* **Data lives on the always-on VM `fluxtrader-1`**, never the local dev Postgres. Never reason
  about pair readiness, history or row counts from the local DB.
* **The binding statistical constraint on all of M3 is ~220 independent trading days**, and no
  rearrangement of the same 253 days fixes it. **Only forward time does** — which is the
  standing argument for getting to paper trading rather than re-analysing.
