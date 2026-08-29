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
| **Deploy M3-5 to `fluxtrader-1`** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | ✅ **DONE 2026-08-28.** The clock has started |
| **The forward paper test** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | 🔵 **RUNNING. Restarted 2026-08-29** on the twelve-pair universe (see the row below). It needs no work, only **calendar time**: it is the only mechanism that manufactures new independent trading days. Check it with `curl localhost:4000/api/health` **on the VM** (host port 4000 there; 4001 is the local-compose mapping). ⚠️ `warm: false` until the rank window holds 2,016 bars — that is **~14 hours at twelve pairs, NOT seven days**; the constant is a bar count pooled across served pairs, and every document said "seven days" until 2026-08-29. It may then idle for weeks (see the volatility note below). Both are the strategy working |
| **Widen the served universe to 12** | [M3_PLAN.md](./M3_PLAN.md) §0.6 | ✅ **DONE 2026-08-29.** The four extras now carry their own measured crossing cost, so nothing served falls back to a pooled number. See "The twelve-pair widening" below |
| **M3-0b** — price/funding side-table | [M3_0B_RESULTS.md](./M3_0B_RESULTS.md) | ✅ **DONE 2026-08-29. This was the last M3 build item — M3 now has none.** Acceptance passes on all four dumps (2,655,988 bar-comparisons, every one exact), and it carries **B0** in the same alignment, which closes B0 and unblocks B1. See "What M3-0b found" below — one of its three results is a live setting that needs a decision |

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

## What M3-0b found, 2026-08-29 — and the one decision it hands over

**[M3_0B_RESULTS.md](./M3_0B_RESULTS.md)** is the record. Three results, in descending order of
how much they matter:

1. 🔴 **The `auto` path's 2% stop / 4% target costs ~10.5 gross bps per trade** — +33.76 →
   +23.24, on a policy netting ~20. `RiskManager` attaches it to every `auto` entry
   (`stop_loss_pct: 0.02`, `take_profit_ratio: 2.0`); the validated policy exits at a fixed
   four hours. The stop fires three times as often as the target (34.1% vs 11.2%). 🟢 **The
   running paper test is NOT affected** — `Executor`'s paper arms ignore both barriers and
   close on the timer, and the `auto` path cannot trade because it is unsigned. Filed with the
   **real-money blockers**, which is where the executor's own moduledoc said this belonged:
   the brake "must be priced before real money goes near this", and now it is.
2. 🟢 **Funding is a rounding error: +0.14 bps/trade**, moving the headline +20.59 → +20.45. It
   was an unquantified term for the whole project. ⚠️ **HYPEUSDT settles every 4 hours, not 8**
   — the schedule is now read per pair from the data, never assumed; a hardcoded 8h calendar
   would have halved it on a pair the policy trades.
3. 🟢 **C4b is answered.** Every barrier setting tried loses to the fixed 4h hold (best +9.2
   against +19.8 net bps), improving monotonically as the band widens back toward it. The
   label/booking mismatch is real and points *away* from barriers, so accepting it costs
   nothing. ⚠️ This is a slice, not a search — six (stop, target) pairs at one horizon on one
   entry rule. Trailing stops, vol-scaled bands and regime-conditional barriers stay untested,
   and stay that way until someone writes a pre-registration.

⚠️ **Two corrections to what the plans asserted**, both caught by the acceptance test rather
than by review: M3-0b's data was **not** "already on disk" (the M3-4 export is the 23-day book
era, and 96% of the policy's trades fall outside it — the price path is now its own export over
2025-11-15..2026-08-30), and funding is **not** "a real term in the P&L, not a rounding error"
at a 4h hold. Both assertions were reasonable; measuring is what settled them.

---

## 🔴 Open — blockers on trading anything but paper

*New 2026-08-28, from M3-5. Neither blocks the forward paper test; both block real money.*

