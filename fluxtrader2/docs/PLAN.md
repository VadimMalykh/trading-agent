# fluxtrader2 — the plan

**Written 2026-09-15 from a design conversation; this is the whole plan, kept current.** When a
phase finishes, its section gets a result line and the README status row moves. Superseded
reasoning is deleted, not appended to. Parked items go in §7 with a revival trigger.

## 0. The goal, and the one-sentence strategy

**Goal:** a system that generates profitable trades on the twelve USDⓈ-M perpetual pairs the
collector records, using only that data.

**Strategy:** start at the trade end and work backwards. The cost of a trade fixes the
horizon, the horizon fixes the target, and the target fixes which kind of model can possibly
work. Build the measuring instrument before any model. Let measured ceilings, not taste, choose
the architecture, and add capacity only when a measurement says the cheaper thing left money
on the table.

## 1. What we know going in (no project conclusions, only general facts)

Read this section first if you are new to the problem; it defines the words used below.

- **Signal is weak by construction.** A market removes any regularity once it is traded, so the
  predictable part of the next few hours' return is a fraction of a percent of its variance.
  That is the opposite of the regime where large flexible models shine. Here *variance
  control* (shrinkage, averaging, few features, cleaner targets) matters more than model class.
- **Magnitude is predictable, direction barely is.** How much a price will move in the next
  hours can be forecast well from recent volatility and book depth. Which way it moves cannot,
  or only slightly. Anything that keys on magnitude (sizing, choosing when to trade) is the
  tractable half of the problem.
- **Breadth beats accuracy.** A weak edge becomes useful by being applied to many nearly
  independent bets. The usable quality of a strategy scales as skill × √(number of independent
  bets). Twelve pairs and many decision points per day is where that breadth comes from.
- **Units.** A basis point (bps) is 0.01%. "Gross" is before costs, "net" after. A "taker" order
  crosses the spread and pays the exchange's taker fee; a "maker" order rests and may not
  fill. A "round trip" is entry plus exit, so every per-trade cost below is counted twice.
- **The data.** Four years of 1m/5m/15m/1h candles on nine pairs (less on three) — plus, since 2026-09-21, the public
  archive's 5m candles for the same nine from 2020 (fold FP) — and about
  two months of order book, trades, funding and open interest. Details, extents and known
  defects in [DATA.md](./DATA.md). The two-month book era is *too short* to support a
  walk-forward with any statistical power on its own; it is used to calibrate cost and
  execution models, and as a check on candle-derived proxies, not as training data.

## 2. Principles (the rules this project holds itself to)

1. **Cost first.** No target or model is discussed before the cost of trading it is priced.
2. **Ceiling before model.** Every candidate bet type and horizon gets a measured
   signal-strength ceiling, a noise floor and a detectable-effect size *before* a model is fitted
   to it. A model is only fitted where the ceiling clears the cost.
3. **Registration before reading.** Every comparison that could change a decision is written
   down first: the exact contrast, the folds it reads, the gate that decides, and what we expect
   to see. Then the number is read once. No re-picking a searched dimension after seeing results.
4. **Untouched folds.** Data is split into time folds up front; the later folds are read only at
   pre-registered confirmation points, never during exploration.
5. **Power is reported with every result.** A negative result on an underpowered test is
   "not detectable", never "no effect". Every reported interval comes with the effect size the
   test could have detected.
6. **Simplest thing first, and it stays as the baseline.** A fixed rule with two or three
   parameters is the first trade generator, and every later stage must beat it out of sample
   and outside the noise floor.
7. **Capacity is earned.** A learned policy, an end-to-end model, a sequence model, or book
   features as inputs each require a prior measurement showing the cheaper stage leaves money.
8. **Everything runs in Docker, nothing on the host.** Repo-wide rule.
9. **One entry point** (README.md), one plan (this file), one data document. Results are
   recorded as result lines and tables inside these; a new document needs a reason.

## 3. Protocol (how a number becomes a decision)

- **Folds.** The candle history is cut into six contiguous 8-month folds (DATA.md "Folds",
  `ft2/folds.py`), with a 2-day embargo at the start of each scored fold. F0 is warm-up
  (training history only); F1 and F2 are the *exploration* folds; F3–F5 are *confirmation*
  folds, read only by registered contrasts. Each confirmation read is logged; a fold that has been
  read for a question cannot be reused for the same question.
- **Walk-forward.** Any fitted thing is fitted on data strictly before the window it is scored
  on, refitted per fold, and scored on the fold it has never seen.
- **Noise floor.** The same pipeline is run on labels shuffled within day, many times. A real
  result must sit outside the spread of those runs, otherwise it is unmeasured.
- **Effect size and detectable effect.** Results are per trade or per unit of notional, in bps,
  with an interval clustered by day (returns within a day are not independent). Alongside every
  interval: the minimum detectable effect (MDE) at that sample, so the reader can see whether a
  null is informative.
- **Registration file.** Each registered contrast is a short block in §8 of this document:
  name, question, contrast, folds read, gate, expectation, and, after the read, the result. Written
  before the number, dated, never edited after the read except to add the result.
- **Ledger.** Every simulated trade records the decision (what, when, why, at what size) and the
  fill (price, cost) *separately*, so that execution assumptions can be re-priced without
  re-deciding.

## 4. Phases

Each phase names its deliverable, its exact command once the code exists, and what it needs
from Vadim. Phases are serial unless stated. Times are rough and CPU-only.

### P0 — Get the data in (✅ done 2026-09-15, P0b ✅ done 2026-09-15)

**Result 2026-09-15:** all nine collector slices exported and ingested (DATA.md has the counts and
the integrity summary: no duplicates, no interior gaps, 5m bars consistent with 1m, ~160 ms
book clock skew, ≤1.8% censored tape windows); folds fixed in `ft2/folds.py`; the public
archive's coverage measured (§9 #1).

**P0b result 2026-09-15:** the archive's `metrics` (5m), `bookDepth` (30 s, ±1..5 % bands) and
monthly `fundingRate` fetched for all twelve pairs from 2023-01-01 and ingested
(`ft2 ingest metrics depth funding_archive`; DATA.md "External data" has the tables). Two
corrections to what the plan assumed: **(a)** the first fetch had died silently on a connection
reset after three pairs — the fetcher now retries and reports; **(b)** `bookDepth` holds *no best
bid/ask* (it is depth within ±1–5 % of mid), so the historical spread must come from the tape,
which is 136 GB zipped and is streamed into a per-minute summary (`ft2 tape`, DATA.md "tape")
rather than kept. Archive funding matches the collector's funding 100 % where they overlap.

**Deliverable:** one parquet per table under `fluxtrader2/data/`, a loader in `ft2.data`, and
an integrity report (row counts, extents, interior gaps, duplicate timestamps, partial-bar
check) written into DATA.md as a measured table.

- Export with `scripts/export.sh`: **5m and 1h candles over the full history** (2022-08 →
  today, all twelve pairs), and the **book-era tables** (snapshots, trades, funding, oi, lsr) from
  2026-07-01. With the VM's disk, 1m candles over the full history (23M rows) are pulled too; the raw ladder
  (`levels`) is pulled windowed only when P1's impact walk needs it.
- `ft2 ingest`: raw csv.gz → one parquet per table, typed, sorted, de-duplicated.
- `ft2 inventory`: the integrity report (extents, interior gaps, duplicates, partial-bar
  check, clock skew) written as tables into DATA.md.
- Define the folds (§3) from the measured extents and write them into DATA.md.

**Needed from Vadim:** the work VM (PLAN §6). Then Claude runs P0 on it.

### P1 — Price the trade (✅ measured 2026-09-15; fee tier ✅ read from the account 2026-09-20)

**Result in plain words.** A basis point (bps) is 0.01 %; a "round trip" is entry plus exit.
On a 10,000 USDT position, a **taker** round trip (crossing the spread both ways) costs
**10.0–10.6 bps on BTC, ETH and SOL, 10.8–12.8 bps on DOGE, XRP, AVAX, LINK, HYPE and PEPE,
11.9–13.3 on ADA, ~14.2 on WLD and 14.5–15.5 on ZEC** — that is 10 to 16 USDT per 10k
traded. Of those, **10 bps are the exchange fee** (5 bps each way at the published VIP 0
schedule); the spread and the book's depth add only 0.02–5.5 bps at this size. So at the sizes
we would start with, the cost is the fee, and **the account's fee tier is the single biggest
lever on cost** — read from the account on 2026-09-20: VIP 0, as assumed. At 100,000 USDT the majors still cost ~10–11 bps but
the thin pairs 17–28 and ZEC cannot be priced (the book is too shallow on most days: blank, not
guessed). A **maker** round trip (resting at the touch, filled only when price trades through
the order) costs **6–10 bps** — 4 bps of fees plus 1–3 bps of adverse drift after the fill —
and gets filled within 15 minutes on 86–97 % of placements; the rest have to pay the taker
path. Holding through funding costs 0.6–2.7 bps per 8 hours (unconditional on side), so a
one-day hold adds 2–8 bps. **Bottom line for P2: a signal has to be worth more than ~10–13 bps
per round trip at 10k (14–16 on ZEC) as a taker, or ~6–10 as a maker, before it can trade.**

