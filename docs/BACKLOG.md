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

## 🔴 Right now — where 2026-09-15 ended, and where to continue

**Mode: build offline, with the forward clock running in the background.** The forward paper
test has run since **2026-09-11 06:07:51 UTC** (third start, accepted 09-12 on a 3,092/3,092
replay): seven signal bars on the first afternoon, nothing above the cut since 09-11 22:40 UTC,
health green. Silence is the rule working, not a fault. Nothing served has changed since.

**The experimental track, 2026-09-13 → 15 — five offline ideas, each registered before a
number was read, each closed under its own gate** (rows in "new experiment ideas" below):

- **X1** market-block features → **WORSE** (−0.021); the M2 feature route is closed in both
  directions and the freeze re-sealed. X0, its 3-seed control on the repaired snapshot, is banked.
- **X3** predicted-magnitude sizing → **gate not passed**; the paired design excludes a
  ladder-sized gain.
- **X4** signal-conditioned exits → flips never fire; holding past 4 h while the model still
  agrees is positive on every fold and seed but **NOT CONFIRMED** at the bar. Carried to the
  forward ledger as reading **R5** (M3_5 §4.3), free.
- **X2** volatility-normalised training labels → **registered and funded**; code built and
  checked; three serial GPU runs.
- **X5** split embargo → hygiene, parked.

