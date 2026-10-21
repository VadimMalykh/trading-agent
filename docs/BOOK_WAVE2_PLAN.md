# Book wave 2 — three designs the B-wave did not try

**Status (2026-10-21, evening): §M2 BUILT on Vadim's "build M2" — the maker path in the executor, pilot arm only, off until `LIVE_PILOT_MAKER_PATH=true`; the leg columns, the engine's `close_resting`, `flux.testnet_smoke --maker`, the harness's `makerpath live` read (S2 at 100 / 200); tests green (167 + 18 Elixir, 5 harness); NOT DEPLOYED — needed from Vadim: the testnet smoke with `--maker` (prerequisite 2), then "Deploy" (§M2 Built block). Earlier status (2026-10-21, 15:02 UTC): the clock fix (A+B) DEPLOYED on Vadim's "push and deploy" — boundary 2026-10-21 15:02:33 UTC in M3_5 §4.5 and `forward.BAR_KEY_CHANGE_UTC`; same-day acceptance in §4.5's deploy record (stamps present, settle 40 s and the 15 s poll live, rows 79 … 224 s after the scored close against 337 … 469 before — the registered 40–160 s missed at the top by the serial inference cycle, named, nothing licensed; the first closes and the first trades' latency still to read). M2's prerequisite 1 is met on those terms; needed from Vadim: "build M2". Earlier status (2026-10-21, night): the clock fix (A+B) BUILT on Vadim's "Ok, go A plus B" and registered as M3_5_INTEGRATION §4.5 — the row and the exit keyed on the served bar; B's premise corrected (the candle poll's period is 62–90 s, not 60: a 15 s 5m-only collector poll + a 40 s settle instead of 65–70 s); tests green; NOT DEPLOYED (Vadim's "Deploy"). M2's prerequisite 1 is then the deploy and its acceptance. Earlier status (2026-10-21, evening): the 7-minute clock INVESTIGATED (§M1 Result, last block — the server scores the last settled bar, `predict.ex` stamps wall-clock time, the engine floors it; options A/B/C for Vadim, A+B recommended) and §M2 REGISTERED on Vadim's "2 - yes" — the maker path in the executor, pilot arm only, not built, prerequisite the clock decision. Earlier status (2026-10-21): §M1 BUILT and READ — WORTH BUILDING, on the quoted leg alone: S1 = maker path − taker = +3.14 bps net per trade [+1.47, +4.81] on 339 of the policy's own trades (2026-08-05 → 09-09, the ladder era), the forward ledger's policy arm +1.25 [−3.09, +5.59] the same sign; the prerequisite FAILED on every pair (a ladder sampled every ~9 s cannot meet a one-tick bar where the tick is 0.01–0.5 bps — the two sources agree at the same instant, the gap is sampling age, not a clock offset), so the tape leg's +3.07 [+2.60, +3.55] on 2,168 trades is descriptive. Fills 84–86 % (not below M3-4's range as expected); the saving sits on the EXIT (+2.5), the entry gives its fee saving back to the chase (+0.6). Licensed and not done: WRITING a pilot-only maker-path registration — Vadim's call. Beside it, a serving finding the pin surfaced: the ledger books the close of the bar that closed 5 min BEFORE its bar_ts and the order goes out ≈ 7 min after that price (M3_5 §5 row 4 said ~30 s). Result block in §M1. Earlier status (2026-10-20): §K1 READ — VOID at its prerequisite, 2026-10-20, before either population was touched: the harness replays X7 exactly (670 trades, +13.46), but the archive's three-ingredient composite is NOT X7's key on the book era — Spearman 0.51 against the bar 0.80, the same ladder rung on 44.6 % of the 670 trades against 70 % (within one rung 79.0 % against 95 %). Nothing changes anywhere; X7's confirmation stays on 2027-03-10 as §R.4 registered it (result block in §K1). Earlier status (2026-10-19): two new registrations appended — §K1 (X7's ladder key read on archive history) and §M1 (the maker path on the policy's own entries), both before any code, on Vadim's "let's go with 1 and 2"; the archive's `bookTicker` ends 2024-03-30, which shapes both. Earlier status (2026-10-12): option 2 DEPLOYED 02:17 UTC — the collector fetches 500 levels and writes the archive-style bands and reach (±0.2 % now on 10 pairs, ±1 % on 8; BTC still out of reach). ⚠️ 2026-10-14: the weight arithmetic in §L1 left out the tape sweep (weight 20 a call, 600–1,440 a minute); the loop crossed 2,400 in the busy hours and the IP was banned twice on 2026-10-13 (holes 07:26–09:40 and 14:00–18:00 UTC in book and tape) — fixed by a rate-limit guard, BACKLOG "collector / data quality"; L1 READ (the ladder reaches ±0.2 % on 8 pairs, ±1 % on 3; the archive band is the same number with stale stretches — collector decision for Vadim in §L1); E1 READ — gate not passed, with a side-finding registered forward (§E1); D1 READ 2026-10-15 — gate not passed (best of 36 cells `dimb_5` @ 60 m, +3.48 bps raw against +5), book dynamics on the scalar snapshots closed (§D1). ⚠️ 2026-10-15: X8c's identity on the live ±0.2 % columns FAILED by the registered bar on every pair-side (medians 5–9 %; the series agree at ratio 0.997–1.003, the bar is below the band's own ten-second change, the archive stamp ~15 s behind the book) — X8c VOID before any run, decision for Vadim in NEXT_TRAINING_PLAN §2 X8c.** Written after Vadim's "go ahead with 1 and 3"
on 2026-10-11, before any number below exists. Order: **L1** (ladder span, archive band
identity) first, **E1** (book-timed entry) second, **D1** (book dynamics) registered after E1
reads. Mode: build offline; the forward paper test, the exploratory arm and the micro-pilot run
untouched in the background. Nothing in this document changes anything served.

**Why a second wave at all.** [BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) closed on 54 days with
every book number inside its own day-clustered resolution. The era is 86 days today (snapshots
from 2026-07-17 on BTC/ETH/SOL; 58 days on ADA/AVAX/LINK/XRP; the 100-level ladder from
2026-08-05, 67 days, 18 GB). Re-running the B-wave's designs on 86 days shrinks a CI by 1.26×
and settles nothing — B1's best cell would read roughly ±5.7 around +4.75. What the extra
history and the unread ladder buy is room for **different designs**:

| id | the design | why it was never tried | what it costs |
|---|---|---|---|
| **L1** | measure what the 100-level ladder spans, then test whether the archive's ±0.2 % / ±1 % depth bands can be computed from it | nothing on the Python side has ever read `orderbook_levels`; the "collector cannot compute the archive's bands" sentence in BACKLOG was written without looking | one 300 MB export, 72 archive files, CPU minutes |
| **E1** | let the incumbent's entry wait up to K minutes for the 1m book state to agree with the trade's side; paired on identical trades | every B-wave test asked the book to *predict* a return; none asked it to *time* an entry the policy had already decided on, which is the one design whose statistic resolves at the bps level the book has ever shown | CPU, `ml_analysis`; no export (B0's 1m table) |
| **D1** | order-flow imbalance, book delta, within-bar aggregates — the F6 list of 2026-08 | proposed in TRAINING_HISTORY (F6) and never built; the eleven scalars are all instantaneous and 5 of 6 snapshots are discarded | CPU; registered after E1 reads |

🔴 **Contamination, stated once.** The book-era bars 2026-07-17 → 09-09 were read by B1, B2, B3
and X7. An exploration on them can **close** a question and cannot **establish** one; every
confirmation below is on forward bars nobody has read (the served checkpoint's `policy_bars`
from 2026-09-11, the dataset X7 reserved — read once, on X7's date, so the forward window gets
one look for both).

---

## L1 — the ladder's reach, and the archive band identity — 🟢 READ 2026-10-11

**RESULT, read 2026-10-11** (`logs/l1_ladderspan_20261011.log`, `logs/l1_export_20261011.log`,
`logs/l1_archive_fetch_20261011.log`). Sample as registered: 178,586 ladder rows × 12 pairs on
the six days, one row per 30 s slot (p50 spacing 30 s), no crossed touch; 207,360 archive rows.

**1. What the ladder reaches** (distance of level 100 from the mid, p50, bps; "levels to …"
are the registered estimate, span ÷ 100, not a measurement of a deeper book):

| pair | L100 span p50 | reaches ±0.2 % | reaches ±1 % | est. levels to 20 bps / 100 bps |
|---|---:|---|---|---|
| BTC | 1.7 | no | no | ~1,190 / ~5,900 |
| ETH | 4.1 | no | no | ~490 / ~2,400 |
| ZEC | 10.4 | 10 % of rows | no | ~190 / ~960 |
| HYPE | 12.3 | no | no | ~160 / ~810 |
| 1000PEPE | 28.5 | **yes** | no | 71 / 350 |
| XRP | 71 | **yes** | no | 29 / 140 |
| LINK | 86 | **yes** | no | 24 / 120 |
| SOL | 99 | **yes** | 37 % of rows | 21 / 100 |
| DOGE | 121 | **yes** | **yes** | 17 / 83 |
| AVAX | 131 | **yes** | 58 % of rows | 16 / 77 |
| WLD | 265 | **yes** | **yes** | 8 / 38 |
| ADA | 459 | **yes** | **yes** | 5 / 22 |

The 20-level basis of the served scalars reaches ±0.2 % on ADA, DOGE, WLD only. So: the
±0.2 % band is computable live from the collector as it stands on **8 of 12 pairs**, the ±1 %
band on **3** (ADA, DOGE, WLD; AVAX and SOL part of the time). On the majors the top 100 levels
are a few bps deep. Binance's REST depth stops at 1,000 levels, which by the estimate covers
ETH, HYPE, ZEC and 1000PEPE at ±0.2 % and leaves **BTC out of reach from REST at any limit**;
±1 % on the majors is a `@depth`-stream-and-local-book question (B4.3 proved the stream
reachable).

**2. The identity, by the bar: DIFFERENT on all 12 reachable pair-bands, IDENTICAL on none**
(medians 3.7–7.1 % at ±0.2 %, 1.2–1.8 % at ±1 %; p99 far over 10 % everywhere; the two clocks
and the two references give the same picture; the mid reference is the better one on every
pair-band). **Read with the structure of the miss, which the log's follow-up describes:**

* the **central quantity is the same number** — the ratio ladder-sum ÷ archive has a median of
  **1.000 (0.995–1.005)** on every reachable pair-band, both sides, both bands;
* the miss lives in the **tails**, and the tails are **day-shaped**: on 2026-09-03 50–73 % of
  rows disagree by more than 10 % on every pair, on 2026-10-01 20–57 %, on the other four days
  10–30 % at ±0.2 % and **0.3–6 % at ±1 %** (SOL ±1 %: 2–3 % overall). The worst rows show the
  archive's ask band **frozen at 869 DOGE for ninety minutes** (12:53–14:21 on 09-03) while the
  ladder held 13–18 million — stale archive rows, not a definitional difference;
* at ±0.2 % on the clean days the residual 10–15 % is what 15 s of clock jitter does to a
  20-bps-wide band on a pair whose touch moves every second.

So the outcome is (c) by the letter and closer to (a) in substance: the archive's band **is**
the ladder's band summed from the mid, carried with stale stretches the archive itself does not
flag. Not registered here and written down as the next step if the family is ever built: a
stale-row filter (a value unchanged across consecutive 30 s stamps is dropped), then the
identity re-read on the filtered rows under the same bar — that is a new registration, not a
re-run of this one.

**3. What it means, written against the outcome paragraph below.**

* **The M2 reopening condition for a book family is now met in substance on 8 pairs at ±0.2 %
  and 3 at ±1 %**, with the archive-quality caveat above; it is **not met on BTC, ETH, HYPE,
  ZEC** from the collector as it stands. A depth-band family is **admissible to register** on the
  reachable pairs (masked elsewhere, `has_*`), after the stale-row identity re-read; it is not
  registered here and it is a GPU item (X8's shape). 🟡 **Needed from Vadim: the collector
  decision**, with these numbers — (i) nothing, serve the band where 100 levels reach it;
  (ii) REST `limit=500` or `1000` (request weight 10 / 20 a poll a pair, against the current 5;
  the twelve-pair poll loop would spend ≈ 840 / 1,700 weight a minute of the 2,400 ceiling,
  before the other polls), which brings ETH/HYPE/ZEC/PEPE to ±0.2 % and nothing to BTC;
  (iii) the `@depth` stream with a local full book, the only route to BTC and to ±1 % on the
  majors — a real collector build. In every option the thing worth **storing** is the band sums
  (twelve floats a snapshot), not a deeper ladder: a 500-level ladder would grow the disk at
  ≈ 5× today's 14 GB/month.
* **The disk decision (2026-11-01)** gets its fact: the 100-level ladder has one reader (this
  module) and its content for a served feature is the band sums. A rolling-window prune (e.g.
  30 days) plus band scalars written by the collector loses nothing L1 found useful.
* The "collector cannot compute those bands" sentence in BACKLOG is replaced by this table.

*The registration as written on 2026-10-11, before the run:*

### In plain terms

Binance's public archive publishes, for every traded pair, the quantity resting within ±0.2 %,
±1 %, ±2 %, ±3 %, ±4 % and ±5 % of the mid, every 30 seconds, as daily files
(`data/futures/um/daily/bookDepth/<SYM>/`). Measured 2026-10-11: files from **2024-05-16/17**
for the 2022-listed pairs (BTC, ETH, SOL, DOGE, ZEC, ADA, AVAX, LINK, XRP), 2024-09-16 for
1000PEPE, 2024-12-04 for WLD, 2025-05-30 for HYPE; current to the previous day; 2,880 rows a day
per band; no best bid/ask. (BACKLOG's "from 2023-01" was wrong for this product and is corrected
there.) That history sits **inside M2's training window** for its last ~16 months — the one
condition the M2 freeze names for a book feature family — *if* the same quantity can be computed
live. The collector holds 100 levels a side every ~8 s. Whether 100 levels reach ±0.2 % or ±1 %
depends on the pair's tick: a format peek on 2026-10-11 showed BTC's level 100 about 2 bps from
the touch and DOGE's about 1.1 % away. L1 measures that for every pair and then checks, where
the ladder reaches, that a band summed from the ladder **is** the archive's number.

### Data, fixed now

* **Ladder sample.** `orderbook_levels`, all 100 levels, one row per 30-second slot
  (`extract(epoch from ts)::bigint % 30 < 10` — at the ~8 s cadence that is ≈ one row a slot),
  on six UTC days spread over the ladder era: **2026-08-06, 08-20, 09-03, 09-17, 10-01,
  10-10**. All twelve pairs (ADA/AVAX/LINK/XRP have no 08-06). Exported by
  `scripts/gcp_m3_export.sh` with `LEVELS=100` and the new `BOOK_FILTER` clause into
  `ml/train/output/ladder_span/`. Expected ≈ 200k rows.
* **Archive.** The same six days, twelve pairs, from `data.binance.vision`, sha256-verified as
  X8's fetcher does (`ml/train/m3/archiveoi.py`), cached under `output/archive/bookdepth_zips/`.

### Measurements, all descriptive (no gate)

Per pair, over the sampled rows: the distance of level 100 from the mid, bid and ask, in bps
(p5 / p50 / p95); the share of rows where the ladder reaches ±0.2 % and ±1 % on **both** sides;
the same at 20 levels (the served scalars' basis), for the record; and the bps per level
(span ÷ 100) as the only basis for an estimate of what a 500- or 1000-level poll would reach
(labelled an estimate — a deeper book is not a linear extrapolation of its top).

### The identity check (the one thing with a bar)

For each pair, day and archive timestamp: the nearest ladder row within **15 s** (`ts`, the
receipt clock; `event_time` as a second match where present). From the ladder: cumulative
quantity within x % of the mid on each side, mid = (best bid + best ask) / 2, x ∈ {0.2, 1}. Two
reference conventions are scored, mid and the side's own best price, and the one that matches
is reported as the data's choice (as X8 reported the +5 min shift). A row counts only when the
ladder's level 100 lies **beyond** the band edge on that side; a pair-band with fewer than
**50 %** such rows is reported **UNREACHABLE** — a measurement, not a failure. On the reachable
rows the bar, per pair-band, is **median relative difference < 2 % and p99 < 10 %**, ≥ 1,000
matched rows. The bar is wider than X8's (0.5 % / 2 %) because the two clocks are up to 15 s
apart and a book changes in 15 s; the distribution is printed so a reader can judge a near miss.

### What each outcome means, written now

* **IDENTICAL on a reachable band** → that band can be served from the ladder as is, and filled
  from the archive back to 2024-05. A depth-band feature family becomes **admissible** under the
  M2 freeze's reopening condition; it is **not registered here** — it would be its own
  registration (GPU, three runs, X8's shape) after Vadim's go. Pairs where the band is
  UNREACHABLE would carry it masked (`has_*`), which is a recipe question for that registration.
* **UNREACHABLE on the majors** (the likely case for BTC/ETH at ±1 %) → the decision becomes a
  collector one and goes to Vadim with numbers: REST depth at 500 / 1000 levels (weight 10 / 20
  a poll; ×5–10 the ladder's disk growth, against the 2026-11-01 disk decision), or the `@depth`
  stream B4.3 proved reachable, or serve the band only where the ladder reaches.
* **REACHABLE but NOT IDENTICAL under either convention** → the archive's band is not a naive
  sum over the ladder; the M2 book condition stays unmet and the reason is written down.

### Commands

```sh
# 1. export (≈300 MB; the ladder rows are index-ranged by day, the filter is cheap)
# (amended 2026-10-11 before any row was read: the 400-column projection ran at ~1 MB/min on
#  the VM and was cancelled after 11 MB; the raw-jsonb slice and per-day ranges replace it —
#  same rows, same sample, parsed on the analysis side)
OUT=ml/train/output/ladder_span ONLY=book_raw \
  BOOK_FILTER="AND ((ts >= '2026-08-06' AND ts < '2026-08-07') OR (ts >= '2026-08-20' AND ts < '2026-08-21') OR (ts >= '2026-09-03' AND ts < '2026-09-04') OR (ts >= '2026-09-17' AND ts < '2026-09-18') OR (ts >= '2026-10-01' AND ts < '2026-10-02') OR (ts >= '2026-10-10' AND ts < '2026-10-11')) AND (extract(epoch from ts)::bigint % 30) < 10" \
  ./scripts/gcp_m3_export.sh
# 2. archive + measurement + identity
./scripts/m3.sh -m m3 ladderspan fetch
./scripts/m3.sh -m m3 ladderspan report 2>&1 | tee logs/l1_ladderspan_$(date +%Y%m%d).log
```

**Needed from Vadim: nothing** until the outcome paragraph above is read.

---

## E1 — book-timed entry: the registration — 🟢 READ 2026-10-11, GATE NOT PASSED

**RESULT, read 2026-10-11** (`logs/e1_bookentry_explore_20261011.log`; every harness check PASS:
1,241 / 1,241 trades rebuilt exact at float32, `null0` = incumbent to 1e-8, identical trades and
sizes in every arm, fallbacks 0–1). Population: the three X8″ seeds, 143,569 bars × 12 pairs,
2026-07-18 21:15 → 09-09 20:05; cov 0.05 → 1,241 trades (389 / 446 / 406 a seed), 52 exit days.

**In plain language.** Letting the entry wait for the book to agree did nothing the book can take
credit for. All six book arms sit within ±1.4 bps of the incumbent with intervals of about ±1.5
to ±3 — this test resolved at the scale it was built for — and **every one of them is below its
own fixed-delay control** (−0.2 to −3.8 bps). Whatever the book said, waiting the fixed K minutes
without reading it did at least as well. The gate fails on condition (iii), the one that asks
whether the result is about the book rather than about waiting.

| arm (cov 0.05) | vs incumbent | 95 % CI | s1 / s2 / s3 | median seed | vs control | delay mean / p90 |
|---|---:|---|---|---:|---:|---|
| `imb5` | +1.29 | [−0.20, +2.79] | −1.38 / +2.36 / +2.64 | +2.36 | −1.85 | 2.5 / 5 |
| `imb15` | +1.08 | [−0.82, +2.97] | −1.27 / +1.52 / +2.80 | +1.52 | −0.48 | 3.7 / 11 |
| `micro5` | −0.62 | [−3.57, +2.32] | −1.84 / −0.73 / +0.64 | −0.73 | −3.77 | 1.9 / 4 |
| `micro15` | −0.72 | [−3.69, +2.24] | −1.34 / −1.00 / +0.16 | −1.00 | −2.28 | 2.0 / 4 |
| `both5` | +1.19 | [−1.19, +3.56] | −2.20 / +1.65 / +3.87 | +1.65 | −1.96 | 3.1 / 5 |
| **`both15`** (chosen) | **+1.36** | [−1.51, +4.24] | +0.32 / −0.25 / +4.12 | +0.32 | **−0.19** | 4.9 / 14 |
| `fixed5` (control) | +3.14 | [−0.26, +6.55] | −1.84 / +4.48 / +6.36 | +4.48 | — | 5 / 5 |
| `fixed15` (control) | +1.55 | [−4.92, +8.03] | +3.38 / +2.97 / −1.73 | +2.97 | — | 15 / 15 |
| `coin15` (null) | +2.81 | [−2.99, +8.60] | −1.06 / +0.66 / +8.81 | +0.66 | — | 8.3 / 14 |

Gate: (i) best > 0 ✓ (ii) median seed > 0 ✓ (iii) above its control ✗ → **NOT PASSED.** Forecast
confirmation MDE on the served seed: 2.56 bps per notional — the design would have been
confirmable; the effect is not there. At cov 0.02 (556 trades, information only) the same
picture: book arms −1.2 to +2.7, every one 2.7–7.8 below its control.

**Disposition.** Book-timed entry on `imbalance` / `micro_mid` at K ≤ 15 is **closed on these
bars** (🔴 no other scalar, threshold, K or exit convention on them). Nothing served changes.
The 2027-03-10 confirmation row for E1 is **not** added. D1's prior is lowered as §D1 says.

🟡 **The side-finding — plain waiting.** The *controls* came out positive: entering five minutes
after the decision rather than at once reads **+3.14 [−0.26, +6.55]** at cov 0.05 (two seeds of
three) and **+3.95 [−0.60, +8.50]** at the served cov 0.02 with **all three seeds positive**
(+3.99 / +4.40 / +3.55). Read it with the discipline it deserves: the controls were registered as
controls, not as hypotheses; the intervals include zero; a fifteen-minute wait is wider and
noisier (+1.55 / +6.58) and the coin arm sits between. The mechanism it would point to is
mundane and plausible — the model's signal is computed at a bar's close and the first minutes
after a signal bar partly revert, so an immediate taker entry buys the bar's own extreme. It is
**a hypothesis for the forward look, not a result**: `fixed5` is registered now as a **second arm
of the 2027-03-10 confirmation**, read in the same look as X7's key, on the served checkpoint's
forward `policy_bars` rebuilt from forward 1m candles — two pre-registered hypotheses in one look
on untouched bars, stated here so the multiplicity is on the record. CONFIRMED iff its 95 % lower
bound vs the incumbent is > 0 at cov 0.02; it would license *writing* a serving registration for a
five-minute entry delay in the executor (M3_PROTOCOL §8.3), not a change to the model or the rule.
Expectation, written now: +1 to +4, interval including zero at 180 days (MDE ≈ 2.6 on 1,241
trades over 52 days; the forward trade count is a few hundred).

*The registration as written on 2026-10-11, before the run:*

### In plain terms

The live rule decides at a 5-minute bar's close and buys or sells at once, taker. E1 asks one
thing: if the entry had waited up to K minutes for the book to lean the trade's way — buyers
on the bid when we are buying — would the same trades have been entered at better prices, net of
the drift missed while waiting? Every arm takes the incumbent's trades exactly, same sizes, same
240-minute hold from the actual entry. Only the entry minute moves, by at most K.

### Why this shape — the power

B1's best book cell (imbalance at 60m) is +4.75 bps excess with a ±7 bps CI on 54 days,
measured as a *prediction*. The same bars, read as a *paired entry difference* on ≈ 1,000 trades
a seed at cov 0.05, have a per-trade sd near a ≤ 15-minute return (≈ 30 bps), so the paired
statistic resolves at roughly **±2–3 bps** day-clustered — the first book test in this project
whose resolution is smaller than the effect it looks for. X7's harness check (identical trades)
and §9.6's statistic are reused unchanged.

### Population — identical in every arm

* **Dumps:** the three X8″ seeds, the served family —
  `20261001T155917Z` (s1), `20261002T053534Z` (s2), `20261003T191545Z` (s3, **served**,
  `m2_multi_20261003T191545Z_117836a9.pt`). 12 pairs, val 2025-12-14 → 2026-09-09.
* **Bars:** the book era, 2026-07-17 → 2026-09-09, restricted as X7 restricts: rows where the
  incumbent's regime key `btc_absret_1d` is present and the 5m book-era table has `has_book`.
* **Incumbent:** `WINNER_SPEC` (signal/hold 240, regime ladder ⅓..5⁄3 on `btc_absret_1d`),
  coverage **0.05 primary**, 0.02 information only — X7's reasons (trade count decides).
* **1m grid:** B0's `book_era_1m.parquet` (950,400 rows, 12 pairs, closes and the eleven scalars
  as-of each minute's open; `has_book` with the 5-minute staleness cap). A trade's candidate
  window is the 1m rows from its decision time to decision + K minutes.

### Timing conventions, fixed now

* Decision time T0 = `entry_ts` + 5 min (the 5m bar's close; the dump's entry price is that
  close, which equals the close of the 1m bar opening at `entry_ts` + 4 min).
* Minute k ∈ 1..K: the price is the close of the 1m bar opening at T0 + (k − 1) min, i.e. the
  price at T0 + k min; the book state read at that instant is the 1m table's row at open time
  T0 + k min (the last snapshot at or before it — never a later one).
* Exit: the close of the 1m bar closing 240 min after the actual entry. The hold is unchanged;
  an arm's exit lands up to K min after the incumbent's. Overlap with the pair's next incumbent
  trade is possible for ≤ K min and is **counted and printed**, not modelled.
* A trade whose window lacks a `has_book` row at some minute skips that minute; a trade with no
  usable minute enters at T0 (a **fallback**, counted; cap 10 % per X7/§9.8).

### The arms — the list is the registration

| arm | enters at the first minute k ≤ K where … | K |
|---|---|---|
| `imb5`, `imb15` | sign(`imbalance`) = side | 5, 15 |
| `micro5`, `micro15` | sign(`micro_mid`) = side | 5, 15 |
| `both5`, `both15` | both of the above | 5, 15 |
| `fixed5`, `fixed15` | **control**: always minute K, no book read | 5, 15 |
| `coin15` | **null**: a per-trade uniform minute in 1..15, seed 20261011 | 15 |
| `null0` | **harness**: K = 0, must equal the incumbent exactly | 0 |

Six book arms, two controls, one null. Agreement is strict sign (zero never agrees). No
threshold on magnitude, no other scalar, no other K: adding one is a new registration.

### The statistic, fixed now

Arm − incumbent, **net bps per unit of notional**, `walkforward.paired_notional_diff_bps`,
clustered on UTC exit days (union of both arms' days). Fees cancel (both taker). Pooled over the
three seeds, then per seed, then the median seed. **Reported, not deciding:** each book arm
minus its own fixed-delay control (the mechanism: book-timed waiting vs plain waiting), the mean
and p90 delay actually taken, the share of trades entering at the cap, the fallback count, the
overlap count, and the cov-0.02 table.

### Harness checks, before any contrast is read (falsifiable)

1. **Acceptance:** for every incumbent trade, exit close ÷ entry close − 1 rebuilt from the 1m
   grid equals the dump's `fwd_ret` at float32 on ≥ 99.9 % of trades and within 1e-6 on all.
2. `null0` reproduces the incumbent's `signed_ret` to 1e-6 on every trade.
3. Every arm holds identical `(seed, pair, entry_ts, size)` rows.
4. Fallbacks ≤ 10 % of trades in every arm.

Any failure → return code 3, nothing below may be read.

### Exploration gate and choice rule, mechanical

The book arm with the **highest pooled contrast vs the incumbent** is chosen. The gate passes
iff (i) that contrast is **> 0**, (ii) it is **> 0 on the median seed**, and (iii) the arm's
contrast against **its own fixed-delay control** (same K) is **> 0** pooled — otherwise the
result is about waiting, not about the book. The forecast confirmation MDE on the served seed
(s3's SE × √(days / 180) × 1.96) is printed.

### Confirmation, fixed now

On the served checkpoint's forward `policy_bars` from 2026-09-11, the live cov-0.02 trades,
rebuilt the same way from forward 1m candles and snapshots; **read once, on or after
2027-03-10, in the same look as X7's confirmation**. CONFIRMED iff the chosen arm's 95 %
lower bound vs the incumbent is > 0. NOT CONFIRMED is "not detectable" unless the interval
excludes the exploration estimate. `m3 bookentry --stage confirm` refuses before the date.

### What each outcome licenses

* **Gate passed** → one BACKLOG row dated 2027-03-10 naming the arm. Nothing served changes.
* **Gate not passed** → book-timed entry on `imbalance` / `micro_mid` at K ≤ 15 is **closed on
  these bars**: 🔴 no other scalar, threshold, K or exit convention may be tried on them.
  D1 is still registered — it is a different question — with the prior written down as lowered.
* **CONFIRMED** (2027) → licenses *writing* a serving registration for a delayed-entry executor
  path under M3_PROTOCOL §8.3; it is a change to the executor, not to the model or the rule.

### Expectation, recorded before the run

`fixed5` / `fixed15` slightly **negative** (−1 to −3 bps: a momentum-shaped signal pays for
every minute not held). The book arms within ±3 of the incumbent; the best book arm **+1 to +3
above its control**. The gate more likely **not passed** than passed. A pass with the chosen arm
over +3 would be the surprising reading and would still be "a hypothesis for 2027-03-10".

### Commands

```sh
M3_ERA=repaired M3_EXPORT_DIR=/workspace/train/output/book_era \
  ./scripts/m3.sh -m m3 bookentry --stage explore 2>&1 | tee logs/e1_bookentry_explore_$(date +%Y%m%d).log
# 2027-03-10 or later, once, after the table above is transcribed into §E1:
#   ./scripts/m3.sh -m m3 bookentry --stage confirm --exploration-recorded --config <arm>
```

**Needed from Vadim: nothing** until the gate is read.

---

## D1 — book dynamics (F6): the registration — 🟢 READ 2026-10-15, GATE NOT PASSED

**RESULT, read 2026-10-15: GATE NOT PASSED — book dynamics on the scalar snapshots are CLOSED** (`logs/d1_bookera_20261015.log`, `logs/d1_bookdyn_20261015.log`; export `logs/d1_export_20261011.log` (snapshots) + `logs/d1_export_rest_20261015.log` (the other five slices), 2026-07-17 → 10-10, one window). B0's mandatory acceptance on the rebuild: the 240m forward return equals the X8″ dumps **exactly on every overlapping row for all three seeds** (111,208 / 111,112 / 111,328 of as many; o8's pre-repair rows are not a gate on a post-repair export). Grid 297,216 5m rows × 12 pairs; `has_dyn_W` 84.9–85.3 % of rows; halves split at 2026-08-28 23:57 UTC; 43 day-clusters on half 2. **The gate (the max over the 36 cells, h ≤ 60 m at cov 5 %): best eligible slice `dimb_5` @ 60 m, +3.48 bps raw on n 7,416 against the +5 bar; +1.70 in excess of the period's drift, 95 % [−3.55, +6.95].** At 5 m and 15 m the best cov-5 % cells are +0.85 and +1.21 raw (`imb_mean_5`), under the fee wall as recorded. Classes: `spread_max_5` and `imb_sd_5` VOL-PROXY/BOTH as expected; `imb_mean_5` BOTH at 5/15 m (the imbalance's known vol loading, vol_rho −0.03); `dimb_15` the only DIRECTIONAL cell at 15/60 m, at +2.3 raw. Sign agreement on 24 of the 36 cells. Every line of the recorded expectation was met, including "a pass at 60 m on an `ofi_*` column would be the surprising reading" — the `ofi_*` cells at 60 m sit at +0.2 … +2.7 raw. **Licensed: nothing further on this question** — 🔴 no other window, normalisation, feature or horizon; no B3d arm. Per-level OFI from the raw ladder stays the separate question tied to L1's reading and the 2026-11-01 disk decision. Nothing served changes.

### In plain terms

Every one of the eleven served scalars is a *level* — the book as it stands at one instant —
and the 5m grid keeps one snapshot of the ~35 the collector takes in five minutes. F6 (2026-08)
said the obvious thing and was never built: the information, if any, is in how the book
*moves* — order flow at the touch, the imbalance's drift and its churn, the spread's spikes —
not in where it sits. D1 builds those from the ~8.6 s snapshots the VM already holds and asks
B1's exact question of them, with B1's exact gate.

**Prior, written after E1.** E1 found that the book's instantaneous lean carries nothing an
entry could use at the minute scale (every book arm below its blind control). That lowers, and
does not settle, the dynamics question — E1 read signs at one instant; D1 reads flows over
windows. The expectation below is written with that in mind.

### Data, fixed now

A B0 rebuild on the full era: `scripts/gcp_m3_export.sh` with `FROM=2026-07-17` to the export
date (≈ 87 days, 12 pairs) into `ml/train/output/book_era2/`, then `m3 bookera` there — the same
alignment, acceptance and staleness caps as B0 (the 240m rebuild must equal the X8″ dumps
exactly). The dynamic columns are computed from `snapshots.parquet` (receipt clock `ts`,
median gap 8.6 s) onto the 5m grid, using only snapshots **at or before the bar's open**.

### The features — the list is the registration (12)

For a trailing window W minutes ending at the bar's open, over the snapshots inside it
(masked `has_dyn_W` = 0 when fewer than two snapshots fall in W or the bar's `has_book` is 0):

| column | definition |
|---|---|
| `ofi_1`, `ofi_5`, `ofi_15` | Σ over consecutive snapshots of Δ(`bid_depth_near` − `ask_depth_near`), divided by the window's mean (`bid_depth_near` + `ask_depth_near`) — order flow at the top five levels |
| `dflow_5` | the same with the 20-level `bid_volume` / `ask_volume` |
| `dimb_1`, `dimb_5`, `dimb_15` | `imbalance` at the window's last snapshot minus at its first |
| `imb_mean_5`, `imb_sd_5` | mean and sd of `imbalance` over the window |
| `spread_max_5` | max of spread/mid in bps over the window |
| `micro_mean_5`, `micro_mean_15` | mean of (`microprice` − `mid`) / `mid` over the window |

Horizons 5 (the fee-wall control), 15, 60, and 240 (the drift control), coverages 1/2/5/10 %.
Everything goes through `bookaudit.score` unchanged: direction and percentile map fitted on
half 1, every number from half 2, day-clustered, drift subtracted, DIRECTIONAL / VOL-PROXY
measured apart. **36 gate cells** (12 features × {5, 15, 60} m at cov 5 %); the gate takes the
max, and the reader is told so.

### The gate — §4.1 of BOOK_ERA_PLAN, verbatim

Some feature, on half 2, at a horizon ≤ 60 m, with a top-5 % mean signed return **above +5 bps**
(the maker line), **n ≥ 2,000**, sign agreeing between halves. Reported next to it, not deciding:
the excess over the period's drift with its day-clustered 95 % interval. 🔴 Not negotiated
downward after the read.

### What each outcome licenses

* **Pass** → one registration, later: a 15m GBT arm of B3c's exact shape with the passing
  column(s) added (B3d), run after B3c reads on or after 2026-11-02; nothing served.
* **Fail** → book dynamics on the scalar snapshots are **closed**: 🔴 no other window,
  normalisation, feature or horizon. Dynamics from the raw ladder (per-level OFI) are a
  separate question that depends on L1's reading and on the ladder's disk fate.

### Expectation, recorded before the run

At 5 m and 15 m nothing clears +5 raw (the fee wall, measured twice already). At 60 m the best
cell between +2 and +6 raw with the excess interval including zero; sign agreement on about half
the cells; `spread_max_5` and `imb_sd_5` VOL-PROXY. The gate more likely **not passed**. A pass
at 60 m on an `ofi_*` column would be the surprising reading.

### Commands

```sh
# after the L1 export has finished (one export at a time on the VM; ≈ 1.5 h for the snapshots)
OUT=ml/train/output/book_era2 FROM=2026-07-17 TO=$(date -u +%F) \
  ONLY=snapshots,trades,candles_5m,candles_1m,funding,oi ./scripts/gcp_m3_export.sh
M3_EXPORT_DIR=/workspace/train/output/book_era2 M3_ERA=repaired ./scripts/m3.sh -m m3 bookera 2>&1 | tee logs/d1_bookera_$(date +%Y%m%d).log
M3_EXPORT_DIR=/workspace/train/output/book_era2 ./scripts/m3.sh -m m3 bookdyn 2>&1 | tee logs/d1_bookdyn_$(date +%Y%m%d).log
```

**Needed from Vadim: nothing** until the gate is read.

---

## K1 — X7's ladder key read on archive history instead of waiting for 2027-03-10 — ⚫ VOID 2026-10-20 at the prerequisite (registered 2026-10-19, before any code)

**Written 2026-10-19 on Vadim's "let's go with 1 and 2" (chat; this is item 2), before any
archive file beyond the format listing was fetched, before any number below existed. Nothing
served changes on any outcome.**

### Result — VOID at the prerequisite, read 2026-10-20 (`logs/k1_check_20261020.log`)

**Run as registered, in order: `archivekey fetch` (288 monthly 5m `klines` files, 12 pairs,
2024-10 → 2026-09, sha256-verified, every pair complete, HYPE from its 2025-05-30 listing;
`klines_um_5m_fcb8442a.parquet`), `archivekey reduce` (X8's `metrics_um_5m_83c85bd7.parquet`
reused with the +5 min relabel; 2,453,346 bars, OI present on 97.7 % — the 2.3 % is 2026-09-14
onward, past the metrics file's end and outside every K1 window; `archive_key_5m_bb7c984e.parquet`),
then `archivekey check` on X7's own population (M3_ERA=repaired, the eight book pairs,
M3_EXPORT_DIR=book_era; 97,697–97,913 bars a seed, 2026-07-18 21:15 → 2026-09-03). The
construction tests (`tests/test_archivekey.py`, 5 green) pin the OI alignment to
`sidetable.add_open_interest` on a synthetic series and the composite to a hand computation.**

| prerequisite | bar | measured | |
|---|---|---|---|
| 1. harness replay | 670 trades, +13.46 | 670 trades, `book_composite_lo` − incumbent **+13.46** [−7.97, +34.89], E −8.38; every arm the incumbent's trades exactly | PASS |
| 2. rank agreement | Spearman ≥ 0.80 | **0.512** over 97,913 bars (0.511 over 12,670 timestamps); the archive row present on all 115,365 of X7's bars | **FAIL** |
| 3. rung agreement | identical ≥ 70 %, within one ≥ 95 % | **44.6 %** identical, **79.0 %** within one, 21.0 % two or more rungs apart, on all 670 | **FAIL** |

**K1 is VOID: the archive cannot carry X7's key.** By §K1 nothing further was read — neither
P1 nor P2 was loaded, no look marker exists — and nothing changes anywhere: X7's confirmation
stays on **2027-03-10**, key `book_composite_lo`, exactly as §R.4 registered it; the BACKLOG
row X7 is unchanged, row X15 closed.

**Why it failed (prerequisite 4, description only — no re-cut was made or is permitted).** Two
sources, the larger one not the missing spread:

* **The tape ingredients are different observables, not the same one measured twice.** The
  collector's `trade_count` / `trade_vol` on the 5m grid are the LAST ~10-second poll at the
  bar (`window_start` is the last trade of a poll, asof within 5 min — bookprep, sidetable),
  censored at 200 trades a poll; the archive's are the bar's full 5-minute totals. Per pair
  the Spearman is 0.48–0.75 for the count and 0.38–0.55 for the volume; the open-interest
  change, which both sides derive the same way from the same series, agrees at 0.87–0.89
  (X8's identity, again). Market-wide ranks: count 0.73, volume 0.64, OI 0.88.
* **The spread is a quarter of X7's composite** and is not in the archive. The collector's OWN
  three-ingredient composite (count, volume, OI — the spread left out) ranks the bars at
  Spearman **0.70** against the archive's three, and at **0.85** against X7's four — so the
  tape sampling costs about 0.30 of rank agreement and the missing spread about 0.15.

For the record, not a result: on this population the archive key's contrast is +12.41 [−9.49,
+34.31] against X7's +13.46 — nearly the same money from rungs that agree on fewer than half
the trades, which says the book-era number is as loose as its interval, not that the keys are
interchangeable.

**What this leaves.** The archive carries X7's *idea* (quiet market → bigger size) but not X7's
*key*, and §R.4 admits no other key before the forward look. A live key the archive could
confirm would be a NEW registration with its own exploration — the archive's three ingredients
on the book era score as a key only under a fresh §B2-style gate, and the engineering note in
"What each outcome licenses" (the kline poll keeps `count` and `volume`) would belong to it.
Not proposed here; it is a brainstorm item, not a follow-up.

### In plain terms

X7 found, on the 43-day book era, that sizing each trade by how *quiet* the whole market is
(low spreads, few trades, little volume, flat open interest → bigger size) beat the live rule of
sizing by BTC's last-day move, but only weakly, on bars that B1/B2 had already read. Its one
clean confirmation was parked to **2027-03-10** because confirmation needs about six months of
untouched bars and the collector's book history began in July 2026. This registration asks the
same question on history the collector never saw: Binance's public archive carries, per 5-minute
bar and back to 2020, the **trade count**, the **traded volume** and (every 5 minutes) the **open
interest** — three of X7's four ingredients. The fourth, the **spread**, is not in the archive
after **2024-03-30** (`bookTicker` daily files stop there; checked 2026-10-19 on BTC and SOL, 404
afterwards), so the archive key is built from three ingredients and must first be shown to be the
*same* key where both exist. If it is, X7's confirmation can be read now on seven months of the
served checkpoint's own predictions, plus a year and a half of fold-era predictions as a
replication, and the 2027-03-10 forward look becomes the second confirmation rather than the first.

### Data, fixed now

* **Archive, three sources, all `data.binance.vision`, sha256-verified as `archiveoi.fetch` does.**
  `klines` 5m monthly files (`count`, `volume` per bar) and `metrics` 5m daily files
  (`sum_open_interest`; X8's reduced parquet is reused as is, with its +5 min relabel), twelve
  pairs, **2024-10-01 → 2026-09-30**. Not used: `bookDepth` (bands, no touch — L1's product),
  `bookTicker` (ends 2024-03-30), `aggTrades` (K1 needs per-bar counts only; the klines carry
  them). Expected size: tens of MB.
* **The archive observables**, per (pair, 5m bar), named with a prefix so no table can be mistaken
  for B0's: `a_trade_count` = klines `count`; `a_trade_vol` = klines `volume` (base units, as the
  collector's `trades.volume`); `a_oi_chg` = the bar-to-bar percentage change of the archive OI
  series aligned exactly as `sidetable.add_open_interest` aligns the collector's (`data/features.py`'s
  derivation; zero past the same 8 h cap). `has_a_trades = 1` where the kline exists, `has_a_oi = 1`
  where the OI row exists. Written to `ml/train/output/archive/archive_key_5m_<sha8>.parquet`.
* **The key.** `bookregime.observables` unchanged — within-pair percentile rank over the
  evaluation window's bars, the cross-pair mean at each timestamp, the composite = mean of the
  three market-wide ranks, negated for `_lo`. Name: **`a_composite3_lo`**. The ranks are taken
  **within each population window** below, as B2 and X7 took them (a non-causal convention, kept
  because it is the registered construction; a trailing-30-day causal rank is printed as a
  secondary, information only).
* **Populations.**
  * **P1 — decides.** The served checkpoint's own dump, `eval_preds_20261003T191545Z` (X8″ s3,
    the one serving since 2026-10-04), horizon 240, all twelve pairs, bars **2025-12-14 09:35 →
    2026-07-17 00:00 UTC** — every bar before the book era's first bar (07-18 21:15); none was read
    by B1, B2 or X7. ≈ 215 days, one checkpoint, as the forward confirmation would be.
  * **P2 — replication, reported, not deciding.** The fold era `walkforward_x8`, F3 + F2 + F1
    restricted to bars **before 2025-12-14 09:35** (so P1 and P2 share no bar), three seeds a
    fold, pooled with the §9.6 statistic; F0 is excluded (it is P1's window plus the book era).
* **Entries — identical in every arm.** M3-2's winner rule (`WINNER_SPEC`) at **coverage 0.05**,
  cut per dump over that population's bars, side from the 240m head, 240-minute hold, serial per
  pair; bars where the incumbent key or the archive key is missing are dropped from the population
  before the cut, as X7 did. Cov 0.02 printed for information.
* **Arms.** `incumbent` (`btc_absret_1d`, `regime.build` from the dump's own BTC rows), `flat`
  (size 1), **`a_composite3_lo`** — the one key under test. Quintile edges over the population's
  own bars, `backtest.run` with `size_by_regime=True`; nothing else differs.

### Prerequisite — the archive key IS X7's key (exit = VOID)

Read **before** either population, on the bars X7 itself read (book era, the eight book pairs,
2026-07-18 21:15 → 2026-09-03, the s1/s2/s3 repaired dumps, `bookregime.restrict` to bars with
book, tape and OI present — X7's population reproduced from `logs/bookladder_explore_20260915.log`'s
own counts, 670 trades at cov 0.05): build `a_composite3_lo` from the archive and
`book_composite_lo` from `book_era_5m.parquet` on the same bars, then:

1. **Harness replay:** the incumbent's 670 trades and X7's `book_composite_lo` contrast **+13.46**
   at cov 0.05 reproduce from the collector table (a check that the harness is X7's).
2. **Rank agreement:** Spearman between `a_composite3_lo` and `book_composite_lo` over the
   population's bars **≥ 0.80**.
3. **Rung agreement:** the ladder rung assigned per incumbent trade (⅓ … 5⁄3) is **identical on
   ≥ 70 %** of the 670 trades and never more than one rung apart on ≥ 95 %.
4. **Per-ingredient check, reported:** Spearman of `a_trade_count` vs the collector's
   `trade_count`, `a_trade_vol` vs `trade_vol`, `a_oi_chg` vs `oi_chg`, per pair. The tape is
   censored at 200 trades a poll (M3_4 §1.2), so the first two are expected to agree on the
   quiet side and compress on the busy side; OI should agree as X8's identity did.

Any of 1–3 failing → **K1 VOID**: the archive cannot carry X7's key, nothing further is read, X7's
confirmation stays on 2027-03-10 exactly as registered. No re-cut of the composite (e.g. two
ingredients, another orientation) is permitted — that would be a new key, which §R.4 forbids.

### The statistic and the rule — §R.4's, verbatim where it can be

Contrast = **`a_composite3_lo` − `incumbent`, net bps per unit of notional**, cluster-robust on UTC
exit days (`walkforward.paired_notional_diff_bps`); reported beside it: key − flat, incumbent −
flat (E), each arm's per-notional net at the measured cost, cov 0.02. **Harness check first:**
every arm's trade set equals the incumbent's exactly and every size is a ladder rung.

**CONFIRMED iff the 95 % lower bound of the contrast on P1 is > 0.** NOT CONFIRMED is "not
detectable" unless P1's interval also excludes E on that window. P2 is printed with the same
statistic; if P1 confirms and P2's point estimate is negative, the result is written **CONFIRMED,
REPLICATION FAILED** and carries that line into anything it licenses. One look at P1; one at P2.

### What each outcome licenses

* **CONFIRMED** → *writing* a served-change registration for the ladder key (the same thing §R.4's
  forward confirmation would license), which is also an engineering item: the collector's `candles`
  table stores no trade count (migration `20260717000001`), so a live key needs the kline poll to
  keep `count` and `volume` (Binance's kline payload carries both) or the uncensored tape — that
  registration says which, and the live key must be the archive key's construction, not B0's. The
  2027-03-10 forward look stays as registered and becomes the second confirmation.
* **NOT CONFIRMED** → book-keyed sizing closes **now**, on the strength §R.4 wrote ("no other key,
  construction, coverage or window"); the 2027-03-10 look is cancelled, the BACKLOG row closed.
  Not detectable (interval spans zero and E) → X7 stays parked to 2027-03-10, unchanged.
* **VOID** → nothing changes anywhere.

### Expectation, recorded before the run

**Prerequisite: likely passes** (three of four ingredients, the market-wide mean is dominated by
trade count and volume, which the spread tracks). **P1: not detectable, leaning negative.** The
book era's +13.46 was mostly "not the incumbent" (the incumbent ladder was −8.4 against flat
there); on the fold era the incumbent key was certified, so on P1 it is probably positive and the
challenger's margin over it smaller than the forecast MDE of 11.1. A CONFIRMED here would be a
real surprise and gets the six-month forward look as its second confirmation regardless.

### Contamination, stated

P1's bars were read by X8″'s training-time validation (model selection) and P2's by the fold
certification and by M3's choice of the incumbent key — the incumbent is in-sample there, which
biases **against** the challenger, the conservative direction. No book test has read either.

### Code, planned (none written)

`ml/train/m3/archivekey.py`: `fetch` (klines 5m + the existing metrics reduction), `reduce`
(the parquet above), `check` (the prerequisite), and a `--book-table` option on `bookladder`
so `bookregime.observables` runs unchanged on the archive table; `--stage archive-confirm`
refuses unless `check` has written its PASS marker. Tests: the OI alignment equals
`sidetable.add_open_interest` on a synthetic series; the composite equals a hand computation.

### Commands

```sh
./scripts/m3.sh -m m3 archivekey fetch --from 2024-10-01 --to 2026-09-30
./scripts/m3.sh -m m3 archivekey reduce
M3_EXPORT_DIR=/workspace/train/output/book_era M3_ERA=repaired \
  ./scripts/m3.sh -m m3 archivekey check 2>&1 | tee logs/k1_check_$(date +%Y%m%d).log      # prerequisite; exit 2 = VOID
M3_ERA=repaired ./scripts/m3.sh -m m3 bookladder --stage archive-confirm --population P1 \
  2>&1 | tee logs/k1_p1_$(date +%Y%m%d).log
M3_ERA=walkforward_x8 ./scripts/m3.sh -m m3 bookladder --stage archive-confirm --population P2 \
  2>&1 | tee logs/k1_p2_$(date +%Y%m%d).log
```

**Needed from Vadim: nothing** until the outcome is read. CPU only, `ml_analysis`.

---

## M1 — the maker path priced on the policy's own entries, with an uncensored tape — 🔵 REGISTERED 2026-10-19, before any code

**Written 2026-10-19 on Vadim's "let's go with 1 and 2" (this is item 1), before any archive
trade file was fetched, before any number below existed. Nothing served changes on any outcome.**

### What the record already says — and what this adds

A maker-versus-taker study exists: **M3-4** ([M3_4_PROTOCOL](./M3_4_PROTOCOL.md),
[M3_4_RESULTS](./M3_4_RESULTS.md), August 2026). It measured a taker round trip of **9.84 bps** at
$10,000 (11.84 at the verified 5-bps taker fee), a maker saving of **+3.60** on the cost arithmetic
alone, and **adverse selection negative in 16 of 16 pair-side cells** — a resting order fills
because the price is coming through it. Its verdict: a fee-rebate accounting gain, not a trading
gain; do not build the maker arm on it. Its own stated limits: the window held **zero policy
trades** (the policy's last entry before the window was 2026-07-16), the month was the calmest of
the period while the policy trades the violent bars, the tape was **censored at 200 trades a poll**
(biasing fills downward where they matter), and §3's adverse drift was measured at 60 s and kept
out of the cost by design because the policy's return already contains it.

M1 removes those four limits at once and asks the one question M3-4 could not: **on the trades the
4h policy actually takes, does entering (and exiting) with a resting order beat crossing, after
the price path over the whole 4-hour hold is counted?** The P&L accounting makes adverse selection
and the chase a line in the ledger rather than a side panel.

### In plain terms

Every policy trade is scored as if it were entered two ways: **cross** at the bar close (what the
pilot does now, at the verified 5 bps fee) or **rest** a limit at the touch for 60 seconds and
cross if still unfilled (the maker path the executor does not have, M3_5 §3.1). The exit at +4 h
is scored the same two ways. Each trade then has two net returns; the difference, averaged per
unit of notional over thousands of the policy's own trades, is the number. Binance's public
archive supplies every trade printed (`aggTrades`, uncensored), so fills are judged on the full
tape; the collector's book supplies the quotes where it exists (from 2026-07-17), and before that
the quotes are read off the tape itself, after a calibration that says how well that works.

### Population — the policy's own trades, two strata

* **A (decides).** The served checkpoint's dump `eval_preds_20261003T191545Z`, horizon 240, twelve
  pairs, **2025-12-14 09:35 → 2026-09-09 20:05**, entries by `WINNER_SPEC` at **coverage 0.05**
  (cut over the dump's window), serial per pair, 240-minute hold — the backtester's own trade list
  for the served policy. Expected several thousand trades (the harness prints the count before
  anything is priced). The book-era bars inside A were read by B1/B2/X7 for a *return* question;
  M1 asks a *fill* question about the same entries and states that here rather than pretending
  the bars are untouched.
* **B (direction check, reported).** The forward ledger's actual `policy` entries from
  2026-10-07 (57 closed at writing) and the `explore_cov05` entries (153 closed) as a second line,
  at the read date, with their real `entry_ts`. The 38 pilot (`live`) fills on shared entries give
  a **measured** taker entry: pilot `entry_price` against the paper arm's — descriptive, a reality
  check on the taker arm's model, no bar.

**Entry moment T** = the close of the 5-minute bar the signal was scored on; **exit moment** =
T + 240 min. Pinned mechanically: on B, the paper arm's `entry_price` must equal the candle close
at T for ≥ 99 % of entries (the live engine books the bar close), and A's `ts` is mapped to T by
the same candle match on the overlap. A mismatch is a harness defect, fixed and recorded.

### Data, fixed now

* **Tape:** archive `aggTrades` daily files (`data/futures/um/daily/aggTrades/<SYM>/`), only the
  pair-days that hold an entry or exit moment, sha256-verified, **streamed**: the rows in
  [T − 120 s, T + 1,800 s] around each moment are kept (`output/makerpath/tape_windows.parquet`),
  the zip is discarded. Estimated ≈ 2,000 pair-days × 2–20 MB downloaded, under 200 MB retained.
  Columns used: price, quantity, `transact_time`, `is_buyer_maker`.
* **Quotes, two legs:**
  * **Quoted leg** (moments ≥ 2026-07-17 21:13, the collector's book): `orderbook_levels` (20
    levels suffice for the walk at the sizes below; `b0p/a0p/b0q/a0q`), exported for the moment
    windows only (`BOOK_FILTER` on [T − 60 s, T + 300 s]), nearest row ≤ 15 s before the moment,
    M3-4 §2.4's 30 s staleness cap. M3-4 §2.3's **three-branch fill rule verbatim** (certain fill
    `low < P`; queue-conditional Σ same-side aggressor volume ≥ Q₀ + S; else cross at T + W), on
    the uncensored tape.
  * **Tape leg** (moments before 2026-07-17): the touch is read off the tape — `P_bid(T)` = price
    of the last trade with `is_buyer_maker = true` in [T − 60 s, T], `P_ask(T)` the last with
    `false`; `M_T` their mean; a moment with either side missing is **stale** and dropped (counted,
    §2.4). Fill rule: **branch 1 only** (a trade printed strictly through P within W) — no Q₀ exists,
    so queue-conditional fills count as unfilled; this is the conservative side. The touch rule
    (any trade at P or better) is printed as the optimistic bound, information only.
* **Sizes:** notional **$1,000 primary** (the pilot's next scale), $100 (the pilot today) and
  $10,000 (M3-4's primary) as the ladder, converted at `M_T`. On the tape leg the taker fill at
  $100 / $1,000 is the touch (no walk is possible); at $10,000 the tape leg is not scored.
* **W = 60 s primary**, 30 and 300 s sensitivity — M3-4 §2.2 unchanged.
* **Fees: the verified account tier, taker 5.0 / maker 2.0 bps per side** (REAL_MONEY_TRACK §7
  row 1), passed as parameters; `execcost.py`'s 4.0 / 2.0 constants are M3-4's record and are not
  edited.

### Prerequisite — the tape-implied touch is the book's touch (a bar, not a void)

On the quoted leg's moments (expected ≥ 1,000, book era to 2026-09-09 plus B): the tape-implied
`P_bid`/`P_ask` against the collector's `b0p`/`a0p` at the same moment. **PASS iff** each side agrees
within one tick on ≥ 80 % of moments per pair-side **and** the branch-1 fill verdict computed from
the tape touch equals the one from the book touch on ≥ 90 % of moments. FAIL → the tape leg is
reported descriptively only and the decision below is read on the **quoted leg alone** (A's
2026-07-18 → 09-09 trades plus B); the study is not void, it is shorter.

### Arms, per trade, identical trade sets

| arm | entry | exit |
|---|---|---|
| `TAKER` | cross at T: `1e4·(walk_ask(T,S) − M_T)/M_T + 5.0` (M3-4 §2.6; tape leg: `P_ask`) | cross at T + 240 m, mirrored |
| `MAKER→TAKER` | rest at the touch at T; filled → `1e4·(P − M_T)/M_T + 2.0`; unfilled → cross at T + W against `M_T` | the same rule at T + 240 m |

Each arm's **net return per trade** = side × (exit fill ÷ entry fill − 1) − fees, in bps of notional,
so the price path between a late fill and the exit is inside the number. `MAKER→TAKER` with the
**filled subset only** is printed as a diagnostic and never decides (conditioning on a fill is the
error M3-4 §3 names).

### The statistic and the rule

**S1 = `MAKER→TAKER` − `TAKER`, net bps per unit of notional**, paired on identical trades,
cluster-robust on UTC exit days (`walkforward.paired_notional_diff_bps`), stratum A, W = 60 s,
$1,000. **The maker path is WORTH BUILDING iff S1's 95 % lower bound > 0 on A and S1's point
estimate on B has the same sign.** Otherwise **NOT WORTH BUILDING** at this hold and these sizes,
and M3-4's verdict stands with the policy's own entries now measured. B's own interval is printed
(it will be wide); the sensitivities (W, size, the filled-only diagnostic, per pair, per side,
entries vs exits, the pilot's 38 measured taker fills against the model) are printed and never
promote.

**Harness checks before S1 is read (falsifiable):** every arm has exactly A's trade set; on the
M3-4 pairs and window (08-05 → 09-10) the `TAKER` arm's per-pair entry cost at $10,000 reproduces
M3-4 §1's `C_taker` within ±1.0 bps (the tape is different, the book is the same — a larger gap is
a defect); the uncensored tape's count per 5 m bar ≥ the collector's `trade_count` on every bar
compared (a check on the archive).

### What each outcome licenses

* **WORTH BUILDING** → *writing* a served-change registration for a maker entry/exit path in the
  executor, **pilot arm only** (the paper arms keep booking the bar close — they are the scored
  rule and stay comparable), with a paired forward design of its own; nothing is built or deployed
  on this read.
* **NOT WORTH BUILDING** → the executor stays taker; the BACKLOG maker line closes for the 4h
  policy. No re-cut by pair, side, size or window to find a subset that passes.

### Expectation, recorded before the run

Fill rate at 60 s on the policy's entries **below** M3-4's 70–92 %: the policy enters with the
move, and a resting order on the wrong side of a move does not fill. S1 positive by a few bps
round trip at most (6 bps of fee saving at the verified tier against 1–2 bps of adverse selection
per side and the chase on the unfilled third), interval plausibly spanning zero. The pilot's 38
measured entries should sit within ±2 bps of the modelled taker cost; if they do not, that line
matters more than S1.

### Code, planned (none written)

`ml/train/m3/makerpath.py`: `entries` (the trade lists for A and B, the candle match), `fetch`
(streamed aggTrades windows), `calibrate` (the prerequisite), `read` (arms, S1, the tables), with
`execcost.py`'s arithmetic imported and its fees parameterised. One ladder export for the moment
windows via `scripts/gcp_m3_export.sh` (`ONLY=book_raw`, `BOOK_FILTER` built by `entries`). Tests:
the three-branch rule on a synthetic tape reproduces M3-4's worked cases; net return under each
arm equals a hand computation; the streamed window extraction keeps exactly the rows in range.

### Commands

```sh
./scripts/m3.sh -m m3 makerpath entries 2>&1 | tee logs/m1_entries_$(date +%Y%m%d).log       # counts, pair-days, the BOOK_FILTER
OUT=ml/train/output/makerpath_book ONLY=book_raw BOOK_FILTER="$(cat ml/train/output/makerpath/book_filter.sql)" ./scripts/gcp_m3_export.sh
./scripts/m3.sh -m m3 makerpath fetch 2>&1 | tee logs/m1_fetch_$(date +%Y%m%d).log
./scripts/m3.sh -m m3 makerpath calibrate 2>&1 | tee logs/m1_calibrate_$(date +%Y%m%d).log   # prerequisite: PASS / FAIL (tape leg descriptive)
./scripts/m3.sh -m m3 makerpath read 2>&1 | tee logs/m1_read_$(date +%Y%m%d).log
```

**Needed from Vadim: nothing** until S1 is read. CPU only; ≈ 20 GB streamed, < 1 GB kept.

### BUILT 2026-10-21 (Claude) — mechanical choices fixed before the first fill number existed

Written after `entries` ran (counts only — no fill, no price, no S1) and before `fetch`, `calibrate`
or `read`. Each with the direction of its bias, M3-4 §2.7's way. `ml/train/m3/makerpath.py`;
tests `ml/train/tests/test_makerpath.py` (4 green: the three-branch rule and the tape-leg touch on
a planted tape, both arms' net return against a hand computation on the tape leg and on a planted
ladder with a walk and a queue-conditional fill, the streamed window extraction keeping exactly the
rows in range and a midnight-crossing window naming both days).

* **(a) The quoted leg is a moment with an `orderbook_levels` row ≤ 30 s before it** — the table
  the data section names. That table begins **2026-08-05** (migration `20260805000001`), not
  2026-07-17 as the prose above says: 07-17 → 08-05 holds only scalar snapshots (mid, spread,
  imbalance), no touch prices or sizes. Those moments go to the tape leg. Direction: none.
* **(b) The retained tape is [T − 120 s, T + 360 s]**, not T + 1,800 s: no registered quantity
  reads past T + W_max + 60 s, and the tail would have quadrupled the kept rows (BTC prints ~35 a
  second in a busy window). Direction: none — nothing registered reads it.
* **(c) The tape leg's T + W touch** is read like the T touch (the last print of each aggressor
  kind in [T + W − 60 s, T + W]); a moment missing either touch at T or at T + W is dropped from
  **both** arms (M3-4 §2.7's identical-set consequence), counted. Direction: none.
* **(d) Fees sit inside each arm's return** (taker 5.0 / maker 2.0 per side, parameters; an
  unfilled maker leg pays taker) — the arms' fees differ, so nothing cancels in the contrast and
  `paired_notional_diff_bps`'s no-cost design is honoured by putting the fee in `gross`.
* **(e) The primary weighting is equal notional per trade** ($1,000 each, the fill-model size);
  the policy's own size ladder (⅓ … 5⁄3 by regime quintile) is a reported sensitivity.
* **(f) The tick, per pair,** is the smallest positive difference between distinct archive prices
  on that pair's retained tape (printed in the calibration table).
* **(g) A trade's leg is `quoted` iff both its moments are quoted**, else `tape`; each moment is
  priced on its own leg either way. "The quoted leg alone" means the `quoted`-tagged trades.
* **(h) Harness check 2** is read as M3_4_RESULTS §1's `C_taker` column — the round-trip taker
  cost at that table's 4.0-bps fee on the 5-minute grid over M3-4's own exported book
  (`output/m3_4/book_top20.parquet`) — reproduced per pair within ±1.0 bps by this module's walk.
* **(i) Stratum B's sign check is the ledger's `policy` arm alone**; `explore_cov05` is printed as
  the second line beside it, as the population section says. B was exported fresh on 2026-10-21
  (`paper_trades_20261021.csv`: 60 closed `policy`, 167 `explore_cov05`, 41 `live` fills).
* **(j) The BOOK_FILTER** is per symbol, adjacent ranges merged, minute precision (T is on the
  5-minute grid) — 51 KB, because the export ships the query base64-encoded inside one
  remote-shell argument (128 KB on Linux); the first form (one clause per moment, 107 KB) would not
  have fit.

**Entries (`logs/m1_entries_20261021.log`):** A = **2,507 trades** at cov 0.05 on the served dump
(2025-12-15 14:55 → 2026-09-09 18:05; 1,549 long / 958 short; WLD 776, HYPE 322, ZEC 289, BTC 218,
ETH 203 … XRP 69), the candle pin exact on 2,507 / 2,507 (the dump's `fwd_ret` equals exit close ÷
entry close − 1). B = 60 `policy` + 167 `explore_cov05` closed rows (entries 2026-10-04 15:25 →
10-21 02:25), 41 pilot fills; B's candle pin runs at `read` on the export's candles. **5,468
moments**, 1,146 on or after 2026-08-05 (the quoted leg's export), 4,322 tape-only; **1,456
pair-days** of archive aggTrades to stream.

### RESULT, read 2026-10-21 (`logs/m1_{entries,fetch,fetch_b,calibrate,read}_20261021.log`; `output/makerpath/read.md`, `trade_arms_w60_1000.parquet`): **WORTH BUILDING — on the quoted leg alone**

**Plain reading first.** On the trades the 4-hour policy actually took during the two months the
collector's ladder exists, resting a limit at the touch for 60 seconds (and crossing if it does not
fill) instead of crossing at once would have earned **about 3 bps more per trade, round trip**, with
the 95 % interval **+1.5 … +4.8** — clear of zero. The forward ledger's own 60 policy trades point the
same way (+1.3, wide). The fee saving is 6 bps a round trip at the account's tier; the maker path
keeps half of it: the **exit** keeps most of its 3 (+2.5), the **entry** gives nearly all of its 3
back (+0.6) because the policy enters with the move and the 15 % of entries that do not fill chase
the price. **This licenses writing a registration for a pilot-only maker path; it does not build or
deploy one.** Two cautions sit next to the number: the pre-registered calibration of the pre-ladder
leg failed on its own terms (so the decision rests on 339 trades, not 2,500 — the other 2,168 agree
descriptively), and the pilot's real fills cost 2–5 bps more than the taker model says, which
widens rather than narrows the maker margin but says the taker arm here is optimistic.

**Prerequisite: FAIL on all twelve pair-sides** (`logs/m1_calibrate_20261021.log`, 1,131 quoted
moments ≥ the 1,000 written): within one tick on 7 % (ZEC bid) … 88 % (ADA ask) against the 80 %
bar — above 70 % only where a tick is ≥ 1 bp (ADA 85 / 88, WLD 78 / 77, DOGE 58 / 58), under 20 %
where it is a hundredth of a bp (BTC 35 / 36 at a $0.10 tick = 0.013 bps, ETH 15 / 15, ZEC 8 / 9,
HYPE 14 / 18, 1000PEPE 7 / 4); the branch-1 fill verdict agreed on 83 % (ADA) … 96 % (LINK) against
90 % (seven pairs over, five under). **Diagnostic, after the FAIL (not a re-cut — the bar stands):**
the tape touch against the book touch read at the book row's own stamp agrees on 81 % (BTC), 78 %
(ETH), 94 % (WLD), 92 % (DOGE), 97 % (ADA), and the agreement falls symmetrically with the tape
shifted ±2 / ±5 / ±15 / ±30 s around that stamp (BTC 50 / 45 → 26 / 19 → 10 / 7 → 7 / 5 %) — **no
clock offset between the collector and the archive; the gap at T is the ladder's sampling age
(median 5 s at a ~9 s cadence) on pairs whose tick is a fraction of a basis point.** The two
sources are one market; the bar asked a 9-second ladder to match a 10-cent tick at the moment T. As
registered: the tape leg is descriptive, the decision is read on the quoted leg.

**Harness checks.** (1) Both arms on the identical set by construction — one row per trade carries
both fills; 2,733 priced. (2) **PASS** — this module's walk on M3-4's own book reproduces
M3_4_RESULTS §1's `C_taker` on all eight pairs to ≤ 0.04 bps (BTC 8.017 / 8.017, …, 1000PEPE 11.302 /
11.263, WLD 14.068 / 14.060). (3) **FAIL as written, explained, the archive stands:** archive volume
≥ the collector's polled volume on 559 of 864 whole bars; the 305 bars where the collector shows
more are the QUIET ones (median 428 prints in the bar against 1,176 on the passing bars; 90 % of
them under 100 prints a poll) — the collector's "most recent 200" polls re-count the same trades
across overlapping polls when fewer than 200 arrive (its count is 1.01× the archive's on those bars,
0.97× on the busy ones; the excess at most 1.9×); on the busy bars, where censoring bites, the
collector is the shorter one as M3-4 §1.2 measured. The premise "the collector can only undercount"
was wrong; the archive is not short of anything.

**Population.** A: 2,507 trades (1,549 long / 958 short; WLD 776, HYPE 322, ZEC 289, BTC 218, ETH
203, LINK 128, ADA 117, DOGE 100, SOL 99, 1000PEPE 98, AVAX 88, XRP 69), all priced — **339 on the
quoted leg** (both moments with a ladder ≤ 30 s old: 2026-08-05 → 09-09; WLD 151, ZEC 36, HYPE 31,
ADA 20, BTC 20, XRP 18, ETH 13, DOGE 12, LINK 12, SOL 11, AVAX 8, 1000PEPE 7), 2,168 on the tape leg.
B: 227 closed rows, 226 priced (223 quoted; 1 dropped — WLD's 2026-10-21 archive day not yet
published). No ladder exhausted at $1,000.

| S1 = MAKER→TAKER − TAKER, net bps per unit notional | estimate | 95 % | n | exit-day clusters |
|---|---:|---|---:|---:|
| **A, quoted leg, W 60 s, $1,000, equal notional — DECIDES** | **+3.14** | **[+1.47, +4.81]** | 339 | 36 |
| B, the ledger's `policy` arm — the sign | +1.25 | [−3.09, +5.59] | 60 | 12 |
| B, `explore_cov05` (the second line) | +0.94 | [−1.83, +3.72] | 163 | 18 |
| A, the policy's own size ladder as weights | +3.01 | [+0.53, +5.49] | 339 | 36 |
| A, tape leg (descriptive — the prerequisite failed) | +3.07 | [+2.60, +3.55] | 2,168 | 237 |
| A, W 30 s | +2.48 | [+0.94, +4.01] | 339 | 36 |
| A, W 300 s | +5.31 | [+3.70, +6.92] | 339 | 36 |
| A, $100 (both legs; the tape leg has no walk, so the touch) | +3.07 | [+2.60, +3.54] | 2,507 | 267 |
| A, $10,000 (quoted leg, unexhausted) | +4.79 | [+3.69, +5.89] | 334 | 36 |
| A, filled at both ends — DIAGNOSTIC, conditions on the fill | +9.34 | [+8.92, +9.75] | 244 | 34 |

**Verdict: WORTH BUILDING** — A's lower bound +1.47 > 0 (with Student t on 35 clusters in place of
the registered z: +1.42, still clear) and B's point estimate the same sign. The recorded expectation
("a few bps at most, interval plausibly spanning zero") held on the size and not on the interval —
the quoted leg had more trades than the ≥ 1,000-moment floor implied.

* **Per pair (A, quoted):** WLD +5.29 [+3.40, +7.18] (n 151), DOGE +7.85 [+6.93, +8.77] (12), LINK
  +5.86 [+3.30, +8.42] (12), SOL +5.96 [+3.25, +8.67] (11), AVAX +5.17 (8), XRP +4.14 (18), ADA +3.47
  (20), BTC +3.05 [−0.26, +6.37] (20), ZEC +2.72 [−0.28, +5.72] (36), ETH +0.59 (13), **HYPE −3.60
  [−9.66, +2.46] (31)**, 1000PEPE −29 (7, noise). Per side: **short +4.58 [+2.94, +6.22]** (173),
  long +1.64 [−1.16, +4.44] (166). Described, no verdict; no subset is licensed by this.
* **Fill rates, W 60 s, $1,000:** quoted leg entry 0.841 (certain 0.776, queue-conditional 0.065),
  exit 0.858 (0.773 / 0.086); tape leg 0.850 / 0.809 (branch 1 only); B 0.863 / 0.836. **Not below
  M3-4's 70–92 % as the expectation said** — the policy's entries fill like the unconditional
  grid did; the chase on the unfilled sixth is what eats the entry's saving.
* **Where the contrast comes from** (A quoted, mean bps of the moment mid, positive = cost): entry
  taker 5.92 vs maker path 5.30 (**saving +0.62**); exit taker 5.96 vs maker path 3.43 (**saving
  +2.53**). Taker arm net −1.95 a trade, maker arm +1.19, the candle return +10.44 before costs.
* **The pilot's 41 measured taker entries** (shared with the `policy` arm; descriptive, no bar):
  against the paper close mean −0.78, median +0.37, p90 +56.6 bps — but that span holds ≈ 7 minutes
  of drift (the finding below); against the archive print at the order's `inserted_at` (the taker
  execution cost proper, reference uncertain by seconds): **mean +5.53, median +1.95, p90 +23.95
  bps**, while the modelled taker at $100 on the same moments is +0.45. The mean is **outside** the
  ±2 bps the registration wrote and said would matter more than S1; the median inside. Direction:
  real crossing costs more than the model's walk — that widens the maker arm's margin (85 % of its
  legs never cross; the 15 % that do pay the same real cost as the taker arm) rather than narrowing
  it, so it does not threaten the verdict; it says the TAKER arm here is optimistic by a few bps.

**Finding the candle pin surfaced (not registered, recorded here and in BACKLOG):** the ledger's
`entry_price` equals the candle close at **`bar_ts` − 10 min** on 99.7 % of 57,515 `policy_bars` rows
(exact at no other offset; 1.7 % at `bar_ts` itself), i.e. the served signal's price is the close
of the bar that closed **five minutes before** the row's stamp, and the order goes out 112 s (median)
after `bar_ts` — **≈ 7 minutes after the price it is booked at.** M3_5_INTEGRATION §5 row 4 records
"up to ~30 seconds stale". The engine takes `price` and `timestamp` from the inference signal
(`policy_engine.ex` ~:790); whether the inference server reports the last *finalised* candle one bar
late, or the stamp is one bar early, is not established here. For M1, B's T was placed by the pin
(choice (i)'s correction: the signal bar's open is `bar_ts` − 10 min; pin 226 / 227 after it, 5 / 227
before). For the forward test it means the paper arms' entries are 7 minutes stale against the
tradable moment — a comparability question for Vadim, not changed by this read.

**What this licenses, as registered, and nothing more:** *writing* a served-change registration for
a maker entry/exit path in the executor, **pilot arm only**, with a paired forward design of its
own; nothing is built or deployed on this read. **Not licensed:** a subset by pair, side, size or
window (HYPE's and the longs' intervals are described, not acted on); re-reading at another W.
**Needed from Vadim:** whether to have the registration written (the recommendation: yes — the
interval is clear, both arms' mechanics are M3-4's, and the executor has no limit-order path at
all, M3_5 §3.1 — and a decision on the 7-minute finding first, since a maker path built on a stale
decision clock inherits it).

**The 7-minute clock, investigated 2026-10-21 on Vadim's "1 - investigate" (read-only; nothing changed).**
*Mechanism, from the code:* `serve.py` builds the features from the last **settled** closed bars —
`db.load_candles_tail` keeps candles with `close_time ≤ now − CANDLE_SETTLE_S` (120 s; the collector
polls klines every 60 s and stores the forming bar, so a just-closed bar's row may be the in-bar
snapshot until the next poll — M3_FIDELITY §7.6, 2026-09-11) — and returns `price` = that bar's
close and `last_closed_bar_open_time`. `predict.ex:77` keeps the price and **discards the bar**,
stamping `timestamp: DateTime.utc_now()`. `policy_engine.ex:787` floors that wall clock to
`bar_ts` and records each `(pair, bar_ts)` once, at the first tick that sees it. In the first two
minutes of a bar B the settled bar is the one that closed at B − 5 min (opened B − 10), so the row
stamped B carries the B − 10 bar's close: **99.7 % of 57,515 rows**. The trade is placed at that
recording tick — on the VM, bar rows are inserted 37 / 74 / **102** / 130 / 169 s after `bar_ts`
(p5 … p95, 48,380 rows of 14 days), trades 46 … 173 s (median 111) on every arm — i.e. **≈ 7
minutes after the close the model scored**, which is where the backtest trades. *Live check,
09:10:57 UTC:* the server on BTC reported `last_closed_bar_open_time` 09:00 and price 83,229.4
(the 09:00 bar's close; the 09:05 bar had closed 57 s earlier, unsettled), while the row stamped
09:05 (inserted 09:06:34 on ETH's twin) carried the **08:55** bar's close. *What it touches:*
arm-vs-arm contrasts on the ledger (R5) share the clock and stand; paper-vs-backtest and
paper-vs-pilot comparability do not — the pilot's fills land 7 minutes after the booked price
(p90 of the gap 57 bps on 41 fills). *Diagnostic, not registered:* on the dump's 2,507 cov-0.05
trades, delaying entry and exit by 5 / 10 / 15 min changes the gross return per trade by **−0.85
[−3.43, +1.73] / −2.49 [−6.62, +1.63] / −5.04 [−9.42, −0.65] bps** (paired, exit-day clusters)
against +8.06 gross — at 10 min a third of the edge at the point estimate, the interval wide.
*Options, Vadim's served-change decision:* **(A)** `predict.ex` passes `last_closed_bar_open_time`
through, the engine keys `policy_bars` on that bar (its close as `bar_ts`) and decides when a NEW
closed bar is scored — the trade then goes out ≈ settle + one tick ≈ 2–2.5 min after the close;
the ledger's `bar_ts` meaning shifts by 10 min from the deploy (R5's parity must say so). **(B)**
with (A), `CANDLE_SETTLE_S` 120 → 65–70 s (the poll is 60 s) — ≈ 1.5–2 min. **(C)** book the paper
arms at the decision-time mark — not recommended: the paper arms mirror the backtest's rule; the
fix is to bring the real trade to the booked price, not the booked price to the stale trade.
**Recommended: (A)+(B), one registered change in M3_5_INTEGRATION with R5's parity test, deployed
before M2 is built — a maker path measured on a 7-minute-late clock would be measured on the wrong
clock.**

## M2 — the maker path in the executor, pilot arm only — 🔵 REGISTERED 2026-10-21; BUILT 2026-10-21 (the "Built" block at the end), NOT DEPLOYED until the testnet smoke and Vadim's "Deploy"

**Written on Vadim's "2 - yes" (2026-10-21), after §M1's read and before any line of executor code.
Prerequisite: the clock decision above, taken and (if A/B) deployed — the maker path must run and be
measured on the clock it will live on.**

### In plain terms

Today the pilot buys and sells by crossing the spread at once (M3_5 §3.1: the executor has no
limit-order path at all). M1 says that on this policy's own trades a resting order at the touch for
60 seconds, crossing if unfilled, would have earned about 3 bps more per round trip. M2 builds that
path for the **pilot arm only** and measures, on real fills, whether it does. The paper arms keep
booking the bar price — they are the scored rule and stay comparable to the backtest.

### The path, fixed now

* **Entry.** At the decision tick `t_d`: a **post-only limit** (`timeInForce=GTX`) at the touch on our
  side — a buy at the best bid, a sell at the best ask — for the pilot's size. **W = 60 s.** If the
  order is filled, done. If unfilled or partly filled at `t_d + W`: cancel and a **market order**
  for the remainder. **No re-pegging** while resting (M1's model rested at one price). A GTX
  rejection (our price would cross — the market has moved through our side) is answered by a
  market order at once and recorded as `rejected_then_crossed`.
* **Exit.** At the timer close, the same rule mirrored (a long rests a sell at the best ask).
  The stop / target orders the pilot carries today are unchanged.
* **Size.** The pilot's ($100 today; whatever the pilot's scale is at the time — one size, the
  pilot's, never a different one for the maker path).
* **Recorded per trade (new `paper_trades` columns on the `live` arm):** `entry_order_type`
  (`maker` / `maker_then_taker` / `rejected_then_crossed` / `taker`), `entry_rest_price`,
  `entry_wait_s`, `entry_fill_price` (the realised VWAP), the same four for the exit; the
  decision-time touch (`b0p`, `a0p`) from the collector's book at `t_d`.

### The statistic and the rule

**S2 = live maker-path net return − the TAKER counterfactual**, per trade, net bps of notional,
fees inside (the account's tier: maker 2.0 / taker 5.0 per side), paired on identical trades,
exit-day clusters, `walkforward.paired_notional_diff_bps`. The counterfactual is M1's taker arm
priced at `t_d` from the archive tape and the collector's ladder — cross at the touch (walk at the
pilot's size), fee 5 — with M1's machinery (`makerpath.price_moments_quoted`) and the live order's
own `t_d`, so the comparison is at the same instant. **Calibration of the counterfactual, printed
beside, no bar:** the pilot's taker fills before M2 (41 at writing, more by the build) against the
same model — M1 measured them +1.95 (median) / +5.53 (mean) bps worse than the model; if the
maker-path's own crossing legs show the same gap, the counterfactual understates the taker's cost
by that much and S2 is conservative; the line is printed so the reader sees it.

**Readings: at 100 and at 200 closed maker-path pilot trades** (≈ 3 and 6 weeks at the pilot's
~4.7 a day). **EARNING** iff S2's 95 % lower bound > 0 at either reading (the first clear reading
decides; a reading is one look). **NOT EARNING** iff ≤ 0 at both. **Power:** M1's per-trade spread
on the quoted leg ≈ 16 bps (clustered) → se ≈ 1.6 at 100, 1.1 at 200; a +3 is ~2 se at 100 and
clear at 200; +1.5 is not resolvable before 200. **Expectation, recorded now:** +2 … +3 bps (M1's
+3.1 less real slippage on the crossing legs), inconclusive at 100, EARNING at 200 the likelier
outcome.

**Alternative design, Vadim's pick before the build (one or the other, not both):** randomise each
pilot entry 50 / 50 maker-path / taker, pair by exit day, S2 = the arms' difference — model-free,
and needs ≈ 440 trades (≈ 3 months) for the same precision. Default: the paired counterfactual.

### What each outcome licenses

* **EARNING** → the maker path becomes the live arm's default execution at the next pilot scale
  step, and `Trading.ExecCost` gains a measured maker branch for the backtester's cost (the
  taker branch untouched); the paper arms keep booking the bar price.
* **NOT EARNING** → the path is removed from the executor; the maker line closes for the 4h policy.
* 🔴 Not licensed: changing W, re-pegging, a size other than the pilot's, scoring entries and
  exits apart, a third reading, or applying the path to the paper arms.

### Prerequisites and cost

1. The clock decision above — **taken 2026-10-21 (A+B), built and registered as M3_5_INTEGRATION §4.5 (B in its corrected form: a 15 s 5m poll + a 40 s settle)**; deployed on Vadim's word and its §4.5 acceptance run, then R5-parity-checked at the next ledger reading.
2. The executor: `Trading.Executor` gains a limit path — place GTX at the touch, poll order status,
   cancel at W, market the remainder, record the four fields per leg; the ledger columns; tests
   on the Binance testnet through `mix flux.testnet_smoke` (REAL_MONEY_TRACK §6) before any live
   order. Claude's build, a day or two; Vadim's deploy (the fifth-start rule: a served change is a
   restart, said so in the forward record).
3. M1's harness extended with a `--live` read that takes `paper_trades` rows with the new columns,
   fetches the archive days, prices the counterfactual at `t_d`, and prints S2 with the
   calibration line.
No GPU. **Needed from Vadim:** the clock decision; then "build M2".

### Built 2026-10-21 (Claude, on Vadim's "build M2"; the clock fix deployed 15:02 UTC the same day) — NOT DEPLOYED

**What exists now, in plain terms.** The executor can enter and exit the pilot's trades the way
the registration says: a post-only limit at the touch for 60 s, then whatever is unfilled is
crossed. It is off until `LIVE_PILOT_MAKER_PATH=true` is in the VM's environment. The paper
arms are untouched — they never reach this code. Every leg is recorded on the row (what was
rested, how long, what it filled at, the realised fee, the touch it was priced from), and a new
harness job reads S2 from those rows against the taker counterfactual at each leg's own instant.

**The pieces (all tests green in Docker: 167 + 18 Elixir, 5 harness):**

* `Trading.ExchangeOrders`: `place_resting/6` (the touch from the trading host's `bookTicker`,
  `LIMIT GTX` at the bid for a buy / the ask for a sell), `settle_resting/8` (poll `GET /order`
  every 2 s; at W cancel, read the final fill, cross the remainder with a `MARKET`; a cancel
  that races a last-moment fill reads the order back), `cross_now/6` (GTX refused — `-5022` or
  an `EXPIRED` answer — crossed at once), and the synchronous `maker_open/4` / `maker_close/4`
  for the smoke test. Each leg comes back typed with its VWAP, quantity, wait and fee.
* `Trading.Executor`: the `live` arm takes the maker path when the flag is on. The **row is
  written when the entry is placed** (`entry_order_type: "maker_resting"`, priced at the rest)
  so the pilot's slot is held and a restart can find the order; a task under the app's task
  supervisor waits out the rest and reports back (`entry_settled/2`), which rewrites the row
  from the realised leg and places the brakes on the filled quantity. The exit mirrors it:
  `close/2` cancels the brakes, rests a reduce-only limit, marks the row `exit_order_type:
  "maker_resting"` (which `Ledger.due_trades/1` then skips) and answers `{:resting, trade}`;
  `exit_settled/2` books the close with the summed realised fees as the row's `cost_bps`. A
  row whose entry the maker path placed exits on the maker path whatever the flag says at
  that moment, so a trade is measured whole or not at all. After a restart, any leg still
  marked resting is settled at once (cancel and cross; the wait recorded is the real one).
* `paper_trades` columns (migration `20261021000001`): `entry_order_type`, `entry_rest_price`,
  `entry_wait_s`, `entry_fill_price`, `entry_touch_bid`, `entry_touch_ask`, the same six for
  the exit, plus `entry_fee_bps` / `exit_fee_bps` and `exit_rest_at` (below). The engine counts
  `close_resting`; `/api/health` → `live_pilot.maker_path` / `maker_wait_s`.
* `mix flux.testnet_smoke --maker [--wait-seconds N]` — the registered prerequisite 2: the same
  open / hold / close on the testnet through `maker_open` / `maker_close`, each leg's type,
  rest, wait, VWAP and fee printed, `TESTNET_OK` on the same criterion.
* `m3 makerpath live [--ledger CSV]` — prerequisite 3, the `--live` read: the pilot's closed
  maker-path rows (both legs typed, timer exit), each leg's moment at its own t_d (entry =
  `inserted_at`, exit = `exit_rest_at`), the taker counterfactual priced with M1's machinery
  (`price_all_moments` at the pilot's $100, cross the touch, walk the collector's ladder, fee
  5.0) at those instants, S2 = live net − taker net paired per trade, exit-day clusters, the
  **readings on the first 100 and the first 200 trades by exit time** (one look each, as
  registered) and the all-so-far number beside; the calibration line from the crossing legs
  (the pre-M2 taker rows on both legs and M2's `rejected_then_crossed` legs: measured fill −
  modelled taker at the same instant); the leg table and the per-leg cost split. The job
  writes its own moment list, pair-days and `BOOK_FILTER`; `makerpath fetch --live` cuts the
  tape into its own cache (a cached pair-day holds only the rows inside the moments it was
  cut for), and the ladder export goes to `output/makerpath_book_live`. Planted-data test:
  S2 and the calibration equal the hand computation.

**Deviations from the registration's letter, each stated (none changes the rule):**

1. **A fifth leg type, `maker_partial`.** An entry part-filled at the rest whose remainder is
   under the exchange's minimum order (`-4164` if sent) keeps the partial position; the exit
   closes exactly that quantity. The registration's four types did not cover it. (At $100 on
   BTC a partial is impossible — one lot is the whole order; on DOGE-sized quantities it is
   possible and rare.)
2. **Three columns beyond the registered eight + touch:** `entry_fee_bps` / `exit_fee_bps`
   (the realised fee per leg, maker and taker parts weighted by quantity — S2 needs the exact
   fee, and a VWAP alone does not carry the split) and `exit_rest_at` (the exit's t_d; the
   entry's is `inserted_at` because the row is written at placement).
3. **The brakes go on after the entry settles**, on the filled quantity: a position may stand
   unbraked for up to 60 s. (A `closePosition` brake before any position exists is refused.)
4. **A brake that fires during the hold** (the stop at 10 %) closes the row with the brake's
   fill as before, `exit_order_type` nil; such a row is **not an S2 trade** (the exit was not
   the path's) and the read says how many were dropped for it. A `-2022` while the exit rests
   is read the same way (the brake's fill is looked up and booked).
5. **On the way, a latent bug on the existing market path:** an exactly-round float quantity
   (`1200.0`) was being sent as `1.2e3`; numbers now go to the exchange as plain decimals
   (`ExchangeOrders.num/1`). Nothing booked so far was affected (no such quantity occurred).

**Not licensed, unchanged:** W, re-pegging, a size other than the pilot's, scoring entries and
exits apart, a third reading, the paper arms.

**Before the deploy — the registered prerequisite 2, Vadim's keystroke (testnet keys):**

```sh
docker compose exec -e BINANCE_TESTNET=true -e BINANCE_API_KEY=<testnet key> -e BINANCE_API_SECRET=<testnet secret> \
  app mix flux.testnet_smoke --maker --wait-seconds 60 --hold-seconds 30
```

`TESTNET_OK` with the two leg types printed is the pass (a quiet testnet book fills nothing at
the rest, which is `maker_then_taker` — a valid outcome). Paste the output; Claude records it
in REAL_MONEY_TRACK §6 and then needs the word **"Deploy"**.

**The deploy (Claude runs it on "Deploy"):** on `fluxtrader-1`, add `LIVE_PILOT_MAKER_PATH=true`
to `.env`, `git pull`, `docker compose up -d app` (the container recreates: the migration runs
at boot, the flag is in the environment). Acceptance the same day: `/api/health` →
`live_pilot.maker_path: true`; the next pilot entry's row carries `entry_order_type`
`maker_resting` then its settled type within ~70 s, and the log's `[MAKER]` lines; the first
exit's row `close_resting` on `/api/health` and then `exit_order_type` set and `cost_bps` =
the two realised fees. The forward record (M3_5 §4.3/§4.5) gets one line: **not a new start** —
the paper arms book exactly what they booked; the pilot's rows from the deploy are M2's, told
apart by the columns, and R0–R5 never read that arm.

**The read:** `./scripts/gcp_forward_ledger.sh` (the export), `./scripts/m3.sh -m m3 makerpath
live`, then the data steps it prints (`fetch --live`; the ladder export with
`output/makerpath/live/book_filter.sql`), then `live` again. First look when the export holds
100 closed maker-path trades (≈ 3 weeks at the pilot's rate).
