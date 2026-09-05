# Backlog — every piece of planned work, and what would revive it

**This is the entry point.** One place that enumerates *all* open work, so a fresh session can
see what exists without reading five plan documents and inferring what is still alive. Requested
2026-08-28: *"document everything clearly and carefully, so we don't lose any of planned stuff and
return back when it's needed."*

**It is an index, not a plan.** Every row points at the document that owns the detail. It carries
no narrative and no numbers — those go stale here. What it does carry, for each item, is the
thing that is easiest to lose: **why it is not being worked on right now, and what would change
that.** 🔴 A parked item without a revival trigger is how a plan quietly becomes a graveyard.

| state | meaning | treatment |
|---|---|---|
| 🔵 **active** | being worked on now | full detail in the owning plan's status block |
| 🟡 **parked** | planned, not done, still worth doing | **stays here with a revival trigger** — never archived |
| 🟢 **closed** | answered, *including* "answered as unresolvable" | one-line tombstone + link, so it is not re-opened by accident |
| ⚫ **superseded** | a later result invalidated it | moved to [archive/TRAINING_HISTORY.md](./archive/TRAINING_HISTORY.md), not listed here |

*Restructured 2026-09-04 (RULES_REVIEW §6.3): the deploy-day, twelve-pair-widening, M3-0b,
candle-defect, freshness and arrival-rate narratives moved to the documents that own them. This
file is tables.*

---

## 🔴 Right now — what 2026-09-04 left open

The rules review answered three questions — are the rules too tight, what can be cleaned up, and
why not re-assess M3 (rule *and* RL) on corrected validation — and all eight decisions it raised
were taken and carried out the same day. Record: [RULES_REVIEW.md](./RULES_REVIEW.md).
**Three things remain, in this order:**

| # | item | owner | state |
|---|---|---|---|
| 1 | **Deploy the re-derived rule and the checkpoint guard to `fluxtrader-1`** | [RULES_REVIEW.md](./RULES_REVIEW.md) §6.1 | 🔵 both `ml_inference` and `app`, no truncate (the ledger persists across swaps), verify `checkpoint_bound: true` |
| 2 | **The walk-forward fold queue** — 12 serial runs, F2 first | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) §5 | 🔵 harness built and committed; **0 of 12 banked**, five runs void so far (§6.1). The 2026-09-04 attempt inherited the M2-era defaults (8 pairs, 1m, seq 128) from the gitignored `scripts/gcp_env`; §5 now carries the full recipe and `gcp_train.sh` refuses a fold that does not match the incumbent. The four 2026-09-05 runs (F2 s1–s3, F3 s1) trained correctly but were **scored on the wrong window** — `eval_m2.py` always took the newest `VAL_FRACTION` of history, so every fold was measured on F0's rows; fixed 2026-09-05 (`split_from_meta` reads the window off the checkpoint meta) and §5.1 gained a sixth check that compares the eval window to the training `Split` line. **Restart the queue at F2 s1** |
| 3 | **The document restructuring** | [RULES_REVIEW.md](./RULES_REVIEW.md) §6.3 | 🔵 in progress 2026-09-04 |

**What the review established, in one line each:** the bars are right and the friction is four
structural gaps around them, all four fixed by [M3_PROTOCOL.md](./M3_PROTOCOL.md) §9
(Amendment 2); **the incumbent still passes Tier 1 on repaired data** — worst window −4.61 bps
against a −5 floor, pooled +13.82 net at taker — while **0 of 8 learned runs pass**
([M3_2_RESULTS_REPAIRED.md](./M3_2_RESULTS_REPAIRED.md),
[M3_3_RESULTS_REPAIRED.md](./M3_3_RESULTS_REPAIRED.md)); and RL is not forbidden but unfundable
on ~220 independent days, which is what the folds exist to change.

---

## 🔵 Active

