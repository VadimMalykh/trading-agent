# Book wave 2 — three designs the B-wave did not try

**Status (2026-10-11): L1 running; E1 READ — gate not passed, with a side-finding registered forward (§E1); D1 REGISTERED, export queued behind L1's.** Written after Vadim's "go ahead with 1 and 3"
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

## L1 — the ladder's reach, and the archive band identity

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

## D1 — book dynamics (F6): the registration — 🟡 REGISTERED 2026-10-11, after E1's read

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
