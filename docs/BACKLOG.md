Executed as written in §7.6. Verified after deploy and after the reboot: `checkpoint_bound: true`, `served_closed_bars_only: true`, bars recording for 12 pairs, `bar_already_recorded` counting. **Acceptance still open, ~2026-09-12:** live `policy_bars` rows must equal the offline scorer bar for bar (§7.6) |⚠️ **Both trades are void as policy evidence (row 8): they were scored on the forming candle, the first on a re-score the ledger never held. The clock restarts at row 8's deploy; record the new start time here.** 🔴 Do not change anything on the VM while it accumulates — the row-8 deploy is the one sanctioned exception |# Backlog — every piece of planned work, and what would revive it

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

## 🔴 Right now — where 2026-09-10 ended, and where to continue

**Three things happened on 2026-09-10, in this order.** (1) The forward paper test was
restarted on the right bar size at **04:50 UTC** — `ml_inference` had been feeding the 5m
checkpoint 1-minute candles since 08-24 ([M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md)
§7.5); the pre-deploy `policy_bars` were deleted, `paper_trades` is empty, the clock starts
there. (2) The fee tier was read off the account for the first time: **taker 5.0 bps/side, not
4.0**; every measured cost now carries +2.0 bps per round trip, and M3_4_RESULTS §7 was re-run
at the true fee ([REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) §5). (3) The real-money track's
three steps were **all finished**: the order path is signed, reconciled, braked through the
Algo Order API, watched by the user-data stream, and **demonstrated on the Binance demo
exchange end to end** (§6.1, §6.2 there). Nothing is authorised to trade real money — the
evidence blocker is untouched — but the mechanics no longer are one.

**The mode is: build, with the forward clock running in the background.** The one question
only calendar answers is whether the policy earns money forward. What the wait forbids is
changing the model or the rule *because* the test is silent. **By the end of 2026-09-10 every
build item that needed no market was done** (rows 2, 5 and 6 below closed that day — the
learned challenger was funded, explored and closed the same afternoon); what is left is the
forward clock (row 1), the parked retrain-trigger restatement (row 4), and later the go-live
decision (row 3). The one offline lever still open anywhere is the **book-era wave**
([BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md)), which §9.5's closure now points at as the only route
to a learned policy: new observations, not more days. **2026-09-10: its measurement half was
re-run on the full era with repaired candles; both gates passed by the letter, neither result
is distinguishable from zero. 2026-09-11: B3 finished on both arms and the wave is CLOSED on
its verdict — 5m fails decisively; 15m fails as written (+0.29 net at maker vs +5) but inside
the window's ±8.4-bps resolution, so it is parked for an identical re-run on 2026-11-02, not
re-tuned; O5 says the model leans on a candle feature, not the book. Rows in the B-wave section.** **Also 2026-09-11: the forward test produced its first two trades on day one (row 1, ZEC, +112 net bps on the first), and reading the first one exposed a fidelity defect on the served path — the engine re-scored each bar ~8 times on the forming candle and acted on any draw (row 8). Vadim chose to fix now: **fixed, tested and deployed the same day (M3_FIDELITY_RESULTS §7.6); the forward clock restarted at 2026-09-11 04:17 UTC and the day-one trades are void. The VM was also rebooted for a kernel update at 04:20 UTC, and `app`/`postgres` now carry a restart policy — before that only `ml_inference` would have come back.**


| # | item | owner | state / what to do |
|---|---|---|---|
| 1 | **The forward paper test** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | 🔵 **RUNNING since 2026-09-10 04:50 UTC, mode `simulation`, corrected fee.** Check on the VM: `curl -s localhost:4000/api/health \| jq '{policy, ab, exec_cost}'` — expect `checkpoint_bound: true`, both candle-interval fields `5m`, `fee_tier_verified: true`, `executor.auto_refused: null`. **First trades landed on day one (read 2026-09-11):** ZECUSDT long, entered 2026-09-10 16:35 UTC at 1113.70, conf 0.6366 vs cut 0.6296, regime 0.0246 (below the frozen p80 0.0256 → calm bucket, policy size 1.33), closed by timer 20:35 at 1127.46: **gross +123.6, net +112.1 bps** on the flat arm, +164.7 / +149.5 on the sized policy arm (cost 11.448 bps measured). A second ZEC long opened the same minute (20:30 bar, conf 0.6656, regime 0.0126, size 1.0), exit due 2026-09-11 00:30. One trade is one trade — the split by frozen p80 (row 7) starts when there are tens. 🔴 Do not change anything on the VM while it accumulates — **except that row 8 records a fidelity defect on the served path that Vadim must rule on first** |

