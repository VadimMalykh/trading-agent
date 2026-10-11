# Book wave 2 — three designs the B-wave did not try

**Status (2026-10-11): REGISTERED, nothing run.** Written after Vadim's "go ahead with 1 and 3"
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
OUT=ml/train/output/ladder_span LEVELS=100 ONLY=book_top100 \
  BOOK_FILTER="AND ts::date IN ('2026-08-06','2026-08-20','2026-09-03','2026-09-17','2026-10-01','2026-10-10') AND (extract(epoch from ts)::bigint % 30) < 10" \
  ./scripts/gcp_m3_export.sh
# 2. archive + measurement + identity
./scripts/m3.sh -m m3 ladderspan fetch
./scripts/m3.sh -m m3 ladderspan report 2>&1 | tee logs/l1_ladderspan_$(date +%Y%m%d).log
```

**Needed from Vadim: nothing** until the outcome paragraph above is read.

---

## E1 — book-timed entry: the registration

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

## D1 — book dynamics (F6): placeholder

Registered after E1 reads, with E1's verdict written into its prior. The shape, so the later
registration cannot drift: order-flow imbalance over 1 / 5 / 15 min from the ~8 s snapshots,
the book delta over the same windows, within-bar mean / sd of `imbalance`, max `spread_bps`,
and the microprice drift — run through `bookaudit`'s bps gate (held-out halves, drift-adjusted,
day-clustered) at 15 / 60 / 240 m on the 86-day era, cell count fixed in advance, 5m as the
registered fee-wall control. Needs one snapshot re-export (2026-09-10 → today). Not before E1.