**Where each number comes from** (`ft2 cost`, `output/cost.md`, `data/cost_daily.parquet` for
the harness, `data/cost_table.parquet` for the summary):

| component | measured | validation / caveat |
|---|---|---|
| spread | tape bounce estimate per pair × day, 2023-01 → 09-13; BTC 0.02 bps, ETH 0.05, SOL 0.4–0.5, the rest 0.3–2.6; hour-of-day effect ≤ 30 % | vs the collector's quoted spread on the 2026-07 → 09 overlap: ratio 0.76–1.00, daily correlation 0.63–0.99; the per-pair ratio calibrates the whole history (`spread_cal_bps`) |
| impact | ladder walk, 40 days, 8 notionals; at 10k: 0–0.6 bps beyond the half-spread on the majors, 0.5–1.6 on PEPE/WLD | carried back by the archive ±1 % depth as impact(N·(D_ref/D_day)^γ); γ = 0.5 chosen inside the window (deep half → shallow half, mean relative error 0.406 vs 0.424 with no scaling — depth scaling barely matters at the window's 1.2–1.9 depth ratios; the history reaches ratio 12 on ZEC, where censoring, not the curve, protects the number) |
| maker fill / adverse selection | tape minutes: resting at the minute's last bid/ask, filled if a later trade goes through it within 5/15/30 min; drift vs the resting price conditional on the fill | coarse (1-minute, queue position unknown); trade-level check on a short raw window is parked (§7) |
| fees | **measured 2026-09-20**: VIP 0, maker 2.0 / taker 5.0 bps per side on every pair checked (`GET /fapi/v1/commissionRate`, read-only key) — exactly what P1 and P2 assumed, so no number changes and nothing is re-run | BNB fee-burn is ON on the account but the futures wallet holds **no BNB**, so the 10 % discount does not apply today. Holding a little BNB there makes it 1.8 / 4.5 bps (round trip 9 instead of 10 taker): `--taker-bps 4.5 --maker-bps 1.8` on `cost` and `ceiling` when that happens. The `output/*.md` headers generated before 2026-09-20 still say PENDING |
| funding | `funding_archive`, signed and absolute per day; interval 8 h (HYPE 4 h) | — |
| candle proxy | per-pair regression of the daily spread on 5m range, dollar volume and price; applied to 2022-08 → 2022-12 (1,215 pair-days) | time-split error 3–19 % on 7 pairs, 31–71 % on AVAX, WLD, ZEC, PEPE, SOL; only fold F0 (never scored) uses it |

**Not yet done:** the trade-level maker validation (parked).


**Deliverable:** a cost table, per pair × side (taker/maker) × volatility regime, in bps per
round trip at a range of notionals (decided in P1 from the measured depth), over the **whole
2023-01 → history** — not proxied — plus a **candle-based cost proxy** for 2022-08 → 2022-12
and as a sanity check on the tape estimate.

What each cost component is measured from (decided 2026-09-15 from what the data turned out
to contain; DATA.md "External data"):

| component | source | window | how |
|---|---|---|---|
| **effective spread** (taker's half-spread paid at the touch) | archive tape per-minute summary `data/tape/` (`eff_spread_bps`, `ask_last`−`bid_last`) | 2023-01 → | per pair × hour-of-day × volatility tercile; **validated** against the collector's quoted `spread` in `snapshots` on their overlap (2026-07-17 → 09-13), which is the only window with both truth and estimate |
| **impact** of a given notional | collector's raw ladder `orderbook_levels` (walk the book) | 2026-08-05 → 09-13, exported windowed | impact(notional) per pair; then **scaled back in time** by `depth` (`usd_m1`/`usd_p1`, the ±1 % band) — the scaling's error is reported from the overlap, not assumed |
| **maker fill & adverse selection** | tape per-minute `high`/`low` (did price trade through a resting level within N minutes) and `close` N minutes later | 2023-01 → | coarse (1-minute) over the full history; **trade-level** on a short validation window fetched with `ft2 tape --keep-zip` |
| **fees** | the venue's published schedule + the account's tier | input | recorded with its source; never assumed. **This is the one input Vadim must supply.** |
| **funding** | `funding_archive` (`rate`, `interval_h`) | 2020 → | a carry cost for holds that cross a funding time; interval is *not* constant (4 h / 2 h periods exist) |
| **candle proxy** | 5m candles high/low/close | 2022-08 → | fitted on 2023-01 → against the tape estimate, error reported, applied to 2022-08 → 2022-12 only |

Commands, in order (all on the work VM; the code is unit-tested on synthetic data first with
`scripts/ft2.sh --test`, Docker, no VM):

1. `ft2 tape` — **started 2026-09-15 04:35 UTC** on the VM (log `output/logs/p0b_chain2.log`,
   the VM powers itself off at the end). The log ends with one `tape <pair> {...}` line per pair
   and `tape-done`; any `err` or unexpected `missing` count → `vm.sh run tape` again (per-day
   parts already done are skipped). Then `vm.sh run inventory`, `vm.sh pull`, fill the `tape`
   row in DATA.md.
2. `vm.sh bgsh p1_levels_export 'FROM=2026-08-05 TO=2026-09-14 FT2_PG_HOST=10.212.0.2 bash scripts/export.sh levels'`
   (started 2026-09-15 06:23 UTC, in parallel with the tape), then `vm.sh run ingest levels` →
   `data/ladder/<symbol>.parquet` (DATA.md "ladder"; `ft2/ladder.py` holds the book walk).
3. `vm.sh run cost` (`ft2/cost.py`, written 2026-09-15) → `output/cost.md`,
   `data/cost_daily.parquet` (pair × day: regime, spread with its source, impact per notional,
   maker fill/adverse selection, funding — what the harness re-prices trades from) and
   `data/cost_table.parquet` (pair × regime summary). Fees enter as `--taker-bps/--maker-bps`
   (default: the published VIP 0 schedule, 5 / 2 bps, recorded as PENDING in the report header)
   and `--fee-source`. Then `vm.sh pull` and fill the table rows below from `output/cost.md`.

**Needed from Vadim:** the account's Binance USDⓈ-M fee tier — either the VIP level and whether
BNB fee discount is on, or a read-only API key so that `GET /fapi/v1/commissionRate` can be
read once and recorded. Everything else in P1 runs without him.

### P2 — Ceiling audit: how much signal is there, per bet type and horizon (✅ all seven items measured 2026-09-20; verdicts below)

**Result, in plain words** (`ft2 ceiling`, `output/ceiling.md`; exploration folds F1+F2 only,
2023-05-03 → 2024-08-31, eleven pairs, 485 days; fees VIP 0, read from the account 2026-09-20). Words used: a
*basis point* (bps) is 0.01 %; a *round trip* is entry plus exit — 12.3 bps as a taker, 7.2 as a
maker (P1); *IC* is the correlation between a signal and the move that follows, 0 = useless,
0.05 = a good weak signal; "IC needed" is the IC at which trading the strongest tenth of signals
just pays its round trip; the *noise floor* is the IC the same search reaches on labels that were
shuffled so that no signal can exist (200 shuffles) — a measured IC counts only above it.

**Can anything trade profitably yet? Not shown — but there is now one bet worth building.**
A pair's **own move over the next 4 hours** is predictable by short-term *reversal* (what rose
over the last hours to a day tends to give some back) at a strength that is (a) far outside the
noise floor, (b) reproduced out of sample by a fitted forecast, and (c) as large as the cost bar
if the order rests as a maker or if only high-volatility bars are traded. That is a funded
*candidate*: nothing has been run through a ledger with costs yet, which is P3/P4's job.
Everything at 15m and 1h is real but too small for the cost; the pair-vs-basket bet, the plan's
prior favourite, did **not** hold up at 4h–1d.

| bet | horizon | IC needed (taker / maker; *with vol timing*) | best IC measured (feature) | noise floor (IC) | fitted forecast, out of sample | **verdict** |
|---|---|---|---|---|---|---|
| directional | 15m | 0.19 / 0.11; *0.08 / 0.05* | 0.024 (last 15m return) | — | — | **excluded** — a quarter of the bar |
| directional | 1h | 0.09 / 0.05; *0.04 / 0.03* | 0.031 (last 1d return) | 0.016 | 0.028, real (p 0.005) | **real, not funded** — below the bar except maker + timing, with no margin |
| directional | 4h | 0.047 / 0.027; *0.024 / 0.015* | 0.045 (last 1d return), 0.043 (last 4h) | 0.026 | 0.035 on all history, 0.052–0.057 refitted on the last 30–120 days; real (p 0.005) | **FUND — P4's bet** |
| directional | 1d | 0.018 / 0.011; *0.011 / 0.007* | 0.051 (last 4h return) | 0.045 | 0.012 on all history = noise (p 0.61); 0.06–0.08 on the last 30–120 days (t 2.5–3.9, window picked after the fact) | **not detectable yet** — second in line; the single features are real, the forecast is unstable |
| relative | 15m | 0.29 / 0.17; *0.13 / 0.08* | 0.043 (last 15m return) | — | — | **excluded** — very real, far too small |
| relative | 1h | 0.14 / 0.08; *0.07 / 0.04* | 0.032 (last 1h return) | 0.011 | 0.013, real (p 0.005) | **excluded on cost** |
| relative | 4h | 0.071 / 0.041; *0.038 / 0.024* | 0.030 (last 4h return) | 0.021 | −0.002 = noise (p 0.75) at every window, ridge and tree | **not funded** — single features real, no forecast reproduces them |
| relative | 1d | 0.027 / 0.016; *0.016 / 0.010* | 0.032 (±1 % book imbalance) | 0.036 | −0.028: the fitted relation *flips sign* out of sample (p 0.015) | **not detectable** — one feature, p 0.015 after paying for the search |

What the seven items say, each in a sentence:

- **#7 Move vs cost.** Costs are small next to moves except at 15m: a sign bet must be right 70 %
  of the time at 15m, 60 % at 1h, 55 % at 4h, 52 % at 1d (taker). The pair-vs-basket bet moves
  only two-thirds as much as the pair itself, so its bar is higher at every horizon.
- **#1 Magnitude vs direction.** *How much* price will move is predictable out of sample (R² 16 %
  at 15m, 14 % at 1h, 11 % at 4h, 5 % at 1d); *which way* is not (R² ≤ 0.2 %). Trading only the
  tenth of bars with the largest predicted move doubles the average move (×2.1 at 1h, ×1.9 at 4h,
  ×1.7 at 1d) at the same cost — that is the "with vol timing" column, and it roughly halves
  every bar. **Volatility timing is funded as a multiplier** (decision table row 2).