| item | owner doc | state |
|---|---|---|
| **The forward paper test** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | 🔵 **running; the clock restarts at the §6.1 deploy**, because every row from there carries its checkpoint tag and the A/B is read on tagged rows. It needs no work, only calendar time — it is the only mechanism that manufactures new independent trading days. Check with `curl -s localhost:4000/api/health \| jq '{policy, regime}'` **on the VM** (port 4000 there; 4001 is the local-compose mapping). Long silences are the strategy working |
| **The walk-forward folds** | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) | 🔵 **pre-registered 2026-09-04, before any fold was trained.** 4 folds × 3 seeds, F2 first, ~4h each, strictly serial. The scoring harness is committed (`ml/train/m3/walkforward.py`, `M3_ERA=walkforward`); C3's third acceptance test must pass before any fold number is read |
| **Deploy M3-5 to `fluxtrader-1`** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | ✅ **DONE 2026-08-28.** Deploy day found three defects invisible on the local stack — recorded in that document's §8 |
| **The M3 dashboard panel** | [archive/M3_UI_PLAN.md](./archive/M3_UI_PLAN.md) | ✅ **BUILT 2026-08-29, live 2026-08-31.** It earned its keep immediately: the panel is what made the served-vs-scored threshold gap visible ([M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md)). Its empty-state doctrine now lives in [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) §2 |
| **Widen the served universe to 12** | [M3_PLAN.md](./M3_PLAN.md) §8 | ✅ **DONE 2026-08-29.** Every served pair now carries its own measured crossing cost |
| **M3-0b** — price/funding side-table | [M3_0B_RESULTS.md](./M3_0B_RESULTS.md) | ✅ **DONE 2026-08-29 — the last M3 build item.** Acceptance passes on all four dumps. Its stop/target finding is a real-money row below |
| **M3-4** — execution costs | [M3_4_RESULTS.md](./M3_4_RESULTS.md) | ✅ **DONE 2026-08-28.** Crossing costs 9.84 bps round trip, not 14; the maker arm is not worth building. Risk #2 closed |
| **The candle repair** | [CANDLE_POLL_DEFECT.md](./CANDLE_POLL_DEFECT.md) | ✅ **DONE 2026-09-04**, verified 36/36, and the three checkpoints re-scored on it. The integrity guard that would have caught it is in [CANDLE_GUARD.md](./CANDLE_GUARD.md) |
| **The freshness question** | [RETRAIN_PLAN.md](./RETRAIN_PLAN.md) | 🟢 **not decidable on one split, and Phase 3 as written could not decide it either** (§9). Superseded by the folds, which is the design that can. The 65-day staleness trigger from it is in force (M3_PROTOCOL §9, Q3 (b)) |

---
## 🟢/🔴 The forward test's own blockers

*Different from the real-money blockers below: these do not block real money, they block the
paper test from meaning anything. Owner: [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md).*

| item | state | source |
|---|---|---|
| **Which coverage cut is the policy** | ✅ **CLOSED 2026-08-31, re-derived on repaired data 2026-09-04.** Frozen to the constants `backtest.py` derives over **the served checkpoint's own split** — cut `0.6296127438545227`, ladder p80 `0.025596268475055695`. ⚠️ A cut belongs to a **checkpoint** first and a universe second; a first attempt used O8's 12-pair cut and realized 4.01% coverage instead of 2% | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §6 |
| **The A/B had no B** | ✅ **CLOSED 2026-08-31.** The `signal_only` control could not fire, so it was re-registered as **`flat_size`** — the same bars at size 1.0, which measures the regime ladder. 🔴 Compare the arms on net bps per unit of **notional**, not per trade | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) §4 |
| **The daily loss limit biases the forward estimate** | 🟡 **OPEN.** `RiskManager`'s −50/day limit suppresses entries after a bad day, truncating the sample's left tail, so the forward mean is biased **upward**. Accept and document, or log suppressed entries as counterfactual bars so the bias can be removed | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §4.2 |

---
## 🔴 Open — blockers on trading anything but paper

🔵 **These three rows now have an owning document with an ordered, executable checklist:
[REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) (new 2026-09-01).** It is the recommended next
session's work, because it is the only open work whose progress does not depend on the market
producing a signal — see the arrival-rate finding below. ⚠️ Finishing it does **not** authorise
trading real money and the document says so in §4: it clears the *mechanical* blockers, while
the *evidence* blocker (zero forward trades) is untouched. Three decisions are stated there as
explicit questions (Q1 the API key, Q2 the stop/target, Q3 whether to build signing now).

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
| ~~**B1**~~ | ✅ **DONE 2026-08-31** — `./scripts/m3.sh -m m3 bookaudit` | — | **`NOT EVALUABLE`, which is NOT `FAIL`.** §4.1 needs n ≥ 2,000 in a top-5% slice = ≥ 40,000 held-out rows; the era supplies 39,740, short by ~1%. Best sign-agreeing slice `trade_vol` @ 60m: **+12.47 bps excess of drift, day-clustered CI [−6.06, +30.99]** on 12 clusters — indistinguishable from zero, though the naive SEM said six sigma. At 5m nothing clears even the 5 bps maker line. Delivered the real per-horizon sd (grows *slower* than √t) and confirmed `spread_bps`/`trade_count`/`trade_vol`/`funding_rate` as **VOL-PROXY**, per §0.4 |
| ~~**B2**~~ | ✅ **DONE 2026-08-31** — `./scripts/m3.sh -m m3 bookregime` | — | **`NOT YET DECIDABLE`**, exactly as §4.2 pre-registered. 🟢 The internal control settles the reading: the **incumbent** `btc_absret_1d` — Q1's 4× effect — scores +25.16 on **n=33** with its three seeds **split in sign**. The observable we know works fails its own gate on this window, so the *window* is what cannot resolve it. Cells are 19–78 trades. Texture only: the **conditional** column (book gate inside calm-BTC bars) is positive for `trade_count`/`trade_vol`/composite — the orthogonality hypothesis, to re-test at ≥90 days |
| **B3** | One book-era GBT, pre-registered | **B1 passing §4.1 — which it has NOT** | 🔴 **BLOCKED, not refused.** B1 returned `NOT EVALUABLE`, so §4.1 has neither authorised nor forbidden B3. Un-blocked by calendar (≈2026-10-15, when the window clears the n floor) **or** by a fresh pre-registration of the floor written *before* the numbers are re-read. ⚠️ Do NOT reach n by widening the coverage to 10% — §4.1 names top-5%, and changing it after seeing results is what M3_PROTOCOL §0 forbids. Recorded in [NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) §2 as the only training run any plan still calls for |