| 2 | **§4.3's confirmations on the folds** | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) §9 | ✅ **ALL FOUR DONE 2026-09-10.** ✅ §9.1 coverage at twelve: closed 2026-09-10 at the explore gate (−7.34 [−21.85, +7.17] on F0+F1; the eight-derived cut is merely tighter, not a lever). ✅ §9.2 hour-of-day: **NOT CONFIRMED** 2026-09-10 — set chosen on F0+F1 (+14.29 in-sample) came out +3.84 [−9.50, +17.19] on F2+F3, MDE 13.3 bps; not detectable at this power, F2/F3 now read for this question. ✅ §9.3 market-neutral: **closed 2026-09-10 at the explore gate** (`m3 marketneutral`) — a netted dollar hedge in BTC came out −19.77 [−42.22, +2.67] bps per unit of notional on F0+F1, because two-fifths of the incumbent's gross is the BTC move its sides agree with and the hedge costs almost a full second trade; F2/F3 not read. ✅ §9.4 learned/RL: **gate run 2026-09-10 — FUNDABLE under the registered bar** (`m3 rlgate`, MDE 17.7 bps/trade against the incumbent's +29.5 on four folds; nothing fitted). Read the plain reading in §9.4 before acting on it: a challenger the size of the regime ladder (+13) would still be invisible, so it funds a search for a *large* improvement only. **All four of §4.3 are now done.** What it licenses is *writing* a fitting registration, filed below as 🟡 parked — a spend decision for Vadim, not a next step |
| 3 | **Going live, when the evidence exists** | [REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) §4, §6 | 🟢 **MECHANICALLY READY, NOT AUTHORISED.** What it would take, and nothing here is to be done now: a production key **with** futures-trading rights (the one in `.env` is read-only), `TRADING_MODE=auto` on the VM, `BINANCE_TESTNET` unset, and an explicit decision recorded here with the forward evidence it rests on. 🔴 Switching the VM to `auto` puts exchange-filled rows into the same ledger the A/B is registered on paper; that is a new registration, not a config change |
| 4 | **Restate the retrain trigger's N** | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) §8.5 | 🟡 N = 65 stands; needs a fresh pre-registration choosing a tail statistic |
| 5 | **The `flux.fee_tier` ETHUSDT control** | [REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) §5 | ✅ **DONE 2026-09-10 — MATCH** (run by Vadim on the VM). The 5.0/2.0 tier is confirmed account-level; nothing changes |
| 6 | **A learned challenger on the folds** | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) §9.5 | 🟢 **CLOSED 2026-09-10 at the exploration gate** (`m3 learnfolds --stage explore`). Registered, fitted out-of-fold and out-of-checkpoint on F0+F1: all 8 of M3-3's configurations lose to the rule by 28–34 bps/trade; on F0 every upper bound is under +4.6, so a ladder-sized improvement is excluded there. F2/F3 not read. Third independent negative for the linear class on this observation vector. **Revival trigger: new observations (side-table or book features over the fold era), not more days.** ⚠️ 2026-09-10: the B-wave's B2 now supplies exactly one candidate — `spread_bps_mkt_lo`, a hypothesis at ±69 bps — and one warning about the observation vector already in use, next row. ⚠️ 2026-09-11: B3's O5 importances weaken the "book features" half of this trigger — a tree model given all eleven book scalars over the whole era puts only 15–22% of its gain on them and leans on a candle feature (`xs_disp_1h`); B2's one regime hypothesis is the book item still standing (BOOK_ERA_PLAN §R.3) |
| 7 | **The regime observable is inverted on the book era** | [BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) §R.1 | 🟡 **OBSERVATION, 2026-09-10, for the forward test to check — not a finding.** On the repaired dumps over 2026-07-17..09-03 (8 pairs), the incumbent `btc_absret_1d` top-quintile gate scores **−20.23 gross (n=162) at cov 2% and −38.85 (n=330, seeds agreeing) at cov 5%**, against no-gate −7.85 / −17.61, while the calm-BTC subset earns +21.71 / +10.74. Q1's 4× effect points the other way on this era. The live size ladder is keyed on this observable. CIs are ±67–115 bps on 54 days, so **change nothing**; but when the forward ledger has trades, split them by the frozen p80 first |
| 8 | **The served path scored each bar ~8 times on the forming candle and acted on any draw** | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §7.6 | ✅ **FIXED AND DEPLOYED 2026-09-11 04:17 UTC (app rebuilt on `a9eadee`, inference reloaded, day-one ledger voided with CSV backups); the forward clock restarted there.** Found on the first trade: the 16:35 ZEC bar is in `policy_bars` at 0.6270, not gated, price 1123.18, while the trade opened on a re-score of the same bar at 0.6366 / 1113.70; `serve.py` scored the still-forming candle and the engine re-decided every bar on each 30 s tick (~8 draws per bar, health's own skip counts). Fix: `load_candles_tail` takes closed candles only and `serve.py` reports `closed_bars_only`; the engine decides each `(pair, bar_ts)` once, on the tick that recorded it (`bar_already_recorded` skip); the binding guard requires `closed_bars_only: true` (`forming_bar_unverified` skip). Tests: 126 + 7, 0 failures. **Runbook, in order, in §7.6** — recreate `ml_inference`, stop `app`, back up and void `paper_trades` + `policy_bars`, rebuild `app`, verify health. Acceptance a day later: live rows equal the offline scorer bar for bar |


**Operational rules learned today, so nobody re-learns them:** after a `git pull`, run
`docker compose exec app mix compile` **before** any `mix <task>` (a task that compiles on the
way in still runs the old beam); `docker compose exec` needs `-e` for every env var; the demo
exchange's fee is 4.0 bps and its book is thin, so nothing measured there is a production number.
Also (2026-09-10): the collector VM's `/tmp` is a **980 MB tmpfs**, and a stale 821 MB
`/tmp/app.log` from 09-05 is sitting in it — it broke the book-era export (now staged under
`~/m3_export` instead) and it is RAM on a 2 GB box; delete it when convenient. **2026-09-11:** the reboot (kernel 7.0.0-1011, `libc6`) was done at 04:20 UTC and cleared that tmpfs; it also showed that `app` and `postgres` had **no Docker restart policy** (only `ml_inference` did), so a reboot would have silently stopped the paper test — both are now `restart: unless-stopped` in `docker-compose.yml` (`3dcdfa4`). After any future reboot, still check `docker compose ps` shows all three up.

**Closed on 2026-09-09, with links to the record:**

| item | record |
|---|---|
| ✅ Deploy the re-derived rule and the checkpoint guard | [archive/RULES_REVIEW.md](./archive/RULES_REVIEW.md) §6.1 — verified live; all six checks pass |
| ✅ The walk-forward fold queue, 12 runs | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) §7 — **verdict CONFIRMED**, W1 = +33.23 net bps, CI [+9.28, +57.17] |
| ✅ The document restructuring | [archive/RULES_REVIEW.md](./archive/RULES_REVIEW.md) §6.3 — finished by archiving that file |
| ✅ The retrain trigger could never fire | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §7.3 — two independent defects, fixed and deployed with regression tests |