- **#2 Linear structure.** Mild mean reversion everywhere: variance ratios 0.95 (15m) → 0.85 (1d),
  never above 1 on any pair raw. The first principal component is 61–70 % of the pairs' variance
  — two-thirds of what any pair does is "the market", which is what the relative bet removes.
- **#3 IC screen** (24 features × 4 horizons × 3 bets). Every directional and relative signal
  that survives is **reversal**: trailing returns with a negative sign, stable in 81–100 % of
  months. Book depth, order flow, open interest, long/short ratios and funding add little on
  direction. For magnitude, dollar-volume surprise and short/long volatility ratio carry IC ≈ 0.25.
- **#6 Power.** 485 days resolve ±0.4 (15m) to ±3.5 (1d) bps per trade at a tenth of the bars
  traded, and an IC of ±0.005–0.03. Power is not the constraint on these folds; signal size is.
- **#4 Noise floor** (200 whole-day label shuffles, 1h/4h/1d). The reversal signals are not an
  artefact of searching 24 features: on noise the best of the screen reaches |t| 3.1–3.2
  (directional) and 3.9–4.3 (relative), the real ones sit at 4.4–17.8, and no shuffle out of 200
  matched them (relative 1d: 2 of 200). Two corrections to read #3 with: the **relative t-statistics
  are overstated by ~1.4×** (their spread on noise is 1.4, not 1; directional is calibrated at
  1.0), and about **a quarter of the directional forecast's IC is drift** — the fitted intercept
  betting that the market's average direction continues (0.006 of 0.028 at 1h, 0.010 of 0.035 at 4h).
- **#5 Learning curves** (ridge vs a depth-2 boosted tree, trained on the last 30 / 60 / 120 / 250
  days or on everything before the fold; 4h and 1d). Three readings. *More history does not help —
  it hurts*: directional 4h scores IC 0.052–0.057 on the last 30–120 days against 0.035 on all
  ~500, and directional 1d 0.06–0.08 against 0.012; the relation drifts, so the lever is **short,
  frequent refits, not more data** (decision table row 4). *The tree never beats the line*: equal
  at best, worse by t −3 to −5 on short windows, while fitting its training window two to three
  times better — no interactions evidenced, so nothing beyond linear is funded (§7). *Extra
  sources are a wash*: all 24 features against the 11 candle ones is +0.008 at 4h on all history
  and −0.01 on short windows; only directional 1d on all history improves (0.012 → 0.050, t 3.4),
  one cell out of many, recorded and not acted on.

**Why the relative bet is not funded although its single features are real.** At 4h the reversal
features pass the noise floor (IC 0.024–0.030) but sit below the bar except as maker + timing, and
neither model fitted on them reproduces any of it out of sample (in-sample IC only 0.014). The
screen measures *ranks* across pairs, the forecast was fitted on raw vol-scaled values, and the
young pairs' tails dominate a least-squares fit; whether a rank rule recovers it is cheap to see
once P3's harness exists, and is parked in §7 with that trigger.

