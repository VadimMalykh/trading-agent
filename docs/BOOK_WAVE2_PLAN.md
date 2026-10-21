# Book wave 2 — three designs the B-wave did not try

**Status (2026-10-20): §K1 READ — VOID at its prerequisite, 2026-10-20, before either population was touched: the harness replays X7 exactly (670 trades, +13.46), but the archive's three-ingredient composite is NOT X7's key on the book era — Spearman 0.51 against the bar 0.80, the same ladder rung on 44.6 % of the 670 trades against 70 % (within one rung 79.0 % against 95 %). Nothing changes anywhere; X7's confirmation stays on 2027-03-10 as §R.4 registered it (result block in §K1). Earlier status (2026-10-19): two new registrations appended — §K1 (X7's ladder key read on archive history) and §M1 (the maker path on the policy's own entries), both before any code, on Vadim's "let's go with 1 and 2"; the archive's `bookTicker` ends 2024-03-30, which shapes both. Earlier status (2026-10-12): option 2 DEPLOYED 02:17 UTC — the collector fetches 500 levels and writes the archive-style bands and reach (±0.2 % now on 10 pairs, ±1 % on 8; BTC still out of reach). ⚠️ 2026-10-14: the weight arithmetic in §L1 left out the tape sweep (weight 20 a call, 600–1,440 a minute); the loop crossed 2,400 in the busy hours and the IP was banned twice on 2026-10-13 (holes 07:26–09:40 and 14:00–18:00 UTC in book and tape) — fixed by a rate-limit guard, BACKLOG "collector / data quality"; L1 READ (the ladder reaches ±0.2 % on 8 pairs, ±1 % on 3; the archive band is the same number with stale stretches — collector decision for Vadim in §L1); E1 READ — gate not passed, with a side-finding registered forward (§E1); D1 READ 2026-10-15 — gate not passed (best of 36 cells `dimb_5` @ 60 m, +3.48 bps raw against +5), book dynamics on the scalar snapshots closed (§D1). ⚠️ 2026-10-15: X8c's identity on the live ±0.2 % columns FAILED by the registered bar on every pair-side (medians 5–9 %; the series agree at ratio 0.997–1.003, the bar is below the band's own ten-second change, the archive stamp ~15 s behind the book) — X8c VOID before any run, decision for Vadim in NEXT_TRAINING_PLAN §2 X8c.** Written after Vadim's "go ahead with 1 and 3"
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