| item | why it matters | what to do | source |
|---|---|---|---|
| **Verify the Binance USDⓈ-M VIP fee tier** | Every M3 cost uses taker 4.0 / maker 2.0 bps per side because that is what `metrics.py`'s 14 and 5 decompose to. It has **never been checked against the account.** A wrong tier shifts every published M3 number by a constant, in a direction nobody has established | `docker compose exec app mix flux.fee_tier` — the task is written and signs `/fapi/v1/commissionRate` itself. It needs `BINANCE_API_KEY` / `BINANCE_API_SECRET` in the app container, which is the only reason it is still open. It fails loudly rather than printing an unverified number | [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) §2.5, [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) §6 |
| **Decide what to do about the `auto` path's stop/target** | The 2%/4% brake costs **10.5 gross bps/trade**, about a third of the edge — now measured ([M3_0B_RESULTS.md](./M3_0B_RESULTS.md) §4). 🟢 **Not urgent and not a bug.** The paper arms ignore both barriers and close on the timer, so the running A/B is unaffected; the brake bites only on the `auto` path, which cannot trade anyway. But it bounds single-position catastrophe loss, and the offline measurement contains no catastrophe — **it prices the premium, not the insurance** | Keep it and accept the premium, widen it, or make it regime-conditional. The one thing not to do is drop it *because* the backtest says it costs money: a fixed-hold backtest has never had to survive a 60% overnight move. Decide it alongside the two rows below, as part of going live | [M3_0B_RESULTS.md](./M3_0B_RESULTS.md) §4, `executor.ex` moduledoc |
| **The `auto` order path is unsigned** | `Binance.Client.post/2` sends neither the `X-MBX-APIKEY` header nor the HMAC-SHA256 signature Binance requires on every TRADE endpoint, so a real order returns 401. Before M3-5 this failed silently; the executor now logs it at boot | Implement request signing (the same HMAC the fee-tier task already does) plus `listenKey` / order-status reconciliation. **Not M3 work** — M3-5's deliverable is the paper A/B — but it is a hard prerequisite for anything beyond paper | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) §6 |

---

## 🟡 Parked — M3

*M3-0b is done (see above). Its stop/target decision is filed with the real-money
blockers, not here, because it does not affect the running paper test.*

| item | what | gated on | revival trigger |
|---|---|---|---|
| **Export `open_interest`** | B0 builds **nine of its eleven** scalars; `oi` and `oi_chg` are missing because `open_interest` is not one of the tables `scripts/gcp_m3_export.sh` pulls | nothing | A one-line export change plus a re-run of `m3 bookera` — **not** an alignment change. Do it if B1 or B2 wants OI; they can proceed on nine without it |
| **Re-pre-register the served coverage** | The universe went 8 → 12 on 2026-08-29 at an unchanged cov 0.02, which takes **more** trades (3.05/day vs 2.02), not better ones. T6's count-matched cut on twelve is **0.01288**, and on the 8-pair arm tightening the cut alone was worth **+12.72 bps** while widening the universe at a fixed cut was worth **−2.51**. So the cut, not the pairs, is where T6's signal lived | nothing technical | 🔴 **Blocked by protocol, not by work.** M3_PROTOCOL §0 forbids re-picking a searched dimension after seeing results; this needs a fresh pre-registration on the population it will be served from, written before anything is scored. Revive it when someone is prepared to write that document first — **not** by re-scoring the grid and picking the winner |

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
| ~~**B4**~~ | ✅ **DONE — deployed and verified 2026-08-28.** `event_time` filling 100%; `long_short_ratios` holding 116,073 rows over 12 symbols spanning ≈33 days (the one-shot ~30d backfill worked) | — | **B4.3 answered `DEPTH_OK`** — 586 `depthUpdate` frames in 60s from the VM's egress. See the new row below: this is a result, not just a closed chore |
| ~~**B0**~~ | ✅ **DONE 2026-08-29** — built as an extension of M3-0b exactly as planned, one export and one alignment. `book_era_5m.parquet` (79,488 rows x 12 pairs) and `book_era_1m.parquet` (423,130 rows), by `./scripts/m3.sh -m m3 bookera`. **The mandatory acceptance test passes on all four dumps**, every overlapping row exact. ⚠️ Nine of eleven scalars — `oi`/`oi_chg` need an export change (filed above) | — | **B1 and B2 are unblocked** |
| **B1** | Economic information check (the fixed audit) | ~~B0~~ ✅ **nothing** | 🟢 **Unblocked 2026-08-29.** Replaces re-running the 2026-08-04 audit unchanged. Reports **basis points, not Spearman rho** — the earlier audit escalated on rho and the run it triggered was inconclusive |
| **B2** | Book features as **M3 regime observables** | ~~B0~~ ✅, M3-0a ✅ — **unblocked** | 🔴 **The highest-expected-value item in the wave.** `spread_bps` was the earlier audit's strongest finding and was classified VOL-PROXY — useless to M2, which emits direction, but potentially very useful to M3, whose 4× effect *is* a volatility regime switch. A book-derived observable would be **contemporaneous** rather than trailing like `btc_absret_1d` |
| **B3** | One book-era GBT, pre-registered | **B1 passing §4.1** | One CPU run on its own throwaway VM, not a search |