**Defect records.** (1) The first run (2026-09-20 08:38 UTC) computed the directional and vol ICs as
a within-day Spearman and read −0.2 at 1d with t = −16. Feature and label share the price at t,
and demeaning inside the day (which uses the day's future prices) makes them negatively
correlated on a pure random walk (−0.5 for one pair). Voided and re-run the same day with an
uncentred daily correlation; `tests/test_p2.py::test_random_walk_has_no_directional_ic` holds
the statistic at zero on a random walk. (2) #4 was planned as "labels shuffled within day". That
is not a null here: a label moved to a later bar of its own day overlaps the trailing-return
features, and a 4-draw trial read an IC of +0.09 … +0.18 for the ridge from that leak alone.
Replaced before the real run by whole-day shuffles that never hand a day the labels of the 8 days
before it (`_shuffle_days`, with a test); nothing was read from the leaky version.

**What followed:** P3 and P4's stage 1 (below). The work VM is stopped. To re-run the audit: `scripts/ft2.sh --test`,
`vm.sh start`, `vm.sh bg p2 ceiling` (≈ 45 min for all seven items on 4 vCPU), `vm.sh pull`,
`vm.sh stop`. **Watch the job with the log's `wrote ` line, not `pgrep -f "ft2 ceiling"`** — the
ssh command line matches itself, which left the VM idling for five hours on 2026-09-20.

**Deliverable:** one table. Rows = bet type × horizon. Columns = signal ceiling, cost (from P1),
noise floor, detectable effect, sample size, verdict (fund / not detectable / excluded).

Bet types:

| bet type | what is predicted | why it is on the list |
|---|---|---|
| **directional** | sign / size of a pair's own forward return | simplest to execute; weakest, most competed |
| **cross-sectional relative value** | which pairs beat the basket over the horizon | removes the common market factor, the largest and least predictable piece of variance; twelve semi-independent bets per bar; market-neutral by construction. **Prior: highest ceiling on this data** |
| **volatility timing** | forward absolute move | not a strategy on its own; a multiplier on either of the above, measured here so its value is known |

Horizons: 15m, 1h, 4h, 1d on the 5m grid (bars of the coarser grids when it helps).

The audit itself, per target (from the design conversation; each item is a subcommand):

1. **Magnitude vs direction split** — out-of-sample R² of forward |return| vs of signed return
   from trailing volatility and a few candle features.
2. **Raw linear structure** — autocorrelation and variance-ratio tests per horizon; share of
   cross-pair variance in the first principal component (how much is "the market").
3. **Rank information coefficient (IC) screen** — Spearman correlation between each candidate
   feature and the target, per day, averaged with a t-statistic and a rolling plot. Stable
   hundredths = real weak signal; sign that flips monthly = noise or non-stationarity.
4. **Noise floor** — the intended pipeline on labels shuffled within day, walk-forward, many
   times.
5. **Learning curves** — ridge and a depth-2 boosted tree on growing windows: in-sample vs
   out-of-sample gap (variance-dominated?), slope (data-limited?), tree vs linear (interactions
   evidenced?).
6. **Effective sample size and MDE** — from residual autocorrelation and label overlap.
7. **Move vs cost** — share of bars whose absolute forward move exceeds the P1 round-trip
   cost. Bounds usable signal regardless of model.

Reads the exploration folds (F1+F2) only. **Needed from Vadim:** nothing.

### P3 — The harness (✅ built and checked on real data 2026-09-21)

**Result.** `ft2 backtest <strategy>` (`ft2/backtest.py`; its docstring is the specification) → a report,
the decisions, the fills per execution and the shuffles under `output/backtest/<name>/`. Two checks say
the instrument reads true. On synthetic data a planted edge of 30 bps comes back as 30 within its
interval, with taker and maker costs exact to the cent (`tests/test_p3.py`). On the real F1+F2 a coin
(random side, a tenth of the bars, 26,500 trades) comes back at **−12.2 bps as a taker — P1's cost —
and at −7.2 on the simulated maker against −7.4 on P1's day-average maker**: the bar-level fill
simulation and the tape measurement, two independent methods, agree to 0.25 bps.

What was added beyond the plan, and why: **the maker is simulated on the bars** (a limit order rests at
the bar's close for 15 minutes; filled only if a later bar trades through it; otherwise it crosses as a
taker at the price by then). P1's maker number is a day average and cannot know *which* orders fill; for a
rule that buys what is falling, the unfilled orders are exactly the ones that ran away. Both are reported.
Also enforced by the harness, not by the strategy: fits see only labels that ended before their block; a
block is re-run on a market cut off mid-block and any changed decision is refused as reading its future;
a confirmation fold needs a §8 block and is read once per registration
(`output/backtest/confirmation_reads.csv`).

**One known weakness of the noise floor:** whole-day shuffles give a volatility-timed rule the moves of
*average* days, so the shuffles' spread is about half the rule's real day-to-day spread (4.7 vs 8.5 bps on
R1). **Fixed 2026-09-21:** the harness now also runs a *flip* null — the rule's own trades, every day's sides
multiplied by one random sign — and the report's verdict uses the larger of the two p-values. Every fill also
carries the other pairs' move over the same bars (*hedged* gross), and long and short are reported apart.

**Deliverable:** `ft2 backtest` — walk-forward over the folds, the ledger (§3), the cost model
from P1 plugged in, the shuffled-label noise floor, day-clustered intervals with MDE, and a
registration template. Tested by feeding it a strategy with a known planted edge and checking it
is recovered with the right interval.

**Needed from Vadim:** nothing.

### P4 — The dumbest trade generator, through the harness (🟡 stage 1 read 2026-09-21: gate passed; the confirmation read is Vadim's decision)

**Result in plain words** (registration R1, §8; `output/backtest/reversal4h/report.md`). The rule: when a
pair has been unusually volatile for 4 hours and has moved a lot over the last 4 hours to a day, bet on it
giving some back over the next 4 hours. No model, three fixed numbers, written down before it ran. On
F1+F2 (2023-05 → 2024-08) it made **3,404 trades, 7 a day, right 57 % of the time, earning 17.9 bps
before costs and +14.0 bps after them as a maker (+9.7 as a taker)** — on a 10,000 USDT position that is
+14 USDT a trade, about +100 USDT a day with up to eleven positions open. Not one of 200 shuffles came
close (p 0.005), so the registered gate passed.

**Can it trade profitably? Still not shown — three cautions, in order of weight:**

1. **The error bar is ±17 bps.** The interval is [−2.7, +30.8]: trades bunch on volatile days (a third of
   them fall on a tenth of the days; the best ten days are more than the whole profit and the worst ten
   cancel them), so 3,400 trades are worth far fewer independent bets. The smallest edge this sample could
   have proven is 24 bps; the rule's is 14.
2. **All of the profit is on the long side: longs +51 bps, shorts −19.** F1+F2 was a rising market, so
   part of this is "buy the dip in a bull market", which is a bet on the market, not a skill. P2 had
   flagged that a quarter of the signal was drift; in the traded tail it is more. **Measured in P5 step 1: it is not drift
   but a bounce of the whole market after a fall — and against the other pairs the rule's picks lose.**
3. **The stricter null gives p 0.03, not 0.005** (P3 "known weakness").

**Why F3 was not read although the gate passed.** R1's stage 2 reads F3 alone. At this rule's day-to-day
spread, F3's 240 days would confirm a true 14-bps edge only about one time in five — four times in five
the fold would be spent on "not detectable". Deferring a read changes nothing about the registration (no
parameter moves; stage 2 can be run as written at any time), so it is parked in §7 with the choices.

**Deliverable:** a fixed rule with ≤3 parameters for the bet type P2 funds (for relative value:
"long the bottom-decile residual, short the top, hold N bars, size by inverse volatility"), run
walk-forward, with its result, interval, noise floor and MDE. Its purpose is to be the baseline
and to prove the harness, cost model and ledger agree with each other.

Registered as a §8 block before it is run. **Needed from Vadim:** nothing.

### P5 — Forecast + analytic decision (🟡 steps 1–2 read 2026-09-21: the one bet that looked good does not hold up outside the data it was found on)

**Can it trade profitably? Not shown, and the best candidate just got much weaker.** Plain version of where P5 stands
(a bps is 0.01 %; on a 10,000 USDT position 1 bps = 1 USDT; *taker* = crossing the spread, ~12.5 bps a round trip):

- **Step 1 (R2, R3; F1+F2 = 2023-05 → 2024-08).** P4's rule ("fade a volatile pair's move") was taken apart. Its profit was
  not the pair reverting but **the whole market bouncing after a violent fall**: against the other pairs its picks lose
  11.6 bps; its longs earned +51, its shorts −19. The market-neutral version loses outright (−20.6 bps a leg, all six
  quarters; closed), and two ways of smoothing the result made it worse (closed). Two sharper hypotheses came out of it:
  H1 "buy the market after a market-wide panic", H2 "a pair torn away from the others keeps going".
- **Step 2 (R4, R5).** To test them on data that played no part in finding them — without spending a confirmation fold —
  the public archive's 2020–2022 candles were added as a pre-history fold **FP** (DATA.md; nine pairs, identical to the
  collector's bars where they overlap), read together with F0: three years, 2020-05 → 2023-05, a bull market, two crashes
  and the 2022 bear.
  - **H1 (`panic4h`): +39.9 bps a trade where it was found, +7.4 [−16.9, +31.7] where it was not.** Verdict by the
    registered gate: NOT DETECTABLE — and the +40 itself is ruled out (it lies above the interval). By half-year the
    picture is plain: **+6 to +31 net while the market was rising (2020-H2 → 2021), −8 to −12 in every half-year from
    2022-H1 to 2023-H1.** So what F1+F2 showed was "buying dips works in a bull market". The five worst days are the
    cascades (2021-05-19, 2022-05-11 LUNA, 2022-11-08/09 FTX): the first bounce fails and the rule buys again.
  - **H2 (`rankcont4h`): real before costs, eaten by them.** Gross +12.5 bps a leg (hedged +14.2 [+1.8, +26.5]), net −0.2 as
    a taker and +4.9 as a maker — under the +5 bar written beforehand, so FP+F0 was NOT spent on it (it could have
    confirmed a true +5 only one time in ten). Parked with its revival trigger (§7), not closed.
- **What this means for R1** (§7, first row): R1's profit *is* H1's bounce, so the pre-history read is the best evidence
  about it too. Reading F3 for R1 now would very likely spend the fold on "not detectable".
- **What the project gained regardless:** the exploration data grew from 1.3 years (F1+F2) to 4.3 (FP+F0+F1+F2) with
  very different regimes in it, and the harness reads it (`--folds FP F0`, guarded like a confirmation fold: by
  registration, once). Every earlier "found on F1+F2" result can now be checked for regime dependence before a
  confirmation fold is spent on it.

**Next session (Claude; needs nothing from Vadim):**

1. **Re-measure the ceiling for the market factor on all 4.3 years** — P2's audit (#1 magnitude/direction, #3 IC screen, #4
   noise floor) with the target "the equal-weight basket's next 4 hours" and features that the step-2 result points at:
   breadth of the fall, the basket's own trailing 4h/1d/1w/30d return (the trend the bounce seems to depend on), realised
   volatility. Reported **per year**, because the lesson of R4 is that a pooled number hides a sign that changes with
   the regime. `ft2 ceiling` needs a `--target basket` and `--folds` option for this; FP+F0 are now *seen* for H1-like
   rules, so anything found there is a hypothesis, and only F3–F5 can confirm it.
2. **Only if #1 shows a stable IC above the bar in every regime** → the forecast layer below, aimed at the basket, with
   short refits (decision-table row 4). If the sign flips with the regime and nothing predicts the regime, the honest
   conclusion is decision-table row 6 for the directional bet on these twelve names, and the next lever is breadth:
3. **The wider universe (§9 #2) for H2.** H2 is the only effect so far that is market-neutral, has the same sign in both
   exploration folds and survives hedging; it fails on cost with one name a side. Fetch 5m klines for the top ~40 perps
   (same fetcher, `--symbols`), and register the rank rule with 3–5 names a side before reading.

**Deliverable (unchanged):** a forecast of the forward target's distribution (ridge and a shallow boosted
tree, ensembled over seeds and training windows) and a **closed-form** decision layer: trade when
expected value exceeds cost by a margin, size by expected value over variance, capped. No learned
policy. Registered contrast: P5 vs the P4 rule on the confirmation folds.

Why the split and not one end-to-end model: the forecast learns from every bar with a
comparatively clean label; a policy trained on trade profit sees only the bars it acted on,
with execution noise added to the label. That is the wrong direction for a weak-signal problem.

### P6 — Earned capacity (only on a measurement from P5)

Each of these is parked (§7) with the measurement that would fund it:

- **Learned decision layer / end-to-end model** — funded only if a registered contrast shows the
  analytic decision leaves money against an oracle sized on the same forecasts.