### 🟡 New 2026-09-01, PARKED — the tradeable horizon has never been tested with book features

**The whole B-wave is aimed at horizons that cannot clear costs, and the horizon that can is used
only as a control.** This is an open question, not a defect, and it needs a pre-registration before
any number is looked at.

**What is true today:**

* §1.2's own fee-wall table says **240m is the only horizon that clears both cost lines** at the
  current skill level (~22 bps captured against a 14 bps taker round trip). 1m/5m/60m do not. That
  is why the served policy holds for four hours.
* B1's gate (§4.1) is capped at horizons **≤ 60m**, and 240m is scored **only as a negative
  control** — the pre-registered expectation being that an apparent 240m book signal is
  confounding. **The control fired:** every feature showed large positive raw bps (up to +99),
  which the harness correctly attributed to the period's own **+62 bps drift**.
* B3 as specified is `GBT_HORIZONS=5,15,60 GBT_PRIMARY=5` — so the wave's **only** training run
  would not test 240m either.
* ⚠️ **B1 is a univariate screen, not a model.** It ranks bars by *one* feature at a time. §4.1's
  wording — "if the best out-of-sample slice is under +5bps, no architecture recovers it" — is
  **stronger than what a univariate rank test can support**; a feature interaction invisible to a
  single-feature sort is ordinary. What B1 legitimately establishes is the weaker and still-useful
  claim: *no individual book feature is strong enough on its own to justify the training run.*

**The counter-argument, which is not weak and must be answered rather than ignored:** book
microstructure is theorised to decay in minutes, so a book feature that appears to predict a 4h move
is more likely a volatility proxy riding drift than an edge. B1 measured exactly that —
`spread_bps`, `trade_count`, `trade_vol` and `funding_rate` all came back **VOL-PROXY**, with
directional correlation an order of magnitude below their magnitude correlation.

🟢 **And that is a lead, not a dead end.** A feature that predicts *size but not direction* is the
definition of a **regime / sizing observable**, which is where M3's largest measured effect already
lives (the regime size ladder, worth +8.6 bps on the worst window). That is B2's question, not B3's,
and it needs no new model at all.

**Gated on:** a fresh pre-registration, written **before** any 240m number is re-read. 🔴 Adding a
240m arm to B1's existing gate is **not** available — B1's results are already known, and changing a
pre-registered criterion after seeing its output is precisely what M3_PROTOCOL §0 forbids.

**Revival trigger:** whoever is prepared to write that pre-registration first. ⚠️ Note before
anyone does: B3's gate is stated in **net bps at maker**, and the executor has **no limit-order path
at all** (M3-5 §3.1) — so a maker-side pass is not executable today without building resting orders.
Prefer framing a new registration on the **taker** line, or scope the maker work explicitly.

---

### 🔴 New 2026-09-01 — B1's blocker may already be gone, and the export is the reason

**The "≈2026-10-15" revival trigger on B1/B3 is probably too pessimistic, and it is worth one cheap
check before anyone plans around it.** That date comes from §4.4's *exit condition* (≥90 days of
book history), **not** from B1's actual n floor, and the two are different criteria.

What the numbers say, measured 2026-09-01:

* §4.1 needs **≥ 40,000 usable half-2 rows**; B1 reported **39,740** — short by ~1%, i.e. by
  *hours* of collection, not weeks.
* **The export B1 ran on is stale and narrower than the data we already hold.**
  `ml/train/output/m3_4/book_era_5m.parquet` covers **2026-08-05 → 2026-08-27 (23 days)**.
* On the VM right now, `orderbook_snapshots` holds book history from **2026-07-17** (BTC/ETH/SOL),
  **07-21** (DOGE/HYPE/WLD), **07-25** (ZEC), **07-27** (1000PEPE) through **2026-09-01** — so the
  **8 main pairs**, which are the pairs §4.1 and B3 actually name, have **~36 days complete**
  against the 23 in the export. The four added pairs only start **2026-08-14**.

**So re-exporting over the 8 main pairs' true span is a ~56% increase in rows with zero waiting.**

⚠️ **This is a hypothesis about reachability, not a result, and it must not be run as one.** The
n floor is a *power* criterion; clearing it changes only whether §4.1 **can** be evaluated, never
what the verdict is. 🔴 **Do not widen coverage past the pre-registered top-5% to reach n**, and do
not re-read the numbers first and then decide the window — fix the window, then run it.

**To check it:** re-run the export over the 8 main pairs' span, then `./scripts/m3.sh -m m3 bookera`
and `./scripts/m3.sh -m m3 bookaudit`. If B1 becomes evaluable it either authorises or refuses B3 on
evidence — which is the outcome the wave has been waiting on. Owner:
[BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) §4.1.

---

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