### 🟢 New, from B4.3 — a WS depth consumer is now a real option

**`@depth` is NOT egress-blocked.** The plan was written against the risk that it sat where
`!forceOrder@arr` sits (upgrade + ACK, then silence — which is why `liquidations` has 0 rows).
It does not: 586 depth frames arrived in a 60s window from `fluxtrader-1` itself.

🟡 **Parked, with an explicit revival trigger.** Nothing needs it *today* — the 5s REST book
poll is what every existing number was measured on, and swapping the source mid-flight would
break comparability exactly as the tape change did (§7 of M3_4_PROTOCOL). What changed is that
the pessimistic branch is closed: **the 5s cadence is a choice, not a ceiling**, and §1.2's
fee-wall arithmetic is not the only lever left at short horizons.

**What would revive it:** any result that is limited by book *resolution* rather than book
*history* — most likely B2, if a book-derived regime observable looks promising at 5s and the
question becomes whether finer sampling sharpens it. Build it then, not before.

⚠️ Whoever builds it should first re-check the `@aggTrade` control: it reported **0 frames** in
the same window on a continuously-trading pair, so the probe's control did not do its job. That
does not affect the depth verdict, but do not assume the trade stream is reachable on its basis.

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
| ~~**Raise the trade-tape `limit: 200`**~~ | ✅ **DONE 2026-08-28** — raised to 1000, the endpoint maximum, and verified request-weight-neutral (aggTrades costs 20 weight at every limit, measured). Post-change sampling over 25 clean minutes shows **3 of 861 windows at the new cap (0.35%)**, against the old **30.4% on BTC**. The residual is irreducible by this route — 1000 is the endpoint maximum — and would need the WS tape to close (see the B4.3 row). ⚠️ It fixes the tape only *going forward* — the existing history is censored for good, and per §7 **no number measured before the change may be compared to one measured after it** | [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) §1.2 |
| **Disk budget** | `orderbook_levels` runs ~24 MB/pair/day → ~8.6 GB/month at 12 pairs, against **53 GB free** on `fluxtrader-1` (46% used, checked 2026-08-29): about six months of headroom, under four if the universe grows to twenty. ⚠️ Now that all twelve collected pairs are also *traded*, adding an instrument means adding it to both lists — and the disk cost is what bounds how many | [M3_PLAN.md](./M3_PLAN.md) §2 M3-4 |

---

## 🟢 Closed — tombstones, so they are not re-opened by accident

| question | verdict | where |
|---|---|---|
| **The 12-pair traded universe (8-vs-12)** | **Closed as UNRESOLVABLE on this evaluation period** — not "12 is worse". The effect is within a couple of bps of zero in every fair framing and the data resolves ±37 bps at 80% power. More seeds cannot help; only a longer evaluation period can, and that is calendar, not compute. ⚠️ **This tombstone said "served universe stays 8" until 2026-08-29 and was being read as a decision against twelve. It is not one.** Eight was the default while the four extras had no measured crossing cost; they have one now, and **the served universe is twelve** — see "The twelve-pair widening" in Active. What stays closed is the *question*: this data cannot rank the two universes, and re-opening it offline is what is forbidden, not trading twelve | [T6_RESULTS.md](./T6_RESULTS.md), [M3_PLAN.md](./M3_PLAN.md) §0.6 |
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