- **Book/tape features as inputs** — testable back to 2023-01 (§9 #1); P2 measured them as a wash
  on direction (2026-09-20); revival trigger in §7.
- **Sequence / deep models** — P2 #5 found no interactions (a depth-2 tree never beat ridge);
  revival trigger in §7.

### P7 — Paper trading, then money

Needs a serving path (a process that reads the collector's DB, decides, and records). This is
the only phase that needs an always-on host, and it is months away. Decided when P5 produces a
registered positive on confirmation folds.

## 5. Decision table (what the P2 readings mean for model choice)

| reading | choice |
|---|---|
| IC small but stable, out-of-sample R² well under 1% | ridge or shallow boosted tree, ensembled; the gain comes from breadth |
| magnitude R² high, direction near zero | separate volatility model for sizing; direction model kept minimal |
| learning curve still rising with data | extend data (more history, more pairs) before extending the model |
| IC sign unstable over time | regime detection or shorter refits, not capacity |
| tree clears linear outside the noise floor | keep the tree, add monotone constraints, stop there |
| no bet type clears cost at any horizon | more data or a different market, not a better model — and finding that out in a month is the cheapest outcome this project can have |

## 6. Infrastructure

- **Where things run (decided 2026-09-15):** a dedicated GCP VM, `fluxtrader2-work`, holds
  the data and runs every CPU job. Reason: the MacBook is short on disk, its CPU is shared, and a
  VPN toggle can kill a long download. Spec: `e2-standard-4` (4 vCPU, 16 GB), 200 GB pd-balanced
  disk, Debian 12, zone `me-central1-b` (same as the collector, so exports are VM-to-VM inside the
  region). Sizing reason: the largest frame in P0–P5 is the full-history 1m candles, about 2 GB in
  memory; CPU only matters for the repeated refits in P2/P3, and a resize (stop, change type,
  start; disk persists) takes a minute if a job turns out to be CPU-bound for hours. **Stopped when
  idle**; a stopped VM bills only its disk. Price: the Iowa list price is $0.134/h running; Doha
  is higher and was not verified on 2026-09-15 (the project's Cloud Billing API is disabled) —
  check the console's estimate when creating. Claude starts and stops it with `scripts/vm.sh`.
- **No Docker on the VM.** A plain virtualenv (`~/ft2-venv`) installed by `scripts/vm_setup.sh`,
  which is idempotent and doubles as the reinstall runbook. Reason: nothing to isolate on a
  single-purpose machine, and no image rebuild per dependency change.
- **Docker for anything local.** Quick checks on the MacBook go through `scripts/ft2.sh` and the
  Dockerfile; no host installs, ever (repo rule).
- **Code flow:** edit locally, `vm.sh push` (rsync, excludes data/ and output/), run there,
  `vm.sh pull` brings `output/` back. The VM never pushes to git.
- **Data flow:** `scripts/export.sh` runs *on the work VM* and reads the collector's Postgres
  directly over the VPC (P0 verifies the firewall and falls back to the ssh chain otherwise).
  External archives (§9) download straight to the VM.
- **Always-on host:** not needed before P7 (paper trading); that decision is P7's.
- **Deliberately not first:** any sequence model or deep network; anything trained on the book
  data alone; any reinforcement learning. Each is a capacity increase on a problem whose ceiling
  is not yet known.

## 7. Parked

| item | why parked | revival trigger |
|---|---|---|
| **R1 stage 2 — the confirmation read of `reversal4h`** | **Needed from Vadim: nothing unless you disagree — saying nothing = (a).** Gate passed 2026-09-21, but (a) *recommended, firmly after P5 step 2*: do not read. R1's profit is the market's bounce after a fall (R3), and that bounce, tested on three unseen years, is +7 bps [−17, +32], positive only in rising markets (R4). F3 would be spent on a rule we would not trade. (b) read F3 anyway as registered: `vm.sh start`, `vm.sh run backtest reversal4h --folds F3 --registration R1`, `vm.sh pull`, `vm.sh stop`. (c) amend R1 before any read to pool F3+F4+F5 | Vadim's choice; or P5 "Next session" #1 finds what predicts the regime |
| **H1 panic bounce (`panic4h`, R4)** — NOT DETECTABLE on FP+F0 2026-09-21 | Claude does the next step (P5 "Next session" #1); nothing needed from Vadim. +7.4 bps [−16.9, +31.7] against +39.9 where it was found; sign follows the market's trend. R4 forbids variants on FP+F0 | a registered ceiling read shows a feature that predicts the bounce's sign in every year; the conditional rule is then a NEW registration and only F3–F5 can confirm it |
| **H2 tail continuation (`rankcont4h`, R5)** — PARKED on cost 2026-09-21, FP+F0 unread for it | Claude does the next step (P5 "Next session" #3). Gross +12.5 bps a leg, hedged +14.2 [+1.8, +26.5]; net −0.2 taker / +4.9 maker, under the +5 bar | the wider universe (§9 #2) with 3–5 names a side, or a lower fee tier (VIP 1 / BNB discount takes 1–2 bps off a round trip) |
| learned decision layer / end-to-end model | capacity not yet earned (P6) | registered P5-vs-oracle contrast shows money left on the table |
| book/tape features as model inputs | P2 #3/#5 (2026-09-20): measured, a wash — single features add little on direction; all 24 vs the 11 candle features is ±0.01 IC, except directional 1d on all history (0.012 → 0.050), one cell | P4/P5 funds a 1d directional bet, or a registered contrast shows the 1d cell repeats on a confirmation fold |
| sequence / deep models | P2 #5 (2026-09-20): a depth-2 tree never beats ridge (equal at best, t −3 to −5 on short windows) and the curve falls with more history | a registered contrast in P5 where the tree beats ridge outside the noise floor |
| 1m candles over the full history | 23M rows, not needed for horizons ≥ 15m | P1 or P2 asks for sub-15m horizons |
| ~~relative (pair-vs-basket) *reversal* at 4h~~ — **CLOSED 2026-09-21 (R2)** | the rank rule loses −20.6 bps per leg [−31.7, −9.5] in all six quarters; do not re-open as a reversal bet | none. The opposite sign (tail continuation) is a new hypothesis, H2 in P5, not a revival of this row |
| caps and inverse-vol sizing on `reversal4h` — **CLOSED 2026-09-21 (R3)** | both lower the t; the capped-away trades were the profitable ones | none; R3 forbids further variants of this kind |
| directional 1d with short refits | P2 #5: IC 0.06–0.08 on 30–120-day windows vs 0.012 on all history, but the window was picked after the fact and 485 days resolve only ±0.03 at 1d | P4's 4h result is in: register the 1d twin with the same fixed window |
| paper trading (P7) | nothing to trade yet | P5 registered positive on confirmation folds |
| trade-level maker validation (`ft2 tape --keep-zip` on a ~2-week window; queue position and fill timing at the trade level) | P1's minute-level maker numbers (fill 86–97 %, adverse 1–3 bps) are coarse; refining them changes nothing until a maker path is on the table | P5 chooses a maker execution, or P2's verdict hinges on the 4-bps taker-vs-maker difference |

## 8. Registrations

### R1 — reversal4h, the P4 baseline rule (registered 2026-09-21, before the rule saw any real bar; stage 1 read —, stage 2 read —)
Question:      Does the bet P2 funded — a pair's own next-4-hour move, by reversal, only when the pair is
               volatile — make money after costs as a fixed rule with no model?
Rule:          `ft2/rules.py::Reversal`, parameters fixed here and not searched: q_vol 0.90 (trade only when the
               last 4 hours' volatility is in the pair's top tenth), q_sig 0.80 (and the reversal signal
               −½(z_4h + z_1d) is in its top fifth by size), window 120 days (both cuts from the 120 days before
               each 30-day block). Hold 48 bars, one unit, one position per pair, executed 1 bar after the decision.
               Why 0.80: at P2's IC of ~0.045 a signal pays its maker round trip from about |z| ≈ 1.2 in volatile
               bars — roughly the top fifth; chosen from that arithmetic, not from a run.
Contrast:      the rule's mean net bps per unit of notional vs zero, and vs its own noise floor (200 whole-day
               shuffles). Primary execution: `maker` (simulated on the bars). `taker` and `maker_ev` are reported,
               never used to pass a gate.
Folds read:    stage 1: F1+F2 (exploration — P2 chose the bet on these folds, so this stage is a gate, not evidence).
               stage 2: F3 only, once. F4 and F5 stay unread for P5's contrast.
Gate:          stage 1 passes if maker net > 0 (point estimate) AND noise-floor p ≤ 0.05. Fail → F3 is NOT read;
               the rule stays as P5's baseline and the miss is diagnosed on F1+F2 only. Pass → stage 2:
               `ft2 backtest reversal4h --folds F3 --registration R1`. Stage 2 verdicts: CONFIRMED if the maker
               interval's lower bound > 0; REFUTED if its upper bound < 0; otherwise NOT DETECTABLE, with the MDE.
               No parameter is changed between the stages.
Expectation:   Gross +8 to +15 bps per trade, a few trades a day. Maker net between −2 and +5, with an MDE of
               roughly 5–8 — so the likeliest stage-1 outcome is a small positive that does not clear its own
               noise, i.e. a FAIL on p. Taker net negative. A clear pass would be a surprise worth distrusting
               (check the fill simulation first).
Result:        **Stage 1, read 2026-09-21 (commit 1393fe7 holds this block as written before the read): GATE PASSED.**
               maker net +14.03 bps [−2.69, +30.75], MDE 23.9, 3,404 trades / 485 days, gross +17.91, p = 0.005
               (0 of 200 shuffles; shuffle mean −5.89 ± 4.74). taker +9.74 [−6.72, +26.20]; maker_ev +14.07.
               F1 +14.98, F2 +13.07; ten of eleven pairs positive gross. Against the expectation: gross was higher
               than expected (17.9 vs 8–15) and the MDE three times larger (24 vs 5–8) — the expectation ignored that
               trades bunch on volatile days. The promised distrust check: both maker versions agree (14.03 / 14.07)
               and the coin calibrates, so the fill simulation is not the source. Diagnostics, not gates: longs +51.4,
               shorts −18.8; a day-level side-flip null gives p = 0.031.
               **Stage 2: not read.** Power on F3 alone ≈ 20 % for a true +14 (se ≈ 12 on 243 days). Parked in §7;
               runnable unchanged.

### R2 — rank4h, the pair-vs-basket bet as a rank rule (registered 2026-09-21, before the rule saw any real bar; read —)
Question:      P2 found real single-feature reversal in a pair's move RELATIVE to the other pairs at 4h (IC 0.024–0.030)
               that no fitted forecast reproduced. Does a rank rule — which needs no fit — turn it into money after costs?
               It is market-neutral by construction, so it cannot be "buying dips in a rising market" (R1's main caution).
Rule:          `ft2/rules.py::RankReversal`, parameters fixed here and not searched: at each bar, x = a pair's
               vol-standardised last-4h return minus the all-pair mean; long the lowest x, short the highest, one unit
               each, both legs or neither (the harness's `group`), hold 48 bars; only when the gap between the two is
               at least its q_disp = 0.90 quantile over the 120 days before each 30-day block. Why 0.90 and one name a
               side: with eleven names "the bottom decile" is one name, and at P2's IC of ~0.03 a leg pays its maker round
               trip only at |x| ≈ 3 in dispersed (= volatile) bars — about the widest tenth of gaps. Arithmetic, not a run.
Contrast:      mean net bps per unit of notional (per leg) vs zero and vs both nulls. Primary execution: `maker`.
Folds read:    F1+F2 only. No confirmation fold is read by this registration.
Gate:          PASS if maker net > 0 AND the larger of the shuffle p and the flip p ≤ 0.05 → the relative bet at 4h becomes
               a funded arm of P5 next to the directional one. Otherwise: if the interval's upper bound is below +3 bps
               (nothing worth a round trip is left) → the relative bet on twelve names is CLOSED; else NOT DETECTABLE —
               it stays parked, and its revival trigger becomes a wider universe (§9 #2), where a decile is 3–5 names.
               No parameter is changed after the read.
Expectation:   Gross +4 to +10 bps per leg, 4–10 legs a day, maker net between −3 and +3, MDE 6–10: the likeliest
               outcome is NOT DETECTABLE. Hedged gross ≈ gross (that is what neutral means); long ≈ short.
Result:        **Read 2026-09-21 (commit b842d64 holds this block as written before the read): FAIL → CLOSED.**
               maker net −20.58 bps per leg [−31.69, −9.48], MDE 15.9, 1,780 legs / 485 days (3.7 a day), gross −16.30,
               hedged −17.62 [−29.86, −5.38]; shuffle p 0.995, flip p 1.000 (i.e. in the LEFT tail of both). taker −25.16.
               F1 −24.4, F2 −15.6; gross negative in 6 of 6 quarters and on 8 of 11 pairs (PEPE −87, DOGE +48).
               Upper bound < +3 → closed as a reversal bet. Against the expectation: the sign. The tail continues; it does
               not revert. Recorded as hypothesis H2 (P5), to be registered on its own before any read.

### R3 — P5 step 1: cut reversal4h's day-to-day spread (registered 2026-09-21, before any variant ran; read —)
Question:      R1 earns +14 bps with a standard error of 8.5 because its trades bunch on a few violent days. Do two
               mechanical changes — neither touches the signal — make the same edge more certain?
Variants:      `reversal4h` with R1's three numbers unchanged, plus (A) `size=invvol`: vol_cut / v units, floored at 0.25;
               (B) `max_side=3`: at most three positions open at once on one side; (C) both. Why 3: a third of R1's trades
               fall on a tenth of the days (~23 a day there, against 7 on average) — a cap of 3 of 11 leaves ordinary days
               untouched and turns a market-wide fall into three bets, not eleven. Chosen from that, not from a run.
               Baseline: R1 re-run unchanged on the same folds (adds long/short, hedged gross and the flip p; its
               decisions and its +14.03 must reproduce exactly, or the run is void).
Contrast:      maker net ÷ its day-clustered standard error (t), variant vs baseline (R1: 14.03 / 8.53 = 1.64), F1+F2.
Folds read:    F1+F2 only.
Gate:          The candidate for the ONE confirmation read is the variant with the highest t, if it beats the baseline's t
               by ≥ 0.3 (picking the best of three correlated variants is worth about that much by luck), its maker net
               is ≥ +7 bps and its flip p ≤ 0.05. Otherwise R1 stays the candidate. Either way the confirmation read is
               registered separately, with its power computed from the winner's standard error BEFORE the read.
               No other variant, cap or floor is tried after this read.
Expectation:   (A) net a little lower (the most violent bars are the most profitable per unit), se −15 to −25 %, t ≈ 1.8.
               (B) ~2,000 trades, net about unchanged, se −25 to −35 %, t ≈ 2.1–2.4. (C) the best, t ≈ 2.3–2.6.
               Hedged gross of the baseline: about half of gross (the rest is the market bouncing).
Result:        **Read 2026-09-21 (commit b842d64): no variant passes; R1 stays the candidate.** Baseline reproduced exactly
               (3,404 trades, +14.03, se 8.53, t 1.64; flip p 0.025). (A) invvol +11.34, se 9.23, t 1.23. (B) cap 3: 2,359
               trades, −6.88, se 7.43, t −0.93. (C) both: −7.30, se 7.65, t −0.95. Every expectation was wrong, for one
               reason: baseline hedged gross is −11.64 [−19.13, −4.15], not "half of gross" — all of the profit and more is
               the market's bounce (other pairs +66 bps over the longs' four hours), and it is largest exactly when many
               pairs fall together, which is what (A) shrinks and (B) removes (the 1,045 capped trades had earned +61 each;
               days with ≥ 8 same-side trades: +4 a trade, the rest +36 — the first entries into a fall lose, the later
               ones win). Longs +51.4 [25.1, 77.7], positive in 6 of 6 quarters; shorts −18.8, negative in 5 of 6.

### R4 — panic4h, hypothesis H1: buy the market after a market-wide fall (registered 2026-09-21, before the rule saw any real bar; stage 1 read —, stage 2 read —)
Question:      R1's profit turned out to be the whole market bouncing after a violent fall (R3's result). Stated as its own
               rule — long only, triggered by how many pairs are falling at once, buying the market rather than the fallen
               pairs — does it make money after costs on data that played no part in finding it?
Rule:          `ft2/rules.py::Panic`. A pair is FALLING at a bar when R1 would buy it (R1's v, s, q_vol 0.90, q_sig 0.80,
               120-day cuts — unchanged). When at least a third of the pairs that have cuts were falling at some bar of the
               last 48 (11 pairs: 4; 9: 3; 6: 2), go long EVERY such pair, one unit each, hold 48 bars, one position per pair,
               executed 1 bar later. Where the two free choices come from — both from R1's fills on F1+F2, which is why
               F1+F2 is not evidence: (a) *a third*: R1's longs entered while ≥ 4 of 11 pairs had fired in the last 4 hours
               saw the other pairs rise +90 bps over the hold, those entered with 1–3 saw +20 (1,055 vs 535 trades);
               (b) *the basket, not the fallen pairs*: hedged, R1's picks lose 11.6 bps to the others. No other value was tried.
Contrast:      mean net bps per unit of notional vs zero and vs both nulls (the shuffle null is what removes "long in a
               rising market": it holds the same long positions on other days). Primary execution: `taker` — the edge, if it
               exists, is several times the cost, and before 2023 the spread is a candle proxy (`ft2 costpre`), so the
               execution that depends least on simulation decides. `maker` is reported. Sensitivity reported with the
               result: spread + impact doubled (= taker net − other_cost).
Folds read:    stage 1: F1+F2 — a mechanical gate (costs, fills, trade count), NOT evidence.
               stage 2: FP+F0 (2020-05-01 → 2023-05-01; archive klines under the collector's; 5 → 9 pairs), once:
               `ft2 backtest panic4h --folds FP F0 --registration R4 --execs taker maker`. F3–F5 are not read.
Gate:          stage 1 passes if taker net > 0 AND the larger p ≤ 0.05; fail → stage 2 is not read and H1 is closed as an
               artefact of how R1's trades were sliced. Before stage 2 runs, its power is written here from stage 1's
               standard error. Stage 2: SUPPORTED if the taker interval's lower bound > 0 AND the larger p ≤ 0.05 → H1
               becomes the candidate for the one confirmation read (replacing R1 in §7's first row) and the market factor
               becomes P5's forecast target. REFUTED if the upper bound < 0 → closed. Otherwise NOT DETECTABLE, with the MDE;
               it stays parked, no variant is tried on FP+F0. No parameter changes between the stages.
Expectation:   Stage 1: gross +50 to +90 bps, 3–6 trades a day bunched on ~120 days, taker net +40 to +80, se ≈ 20, passes.
               Stage 2: positive but much smaller — gross +15 to +45, taker net +5 to +35. 2021-05, 2022-05 and 2022-06 were
               cascades in which the first bounce failed, and the rule was found in a rising market. With se ≈ 15 the
               likeliest verdict is NOT DETECTABLE, SUPPORTED second.
Power:         Written 2026-09-21 after stage 1, before stage 2. Stage 1's taker se is 10.65 on 485 days. FP+F0 has ~1,090
               scored days and 2020–22 moved about 1.4× as much as 2023–24, so se ≈ 10.65 × √(485/1090) × 1.4 ≈ 10 and the
               MDE ≈ 28 bps. A true edge equal to stage 1's (+40) would be SUPPORTED about 98 times in 100; half of it (+20)
               about 1 time in 2; +28 four times in five. So SUPPORTED and REFUTED are both informative; NOT DETECTABLE
               would mean "smaller than about +28, if it exists" — and is NOT a reason to close.
Result:        **Stage 1, read 2026-09-21 (commit b33449e holds this block as written before the read): GATE PASSED.**
               taker net +39.87 bps [+19.00, +60.75], se 10.65, MDE 29.8, 3,249 trades / 485 days (6.7 a day), right 61.6 %,
               gross +52.68, shuffle p 0.005 (null −8.45 ± 7.23), flip p 0.005. maker +45.71 [+24.79, +66.62]. F1 +22.2,
               F2 +57.0. Spread + impact doubled: +37.6. Against the expectation: inside it (gross 53 vs 50–90), the se half
               of what was guessed (10.7 vs 20). R1 re-run on the changed harness first: +14.03 / +9.74, identical.
               **Stage 2, read 2026-09-21 on FP+F0 (commit 4857796 holds the block and the power as written before the read):
               NOT DETECTABLE.** taker net +7.38 bps [−16.91, +31.66], se 12.4, MDE 34.7, 5,244 trades / 1,093 days (4.8 a
               day on 258 days), right 56.9 %, gross +19.82; shuffle p 0.035, flip p 0.070 → larger p > 0.05. maker +11.71
               [−12.35, +35.77]. FP +11.5, F0 −9.6. Spread + impact doubled: +4.7. Stage 1's +39.9 lies outside the
               interval. Against the expectation: inside it (gross 15–45, net 5–35, "likeliest NOT DETECTABLE"); the se was
               12.4, not 10, so the MDE is 35, not 28. Diagnostic, not a gate — net by half-year: 2020-H2 +6, 2021-H1 +31,
               2021-H2 +23, 2022-H1 −12, 2022-H2 −9, 2023-H1 −8: positive only while the market was rising. Per the gate:
               parked (§7), no variant is tried on FP+F0.

### R5 — rankcont4h, hypothesis H2: a pair torn away from the others keeps going (registered 2026-09-21, before the rule saw any real bar; stage 1 read —, stage 2 read —)
Question:      R2 lost 16.3 bps gross per leg in all six quarters, i.e. its mirror image earns that before costs. Is it more
               than a round trip costs, and does it exist outside the data it was found on?
Rule:          `ft2/rules.py::RankContinuation` = R2's rule with the sides swapped, nothing else touched (q_disp 0.90,
               120 days, hold 48, both legs or neither): long the pair furthest ABOVE the others over 4 hours, short the
               one furthest below.
Contrast:      mean net bps per leg vs zero and vs both nulls; `taker` and `maker` both reported. A resting order that
               chases a move is filled when the move stalls, so which execution is better is not known in advance: the
               primary execution is the better of the two by stage 1's point estimate, fixed for stage 2.
Folds read:    stage 1: F1+F2 — by construction the gross is R2's with the sign flipped; what is new is the cost side.
               stage 2: FP+F0, once: `ft2 backtest rankcont4h --folds FP F0 --registration R5 --execs taker maker`.
Gate:          stage 1 → stage 2 only if the primary net ≥ +5 bps per leg. Below that the honest read could not see it:
               R2's se was 5.7 on 485 days, so FP+F0's ~1,090 days give se ≈ 4–5 and an MDE ≈ 12–14 — a true +3 would be
               confirmed about one time in ten. In that case H2 is PARKED, not closed ("real before costs, not tradable at
               VIP 0 fees on twelve names"), revival: a lower fee tier, or a wider universe (§9 #2) where the tails are
               3–5 names a side. Stage 2 verdicts as in R4. No parameter changes between the stages.
Expectation:   Stage 1: taker gross ≈ +13, net between −2 and +4; maker about the same or worse (adverse fills). The
               likeliest outcome is below +5 → parked without reading FP+F0.
Result:        **Stage 1, read 2026-09-21 (commit b33449e): primary = maker, +4.92 bps per leg [−6.33, +16.16] — below the +5 bar
               (by 0.08; the bar was written first, so it holds) → PARKED, FP+F0 NOT read.** taker −0.20 [−11.27, +10.88],
               gross +12.50 (taker prices) / +9.22 (maker: the chasing order does get the worse fills, −3.3), hedged +14.15
               [+1.83, +26.47]; 1,777 legs, 3.7 a day; F1 +8.8, F2 −0.1 (maker). All of it is the long leg (the pair torn
               UPWARDS keeps going: +20.7 gross; the one torn downwards: +4.3). As expected. The effect is real before
               costs and the size of one round trip: not tradable at VIP 0 on twelve names. Revival in §7.

### R6 — the market factor's ceiling on 4.3 years, per year (registered 2026-09-21, before the audit saw any real bar; read 2026-09-21)
Question:      R4 says the market's bounce after a fall has a sign that follows the regime. Is there ANY feature, or a
               short-refit forecast, that predicts the equal-weight basket's next 4 hours with one sign in every year
               2020 → 2024 and at a size that pays a round trip?
Audit:         `ft2/market.py` (its docstring is the specification), `ft2 ceiling --target basket --folds FP F0 F1 F2`.
               17 features fixed here: the basket's trailing return over 1h/4h/1d/1w/30d; breadth of the fall and of the
               rise (share of pairs ±1σ over 4h), dispersion; three volatility ratios; dollar-volume surprise; mean
               funding; and the four interactions R4 points at (−4h return × sign of the 30d / 1w trend, the fall alone,
               the fall × 30d trend). Null: 200 circular shifts of the labels (day shuffles would flatter slow features).
               Forecast: ridge without intercept, refitted every 30 days on the last 120 days (the gate's window; 365
               and all are reported). IC = whole-sample correlation with a day-clustered t (the per-day statistic P2
               used is biased on random walks — found while testing this module; R7).
Folds read:    FP+F0+F1+F2, all already seen for H1-like rules: whatever is found is a HYPOTHESIS, confirmable only on F3–F5.
Gate:          FUND a basket forecast (P5's deliverable, aimed at the market) if the 120-day ridge at 4h has one-sided
               shift p ≤ 0.05 AND a positive IC in each of the five calendar years AND a pooled IC ≥ the smaller of the
               two bars "maker, all bars" and "taker, most volatile tenth of bars". A single feature with family-wise
               p ≤ 0.05 AND one sign in all five years is recorded as a hypothesis for a new registration (this is
               H1's revival trigger in §7 if it is one of the interactions). Neither → the directional/market bet on
               these twelve names gets decision-table row 6, and the next step is the wider universe for H2.
Expectation:   Pooled, the 4h and 1d trailing returns show reversal (IC −0.01 to −0.03) that is strongest in 2020–21 and
               2023–24 and near zero or positive in 2022; the trend interactions are a little better pooled (+0.01 to
               +0.03) but still fail 2022. Ridge IC +0.00 to +0.02, positive in 3–4 of 5 years. Volatility features
               predict |move| with IC > 0.2 in every year. Likeliest verdict: NOT FUNDED, no regime-stable feature.
Result:        **Read 2026-09-21 (commit 237240a holds this block as written before the read; `output/market.md`): forecast NOT
               FUNDED; one regime-stable feature recorded as a hypothesis.** 1,578 days, 6–11 pairs. The bar at 4h: IC 0.034
               (maker, all bars; = taker on the most volatile tenth); buying the basket costs 12.8 bps a round trip as a taker.
               Ridge 120 d: IC +0.015, p 0.14, 2022 negative (−0.029) → fails all three conditions. Reported, not the gate:
               365 d +0.023 (p 0.015, 2022 −0.001); all history +0.030 (p 0.005), positive in 5 of 5 years (+0.021 … +0.054) —
               the opposite of P2 #5's "short refits are better", which was read with the biased statistic (R7).
               Screen at 4h: ONE feature has p_fw ≤ 0.05 and one sign in every year — `fall_x_trend30d` (the size of the
               basket's 4h fall, signed by the 30-day trend): IC +0.032, t 3.4, p_fw 0.015; by year +0.009, +0.053, +0.032,
               +0.035, +0.024; also first at 1d (+0.051, p_fw 0.035, 5 of 5) and 5 of 5 at 1h. The 30-day trend itself
               (`mret_30d`) +0.030, 5 of 5 years, p_fw 0.075. Plain reversal is NOT there: `mret_4h` −0.007 (p 0.47),
               `mret_1d` −0.004, signs mixed by year; the fall alone flips in 2022 (+0.040 against −0.02 … −0.07).
               Money view, gross bps over the next 4 h after a ≥ 2σ 4h fall of the basket: 30-day trend UP +54.3 (t 4.7;
               by year +19, +132, +3, +58, +29; 306 days), trend DOWN +5.5 (t 0.4; 2022 −9.9). Broad fall: up +32.4 (t 3.9,
               2022 −15.9), down −0.4. Every bar: up +5.6 (t 2.3), down −2.2. |move|: volatility ratios IC 0.16–0.24 in
               every year. Against the expectation: the ridge and the verdict as expected; NOT expected — no pooled
               reversal at all, and an interaction that holds its sign through 2022 (there it is ≈ 0 in money, not negative).
               Per the gate: H1's revival trigger (§7) is met → a NEW registration for the conditional rule; this read is
               on seen data and is a hypothesis only.

### R7 — P2's directional numbers re-read with an unbiased IC (registered 2026-09-21, before the re-run; read —)
Question:      P2's directional and vol ICs were means of per-day correlations. On correlated random walks that statistic
               reads −0.02 to −0.03 for a trailing return at 4h (`tests/test_p5_market.py`), and P2's day-shuffle null
               cannot show it (a shuffle breaks the within-day link that causes it). P2's funded signal was "reversal,
               IC 0.045 at 4h". How much of it is left when the statistic is the whole-sample correlation?
Re-run:        `ft2 ceiling` unchanged except `_ic_pooled` (now each day's share of the whole-sample correlation); all
               seven items, F1+F2 as before. The relative bet's statistic (Spearman across pairs per bar) is not
               affected and must reproduce. The first report is kept as `output/ceiling_2026-09-20_biased.md`.
Gate:          Directional 4h stays FUNDED only if its best single feature clears the screen's family-wise bar
               (p_fw ≤ 0.05) AND the walk-forward ridge is real (p ≤ 0.05) AND the ridge's IC is ≥ the "maker + vol
               timing" bar (0.015). Otherwise P2's verdict for it becomes "not funded", P2's table is rewritten (the
               old numbers deleted, the defect recorded), and R1's premise is marked as withdrawn.
Expectation:   The 4h reversal ICs fall from 0.043–0.045 to 0.015–0.025, still above the noise floor; the ridge from
               0.035 to 0.01–0.02 — at or under the bar. 1h similar in proportion. Vol ICs barely move (|move| and
               volatility share no price). Likeliest verdict: real but NOT FUNDED — which is what R1's hedged loss
               and R4's pre-history read already say in money.
Result:        —

### R8 — trendfall4h: buy the market's fall only while its 30-day trend is up (registered 2026-09-21, before the rule saw any real bar; stage 1 read —, stage 2 read —)
Question:      R6's one regime-stable feature, stated as a rule: does it make money after costs through the harness, in
               every year — and is a confirmation read on F3–F5 worth spending?
Rule:          `ft2/rules.py::TrendFall`, both numbers are R6's money view, written before R6 was read and not searched:
               the basket fell ≥ 2 of its own 4h sigmas AND its 30-day return is positive → long every pair, one unit,
               48 bars, one position per pair, executed 1 bar later. No fit.
Contrast:      mean net bps per unit of notional vs zero and vs both nulls; primary execution `taker` (as R4, and for
               R4's reasons); `maker` and spread + impact doubled reported. Per calendar year.
Folds read:    stage 1: FP+F0+F1+F2 — ALL SEEN by R6, which chose the rule: a mechanical gate (costs, fills, the book
               rule's effect, the day-clustered se), NOT evidence.
               `ft2 backtest trendfall4h --folds FP F0 F1 F2 --registration R8 --execs taker maker`
               stage 2: confirmation folds, once. WHICH folds (F3 alone, or F3+F4+F5 pooled) is decided from stage 1's
               se and written here as "Power" before the read; pooling all three spends every confirmation fold
               this project has on one rule, so that choice is Vadim's.
Gate:          stage 1 passes if taker net > 0 AND the larger p ≤ 0.05 AND taker net ≥ −5 bps in each calendar year with
               ≥ 30 trade-days (the point of the rule is that it does not lose in a bear market; a year at −10 means the
               harness disagrees with the money view). Fail → parked with H1, no variant tried. Stage 2: CONFIRMED if
               the taker interval's lower bound > 0 AND the larger p ≤ 0.05; REFUTED if the upper bound < 0; else NOT
               DETECTABLE with the MDE. No parameter changes between the stages.
Expectation:   Stage 1: gross +40 to +55 (the money view's +54 is per bar in the state; the book rule takes the first
               bar of each 4 hours, which R3 showed is the WORST entry into a fall), taker net +25 to +40, se 9–12,
               2–3 trades a day on ~300 days, 2022 between −10 and +5 → passes, or fails on 2022. Stage-2 power will
               be poor on F3 alone (se ≈ 25–30) and fair pooled (se ≈ 15).
Result:        —

Template:

```
### R<n> — <name> (registered <date>, read <date or —>)
Question:      …
Contrast:      A vs B, per <trade | unit notional>, bps
Folds read:    …
Gate:          … (and what happens on pass / fail)
Expectation:   …
Result:        — (filled once, after the read; interval, MDE, verdict)
```

## 9. Data we could add (Vadim's offer, 2026-09-15: "we can download/build whatever possible")

Ranked by what it unlocks. Indicators are *not* on this list: anything computed from candles is
built here in P2 and needs no download.

| # | data | source | what it unlocks | phase |
|---|---|---|---|---|
| 1 | **Historical book depth, tape and flow for the same twelve pairs** | Binance's public archive (`data.binance.vision`, USDⓈ-M futures; free, no key). **Coverage measured 2026-09-15:** depth within ±1..5 % of mid (`bookDepth`, 30 s) **2023-01-01 → today** for every pair (from listing for the younger ones), ~0.5 MB/day/pair; 5m open interest + long/short + taker ratios (`metrics`) 2020-09 → today; the full tape (`aggTrades`) 2019-12 → today, **~136 GB zipped for our pairs from 2023-01** (BTC 14–27 MB/day); funding monthly since 2020. Best bid/ask (`bookTicker`) was discontinued in 2024 and **`bookDepth` does not replace it** (no touch prices in it) — the historical spread is estimated from the tape's bid–ask bounce. 1m klines back to 2019-12 (2.7 years more than the collector holds). | The single biggest gap in our data was that book, tape and flow existed for two months while candles existed for four years. This closes it back to 2023-01: P1's cost model is measured over 3.7 years instead of proxied, and book/flow features (§7) become testable in a powered walk-forward over F1–F5. **Done in P0b** (`bookDepth`, `metrics`, `fundingRate` ingested; DATA.md); the tape is streamed to a per-minute summary in P1 (`ft2 tape`, not kept raw). | P0b ✅ → P1, P2 |
| 2 | **Candles for a wider universe** (the top ~30–50 USDⓈ-M perps by volume, 5m and 1h) | same archive | Breadth: the plan's edge comes from many semi-independent bets, and a cross-sectional strategy on twelve names is thin. More names also gives a cleaner "market" factor. The collector need not record them for research; only for trading later. | P2 (ceiling audit on 12 vs 40) |
| 3 | **Spot klines for the same symbols** | same archive (spot) | Basis (perp minus spot) and its changes, a known carry/flow signal; also a cleaner index for the market factor | P2 |
| 4 | **Same pairs on a second venue** (Bybit / OKX perps, 1m klines) | their public archives | Cross-venue lead-lag at short horizons; only relevant if P2 funds a sub-15m horizon | parked |
| 5 | On-chain, news, sentiment | various | Low prior at these horizons, high engineering cost; not now | parked |

Rule for adding any of them: a raw download lands under `data/raw/external/<source>/`, is
ingested by `ft2 ingest` into its own parquet, and gets a row in DATA.md with its measured
extent and its integrity check before any phase reads it.