**Needed from Vadim now: run X2's three GPU commands (NEXT_TRAINING_PLAN §2) after a `git
push`, and bring back `logs/X2_s1..3.log`. Nothing else.**

*Background, 2026-09-10 → 12, each in its owning document:* the forward clock restarted three
times — wrong bar size (M3_FIDELITY §7.5), forming-bar re-scores (row 8), settle lag (row 9);
the fee tier was read off the account (taker 5.0 bps, REAL_MONEY_TRACK §5); the real-money
path was demonstrated on the demo exchange and is **not** authorised (row 3); the book-era wave
closed on B3's verdict with B3c parked to 2026-11-02 (B-wave section).


| # | item | owner | state / what to do |
|---|---|---|---|
| 0 | **fluxtrader2 — parallel from-scratch project** | [../fluxtrader2/README.md](../fluxtrader2/README.md) | 🔵 **CREATED 2026-09-15.** A second system built in `fluxtrader2/` on the same collector data and *nothing else* (no model, code, protocol or conclusion from this project). Its own README/PLAN/DATA; it does not use this file. **Needed from Vadim: decide when to run its P0 (data export, ~30 min, read-only on the VM).** This row exists only so a fresh session knows the folder is live work |
| 1 | **The forward paper test** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | 🔵 **RUNNING since 2026-09-11 06:07:51 UTC — start ACCEPTED 2026-09-12 (3,092/3,092 rows exact, M3_FIDELITY_RESULTS §7.6).** **Needed from Vadim: nothing.** Do not touch the VM, do not change the model or the rule; just ask in a session and Claude does the checks below. **Ledger so far (re-read 09-14 19:28 UTC, unchanged since 09-12):** 7 signal bars, all on 09-11 between 15:25 and 22:15 UTC, each traded on both arms — 14 closed rows, all `timer` exits, none stopped. Two shorts into the afternoon drop (LINK, AVAX, sized 4/3) won big, five longs in the calm evening (HYPE, DOGE, ETH ×2, ADA, sized 1/3–1) roughly cancelled; the day is one market move, not seven observations. Every trade sits **below** the frozen regime p80 (0.0256), so row 7's split has no top-quintile bar yet. **Since then, nothing above the cut:** 09-12 / 13 / 14 peaked at 0.568 / 0.598 / 0.591 against 0.6296, BTC's 1-day \|return\| (2.5%) sits just under the 2.56% p80, health is all green (checkpoint bound, closed bars only, 5m, settle 120 s, `last_error: null`, all three containers up 3 days). Three quiet days against a 21.5-day record dry spell mean nothing. **What Claude does next:** (a) On request, read `/api/health` on the VM and confirm it still says: checkpoint bound, closed bars only, 5m candles, fee tier verified, candle settle 120 s, `last_error: null`. (b) Re-run `accept_76.py` only after a code change on the serve or engine path, or on any trade whose confidence does not equal its `policy_bars` row — not routinely; the probe now takes ~20 min per day of rows. (c) **The readings are pre-registered (2026-09-13, M3_5 §4.3):** run `./scripts/gcp_forward_ledger.sh` at every 50 closed policy trades; it prints the A/B, the cut level, the regime split (row 7), the hour set, the loss-limit counterfactual and (R5, 2026-09-15) the hold-extension counterfactual, all per unit of **notional**. Before 50 it prints TEXTURE and nothing may be quoted. *Background:* this is the third start. The 09-10 start fed the wrong bar size, the 04:17 start scored bars before the collector had finalised them; both ledgers are void and backed up on the VM (`~/*_formingbar_20260911.csv`, `~/*_settle_20260911.csv`). Mode `simulation`, corrected 5.0-bps fee, $500 per size unit. Silence is normal: the longest dry spell ever measured is 21.5 days |


| 2 | **§4.3's confirmations on the folds** | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) §9 | ✅ **ALL FOUR DONE 2026-09-10.** ✅ §9.1 coverage at twelve: closed 2026-09-10 at the explore gate (−7.34 [−21.85, +7.17] on F0+F1; the eight-derived cut is merely tighter, not a lever). ✅ §9.2 hour-of-day: **NOT CONFIRMED** 2026-09-10 — set chosen on F0+F1 (+14.29 in-sample) came out +3.84 [−9.50, +17.19] on F2+F3, MDE 13.3 bps; not detectable at this power, F2/F3 now read for this question. ✅ §9.3 market-neutral: **closed 2026-09-10 at the explore gate** (`m3 marketneutral`) — a netted dollar hedge in BTC came out −19.77 [−42.22, +2.67] bps per unit of notional on F0+F1, because two-fifths of the incumbent's gross is the BTC move its sides agree with and the hedge costs almost a full second trade; F2/F3 not read. ✅ §9.4 learned/RL: **gate run 2026-09-10 — FUNDABLE under the registered bar** (`m3 rlgate`, MDE 17.7 bps/trade against the incumbent's +29.5 on four folds; nothing fitted). Read the plain reading in §9.4 before acting on it: a challenger the size of the regime ladder (+13) would still be invisible, so it funds a search for a *large* improvement only. **All four of §4.3 are now done.** What it licenses is *writing* a fitting registration, filed below as 🟡 parked — a spend decision for Vadim, not a next step |
| 3 | **Going live, when the evidence exists** | [REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) §4, §6 | 🟢 **MECHANICALLY READY, NOT AUTHORISED.** What it would take, and nothing here is to be done now: a production key **with** futures-trading rights (the one in `.env` is read-only), `TRADING_MODE=auto` on the VM, `BINANCE_TESTNET` unset, and an explicit decision recorded here with the forward evidence it rests on. 🔴 Switching the VM to `auto` puts exchange-filled rows into the same ledger the A/B is registered on paper; that is a new registration, not a config change |
| 4 | **Restate the retrain trigger's N** | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) §8.5 | 🟡 N = 65 stands; needs a fresh pre-registration choosing a tail statistic |
| 5 | **The `flux.fee_tier` ETHUSDT control** | [REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) §5 | ✅ **DONE 2026-09-10 — MATCH** (run by Vadim on the VM). The 5.0/2.0 tier is confirmed account-level; nothing changes |
| 6 | **A learned challenger on the folds** | [WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) §9.5 | 🟢 **CLOSED 2026-09-10 at the exploration gate** (`m3 learnfolds --stage explore`). Registered, fitted out-of-fold and out-of-checkpoint on F0+F1: all 8 of M3-3's configurations lose to the rule by 28–34 bps/trade; on F0 every upper bound is under +4.6, so a ladder-sized improvement is excluded there. F2/F3 not read. Third independent negative for the linear class on this observation vector. **Revival trigger: new observations (side-table or book features over the fold era), not more days.** ⚠️ 2026-09-10: the B-wave's B2 now supplies exactly one candidate — `spread_bps_mkt_lo`, a hypothesis at ±69 bps — and one warning about the observation vector already in use, next row. ⚠️ 2026-09-11: B3's O5 importances weaken the "book features" half of this trigger — a tree model given all eleven book scalars over the whole era puts only 15–22% of its gain on them and leans on a candle feature (`xs_disp_1h`); B2's one regime hypothesis is the book item still standing (BOOK_ERA_PLAN §R.3) |
| 7 | **The regime observable is inverted on the book era** | [BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) §R.1 | 🟡 **OBSERVATION, 2026-09-10, for the forward test to check — not a finding.** On the repaired dumps over 2026-07-17..09-03 (8 pairs), the incumbent `btc_absret_1d` top-quintile gate scores **−20.23 gross (n=162) at cov 2% and −38.85 (n=330, seeds agreeing) at cov 5%**, against no-gate −7.85 / −17.61, while the calm-BTC subset earns +21.71 / +10.74. Q1's 4× effect points the other way on this era. The live size ladder is keyed on this observable. CIs are ±67–115 bps on 54 days, so **change nothing**; but when the forward ledger has trades, split them by the frozen p80 first — **pre-registered 2026-09-13 as R2 of M3_5 §4.3** |
| 8 | **The served path scored each bar ~8 times on the forming candle and acted on any draw** | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §7.6 | ✅ **FIXED AND DEPLOYED 2026-09-11 04:17 UTC (app rebuilt on `a9eadee`, inference reloaded, day-one ledger voided with CSV backups); the forward clock restarted there.** Found on the first trade: the 16:35 ZEC bar is in `policy_bars` at 0.6270, not gated, price 1123.18, while the trade opened on a re-score of the same bar at 0.6366 / 1113.70; `serve.py` scored the still-forming candle and the engine re-decided every bar on each 30 s tick (~8 draws per bar, health's own skip counts). Fix: `load_candles_tail` takes closed candles only and `serve.py` reports `closed_bars_only`; the engine decides each `(pair, bar_ts)` once, on the tick that recorded it (`bar_already_recorded` skip); the binding guard requires `closed_bars_only: true` (`forming_bar_unverified` skip). Tests: 126 + 7, 0 failures. **Runbook, in order, in §7.6** — recreate `ml_inference`, stop `app`, back up and void `paper_trades` + `policy_bars`, rebuild `app`, verify health. **Acceptance run 2026-09-11 04:30–05:00 UTC on the first 42 rows: 32/42 equal the offline scorer exactly (the ZEC trade's row among them); the 10 others were scored on a closed bar whose stored row the collector had not yet refreshed after the close — the residual is row 9.** |
| 9 | **A closed bar is admitted before its stored row is final (collector polls once a minute)** | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §7.6 "Acceptance" | ✅ **FIXED (option a) AND DEPLOYED 2026-09-11 06:06 UTC; the forward clock restarted at 06:07:51.** Measured at the 04:55 close: the 12 stored rows settle 7–93 s after `close_time`; serve's `close_time <= now` admitted the last in-bar poll of an already-closed bar, so ~1 live row in 4 (10 of the first 42) was scored on a bar missing its final seconds to a minute (|Δconf| 0.0002–0.003). Fix: `load_candles_tail`'s live default is `now − CANDLE_SETTLE_S` (120 s, env-overridable); an explicit `as_of` is unchanged; serve reports `candle_settle_s` on `/health` and every prediction (`05a0878`). Costs ≤ 2 min of signal age. Not taken: (b) the collector storing/marking only final bars — no lag but an app change and a migration; revisit if the 2-minute age ever matters. Acceptance: row 1's check, 42/42 |


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
| **The forward paper test** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | 🔵 **RUNNING since 2026-09-11 06:07:51 UTC (third start, accepted 09-12) — row 1 of "Right now" is the live status; this row is background.** First put on the right bar size 2026-09-10 04:50 UTC ([M3_FIDELITY_RESULTS §7.5](./M3_FIDELITY_RESULTS.md)); `policy_bars` holds nothing older than the current start. Expect the first trade in **days, not weeks** if the market stays as it was in late August: on repaired 5m bars the offline scorer cleared the frozen cut on **11 of the 15 days 08-20 → 09-03** and on 34 of the 120 days before 09-04 — but a calm day (BTC 1-day \|return\| under ~1%, as on 09-10) fires nothing, and the longest dry spell ever measured is 21.5 days. Previously: **the clock restarts at the §6.1 deploy**, because every row from there carries its checkpoint tag and the A/B is read on tagged rows. It needs no work, only calendar time — it is the only mechanism that manufactures new independent trading days. Check with `curl -s localhost:4000/api/health \| jq '{policy, regime}'` **on the VM** (port 4000 there; 4001 is the local-compose mapping). Long silences are the strategy working |
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
| ~~**The daily loss limit biases the forward estimate**~~ | ✅ **CLOSED 2026-09-13 — nothing to build.** The `flat_size` arm bypasses `RiskManager` and takes the same bars, so a refused policy entry is a flat-arm row with no policy twin; reconstructing it at ladder size gives the unbiased arm. Pre-registered as R4 of M3_5 §4.3 (`m3 forward`); the limit stays, the VM was not touched | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §4.2 |

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
| **Re-pre-register the served coverage** | ⚠️ 2026-09-10, WALKFORWARD §9.1: re-deriving the cut over *twelve* is not the lever — on F0+F1 the eight-derived cut is only slightly tighter and the marginal trades earn nothing (−7.34 [−21.85, +7.17]). What stays parked here is the cut *level*. The universe went 8 → 12 on 2026-08-29 at an unchanged cov 0.02, which takes **more** trades (3.05/day vs 2.02), not better ones. T6's count-matched cut on twelve is **0.01288**, and on the 8-pair arm tightening the cut alone was worth **+12.72 bps** while widening the universe at a fixed cut was worth **−2.51**. So the cut, not the pairs, is where T6's signal lived | nothing technical | 🔴 **Blocked by protocol, not by work.** M3_PROTOCOL §0 forbids re-picking a searched dimension after seeing results; this needs a fresh pre-registration on the population it will be served from, written before anything is scored. Revive it when someone is prepared to write that document first — **not** by re-scoring the grid and picking the winner. ⚠️ **2026-09-13: the forward *reading* of this question is now pre-registered** — R1 of M3_5 §4.3 splits the policy arm at the cuts for cov 0.015 / 0.01288 / 0.01 (derived over the served split before the ledger was read) and reports what the marginal trades earn. A reading that excludes zero is what licenses writing the served-change registration; it is not the registration |

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

## 🟡 Parked — new experiment ideas, 2026-09-13

*Asked for on 2026-09-13 while the forward test idles: "other models / flow / data mangling",
not process. Each row was checked against §5 of NEXT_TRAINING_PLAN and the tombstones below
before it was written, so none re-proposes a closed lever. Every one needs a pre-registration
written before a number is read; GPU runs are serial. The forward test is untouched by all of
them — they are offline.* **Both decided 2026-09-15: R5 is registered (X4's row) and X2 is funded and registered.
Needed from Vadim: run X2's three GPU commands (NEXT_TRAINING_PLAN §2) and bring back the
logs. X1 (WORSE), X3 (gate not passed) and X4 (not confirmed, sign consistent) are closed;
X5 is hygiene and stays parked.**

| # | idea | what would be new | cost | grounded in | state |
|---|---|---|---|---|---|
| **X1** | **The cross-sectional block, separated** | The served model reads own-pair candle columns only. The five market columns (`btc_rel_ret_1h`, `beta_btc_1d`, `xs_rank_1h`, `xs_disp_1h`, `has_market`) were only ever tested inside Q3's 30-column bundle, whose six own-pair multiscale channels R1 later showed were pure memorisation surface. They are *external* information — other pairs' returns — which is the one reopening condition §5's feature row names. | GPU, serial: a 3-seed control family on the current (repaired) snapshot, then the 3-seed arm — six runs. The control is reusable by X2. | B3's O5 importances: `xs_disp_1h` carries 33–38% of the GBT's gain, more than any other feature, at 5m and 15m (BOOK_ERA_PLAN §R.3) | 🟢 **CLOSED 2026-09-15 — WORSE** (NEXT_TRAINING_PLAN §2, result block). X1 − X0 = **−0.020** on the pre-registered read (the fallback fired: every X1 plateau under 15 epochs), ≈ 8σ, every X1 seed below the control; the 24-column runs leave the plateau at epoch 6–7 — Q3/R1's memorisation signature, now on *external* columns too. §5's feature row carries the second entry; the M2 freeze is re-sealed. X0 seed 3's first attempt ran at seq 128 and was void; **re-run 2026-09-15 on the same snapshot, valid** — X0 is banked with three seeds (0.5254) as X2's control. **Needed from Vadim: nothing** |
| **X2** | **Volatility-normalised labels** | The flat band is a fixed 0.6% at 4h in every regime (`FLAT_TH_4H`), so calm months are almost all "flat" and direction is learned mostly on volatile bars — which is why the served model is silent in a calm market. Label the sign of `fwd_ret / realised vol` with the band in vol units; the directional head then trains on calm bars too. Never tried (triple-barrier is the only vol-scaled label and it was voided, never redone). | GPU, 3 seeds, reusing X0's control | The regime finding: the edge lives in the top vol quintile (NEXT_TRAINING_PLAN §1.8); the served model emits nothing in calm (M3_5 §4.2) | 🔵 **REGISTERED 2026-09-15 — NEXT_TRAINING_PLAN §2 "X2"**, funded by Vadim. `LABEL_MODE=volnorm` built and synthetically checked; selection and eval stay on the fixed labels so the contrast is like-for-like; k is derived from the fixed label's flat share on X0's train window, not chosen. Control X0 banked (0.5254). Expectation recorded: FLAT. **Needed from Vadim: `git push`, then run the three serial GPU commands in §2 (~8 h, ≈ $4.5) on the untouched dump cache and bring back `logs/X2_s1..3.log`.** |
| **X3** | **Predicted-magnitude sizing** | The ladder — M3's largest measured effect, +8.6 bps on the worst window — keys on *backward-looking* BTC realised volatility. Fit a small tree model for the forward absolute 4h move on candle features over the full history and feed it as the harness's `size_col`; a paired comparison on the same entries against the realised-vol ladder. Never tried as a model. | CPU only, `ml_analysis` container; no M2 change | B1: book and candle features predict *magnitude*, not direction (VOL-PROXY, BOOK_ERA_PLAN §R.1); M3_PROTOCOL §5's bar that magnitude belongs in the policy, not the loss | 🟢 **CLOSED 2026-09-15 at the exploration gate — [WALKFORWARD_PROTOCOL §9.6](./WALKFORWARD_PROTOCOL.md)** (registered, built, run and read the same day). Same entries as the incumbent, same ⅓..5⁄3 ladder, only the key changed to an out-of-fold LightGBM prediction of the forward 4h magnitude. **X3 − incumbent = −2.24 [−6.81, +2.33] bps per unit of notional on F0+F1**, negative on all three seed-numbers; F2/F3 not read. Because both arms take the same trades the interval is tight enough to **exclude a ladder-sized gain (+8 here)** — a detected absence, not "not detectable". The no-model ablation (own-pair trailing vol as key) is −0.40; the model's gain is hour-of-day and weekday. **Revival trigger:** a magnitude observable the dumps cannot supply (book/flow inside the training window, ≈2027), or the forward ledger's R0 reading. **Needed from Vadim: nothing** |
| **X4** | **Dynamic exits from the side-table** | Every hold is a fixed 240 minutes. M3-0b's price-path side-table makes signal-flip exits, hold extension while the signal persists, trailing stops and regime-conditional barriers scorable offline; M3_0B_RESULTS lists exactly these as untested. Gate must be net of the extra crossing. | CPU only | M3_0B_RESULTS §C4b: six fixed barriers all lost to the 4h hold, "trailing stops, vol-scaled bands and regime-conditional barriers stay untested" | 🟢 **CLOSED 2026-09-15 — NOT CONFIRMED on F2+F3, sign consistent — [WALKFORWARD_PROTOCOL §9.7](./WALKFORWARD_PROTOCOL.md)** (registered, built, explored, confirmed and read the same day). Scoped to the signal-conditioned half; the flip arms never fire (0.0–0.1% of trades); **`persist05`** — hold past 4 h while the model still agrees at the 5% cut, 12 h cap — passed the exploration gate (+43.8 per seed-day on F0+F1) and came back **+25.7 [−23.2, +74.7] bps per seed-day on F2+F3**: positive on all four folds and all three seeds, lower drawdown on every fold, lower bound below zero. Not resolvable offline (MDE ≈ 70). ⚠️ Trailing stops / vol bands / intrabar barriers were never in scope: the side-table starts 2025-11-15 and does not cover the folds; they need an export and their own registration. **Carried forward as R5 of M3_5 §4.3 (registered 2026-09-15, Vadim's yes):** `persist05` reconstructed as a counterfactual from `policy_bars`, read at the same 50-trade steps as R0–R4 by `./scripts/gcp_forward_ledger.sh`; nothing served changes. **Needed from Vadim: nothing** |
| **X5** | **An embargo on the split** | 4h labels on 5m bars overlap 48 ways and the chronological split has no purge, so the last two days of train leak into val and early-stop selection is slightly optimistic. Hygiene, not edge; expected to move nothing. | a small trainer change (no embargo knob exists in `train_m2.py` today) plus one control run to show it moves nothing | standard purged-CV practice; not found anywhere in the project's docs | 🟡 parked as a code item; **not** folded into X0, which must be the served recipe unchanged |

---

## 🟡 Parked — collector / data quality

| item | why it matters | source |
|---|---|---|
| ~~**Raise the trade-tape `limit: 200`**~~ | ✅ **DONE 2026-08-28** — raised to 1000, the endpoint maximum, and verified request-weight-neutral (aggTrades costs 20 weight at every limit, measured). Post-change sampling over 25 clean minutes shows **3 of 861 windows at the new cap (0.35%)**, against the old **30.4% on BTC**. The residual is irreducible by this route — 1000 is the endpoint maximum — and would need the WS tape to close (see the B4.3 row). ⚠️ It fixes the tape only *going forward* — the existing history is censored for good, and per §7 **no number measured before the change may be compared to one measured after it** | [M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md) §1.2 |
| **Disk budget** | 🟡 **Needed from Vadim: nothing yet — decide by 2026-11-01** whether to prune `orderbook_levels` older than N days or grow the VM disk; Claude surfaces this row on or after that date. Measured: **46 GB free, 53% used, 2026-09-13**, down from 53 GB free / 46% on 2026-08-29 — ~7 GB in 15 days, ≈14 GB/month, so the disk fills around **December 2026**, not the six months the earlier per-pair estimate gave. (Earlier estimate: `orderbook_levels` ~24 MB/pair/day → ~8.6 GB/month at 12 pairs.) ⚠️ Now that all twelve collected pairs are also *traded*, adding an instrument means adding it to both lists — and the disk cost is what bounds how many | [M3_PLAN.md](./M3_PLAN.md) §2 M3-4 |

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
