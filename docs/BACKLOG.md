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

## 🔴 New 2026-09-04 — the rules review, the M3 re-score on repaired data, and eight open decisions

**Owner: [RULES_REVIEW.md](./RULES_REVIEW.md).** Asked the same day: are the rules too tight, what
can be cleaned up, and why not re-assess M3 (rule *and* RL) on corrected validation. Verdict in one
line each: the bars are right, the friction is four structural gaps around them (the swap rule is
not in force, the confirmatory lane has no dataset but forward time, Tier 1 ranks on an undecidable
statistic, and there is no data-correction rule); **M3 was re-executed on repaired data and the
incumbent still passes Tier 1 — worst window −4.61 bps against a −5 floor, pooled +13.82 net at
taker — while 0 of 8 learned runs pass**, records in [M3_2_RESULTS_REPAIRED.md](./M3_2_RESULTS_REPAIRED.md)
and [M3_3_RESULTS_REPAIRED.md](./M3_3_RESULTS_REPAIRED.md); RL is not forbidden, it is unfundable on
~220 independent days, and **walk-forward folds over the older history** are the one investment
that unblocks it, the parked pre-registrations, and retraining alike.

✅ **All eight decisions taken the same day and carried out** (RULES_REVIEW §4): **Amendment 2 is
written and in force** ([M3_PROTOCOL.md](./M3_PROTOCOL.md) §9 — Q1 (c) promote on backtest / keep on
forward, Q2 (c) margin plus breadth, Q3 (b) a **65-day staleness trigger** superseding the quarterly
cadence, the data-correction clause, the walk-forward folds as the standing confirmatory dataset,
and a new ranking axis for *future* protocols); the served constants are **re-derived on repaired
data** (cut 0.6296127438545227, p80 0.025596268475055695); the **checkpoint-binding guard is built**
(RETRAIN_PLAN 0.2 — the policy skips every bar unless `ml_inference`'s reported sha256 matches);
the **forward ledger persists across swaps**, every row tagged with its checkpoint and ladder;
`TRAIN_FRACTION` is plumbed and **[WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) is
pre-registered** (4 rolling fixed-width folds × 3 seeds, F2 first); the approved cleanup ran (M1
code, the pre-bucket migration scripts, `quant_ab.sh` and a crash dump are gone; M2-era logs are in
`logs/archive/`; two M2-era studies in `scripts/archive/`). 🟢 **The arrival question is answered
on true data: the cut fires on repaired candles** (last 2026-08-31, longest dry spell 51.8 days) —
the forward test was never regime-blocked.

🔴 **Three things remain, all in RULES_REVIEW §6:** (1) **deploy to `fluxtrader-1`** — both
`ml_inference` and `app`, no truncate, verify `checkpoint_bound: true`; (2) **the fold queue**,
twelve serial runs; (3) **the document-restructuring session**, brief in §6.3. The parked
"re-answer the arrival question" row below is closed by this.

## 🔵 Active

| item | owner doc | state |
|---|---|---|
| **Deploy M3-5 to `fluxtrader-1`** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | ✅ **DONE 2026-08-28.** The clock has started |
| **The forward paper test** | [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) | 🔴 **RESTARTED AND VERIFIED 2026-09-01 — and now REGIME-BLOCKED, which is a new problem.** The frozen rule is deployed and every §6.4 check passes (threshold `0.6318973898887634` on both `confidence_threshold` and `frozen_threshold`; `warm: true` immediately; frozen quintile edges; `rolling_threshold` 0.5549 correctly below the cut; only `below_coverage` in `skips`; arms `policy` + `flat_size` at zero trades; `daily_pnl` 0.0). 🔴 **But the cut has not been exceeded since 2026-06-29 — see "The arrival-rate finding" below.** Waiting is no longer a plan that can be costed, which is why [REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) is the recommended next work. *Superseded status follows.* ⚫ AWAITING RESTART — the rule is fixed in code, the clock is not yet reset.** The cut and ladder are frozen ([M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §6); what remains is the deploy plus the manual `TRUNCATE paper_trades` in §6.4, and the §4.1 control-arm decision that should be made in the same restart. ⚠️ After it, **`warm` is true immediately** — the ~14-hour rank-window wait no longer exists — and long stretches with no trade are expected. Check with `curl localhost:4000/api/health` **on the VM** (host port 4000 there; 4001 is the local-compose mapping). *Superseded status follows.* 🔴 **RAN THE WRONG RULE — see [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) (2026-08-31) and the blocker row below. It needs a decision before more calendar time is spent.** Original status: **Restarted 2026-08-29** on the twelve-pair universe (see the row below). It needs no work, only **calendar time**: it is the only mechanism that manufactures new independent trading days. Check it with `curl localhost:4000/api/health` **on the VM** (host port 4000 there; 4001 is the local-compose mapping). ⚠️ `warm: false` until the rank window holds 2,016 bars — that is **~14 hours at twelve pairs, NOT seven days**; the constant is a bar count pooled across served pairs, and every document said "seven days" until 2026-08-29. It may then idle for weeks (see the volatility note below). Both are the strategy working |
| **The M3 dashboard panel** | [M3_UI_PLAN.md](./M3_UI_PLAN.md) | ✅ **BUILT 2026-08-29, DEPLOYED and live on `fluxtrader-1` 2026-08-31.** It earned its keep immediately: the panel is what made the served-vs-scored threshold gap visible, which is [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md). Original build note follows. ✅ BUILT 2026-08-29.** The forward paper test is the phase's only deliverable and it was **invisible in the UI**; the dashboard now leads with warm state, the rank-window progress, the A/B arms, the named skips and the served-vs-collector drift check, all read-only. 79 tests green; verified with an empty ledger, with Postgres stopped, and against `fluxtrader-1`'s real `/api/health` state. ⚠️ **`fluxtrader-1` still serves the M2-era page** — the deploy is deliberate and pending, and it **changes dependencies** (a test-only Floki), so it needs `app_deps` / `app_build` recreated. Command in [M3_UI_PLAN.md](./M3_UI_PLAN.md) §9 |
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

## 🟢/🔴 The blocker on the forward test itself

*New 2026-08-31. Different from everything below it: it does not block real money, it blocks
the paper test from meaning anything. **The cut row is closed the same day; the two rows under
it are still open and the restart is the moment to settle them.***

| item | why it matters | what to do | source |
|---|---|---|---|
| ✅ **Which coverage cut is the policy — CLOSED 2026-08-31** | Frozen at **0.6318973898887634**, ladder alongside it at **[0.00391214806586504, 0.008861115202307701, 0.015078878961503506, 0.025166796520352364]**. Both derived by `backtest.py` over **the served checkpoint's own split** (seed 2, `20260819T142759Z`); recomputing them reproduces that seed's arm A exactly — 483 trades, mean size 1.362. ⚠️ **A first attempt used O8's 12-pair cut (0.5992) and was wrong:** O8 is a different trained model, and its cut realizes **4.01% coverage** on the served checkpoint against the searched 2% — §1.5's closed "absolute threshold across checkpoints" defect, one level down. A cut belongs to a **checkpoint** first, a universe second. ⚠️ Remaining gap, deliberate: the constants are from an 8-pair split while twelve are served, so realized coverage is not exactly 2%; closing it needs seed 2 re-evaluated on twelve pairs, which would settle the parked coverage pre-registration as a side effect. Consequences that are intended: **no warmup at all**, and **long correct silences** — August's confidence tops out at 0.569 against a 0.6319 cut | 🔴 **The deploy is not the whole fix.** The forward clock restarts by hand: back up and `TRUNCATE paper_trades`, then restart the app to clear the daily P&L. `policy_bars` is **kept** this time — the cut no longer reads from it. Full procedure and the post-restart verification list: [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §6.4 | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §6 |
| ⚫ *(superseded — the original row, kept one release for context)* 🔴 **Decide which coverage cut is the policy** | The backtest ranks the top 2% over the whole 253-day split (a fixed cut, ~0.62). Live, `Ledger.coverage_threshold/3` ranks over a **trailing 14 days**, so it admits 2% of bars in *every* window by construction. August's confidence never exceeds 0.569, so **the validated rule would have taken zero trades and the served rule took twelve**, all of them below every seed's fixed cut. Measured: the served rule scores **+8.62 vs +15.03** net taker bps on the 8-pair baseline with the worst window going **+0.25 → −8.88**, and on the served 12-pair universe it **flips sign, +21.44 → −18.43**. The sizing ladder has the same defect (trailing 30d quintiles; `p80_edge` 0.0179 against a published 0.0431) and costs ~1.5 bps | Freeze the cut at the served seed's banked value (s2 = **0.6319**) so live matches what was scored — this is *not* re-picking a searched dimension, so M3_PROTOCOL §0 is not engaged — **or** pre-register the floating cut as a new rule. Fix the ladder in the same change. ⚠️ **Either way the forward clock restarts and the twelve trades are discarded.** Doing that at twelve trades costs two days; at two hundred it costs the phase. 🔴 The one thing not to do is leave it running undecided | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md), `./scripts/m3.sh -m m3 fidelity` |
| ✅ **The A/B has no B — CLOSED 2026-08-31** | The control arm `signal_only` required `bar.gated` and **nothing had gated in 8,184 bars** (none since 2026-06-29), so it stood at 0 trades against the policy arm's 12 with no end in sight. Re-registered as **`flat_size`: the same bars as the policy, at size 1.0.** The A/B now measures **the regime size ladder** — M3-2's own central claim, worth +8.6 bps on the worst window and never checked forward. `Policy.decide_flat/3` delegates to `Policy.decide/3` so the two arms cannot drift into a two-variable comparison. 🔴 **Compare them on net bps per unit of NOTIONAL, not per trade** — the policy arm varies size, so its per-trade mean is flattered by the very thing under test | Nothing further to decide. Deploy carries it. ⚠️ The arm rename makes `TRUNCATE paper_trades` **required**, not advisory: `PaperTrade.@arms` no longer accepts `signal_only`. The `signal_only` comparison is no longer measured live; reviving it as a third arm is small if M2's gate ever fires again, but should not be done on the assumption that it will | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §6.6, [M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) §4 |
| 🟡 **The daily loss limit biases the forward estimate** | `RiskManager`'s −50/day limit suppresses entries after a bad day, truncating the recorded sample's left tail, so the forward test's mean net bps is biased **upward**. Daily P&L reached −26.78 against it on 2026-08-31 | Accept and document, or log suppressed entries as counterfactual bars so the bias can be removed | [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §4.2 |

---

## 🔴 New 2026-09-03 — the stored candles have been partial bars since 2026-07-18, and the silence is a data defect

**Owner: [CANDLE_POLL_DEFECT.md](./CANDLE_POLL_DEFECT.md).** The collector polls the five most
recent klines every 60 s and inserts with `on_conflict: :nothing`, so every candle is stored at
its **first sighting — within a minute of opening — and never updated when it closes.** Verified
against Binance at identical timestamps: on 2026-08-20 the stored BTCUSDT 5m bars carry a median
**11% of true volume** and **31% of true high–low range**, the close matches in 0/288 bars, and
all twelve pairs show the same (volume ratio medians 0.089–0.112, zero exact matches). A
pre-collector control day matches 288/288. 42 of the 43 post-07-18 days in the export are corrupt.

🔴 **This supersedes the "regime fact" reading in the arrival-rate section below, in
[REAL_MONEY_TRACK.md](./REAL_MONEY_TRACK.md) §1, NEXT_TRAINING_PLAN's top block, M3_PLAN §0.8 and
M3_PROTOCOL §8.0.** The model did not respond to the 8% BTC move on 08-20/21 because the candles
it was shown for those days had a tenth of the volume. The 2026-09-01 check that "live confidence
matches the split" compared two outputs of the same corrupt input. Day-to-day dispersion of the
daily p98 confidence fell **7–14×** on 2026-07-18 on all three seeds — the signature of an input
going flat, not of a calm market.

**Consequences:** every live prediction since 07-18 is void, so the forward paper test has measured
nothing since it began; the last 31 days of every eval dump's split (~12%) are corrupt, so the
frozen cut and ladder must be re-derived after repair (same checkpoint, same rule — a data
correction under C4, not a re-pick); M3-0b and B1/B2 read book-era candles and should be re-run.
Not affected: every training window (all end 2025-12-10), the book/tape/funding/OI tables, M3-4.
**Nothing is lost** — klines are fully backfillable. The fix is a one-line `on_conflict` change plus
a forced re-pull from 2026-07-17; the existing `backfill_history.py` cannot do it because it only
fills gaps. Three decisions are stated as questions in the owning document §6.

---

### 🔴 The candle-repair queue — decided 2026-09-03 to implement later, in this order

**The ordered checklist with real commands is [CANDLE_POLL_DEFECT.md](./CANDLE_POLL_DEFECT.md)
§7.** Three decisions are open there (§6) and must be answered before the step that depends on
each:

| # | question | blocks |
|---|---|---|
| **Q1** | Apply the collector fix **and** the history repair now, or fix only, or neither yet? *(recommended: both)* | §7 steps 1–4 |
| **Q2** | Re-score the served checkpoint on repaired data and re-derive the frozen cut and ladder (same checkpoint, same rule, a C4 data correction), or keep the constants and fix only the live inputs? *(recommended: re-score)* | §7 steps 5–7 |
| **Q3** | Bundle the `serve.py` forming-candle exclusion into the same change, or keep it separate and measured as a fidelity fix? *(recommended: separate)* | the parked row below |

### 🟡 Parked 2026-09-03 — what the defect investigation surfaced, for after the repair

*Each is a proposal filed so it is not lost. None is scheduled; each names what would start it.*

| item | what | why | revival trigger / command |
|---|---|---|---|
| ~~**Input-integrity guard**~~ ✅ **DONE 2026-09-03** (`1200152`) | `scripts/candle_guard.sh` runs `ml/train/verify_candles.py --since-yesterday` daily on `fluxtrader-1` under the **systemd timer** `candle-guard.timer` — runbook: [CANDLE_GUARD.md](./CANDLE_GUARD.md) — (01:40 UTC; the VM is Ubuntu 26.04 with no cron daemon, and `Persistent=true` fires a run missed while the VM was down). Quiet on success, Telegram alert on failure through the bot the app already uses, and `/var/tmp/candle_guard_status.json` written either way. Install/update with `./scripts/install_candle_guard.sh` | The 2026-09-01 "live matches the split" check compared two outputs of the same corrupt input. A candle-vs-exchange check would have fired on 2026-07-19 | **Remaining half, still parked:** (a) surface `candle_guard_status.json` on `/api/health` — the guard cannot alert if the VM is off or the timer is disabled, and only the app can notice that silence; (b) the served model's live feature z-scores against the checkpoint's own `norm_stats`, a drift monitor needing no external call — a live column sitting at −2σ for a month is this defect's signature |
| **The forming candle is the newest timestep at serve time** | `serve.py` `build_tensor` takes the last `max_rows` candles including the still-forming bar; offline every window ends on a complete bar. Drop candles whose `close_time` is in the future | A live/offline mismatch the `on_conflict` fix does not remove. Its size is unmeasured | Q3. Pre-register as a fidelity fix (the 2026-08-31 pattern); measure with `./scripts/m3.sh -m m3 fidelity` before and after |
| ~~**Re-answer the arrival question on true data**~~ ✅ **CLOSED 2026-09-04** | On the repaired seed-2 dump the frozen cut is exceeded through **2026-08-31**; its longest dry spell is **51.8 days** (seeds 1/3: 24.9 / 12.7). `ml/train/output/probe/c4_repaired.py` | The forward test was never regime-blocked — it was reading partial bars. The staleness trigger is calibrated on this (N = 65 days, M3_PROTOCOL §9.1) | — |
| **Kline taker-buy volume and trade count as M2 inputs** | `/fapi/v1/klines` returns `taker_buy_base_volume`, `taker_buy_quote_volume` and `number_of_trades` for the full history; `collector.ex` `parse_kline` and `backfill_history.py` both keep only indices 0–6 ([DATA_COLLECTION_AUDIT.md](./DATA_COLLECTION_AUDIT.md) item 3). Add the columns, backfill four years, one pre-registered run under M3_PROTOCOL §8.3 | It is the one kind of **genuinely external information that is inside the training window today** — order-flow imbalance, not a re-parameterization of bars already in the window, which is what NEXT_TRAINING_PLAN §5 names as the sole reopening condition for features. Every closed feature lever was a function of the existing seven columns | Needs a migration (three columns), collector + backfill changes, a `features.py` group, and a pre-registration written before the run. Do it after the repair, since the same backfill pass can carry the new columns. ⚠️ One run is a probe, not a bank — three seeds bank it (§0.3) |
| **Exploratory probes on the dumps, no GPU** | (a) gross bps and `dir_acc` of the cov-0.02 slice by hour of day and weekday — the model has no clock and crypto has strong intraday seasonality; (b) a market-neutral pairing: at each bar, long the top up-confidence pair against short the top down-confidence pair, scored against the single-leg policy | Both are `EXPLORATORY` under M3_PROTOCOL §8.2 — reasons to write a confirmatory test, never findings. Either could become an M3 observable (a) or an M3 execution variant (b) | Any idle session; run on the **repaired** dumps, not the current ones. Output labelled `EXPLORATORY` |

---

## 🔵 New 2026-09-03 — how fresh should the model be, and how do we find out cheaply

**Owner: [RETRAIN_PLAN.md](./RETRAIN_PLAN.md).** The served model's training data stops
~2025-12-10, so it is **~253 days ≈ 8.3 months stale**, and *nobody chose that*: the split is a
fraction (`VAL_FRACTION = 0.2`), so `staleness = 0.2 × span = exactly the val window's length`.
Staleness therefore **grows on its own at 0.2 days per calendar day**, and adding older history
makes it *worse* (the boundary is `start + 0.8 × span`).

🔵 **ANSWERED 2026-09-04 (Phase 2): whether staleness costs anything is UNMEASURABLE on this
data.** The repair removed the candle defect from w4 and the decay-shaped curve survived
(+18.6 / +15.2 / +5.5 / **−1.9** net at taker) — **but w4's 95% interval contains the means of
all three other windows**, so the windows cannot be ranked at all. Three seeds over one market
give ~35–52 day-clusters per window and ±50–100 bps intervals on a ~15 bps edge. **Phase 3
cannot fix this**: priced against the same precision, its gate could only resolve a freshness
effect of ~111–118 bps/trade, 7–12× the model's entire edge. Freshness is now ranked **fourth**
— behind three things Phase 2 found on the way (see the table).

### ✅ Phase 0 closed 2026-09-04; Phases 1 and 2 done — the plan's centre of gravity has moved

| step | state |
|---|---|
| **0.1** verify the repair actually finished | ✅ **PASSED** — `verify_candles.py` returned **36/36**, twelve pairs × 07-21 / 08-20 / 09-02 at 5m, every one `288/288 exact vol=close=high=low=1.000`. 🟢 **2026-08-20 is the decisive one**: it is the day recorded at a median **11%** of true volume with **0/288** matching closes, and it is now 1.000 across the board. Pre-deploy days prove the repair, the post-deploy day proves the collector fix |
| **0.2** the checkpoint-binding guard | ⚪ **not started — and deliberately not blocking.** See the decision below |
| **0.3** plumb `VAL_FRACTION` and `VAL_OFFSET` into the launcher | ✅ **DONE — both halves.** `train_m2.py` always accepted `--val-frac` / `--val-offset`; the launcher forwarded neither. `VAL_FRACTION` was closed first; `VAL_OFFSET` followed 2026-09-04 (`config.py:188`, `train_m2.py:548`, `gcp_train.sh:180`), with the argparse default moved `0.0 → None` so the env var is reachable and an out-of-range fold now **exits** instead of clamping silently. `VAL_OFFSET=0.0` reproduces the trailing split bar for bar. **This is what makes walk-forward folds launchable** |

🟢 **All five §8 decisions taken 2026-09-04: Q0 (a), Q1 (d), Q2 (B), Q3 (a), Q4 (a).** In one
line each: **re-score the incumbent against Tier 1 on repaired data first** (it is cheap and
everything else assumes its answer); **buy statistical precision before touching the split**,
since a shorter holdout cannot score a challenger; **certify by walk-forward folds** rather than
by refreshing an uncertified checkpoint; **quarterly cadence**, no trigger — this population
cannot calibrate one; and the guard blocks **Phase 4 only**. Q1 and Q2 converge on a single
investment: the folds bought for precision are the folds that certify a fresh checkpoint.

**Decision taken 2026-09-04 — RETRAIN_PLAN §8 Q4 = (a): the checkpoint-binding guard blocks
Phase 4 only.** Phases 1–3 swap no checkpoint, so nothing can be mis-served. The guard remains a
hard precondition for Phase 4 and for M3_PROTOCOL §8.3 **C5**, and it is still the thing that
"blocks fast iteration today" — it is just not a reason to delay a read-only re-baseline.

| item | what | gated on | revival trigger / next command |
|---|---|---|---|
| ✅ **Phase 1 — re-baseline on repaired data** | **DONE 2026-09-04.** Three eval-only runs (`20260904T051921Z` / `061948Z` / `073714Z`), all DONE, on a verified-fresh post-repair dump. 🔴 **Its headline is RETRACTED**: "the repair bought back real edge, median +2.14 bps, 3/3 seeds" was read off the eval log's **Horizon 60m** block, not the **240m primary head** every M3 policy uses. On 240m the same cells are **−1.22 / +3.17 / −3.51** — 1 up, 2 down. What survives: the 240m head is net-**positive** at taker on all three seeds (+6.89 / +6.00 / +8.72), and the C4 cut re-derived to **0.6296** against the frozen `0.6318973898887634` | — | See [RETRAIN_PLAN.md](./RETRAIN_PLAN.md) §4. When reading `eval_m2.py`, **the 240m block is the one that counts** |
| ✅ **Phase 2 — read the decay curve** | **DONE 2026-09-04. Verdict `NOT DECIDABLE`** on both policies, both eras, both scopes — w4's clustered CI contains all three other windows' means. Also found: the two eras are **not the same calendar rows** (val start moved +12d, end +16d), so every before/after is clipped to the shared span; the defect did not degrade w4 evenly, it **deleted the last fortnight** (0 bars over the cut in 2026-08-01..17, all three seeds) | — | `./scripts/m3.sh -m m3 decay` reproduces it; `M3_ERA=repaired` switches any m3 command to the repaired dumps. Logs `logs/P2-*.log` |
| 🔴 **Phase 3 — the paired freshness test** | **BLOCKED — underpowered by construction, not scheduled.** §5.4 prices its gate at a **~111–118 bps/trade** minimum detectable effect against a ~9–17 bps edge. Running it as written returns `NOT DECIDABLE` whatever the truth is | A **redesign that adds day-clusters** — more seeds, the banked 12-pair universe, or walk-forward folds. A shorter holdout makes precision *worse*, not better. 🟢 **§8 Q1 = (d) funds exactly this**, so the revival trigger is now being built | Do **not** launch `VAL_FRACTION=0.095`. Revive only when a per-window mean has an interval narrower than the edge |
| ⚪ **Phase 4 — what gets served, and on what cadence** | Resolves a genuine conflict: a fresh-boundary challenger has a short split and cannot satisfy C1/C2 as written, and §8.5 refuses to lower Tier 1 | Phase 0.2 **only** — the Phase 3 gate is removed, since Phase 3 cannot report | ✅ **RESOLVED §8 Q2 = (B), walk-forward certification** at k× the compute — the only option under which the *served* artefact is itself certified, and the same runs Q1 (d) buys for precision. (A) stays available as an interim only if the promotion record states plainly that the served checkpoint is uncertified. 🔴 **One design question precedes the runs**: anchored versus rolling fixed-width train window (RETRAIN_PLAN §7 B) — the implemented split is anchored, so older folds train on less data and a fold score mixes boundary age with training-set size |

### 🔴 What Phase 2 found on the way — these outrank freshness

| # | finding | why it outranks | cost |
|---|---|---|---|
| 1 | **The incumbent's worst window is −4.61 bps** on repaired data, against the **+0.25 bps** M3_2_RESULTS §D fixed as M3-3's promotion bar | It is about what is servable **today**, and every other question assumes an answer to it | No GPU — a Tier-1 re-score of an existing checkpoint |
| 2 | **The regime ladder flattened by half at Q5** (+35.5 → +17.4 bps; per seed `[+34.8,+32.5,+38.7]` → `[+12.3,+8.3,+32.3]`) | The incumbent's `size_by_regime` overlay rests on exactly this ladder | No GPU |
| 3 | **The served rule (fidelity arm D) scores −0.29 bps** at taker, down from +8.62; the **validated** arm A is at +13.82 | The gap between what was certified and what runs in production is now the entire edge — which is what **0.2, the checkpoint-binding guard**, exists to catch | 0.2 is already sized |

🔴 **Phase 1 buys far more than this plan.** The same three re-scored dumps are what unblock
the arrival-rate re-answer, the C4 re-derivation of the frozen cut and ladder, and the M3-0b /
B1 / B2 re-runs — every one of which currently rests on corrupt candles. They are reachable
from any m3 command as `M3_ERA=repaired`.

🔴 **M3_PROTOCOL §8.6 Q3's recommended retrain trigger is void, and Phase 2 confirms it stays
void.** It proposed triggering on "the served checkpoint going N days without exceeding its own
cut", calling that "exactly the condition now in force" — but **that condition was the candle
defect**. A repaired baseline now exists and it **still cannot calibrate a trigger**: this
population cannot resolve a per-window change of the size a trigger would fire on. The answer
remains a fixed **quarterly** cadence, chosen to bound staleness rather than to react to a
signal.

**The open questions** (§8) — ✅ **all answered 2026-09-04**:
**Q0 = (a)** re-score the incumbent against Tier 1 on the repaired dumps, before any other
phase, no GPU;
**Q1 = (d)** add precision before touching the split — (a) "shorten for challengers" was already
**removed** as unscoreable, and (b) keep-and-accept is what happens meanwhile, not a resolution;
**Q2 = (B)** walk-forward certification, the same runs Q1 (d) buys;
**Q3 = (a)** quarterly cadence; a trigger is not calibratable here;
**Q4 = (a)** the guard blocks Phase 4 only.

**Next command, and the pre-registered reading** (RETRAIN_PLAN §8 Q0). Eval-only, in Docker:

```sh
M3_ERA=repaired ./scripts/m3.sh -m m3 validate   # C3 first, then
M3_ERA=repaired ./scripts/m3.sh -m m3 search     # Tier 1 over the 40 configurations
```

Bring back the `n / 36` Tier-1 line, the incumbent `cov0.02_hold240_rqnone_mcnone_SIZED`'s six
criteria individually, and its per-window net at taker with the clustered interval. **Fail P3
(worst window < −5 bps) → not servable, and Phase 4 becomes urgent. Pass P3 but land below
+0.25 → the bar is restated at the new number and M3-3's comparisons are re-read against it;
the challengers do not retroactively pass.**

---

## ⚫ The arrival-rate finding, 2026-09-01 — SUPERSEDED 2026-09-03 for everything after 07-18

*🔴 Read the section above first. The three hypotheses killed here stay dead; the one this section
did not test — the stored inputs themselves — is the cause. The July 1–17 dry spell is real; from
07-18 the model was reading partial bars. Kept one release for the record.*

*Original text, and it changes the phase's sequencing. Measured offline on the served checkpoint's own dump
(`20260819T142759Z`) plus the live bar log; probe scripts in `ml/train/output/probe/` (gitignored).*

**The frozen cut has not been exceeded since 2026-06-29 — ~64 days and counting.** In the 252-day
evaluation split the cut fires on 93 days (36.9%), but **68% of those bars fall in just two months**
(Feb + June), July and August contribute **zero**, and the longest dry spell in the whole record is
**50 days — the same spell, still running.**

🔴 **The comfortable explanation is wrong: volatility came and the model did not respond.** BTC's
1-day absolute return hit **0.080 / 0.075 on 2026-08-20/21**, the largest in the entire export and a
level that historically fired on **100%** of days. Live confidence stayed at ~0.56 against a cut of
0.6319. So "wait for volatility to return" is not a mechanism anyone has evidence for.

**Three defect hypotheses were checked and all are dead** — this is a regime fact, not a bug:

1. **Not serve-path drift.** Live median confidence **0.5197** vs the split's **0.5194**; the live
   distribution is a clean day-for-day continuation of the split's own July–August tail.
2. **Not book features going out-of-distribution.** The ceiling collapse *looks* coincident with
   `has_book` going 0→1, but `NORM_DEGENERATE_MODE=zero` pins constant-in-train columns to zero in
   train, val **and** serve — the model is candle-only and never sees live book values
   (`config.py`, and `serve.py` warns about it at load). The p98 decline also *starts before* book
   turns on, which the coincidence hid. ⚠️ The clean within-day paired test was underpowered
   (8 mixed cells, p≈0.15) and settles nothing on its own; the config is what settles it.
3. **Not seed-specific.** **All six** checkpoints on disk — including the 12-pair O8 and both
   T-wave seeds — show daily-max confidence falling from ~0.62–0.66 pre-July to ~0.55–0.59 after,
   each ceasing to fire its own cut between 2026-06-29 and 2026-08-22.

**What this does NOT license.** 🔴 It is not evidence that the policy is broken, and it is not
grounds to lower the cut. Un-freezing the cut to make trades happen is arm D, whose worst window is
negative, and re-picking coverage after seeing this is exactly what M3_PROTOCOL §0 forbids. The
honest reading is that the rule is correct and the regime that pays it is absent.

⚠️ **One avoidable loss:** `policy_bars` was reset on 2026-08-29, so the Aug 19–28 window covering
the volatility spike is gone. That log is the only record of what the model says during a live
volatility event. **Do not reset it again.**

---

## 🔵 New 2026-09-01 — the protocol now has an exploratory lane, pending three decisions

**[M3_PROTOCOL.md](./M3_PROTOCOL.md) §8 (Amendment 1)** adds two things and changes no bar:

* an **exploratory lane** — no pre-registration, look at anything as often as you like, provided
  the output is labelled `EXPLORATORY` and **never cited in a promotion argument**. To promote on
  an exploratory result you re-establish it confirmatorily on data the exploration did not touch;
* a **standing champion–challenger promotion rule** (C1–C5), registered once so that retraining
  and swapping models needs no fresh pre-registration each time. C4 makes the 2026-08-31 defect a
  rule: the cut and ladder are **always** re-derived from the challenger's own split.

🔴 **It is NOT in force.** §8.6 holds three open decisions — whether a challenger needs forward
evidence (recommendation: promote on backtest, *keep* on forward), what margin C2 must clear
(recommendation: more than the between-seed spread), and whether retraining runs on a cadence or
on a staleness trigger. 🔴 **Q3's recommendation is void as written** — it proposed a trigger of
"N days without the checkpoint exceeding its own cut, measurable today and would have fired in
July", but **that condition was the candle defect**, so it would have fired for the wrong reason.
Until a repaired baseline exists there is no calibrated trigger; the interim answer is a fixed
**quarterly** cadence. See [RETRAIN_PLAN.md](./RETRAIN_PLAN.md) §7 and §8 Q3.

⚠️ **The amendment discloses that search output was seen when it was written**, and is therefore
**prospective only**: it alters no completed verdict, and Tier 1 / Tier 2 are unchanged. It also
does not solve the current problem — see §8.5.

**Blocked on:** the checkpoint-binding guard in the row below. Until a mismatch refuses to serve,
the promotion rule cannot safely be used. ⚠️ That blocker is scoped: it stops **promotion**, and
per RETRAIN_PLAN §8 Q4 it does **not** stop the read-only re-baseline in Phases 1–3.

---

## 🔴 New 2026-09-01 — swapping the served checkpoint silently breaks the policy

*Filed from [M3_FIDELITY_RESULTS.md](./M3_FIDELITY_RESULTS.md) §6.5, where it was recorded but never
indexed here. It is promoted to its own row because it is **the actual blocker on iterating models
quickly**, which is a standing goal — not a footnote to the freeze.*

The policy now serves two constants frozen from **one specific checkpoint's own split**: the
coverage cut `0.6318973898887634` and the regime ladder, both derived by `backtest.py` over seed 2
(`20260819T142759Z`). **Neither is tied to the checkpoint in code.** `served_pairs` is guarded by a
test; the served *checkpoint* is not. Dropping a new `m2_multi.pt` in place silently invalidates
both constants, and **nothing currently fails when that happens** — the policy would keep trading,
against a threshold belonging to a model that is no longer running. That is the served-vs-scored
defect of 2026-08-31 all over again, with a different trigger.

**Why it matters beyond correctness:** it is what makes "retrain and swap the model on the go"
unsafe today. The obstacle to fast iteration is this missing binding, **not** the protocol.

**What to do (not yet scheduled, needs a decision on approach):** record the checkpoint identity
alongside the constants and refuse to serve — loudly, at boot — when the loaded checkpoint is not
the one the constants were derived from. A promotion then becomes: derive the new cut and ladder
from the new checkpoint's split, update both, restart. ⚠️ It also **restarts the forward clock**,
since it is a different rule, so it cannot be done casually mid-test.

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