🔴 **Before quoting any fold number, read [WALKFORWARD_PROTOCOL §7.2](./WALKFORWARD_PROTOCOL.md).**
The F0 control lands at −0.66 net bps against the incumbent's +13.82 on the same era, so the
fixed-width train window costs ~14 bps. That makes W1 *conservative*, but it confounds boundary
age with training size — **§4.1's freshness reading may not be taken off this table.**

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
| **The forward paper test** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | 🔵 **RUNNING ON THE RIGHT BAR SIZE SINCE 2026-09-10 04:50 UTC** ([M3_FIDELITY_RESULTS §7.5](./M3_FIDELITY_RESULTS.md)); the clock starts there and `policy_bars` holds nothing older. Expect the first trade in **days, not weeks** if the market stays as it was in late August: on repaired 5m bars the offline scorer cleared the frozen cut on **11 of the 15 days 08-20 → 09-03** and on 34 of the 120 days before 09-04 — but a calm day (BTC 1-day \|return\| under ~1%, as on 09-10) fires nothing, and the longest dry spell ever measured is 21.5 days. Previously: **the clock restarts at the §6.1 deploy**, because every row from there carries its checkpoint tag and the A/B is read on tagged rows. It needs no work, only calendar time — it is the only mechanism that manufactures new independent trading days. Check with `curl -s localhost:4000/api/health \| jq '{policy, regime}'` **on the VM** (port 4000 there; 4001 is the local-compose mapping). Long silences are the strategy working |
| **The walk-forward folds** | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) §7 | ✅ **DONE 2026-09-09 — verdict CONFIRMED.** Pre-registered 2026-09-04 before any fold was trained; 12 runs, all six §5.1 checks and C3 pass. W1 lower bound +9.28 bps. §7.3 records the one harness amendment (a `win`-column double-rounding in C3's comparison, fixed like-for-like, ratified before any fold number was read) |
| **Deploy M3-5 to `fluxtrader-1`** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | ✅ **DONE 2026-08-28.** Deploy day found three defects invisible on the local stack — recorded in that document's §8 |
| **The M3 dashboard panel** | [archive/M3_UI_PLAN.md](./archive/M3_UI_PLAN.md) | ✅ **BUILT 2026-08-29, live 2026-08-31.** It earned its keep immediately: the panel is what made the served-vs-scored threshold gap visible ([M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md)). Its empty-state doctrine now lives in [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) §2 |
| **Widen the served universe to 12** | [M3_PLAN.md](./M3_PLAN.md) §8 | ✅ **DONE 2026-08-29.** Every served pair now carries its own measured crossing cost |
| **M3-0b** — price/funding side-table | [M3_0B_RESULTS.md](./M3_0B_RESULTS.md) | ✅ **DONE 2026-08-29 — the last M3 build item.** Acceptance passes on all four dumps. Its stop/target finding is a real-money row below |
| **M3-4** — execution costs | [M3_4_RESULTS.md](./M3_4_RESULTS.md) | ✅ **DONE 2026-08-28.** Crossing costs 9.84 bps round trip, not 14; the maker arm is not worth building. Risk #2 closed |
| **The candle repair** | [CANDLE_POLL_DEFECT.md](./CANDLE_POLL_DEFECT.md) | ✅ **DONE 2026-09-04**, verified 36/36, and the three checkpoints re-scored on it. The integrity guard that would have caught it is in [CANDLE_GUARD.md](./CANDLE_GUARD.md) |
| **The freshness question** | [RETRAIN_PLAN.md](./RETRAIN_PLAN.md) | 🟡 **PARKED, and no longer un-blocked by the folds alone.** Not decidable on one split (§9); the folds were the design that could decide it, but [WALKFORWARD_PROTOCOL §7.2](./WALKFORWARD_PROTOCOL.md) shows the fixed-width train window costs ~14 bps, which is confounded with boundary age in every fold-to-fold difference. **Revival trigger:** register §4.1 with the training-size penalty as an explicit term, or re-run the freshness arm at matched training size. The 65-day staleness trigger stays in force (M3_PROTOCOL §9, Q3 (b)) |

### 🟡 Parked, opened 2026-09-09

| item | owner doc | state |
|---|---|---|
| ~~**Root-cause the live-vs-offline confidence tail gap**~~ | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §7.5 | ✅ **CLOSED 2026-09-10.** `ml_inference` was serving the 5m checkpoint from 1m candles. Warmup, normalization and staleness were all tested and contributed nothing. Fix built; deploy is row 1 of "Right now" |
| **Restate the retrain trigger's N** | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) §8.5 | 🟡 **§8's registered statistic was the wrong one** — p95 of inter-bar gaps measures signal density, not silence, and came out at 0.01 days. N = 65 stands, as §8.3 pre-committed. What the run *did* establish: the longest dry spell across all twelve runs and ~2 years is **21.49 days**, so 65 is ~3x the worst ever seen and is a very insensitive alarm. **Revival trigger:** a fresh pre-registration choosing a tail statistic, written by someone who has not just read §8.5's table |
| **§4.3 — confirm the parked findings on the folds** | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) §9 | ✅ **four of four done 2026-09-10.** ✅ §9.1 served coverage at 12 — closed 2026-09-10 at the explore gate (`m3 coverage12`). ✅ §9.2 hour-of-day — NOT CONFIRMED 2026-09-10 on F2+F3 (`m3 hourofday`), MDE 13.3 bps; revive only with a larger untouched sample against the same recorded set. ✅ §9.3 market-neutral — closed 2026-09-10 at the explore gate (`m3 marketneutral`): the edge on the folds is largely market-directional, so a dollar hedge removes edge and adds notional; revive only on a checkpoint whose residual after `side · r_BTC` carries the gross, or under a registered risk objective. ✅ §9.4 learned/RL — gate run 2026-09-10 (`m3 rlgate`): **FUNDABLE**, MDE 17.7 < E 29.5 on four folds, nothing fitted, F2/F3 entered no contrast. The fitting registration it licensed (§9.5) was explored and **closed at the gate** the same day — row 6 of "Right now". **§4.3 is complete** |

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

🔵 **Owner: [REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md).** On 2026-09-10 Vadim answered
its three questions (Q1 read-only key in the VM's `.env`; Q2 keep the brake; Q3 build it all
now), and the track moved from "three open rows" to "one thing left to run". ⚠️ Finishing it
does **not** authorise trading real money and the document says so in §4: it clears the
*mechanical* blockers, while the *evidence* blocker (zero forward trades) is untouched.

| item | state | source |
|---|---|---|
| ~~**Verify the Binance USDⓈ-M VIP fee tier**~~ | ✅ **DONE 2026-09-10 — MISMATCH: taker 5.0 bps/side, not 4.0.** +2.0 bps per round trip on every measured cost, charged by `ExecCost` from that day; the published net-at-14 numbers stay conservative (true line ≈ 11.84). `mix flux.fee_tier` is now a standing check against the verified constant | [REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) §5 |
| ~~**Decide the `auto` path's stop/target**~~ | ✅ **DECIDED 2026-09-10: keep (Q2 a).** And now actually placed on the exchange — `STOP_MARKET` + `TAKE_PROFIT_MARKET`, `closePosition`, mark-price trigger — with the fill booked as `exit_reason: stop / target` so the forward ledger can price the premium forward | [REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) §6, [M3_0B_RESULTS.md](./M3_0B_RESULTS.md) §4 |
| ~~**The `auto` order path**~~ | ✅ **BUILT AND DEMONSTRATED ON THE TESTNET 2026-09-10** — signed open, reconciled fill, both brakes as algo orders, reduce-only close, flat after (`TESTNET_OK`, REAL_MONEY_TRACK §6.1). 123/123 tests. **Left:** the user-data stream has not been exercised against a running `auto` executor — the runbook's local-stack step, never on the VM (it would put demo fills into the forward ledger). **Also found:** the VM's `TRADING_MODE` and credentials were never read (prod-only config under a dev container) — fixed | [REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) §6 |
| ~~**Re-run M3_4_RESULTS §7's re-score at the corrected fee**~~ | ✅ **DONE 2026-09-10, both eras.** Winner's worst window: pre-repair +2.43 → **+0.38** (still clears +0.25, by 0.13); repaired −2.38 → **−4.43** (still inside Tier 1's −5 floor, still short of +0.25). Nothing flips. Only the winner still clears on the published era; the two `rq0.8` configs that did at 4.0 no longer do | [REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) §5 |

---

## 🟡 Parked — M3

*M3-0b is done (see above). Its stop/target decision is filed with the real-money
blockers, not here, because it does not affect the running paper test.*

| item | what | gated on | revival trigger |
|---|---|---|---|
| ~~**Export `open_interest`**~~ | ✅ **DONE 2026-09-10** — `oi` slice added to `scripts/gcp_m3_export.sh`; B0 now builds all eleven scalars | — | — |
| **Re-pre-register the served coverage** | ⚠️ 2026-09-10, WALKFORWARD §9.1: re-deriving the cut over *twelve* is not the lever — on F0+F1 the eight-derived cut is only slightly tighter and the marginal trades earn nothing (−7.34 [−21.85, +7.17]). What stays parked here is the cut *level*. The universe went 8 → 12 on 2026-08-29 at an unchanged cov 0.02, which takes **more** trades (3.05/day vs 2.02), not better ones. T6's count-matched cut on twelve is **0.01288**, and on the 8-pair arm tightening the cut alone was worth **+12.72 bps** while widening the universe at a fixed cut was worth **−2.51**. So the cut, not the pairs, is where T6's signal lived | nothing technical | 🔴 **Blocked by protocol, not by work.** M3_PROTOCOL §0 forbids re-picking a searched dimension after seeing results; this needs a fresh pre-registration on the population it will be served from, written before anything is scored. Revive it when someone is prepared to write that document first — **not** by re-scoring the grid and picking the winner |

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
| ~~**B0**~~ | ✅ **RE-BUILT 2026-09-10** on the full era (2026-07-17..09-09, 54 days, repaired candles), all eleven scalars, own export dir `ml/train/output/book_era/`. Acceptance against the three repaired dumps: **111k/111k exact, each**. O8 (pre-repair) mismatches from 07-17 — the candle defect's signature, now labelled as such by the harness | — | The 2026-08-29 build (23 days, partial-bar candles) is superseded and archived |
| ~~**B1**~~ | ✅ **RE-RUN 2026-09-10 — §4.1 `PASS`** | — | `imbalance` @ 60m: **+10.37 bps raw** on n=3,158 (floor 2,000 cleared), sign agreeing. **+5.62 of it is drift; the excess +4.75 has a day-clustered CI of [−2.45, +11.94]** on 28 clusters. Rank ρ 0.005–0.015. Best of 30 cells. At **5m nothing clears the maker line** (best +3.43 raw). So: passes the rule as written, licenses B3, and is not an edge. VOL-PROXY confirmed on true candles: `spread_bps` −0.19, `trade_count` +0.29, `trade_vol` +0.26, `funding_rate` +0.20. Full reading BOOK_ERA_PLAN §R.1 |
| ~~**B2**~~ | ✅ **RE-RUN 2026-09-10 — §4.2 `PASS` on `spread_bps_mkt_lo`** (repaired dumps, 8 pairs, 07-17..09-09; `oi_chg` now among the candidates) | — | Narrow-spread (volatile) tail of the market-wide spread: **+35.43 gross on n=153** vs baseline **−7.85 (n=311)** at cov 2%, lift +43.29, conditional +27.89, seeds agree; consistent at cov 5% (lift +31.96). **The arm's own 95% half-width is ±68.8 bps**, the orientation was chosen from B1's sign (ten primary tests), so per §4.2 this is a **hypothesis to re-test**, never a policy term. All other candidates fail. 🔴 Side-finding filed under the live policy above: the incumbent `btc_absret_1d` gate is **negative** on this era |
| ~~**B3**~~ | ✅ **RAN 2026-09-10 — 5m arm `FAIL §4.3`** (`logs/b3_gbt_20260910.log`) | — | Val 08-30 → 09-10 (10.9 d). Cov 5%: dir_acc 0.576, LB 0.540, n_dir 750; **gross +2.39, net at maker −2.61, net at 14-bps taker −11.61 bps/trade** against a +5-at-maker gate — a clear miss on a ±2-bps band. Best cov 1%: +3.16 gross. Edge sits in the first 2.7-day fold only (LB 0.574 / 0.448 / 0.481 / 0.520); not drift (val mean +0.18 bps, P(up) 0.493). Third method to land at +2–3 bps at 5m after §1.2 and B1: signal-limited. ETHUSDT `spread_bps` BROKEN SCALE flag = one 8.2-bps bar on 09-01, traced, not a void. Reading BOOK_ERA_PLAN §R.2 |
| ~~**B3b**~~ | ✅ **DONE 2026-09-11 — both runs; the wave closes here** (`logs/b3b_gbt_5m_20260911.log`, `logs/b3b_gbt_15m_20260911.log`) | — | **15m arm at cov 5%: dir_acc 0.627 (LB 0.595), n_dir 911, gross +5.29, net at maker +0.29, net at taker −8.71 bps/trade; day-clustered band ±8.4 → FAIL §4.3 as written, gate inside the band.** 5m re-emit: not digit-identical (the dump refreshed, val window +21 bars) — net at maker −2.90 vs −2.61, verdict unchanged; 2.7-day fold LBs moved by up to 0.06 on that 0.4% data change, so fold-level "where the edge lives" readings are not structure. **O5:** `xs_disp_1h` 33–38% of gain; the 11 book scalars together 22% (5m) / 15% (15m) vs a 37% uniform share, none above 2.7%. Brier 0.251/0.253 — ranking has skill, probabilities do not. Reading BOOK_ERA_PLAN §R.3 |
| **B3c** | The identical 15m registration, re-run with a ~53-day val window | 🟡 **calendar: on or after 2026-11-02** | 🟡 **PARKED, per §B3's pre-registration ("near the gate → more calendar, not a third setting").** Train window held at the first ~54 days of the era, val = everything after (`--tail-days 108 GBT_VAL_FRACTION=0.5`, launcher passthrough added 2026-09-11); brings the band from ±8.4 to ≈±4 bps. Gate unchanged: +5 net at maker at cov ≤ 5%, n_dir ≥ 500. Expectation recorded: FAIL with the gate excluded. A pass promotes nothing and would only license a maker-path registration — which the executor lacks (M3-5 §3.1). Exact command: BOOK_ERA_PLAN §R.3 |


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

### ✅ Closed 2026-09-10 — the 2026-09-01 note that B1's blocker was the export, not the calendar

It was. Re-exporting from 2026-07-17 (the scalars' first day; the 08-05 left edge was the
*ladder's*, which B0 does not read) gave 54 days and 3,158 rows at cov 5% against a floor of
2,000, and the export also picked up the September candle repair, which the 08-31 numbers
predate. The "≈2026-10-15" trigger is retired; what remains calendar-bound is B2's resolution
(±69 bps on the gated arm — roughly four times the days to reach ±30) and, since 2026-09-11, B3's
15m arm (B3c, ±8.4 → ≈±4 bps needs ~53 val days, reached 2026-11-02).

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

**The wave's exit condition (§4.4) did not fire** — both gates passed on 2026-09-10 — so the
wave ran B3 and **closed on its verdict on 2026-09-11**: 5m failed decisively, 15m failed as
written with the gate inside the window's resolution (BOOK_ERA_PLAN §R.3). **Do not open a
B5.** What stays live in the book question is exactly two calendar-gated re-tests: **B3c** (the
identical 15m registration on a ~53-day val window, on or after 2026-11-02 — row above) and the
re-test of B2's `spread_bps_mkt_lo` hypothesis when its window resolves ±30 bps.


⚠️ **A pass under a hard gate is not the same as the answer being yes.** Both passes sit inside
one day-clustered CI of zero; the plan pre-committed to treating a B2 pass as a hypothesis and
a B1 pass as a licence for one run. That is the [negative-results](./M3_PLAN.md) discipline
applied symmetrically.

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
| **Why the live confidence tail was truncated (2026-08-24 → 09-10)** | **Closed as a serving defect, not a regime fact and not a pipeline subtlety:** no `CANDLE_INTERVAL` on `ml_inference`, so a 5m checkpoint was fed 1m candles. The hash-only guard could not see it; the guard now binds the interval too. ⚠️ Every `policy_bars` row before the fix's deploy is a record of the wrong inputs | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §7.5 |
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
