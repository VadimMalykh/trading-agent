# fluxtrader2 — the plan

**Written 2026-09-15 from a design conversation; this is the whole plan, kept current.** When a
phase finishes, its section gets a result line and the README status row moves. Superseded
reasoning is deleted, not appended to. Parked items go in §7 with a revival trigger.

## 0. The goal, and the one-sentence strategy

**Goal:** a system that generates profitable trades on USDⓈ-M perpetual pairs. The twelve pairs
the collector records are the data we *start* with, not the target universe: more pairs can be
downloaded and the set in use can change at any time (Vadim, 2026-09-22). The ultimate shape is a
**screener that selects which pairs to trade, and a model that trades them although it was
trained on entirely different pairs** — generalisation across pairs is part of the goal.

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
- **The unit of money (found defective 2026-09-29, R25 (D1); corrected 2026-09-30).** A trade is counted as a position
  of fixed size earns it: gross = side × (exit / entry − 1), per unit of the size at entry (`backtest.price`;
  `horizon.labels` for the longer-hold label). Until the correction both counted side × log(exit / entry), which
  overstates every short and understates every long by about half the squared move: close for the twelve at holds up to
  a day, wrong for shorts of violent names held a week. Every money number of §8 written before 2026-09-30 is in logs;
  a run counted in actual returns says `"unit": "actual"` in its meta.
  *Hedged* is gross minus side × what one unit spread equally over the other pairs, bought and sold at the same two
  bars, earned (`backtest.basket`: the mean of their returns, not of their logs — counted so, a name picked at random
  earns the basket in the mean, whatever the size of the moves). The flip and the shuffle null are priced by the same
  code. Two things stay logs because they are not money: a model's fitting target (`backtest.labels` — R14's served
  model and P7 are untouched) and the rank IC's vol-standardised label.
  **Charged on the position's value since 2026-10-01** (`backtest.CHARGED`; a run says `"charged": "value"` in its meta):
  each funding payment is the rate × the close at the event ÷ the entry price (`load_costs`' `fundval`), and the exit
  leg's fee, spread and impact are paid on exit ÷ entry; the entry leg on its size. Until then both were charged in bps
  of the size at entry — nothing on small moves (R24's samples: +0.05 bps a trade), −27 bps a trade on R25's shorts of
  names that rose many-fold. The change reproduced the numbers described beside the re-execution to within 1e-6 bps
  (`scripts/charged_check.py` on the saved decisions of R24 and R25: §7's row, PASS 2026-10-01 07:13 UTC — R25 (2,368 trades) net -66.74 against -66.74, R24 pooled (5,054) net -13.83 against -13.83, largest difference over every statistic of the four samples 5.7e-14 bps; the gross unchanged trade by trade). P7's ledger
  (R17) keeps the funding of its exit leg in bps of the size at entry: a one-day hold on the twelve, where the
  difference is nothing; R17's read states it.
- **The re-execution `actual` (Vadim's decision 2026-09-30: "(1)" of P8's "What next").** R22, R23, R24 and R25 are made
  again by their registered commands on the corrected unit — the same cells, members, data and parameters; no download,
  no ingest, nothing else changed. Each writes beside the first read's output (`…_actual`); a guarded fold is read again
  only under `--reexecute actual`, which the guard allows for folds that registration has already read, once, logged as
  `R<n>/actual` in `confirmation_reads.csv` beside the first read's rows, which stay. Each §8 block gets a
  "Re-executed" paragraph under its first result, which is not edited. The re-executed verdict is the read's verdict;
  the first stays on record as what the log unit showed.
  Validity of a re-execution, read first: the first read's own checks on the run (book check, cells, shifts, coverage),
  and `scripts/actual_check.py` — for a book, the decisions and every fill's times, prices, costs and funding are the
  first read's to the last digit, and the first read's fills re-priced give this run's net; for an audit, the cells, the
  shifts and the rank IC are the first read's. The first reads' checks of the INGEST (R23 (2), R25 (2) and (3)) are not
  repeated: nothing has been ingested since, and the check above is what says the inputs are the same.
  Commands: `scripts/actual_chain.sh` on the work VM (`vm.sh bgsh actual 'bash scripts/actual_chain.sh'`), R22 → R23 →
  R24 → R25, each step once. R1–R21 are not made again: one table from their saved fills (`scripts/actual_table.py`,
  below), no new verdict.
- **Ledger.** Every simulated trade records the decision (what, when, why, at what size) and the
  fill (price, cost) *separately*, so that execution assumptions can be re-priced without
  re-deciding.

**R1–R21 as measured and in actual returns (2026-09-30; `scripts/actual_table.py` → `output/backtest/actual_table.md`).**
The saved fills of every harness read made before the correction, counted both ways — decisions, prices, costs and
funding the runs' own; no run was made again, no null was drawn again, and **no verdict changes here**. bps per unit of
notional (1 bps = 1 USDT on 10,000), interval 95 % clustered by day. *actual − log* is about half the squared move:
positive on a long, negative on a short.

In plain words: on the twelve at a 4-hour hold the two ways of counting differ by under 3 bps a trade for rules that
trade both sides and by +5 … +8 for rules that only buy (R4, R8). At a one-day hold the gap is 5–17 bps where one side
carries the money, and small where the sides balance (R15 −0.2, R18 +2.9): the twelve's candle ridge is BETTER in
actual returns (R14 +34.2 → +39.2, R16 +33.1 → +41.2, R13 B +33.0 → +39.3 — its money is on the bought side, and so
is R11's, +5.1 → +17.4); the books that sell violent names are worse (R9 −2.2 → −8.5, R12 −44 → −57, R13 A −78 → −95,
R21 −17.3 → −25.3; R12 at 4 hours −149 → −195 on 49 trades). No closed rule turns positive outside its noise, and no
gate is re-read: each gate also read a null, which this table does not redraw.

| reg | run | folds | exec | trades | gross: log → actual | net: log [95 %] | net: actual [95 %] | actual − log (long side, short side) |
|---|---|---|---|---|---|---|---|---|
| R1 | `reversal4h` | F1+F2 | taker | 3,395 | +21.7 → +21.0 | +9.7 [-6.7, +26.2] | **+9.1** [-7.9, +26.1] | -0.6 (+5.9, -6.4) |
| R1 | `reversal4h` | F1+F2 | maker | 3,404 | +17.9 → +17.3 | +14.0 [-2.7, +30.8] | **+13.4** [-3.9, +30.7] | -0.7 (+5.8, -6.4) |
| R2 | `rank4h` | F1+F2 | taker | 1,777 | -12.5 → -14.6 | -25.2 [-36.2, -14.1] | **-27.3** [-38.9, -15.7] | -2.1 (+3.1, -7.4) |
| R2 | `rank4h` | F1+F2 | maker | 1,780 | -16.3 → -18.5 | -20.6 [-31.7, -9.5] | **-22.7** [-34.4, -11.1] | -2.2 (+3.1, -7.4) |
| R3 | `rev_cap3` | F1+F2 | taker | 2,353 | +0.2 → -2.0 | -11.6 [-26.2, +3.0] | **-13.7** [-29.2, +1.8] | -2.1 (+5.5, -6.9) |
| R3 | `rev_cap3` | F1+F2 | maker | 2,359 | -3.1 → -5.3 | -6.9 [-21.4, +7.7] | **-9.0** [-24.4, +6.4] | -2.1 (+5.5, -6.9) |
| R3 | `rev_invvol` | F1+F2 | taker | 3,395 | +18.7 → +18.2 | +6.8 [-11.1, +24.7] | **+6.3** [-12.0, +24.5] | -0.6 (+5.8, -6.0) |
| R3 | `rev_invvol` | F1+F2 | maker | 3,404 | +15.2 → +14.7 | +11.3 [-6.8, +29.4] | **+10.8** [-7.7, +29.3] | -0.6 (+5.7, -6.0) |
| R3 | `rev_invvol_cap3` | F1+F2 | taker | 2,353 | -0.5 → -2.3 | -12.3 [-27.3, +2.7] | **-14.1** [-29.9, +1.7] | -1.8 (+5.4, -6.5) |
| R3 | `rev_invvol_cap3` | F1+F2 | maker | 2,359 | -3.5 → -5.4 | -7.3 [-22.3, +7.7] | **-9.1** [-24.9, +6.6] | -1.9 (+5.3, -6.5) |
| R4 | `panic4h` | F1+F2 | taker | 3,249 | +52.7 → +57.3 | +39.9 [+19.0, +60.8] | **+44.5** [+23.8, +65.2] | +4.6 (+4.6, long only) |
| R4 | `panic4h` | F1+F2 | maker | 3,254 | +50.4 → +55.0 | +45.7 [+24.8, +66.6] | **+50.3** [+29.6, +71.0] | +4.6 (+4.6, long only) |
| R4 | `panic4h_pre` | FP+F0 | taker | 5,244 | +19.8 → +27.7 | +7.4 [-16.9, +31.7] | **+15.2** [-8.6, +39.1] | +7.9 (+7.9, long only) |
| R4 | `panic4h_pre` | FP+F0 | maker | 5,278 | +15.7 → +23.6 | +11.7 [-12.3, +35.8] | **+19.5** [-4.1, +43.1] | +7.8 (+7.8, long only) |
| R5 | `rankcont4h` | F1+F2 | taker | 1,777 | +12.5 → +14.6 | -0.2 [-11.3, +10.9] | **+1.9** [-9.7, +13.6] | +2.1 (+7.4, -3.1) |
| R5 | `rankcont4h` | F1+F2 | maker | 1,779 | +9.2 → +11.4 | +4.9 [-6.3, +16.2] | **+7.1** [-4.8, +18.9] | +2.1 (+7.4, -3.1) |
| R8 | `trendfall4h` | FP+F0+F1+F2 | taker | 3,384 | +65.6 → +71.3 | +51.9 [+26.4, +77.4] | **+57.6** [+31.9, +83.2] | +5.7 (+5.7, long only) |
| R8 | `trendfall4h` | FP+F0+F1+F2 | maker | 3,423 | +60.1 → +65.7 | +54.9 [+29.7, +80.0] | **+60.5** [+35.2, +85.8] | +5.6 (+5.6, long only) |
| R9 | `bookimb1d` | F1+F2 | taker | 4,411 | +8.0 → +1.8 | -2.2 [-25.2, +20.7] | **-8.5** [-31.6, +14.6] | -6.3 (+12.4, -11.3) |
| R9 | `bookimb1d` | F1+F2 | maker | 4,417 | +4.8 → -1.5 | +2.4 [-20.5, +25.3] | **-3.9** [-27.0, +19.3] | -6.3 (+12.4, -11.3) |
| R10 | `r10_rankcont4h_k4` | F1+F2 | taker | 9,360 | +1.6 → +1.6 | -14.6 [-19.8, -9.4] | **-14.6** [-21.2, -8.1] | -0.0 (+4.5, -4.6) |
| R10 | `r10_rankcont4h_k4` | F1+F2 | maker | 9,366 | -2.7 → -2.7 | -7.4 [-12.5, -2.3] | **-7.4** [-14.0, -0.9] | -0.0 (+4.5, -4.6) |
| R11 | `r11_bookimb1d_long` | F1+F2 | taker | 4,106 | +20.7 → +33.0 | +5.1 [-24.8, +35.0] | **+17.4** [-13.2, +48.0] | +12.2 (+12.2, long only) |
| R11 | `r11_bookimb1d_long` | F1+F2 | maker | 4,114 | +17.9 → +30.2 | +10.3 [-19.7, +40.2] | **+22.5** [-8.1, +53.1] | +12.2 (+12.2, long only) |
| R12 | `r12_ridgebook_4h` | F1+F2 | taker | 49 | -132.4 → -178.2 | -149.0 [-417.6, +119.6] | **-194.7** [-495.7, +106.2] | -45.8 (+3.7, -48.7) |
| R12 | `r12_ridgebook_4h` | F1+F2 | maker | 49 | -139.8 → -185.8 | -147.2 [-414.4, +120.1] | **-193.1** [-492.7, +106.5] | -45.9 (+3.2, -48.8) |
| R12 | `r12_ridgebook_1d` | F1+F2 | taker | 1,648 | -28.1 → -41.1 | -44.3 [-101.0, +12.4] | **-57.3** [-116.5, +2.0] | -13.0 (+16.9, -25.0) |
| R12 | `r12_ridgebook_1d` | F1+F2 | maker | 1,653 | -34.7 → -47.7 | -39.0 [-95.6, +17.6] | **-52.1** [-111.2, +7.1] | -13.1 (+16.9, -25.2) |
| R13 | `r13_ridgebook_1d_inpair` | F1+F2 | taker | 1,410 | -58.4 → -75.9 | -77.9 [-153.7, -2.0] | **-95.3** [-174.9, -15.8] | -17.5 (+18.8, -30.5) |
| R13 | `r13_ridgebook_1d_inpair` | F1+F2 | maker | 1,411 | -65.2 → -82.8 | -72.5 [-147.6, +2.7] | **-90.1** [-169.0, -11.1] | -17.6 (+18.7, -30.6) |
| R13 | `r13_ridgebook_1d_inpair12` | F1+F2 | taker | 1,915 | +46.9 → +53.2 | +33.0 [+0.5, +65.5] | **+39.3** [+4.9, +73.7] | +6.3 (+19.4, -13.5) |
| R13 | `r13_ridgebook_1d_inpair12` | F1+F2 | maker | 1,927 | +44.5 → +50.9 | +38.9 [+5.6, +72.2] | **+45.2** [+10.0, +80.5] | +6.3 (+19.5, -13.6) |
| R14 | `r14_ridgebook_1d_ho12` | F1+F2 | taker | 1,896 | +48.0 → +53.0 | +34.2 [+6.1, +62.3] | **+39.2** [+9.6, +68.8] | +5.0 (+18.1, -13.9) |
| R14 | `r14_ridgebook_1d_ho12` | F1+F2 | maker | 1,909 | +45.3 → +50.4 | +39.8 [+11.0, +68.6] | **+44.8** [+14.4, +75.2] | +5.0 (+18.2, -13.8) |
| R15 | `r15_ridgebook_1d_ho12_all` | F1+F2 | taker | 4,033 | +14.5 → +14.3 | +2.7 [-13.8, +19.2] | **+2.5** [-14.5, +19.5] | -0.2 (+10.7, -10.0) |
| R15 | `r15_ridgebook_1d_ho12_all` | F1+F2 | maker | 4,041 | +12.1 → +11.9 | +8.2 [-8.1, +24.5] | **+8.0** [-8.8, +24.8] | -0.2 (+10.7, -10.0) |
| R16 | `r16_ridgebook_1d_ho12_f34` | F3+F4 | taker | 1,750 | +46.1 → +54.2 | +33.1 [-0.4, +66.6] | **+41.2** [+5.7, +76.7] | +8.1 (+24.6, -13.6) |
| R16 | `r16_ridgebook_1d_ho12_f34` | F3+F4 | maker | 1,750 | +42.7 → +50.7 | +37.8 [+4.2, +71.3] | **+45.7** [+10.1, +81.3] | +8.0 (+24.5, -13.7) |
| R18 | `r18_transferbook_1d` | F1+F2 | taker | 16,306 | +8.6 → +11.6 | -7.9 [-29.3, +13.5] | **-5.0** [-25.9, +16.0] | +2.9 (+21.3, -16.5) |
| R18 | `r18_transferbook_1d` | F1+F2 | maker | 16,306 | +3.9 → +6.8 | -0.0 [-21.4, +21.4] | **+3.0** [-18.1, +24.0] | +3.0 (+21.4, -16.5) |
| R21 | `r21_oibook_1d` | F1+F2 | taker | 8,214 | +1.6 → -6.4 | -17.3 [-28.9, -5.8] | **-25.3** [-37.6, -13.0] | -7.9 (+10.0, -25.9) |
| R21 | `r21_oibook_1d` | F1+F2 | maker | 8,214 | -3.4 → -11.4 | -9.6 [-21.2, +2.0] | **-17.5** [-29.9, -5.2] | -7.9 (+10.0, -25.9) |


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

### P2 — Ceiling audit: how much signal is there, per bet type and horizon (✅ measured 2026-09-20; directional numbers re-read 2026-09-21 with an unbiased IC, R7)

**Result, in plain words** (`ft2 ceiling`, `output/ceiling.md`; exploration folds F1+F2 only,
2023-05-03 → 2024-08-31, eleven pairs, 485 days; fees VIP 0, read from the account 2026-09-20). Words used: a
*basis point* (bps) is 0.01 %; a *round trip* is entry plus exit — 12.3 bps as a taker, 7.2 as a
maker (P1); *IC* is the correlation between a signal and the move that follows, 0 = useless,
0.05 = a good weak signal; "IC needed" is the IC at which trading the strongest tenth of signals
just pays its round trip; the *noise floor* is the IC the same search reaches on labels that were
shuffled so that no signal can exist (200 shuffles) — a measured IC counts only above it.

**Can anything trade profitably yet? Not shown — and the bet this audit first funded was an artefact of its own
statistic (re-read 2026-09-21, registration R7).** The first read (2026-09-20) found short-term *reversal* in a pair's own
next 4 hours at IC 0.045 and funded it; P4's rule was built on that. The IC was a mean of per-day correlations, and that
statistic reads −0.02 to −0.03 for any trailing return on pure random walks (defect record 3). Measured with the
whole-sample correlation, the last-4h return scores −0.013 (t −1.2, p 0.26) and the last-1d return +0.005: **there is no
pair-level reversal on these folds.** What is left at 4h is a fitted forecast with a small real IC (0.030, p 0.025) that no
single feature explains, and at 1d one book feature. Nothing here is funded as a rule; the numbers below are the re-read.

| bet | horizon | IC needed (taker / maker; *with vol timing*) | best IC measured (feature) | noise floor (IC) | fitted forecast, out of sample | **verdict** |
|---|---|---|---|---|---|---|
| directional | 15m | 0.19 / 0.11; *0.08 / 0.05* | 0.016 (last 15m return) | — | — | **excluded** — a tenth of the bar |
| directional | 1h | 0.09 / 0.05; *0.04 / 0.03* | 0.011 (1h change in open interest), family-wise p 0.035 | 0.017 | 0.019, real (p 0.01) | **real, not funded** — a fifth of the bar |
| directional | 4h | 0.047 / 0.027; *0.024 / 0.015* | 0.017 (±1 % book imbalance), family-wise p 0.06 | 0.032 | 0.030, real (p 0.025; 0.005 of it drift); all 24 features on all history 0.044 (t 4.0) | **NOT FUNDED by R7's gate** (no single feature clears the screen) — the forecast is real and above the maker + timing bar: a candidate for P5's forecast layer, not for a rule |
| directional | 1d | 0.018 / 0.011; *0.011 / 0.007* | 0.039 (±1 % book imbalance), family-wise p 0.005, 88 % of months | 0.062 | 0.048 (p 0.09); all 24 features on all history 0.067 (t 3.2) | **not detectable yet, and the most interesting cell** — above every bar in size, under the floor in certainty; the book feature is the lead (§7) |
| relative | 15m | 0.29 / 0.17; *0.13 / 0.08* | 0.043 (last 15m return) | — | — | **excluded** — very real, far too small |
| relative | 1h | 0.14 / 0.08; *0.07 / 0.04* | 0.030 (last 15m return) | 0.011 | 0.014, real (p 0.005) | **excluded on cost** |
| relative | 4h | 0.071 / 0.041; *0.038 / 0.024* | 0.018 (last 15m return) | 0.021 | 0.018 (p 0.04) | **not funded** — half the cheapest bar; R2 closed the rank rule in money |
| relative | 1d | 0.027 / 0.016; *0.016 / 0.010* | 0.032 (±1 % book imbalance), family-wise p 0.015 | 0.036 | 0.025 (p 0.06) | **not detectable** |

What the seven items say, each in a sentence (#7, #2, #6 do not use the defective statistic and are as first read):

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
- **#3 IC screen** (24 features × 4 horizons × 3 bets). *Relative:* reversal of the last 15 minutes to an hour, stable in
  every month, too small for the cost. *Directional:* trailing returns carry nothing beyond 15 minutes; what clears or
  nearly clears the screen is **book imbalance within ±1 % (more bids than asks → lower prices, 4h and 1d)** and the 1h
  change in open interest. For magnitude, dollar-volume surprise and the short/long volatility ratio carry IC ≈ 0.2.
- **#6 Power.** 485 days resolve ±0.4 (15m) to ±3.5 (1d) bps per trade at a tenth of the bars
  traded, and an IC of ±0.01–0.03 at 4h. Power is not the constraint on these folds; signal size is.
- **#4 Noise floor** (200 whole-day label shuffles, 1h/4h/1d). On noise the best of the screen reaches |t| 3.1–3.2
  (directional) and 3.9–4.3 (relative). Directional: 1h and 1d clear it (p 0.035, 0.005), 4h just misses (0.06).
  The **relative t-statistics are overstated by ~1.4×** (their spread on noise is 1.4, not 1). About a sixth of the
  directional forecast's IC is drift (0.004 of 0.019 at 1h, 0.005 of 0.030 at 4h).
- **#5 Learning curves** (ridge vs a depth-2 boosted tree; last 30 / 60 / 120 / 250 days or everything before the fold).
  *More history helps*: directional 4h scores IC 0.011–0.012 on 30–60 days, 0.029 on 120 and on all ~500; 1d −0.006 →
  0.048. (The first read said the opposite — short windows were best at fitting the statistic's bias.) So decision-table
  row 3 applies: **extend the data before the model** — which FP now does. *The tree never beats the line* (t −2.9 to
  +1.4). *Extra sources help on all history*: all 24 features against the 11 candle ones is 0.044 vs 0.030 at 4h and
  0.067 vs 0.048 at 1d — the book and flow features are no longer "a wash" (§7).

**Defect records.** (1) The first run (2026-09-20 08:38 UTC) computed the directional and vol ICs as
a within-day Spearman and read −0.2 at 1d with t = −16. Feature and label share the price at t,
and demeaning inside the day (which uses the day's future prices) makes them negatively
correlated on a pure random walk (−0.5 for one pair). Voided and re-run the same day with an
uncentred daily correlation; `tests/test_p2.py::test_random_walk_has_no_directional_ic` holds
the statistic at zero on a random walk. (2) #4 was planned as "labels shuffled within day". That
is not a null here: a label moved to a later bar of its own day overlaps the trailing-return
features, and a 4-draw trial read an IC of +0.09 … +0.18 for the ridge from that leak alone.
Replaced before the real run by whole-day shuffles that never hand a day the labels of the 8 days
before it (`_shuffle_days`, with a test); nothing was read from the leaky version. (3) **Found 2026-09-21 while testing P5's
basket audit:** the directional, vol and forecast ICs were means of PER-DAY uncentred correlations. A day's normaliser
√(Σf² Σy²) is largest on the days that trend — the days whose products f·y are positive — so a trailing return reads
−0.02 … −0.03 (pooled pairs) or −0.06 … −0.12 (one series) on pure random walks, and the day-shuffle null cannot show it
(a shuffle breaks the within-day link that causes it). `_ic_pooled` is now each day's share of the whole-sample
correlation; `tests/test_p5_market.py::test_ic_statistic_is_unbiased_on_random_walks` holds both at zero. All seven items
were re-run (R7); the first report is kept as `output/ceiling_2026-09-20_biased.md`. The relative screen (Spearman across
pairs per bar) was not affected and reproduced to the digit. Money results (R1–R5, the harness) never used this statistic.

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

### P4 — The dumbest trade generator, through the harness (stage 1 read 2026-09-21: gate passed — but the rule's premise is WITHDRAWN, R7; no confirmation read)

**Premise withdrawn 2026-09-21 (R7):** the pair-level reversal this rule was built to trade was an artefact of P2's IC
statistic; measured without the bias it is zero. The rule's money result below stands as measured (the harness never
used that statistic) and P5 step 1 already explained it: a market-wide bounce in a rising market, not reversal.

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

### P5 — Forecast + analytic decision (🟡 steps 1–11 read, last 2026-09-25; step 11 = R16, the pooled F3+F4 confirmation read of R14: FAILED on the shuffle null only (p 0.18 against a null whose p95 is +104), every other criterion passed and the F1+F2 numbers reproduced — CLOSED by the gate as written; Vadim chose P7 paper trading of R14 by explicit override, 2026-09-25 — P7 is the live phase; R8, R9, R11, R15 parked by their own stage-1 gates, H2 closed on breadth by R10, the candle ridge closed on the forty)

**Can it trade profitably? Not shown.** Plain version of where P5 stands (a bps is 0.01 %; on a 10,000 USDT position
1 bps = 1 USDT; *taker* = crossing the spread, ~12.5 bps a round trip; *IC* = the correlation between a signal and the
move that follows, 0.03–0.05 is what a tradable weak signal looks like here):

- **Step 1 (R2, R3; 2023-05 → 2024-08).** P4's rule ("fade a volatile pair's move") earned its money from **the whole
  market bouncing after a violent fall**, not from the pair reverting: against the other pairs its picks lose 11.6 bps.
  The market-neutral version loses outright (closed). Two hypotheses came out: H1 "buy the market after a panic", H2 "a
  pair torn away from the others keeps going".
- **Step 2 (R4, R5).** The public archive's 2020–22 candles were added as a pre-history fold **FP** (exploration data grew
  from 1.3 to 4.3 years, with a bear market in it). H1 earned +40 bps a trade where it was found and **+7 [−17, +32] on
  the three unseen years** — positive only while the market was rising. H2 is real before costs (+12.5 bps a leg) and
  eaten by them (−0.2 taker / +4.9 maker); parked (§7).
- **Step 3 (R6, R7, R8).**
  - *R6 — what predicts the market's next 4 hours, per year, on all 4.3 years?* A forecast refitted on the last 120 days:
    IC 0.015 against a needed 0.034, negative in 2022 — **not funded**. Plain reversal of the market: nothing (IC −0.007).
    **One feature holds its sign in all five years: the size of the market's 4-hour fall, signed by its 30-day trend**
    (IC +0.032, p 0.015 after paying for the search). In money: after a ≥ 2σ fall the market gains +54 bps over the next
    4 hours when the 30-day trend is up and +5 when it is down.
  - *R8 — that feature as a rule through the harness* (`trendfall4h`: market fell ≥ 2σ in 4h and the 30-day trend is up →
    buy every pair for 4 hours). **+52 bps a trade after costs [+26, +77] on 3,384 trades, p 0.005 — about +110 USDT a
    day at 10,000 USDT a position.** But it is found and measured on the same 4.3 years, it is pure market timing (zero
    against the other pairs), 2022 came in at −5.9 against a bar of −5 written beforehand, and three half-years lose
    18–92 bps a trade. By its own gate it is **parked, no confirmation fold read**; on 2026-09-22 Vadim decided to leave
    it parked rather than spend the confirmation folds on it (§7).
  - *R7 — a defect in P2's statistic, found while testing R6's code.* P2's directional IC was a mean of per-day
    correlations, which reads −0.02 to −0.03 for any trailing return on pure random walks. Re-read without the bias,
    **the pair-level 4h reversal P2 funded (IC 0.045) is zero** (−0.013, p 0.26); P4's premise is withdrawn. What
    survives: a fitted 4h forecast with a small real IC (0.030, p 0.025), and a new lead — **±1 % book imbalance
    predicts a pair's next day** (IC −0.039, family-wise p 0.005), with all 24 features beating the candle-only set on all
    history. "More history hurts" reversed too: more history helps.
- **Step 4 (R9, read 2026-09-22).** R7's lead as a rule (`bookimb1d`: the ±1 % book imbalance in its top decile by size,
  traded against, held a day, F1+F2): **−2.2 bps a trade after taker costs [−25, +21]**, gross +8 where the screen's IC
  promised +20 to +30 — the gate failed on its first condition, **parked, no confirmation fold read**. The screen's pooled
  correlation is carried by the slow level of a pair's imbalance (a book that stays bid-heavy for weeks while the pair
  drifts), not by something a daily trade collects. What the run showed and did not test: 79 % of its trades were shorts,
  and the rare long side (an ask-heavy book) earned +47 gross / +32 net on 930 trades [−5, +69]. That is a new question
  (§7), not a variant.

- **Step 5 (R10, read 2026-09-22).** H2 on breadth: the 40 USDT perpetuals with the most volume in the four months before F0
  (`ft2 universe`, chosen before any of their bars was seen; 32 of them new, clean 5m history 2022-04 → 2024-08, cost from
  one pooled candle proxy `ft2 costwide` whose spread is validated on the twelve and whose impact over-prices thin names),
  four names a side. **The effect is not there: gross +1.6 bps a leg [hedged −3.5, +7.0] on 9,360 legs**, where twelve names
  had shown +12.5 — and this read could have seen +7.4. Net −14.6 taker / −7.4 maker. Closed on breadth; the twelve-name
  version survives only as "maybe, at a lower fee tier, after FP+F0" (§7). The lasting product is the 40-pair dataset.

- **Step 6 (R11, read 2026-09-22).** The ask-heavy book as its own long-only rule (top decile of ask-heaviness, 1d): **+5.1
  bps a trade after taker costs [−25, +35], gross +20.7 — but only +2.0 of it against the market** [−4, +8]; flip p 0.12.
  Gate failed on p; and the hedged number says a pass would have been market exposure, not a book signal. Parked. Fixed rules
  on the raw imbalance are exhausted (§7 book row keeps only the demeaned screen and "inside the ridge").

**Where P5 stands after six steps:** every fixed rule has been read and none clears its own gate; the two that made money
(R8 +52, R11 +5 gross +21) made it by being long the market in rising folds. The plan's own deliverable — a forecast plus a
closed-form decision — has not been built yet, and the restated goal (§0: a model trained on other pairs) makes the 40-pair
universe from R10 the place to build it.

- **Step 7 (R12, read 2026-09-23).** The plan's own deliverable, built and read: a ridge on the 11 candle features, fitted on 30 of
  the 40 pairs and scored on the 10 it never saw (four rotations), forecasting a pair's next-day move against its peers, traded when
  the forecast clears 15 bps. **The forecast does not survive the hold-out: IC 0.0075 (t 1.3) on 463,000 out-of-pair cells, against
  R7's in-pair 0.048; its spread is ~4 bps, so only 3 % of cells clear 15 bps, and those are the wildest names.** Money: 1,648 trades,
  net −44 [−101, +12], MDE 81 — no power, and the gate failed on the IC, the nulls and F2 anyway. At 4h nothing clears 15 bps at all
  (49 trades on 485 days; IC 0.001). Parked (§7). Two things this leaves behind: `forecast.md` — every forecasting run now reports its
  held-out IC, calibration by decile and share of cells clearing the bar — and *hedged net* in every harness report.
- **Step 8 (R13, read 2026-09-23).** The same pipeline fitted in pair. On the forty: IC 0.009 — identical to the held-out 0.0075, so the
  hold-out lost nothing; there was no signal on the forty to begin with. On the twelve collector names (a plain walk-forward, each pair
  fitted on its own past): **IC 0.034 (t 2.2), carried by WLD, SOL, PEPE and AVAX**, monotone in the top decile (forecast +30 bps →
  +78 realised), and the book on it earned **+33 net a trade [+0.5, +65] on 1,915 trades (3.9 a day), hedged +27 [+5, +49], hedged net
  +13 [−8, +35]**, both nulls beaten — in plain money about +130 USDT a day at 10,000 USDT a position. Reported, not a gate: it is an
  in-pair read on exploration folds, i.e. a hypothesis. The candle ridge is closed on the wide universe (§7).
- **Step 9 (R14, read 2026-09-24).** The twelve held out in four groups of three, every name scored by a ridge that never saw it:
  **IC 0.033 (t 2.1) — the same as in pair (0.034)**. WLD 0.113, SOL 0.096, PEPE 0.078, AVAX 0.075 from models that never saw them; the
  seven older names (BTC, ETH, ADA, XRP, ZEC, LINK, DOGE) ≈ 0 or negative. The book: 1,896 trades (3.9 a day), **net +34 [+6, +62],
  hedged +27 [+6, +48], hedged net +13 [−8, +34]**, both folds positive, flip null p 0.01 — but the shuffle null (a ridge fitted on
  day-shuffled labels, traded the same way, 200 draws) is beaten only at p 0.085 against a bar of 0.05, and its 95th percentile is +41,
  above the +33 the read was chasing: **gate (iii) fails, the other four pass → parked by its gate, no variant on F1+F2.** In plain
  words: the sides are right beyond chance and the signal transfers to the names that have it (young, violent ones — the shape §0 wants),
  but the money per trade sits inside the range a random forecast can produce on these names with this rule. 96 % of the money is in
  four names and most of it in 2023Q4–2024Q2. **Needed from Vadim: the confirmation-fold decision (README status row, options A / B / C).**
  **Vadim decided (B) on 2026-09-25:** strengthen the candidate first, then spend the pooled F3+F4 read once, on the arm(s) a
  registration names beforehand.
- **Step 10 (R15, read 2026-09-25: gate FAILED on (ii) and (vi) — parked).** The same held-out ridge with the P2 screen's full
  feature set — 26 columns: the ten candle features, range position and dollar volume, and twelve from beyond the candles (tape flow
  and spread, open-interest change, long/short positioning, taker ratio, ±1 %/±5 % depth imbalance and depth level, funding) — with
  R14's candle-only model inside the run as a paired reference (it reproduced R14's IC 0.0328 exactly, so the run is valid).
  Plain words: **the extra columns add nothing that transfers.** The held-out IC is 0.031 (t 3.0) against the reference's 0.029 on
  the same cells — a paired gain of +0.001, t 0.1 — and the gain that is there moved the signal AWAY from the four young names
  that carry the money (WLD, PEPE, SOL, AVAX) onto the old ones. The wider model also forecasts bigger moves for the same
  information, so twice as many cells clear the 15-bps bar (40 % against 17 %) and the book takes 4,033 trades at +14.5 gross
  each instead of 1,896 at +48: net +2.7 [−13.8, +19.2], hedged net −4.3 — worse than R14 on every money row. In money, +2.7 USDT
  a trade on 10,000 USDT, +22 USDT a day on up to 110,000 deployed (R14: +34 a trade, +133 a day). What the screen saw at IC 0.067
  was the in-pair, own-move reading of a slow per-pair level (R9's finding); out of pair, on the residual, it is gone. R15 is
  parked by its gate (PLAN §8 R15 has the numbers and three unregistered follow-ups); **R16 reads R14 alone** (one arm → p ≤ 0.05).
  Vadim said go on 2026-09-25.
- **Step 11 (R16, read 2026-09-25: FAIL on the shuffle null only — CLOSED by the gate as written).** R14's ridge, unchanged, scored
  on F3+F4 (2024-09 → 2026-01), the folds nobody had looked at; the read is logged and the two folds are spent, F5 is kept.
  Plain words: **the F1+F2 numbers came back.** Net +33 a trade (F1+F2: +34), hedged net +25 (+13), held-out IC 0.043 (0.033),
  flip p 0.005 (0.01) — 1,750 trades, 3.6 a day, +120 USDT a day on 120,000 deployed. Four of five criteria passed. The fifth, the
  shuffle null at p ≤ 0.05, read p 0.18, and could not have been passed: a ridge fitted on shuffled labels earns anything in ±109
  bps a trade on these folds' names, so its 95th percentile is +104 against our +33. The registration said before the read that
  "not distinguishable" counts as a FAIL with the folds spent either way, so by the rule the candle book on the twelve is CLOSED.
  What is thin about it, honestly: the money lives in F4 (net +73) and not F3 (+1.5), in the top forecast decile only, on the
  long side only, and in different names than on F1+F2 (ZEC, PEPE, DOGE, WLD now; SOL and AVAX flat). A real, uneven edge near
  the cost line — §0's shape, not yet a certifiable one. Numbers: PLAN §8 R16.
  **Needed from Vadim: one decision, three options, recorded in §8 R16 when made.** (1) Override the gate on Principle 5 grounds
  and fund P7 paper trading of R14 as is — new observations, no fold spent, needs the serving path built (weeks), and at 3.6
  trades a day it takes years to reach this sample's power on per-trade money, months on the sides (flip null). (2) Spend F5
  (2026-01 → today, ~8 months) on a NEW registration of the same question with a null that has power (flip null as the bar, or
  the shuffle null with per-trade money capped) — the last fold, gone after. (3) Accept closure: R14 parked as the best measured
  candidate, the next registration brings a new target or new observations (§9). Claude's recommendation: (1), because it is
  the only option that adds data the folds do not hold and costs nothing irreversible; (2) is a re-test of a criterion, not a
  strengthened candidate, and F5 is the last untouched fold. **Vadim chose (1) on 2026-09-25 → P7 is funded for R14 (below).**

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

### P7 — Paper trading, then money (🟢 LIVE since 2026-09-25 17:00 UTC: R14 paper-traded on `fluxtrader2-serve` under R17; step 1 built and identity check 1 passed the same day)

**What is being served.** R14 exactly: `ridgebook`, candle features, hold 288, grid 12, min_bps 15, cap 2, groups 4, min_pairs 5,
holdout on, the twelve `PAIRS` in their fixed order (HYPE in group 3), one position per pair, taker. Nothing is tuned for
serving; if serving needs a change to the model it is a new registration, not an edit.

**Needed from Vadim: nothing.** LIVE since 2026-09-25 17:00 UTC (Vadim ran `vm.sh serve-run start` and `vm.sh serve-install`
at 15:57 after Claude's session was refused permission to install persistent timers; the three timers armed). The first
decide run (16:00:15, the first refit) was OOM-killed on the 2 GB host after 44 s — the candle loader built a 4.7 M-row long
frame and the feature cache held every chunk's full array; both fixed in `ft2/serve.py` the same hour (refit peak 935 MB, 13 s,
coefficients bit-identical; SERVE.md "Memory"), the block's model pre-fitted, and `start` re-run so the ledger begins at 17:00
with no `late` row. Claude read `vm.sh serve-status` the next day (green, README) and reads it monthly — the first host refit (2026-09-30 00:00 UTC) PASSED; the first causal check (2026-10-01 01:30 UTC) PASSED: 1,548 cells compared, 0 differ, 27 taken on both sides, 0 differ, `causal_check` pass (`output/serve/checks/check_2026-10-01.md` on the host); the money read is R17's, at ≥ 600 priced trades and ≥ 6 months
(earliest 2027-03-25).

**Built 2026-09-25 (step 1, `ft2/serve.py`, `docs/SERVE.md`, `scripts/serve_install.sh`, `vm.sh serve-*`, `tests/test_p7_serve.py`, 9 tests).**
Identity check 1 PASSED on the work VM (`output/serve/replay/replay.md`): the live path — refit at the harness's block starts,
model saved to and loaded from JSON, one grid bar at a time on a 2,028-bar tail of the market, the book rule from the ledger —
over F3+F4's 11,592 grid bars reproduces R16's forecast.parquet on all 139,104 cells (max |Δ f_bps| 1.5e-10, |Δ σ_h| 1.2e-10,
NaN with NaN) and its 1,753 accepted decisions exactly (t, symbol, side, size). Seed on the host: the collector's 5m candles
2022-08-18 → 2026-09-14 23:55 (4.68 M rows); Binance REST backfill to now: 3,069 bars per pair, no gap, and the 12-bar overlap
with the collector's stored bars matches on all twelve — the served closes ARE the backtest's closes. Design points not in the
prose above: a decision written after its entry bar closed (host down) is recorded with its forecast and skip `late`, never
traded; a pair without its bar at decision time is `no_bar`; the monthly check explains differences at those rows as downtime
and fails on any other; the harness refit runs on the 2 GB host (features in 60-day chunks, same values to 1e-13).

**Where it runs.** A serving path needs an always-on host, and it is a fluxtrader2 host: **this project takes DATA from
fluxtrader1's collector and nothing else — no process, timer or file of this project lives on `fluxtrader-1`** (Vadim,
2026-09-25). The work VM (`fluxtrader2-work`, e2-standard-4, 16 GB, 200 GB) is stopped when idle by design, ≈ 110–130 USD a
month if left on. **Vadim chose a dedicated always-on host on 2026-09-25, and it exists: `fluxtrader2-serve`, `e2-small`
(2 vCPU shared, 2 GB), 20 GB pd-balanced, Debian 12, zone `me-central1-b`, ≈ 13–15 USD a month; created with
`FT2_VM=fluxtrader2-serve FT2_MACHINE=e2-small FT2_DISK_GB=20 scripts/vm.sh create` (the same `vm_setup.sh` venv as the work
VM, no Docker — the cloud exception of §6; code pushed).** Checked on creation: Binance futures REST reachable from it
(`/fapi/v1/klines` and `/fapi/v1/ticker/bookTicker` answer 200 in < 1 s, HYPE included), 1.5 GB free, Python 3.11. Why not the
work VM kept on and resized while idle: every resize stops the VM and the hourly run it lands on is missed, a recurring gap in
a record whose point is to be unbroken. Every `vm.sh` verb takes `FT2_VM=fluxtrader2-serve`; the build adds serve-specific
verbs. A reinstall runbook (`docs/SERVE.md`) is written with the build for everything installed on it. If the refit does not
fit in 2 GB, it moves to the work VM monthly and only the scorer (numpy, 7 days of closes) stays on the small host.

**Data in.** 5m klines for the twelve from Binance's public futures REST (`/fapi/v1/klines`, no key) — the same klines the
collector records (DATA.md candles), so the served closes are the backtest's closes. The history is seeded once from the work
VM's `data/candles` parquet (5m, the twelve, 2022-08-18 → the seed date) and the host appends every closed bar after that.
Live quotes (`/fapi/v1/ticker/bookTicker`: best bid/ask) are recorded for all twelve at every execution time, traded or not,
so that the live spread is measured, not assumed; the last funding rate (`/fapi/v1/fundingRate`) likewise.

**The clock (the harness's, unchanged).** A decision at t uses the bar that closed at t and is executed at the close one bar
later (LATENCY 1): at HH:00 + 15 s the host fetches the klines, forecasts on the grid bar HH:00, and writes the decisions;
at HH:05 + 15 s it records the execution mark for the decisions of HH:00 (the close of the bar ending HH:05, plus the live
bid/ask), and the exit mark for the decisions of HH:00 the day before (288 bars later). One position per pair: a pair with an
open position skips the decision, exactly `accept()`.

**The model.** Refitted every 30 days, on all grid rows whose labels ended before the refit time — the harness's block rule,
continued into live time. Saved as a file (`output/serve/model_<date>.json`: per group μ, σ, coefficients, α; σ_ref), so a
decision can always be re-scored from the model that made it. Training includes F5's bars once the refit passes 2026-01: that
is walk-forward, not a read — no number from F5 is looked at, and F5 stays unread for registrations.

**The ledger** (`output/serve/`, append-only CSV, one row per decision × pair, traded or not): `t, symbol, f_bps, sigma_h, side,
size, skip, model_id, decided_at` — and, filled in by later runs: `entry_t, entry_close, entry_bid, entry_ask, exit_t, exit_close,
exit_bid, exit_ask, funding_bps`. Decision and fill are separate columns on purpose (Protocol, "Ledger"): pricing can be
redone without re-deciding. A `health.json` says: last run, last kline time, bars missing, open positions, rows in the ledger,
model id and age, and any fetch error — so `vm.sh serve-status` reads it in one line.

**Identity checks (the build is not done until these pass).** (1) Replay: the serve code run over F3+F4's grid bars on the
seed history must reproduce `output/backtest/r16_ridgebook_1d_ho12_f34/forecast.parquet`'s `f_bps` per (t, symbol) to 1e-6 and
its accepted decisions exactly — the served model IS R14, or nothing goes live. (2) Continuous causal check: every 30 days the
harness is run over the past month on the appended candle file and its decisions are diffed against the ledger's; any
difference is a bug in serving (look-ahead, a missed bar, a stale model) and is fixed before the ledger continues. This is
the check fluxtrader1 learned the hard way (its X8b), done here from day one.

**How it is read — R17 (§8), written before the first live number.** Monthly: health and the causal check only, no money
number. The money read: at the first month-end when the ledger holds ≥ 600 priced trades AND ≥ 6 months have passed — priced
by the harness's `price()` with the live spread from the ledger's own quotes; gate in R17. A pass → step 2, real money, sized
by Vadim; a fail → R14 is parked with its live numbers and the project moves on (§9).

**Steps.** 1 ✅ 2026-09-25 (build): `ft2 serve` (seed, fetch, start, decide, mark, status, check, replay, ledger), `scripts/vm.sh`
serve verbs (`create-serve`, `serve-seed`, `serve-install`, `serve-run`, `serve-status`, `serve-pull`, `serve-ssh`), the systemd
timers (`scripts/serve_install.sh`), `docs/SERVE.md`, the replay identity test in `tests/test_p7_serve.py`. 2 (go live): seed ✅,
backfill ✅, replay check ✅, `serve-run start` + `serve-install` ✅ (Vadim, 2026-09-25 15:57 UTC) — the first health read
✅ 2026-09-25 19:10 UTC (Claude): green; 5 taken of 36 in three grid bars is a fresh-ledger burst on a 22%-signal day, inside the replay's daily range (README status). Step 2 complete. 3 (monthly): health, causal check (`ft2-check` timer, 1st of the month), refit log. 4 (R17's read): as registered.
5 (money): a new registration.

### P8 — The screener (🟡 R18 read 2026-09-27: not detectable — the twelve's model carries nothing to outside names, no screen finds a group where it does; R19, the hindsight diagnostic, read 2026-09-27: not detectable either; R20, a ceiling audit of new per-name information on the point-in-time universe, read 2026-09-28: nothing clears — funding and the spot–perpetual gap closed, open interest not detectable and the nearest; R21, the open-interest numbers as a priced book on the same names, read 2026-09-28: CLOSED — it loses 17 USDT a trade on 10,000; R22, the same signals at a 3-day and a 7-day hold, read 2026-09-28: not detectable — nothing certified, nothing ruled out; R23, the one open-interest score at 7 days on the unread months 2021-12 → 2023-04, stage 1 of two, read 2026-09-29: CLEARS — +67 bps a leg against a round trip of 17.6, 2.4 times its noise, on cells that did not choose it; a candidate, F3+F4 untouched; R24, the score as a priced book at a 7-day hold on both samples read for it, read 2026-09-29: CANDIDATE by the gate — +17 bps a trade after costs on 5,054 trades, flip p 0.025, but one times its noise and all of it the short side; R25, the confirmation read of that book on the outside names of F3+F4, read 2026-09-29: passed its gate on a defective number — the harness measured profit in log returns, which flatters shorts of violent names; **R22–R25 RE-EXECUTED in actual returns 2026-09-30 (Vadim's decision): R22 nothing clears and the lean mostly gone (+21 a leg, 0.7 times its noise), R23 does not clear (+20, 1.1 times its noise), R24 NOT FUNDED (net −14), R25 NOT CONFIRMED (net −39) — the book is parked; nothing outside the twelve clears its costs; P8 PARKED on Vadim's "(A1) (B1)", 2026-09-30**)

**Why now.** §0's goal has two halves — a screener that picks names, and a model that trades names it was not trained on.
P5 measured the second half among the twelve: the signal transfers, but only to some names, and which names changes from one
year to the next. Nothing has yet asked whether the names can be told apart beforehand. P7 waits six months for its read;
this does not depend on it and spends no confirmation fold.

**What is done, in plain words.** Each month the 60 most-traded USDT perpetuals outside the twelve are listed, with four
things known about each before the month starts: how young it is, how violent, how much its volume has risen ("in play"),
how liquid. The model fitted on the twelve forecasts all of them. Then: is the forecast right more often on, say, the
youngest third than on the oldest third — by more than a meaningless split of the names would give?

**Needed from Vadim: nothing now. P8 is PARKED on his decisions of 2026-09-30 ("What next" below): the re-execution
done (§3; each §8 block's "Re-executed" paragraph), R23's stage 2 not run, the search on outside names parked until a
new question is chosen in a fresh session.**
Commands, gates and numbers: §8 R18–R25. Code: `ft2/screen.py`, `ft2/universe.py`, `ft2/audit.py`,
`ft2/horizon.py`, `tests/test_p8_*.py`.

**Result (R18, 2026-09-27), in plain words. Can the screener pick names yet? No.** On 188 names outside the twelve, chosen
month by month by trading volume alone, the model's forecast was right no more often than a coin: correlation with what
followed 0.0002, where 0.03–0.05 is what it shows on the twelve. None of the four splits found a third of the names where
it works (best: the youngest third, 0.0115, inside the noise). Traded, the book on those names loses 8 USDT a trade on
10,000 after costs — a round trip there costs about 23 bps, twice the twelve's. The test could only have seen a large
difference between groups (about 0.045), so small ones are not ruled out: "not detectable", not "closed".

**What it changes.** It raises a question about the twelve: that list was fixed after 2025-05 (it holds HYPE), by which time
it was known which young names had grown large. A model that buys young names later known to have grown looks skilled on
the long side only — and the twelve's money IS on the long side only, while on names picked without hindsight the long side
loses. This is a hypothesis. The paper test (P7) answers it cleanly, because the list was fixed before every live bar.

**Result (R19, 2026-09-27), in plain words. Is the twelve's result just a lucky choice of names? This test cannot say.**
The same outside names were re-sorted by something only the future knows — how heavily each is traded in 2026 — and the
model was checked on the third that "made it". Its forecast there is right barely more often than a coin (correlation
0.014, with a noise band of ±0.024, against 0.03–0.05 on the twelve): not a signal, and not proof that there is none.
Traded, that third earns 6 USDT a trade on 10,000 after costs, inside the noise, and loses 10 once the market's own move is
taken out. Buying still loses there (−23 USDT a trade) — less than on the names that faded (−74), which is the direction
the suspicion predicted, but on the twelve buying earns +51 … +59, and knowing the future of a name does not reproduce
that. One hint, which decides nothing: on names that are both young and survivors the correlation is 0.031.

**Result (R20, 2026-09-28), in plain words. Does the information the model does not use say which names will do better
tomorrow? Not shown — two kinds of it say nothing, one says something this test could not certify.** After five
registrations found nothing of the price-bar model's signal outside the twelve, R20 asked a question that needs no model: on
the same 188 names, take one number known about each name beforehand and check whether the names that score high on it do
better than the others over the next day. Twelve such numbers were tried, from four kinds of information. *Funding* (what
holders of a position pay each other every 8 hours) and the *premium* (how far the perpetual trades above the spot price):
nothing — closed. The *long/short ratios* (how many accounts are long against short) and the *taker flow* (who is buying at
market): nothing certain; three closed, two unresolved. *Open interest* (the total size of the positions open in a name) is
where something appeared: names whose open interest is large against their daily volume, and names whose open interest has
been falling, did better than their peers the next day, in both halves of the sample. The strongest of them scores a
correlation of 0.033 (t 3.98). It missed the bar: when twelve things are tried at once, the best of twelve on meaningless
data scored as well in 6 % of the trials, and the bar written beforehand was 5 %. So by the rule nothing passed and nothing
may be traded on it.

Two things to know about that result. **The size is small even if it is real:** a trade on these names costs about 18 USDT on
10,000 (a round trip, crossing the spread), and a correlation of 0.033 is exactly where trading the strongest tenth of
signals breaks even — before it earns anything. **And the bar was higher than planned** (4.0 where about 3 was expected),
because two of the twelve numbers carry a lasting fact about names (where the crowd is always long, the name drifted down
over the whole sample) that lifts the score of meaningless trials; that was found after the read and changes no verdict.

One more thing the audit showed, about R18: measured by rank (does the name the model likes more usually do better?)
instead of by average, the twelve's model is WRONG on outside names more often than right (−0.032, t −5.2). What it likes
most there usually does worse than its peers and is rescued on average by a few large winners. It fits R18's money (buying
lost, selling earned) and is described, not tested.

**Result (R21, 2026-09-28), in plain words. Do the open-interest numbers make money? No — closed.** Of three options after
R20, Vadim chose the simulated book. Every hour the block's 60 names were ranked by one score made of the three
open-interest numbers; the book bought the six at the top and sold the six at the bottom, the same amount of each, held
for a day and paid what a real order pays. 8,214 trades over 485 days. **It lost 17 USDT a trade on 10,000 after costs
(between 6 and 29 with 95 % confidence) — about 290 USDT a day on 110,000 deployed.** Before costs it earned 1.6 USDT a
trade, where R20's correlations had promised about 20; trading the same names with random sides did as well. Resting
orders instead of crossing the spread lose less (10 USDT a trade) and still lose. This was the data most favourable to
the idea — the numbers were picked on these very names and months — so by the rule written beforehand it is closed, and no
unread months are spent on it.

*Why the correlation did not become money.* The correlation is real: the check reproduced R20's numbers on the book's own
cells. But it comes from one corner. The tenth of names with the lowest score — small open interest against a lot of
trading, open interest rising: names in a frenzy — usually fall behind the others the next day (74 USDT behind in the
typical case, 25 on average). Among the other nine tenths the score sorts nothing, and the names the book bought did no
better than the rest. And the frenzied names it sold are the most violent ones: usually they fall behind, sometimes one
of them doubles, and the average is much smaller than the typical case.

*What this teaches beyond open interest.* On these names a weak "sorting" signal of this size cannot pay a one-day round
trip: even if every cell could be traded it is worth 12 USDT a leg against 19 of costs. That also bounds the two
long/short numbers R20 left unresolved (they are no bigger). After R10, R12, R13 A, R18, R19, R20 and R21, nothing measured
on names outside the twelve clears its costs at one day.

**Result (R22, 2026-09-28), in plain words. Does holding longer make anything pay? Not shown — and this sample cannot say
no either.** After R21 Vadim chose to measure a longer hold before trading anything. Every hour, for each of six signals
(R20's five unresolved numbers and the price-bar model's forecast), the tenth of names the signal ranks highest was set
against the tenth it ranks lowest: how much more did the first group earn than the second over the next 3 days and the
next 7 days, per 10,000 USDT in each position, funding paid, before trading costs? The bar is the 17.6 USDT a round trip
costs on these names. Twelve readings: none passed, none was ruled out.

The open-interest numbers lean the right way, and more so the longer the hold: R21's score earns 11 USDT at one day, 25 at
three days and 59 at seven; open interest over volume alone 12, 27 and 55. A round trip costs the same 17.6 at every hold,
so on paper the week pays it three times over. But it cannot be told from chance: when the same book is given the price
moves of OTHER weeks — which breaks any real link and keeps everything else — it does as well one time in ten (the
score) to one time in three (open interest over volume alone). In numbers: the part of the score's 59 that belongs to
the timing is 41 USDT with a noise of ±27 — one and a half times its noise, where about three and a half were needed
with twelve things tried at once.

*Where the money would be.* As in R21, all of it is the lowest tenth — names in a trading frenzy — and they keep falling
behind for the whole week: 25 USDT behind their peers after one day, 50 after three, 94 after seven, on average; the
typical one much more (260 after seven days), and a few explode upward. The highest tenth does nothing (−1, +4, +18). So
what is there, if it is there, is a bet AGAINST frenzied names, not a way to pick names that rise.

*Two more things it showed.* The price-bar model's forecast is wrong at a week on outside names: what it likes most
falls 73 USDT behind over seven days (not certified either; the nearest of the twelve). And the two long/short numbers
belong to the names, not to the timing: they change sign between the two halves of the sample.

*Why it could not decide.* 485 days hold 69 separate weeks; the noise came out wider than expected for the slow signals
(51 USDT at seven days for open interest over volume, where 25–40 was expected). The sample ran out, not the idea.

**Result (R23, 2026-09-29), in plain words. Did the one leaning number come back on data that had not been searched?
Yes.** R22 had left one number leaning — the open-interest score held a week — found on the data that was searched. It
was tested once on 71 weeks nobody had read (2021-12 → 2023-04; open interest does not exist earlier), on the 60
most-traded names outside the twelve, re-picked every 30 days. The score ranks names by their *open interest*, the total
size of the positions open in a name: low = a name in a trading frenzy (a lot of trading against the positions held,
open interest rising), high = the opposite.

A position of 10,000 USDT in each of the highest-ranked tenth, against one in each of the lowest-ranked tenth, earned
**67 USDT per position over the week before trading costs**, funding paid; a round trip costs about 17.6. Of the 67,
14 belong to the names rather than to the timing; the remaining 53 are 2.4 times their noise, and none of 471
re-timed versions of the same book did as well. The first half of the sample earned 106, the second 28. Without the
two collapse months of 2022 (May, November) it is 43.

*What is different from R22.* There, only the most frenzied tenth mattered. Here the whole ranking is in order: the
lowest tenth falls 86 behind its peers over the week, the highest four tenths each gain about 40–45.

*What it does not say.* **Can it trade profitably? Not shown yet.** This is a measurement before costs, not a book. What
trading these names cost in 2022 is not known; the second half alone is near the cost; and R21 showed that a real
ranking can still lose money once it is traded (at a one-day hold). Nothing here is licensed to trade.

| step | what | state |
|---|---|---|
| 1 | registration R23, committed before anything else | ✅ 2026-09-29 (d80bd0e) |
| 2 | the universe of the 17 blocks, frozen as `ft2/screen_members_pre.csv` | ✅ 141 names, 60 in every block, none of the twelve (e7a7b45) |
| 3 | downloads to the work VM | ✅ 01:50 UTC: 141 of 141 names, 0 errors, 0 bad checksums |
| 4 | build and tests, committed before the run | ✅ `horizon.run_pre`, `tests/test_p8_pre.py`; 92 pass (28b2c61, 85923e8) |
| 5 | R22 re-run after the ingest and compared; input check | ✅ 02:31 UTC: largest difference 0.0; every old row unchanged |
| 6 | the run, as registered | ✅ 03:01 → 03:11 UTC |
| 7 | the read | ✅ validity PASS, then the gate: CLEARS. Stage 2 not run; work VM stopped |

**Result (R24, 2026-09-29), in plain words. Traded with costs, does the idea leave money? On the data already read:
a little, and not yet for certain.** The book buys the six names the open-interest score ranks highest and sells the six
it ranks lowest, one position per name, held 7 days; every position pays the exchange's fee, the spread, the price
impact and funding. It was run on both samples that had been read for the score (2021-12 → 2023-04 and 2023-05 →
2024-08): 5,054 positions, about five new ones a day, 24–34 open at a time.

Per position of 10,000 USDT held a week: **39 USDT earned before costs, 21 paid in costs, 17 left.** Both samples are
positive (22 and 12). With the estimated spread and impact doubled, 8 is left. The same positions with each day's
direction chosen by a coin lose 18 on average and do as well as the real book one time in forty — that is the test the
book passed, and by the rule written beforehand it makes the book a CANDIDATE.

*What it does not show.* **Can it trade profitably? Not shown yet.** The 17 is about as large as its own noise: the
honest range is from −17 to +51. The second half of the early sample lost 13. All of the money made against the market
comes from the names that were SOLD (names in a trading frenzy); the names that were bought added nothing. And both
samples had already been looked at — only months nobody has read can confirm it.

*In money, if it were real:* about 36 positions a week × 17 USDT ≈ 600 USDT a week, with about 29 positions of 10,000
USDT open — roughly 0.2 % a week on the money deployed.

| step | what | state |
|---|---|---|
| 1 | registration R24, committed before anything else | ✅ 2026-09-29 (3c94437) |
| 2 | build and tests, committed before any run | ✅ `audit.pool`; 94 pass (db75795) |
| 3 | costs for the early months, old rows checked | ✅ 06:42 UTC: largest difference 0.0 |
| 4–6 | run PRE, run F12, their book checks, the pooled read | ✅ 06:45 → 07:58 UTC, one job after the other |
| 7 | the read | ✅ validity PASS, then the gate: CANDIDATE. Work VM stopped |

**Result (R25, 2026-09-29), in plain words. Did the book confirm on months nobody had read? It passed its test — on a
number that turned out not to be money. In actual money it lost.** The run was made once, as registered, on 69 unread
weeks (2024-09 → 2026-01, 216 names). By the harness's figures it looked far better than expected: 70 USDT left per
position of 10,000 a week, and no coin-direction book came close. That was too good, so the trades were checked one by
one — and the way the harness counts profit is wrong for this kind of trade.

*The defect.* The harness counts a trade in *log returns*, a shortcut that is accurate for small price moves. These names
move 25 % or more in a week in one trade out of ten. On such moves the shortcut overstates every sold position and
understates every bought one. Example: a name falls from 4.9 to 1.0. A sold position of 10,000 USDT made 7,960; the
harness booked 15,900. Another name rose from 1.13 to 17.96: a sold position of 10,000 lost 149,000 (unless the exchange
closed it first); the harness booked a loss of 27,700. This book's sold names are its wildest ones.

*The same trades counted as a position earns* (per position of 10,000 USDT a week, after costs):

| sample | as the harness counted | actual | actual, a sold position's loss capped at its size |
|---|---|---|---|
| 2021-12 → 2023-04 (R24) | +22 | **−11** | −9 |
| 2023-05 → 2024-08 (R24) | +12 | **−17** | −10 |
| 2024-09 → 2026-01 (R25, the unread months) | +70 | **−39** | +32 |

The last column assumes the exchange closes a sold position once it has lost its whole size. It is a different rule,
looked at after the fact, and in the unread months one single trade makes most of its difference.

**Can it trade profitably? No — not as measured in money.** The chain from R22 to R25 was built on a number that
flatters exactly this bet. Nothing is licensed. What is NOT affected: the paper test of R14 (P7) stores prices, not
profits, and R14's own backtest is slightly better in actual returns (+39 against +34), because its money is on the
bought side.

| step | what | state |
|---|---|---|
| 1 | registration R25 | ✅ (a8eb67e) |
| 2–5 | build, universe frozen, downloads, ingest and the three checks | ✅ all PASS |
| 6 | the run, made once | ✅ 15:20 → 15:52 UTC |
| 7 | the read | ✅ validity PASS; the gate's letter: CONFIRMED; the measure defective — verdict HELD. Work VM stopped |

**Result of the re-execution (2026-09-30), in plain words. Counted as a position actually earns, is anything left of
the open-interest idea? No. Every link of the chain R22 → R25 was the way of counting.** Vadim chose to fix the
measure and run the four reads again exactly as registered (§3 "The unit of money", "The re-execution `actual`"). Each
re-run was first checked to be the same read — the same cells or the same trades, prices, costs and funding as the
first time, to the last digit — so only the unit differs. Per position of 10,000 USDT, a week's hold:

| read | what it asked | first read (log returns) | re-executed (actual returns) | verdict now |
|---|---|---|---|---|
| R22 | on the months that chose the idea: does the top tenth earn more than the bottom tenth? | +59 before costs, 1.5 times its noise | **+21**, 0.7 times its noise | nothing clears (as before) — the lean is mostly gone |
| R23 | the same on 71 weeks nobody had read | +67 before costs, 2.4 times its noise — passed | **+20**, 1.1 times its noise; second half negative; +3 without the two collapse months of 2022 | does not pass ("go on": above the cost, not certified) |
| R24 | traded with costs, both samples already read | +17 after costs, coin test passed (1 in 40) | **−14** [−53, +25]; both samples lose; a coin's direction does as well 4 times in 10 | not funded |
| R25 | the same book on 69 unread weeks | +70 after costs — passed on a number that was not money | **−39** [−189, +110]; a coin does as well 1 time in 2 | **NOT CONFIRMED — the book is parked** |

Why the unit mattered so much here: the names the ranking puts at the bottom — names in a trading frenzy — do fall
behind in the typical week (the median is 250–300 USDT below their peers). But a few of them rise two-, four-,
sixteen-fold, and a sold position pays for that rise in full. Log returns shrink exactly those rises, so the mean
looked like money. In R25's months a single name (MYX) decides the result.

One more thing the check turned up. The harness charges funding (what holders of a position pay each other every few
hours) on the position's size at entry. A sold position in a name that has risen sixteen-fold pays funding on sixteen
times that. Counted so, R25's loss is 67 a trade, not 39; on R24's samples the difference is nothing (0.05). It changes
no verdict; it is a change the harness needs before another book of this kind is read (§7).

**Can anything outside the twelve trade profitably yet? No.** Eight reads (R18–R25) have now found nothing on names
outside the twelve that clears its costs. R14 on the twelve (P7, paper trading) is not touched by any of this and reads
slightly better in actual returns (§3's table: +39 against +34; R16 +41 against +33).

| step | what | state |
|---|---|---|
| 1 | the unit corrected, tests, the protocol written | ✅ a5c47a1, before any re-run |
| 2 | R1–R21: one table from saved fills, no new verdict | ✅ 3c99450 (§3) |
| 3 | R22 → R25 re-executed, one chain, 06:38 → 08:33 UTC | ✅ all validity PASS, all four "same as the first read" PASS |
| 4 | the four reads, one commit each | ✅ 88be475, ba37154, 55dc239, 18e27ff. Work VM stopped |

**What next — two decisions for Vadim. DECIDED 2026-09-30: "(A1) (B1)" — stage 2 of R23 is not run; the search on names outside the twelve is parked, P7 keeps running, F5 stays unread, and the next question is chosen in a fresh session. Nothing of P8 runs until then.** The options as they were put:

**Decision A — R23's "go on": read its stage 2, or not?** R23 was registered in two stages. Its re-executed verdict
("go on") offers the second stage: the same before-costs number on the outside names of 2024-09 → 2026-01, pooled with
the first stage. It was meant for months nobody had read; since then R25 has read those months for this very idea.
- **(A1) — recommended: do not run it.** Costs nothing. Those months are no longer unread; the book built from this
  number lost on them (R25); and a pass would only license that book, which has now been run on all three samples and
  lost on each. The open-interest score is closed as a trade idea at this hold.
- **(A2) run it.** About 15 minutes on the work VM, no download. We would learn whether the before-costs number is
  there on those months; whatever it says could not be acted on, for the reasons above.

**Decision B — what the screener phase does next.**
- **(B1) — recommended: park the search on outside names; keep P7 running; pick the next question in a fresh
  session.** F5 (37 weeks) stays unread. Before any new registration Claude makes the one harness change named above
  (funding on the position's value) — small, tested, no verdict depends on it.
- **(B2) a book with a protective stop** (close a sold position once it has lost a set share of its size). A new rule
  and a new registration; it could be explored on the three samples already read and confirmed only on F5 or on months
  still to come. The evidence for it is thin: with a sold position's loss capped at its size the book still loses on
  R24's two samples (−9) and is positive on R25's (+32) because of one trade.
- **(B3) new information** (PLAN §9: ETF flows, US indices, events) — a ceiling audit first, as P2 did; its own
  registration.

The decision of 2026-09-29 → 2026-09-30, for the record — how to correct the record after R25; **Vadim chose (1)**:

- **(1) — recommended. Fix the measure, then re-execute R22, R23, R24 and R25 exactly as registered.** The harness and
  the label count the actual return of a position (one change, tested against known cases); the four reads are run
  again with their registered commands on the same cells; the new verdicts replace the old ones and both stay on
  record. About half a day, no download. What to expect, from the re-pricing already done: R24 not funded, R25 not
  confirmed; R22 and R23 unknown until measured. The earlier harness reads (R1–R21) get one table of "as measured /
  actual" from their saved trades, no new verdicts.
- **(2) Accept the re-pricing above as the record.** Cheaper: no re-run; R25 is written down as not confirmed in actual
  returns, the book parked. R22's and R23's statistic stays unmeasured in actual returns.
- **(3) After (1) or (2): a book with a protective stop** (close a sold position that has lost a set share of its size)
  is a NEW rule and needs its own registration. Every sample except F5 (37 weeks) has now been read, so it could be
  explored on the read samples but confirmed only on F5 or on months still to come.

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

- **The always-on serve host (decided and created 2026-09-25):** `fluxtrader2-serve`, `e2-small`, 20 GB, Debian 12,
  `me-central1-b`, ≈ 13–15 USD a month, for P7's hourly paper-trading job only; same venv, no Docker; runbook `docs/SERVE.md`
  (with the build). It is a fluxtrader2 host: fluxtrader1's collector is a data source and nothing of this project runs there.
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
- **Always-on host:** `fluxtrader2-serve` (above), built out 2026-09-25: `docs/SERVE.md` is its runbook and reinstall list.
- **Deliberately not first:** any sequence model or deep network; anything trained on the book
  data alone; any reinforcement learning. Each is a capacity increase on a problem whose ceiling
  is not yet known.

## 7. Parked

| item | why parked | revival trigger |
|---|---|---|
| ~~R1 stage 2 — the confirmation read of `reversal4h`~~ — **CLOSED 2026-09-21** | Needed from Vadim: nothing. The rule's premise (pair-level reversal) was a statistical artefact (R7) and its profit was the market's bounce in a rising market (R3, R4). F3 stays unspent | none; the bounce lives on as R8 |
| **The market's bounce, conditional on the trend (`trendfall4h`, R8; supersedes H1 / `panic4h`, R4)** — PARKED by its own stage-1 gate 2026-09-21; **Vadim decided (a) on 2026-09-22: leave it parked, do not read F3–F5 for it** | Needed from Vadim: nothing. On 4.3 seen years the rule earns +52 bps a trade after costs [+26, +77] (p 0.005), but 2022 came in at −5.9 against a bar of −5 written beforehand, and three half-years lose 18–92. The confirmation folds stay unspent for this question | only a measured observable that separates the losing half-years (2022-H1, 2023-H1) — a new ceiling registration, not a variant of this rule; F5 growing by ~6 months does not by itself re-open the (b) question |
| **H2 tail continuation (`rankcont4h`, R5)** — PARKED on cost 2026-09-21, FP+F0 unread; **on the 40-pair universe CLOSED 2026-09-22 (R10)** | Needed from Vadim: nothing. Twelve names: gross +12.5 a leg, hedged +14.2 [+1.8, +26.5], net −0.2 taker / +4.9 maker. Forty names, four a side (R10): gross +1.6, hedged +1.8 [−3.5, +7.0] on 9,360 legs, MDE 7.4 — the effect is absent with power, and R5's long-side asymmetry reversed. Do not re-open on breadth | only a lower fee tier for the twelve-name version (VIP 1 / BNB discount takes 1–2 bps off a round trip) — and R10 says the twelve-name gross may itself be the upper tail of noise, so that read would need FP+F0 first (R5 stage 2, still unspent) |
| **The candle-feature ridge (`ridgebook`)** — on the WIDE universe CLOSED 2026-09-23 (R12, R13 A); **on the twelve, held out (R14): the F3+F4 confirmation read R16 (2026-09-25) FAILED on the shuffle null only, every other criterion passed and the numbers reproduced (net +33, hedged net +25, IC 0.043, flip p 0.005) — CLOSED by the gate as written; R15 (full feature set) FAILED the same day** | Vadim chose P7 paper trading by override, 2026-09-25 (R16 Result); serve host `fluxtrader2-serve` created the same day; the serving path BUILT and its replay identity check PASSED the same day (P7). LIVE since 2026-09-25 17:00 UTC. Needed from Vadim: nothing. Forty: IC 0.0075 held out (t 1.3), 0.009 in pair — no candle signal on the 32 added 2022-era names; at 4h nothing clears 15 bps. Twelve: IC 0.034 in pair (R13 B) and **0.033 held out (R14, t 2.1)** — the signal transfers to WLD, SOL, PEPE, AVAX from models that never saw them, and to none of the seven older names; the book +34 net [+6, +62], hedged net +13 [−8, +34], flip p 0.01, **shuffle p 0.085 (bar 0.05; null p95 +41 against a +33 effect)** | CLOSED on the twelve by R16's gate; F5 unread. R16's failing null had no power (p95 +104 vs +33); R14 is the best measured candidate and stays so unless a new registration beats it. R15 parked: paired gain +0.001 (t 0.1), net +2.7, hedged net −4.3 on 4,033 trades — the twelve extra columns add nothing held out. Live: P7 paper trading of R14 under R17, running since 2026-09-25 17:00 UTC (`docs/SERVE.md`; R17's read at ≥ 600 trades and ≥ 6 months, earliest 2027-03-25) |
| **Open interest as a rank book (`oibook`, R21)** — **CLOSED 2026-09-28** | Needed from Vadim: nothing. On R18's 188 names, F1+F2, the data that chose the three features: taker net −17.3 [−28.9, −5.8], maker −9.6 [−21.2, +2.0], gross +1.6, flip p 0.50. The score's rank IC is +0.034 (t 5.2) and all of it is the two lowest tenths (the most violent names) falling behind; top minus bottom is +12 bps a leg in the mean on all cells, under the cost | none for the book: no other k, weights, hold or side on these cells. The features stay candidates for a model's inputs (R20: NOT DETECTABLE). A longer horizon is a new question (P8 "What next" (1)), not a revival |
| **The open-interest score at a 7-day hold, names outside the twelve (R22–R25)** — **PARKED 2026-09-30: re-executed in actual returns, R25 NOT CONFIRMED** | Needed from Vadim: nothing — R23's offered stage 2 is not run (his "(A1)", 2026-09-30). The first reads counted a trade in log returns, which overstates shorts and understates longs by half the squared move; this book shorts the most violent names. First read → re-executed: R22 the score at 7 days +58.9 → +20.7 a leg (u 1.54 → 0.68); R23 +66.7 → +20.4 (u 2.43 → 1.13, CLEARS → GO ON); R24 net +17.2 → −13.9 [−52.9, +25.1], flip p 0.025 → 0.42 (CANDIDATE → NOT FUNDED); R25 net +69.9 → −39.4 [−189.3, +110.5], flip p 0.005 → 0.51 (NOT CONFIRMED; −66.7 with funding counted on the position's value). The ranking is real (rank IC +0.02 … +0.04, the median in order); the mean is not there for a sold position | none proposed. As registered: F5 with the months that accrue (a new registration, Vadim's decision) or a measured lower cost — the gross before costs is +11.6, +3.2, −5.6 on the three samples, below the round trip's cost on each. A book with a protective stop is a new rule and a new registration (capped at a short's size: −9.3 on R24's samples, +32.5 on R25's, one trade); the only unread months left for outside names are F5 and what accrues |
| ~~**The harness charges funding and the exit leg's costs on the size at entry**~~ (§3 "The unit of money"; found 2026-09-30, R25 (E4)) — **DONE 2026-10-01** | Needed from Vadim: nothing. On small moves it was nothing (R24's samples: +0.05 bps a trade); on a short of a name that rises many-fold it understated the loss (R25 net −39.4 as counted, −66.7 in full; two MYX shorts). No verdict depended on it. Changed 2026-10-01: `backtest.load_costs` carries `fundval` (Σ rate × the close at the event), `price` charges each funding payment ÷ the entry close and the exit leg × exit ÷ entry, `horizon.labels` the same for the longer-hold label; a run's meta says `"charged": "value"`. Tests: `test_p3.py::test_funding_and_the_exit_leg_are_charged_on_the_positions_value`, `::test_load_costs_values_funding_at_the_close_at_the_event`. Reference reproduced on the work VM from the saved decisions (`scripts/charged_check.py`, `output/backtest/charged_check/`): PASS 2026-10-01 07:13 UTC — R25 (2,368 trades) net -66.74 against -66.74, R24 pooled (5,054) net -13.83 against -13.83, largest difference over every statistic of the four samples 5.7e-14 bps; the gross unchanged trade by trade | none. P7's ledger (R17) is untouched: its exit leg's funding stays in bps of the size at entry (one-day holds on the twelve) |
| learned decision layer / end-to-end model | capacity not yet earned (P6) | registered P5-vs-oracle contrast shows money left on the table |
| **±1 % book imbalance as a rule (`bookimb1d`, R9; long-only R11)** — PARKED by their own stage-1 gates 2026-09-22 | Needed from Vadim: nothing. R9 (both sides, top decile of \|imb\|): −2.2 taker [−25, +21], gross +8, 9 trades a day. R11 (long only, top decile of ask-heaviness): +5.1 taker [−25, +35], gross +20.7 but hedged +2.0 [−4, +8], flip p 0.12 — the long side earns with the market, not against it. The screen's pooled IC lives in the slow per-pair level of the imbalance, which neither a daily short nor a daily long collects at 12 bps a round trip | (b) a demeaned imbalance (today's minus the pair's trailing-month mean) as a new ceiling screen, not a rule; (c) book features inside P5's ridge, which is where a slow level belongs (all 24 features beat the 11 candle ones: 1d 0.067 vs 0.048) — **READ as R15 2026-09-25: out of pair on the residual the gain is +0.001 (t 0.1); parked**. The screen's IC on these columns was the in-pair own-move reading of a slow level, and neither a rule nor the ridge collects it. No further fixed rule on the raw imbalance; (b) stays open as a screen |
| sequence / deep models | P2 #5 (2026-09-20): a depth-2 tree never beats ridge (equal at best, t −3 to −5 on short windows) and the curve falls with more history | a registered contrast in P5 where the tree beats ridge outside the noise floor |
| 1m candles over the full history | 23M rows, not needed for horizons ≥ 15m | P1 or P2 asks for sub-15m horizons |
| ~~relative (pair-vs-basket) *reversal* at 4h~~ — **CLOSED 2026-09-21 (R2)** | the rank rule loses −20.6 bps per leg [−31.7, −9.5] in all six quarters; do not re-open as a reversal bet | none. The opposite sign (tail continuation) is a new hypothesis, H2 in P5, not a revival of this row |
| caps and inverse-vol sizing on `reversal4h` — **CLOSED 2026-09-21 (R3)** | both lower the t; the capped-away trades were the profitable ones | none; R3 forbids further variants of this kind |
| ~~directional 1d with short refits~~ — **CLOSED 2026-09-21 (R7)** | the short-window advantage was the biased statistic; unbiased, 30–60 days score −0.006 … +0.011 and all history 0.048 | none |
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

### R7 — P2's directional numbers re-read with an unbiased IC (registered 2026-09-21, before the re-run; read 2026-09-21)
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
Result:        **Read 2026-09-21 (commit 237240a holds this block as written before the read; `output/ceiling.md`): directional 4h
               is NOT FUNDED — it fails the first condition.** Best single feature at 4h: `depth_imb_1` −0.017, p_fw 0.060
               (> 0.05). The ridge passes its two: IC 0.030, p 0.025, ≥ 0.015. The reversal features: `ret_4h` at 4h −0.0425
               (t −4.9) → −0.0128 (t −1.2, p_single 0.26); `ret_1d` −0.0451 → +0.0047; `ret_1h` −0.0297 → −0.0057; at 1h and
               1d the same. The relative screen reproduced to the digit, as required. Against the expectation: the
               reversal ICs did not shrink to 0.015–0.025, they went to zero — the artefact was the whole signal, not
               half of it; the ridge (0.030) held up better than expected (0.01–0.02), and "short refits beat all history"
               reversed (30–60 days 0.011, all history 0.029). Vol ICs moved by ≤ 0.02, as expected. Consequences: P2's
               table rewritten, R1's premise withdrawn (P4), §7's rows for 1d short refits and for book features updated.

### R8 — trendfall4h: buy the market's fall only while its 30-day trend is up (registered 2026-09-21, before the rule saw any real bar; stage 1 read 2026-09-21: gate FAILED by 0.9 bps on 2022; stage 2 not read)
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
Result:        **Stage 1, read 2026-09-21 (commit 808f1e5 holds this block as written before the read;
               `output/backtest/trendfall4h/report.md`): GATE FAILED on its third condition → PARKED, no confirmation fold read.**
               taker net +51.91 bps [+26.38, +77.45], se 13.0, MDE 36.5, 3,384 trades on 288 of 1,578 days (2.1 a day), right
               63.7 %, gross +65.6, hedged −0.03 (all of it is the market, by construction); shuffle p 0.005, flip p 0.005.
               maker +54.87 [+29.70, +80.05]. By fold: FP +69.8, F0 −11.0, F1 +69.3, F2 +19.9. By calendar year (taker net,
               trade-days): 2020 +64.6 (61), 2021 +102.8 (78), **2022 −5.9 (43)**, 2023 +43.5 (63), 2024 +19.9 (43) — the bar
               was −5, written first, so it holds (as R5's +4.92 against +5 did). By half-year the regime is still visible:
               2022-H1 −17.9, 2023-H1 −24.1, 2024-H2 −92.4 (ten days; 2024-08-05 is the worst day of the sample, −11,630 bps
               summed over its trades); the best days are all 2020-11 → 2021-05. Against the expectation: gross higher
               (66 vs 40–55), se as guessed (13 vs 9–12), 2022 inside its range (−10 … +5) — and on the wrong side of the bar.
Power:         Written 2026-09-21 for whoever revives it. se 13.0 on 1,578 days → F3 alone (243 days) se ≈ 33, MDE ≈ 93:
               a true +52 confirmed about 1 time in 3, a true +25 about 1 in 8. F3+F4+F5 pooled (~745 days) se ≈ 19,
               MDE ≈ 53: a true +52 about 4 times in 5, a true +25 about 1 in 4. Only the pooled read is worth making.


### R9 — bookimb1d: trade against a lopsided ±1 % book for a day (registered 2026-09-22, before the rule saw any real bar; stage 1 read 2026-09-22: gate FAILED on its first condition; stage 2 not read)
Question:      R7's re-read left one per-pair directional signal that clears the screen: the ±1 % book imbalance at 1d
               (IC −0.039, family-wise p 0.005, 87.5 % of months the same sign; relative IC −0.032, p_fw 0.015). Does it
               make money after costs as a fixed rule with no model — and is the money the pair's own, or the market's?
Rule:          `ft2/rules.py::BookImbalance` = P2's `depth_imb_1` exactly as screened (one definition, `ceiling.depth_frames`,
               now shared by the screen and the rule): (bid − ask notional within ±1 % of mid) / their sum, from the archive
               book's last 30 s sample strictly before t. A bid-heavy book precedes a fall, so side = −sign(imb), one unit,
               288 bars (1 day), one position per pair, executed 1 bar later — only when |imb| is at or above the pair's
               q_sig 0.90 quantile of |imb| over the 120 days before each 30-day block (refitted by the harness; nothing
               inside the block is used). Why 0.90 and not a searched value: P2's cost bars (`ic_needed`, #7) were written
               for "trade the top decile of signals", so the rule trades the top decile. Why 1d and not 4h: 4h missed the
               family-wise bar (−0.017, p_fw 0.06); at 1d a round trip is 3 % of the typical move (taker 12.3 vs 385 bps).
               No candle feature enters. Parameters fixed here and not searched: q_sig 0.90, window 120 days, hold 288.
Contrast:      mean net bps per unit of notional vs zero and vs both nulls; primary execution `taker` (path-independent, as
               R8); `maker` and `maker_ev` reported. The HEDGED gross (gross minus side × the other pairs' move) is the
               second reading: it says whether the trade earns against the market or with it. Long and short apart.
Folds read:    stage 1: F1+F2 — the folds the screen read, so a mechanical gate (costs, fills, the book rule's effect on
               a 1-day hold, the day-clustered se), NOT evidence. FP and F0 cannot check this rule: the archive book
               starts 2023-01-01 (DATA.md), 120 days before F1.
               `ft2 backtest bookimb1d --folds F1 F2 --execs taker maker maker_ev`
               stage 2: F3 alone, once: `ft2 backtest bookimb1d --folds F3 --registration R9 --execs taker maker maker_ev`
               — unless stage 1's se says F3 alone cannot tell (Power, below); then the read waits for Vadim's decision on
               pooling F3+F4, as R8's row in §7 does. No parameter changes between the stages.
Gate:          stage 1 → stage 2 only if ALL of: taker net > 0 AND the larger p ≤ 0.05 AND hedged gross > 0 (a positive
               net with hedged ≤ 0 is market timing wearing a book, R8's lesson: parked, not pursued) AND taker net ≥ −5 bps
               in each of F1 and F2 (a rule that loses a whole 8-month fold is a regime bet). Fail → PARKED with the
               numbers, no variant tried on F1+F2 (a demeaned or a ±5 % version is a NEW registration, not a tweak).
               Stage 2: CONFIRMED if the taker interval's lower bound > 0 AND the larger p ≤ 0.05; REFUTED if the upper
               bound < 0; else NOT DETECTABLE with the MDE.
Expectation:   Stage 1: gross +20 to +30 (0.039 × 1.755 × 385 ≈ 26 for the top decile of a standardised signal; the
               imbalance is not normal, so this is loose), taker net +8 to +18, maker +12 to +22 if fills are as P1
               measured (unknown: the resting order sits on the thin side of a lopsided book). 2–6 trades a day on ~480
               days (the imbalance persists, so a pair re-enters most days it is extreme), 1,000–3,000 trades, up to 12 open
               at once. se 15–25, MDE 40–70: the point estimate is likelier than not to be positive and INSIDE the noise —
               then the gate fails on p and the rule is parked as "real in the screen, not shown in money on F1+F2".
               Hedged gross positive but below gross (the relative IC is 0.032 against 0.039). Shorts (bid-heavy books)
               and longs both positive; if one side carries everything, say so, change nothing.
Power:         written after stage 1 from its se, before any confirmation read: F3 alone (243 days) has about half the days
               of F1+F2, so se_F3 ≈ se × √2; the read is worth making only if a true effect of stage 1's size is found
               there at least one time in two.
Result:        **Stage 1, read 2026-09-22 (commit 69bd804 holds this block as written before the read; `output/backtest/bookimb1d/report.md`):
               GATE FAILED on its first condition (taker net > 0) → PARKED, no confirmation fold read, no variant run.**
               taker net −2.23 bps [−25.15, +20.68], se 11.7, MDE 32.7, gross +8.04, hedged +6.74 [−2.16, +15.63], right 50.0 %;
               shuffle p 0.050, flip p 0.164. maker +2.40 [−20.53, +25.33] (96 % of legs filled), maker_ev +2.55. 4,411 trades on 485
               days — 9.1 a day, 176,018 decisions of which 4,427 taken: the imbalance persists, so nearly every pair re-enters the
               day its position closes; 5.95 positions open on average. F1 −1.5 / F2 −2.9 (taker). Against the expectation: gross
               +8 where +20 to +30 was written, trades 9 a day where 2–6 were, se 11.7 where 15–25 was. The one thing the run
               says beyond "not there": **79 % of the trades are shorts** (3,481 bid-heavy books vs 930 ask-heavy — the top decile
               by size is mostly the bid side), and the two sides differ: longs on ask-heavy books +46.9 gross, +31.8 taker net
               [−5.4, +69.0] on 930 trades; shorts on bid-heavy books −2.3 gross, −11.3 net. Per pair the sign flips (ZEC +36,
               WLD +44, LINK +25 vs PEPE −59, AVAX −38). Reading: the screen's pooled IC (−0.039) is carried by the LEVEL of a
               pair's imbalance over weeks (a persistently bid-heavy book while the pair drifts down), which a rule that shorts
               that pair every day cannot turn into money at 12 bps a round trip; the tail the rule can trade (an ask-heavy
               book, rare) looks different but was not registered as its own question. Both are new registrations, not
               variants of this one (§7).


Template:

```
### R10 — rankcont4h on the wider universe, four names a side (registered 2026-09-22, before the rule saw any real bar of the 32 new pairs; stage 1 read 2026-09-22: gate FAILED on gross; stage 2 not read)
Question:      R5 found H2 (a pair torn away from the others keeps going) real before costs — +12.5 bps gross a leg, hedged
               +14.2 [+1.8, +26.5] — and eaten by them on twelve names (net −0.2 taker / +4.9 maker, bar +5). Its own revival
               trigger was "a wider universe where the tails are 3–5 names a side". Is it more than a round trip costs there?
Universe:      `ft2/universe.py::WIDE` — the 40 USDT perpetuals with the highest MEDIAN daily quote volume over 2022-04-18 →
               2022-08-17 (the four months before F0) that have a 1d bar on every day of that window; chosen by `ft2 universe`
               on 2026-09-22 05:19 UTC from 854 archive symbols and frozen in code before any 5m bar of the 32 new pairs was
               read (output/universe_wide.md has the ranking). Nothing after 2022-08-17 entered the choice. Eight of the
               twelve are in it; ZEC ranked 50th, PEPE / WLD / HYPE did not exist. Delisted names (WAVES, UNFI, OGN, …)
               stay in: the harness trades the pairs present at each bar, so there is no survivorship in F1+F2.
Rule:          `ft2/rules.py::RankContinuation(k=4)` = R5's rule with four names a side, nothing else touched (q_disp 0.90,
               120 days, hold 48): long the 4 pairs furthest ABOVE the others over 4 hours, short the 4 furthest below; the
               i-th lowest and the i-th highest are one unit (both legs or neither); the trigger (the gap between the two
               extremes ≥ its q_disp quantile) is R5's. k = 4 of 40 is the top decile each way — the same fraction P2's cost
               bars were written for; k was fixed here, not searched.
Cost:          the 8 measured pairs from the tape (P1, `data/cost_daily.parquet`); the 32 others from `ft2 costwide` —
               ONE pooled regression log(cost) ~ log(range) + log(dollar volume) + log(tick) fitted on the twelve's tape
               days, its leave-one-pair-out error on the twelve in `output/cost_wide.md`, the fitted spread never below the
               day's tick. Funding from the archive for all 40. The proxy is read before the backtest; the rule's numbers
               are not. Every read is run twice: as priced, and with spread + impact doubled (`--cost-mult 2`).
Contrast:      mean net bps per leg vs zero and vs both nulls (shuffle, flip); `taker` and `maker` both reported; the primary
               execution is the better of the two by stage 1's point estimate, fixed for stage 2 (as R5).
Folds read:    stage 1: F1+F2 (exploration):
                 `vm.sh run backtest rankcont4h --param k=4 --universe wide --execs taker maker --name r10_rankcont4h_k4`
                 `vm.sh run backtest rankcont4h --param k=4 --universe wide --execs taker maker --cost-mult 2 --name r10_rankcont4h_k4_cost2`
               stage 2: FP+F0, once, same universe and parameters, after the 32 new pairs' klines from 2020 are fetched:
                 `vm.sh run backtest rankcont4h --param k=4 --universe wide --folds FP F0 --registration R10 --execs taker maker`
               (FP carries one bias the twelve did not: a pair delisted before 2022-04-18 cannot be in the universe.)
Gate:          stage 1 → stage 2 only if the primary net ≥ +5 bps per leg as priced (R5's bar, unchanged). Before stage 2 is
               read, the proxy is checked on the new pairs with a two-week tape sample per pair (`ft2 tape --symbols …`,
               2024-07): if the sampled spread + impact differs from the proxy by more than ×1.5 on the median new pair, the
               stage 1 ledger is RE-PRICED (not re-decided) at the sampled cost and the gate applied again. Below the bar:
               H2 is PARKED again with "real before costs, not tradable at VIP 0 on forty names either" and its next
               revival is a lower fee tier only. Stage 2 verdicts as in R4. No parameter changes between the stages.
Expectation:   Gross a leg like R5's (+8 … +15: the tails of 40 at the decile are about as extreme as the two ends of 12);
               the 32 new pairs cost more to cross (half spread + impact at 10k ≈ 1.5–4.5 bps a leg against 0.5–1.5 on the
               twelve), so taker net ≈ +1 … +8, maker ≈ +3 … +10; R5's long leg carried everything (+20.7 gross vs +4.3),
               expect the same asymmetry. About 8 legs per trigger, 15–30 legs a day, ~10,000 legs on F1+F2; legs of one bar
               are correlated, so se ≈ 3 and MDE ≈ 8. Likeliest: the primary net lands within ±3 of the bar — the read decides.
Result:        **Stage 1, read 2026-09-22 (output/backtest/r10_rankcont4h_k4, _cost2): the edge is not there. Gross +1.6 bps a leg,
               hedged +1.8 [−3.5, +7.0] on 9,360 legs (19.3 a day), MDE 7.4 — R5's +12.5 gross and the expected +8 … +15 are excluded.
               Taker net −14.6 [−19.8, −9.4]; maker net −7.4 [−12.5, −2.3] (gross −2.7: the resting orders that fill are the ones the move
               ran through). Costs doubled: −20.9 / −7.9. Both nulls agree (p 0.10–0.29: a loss of exactly the cost, i.e. no skill).
               → GATE FAILED on its first condition (primary net −7.4 vs +5), FP+F0 NOT read, no tape sample needed: the cost
               proxy is not what decided it. Per fold F1 gross +5.1, F2 −2.5. R5's asymmetry did not repeat: the long leg (torn
               upwards) is −6.1 gross here, the short +9.3, where R5 had +20.7 / +4.3 — the twelve-name asymmetry was noise.
               Per pair: BCH +62 gross on 274 legs is the one outlier; 26 of 40 pairs are within ±20 with intervals over zero.
               Reading: the "torn-away pair keeps going" effect R5 saw on twelve large names does not exist across forty at the
               decile, and the read had the power to see it. H2 on the wide universe is CLOSED; on the twelve it stays parked
               on a fee tier only (§7). What the run leaves behind that is useful: a 40-pair universe with clean 5m history and
               a priced (if rough) cost for every name — the material P5's forecast layer needs for the new goal (§0): a model
               fitted on some pairs and scored on others.**

### R11 — bookimb1d, long only: buy the ask-heavy book (registered 2026-09-22, before the rule saw any real bar in this form; stage 1 read 2026-09-22: gate FAILED on p, and the gross is the market's; stage 2 not read)
Question:      R9 traded both sides of the ±1 % imbalance and lost; 79 % of its trades were shorts on bid-heavy books, and the
               rare long side — an ask-heavy book — earned +46.9 gross, +31.8 taker net [−5.4, +69.0] on 930 trades. R9's
               result named this a new question, not a variant. Is an ask-heavy book, taken as its own signal with its own
               cut, worth a long position for a day after costs?
Rule:          `ft2/rules.py::BookImbalance(side="long")` = R9's rule with two changes and nothing else: long only, and the cut
               is the pair's q_sig 0.90 quantile of −imb (the top decile of ask-heaviness itself) over the 120 days before
               each 30-day block, instead of the top decile of |imb|. Same feature (`ceiling.depth_frames`), one unit, 288
               bars, one position per pair, executed 1 bar later. Why the cut changes: R9's pooled cut on |imb| let the
               bid-heavy side set the bar, so the long side fired only at the far tail (930 of 4,411); a question about the
               ask-heavy book must set its bar on the ask-heavy books. q_sig 0.90, window 120, hold 288: R9's, not searched.
Contrast:      mean net bps per unit of notional vs zero and vs both nulls; primary `taker`; `maker` and `maker_ev` reported;
               hedged gross as the second reading (the trade must earn against the market, not with it).
Folds read:    stage 1: F1+F2 — the data on which R9's long side already showed +31.8, so this is a MECHANICAL read (does the
               decile cut, with ~3–5× the trades, keep a positive net outside the noise?), NOT evidence.
               `ft2 backtest bookimb1d --param side=long --folds F1 F2 --execs taker maker maker_ev --name r11_bookimb1d_long`
               stage 2: F3 alone, once: `ft2 backtest bookimb1d --param side=long --folds F3 --registration R11 --execs taker maker maker_ev`
               — the read that counts, unless stage 1's se says F3 alone cannot tell (Power); then it waits, as R8's row in §7.
Gate:          stage 1 → stage 2 only if ALL of: taker net > 0 AND the larger p ≤ 0.05 AND hedged gross > 0 AND taker net
               ≥ −5 in each of F1 and F2. Fail → PARKED with the numbers; no third cut, no 4h, no ±5 % version on F1+F2
               (each would be a new registration). Stage 2: CONFIRMED if the taker interval's lower bound > 0 AND the
               larger p ≤ 0.05; REFUTED if the upper bound < 0; else NOT DETECTABLE with the MDE.
Expectation:   The decile of −imb is milder than R9's 930 far-tail longs, so less per trade and more of them: gross +10 to
               +30, taker net 0 to +18, maker a few bps better if the resting bid on an ask-heavy book fills as P1 measured;
               3,000–5,000 trades (6–10 a day), se 10–15, MDE 30–40. Likeliest: net positive but inside the noise (p 0.05–0.3),
               so the gate fails on p and the answer is "consistent with R9's tail, not shown" — exactly what a mechanical
               read on seen data is worth. If instead p ≤ 0.05 and hedged > 0, F3 decides.
Power:         written after stage 1 from its se, before any confirmation read: F3 has about half the days of F1+F2, so
               se_F3 ≈ se × √2; the read is worth making only if a true effect of stage 1's size is found there at least
               one time in two.
Result:        **Stage 1, read 2026-09-22 (output/backtest/r11_bookimb1d_long): taker net +5.1 bps [−24.8, +35.0], se 15.3, MDE 42.7 on
               4,106 trades (8.5 a day, 5.5 open on average); gross +20.7 — but HEDGED +2.0 [−4.0, +8.1]: the ask-heavy book
               earns with the market, not against it (R8's lesson, now on a book signal). Shuffle p 0.045, flip p 0.119 → the
               larger p fails the gate. maker +10.3 [−19.7, +40.2] (96.5 % of legs filled), maker_ev +9.9. F1 +14.8 / F2 −3.9
               (both above the −5 floor). Funding −3.4 a trade (a long pays it). Per pair PEPE +73 gross / +58 hedged on 338
               trades and SOL +35 / +31 carry it; eight pairs hedge to within ±10 of zero, WLD −45. → GATE FAILED, PARKED,
               F3 not read. As expected ("positive, inside the noise"), with one thing the expectation did not say: the hedged
               gross is a tenth of the gross, so even a confirmation would have confirmed market exposure. Reading: R9's
               +47-gross long tail was a small, market-carried sample; the ask-heavy book is not a per-pair signal worth a
               day's long at these costs. The book row in §7 keeps its (b) and (c): a demeaned imbalance as a ceiling screen,
               and the book inside P5's ridge — where R7 measured the level's value (1d IC 0.067 vs 0.048 without).**

### R12 — ridgebook: P5's forecast layer, fitted on 30 pairs and scored on the 10 it never saw (registered 2026-09-23, before the strategy saw any real bar; stage 1 read 2026-09-23: gate FAILED on (i), (iii) and (v); stage 2 not read)
Question:      §0's goal is a model that trades pairs it was not trained on. R7 left one funded directional signal — a ridge
               on the 11 candle features (IC 0.030 at 4h, 0.048 at 1d, walk-forward IN pair, twelve names) — and R10 left a
               40-pair universe with clean 5m history and a priced cost. Does that forecast survive being applied to pairs it
               never saw, and does a closed-form decision on it make money against the market after costs?
Strategy:      `ft2/forecast.py::RidgeBook` (`ridgebook`; the module docstring is the specification). Universe `universe.WIDE`
               (40, R10's, unchanged). Hold-out: group g = every 4th name of WIDE in its volume-rank order starting at g
               (g = rank index mod 4; ten names each, spanning the liquidity range); a pair in group g is scored ONLY by the
               ridge fitted on the other 30. Features: `ceiling.dir_features` (the P2 set, one definition) + hour of day
               (sin, cos) = 12 columns, standardised on the training rows. Label: the harness's y (gross bps, execution to
               exit at `hold`) / (σ_1w·√hold), clipped ±5, MINUS the mean over the training pairs present at the bar
               (≥ 5) — the move against peers, so the forecast carries no market direction. Model: RidgeCV over
               ceiling.ALPHAS, no intercept, refitted every 30-day block on every hourly row whose label ended before the
               block (all history from 2022-08-18, as the harness builds the market for F1+F2). Decision grid: bars on the
               hour (24 a day a pair). Forecast f = ẑ·σ_1w·√hold in bps. Trade when |f| ≥ 15 bps (a taker round trip of
               ~12.5 on the twelve + 2.5 margin; the thin names cost more, which the `--cost-mult 2` twin covers), side =
               sign(f), one position per pair (harness), size = (|f|/15)·(σ_ref/σ_h)² floored 0.25, capped 2 (expected value
               over variance; the harness weights means by size, bps stay per unit). Fixed here, not searched: groups 4,
               grid 12, min_bps 15, cap 2, min_pairs 5, ALPHAS, no intercept.
               Two arms, both read: PRIMARY hold 288 (1d: R7's larger IC, and a round trip is ~3 % of the typical move);
               secondary hold 48 (4h). The 4h arm is expected to clear 15 bps on very few cells — that is its reading.
Cost:          as R10 — the 8 measured pairs from the tape, the 32 others from `ft2 costwide`; funding from the archive; every
               read twice, as priced and with spread + impact doubled.
Contrast:      taker net per unit of notional vs zero and vs both nulls (shuffle: the fit is re-walked on day-shuffled labels,
               200 draws; flip: the book's own days' sides flipped); `maker` reported; **hedged net** (net minus side × the
               other pairs' move, the hedge leg uncosted — added to the harness for this read) is the second number; and the
               held-out IC of ẑ against the realised move vs peers on the whole decision grid (`forecast.md`, pooled, day-
               clustered t, per fold and per held-out group) is the third: the forecast has to be real out of pair whether
               or not the trade pays.
Folds read:    stage 1: F1+F2 (exploration), 4 jobs in parallel on the work VM (OMP_NUM_THREADS=1 each):
                 `backtest ridgebook --param hold=288 --universe wide --execs taker maker --name r12_ridgebook_1d`
                 `backtest ridgebook --param hold=288 --universe wide --execs taker maker --cost-mult 2 --name r12_ridgebook_1d_cost2`
                 `backtest ridgebook --param hold=48  --universe wide --execs taker maker --name r12_ridgebook_4h`
                 `backtest ridgebook --param hold=48  --universe wide --execs taker maker --cost-mult 2 --name r12_ridgebook_4h_cost2`
               stage 2: F3 alone, once, primary arm, same parameters — after the 32 new pairs' klines 2024-09 → 2025-05 are
               fetched (`ft2 archive klines/5m --universe wide --monthly --start 2024-09-01 --end 2025-05-01`) and
               `ft2 costwide` re-run to cover them:
                 `backtest ridgebook --param hold=288 --universe wide --folds F3 --registration R12 --execs taker maker`
               No parameter changes between the stages.
Gate:          stage 1 → stage 2 only if ALL of, on the PRIMARY arm as priced, taker: (i) net > 0; (ii) hedged net > 0;
               (iii) the larger of the two null p ≤ 0.05; (iv) net ≥ −5 bps in each of F1 and F2; (v) the held-out IC on
               the grid (all groups pooled) has t ≥ 2. A pass on the 4h arm alone opens nothing (a new registration would).
               Fail → PARKED with the numbers; no variant on F1+F2 (a different threshold, grid, feature set or target is a
               NEW registration). If (v) passes and (i)–(iii) fail, the forecast is real out of pair but not tradable at this
               cost: record that, and the next registration is the demeaned book imbalance as a ceiling screen (P5 step 8),
               not another threshold. Stage 2: CONFIRMED if taker hedged net's lower bound > 0 AND the larger p ≤ 0.05;
               REFUTED if the hedged net's upper bound < 0; else NOT DETECTABLE with the MDE.
Expectation:   Held-out IC at 1d 0.02–0.04 (R7's in-pair 0.048 less what is pair-specific), t 2–4 on 485 days; per group
               within ±0.02 of the pooled. Forecast sd ≈ IC × σ_1d ≈ 8–15 bps, so 10–25 % of cells clear 15 bps; with one
               position per pair for a day: 20–35 trades a day, ~12,000 on F1+F2, se ≈ 3, MDE ≈ 6–8. Gross a trade +8 … +18
               if the forecast is roughly calibrated (the calibration table says); hedged ≈ gross (the target is the residual);
               taker cost 12.5 on the majors, 14–19 on the thin names → taker net −6 … +4; maker net higher by ~5 but its fills
               select against the forecast (R10). Costs doubled: net 4–8 lower. Likeliest: (v) passes, (i)–(iii) do not —
               "real out of pair, not tradable at VIP 0 with candle features alone", and the book row's (c) becomes the next
               question. 4h arm: < 3 % of cells clear 15 bps, a few hundred trades, uninformative on money; its IC (0.01–0.03)
               is the number worth keeping.
Result:        **Stage 1, read 2026-09-23 (commit 620f1c8 holds this block as written before the read; output/backtest/r12_ridgebook_1d,
               _1d_cost2, _4h, _4h_cost2; forecast.md next to each report): GATE FAILED — the forecast does not survive the pair
               hold-out, and it rarely clears the cost.** The three numbers, primary arm (1d):
               (v) held-out IC on the 462,705 grid cells: **0.0075, t 1.26** (F1 0.003, F2 0.013; per group 0.001 / 0.016 / 0.008 / 0.007,
               the best single group-fold 0.037 at t 2.3, F2 group 1); se ≈ 0.006, so an IC of 0.02 is at the edge of the interval and
               R7's in-pair 0.048 is far outside. Calibration by forecast decile: flat — decile 10 (mean forecast +11.5 bps) realised −5.6
               vs peers, decile 1 (−10.1) realised −5.2. Only **3.2 % of cells clear 15 bps** (expected 10–25 %): the forecast's spread is
               ~4 bps, not 8–15, and the cells that clear it are the wildest names (PEOPLE 15 %, ENS 9 %, WAVES 7 % of their cells; ADA,
               SANDS, THETA under 0.5 %).
               (i)–(iv) money, taker as priced: 1,648 trades (3.4 a day), gross −28.1, hedged +3.5 [−29.6, +36.5], **net −44.3 [−101.0,
               +12.4], hedged net −12.7 [−45.9, +20.5], MDE 81** — the trades sit on the most volatile pair-days, so the money read has
               no power (an 81-bps MDE against a +5 bar). F1 +0.5, F2 −120.3 (iv fails on F2); shuffle p 0.77, flip p 0.83 (iii fails).
               Maker −39.0. Costs doubled: −50.8 / −39.4. Long −24.4 (hedged −20.8), short −52.3 (hedged +13.3).
               4h arm: **0.0 % of cells clear 15 bps** (49 trades on F1+F2 — the forecast's spread at 4h is ~1 bps); IC 0.0012, t 0.32
               (F1 −0.001, F2 +0.005); calibration flat. Its `--cost-mult 2` twin: −152.7 [−421.2, +115.8] on the same 49 trades — nothing.
               Against the expectation: the IC came in at a quarter of the low end (0.0075 vs 0.02–0.04) and the forecast's spread at a
               third, so (v) failed where it was expected to pass; the rest failed as expected but for a reason not foreseen — too few,
               too wild trades rather than a cost shortfall. Verdict: **PARKED (§7)**. What it does not say: whether the loss is the hold-out
               (a pair-specific signal, §0's goal at stake) or the change of target and universe (R7's 0.048 was the pair's OWN 1d move on
               twelve names; this is the move against peers on forty). That is R13's question, registered below.**

### R13 — ridgebook in pair: is R12's missing IC the hold-out, or the target and the universe? (registered 2026-09-23, before the in-pair runs saw any real bar; read 2026-09-23: (b) — the universe)
Question:      R12's out-of-pair IC at 1d is 0.0075 (t 1.3) where R7 read 0.048 in pair — but R7 was the pair's OWN move on the twelve
               collector names, and R12 is the move AGAINST PEERS on forty. Which change lost it? If the same pipeline fitted in pair
               (every pair's model has seen its own bars) recovers the IC, the candle signal is pair-specific and does not transfer —
               §0's "trained on other pairs" goal cannot be met with candle features alone. If it does not, there is no candle signal in
               the 1d move against peers at all, in or out of pair, and R7's number was the market-laden own move.
Contrast:      `ridgebook --param holdout=false`, everything else R12's (hold 288, grid 12, same features, same residual label, same
               walk-forward in time; the four "groups" now share one model fitted on all pairs, itself included). Two arms:
                 A  the forty: `backtest ridgebook --param hold=288 --param holdout=false --universe wide --execs taker maker --draws 20 --name r13_ridgebook_1d_inpair`
                 B  the twelve collector pairs (R7's universe, this pipeline's target and grid):
                    `backtest ridgebook --param hold=288 --param holdout=false --execs taker maker --draws 20 --name r13_ridgebook_1d_inpair12`
               The statistic READ is the grid IC in `forecast.md` (pooled, t clustered by day; per fold and per group) against R12's
               0.0075 — a diagnostic of the forecast, not a trading read: the P&L rows and the 20-draw nulls are reported and not
               applied to any gate (the in-pair number is optimistic by construction and is not a candidate rule).
Folds read:    F1+F2 (exploration; R12's cells).
Gate:          (a) A ≥ 0.02 with t ≥ 2 → the signal is pair-specific: the candle-only ridge is CLOSED for the cross-pair goal (§7), and
               the next question is what a pair-level component looks like (a per-pair intercept / level is a NEW registration, not a
               variant). (b) A < 0.02 and B ≥ 0.03 with t ≥ 2 → the thin names or the residual target lost it: the candle signal lives
               in the majors' own move; record and close the candle ridge on the wide universe. (c) both < 0.02 → no candle signal in
               the 1d move against peers anywhere at this power: the candle-only ridge is CLOSED on this target, and the next
               registration must bring new observations (the book, §7 (b)/(c)) — on the twelve, where the book exists.
Expectation:   A 0.015–0.03, t 2–4 (an in-pair fit knows each pair's level of the features); B 0.02–0.04. Likeliest (a) or (b) at the
               boundary: half the gap from R12 to R7 is pair-specificity, half the target.
Result:        **Read 2026-09-23 (commit a483366 holds this block as written before the read; output/backtest/r13_ridgebook_1d_inpair,
               _inpair12): outcome (b) — the universe lost it, not the hold-out.**
               A, the forty in pair: IC **0.0086, t 1.5** (F1 0.004, F2 0.013; 2.6 % of cells clear 15 bps) — the same as R12's held-out
               0.0075. Fitting each pair on its own bars changes nothing on the forty: there was no candle signal to lose. Money (reported,
               not read): 1,410 trades, net −77.9 [−153.7, −2.0], p 0.90.
               B, the twelve in pair (a walk-forward in time, every pair fitted on its own past): IC **0.0341, t 2.2** (F1 0.017, F2 0.050);
               16.2 % of cells clear 15 bps; calibration monotone in the top tail — decile 10 (mean forecast +30 bps) realised +78 gross,
               +38 vs peers. Per pair the IC is carried by four names: WLD 0.123 (t 2.2; 44 % of its cells clear the bar), SOL 0.097,
               1000PEPE 0.076 (37 %), AVAX 0.075; BTC 0.023, ETH 0.004; ADA, XRP, ZEC, LINK negative. Money (reported, NOT a gate —
               written down here because it is a walk-forward read on exploration folds and so a hypothesis): taker, 1,915 trades
               (3.9 a day), gross +46.9, **hedged +27.0 [+5.4, +48.6], net +33.0 [+0.5, +65.5], hedged net +13.1 [−8.4, +34.6], MDE 46**;
               shuffle and flip p 0.048 (the real beat all 20 draws); F1 +35.4, F2 +31.6; long +42.9, short +17.9; maker +38.9. Per
               pair: PEPE +75 (338 trades), AVAX +73, SOL +62, WLD +55; ADA −67, XRP −12, ZEC −3; every pair's interval covers zero.
               Against the expectation: A was expected at 0.015–0.03 and came in at 0.009 — pair-specificity explains NONE of the R12 gap;
               B as expected (0.034 in 0.02–0.04). Reading: the candle signal in the 1d move against peers exists on the twelve collector
               names — young and violent ones above all — and vanishes when 32 older, thinner 2022-era names share the fit. It is a
               property of the names, not of the fit. Consequences: the candle ridge is CLOSED on the wide universe (§7); the cross-pair
               question moves to the twelve, where the signal is (R14, registered below, held out among the twelve); whether the
               in-pair twelve-name book is worth a confirmation fold is a spend question for Vadim (P5 step 9) — a single fold cannot
               resolve +33 against an MDE near 70.**

### R14 — ridgebook held out among the twelve: does the candle signal transfer between the names that have it? (registered 2026-09-23, before the held-out twelve-name run saw any real bar; stage 1 read 2026-09-24: FAIL on (iii) only — parked; stage 2 read —)
Question:      R13 put the 1d candle signal on the twelve collector names (IC 0.034 in pair) and nowhere on the wider set. §0's goal is a
               model that trades a pair it was not trained on. Held out among the twelve — four groups of three, every name scored by
               a ridge fitted on the other nine — does the IC survive, and does the closed-form book make money against the market?
Strategy:      `ridgebook`, R12's registration unchanged (hold 288, grid 12, min_bps 15, cap 2, min_pairs 5, holdout on), on the default
               twelve (`PAIRS`; HYPE absent before F4). Groups by position in PAIRS: g0 BTC/ADA/ZEC, g1 ETH/AVAX/1000PEPE, g2 SOL/LINK/WLD,
               g3 XRP/DOGE — so the two names that carried R13's IC (WLD, PEPE) are scored by models that never saw them. Cost from the
               tape (all twelve measured; no proxy, so no `--cost-mult 2` twin).
Folds read:    stage 1: F1+F2: `backtest ridgebook --param hold=288 --execs taker maker --name r14_ridgebook_1d_ho12` (200 draws).
               stage 2: F3 alone, once: `backtest ridgebook --param hold=288 --folds F3 --registration R14 --execs taker maker` — unless
               stage 1's se says F3 alone cannot tell (a single fold's MDE ≈ 65–75 bps against a +33-sized effect); then the read waits
               for Vadim's decision on pooling F3+F4, as R8/R9 did. No parameter changes between the stages.
Gate:          as R12's, taker as priced: (i) net > 0; (ii) hedged net > 0; (iii) the larger null p ≤ 0.05; (iv) net ≥ −5 in each of
               F1 and F2; (v) held-out IC on the grid, all groups pooled, t ≥ 2. Pass → stage 2 (or the pooling decision). Fail on (v)
               only → the signal is pair-specific on the twelve too: §0's transfer goal is CLOSED for candle features, and the in-pair
               book (R13 B) is what remains, a spend question. Fail otherwise → parked with the numbers, no variant on F1+F2.
Expectation:   IC 0.01–0.025, t 1–2.5 (R13's in-pair 0.034 less the part WLD/PEPE/SOL learn about themselves); 8–14 % of cells clear
               15 bps; ~1,500 trades, MDE ≈ 50; net −10 … +25, hedged net −20 … +15. Likeliest: (v) borderline, (i)–(iii) not met —
               "some transfer, not enough to trade at this cost" — and the decision goes to Vadim as P5 step 9.
Result:        **Read 2026-09-24 (commit 9e75dc5 holds this block as written before the read; output/backtest/r14_ridgebook_1d_ho12,
               200 draws): stage 1 FAILS on (iii) only — the signal transfers, the money does not clear the shuffle null. PARKED by the
               gate; no stage-2 read is licensed by this block; the confirmation-fold question goes to Vadim (P5 step 9).**
               Held-out IC on the grid, all groups pooled: **0.0328, t 2.08** (F1 0.016, t 0.75; F2 0.049, t 2.12) — against R13 B's
               in-pair 0.0341: holding a name out of its own fit costs 0.001. By group: g1 ETH/AVAX/PEPE 0.055 (t 2.2), g2 SOL/LINK/WLD
               0.070 (t 2.1), g0 BTC/ADA/ZEC −0.020, g3 XRP/DOGE −0.020. Per name, scored by a model that never saw it (R13 in pair in
               brackets): WLD 0.113 (0.123), SOL 0.096 (0.097), PEPE 0.078 (0.076), AVAX 0.075 (0.075); BTC −0.001 (0.023), ETH 0.000,
               LINK −0.007, ZEC −0.021, ADA −0.042, XRP −0.049. 16.5 % of cells clear 15 bps (WLD 41 %, PEPE 42 %, AVAX 20 %, SOL 18 %,
               BTC 2 %). Calibration monotone at the top: decile 10 forecast +31 → realised +79 gross, +40 vs peers.
               Money, taker: 1,896 trades (3.9 a day), gross +48.0, hedged +26.8 [+5.9, +47.8], **net +34.2 [+6.1, +62.3], MDE 40**,
               hedged net +13.0 [−7.9, +34.0]; F1 +30.3 [−16.8, +77.5], F2 +36.5 [+1.7, +71.4]; long +51.3 (hedged +15.9), short +9.5
               (hedged +9.0); maker net +39.8 [+11.0, +68.6]. Nulls: flip p 0.010 (null sd 15.8); **shuffle p 0.085 — null mean −20.9,
               sd 43.5, p95 +41.0**. Per name (bps per unit of notional): WLD +67, SOL +65, PEPE +63, AVAX +63, LINK +55, DOGE +41,
               BTC +32, ETH +28, ZEC −11, XRP −26, ADA −35; every interval covers zero; the four carriers hold 96 % of the summed P&L.
               By quarter (unweighted mean net): 2023Q2 −5, Q3 +5, Q4 +27, 2024Q1 +43, Q2 +25, Q3 −16.
               Gate: (i) net > 0 PASS; (ii) hedged net > 0 PASS; (iii) larger null p ≤ 0.05 **FAIL** (0.085); (iv) F1, F2 ≥ −5 PASS;
               (v) held-out IC t ≥ 2 PASS. Power of (iii): the shuffle null's p95 is +41.0, so a true +33 (the size expected, and read)
               could not have passed it at this sample — the fail reads "not distinguishable from a random forecast on these names with
               this rule", not "no effect". The stricter flip null (the same trades, each day's sides randomly signed) is beaten at
               p 0.01: the sides carry information. What a ridge fitted on shuffled labels earns per trade on the same wild names is
               simply ±43 wide, so per-trade money is a weak statistic here.
               Against the expectation: IC above the 0.01–0.025 band (0.033) and equal to in pair — no part of R13's IC was the names
               learning about themselves; trades as expected (1,896 vs ~1,500); net above the band (+34 vs −10 … +25); hedged net inside
               it (+13). Reading: **what nine names teach about the 1d residual move applies unchanged to WLD, PEPE, SOL and AVAX — young,
               violent names with a large share of forecasts over the bar — and not at all to BTC, ETH, ADA, XRP, ZEC, LINK, DOGE.** That
               is the shape §0 asks for (a screener that picks names of a kind, a model fitted on others), with four names and
               2023Q4–2024Q2 carrying the money. Consequences: parked by (iii), no variant on F1+F2. A confirmation read on F3+F4 pooled
               is a NEW registration (R15 or later), written before the read, if Vadim funds it (P5 step 9); nothing in R14 changes for it.

### R15 — ridgebook on the P2 screen's full feature set, held out among the twelve: do the book, flow and positioning features add to the transfer signal? (registered 2026-09-25, before the run saw any real bar; read 2026-09-25: gate FAILED on (ii) and (vi) — the features add nothing held out; parked; R16 reads R14 alone)
Question:      R14 put the transferring 1d candle signal at IC 0.033 (t 2.1) on the twelve, and the book on it at +34 net, failing only
               its shuffle null (p 0.085; null p95 +41). P2's screen (R7) read the full 24-feature set at IC 0.067 against the candle
               set's 0.048 — but on the pair's OWN 1d move, in pair, all history. Does that gain exist on the residual target, out of
               pair, and does it move the book clear of its null? Vadim's decision (B), 2026-09-25: read this on F1+F2 first, then spend
               the pooled F3+F4 read once, on the arm(s) R16 names (below) — not on the candle book alone.
Strategy:      `ridgebook --param features=all`: R14's registration unchanged (hold 288, grid 12, min_bps 15, cap 2, min_pairs 5,
               holdout on, four groups by position in PAIRS, cost from the tape, taker as priced) with the design widened from 12 to
               26 columns: `dir_features` (10), `candle_extras` (range position 1d, dollar volume 1h) and the twelve `EXTERNAL` ones —
               tape flow 1h/1d and effective spread 1h; open-interest change 1h/1d, global and top-trader long/short z, taker ratio 1h
               (archive metrics, the row stamped ts used from ts + 5 min); ±1 % and ±5 % depth imbalance and the ±1 % depth level
               (archive book, the last sample strictly before t); the last settled funding — plus hour of day. ONE definition,
               `ceiling.external_features`: the ridge is fitted on what the screen screened. A cell with any NaN feature gets no
               forecast (the archive sources start 2023-01, before F1; PEPE and WLD from listing; an outage → ffill ≤ 3 bars, then NaN).
               Inside the same run a second ridge on the 12 candle columns is fitted per rotation on the same training bars with its own
               NaN mask — it IS R14's model — and its forecast is kept as `f_ref_bps`: the paired reference.
               Command (VM): `backtest ridgebook --param hold=288 --param features=all --execs taker maker --name r15_ridgebook_1d_ho12_all`
               (200 draws). Validity check, read first: `forecast.md`'s "reference, its own cells" IC must reproduce R14's 0.0328 (t 2.08);
               if it does not, the run is void and the cause is found before any other number is read.
Contrast:      (a) the money rows and nulls as R14, taker as priced; (b) the held-out IC on the grid, all groups pooled; (c) the PAIRED
               IC gain over the reference on the common cells (both forecasts present), each day's share of the pooled correlation
               differenced and t clustered by day (`forecast.md`, "Paired against the candle-only reference").
Folds read:    F1+F2 (exploration; R14's cells less those without an external feature). No stage 2 of its own: the confirmation read is R16.
Gate:          (i) net > 0; (ii) hedged net > 0; (iii) the larger null p ≤ 0.05; (iv) net ≥ −5 in each of F1 and F2; (v) held-out IC
               t ≥ 2; (vi) paired gain over the reference t ≥ 2. R15 JOINS R16 as an arm if (i), (ii), (v) and (vi) pass — the features
               add to a signal that transfers, and the book on it makes money before and against the market; (iii) and (iv) are
               reported and decide nothing here (R14 failed (iii) on this sample, and testing exactly that on fresh data is what R16 is
               for). Any other outcome → R15 is parked with its numbers, no variant on F1+F2, and R16 reads R14 alone.
Expectation:   Cells lost to NaN < 5 %. Held-out IC 0.035–0.045, t 2–3; paired gain +0.003 … +0.012, t 1–2 — (vi) borderline. 18–24 % of
               cells clear 15 bps; 2,000–2,500 trades; net +25 … +45; hedged net 0 … +25; shuffle p 0.03–0.15. Likeliest: (v) passes,
               (vi) fails → R16 reads R14 alone. The screen's +0.019 was in pair on the own move, where a slow per-pair level (R9's
               finding on `depth_imb_1`) counts in full; out of pair on the residual, most of it should not survive.
Result:        **Read 2026-09-25 (commit 6305aa2 holds this block as written before the read; output/backtest/r15_ridgebook_1d_ho12_all,
               200 draws, generated 2026-09-24 21:27 UTC): gate FAILS on (ii) and (vi). PARKED with its numbers; no variant on F1+F2;
               R16 reads R14 alone (arm A; one arm → p ≤ 0.05).**
               Validity first: the reference on its own cells reads IC **0.0328, t 2.08** — R14 reproduced exactly; the run stands.
               Cells lost to a NaN feature: 1,296 of 125,394 (1.0 %; bar < 5 %).
               Held-out IC on the grid, all groups pooled, 26 columns: **0.0308, t 2.95** (F1 0.024, t 1.7; F2 0.039, t 2.5). By group:
               g0 0.034 (t 1.7), g1 0.043 (t 2.4), g2 0.033 (t 1.6), g3 0.000. **Paired gain over the candle-only reference on the
               124,098 common cells: +0.0014, t 0.10** (reference 0.0294 there). The gain is a redistribution, not an addition: the
               four carriers LOSE (reference → all: PEPE 0.079 → 0.031, WLD 0.090 → 0.035, SOL 0.097 → 0.063, AVAX 0.074 → 0.046)
               and the older names GAIN (ZEC −0.028 → 0.072, ETH 0.000 → 0.057, BTC 0.002 → 0.044, DOGE 0.018 → 0.060); by fold
               F1 rises (0.011 → 0.024) and F2 falls (0.047 → 0.039). The t rises (1.9 → 3.0) because the day-to-day spread of the
               correlation shrinks, not because there is more of it.
               The wider ridge also forecasts LARGER moves for the same information: **39.7 % of cells clear 15 bps** (R14 16.5 %;
               expected 18–24 %); calibration decile 1 forecasts −45.5 and realises −15.7, decile 10 forecasts +51.8 and realises
               +66.4 (R14: +31 → +79). So the bar admits twice the trades at a third of the gross each.
               Money, taker: **4,033 trades (8.3 a day; R14 1,896), gross +14.5 (R14 +48.0), hedged +7.5 [−4.0, +19.1], net +2.7
               [−13.8, +19.2], MDE 23.5, hedged net −4.3 [−15.9, +7.2]**; F1 −4.9 [−28.2, +18.5], F2 +10.3 [−12.8, +33.3]; long +5.3,
               short +0.4; maker net +8.2 [−8.1, +24.5], hedged net +0.5. Nulls: shuffle p 0.085 (null mean −13.7, sd 11.8, p95 +8.1),
               flip p 0.030. Per name, taker net: WLD +52, AVAX +30, PEPE +28, ETH +25, LINK +18, DOGE +11, BTC +3, ZEC −5, SOL −19,
               ADA −44, XRP −50 (R14: WLD +67, SOL +65, PEPE +63, AVAX +63 …); every interval covers zero.
               Gate: (i) net > 0 PASS (+2.7, the interval covers zero); (ii) hedged net > 0 **FAIL** (−4.3); (iii) larger null p ≤ 0.05
               FAIL (0.085; reported only); (iv) F1, F2 ≥ −5 PASS (F1 −4.9, by 0.1; reported only); (v) held-out IC t ≥ 2 PASS (2.95);
               (vi) paired gain t ≥ 2 **FAIL** (0.10).
               Against the expectation: the likeliest outcome named before the read — (v) passes, (vi) fails — is what happened, and
               (ii) failed with it. IC 0.031 just under the 0.035–0.045 band with t above it; gain +0.001 under the +0.003 floor; share
               of cells 39.7 % against 18–24 %; trades 4,033 against 2,000–2,500; net +2.7 against +25 … +45; hedged net −4 against
               0 … +25; shuffle p inside its band.
               Reading: **the twelve book, flow and positioning columns carry no held-out information about the 1d residual move beyond
               what the candles carry** — the screen's +0.019 (R7) was the in-pair, own-move reading of a slow per-pair level, as R9
               found for `depth_imb_1`, and out of pair on the residual it is gone. What the columns do is spread the same IC thinly
               across all eleven names and inflate the forecast's scale, which is worse for the book: the four young names that
               carry R14's money are forecast less sharply, and the 15-bps bar fills with trades that clear it on scale, not on
               information. R14 is the stronger candidate by every money row. Consequences: R15 parked; R16 arm B is not licensed;
               the candle-only ridge (R14) goes to the confirmation read alone. Cheaper follow-ups that are NOT registered and not
               licensed here (they would be new registrations, after R16): a ridge with the forecast scale fixed to the reference's
               (the share-of-cells effect isolated from the information effect); a two-column addition (funding, taker ratio 1h)
               instead of twelve; the archive columns as a per-pair demeaned level (R9's (b)).

### R16 — the confirmation read of the twelve-name candle book, F3+F4 pooled, once (registered 2026-09-25, before R15 was read; arms FIXED 2026-09-25 by R15's gate: arm A only, R14 as registered, p ≤ 0.05; read 2026-09-25: FAIL on the shuffle null only (p 0.18, null p95 +104) — every other criterion passed and R14's numbers reproduced; CLOSED by the gate as written; Vadim's call on what closure licenses)
Question:      Does the twelve-name held-out book (R14, and R15 if it qualifies) make money after costs on data nobody has looked at?
               Vadim's decision (B), 2026-09-25: one pooled read, F3+F4, on the arm(s) named here, each arm read once.
Arms:          A: R14 as registered — `backtest ridgebook --param hold=288 --folds F3 F4 --registration R16 --execs taker maker
               --name r16_ridgebook_1d_ho12_f34`. B (only if R15 passes (i), (ii), (v), (vi) — no judgment, R15's gate decides):
               `backtest ridgebook --param hold=288 --param features=all --folds F3 F4 --registration R16 --execs taker maker
               --name r16_ridgebook_1d_ho12_all_f34`. No parameter differs from the F1+F2 runs. Both arms are run before either is
               read; the harness logs each confirmation read in `output/backtest/confirmation_reads.csv`.
               **Fixed 2026-09-25, from R15's read: arm A ONLY.** R15 failed (ii) and (vi), so arm B is not licensed and is not run;
               one arm → the null bar is p ≤ 0.05. Vadim saw R15's numbers and said go on 2026-09-25; launched with `--registration R16`
               (the read is logged in `confirmation_reads.csv`, 2026-09-25 03:57 UTC, F3 and F4).
Folds read:    F3 (2024-09 → 2025-05) + F4 (2025-05 → 2026-01), pooled, once; the twelve gain HYPE inside F4 (listed 2025-05-30). F5
               stays unread. Power: at F1+F2's rate (3.9 trades a day) ≈ 1,900 trades an arm, MDE ≈ 40 bps against R14's +34.
Gate:          per arm, taker as priced: net > 0; hedged net > 0; the larger null p ≤ 0.05 with one arm, ≤ 0.025 with two (Bonferroni
               over the arms); net ≥ −5 in each of F3 and F4; held-out IC t ≥ 2 on F3+F4. An arm that passes → P7 (paper trading) is
               FUNDED for that arm, a serving path is the next build, and P5's forecast layer is that arm. Neither passes → the
               candle-feature book is CLOSED on the twelve (two folds spent, F5 kept); the next registration must bring a new target
               or new observations, not a variant. "Not distinguishable" with the point estimate inside R14's interval is a FAIL here —
               the folds are spent either way, and the bar was written knowing the power.
Expectation:   Arm A: net +10 … +40, hedged net −10 … +20, shuffle p 0.05–0.3; F3 (a strong alt market into 2025-01, then a fall) above F4.
               Likeliest: not distinguishable → CLOSED. If arm B exists: +5 over arm A on net, same verdict.
Result:        **Read 2026-09-25 (commit e0de4ae holds this block as written before the read; output/backtest/r16_ridgebook_1d_ho12_f34,
               200 draws, arm A only): FAIL on one criterion — the shuffle null, p 0.18 — with every other criterion passed. By the
               gate as written, the candle-feature book on the twelve is CLOSED; two confirmation folds are spent; F5 stays unread.**
               Held-out IC on F3+F4, all groups pooled: **0.0427, t 2.12** (F3 0.012, t 0.6; F4 0.077, t 2.2). By group: g0 0.061,
               g1 0.037, g2 0.026, g3 0.033. Per name: ETH 0.108 (t 2.5), ZEC 0.092, DOGE 0.075, WLD 0.065, SOL 0.040, XRP 0.030,
               BTC 0.022, ADA 0.007, AVAX 0.002, PEPE −0.001, HYPE −0.014, LINK −0.052. 13.4 % of cells clear 15 bps (F1+F2: 16.5 %).
               Calibration: deciles 1–9 flat (−13 … +10 realised against −20 … +8 forecast); decile 10 forecast +28 → realised +65,
               +51 against peers. The effect is the top decile, nothing else.
               Money, taker: **1,750 trades (3.6 a day), gross +46.1, hedged +38.4 [+11.7, +65.2], net +33.1 [−0.4, +66.6], MDE 47.8,
               hedged net +25.4 [−1.3, +52.2]**; F3 +1.5 [−36.6, +39.7] on 1,036 trades, F4 +73.0 [+16.3, +129.7] on 714; long +59.4
               (hedged net +47.4 [+9.7, +85.1]), short −1.4; maker net +37.8 [+4.2, +71.3], hedged net +30.1 [+3.3, +56.8]. In money:
               +33 USDT a trade on 10,000, +120 USDT a day on up to 120,000 deployed. Nulls: **shuffle p 0.183 — null mean −15.5, sd
               109.3, p95 +103.6**; **flip p 0.005** (null sd 17.6, p95 +13.0). Per name, taker net: PEPE +84, ZEC +80 (351 trades,
               a fifth of all), DOGE +69, WLD +59, AVAX +43, ADA +23, XRP +11, HYPE +6, SOL +5, ETH −25, LINK −35, BTC −59; every
               interval covers zero.
               Gate: net > 0 PASS (+33.1; the interval's low end is −0.4); hedged net > 0 PASS (+25.4); **larger null p ≤ 0.05 FAIL
               (shuffle 0.183; flip 0.005)**; net ≥ −5 in F3 and F4 PASS (+1.5, +73.0); held-out IC t ≥ 2 PASS (2.12).
               Against the expectation (arm A: net +10 … +40, hedged net −10 … +20, shuffle p 0.05–0.3, F3 above F4): net inside the
               band at its top; hedged net above it; shuffle p inside; F4 above F3, not the reverse — the strong alt market did not
               carry the book, 2025-05 → 2026-01 did.
               Reading, plainly: **R14's F1+F2 numbers reproduced on data nobody had looked at** — net +33 against +34, hedged net +25
               against +13, IC 0.043 against 0.033, flip p 0.005 against 0.010 — and the one criterion that failed is the one this
               sample could not pass: a ridge fitted on shuffled labels earns anything in ±109 per trade on F3+F4's names (F1+F2: ±44),
               so its 95th percentile is +104 and no plausible effect clears it. That is Principle 5's case exactly — "not detectable",
               not "no effect" — and it is also exactly what this block said before the read would count as a FAIL, with the folds
               spent either way. Both statements are true and the gate decides: CLOSED. What did NOT reproduce: the carriers. On F1+F2
               the money was WLD, SOL, PEPE, AVAX; on F3+F4 the IC is ETH, ZEC, DOGE, WLD and the money PEPE, ZEC, DOGE, WLD, with
               SOL and AVAX flat and ETH negative. F3 alone (2024-09 → 2025-05) has no IC and no money; F4 has both. The long side
               earns and the short side does not. A book whose money moves between names and lives in one fold of two and one decile
               of ten is a real but thin, uneven edge — consistent with §0's shape (a model that trades names it never saw), and
               consistent with the P1/P2 reading that the 1d residual is a weak signal near the cost line.
               Consequences by the registration: CLOSED; no variant of the candle ridge on the twelve is registered again; the next
               registration brings a new target or new observations. What closure does not settle — Vadim's decision, recorded here
               when made: (1) whether R14 goes to P7 paper trading anyway, as new observations at no fold cost (the registration funds
               P7 on a pass only, so this is an explicit override of the gate on Principle 5 grounds, to be written as such); (2)
               whether F5 (2026-01 → today, ~8 months, unread) is spent on a new registration of the same question with a null that
               has power (the flip null, or the shuffle null with the money capped per trade), or kept; (3) neither — the project
               moves to a new target or new observations (§9), with R14 parked as the best measured candidate.
               **Vadim decided (1) on 2026-09-25**, after the plain-language explanation of the three options: the gate's verdict
               stands as written (CLOSED for further backtests of the candle ridge on the twelve; no variant is registered again), and
               P7 paper trading of R14 AS IS is funded by explicit override on Principle 5 grounds — the failing criterion could not be
               passed on this sample (null p95 +104 against +33), every other criterion passed, and the F1+F2 numbers reproduced. F5
               stays unread. The paper-trading read is its own registration, R17, written before any live number is looked at.

### R17 — paper trading of R14 (registered 2026-09-25, before the serving path was built and before any live number was looked at; read —)
Question:      Does R14, served live and unchanged, make money after costs on data that did not exist when it was chosen — with the
               spread measured from live quotes rather than modelled? Funded by Vadim's override after R16 (P5 step 11, option (1)).
Strategy:      R14 as registered (`ridgebook`, candle features, hold 288, grid 12, min_bps 15, cap 2, groups 4, min_pairs 5, holdout
               on, the twelve `PAIRS`), refitted every 30 days on all rows whose labels ended before the refit, served as P7 describes.
               The served model must reproduce R16's forecasts in replay (P7 identity check 1) before the ledger starts; a monthly
               causal check (identity check 2) must show no difference between the harness and the ledger, or the ledger is voided
               back to the last clean month and the cause fixed (void and re-run, never salvage).
Contrast:      The ledger priced by the harness's `price()`, taker: fee 5 bps a side as P1 read it (or the tier the account has when
               money is decided, if lower), half the LIVE spread from the ledger's own bid/ask at the execution mark plus P1's impact
               at 10,000 USDT, funding from the recorded rates; hedged against the other eleven's close-to-close move as the harness.
               Nulls: the flip null (the ledger's own trades, each day's sides randomly signed, 2,000 draws) is THE null here — the
               shuffle null has no power on these names (R16) and is reported only.
Folds read:    Live time from the first ledger row. Monthly: health and the causal check, no money number is written down. The money
               read, once: the first month-end at which the ledger holds ≥ 600 priced trades AND ≥ 6 months have passed since the
               first row. Frozen at that read; a second read is a new registration.
Gate:          net > 0; hedged net > 0; flip p ≤ 0.05; held-out IC (grid, all pairs pooled) t ≥ 2 on the live window; no month with
               a failed causal check inside the window. Pass → P7 step 2 (real money) is funded, sizing to Vadim. Fail → R14 parked
               with its live numbers; the candle ridge on the twelve is finished, and the next registration brings a new target or
               new observations.
Expectation:   At F3+F4's rate, 3.6 trades a day → ~650 trades in 6 months (MDE ≈ 75 bps on net; the flip null's sd ≈ 30). Net
               +10 … +50; hedged net 0 … +40; flip p 0.01–0.2; live half-spread within 1 bps of the tape's calibration (P1) on the
               eight liquid names, wider on PEPE, WLD, ZEC, HYPE. Likeliest: net positive, flip p borderline, IC t ≈ 1.5 — one more
               "real but thin"; the read then decides by the gate, not by the reading.
Result:        —

### R18 — the screener: the twelve's candle ridge on names it never saw, cut by what is known about a name beforehand (registered 2026-09-27, before the universe was chosen and before any 5m bar of a new name was downloaded; read 2026-09-27: (A) and (B) FAIL — NOT DETECTABLE, nothing licensed)
Question:      §0 asks for a screener that picks names and a model trained on other names. R14/R16 showed the second half among the
               twelve: the signal transfers, to SOME names (WLD, SOL, PEPE, AVAX on F1+F2; ZEC, DOGE, PEPE, WLD, ETH on F3+F4), and
               which names moves. R12/R13 A found nothing on forty names fixed in 2022 — with ridges fitted on those forty. Two
               questions, one run: (A) does the ridge fitted on the twelve carry information on names it never saw? (B) does
               something known about a name BEFORE the month — how young, how violent, how much in play, how liquid — say where
               that information is?
Universe:      `ft2 universe --screen` (`universe.screen_select`): at the start of each 30-day block of F1+F2 (the harness's own
               blocks), the 60 USDT perpetuals with the largest median daily quote volume over the 30 days before it, a daily bar on
               each of those days required, the twelve left out. With each member, from daily bars before the block only:
               `age_days` (since its first daily bar), `vol_pct` (sd of the daily log returns, 30 days), `play` (30-day median
               volume over the 180-day one; none for a name with < 90 daily bars), `liq_musd` (the 30-day median volume). Frozen
               as `ft2/screen_members.csv` and committed BEFORE any 5m kline of a member is fetched.
Strategy:      `ft2/screen.py::TransferBook` (`transferbook`; the module docstring is the specification): R14's ridge in every
               respect (12 candle columns, the residual label, grid 12, hold 288, min_bps 15, cap 2, min_pairs 5, RidgeCV, refit
               every 30-day block on all rows whose labels ended before it), ONE model fitted on the twelve, scoring the block's
               members. Relative features: against the mean of the twelve, so the model is R13 B's in-pair model to the bit —
               VALIDITY CHECK, read first: the twelve's forecasts in this run equal `r13_ridgebook_1d_inpair12/forecast.parquet`
               to 1e-6 bps on every cell, or the run is void and the cause is found before any other number is read.
Screens:       four, fixed here: `young` (lowest third of age_days), `violent` (highest third of vol_pct), `in_play` (highest
               third of play), `liquid` (highest third of liq_musd) — thirds of the block's members, re-cut every block.
Cost:          the members have no tape: `ft2 costwide`'s pooled candle proxy (it over-prices thin names, R10); every money row is
               read as priced and with spread + impact doubled. Fees VIP 0.
Contrast:      (A) the IC of the forecast on all members' cells (pooled, against the members present at the bar, t clustered by
               day). (B) per screen, the IC inside the top third and the spread top − bottom; null: random STATIC thirds (one score
               per name for the whole sample), four a draw, the largest spread t kept, 200 draws → a family-wise p. (M) the book
               re-run on the top third's name-blocks (and on all members): taker net, hedged net, flip null (the shuffle null has
               no power on wild names, R16, and is reported for the all-members book only).
Commands:      on the work VM, in this order —
                 `vm.sh run universe --screen` → `vm.sh pull` → copy output/universe_screen_members.csv to ft2/screen_members.csv, commit
                 `vm.sh bg r18_fetch archive klines/5m fundingRate --universe screen --monthly --start 2022-08-01 --end 2024-08-31`
                 `vm.sh run ingest klines funding_archive --universe all` and `vm.sh run costwide --universe all` (the archive
                 slices are rewritten whole: `all` = the twelve + R10's forty + the members; the old names' rows must come back unchanged)
                 `vm.sh bg r18 backtest transferbook --universe screen --param hold=288 --execs taker maker --name r18_transferbook_1d`
                 `vm.sh run screen r18_transferbook_1d` → output/screen/r18_transferbook_1d/screen.md
Folds read:    F1+F2 (exploration). Of the members, R10's 32 were read there by R12 / R13 A as a pooled IC of forty-name fits —
               never by this model and never by a screen. F3, F4 (read for the twelve only) and F5 are not touched.
Gate:          validity PASS, then: (A) all-members IC t ≥ 2. (B) the screen with the largest spread t has top-third IC t ≥ 2 AND
               family-wise p ≤ 0.05. (M) on the book the IC licenses — B's top third if (B) passes, all members if only (A) does —
               taker as priced: net > 0, hedged net > 0, flip p ≤ 0.05 (costs doubled: reported).
               (B) and (M) pass → a screener candidate EXISTS on exploration data; it licenses no trade. The next step is a
               confirmation registration on cells nobody has read (the rule's members on F3+F4, where only the twelve were read, or
               F5) — which fold is Vadim's decision. (B) passes, (M) fails → the screen finds the information and the book does not
               pay for it at taker cost on these names; the next registration is about execution on the screened names, not
               another screen. Only (A) passes → the model transfers without a screen; (M) on all members decides the same way.
               Neither → CLOSED for these four screens if every top third's IC and the pooled IC have an upper bound (IC + 1.96 se)
               under 0.02; otherwise NOT DETECTABLE, with the measured MDE, and it stays open (Principle 5).
               No variant on these cells under this registration. What is not blocked, and how: a different screen family is a new
               registration on the same exploration cells, and its family-wise bar counts every screen tried so far (a second
               family of four → p ≤ 0.025).
Power:         expected se of a spread ≈ 0.012 (R12's pooled se 0.006 on forty names; a third of sixty is twenty) → MDE ≈ 0.034.
               Among the twelve the contrast between the carriers and the rest was 0.08–0.10 (R14 per name). A contrast of that size
               would pass almost always; 0.04 about four times in five; 0.02 about one time in four. The read reports the MEASURED
               MDE, and a miss with the MDE above the effect is "not detectable", not "no effect".
Expectation:   110–150 names are a member at least once; ≈ 700,000 cells. Validity PASS. (A) IC 0.005–0.02, t 1–2.5. (B) `young` and
               `violent` point the right way: top-third IC 0.015–0.04, spread +0.01 … +0.03, t 1–2.5, family-wise p 0.05–0.4;
               `liquid` flat or negative. 25–40 % of the members' cells clear 15 bps; 15–25 trades a day on all members, 6–10 on a
               top third; all-members net −10 … +10; the best top third net −5 … +25, MDE 25–35. Likeliest: the screens point the
               right way and do not clear the family bar — NOT DETECTABLE, with a named size.
Result:        **Read 2026-09-27 (commit c332021 holds this block as written before the universe was chosen, a5e99e0 the frozen
               members before any 5m bar was fetched; output/backtest/r18_transferbook_1d, output/screen/r18_transferbook_1d,
               200 draws): (A) FAILS, (B) FAILS → by the gate NOT DETECTABLE for the four screens; nothing is licensed.**
               Validity first: PASS — 125,658 cells of the twelve, largest |Δ forecast| 5.7e-14 bps. One deviation: R13 B's
               forecast.parquet did not exist (R13 ran before the harness saved forecasts). R13 B's command was re-run unchanged
               as `r13_ridgebook_1d_inpair12_rerun` and tied to the original before the read: 20,287 decisions identical, 1,915
               trades, net +32.96, hedged net +13.13 in both. No other number was read before the PASS.
               (A) the forecast on names the model never saw, no screen: **IC +0.0002, t 0.03** on 694,501 cells, 188 names, 484
               days (F1 −0.004, F2 +0.004); se 0.0072, so anything above 0.014 is excluded. On the average liquid name outside the
               twelve the twelve's model knows nothing.
               (B) top-third IC / spread top − bottom (t) / family-wise p: `young` +0.0115 (t 1.1) / +0.009 (0.6) / 0.78;
               `violent` +0.0071 (0.6) / +0.005 (0.3) / 0.86; `in_play` +0.0096 (0.8) / +0.043 (2.45) / 0.070; `liquid` +0.0028
               (0.3) / +0.003 (0.2) / 0.90. No top third reaches t 2. `in_play`'s spread is its BOTTOM third being wrong (names
               whose volume is falling against their 180 days: IC −0.0335, t −2.8; F1 −0.052, F2 −0.017), not its top third being
               right; one third of twelve at |t| 2.8 is what twelve looks produce about once in seventeen. Random static screens,
               best of four: 95th percentile t 2.55.
               Power: the measured spread MDE is 0.043–0.049 (expected 0.034), so a spread under ≈ 0.045 could not have been seen;
               the top thirds' upper bounds are 0.025–0.034, above the 0.02 the gate names for closing → NOT DETECTABLE, not
               CLOSED. What IS excluded: a contrast the size of the twelve's carriers-against-the-rest (0.08–0.10), and a pooled
               transfer IC above 0.014.
               (M) reported, not licensed: all members, taker, 16,306 trades (33.6 a day): gross +8.6, net −7.9 [−29.3, +13.5],
               hedged net −20.3 [−29.8, −10.8], flip p 0.15, shuffle p 0.33; costs doubled −15.2. Best top third (`young`): net
               +2.3 [−25.8, +30.3], hedged net −6.1, flip p 0.05, maker net +11.7. In EVERY book the long side loses and the
               short side earns (all members: long −54, short +41) — the reverse of the twelve (R14 long +51, short +10; R16
               long +59, short −1).
               Against the expectation: names 188 (110–150 expected); cells as expected; (A) below its band (0.0002 against
               0.005–0.02); `young` and `violent` point the right way but under their band, `liquid` flat as expected, `in_play`
               best was not foreseen; 27–37 % of cells clear 15 bps (as expected); trades 34 a day (15–25 expected); all-members
               net inside its band; the named likeliest verdict is the one that came.
               Reading: **what the model learned on the twelve does not carry to liquid names chosen without hindsight, and none
               of the four things known beforehand finds a group where it does.** That sharpens a question about the twelve
               themselves, recorded as a hypothesis and not as a finding: the list holds HYPE (listed 2025-05-30), PEPE and WLD, so
               it was fixed after F1–F4 began — by someone who knew which names had become large. A book that is long young names
               later known to have grown would show money on the long side only, which is what R14 and R16 showed, and the sign
               flips on names picked by trailing volume. P7's paper test is not touched by this (the list precedes every live
               bar) and is the clean answer; a cheaper one is a DIAGNOSTIC screen on these same cells — "is among the most-traded
               names of 2026" (hindsight on purpose): an IC that appears there says the twelve's signal is partly the choice of
               names. New registration (R19), no fold, a day's work; the family bar counts five screens.
               Consequences: R18's four screens stay open as NOT DETECTABLE and are not re-cut; no confirmation fold is asked for.

### R19 — the hindsight diagnostic: R18's cells cut by how much a name is traded in 2026 (registered 2026-09-27, before any 2026 bar of a member was fetched; go by Vadim the same day; read 2026-09-27: NOT DETECTABLE — picking outside names by later volume does not make the forecast look skilled, and does not exclude it at the twelve's size)
Question:      R18 found that the twelve's model knows nothing about liquid names picked without hindsight, and that the long
               side loses there while it is the only side that earns on the twelve. The twelve were fixed after 2025-05, by
               someone who knew which names had become large. Does the forecast LOOK skilled on outside names when they are
               picked the same way — knowing the future? If yes, part of R14's and R16's numbers is the choice of names.
Cells:         R18's run, unchanged and not re-run: `output/backtest/r18_transferbook_1d` (forecast.parquet, decisions.parquet),
               694,501 cells of 188 members, F1+F2. The validity check is R18's and is repeated by the read.
Screen:        ONE, `hindsight` (`universe.HINDSIGHT`): per name, the median daily quote volume over 2026-01-01 → 2026-08-31
               (`hind_musd`; a day without a bar counts as zero, so a name delisted or renamed by then has 0 — the symbol is the
               name). Thirds of the block's members by it, re-cut every block, ties by symbol — R18's cut, R18's code. Frozen
               as `ft2/screen_hindsight.csv` and committed BEFORE the read. Only quote volume of 2026 is read: no price, no
               label, no forecast of F5, and none of the twelve's bars.
Contrast:      (H) the IC inside the hindsight top third, and the spread top − bottom; null: R18's random STATIC thirds, FIVE a
               draw (the family counts R18's four), the largest spread t kept, 200 draws → a family-wise p.
               Described, decides nothing: (D1) per third, the part of the IC that is the product of the two means (the
               forecast's average lean × the names' average drift) — names known to have survived drift up against the rest
               by construction, and a forecast that leans long on them earns an IC without telling one day from another;
               (D2) the book on the top third and on the bottom third: net, hedged net, long side, short side; (D3) the top
               third's cells split by R18's `young`.
Commands:      on the work VM, in this order —
                 `vm.sh run universe --hindsight` → `vm.sh pull` → copy output/universe_hindsight.csv to ft2/screen_hindsight.csv, commit
                 `vm.sh run screen r18_transferbook_1d --hindsight` → output/screen/r18_transferbook_1d_hindsight/screen.md
                 (to repeat the read: add `--reference output/backtest/r13_ridgebook_1d_inpair12_rerun` — see Result)
Folds read:    F1+F2 (exploration), the cells R18 read. No confirmation fold. F5: daily quote volume of the members only.
Gate:          validity PASS, then, on (H):
               top-third IC t ≥ 2 AND family-wise p ≤ 0.05 → SUPPORTED: the forecast looks skilled where the names are chosen
               with hindsight and nowhere else. Then R14's and R16's numbers are recorded as an upper bound that the choice of
               names flatters; the README's money line for the twelve says so; every later universe of this project is cut
               point-in-time (R18's members), and the twelve are no evidence for or against a screener.
               exactly one of the two → POINTS THAT WAY, not detectable; recorded with its size, nothing re-labelled.
               neither, and the top third's IC + 1.96 se < 0.03 (the low end of what the twelve show) → NOT SUPPORTED at the
               twelve's size: choosing by later volume does not reproduce the twelve's IC; the hypothesis in this form is
               dropped and the twelve's signal is recorded as specific to those names.
               neither, upper bound ≥ 0.03 → NOT DETECTABLE.
               Whatever the verdict: no trade is licensed (the screen cannot be traded), P7 runs on unchanged under R17 — it
               is the clean answer, because the twelve were fixed before every live bar — and no variant of this screen (other
               window, other cut, volume growth instead of volume) is read under this registration. Not blocked: the
               positioning family (§9 #6) as its own registration, its family bar counting these five.
Power:         R18 measured the se of a top third's IC at ≈ 0.0105 and the spread's MDE at 0.043–0.049; the best of five random
               screens reaches t ≈ 2.6 one time in twenty. So a top-third IC of 0.033 (the twelve's, held out) reaches t 2
               about six times in seven, 0.02 about one time in two — but the family bar on the spread needs top − bottom of
               about 0.045, which an IC of 0.033 on top passes only if the bottom third is wrong rather than empty (spread
               0.033 → about one time in four; 0.05 → about two in three). SUPPORTED is therefore hard to reach; POINTS THAT
               WAY is the verdict this test can give with good odds if the effect is the twelve's size.
Expectation:   15–30 % of the 188 names have a 2026 median of zero. The top third is mostly old large names (BNB, LTC, BCH,
               DOT …) with the few that grew. Top-third IC +0.005 … +0.025 (t 0.5–2.3), bottom third −0.010 … +0.010, spread
               0 … +0.03 (t 0–1.8), family-wise p 0.2–0.9. (D1) the top third's mean residual is positive, the bottom third's
               negative, and the means' product is under a third of any IC found. (D2) top third: long side −20 … +30 against
               −54 on all members, short side 0 … +40 against +41; bottom third: long side worse than −54. Likeliest: NOT
               DETECTABLE on the IC, with the long side's money moving the way the hypothesis says.
Result:        **Read 2026-09-27 (commit c01ab5a holds this block as written before any 2026 bar of a member was fetched, 4b95fec the
               frozen volumes before the read; output/screen/r18_transferbook_1d_hindsight, 200 draws): top-third IC t 1.15,
               family-wise p 0.90 → neither; the top third's upper bound is 0.038 ≥ 0.03 → by the gate NOT DETECTABLE.**
               One deviation, in the order of reading: the command as registered leaves out `--reference
               output/backtest/r13_ridgebook_1d_inpair12_rerun` (R18's reference; the default path holds no forecasts), so
               the first read printed NO REFERENCE above its numbers. Re-run with the reference: PASS, 125,658 cells, largest
               |Δ forecast| 5.7e-14 bps, every number identical. The cells are R18's run, which passed the same check before
               R18 was read; the read stands. The command to repeat it carries `--reference`.
               The characteristic: 38 of 188 names have a 2026 median of zero (20 %; the archive keeps flat zero-volume bars
               for a delisted contract, so 180 names have a bar on every day); 6–15 of a block's 60 members are gone. Top of
               the list: BNB 316 M USDT a day, SUI 171, TAO 115, NEAR 107, ENA 99, BCH 90. 31 names are in a top third.
               (H) top third **IC +0.0141 (t 1.15)**, middle −0.0220 (t −2.0), bottom +0.0088 (t 0.8); spread top − bottom
               **+0.0053 (t 0.34), family-wise p 0.90**; random static screens, best of five: 95th percentile t 2.68. Per fold
               the top third is −0.006 on F1 and +0.031 on F2. Power: spread MDE 0.044; the top third's se is 0.0123, so an IC
               above 0.038 is excluded there and the twelve's 0.03–0.05 is not.
               (D1) the names that survived do drift up against the rest (mean residual +0.016 on top, −0.014 at the
               bottom), but the forecast does not lean (mean −0.001): the product of the means is −0.0008 of the IC — nothing.
               (D2) taker, top third: 4,566 trades, gross +20.1, net +5.6 [−18.4, +29.7], hedged net −10.4 [−26.4, +5.5],
               flip p 0.035, long side −23.0, short side +39.2. Bottom third: net −17.4, hedged net −19.6, long −74.0, short
               +37.5. Hindsight moves the long side by 51 bps and leaves the short side where it was — the direction the
               hypothesis names — but the long side still LOSES on names known to have survived. The twelve's signature
               (R14 long +51, short +10; R16 long +59, short −1) is not reproduced by choosing on later volume.
               (D3) the top third's cells that are also in R18's `young` top third: IC +0.0312 (t 1.59) on 58,848 cells; the
               rest of the hindsight top third +0.0077 (t 0.5); young without hindsight +0.0051 (t 0.4). The one place the
               twelve's size appears, under t 2, one of three described cuts: a hint, not a finding.
               Against the expectation: zero-volume share, top-third IC, bottom third, spread, family-wise p and the means all
               inside their bands; the top third's long side −23 just under its band (−20 … +30), the short side inside;
               the middle third at t −2.0 was not foreseen (one third of three, the sign no hypothesis names). The named
               likeliest verdict is the one that came.
               Reading: **knowing which outside names are still heavily traded in 2026 does not make the twelve's model look
               skilled on them. The hypothesis "the twelve's result is the choice of names" is neither supported nor
               excluded by this cut; what it predicted about the long side's money happened in direction and not in sign.**
               Consequences: R14's and R16's numbers are not re-labelled. P7 is untouched. This screen is not re-cut (no other
               window, no volume growth, no young × hindsight screen under this registration). Five screens are now counted
               on these cells. After R10, R12, R13 A, R18 and R19 the candle ridge has shown nothing on any universe but the
               twelve: the next registration on outside names should bring new information, not another cut of this forecast.

### R20 — what the information the model does not use says about a name's next day, on names picked without hindsight (registered 2026-09-28 on Vadim's go, before any metrics or premium file of a member was fetched; read 2026-09-28: 0 of 12 clear — seven CLOSED, five NOT DETECTABLE; open interest over volume the nearest, t 3.98, family-wise p 0.060 against 0.05)
Question:      Five registrations (R10, R12, R13 A, R18, R19) looked for the candle ridge's signal outside the twelve and found
               none. Before any model: does funding, the perpetual's premium over spot, open interest, the long/short ratios
               or the taker flow of a name say which way it moves over the next day AGAINST the other members? A ceiling audit
               in P2's sense (Principle 2) — no model, no book, no fold spent.
Cells:         R18's, exactly: the scored cells of `output/backtest/r18_transferbook_1d` (hourly decision bars of F1+F2,
               embargoed; the block's 60 members, the twelve left out; 694,501 cells, 188 names). Label: R18's — the move from
               the close one bar after t to the close 288 bars later, over σ_1w·√288, clipped at ±5. VALIDITY CHECK, read
               first: the audit's own labels equal R18's on every cell to 1e-6 and the cell count is R18's, or the run is
               void.
Features:      twelve, fixed here, each from data known strictly before t (a metrics row stamped ts is used from ts + 5 min, a
               premium bar from its close, a funding rate from the bar after its funding time):
                 funding_last      the last settled funding rate, per 8 h (rate × 8 / interval), bps
                 funding_7d        the mean of the settled per-8-h rates of the 7 days before t
                 premium_1h        the mean premium index (perpetual over the spot index, minus one) of the last 12 bars, bps
                 premium_1d        … of the last 288 bars
                 oi_chg_1d         log open interest (contracts) now minus 288 bars ago
                 oi_chg_1w         … minus 2,016 bars ago
                 oi_turn           log of open interest (USDT) over the dollar volume of the last 288 bars — "crowded"
                 global_ls         log of the long/short ratio of all accounts
                 global_ls_chg_1d  its change over 288 bars
                 top_ls            log of the long/short ratio of the top traders' positions
                 top_vs_global     top_ls − global_ls: the large accounts against the crowd
                 taker_1d          the mean of the log taker buy/sell volume ratio over the last 288 bars
Statistic:     P2 #3's for the relative bet (`ceiling._ic_xs`): per bar, the Spearman correlation across the members present
               (≥ 5 with feature and label) of the feature with the label; averaged per day; mean over days, HAC t (2 lags).
               ONE horizon (1d, the only one whose move clears the cost, P2 #7, R12), ONE bet (relative): a family of twelve.
Null:          P2 #4's: the labels' whole days trade places (`ceiling._shuffle_days`, no day receives one of the 8 days
               before it), whole rows move, 200 draws; per draw the largest |t| of the twelve → a family-wise p. A name keeps
               its own labels, so a link between a name's lasting LEVEL of a feature and its drift over the sample survives
               in the null and earns no credit: only what varies in time can pass. (A lasting level is a choice of names, and
               188 names cannot certify one.)
Described:     R18's forecast by the same statistic on the same cells (the reference row); per feature the share of cells
               covered, the IC per fold and the share of months with its sign; the IC at which trading the top tenth breaks
               even on these names at taker cost (P2 #7's formula on the members' priced round trip).
Commands:      on the work VM, in this order —
                 `vm.sh bg r20_metrics archive metrics --universe screen --start 2023-04-01 --end 2024-08-31`
                 `vm.sh bg r20_premium archive premiumIndexKlines/5m --universe screen --monthly --start 2023-04-01 --end 2024-08-31`
                 `vm.sh run ingest metrics premium --universe all` (metrics is rewritten whole: the twelve's rows must come back unchanged)
                 `vm.sh bg r20 audit r18_transferbook_1d --draws 200` → output/audit/r18_transferbook_1d/audit.md
Folds read:    F1+F2 (exploration), the cells R18 and R19 read. No confirmation fold. Every source is cut at the end of F2.
Gate:          validity PASS, then per feature: CLEARS if |t| ≥ 2 AND family-wise p ≤ 0.05 AND the IC has one sign in F1 and F2.
               ≥ 1 clears → a candidate exists on exploration data; it licenses no trade. Next registration: the smallest
               thing that trades it (a rank rule on the feature, or a ridge on the cleared features alone) through the
               harness on these members, priced — and only if that book clears its own gate, a confirmation on members cut
               for F3+F4, whose data is fetched then.
               none clears → per feature CLOSED if |IC| + 1.96 se < 0.02, else NOT DETECTABLE with its MDE. All twelve closed
               → this information is closed at one day on a volume-ranked universe; what follows (another horizon, another
               market, or P7 alone) is Vadim's decision. No variant of a feature (other window, other normalisation) is read
               on these cells under this registration; a new feature family is a new registration and its bar counts these
               twelve.
Power:         R18's pooled IC on these cells had se 0.0072; a per-bar Spearman of sixty names has sd ≈ 0.13 and a day's 24
               bars share their labels, so the expected se of a feature's IC is 0.006–0.010 and its MDE 0.017–0.028. The
               family bar (the largest of twelve |t| on noise) is expected at 2.8–3.0, i.e. |IC| ≈ 0.02–0.03 to clear.
Expectation:   validity PASS. Coverage ≥ 95 % of cells for every feature. Signs: funding, premium and global_ls negative
               (what the crowd pays for and holds does worse), −0.005 … −0.020; oi and taker features inside ±0.010. Two or
               three features reach |t| 1.5–2.5; the reference row (R18's forecast) within ±0.010. About one chance in three
               that a feature clears the family bar. Likeliest: nothing clears, most features NOT DETECTABLE, funding or
               global_ls the nearest.
Result:        **Read 2026-09-28 (the audit ran 2026-09-27 22:00 → 22:18 UTC; commit 4073321 holds this block as written before any
               metrics or premium file of a member was fetched, 91d26f6 the code before the read;
               output/audit/r18_transferbook_1d, 200 draws): 0 of 12 clear the gate — seven CLOSED, five NOT DETECTABLE;
               nothing is licensed.**
               Validity first: PASS — 694,501 cells of 188 names, largest |Δ label| 7.3e-13, no cell off the hourly grid, none
               without a label. Inputs, checked before the run and without touching a label: both fetches 188 of 188 names,
               0 errors; the twelve's 4,322,018 metrics rows identical to the file kept from before the ingest
               (`data/metrics_before_r20.parquet`); every member has rows in metrics, premium and funding. No deviation
               from the commands. Coverage 99.7–100 % of cells for every feature, 484 days.
               Per feature — IC (t) · F1, F2 · family-wise p · upper bound (|IC| + 1.96 se):
                 oi_turn           +0.0326 (+3.98) · +0.043, +0.022 · 0.060 · 0.049   NOT DETECTABLE (MDE 0.023)
                 oi_chg_1w         −0.0191 (−3.49) · −0.028, −0.010 · 0.19  · 0.030   NOT DETECTABLE (MDE 0.015)
                 oi_chg_1d         −0.0158 (−3.17) · −0.013, −0.018 · 0.36  · 0.026   NOT DETECTABLE (MDE 0.014)
                 global_ls         +0.0114 (+1.28) · +0.006, +0.017 · 1.0   · 0.029   NOT DETECTABLE (MDE 0.025)
                 top_vs_global     −0.0063 (−0.82) · +0.002, −0.014 · 1.0   · 0.021   NOT DETECTABLE (MDE 0.022)
                 global_ls_chg_1d  +0.0100 (+1.99) · +0.004, +0.016 · 0.96  · 0.01997 CLOSED (under 0.02 by 0.00003)
                 funding_last      +0.0069 (+1.35) · +0.012, +0.002 · 1.0   · 0.017   CLOSED
                 premium_1d        +0.0064 (+1.14) · +0.014, −0.001 · 1.0   · 0.017   CLOSED
                 funding_7d        +0.0029 (+0.45) · +0.008, −0.003 · 1.0   · 0.016   CLOSED
                 top_ls            +0.0011 (+0.17) · +0.007, −0.005 · 1.0   · 0.014   CLOSED
                 taker_1d          −0.0020 (−0.38) · +0.006, −0.010 · 1.0   · 0.013   CLOSED
                 premium_1h        +0.0004 (+0.09) · +0.000, +0.001 · 1.0   · 0.008   CLOSED
               The family bar: on shuffled labels the best of the twelve reaches |t| 2.94 on average and **4.00 one time in
               twenty** (2.8–3.0 expected). oi_turn's 3.98 sits on it: 11 of 200 draws did as well.
               Described, decides nothing — computed after the read from the saved draws and cells, so none of it can clear
               a feature (`scripts/r20_describe_null.py`, `scripts/r20_describe_reference.py`; the inputs' check is
               `scripts/r20_check_inputs.py`; each file's first lines say how to run it on the work VM):
               (D1) where the bar of 4.0 comes from. The registered null keeps each name's own labels, so a lasting link
               between a name's LEVEL of a feature and its drift survives the shuffle — as registered. The registered p,
               however, measures |t| from zero, and two features are not centred at zero under that null: global_ls
               (shuffled t −2.65 on average, sd 0.74) and top_vs_global (+2.61, sd 0.78) — names where the crowd is
               lastingly long drifted down against the rest over F1+F2. These two hold the family's largest |t| in 161 of
               200 draws and in ALL 11 draws that reached oi_turn's 3.98. Two consequences: the bar every feature had to
               clear was set by two features' name-level link, not by noise in time; and for those two the registered p
               cannot see what it was meant to see — their real t (+1.28, −0.82) lies in the far tail of their OWN shuffles
               (single-feature p 0.97 and 0.99 mean "less extreme than almost every shuffle"). Measured from the centre
               of its own shuffles: global_ls +0.027 in IC (5.3 sd), top_vs_global −0.021 (4.4 sd), oi_turn +0.025 (3.0 sd;
               +0.007 of its +0.033 is level), oi_chg_1w −0.017 (3.1 sd), oi_chg_1d −0.015 (2.8 sd), funding_last +0.010
               (2.4 sd); the other six inside 1.8 sd. A weakness of the registered p found at the read, not a defect of
               the run: the verdicts above are the gate's and stand.
               (D2) the reference row: R18's forecast by this statistic reads **IC −0.0320 (t −5.18)** where ±0.010 was
               expected and R18's own statistic read +0.0002. Both instruments are right (four correlations on the same
               694,501 cells: pooled Pearson +0.0002, t 0.03 — R18's number to the digit; per-bar Pearson −0.006, t −0.9;
               pooled ranks −0.031, t −5.1; per-bar Spearman −0.032, t −5.2). The difference is rank against mean: in the
               forecast's top tenth the MEDIAN move against the peers is −0.126 σ and the mean −0.011 σ (deciles 2–7:
               median −0.05, mean −0.01 … +0.01). What the twelve's model likes most on outside names usually does worse
               than its peers and is rescued in the mean by a few large winners — R18's book in other words (long −54,
               short +41). No null was drawn for this row.
               (D3) what a signal needs here: a taker round trip cost 18.0 bps on the run's trades, the mean move against
               the other members is 245 bps, so trading the top tenth of a signal breaks even at an IC of about 0.033 —
               oi_turn's size exactly, twice the open-interest changes'. And by (D2) a rank IC on these names need not
               turn into money at all: only a priced book says.
               Against the expectation: validity, coverage and the se (0.004–0.009 against 0.006–0.010) as expected.
               Signs: funding, premium and global_ls were expected NEGATIVE and came positive, all small; the open-interest
               features were expected inside ±0.010 and are the three largest; taker inside its band. Three features
               beyond |t| 3 where two or three at 1.5–2.5 were expected. The family bar 4.0, not 2.8–3.0 (D1). The
               reference row far outside its band (D2). "Nothing clears, most NOT DETECTABLE" came half true: nothing
               clears, seven of twelve are CLOSED; the nearest is oi_turn, not funding or global_ls.
               Reading: **funding and the perpetual's premium over spot say nothing about which name does better than its
               peers over the next day — closed at this horizon on this universe, with the taker flow, the top traders'
               ratio and the crowd's one-day change. Open interest says something this read could not certify: names
               whose open interest is large against their volume, and names whose open interest has been falling, did
               better than their peers the next day, in both folds, at sizes between half of break-even and break-even.**
               Consequences: nothing is licensed. No variant of any of the twelve is read on these cells under this
               registration. The five NOT DETECTABLE stay open; the seven CLOSED are closed at one day on a volume-ranked
               universe only. Counted on these cells so far: R18's four screens, R19's one, these twelve features. Any
               later null of this kind reports each feature against the centre of its own shuffles (D1). What follows
               is R21 (Vadim's go, 2026-09-28).

### R21 — oibook: the open-interest numbers as a priced book on the names that chose them — a kill test (registered 2026-09-28 on Vadim's go, before the rule was written and before it saw any bar; read 2026-09-28: CLOSED — taker net −17.3 [−28.9, −5.8], maker net −9.6; the rank correlation is there and is worth +1.6 bps a trade before costs)
Question:      R20 left three open-interest features NOT DETECTABLE and nearest the bar (oi_turn +0.033, oi_chg_1w −0.019,
               oi_chg_1d −0.016; none cleared). Ranked by them, do the members earn money after costs — on the very cells
               that pointed at these three? The features were picked after being seen here, so the estimate leans upward: a
               profit proves nothing and licenses only a confirmation on unread names and months; a clear loss closes
               the book without spending anything. It is also the first answer to R20 (D2): does a RANK correlation on
               these names turn into money at all?
Universe:      R18's members (`ft2/screen_members.csv`, frozen; the block's 60, the twelve left out), F1+F2, the harness's
               30-day blocks. Hourly decision bars (grid 12), executed one bar later, held 288 bars — R18's and R20's cells.
Rule:          `ft2/audit.py::OIBook` (`oibook`), no fit, no label, no number taken from the data. At a decision bar t,
               among the block's members that have a close and all three features (at least 12 of them):
                 r(x)  = the rank of x among them, as a share
                 s     = r(oi_turn) − ½ · [ r(oi_chg_1d) + r(oi_chg_1w) ]      (the level and the change weigh the same;
                         the signs are R20's)
               long the k = 6 names with the highest s, short the 6 with the lowest, one unit each (no sizing); the i-th
               highest and the i-th lowest are ONE unit of the book (both legs or neither), so the book is dollar-neutral
               at every bar. k = 6 is a tenth of sixty: P2 #7's "top tenth", the cost bar R20 (D3) quoted. The three
               features are `audit.features`' own code, unchanged (a metrics row stamped ts is used from ts + 5 min).
               One position per pair, latency, fills, costs and nulls are the harness's.
Cost:          R18's: the members have no tape, `ft2 costwide`'s pooled candle proxy (it over-prices thin names, R10).
               Every money row is read as priced and, in a twin run, with spread + impact doubled. Fees VIP 0.
Validity:      read first (`ft2 audit <run> --book`): every decision sits on the hourly grid and on a member of its
               block; every accepted unit has one long and one short leg; accepted longs = accepted shorts. Any failure →
               the run is void and the cause is found before a money number is read.
Commands:      on the work VM, in this order (the twin after the first has finished: one job at a time) —
                 `vm.sh bg r21 backtest oibook --universe screen --param hold=288 k=6 --execs taker maker --name r21_oibook_1d`
                 `vm.sh run audit r21_oibook_1d --book`
                 `vm.sh bg r21_x2 backtest oibook --universe screen --param hold=288 k=6 --execs taker --cost-mult 2 --draws 1 --name r21_oibook_1d_x2`
               → output/backtest/r21_oibook_1d/report.md (the twin's nulls are not read)
Folds read:    F1+F2 (exploration), the cells R18, R19 and R20 read. No confirmation fold, no new download.
Gate:          validity PASS, then on the taker book as priced, F1+F2 pooled:
               CANDIDATE if net > 0 AND hedged net > 0 AND flip p ≤ 0.05 AND gross > 0 in F1 and in F2. It licenses no
               trade and one next step: a confirmation registration on the members cut point-in-time for F3+F4, whose
               bars, funding and metrics are fetched then — spending those months for this question is Vadim's decision.
               CLOSED if the upper end of the net interval is below zero AND the maker net is ≤ 0: open interest as a
               rank book at one day on a volume-ranked universe is closed, on the data that was most favourable to it.
               Otherwise NOT FUNDED: no fold is spent on this book; the three features stay what R20 left them (NOT
               DETECTABLE, candidates for a model's inputs); revived by a lower cost on these names (a maker path that is
               measured, a fee tier) or by a registration that brings new cells.
               Whatever the verdict: no variant on these cells under this registration — no other k, weights, hold,
               grid, feature or side. The shuffle null is reported and does not decide (the rule reads no label; R16
               showed what that null is worth on wild names).
Described:     long and short apart; per fold; the maker book; the twin with costs doubled; trades a day and positions
               open; the share of the net that the five best names carry.
Power:         R18's all-members book (16,306 trades) had a hedged-net se of 4.8 bps and a net se of 10.9. This book is
               dollar-neutral, so its net behaves like a hedged net; at 12–14 trades a day (6,000–7,000 trades) the
               expected se is 7–9 bps and the MDE 20–25. A true edge under about 20 bps a trade after costs cannot be
               certified here, and the interval will be about ±16 wide: CLOSED needs a net below about −16.
Expectation:   validity PASS. 12–16 trades a day, 10–12 positions open on average. Gross +8 … +22 a trade (R20's sizes
               promise about +20 at the top tenth; R9 collected a third of what its screen promised), costs 18–23 as a
               taker → net −14 … +4, hedged net within 3 of it; maker net −8 … +10; flip p 0.05–0.5; costs doubled 6–12
               lower. The short side earns more than the long side, as in every book on these names (R18, R19). About
               one chance in five CANDIDATE, one in five CLOSED. Likeliest: NOT FUNDED, net slightly below zero.
Result:        **Read 2026-09-28 (the run 04:27 → 05:03 UTC; commit 97b6020 holds this block as written before the rule was
               written, c873f53 the rule and its tests before it saw a real bar; output/backtest/r21_oibook_1d, 200 draws):
               the upper end of the taker net interval is below zero and the maker net is ≤ 0 → by the gate CLOSED.**
               Validity first: PASS — 139,212 decisions, none off the hourly grid, none on a non-member; 8,234 taken in
               4,117 whole units, 4,117 longs and 4,117 shorts, 185 names traded. No deviation from the commands.
               Taker, as priced: 8,214 trades (16.9 a day; 20 unpriceable), at most 28 positions open and 11.05 on
               average, right on 52.1 %. Gross **+1.56**, hedged +1.57 [−9.99, +13.14]; fees 10.00, spread and impact
               7.55, funding −1.34 → **net −17.33 [−28.86, −5.81]**, MDE 16.5, hedged net −17.32 [−28.92, −5.72]; flip
               null −17.18 ± 4.93, **flip p 0.50**; shuffle p 0.54. F1: gross −1.9, net −22.4 [−37.2, −7.6]; F2: gross
               +5.0, net −12.3 [−29.9, +5.4] — gross is not positive in both folds either.
               Maker: gross −3.43 (the unfilled legs are the ones that ran), fees 4.31, other 0.51, fill share 0.95 →
               **net −9.59 [−21.16, +1.98]**, flip p 0.51. Costs doubled (twin, taker): net −24.88 [−36.42, −13.35].
               Long and short apart (taker): long gross −15.8, hedged −10.8, net −37.0 [−65.5, −8.5], hedged net −32.0
               [−42.6, −21.4]; short gross +18.9, hedged +13.9, net +2.4 [−36.7, +41.4], hedged net −2.6 [−21.0, +15.7].
               Names: the net summed over trades is −142,373 bps on 185 names, 86 of them positive; five best +40,920
               (HIGH, MASK, JASMY, WIF, EOS), five worst −65,742 (FET, 1000BONK, RUNE, ID, 1000SHIB).
               Described, decides nothing — computed after the read (`scripts/r21_describe_score.py`; its output is
               kept as `describe_score.txt` beside the run):
               (D1) the book traded what R20 measured. On the book's own 691,153 cells, by R20's statistic: oi_turn
               +0.0328 (t 4.0), oi_chg_1w −0.0191 (t −3.5), oi_chg_1d −0.0157 (t −3.2) — R20's numbers — and the score
               itself **+0.0343 (t 5.2)**. The rule is not broken; the correlation is there.
               (D2) where it lives. The move over the next day against the other cells, by the score's tenth inside the
               bar (mean / median, bps): bottom tenth −24.8 / −73.6, second −10.0 / −55.1, third to tenth between −0.5
               and +11.1 in the mean with no order, medians −33 → −20. The top tenth — what the book buys — is −0.5 /
               −20.3. All of the rank correlation is the two lowest tenths doing worse; nothing separates the other
               eight. Those lowest tenths are the most violent names (median one-day σ 622 bps against 422 at the top).
               (D3) rank against money. Top tenth minus bottom tenth, per leg, on all cells: **+12.2 in the mean, +26.6
               in the median**; on the trades taken: mean +1.56, median +18.5. The typical trade is right and a few
               large moves of the shorted violent names take it back — R20 (D2) in money.
               Against the expectation: validity, positions open (11.05), costs (18.9 with funding), the doubled costs
               (7.5 lower) and "the short side earns more than the long" as expected. Trades a day 16.9 (12–16
               expected). Gross +1.56 where +8 … +22 was expected — below the band; net −17.3 below its band (−14 … +4);
               maker −9.6 just below its band; flip p 0.50 at the far end of 0.05–0.5. The se came out at 5.9, tighter
               than the 7–9 expected, which is why the interval excludes zero. CLOSED was given one chance in five.
               Reading: **the open-interest numbers do sort the names — the correlation R20 saw is real on these cells —
               and sorting by them earns nothing: +1.6 bps a trade before costs of 19. A rank correlation of 0.034 on
               these names is worth at most 12 bps a leg even if every cell could be traded, because it says "the most
               frenzied tenth usually falls behind" and says nothing about which names rise.**
               Consequences: open interest as a rank book at one day on a volume-ranked universe is CLOSED, on the data
               most favourable to it; no confirmation fold is asked for and F3+F4 of the outside names stay unread. Not
               re-cut: no other k, weights, hold, grid or side on these cells (a short-only or exclusion rule built on
               (D2) would be one). The three features stay what R20 left them as inputs. What this read adds for every
               later registration on these names: **a single feature's rank IC near 0.03 cannot pay a one-day round
               trip here; the bar for a rule is money in the mean, not the rank.** What follows is Vadim's decision
               (P8 "What next").

### R22 — the longer hold: what R20's five unresolved numbers and the price-bar forecast say about a name's next 3 and 7 days, in money (registered 2026-09-28 on Vadim's go, before the code was written and before any label beyond one day was computed; read 2026-09-28: 0 of 12 clear — twelve NOT DETECTABLE; the open-interest numbers lean the right way and grow with the hold (the score +11, +25, +59 bps a leg at 1, 3, 7 days) at 1.3–1.5 times their noise; RE-EXECUTED 2026-09-30 in actual returns: 0 of 12 clear, twelve NOT DETECTABLE as before, and the lean is mostly the unit — the score +3, +4, +21 at 1, 3, 7 days, 0.2–0.7 times its noise)
Question:      Everything measured on names outside the twelve was measured at a one-day hold, and nothing clears its costs
               there (R10, R12, R13 A, R18–R21). A round trip costs the same whether a position is held a day or a week,
               and the numbers that showed something are slow ones. Held 3 days or 7 days, do the names a signal puts at
               the top earn more than the names it puts at the bottom — in the MEAN, in bps, by more than the round trip?
               A ceiling audit (Principle 2): no model, no book, no fold spent, no download.
Cells:         R18's, exactly (R20's and R21's): the scored cells of `output/backtest/r18_transferbook_1d`, hourly decision
               bars of F1+F2, embargoed, the block's 60 members, the twelve left out. A cell is read at a hold if its label
               exists there (the last 3 or 7 days of F2 have none: nothing at or after the end of F2 is read).
Holds:         two, fixed here: 864 bars (3 days) and 2,016 bars (7 days). One day (288) is computed by the same code as
               the validity check and the reference row; it was read by R20 and R21 and can clear nothing.
Label:         what a long position earns before trading costs: the move from the close one bar after t to the close
               `hold` bars later, MINUS the funding a long pays over those bars (`backtest.load_costs`' cumulative funding,
               the harness's own), bps. Against the peers: minus the mean over the bar's cells with a label.
Signals:       six, fixed here, each known strictly before t. R20's five NOT DETECTABLE features by `audit.features`' own
               code, unchanged: oi_turn, oi_chg_1w, oi_chg_1d, global_ls, top_vs_global. And `forecast`: R18's ẑ (the
               candle ridge fitted on the twelve, a one-day forecast), read from the run's forecast.parquet, not refitted.
Statistic:     M, the money in the mean (R21's lesson: the mean, not the rank). Per bar with ≥ 20 cells that have the
               signal and the label: k = the tenth of them, rounded; the mean label-against-peers of the k highest by
               the signal minus that of the k lowest, HALVED — bps per leg, what one leg of a top-against-bottom book
               earns before trading costs. Averaged per day; M = the mean over days. Two-sided: a signal that sorts the
               wrong way round is a signal.
Null:          the labels move by a whole number of days, the same for every name and every bar (a circular shift of the
               scored days; time of day kept, whole rows move). EVERY admissible shift is computed, none drawn: a shift
               is admissible if no day receives the labels of a day less than 15 days away in either direction (7 days
               of the longest feature window + 7 of the longest hold + 1), the same shifts for both holds — 456 of them
               on 485 days. Why not R20's null (whole days trade places): labels of neighbouring days share 2/3 or 6/7 of
               their window at these holds, and trading days' places would break that overlap and make the null too
               narrow. A shift keeps it, and keeps each name's own labels, so a lasting link between a name's LEVEL of a
               signal and its drift survives in the null and earns no credit (R20).
               Per signal × hold: centre = the mean of M over the shifts, se = their standard deviation (R20 (D1): each
               number against the centre of its own null). M_c = M − centre, u = M_c / se. Family: the 6 × 2 = 12;
               per shift the largest |u| of the twelve (each against its own centre and se) → the family-wise p of a
               real |u|. The HAC se over days (lags = days of the hold + 1) is reported beside the null's and decides
               nothing.
Cost:          17.6 bps per leg, fixed here: R21's fees (10.00) + spread and impact (7.55) on its 8,214 taker trades —
               the top and bottom tenths of these names, which is what such a book trades. Funding is inside the label.
Validity:      read first, or the run is void: (1) the labels at 288 bars, before funding, equal R18's on every cell to
               1e-6 and the cell count is R18's (R20's check); (2) the rank IC of the five features at 288 bars, by this
               code on the vol-standardised label, equals R20's `features.csv` to 1e-9; (3) every scored day holds 24 bars
               and the number of shifts is the number of days − 29.
Described:     decides nothing. Per signal × hold: M before centring and the funding's part of it; M per fold; the
               mean and the median label-against-peers in each of the ten tenths; the top and the bottom tenth apart;
               the part of M earned AFTER the first day (the label from bar 289 on); R20's rank IC at that hold with
               its HAC t, and the IC at which the top tenth pays the round trip there. The same for the one-day row,
               and for R21's score (r(oi_turn) − ½[r(oi_chg_1d) + r(oi_chg_1w)]) at all three holds: reference rows,
               outside the family, no verdict.
Commands:      on the work VM —
                 `vm.sh bg r22 horizon r18_transferbook_1d --holds 864 2016` → output/horizon/r18_transferbook_1d/horizon.md
Folds read:    F1+F2 (exploration), the cells R18–R21 read. No confirmation fold, no new download.
Gate:          validity PASS, then per signal × hold, on F1+F2 pooled:
               CLEARS if |M_c| > 17.6 AND |u| ≥ 2 AND family-wise p ≤ 0.05 AND M has M_c's sign in F1 and in F2 AND the
               part earned after the first day has M_c's sign. It is a candidate on exploration data and licenses no
               trade. Next registration, on Vadim's go: the smallest book that trades it at that hold through the
               harness on these names, priced (R21's pattern); only if that book clears its own gate, a confirmation on
               members cut for F3+F4.
               CLOSED if |M_c| + 1.96 se < 17.6: whatever is there cannot pay the round trip — that signal at that hold
               is closed on a volume-ranked universe.
               NOT DETECTABLE otherwise, with its MDE (2.8 se).
               None clears → nothing is licensed; what follows is Vadim's decision (P8 "What next" (2) or (3); or, only
               if a point estimate |M_c| exceeds the cost with the after-the-first-day part agreeing, a registration
               that brings NEW cells — more months or more names; never a re-read of these).
               Whatever the verdict: no variant on these cells under this registration — no other hold, tenth, window,
               signal, side or weighting.
Power:         stated before the read, and it is weak. From R21's book (se 5.9 bps a trade at one day): a day's M is about
               √3 or √7 times wider at these holds and neighbouring days repeat each other for 3 or 7 days, so the expected
               se is 12–18 bps a leg at 3 days and 25–40 at 7 days. The family bar (the largest of twelve |u|) is expected
               at 2.8–3.0. To CLEAR a signal needs about |M_c| ≥ 45 bps a leg at 3 days and ≥ 95 at 7 days — two and a
               half and five times the cost. CLOSED needs an se under 9 and is out of reach if the se comes out as
               expected: this audit can find a large effect or say "not detectable"; it cannot rule a small one out.
               485 days hold 69 separate weeks.
Expectation:   validity PASS; about 1.5 % of the cells lose their label at 7 days. One day, reference: oi_turn's M +6 …
               +14, the score's +12 (R21 (D3)). 3 days: the open-interest signals' M_c between −5 and +30, 7 days between
               −30 and +60; the two long/short signals and the forecast inside ±1 se at both holds. The part after the
               first day smaller than the first day's for the open-interest signals. About one chance in eight that
               something clears. Likeliest: twelve NOT DETECTABLE.
Result:        **Read 2026-09-28 (the run 07:25 → 07:44 UTC; commit 4c122f1 holds this block as written before the code, 85032fb
               the code and its tests before any label beyond one day was computed on a real bar;
               output/horizon/r18_transferbook_1d, 456 shifts): 0 of 12 clear the gate — twelve NOT DETECTABLE, none
               CLOSED; nothing is licensed.**
               Validity first: PASS — 694,501 cells of 188 names, largest |Δ label| 7.3e-13, none off the grid, none without
               a label; R20's five ICs reproduced to 8.7e-17; 485 whole days, 456 shifts. No deviation from the command.
               Cells with a label: 99.4–99.6 % at 3 days, 98.6–98.8 % at 7.
               Per signal × hold — M · centre · M_c · se · u · family-wise p · after the first day · F1, F2 (bps a leg):
                 oi_turn        3d  +26.6 · +10.2 · +16.4 ·  21.7 · +0.76 · 0.93 · +15.0 ·  +23.3,  +29.8
                 oi_turn        7d  +54.8 · +21.1 · +33.7 ·  51.0 · +0.66 · 0.96 · +43.5 ·  +37.5,  +72.7
                 oi_chg_1w      3d   −8.3 ·  −4.4 ·  −3.9 ·  23.5 · −0.17 · 1.0  ·  −9.5 ·   −8.4,   −8.3
                 oi_chg_1w      7d  −56.2 · −11.9 · −44.3 ·  55.2 · −0.80 · 0.91 · −56.9 ·  −67.4,  −44.6
                 oi_chg_1d      3d  −11.6 ·  −1.3 · −10.2 ·  10.2 · −1.00 · 0.74 ·  −5.9 ·   +3.1,  −26.5
                 oi_chg_1d      7d   −4.1 ·  −3.7 ·  −0.4 ·  19.4 · −0.02 · 1.0  ·  +1.6 ·   +5.4,  −13.9
                 global_ls      3d  −23.0 · −29.9 ·  +7.0 ·  43.0 · +0.16 · 1.0  · −12.7 ·  −65.1,  +19.9
                 global_ls      7d  −11.0 · −71.5 · +60.5 · 104.4 · +0.58 · 0.98 ·  −1.1 ·  −95.8,  +76.6
                 top_vs_global  3d   +5.0 · +25.0 · −20.1 ·  34.8 · −0.58 · 0.98 ·  +1.1 ·  +58.3,  −49.2
                 top_vs_global  7d  −29.4 · +60.7 · −90.1 ·  84.0 · −1.07 · 0.64 · −33.3 ·  +64.1, −126.0
                 forecast       3d   −6.1 ·  −0.9 ·  −5.3 ·  10.0 · −0.53 · 0.99 ·  −8.3 ·   +5.5,  −17.9
                 forecast       7d  −32.0 ·  −2.9 · −29.1 ·  17.9 · −1.62 · 0.23 · −33.4 ·  −11.7,  −52.9
               The family bar: over the shifts the largest |u| of the twelve is 1.46 on average and 3.38 one time in
               twenty (2.8–3.0 expected). The largest real |u| is 1.62 (the forecast at 7 days, the wrong way round).
               Reference rows, outside the family (M · M_c · se · u · single p): one day — oi_turn +11.8 · +8.3 · 7.5 ·
               1.11 · 0.16; oi_chg_1w +0.8; oi_chg_1d −5.9; global_ls −10.2 (centre −10.0); top_vs_global +3.8;
               forecast +2.3. R21's score — 1d +11.1 · +8.3 · 5.2 · 1.60 · 0.12; 3d +25.0 · +17.0 · 13.4 · 1.28 · 0.19;
               7d +58.9 · +41.4 · 26.9 · 1.54 · 0.10; both folds positive at every hold (7d: +46.1, +72.2), after the
               first day +14.5 (3d) and +48.3 (7d).
               Described, decides nothing (the report's tables; `tenths.csv`, `signals.csv`, `shifts.parquet`):
               (D1) where the open-interest money is: the LOWEST tenth, as in R21 (D2), and it keeps falling behind for the
               whole week. The label against the bar's peers, mean / median, for oi_turn's lowest tenth: −25 / −92 at one
               day, −50 / −173 at three, −94 / −260 at seven; its highest tenth −1, +4, +18 in the mean. The score's
               lowest tenth −22, −41, −77; its highest −1, +7, +40. Tenths three to nine carry no order at any hold.
               (D2) the forecast is wrong at a week. What the twelve's model likes most on outside names falls behind:
               its highest tenth −6.7 / −64.8 at one day, −25.6 / −117 at three, −72.9 / −205 at seven; its lowest tenth
               −11, −13, −9 in the mean. Rank IC −0.031 at both holds (HAC t −4.1, −3.8) — R20 (D2) at a longer hold.
               (D3) the two long/short signals are the names', not the timing's: the centre is larger than M_c at three
               days and of its size at seven, and M changes sign between the folds (global_ls 7d: −96 in F1, +77 in F2).
               (D4) the two standard errors. The null's se is above the HAC se over days wherever the signal is slow:
               oi_turn 21.7 against 19.0 (3d) and 51.0 against 35.1 (7d); global_ls 43.0 against 17.6 and 104 against 39;
               for the fast ones they agree (oi_chg_1d 10.2 / 9.4, forecast 10.0 / 10.3). By the HAC se and measured
               from zero the score at 7 days reads t 2.1 and oi_turn 1.6: not certifiable by either yardstick, for
               signals that were chosen on these cells.
               (D5) funding's part of M: −5.4 and −8.5 bps a leg for oi_turn (3d, 7d), −2.7 and −3.2 for the score, up
               to −18 for global_ls at 7 days: the book's sides pay funding on balance, and it is inside every M above.
               (D6) rank IC at the hold and what the top tenth needs there (0.018 at 3d, 0.012 at 7d; the mean move
               against the peers is 434 and 667 bps): oi_turn +0.019 (t 1.4), +0.015 (0.7); oi_chg_1w −0.023 (−2.7),
               −0.036 (−3.0); oi_chg_1d −0.016 (−2.7), −0.012 (−1.7); the score +0.023 (2.1), +0.024 (1.6).
               Against the expectation: validity, the share of cells lost and the one-day reference rows as expected; M_c
               of the open-interest signals inside their bands at both holds. The se came out WIDER than expected for
               the slow signals (oi_turn 21.7 and 51.0 against 12–18 and 25–40; the long/short two 35–104) and as
               expected or tighter for the fast ones; the family bar 3.38, not 2.8–3.0. "Inside ±1 se" held for
               global_ls and failed narrowly for top_vs_global (−1.07) and for the forecast (−1.62). "The part after
               the first day smaller than the first day's" was WRONG: for oi_turn it is +15.0 and +43.5 against +11.8 —
               what is there keeps accruing after the first day. "Twelve NOT DETECTABLE" came true.
               Reading: **a longer hold certifies nothing on these cells, and rules nothing out. The open-interest
               numbers lean the way R20 saw and grow about in step with the hold — the score earns 11, 25 and 59 bps
               a leg at one, three and seven days against a round trip of 17.6 — but the same book given the moves of
               other weeks does as well one time in ten (the score) to one time in three (oi_turn alone), and all of
               it is a SHORT of the most frenzied tenth; nothing here picks names that rise. The sample, not the
               signal, is what ran out: 485 days are 69 weeks.**
               Consequences: nothing is licensed and no book is built on these cells. The clause for new cells applies
               (|M_c| above the cost with the part after the first day agreeing and one sign in both folds): oi_turn
               at 7 days, oi_chg_1w at 7 days, the score at 7 days (reference), and the forecast at 7 days with the
               opposite sign. No variant is read on these cells — no other hold, tenth, window, side or weighting (a
               short-only rule on (D1) would be one). Counted on these cells so far: R18's four screens, R19's one,
               R20's twelve features, R21's book, these twelve. What follows is Vadim's decision (P8 "What next").
Re-executed:   **2026-09-30, the re-execution `actual` (§3; the run 06:38 → 06:49 UTC on the work VM, the registered command
               with `--name r18_transferbook_1d_actual`; commit a5c47a1 holds the corrected unit and the protocol before
               the run; output/horizon/r18_transferbook_1d_actual, 456 shifts): in actual returns 0 of 12 clear the
               gate — twelve NOT DETECTABLE, as before; and the lean of the open-interest numbers, which is what R23
               was registered on, is mostly gone.**
               Validity first: PASS — the first read's three checks as before (694,501 cells of 188 names, largest
               |Δ label| 7.3e-13, R20's five ICs to 8.7e-17, 485 whole days, 456 shifts), and the same cells
               (`same_as_first_read.json`): 21 rows, the cells, days, shifts and the rank IC of every row equal the
               first read's, largest difference 0.0. No deviation from the command.
               Per signal × hold — M (first read, in logs) → M · centre · M_c · se · u · family-wise p (bps a leg):
                 oi_turn        3d  (+26.6) →  +0.2 ·  −1.1 ·  +1.3 ·  26.7 · +0.05 · 1.0
                 oi_turn        7d  (+54.8) →  +3.2 ·  −9.0 · +12.2 ·  68.1 · +0.18 · 1.0
                 oi_chg_1w      3d   (−8.3) →  +2.3 ·  −6.5 ·  +8.8 ·  28.2 · +0.31 · 1.0
                 oi_chg_1w      7d  (−56.2) → −39.7 · −17.0 · −22.7 ·  70.3 · −0.32 · 1.0
                 oi_chg_1d      3d  (−11.6) →  −7.2 ·  −2.6 ·  −4.6 ·  11.6 · −0.39 · 1.0
                 oi_chg_1d      7d   (−4.1) →  +1.9 ·  −6.9 ·  +8.7 ·  24.0 · +0.36 · 1.0
                 global_ls      3d  (−23.0) → −40.5 · −31.2 ·  −9.3 ·  47.3 · −0.20 · 1.0
                 global_ls      7d  (−11.0) → −38.3 · −74.7 · +36.4 · 120.2 · +0.30 · 1.0
                 top_vs_global  3d   (+5.0) → +21.7 · +28.0 ·  −6.3 ·  38.4 · −0.16 · 1.0
                 top_vs_global  7d  (−29.4) →  −2.2 · +67.9 · −70.2 ·  97.9 · −0.72 · 0.96
                 forecast       3d   (−6.1) →  +4.7 ·  −1.5 ·  +6.2 ·  11.2 · +0.56 · 0.99
                 forecast       7d  (−32.0) → −14.8 ·  −4.2 · −10.6 ·  22.0 · −0.48 · 1.0
               The family bar: the largest |u| of the twelve over the shifts 1.44 on average, 3.41 one time in twenty;
               the largest real |u| is 0.72. Reference rows (M first read → M · M_c · se · u): R21's score — 1d
               (+11.1) → +3.5 · +2.6 · 5.5 · 0.48; 3d (+25.0) → +4.5 · +3.0 · 14.7 · 0.21; 7d (+58.9) → +20.7 · +21.8 ·
               32.3 · 0.68, both folds positive (+12.8, +28.9), after the first day +17.8. oi_turn at one day (+11.8)
               → +2.2; the forecast at one day (+2.3) → +6.8 (u 1.53).
               Described, decides nothing:
               (E1) where the lean went. The lowest tenth of oi_turn — the names in a frenzy — still falls behind
               in the TYPICAL case: median against the bar's peers −97, −188, −300 bps at one, three and seven days
               (first read −92, −173, −260). In the MEAN it is −11, −11, −18 (first read −25, −50, −94): a few of
               those names rise so far that they pay most of it back, and a sold position carries that rise in
               full where the log shrank it. The score's lowest tenth: mean −12, −12, −23 (first read −22, −41, −77).
               (E2) the forecast's "wrong way round at a week" (first read (D2)) is the unit too: M_c −29.1, u −1.62
               → −10.6, u −0.48. Its rank IC is unchanged (−0.031, the label there is R20's) — the ranking is
               inverted, the money is not there.
               (E3) the standard errors are wider in actual returns (oi_turn 7d 51.0 → 68.1, the score 26.9 → 32.3):
               the right tail the log compressed is in them.
               Reading: **counted as a position earns, nothing on these cells leans further than its noise: the
               open-interest score is +21 bps a leg at seven days, 0.7 times its noise, where the log showed +59 at
               1.5; oi_turn alone is +3 where the log showed +55. Two thirds of what R22 reported for the
               open-interest numbers was the unit. The verdict — twelve NOT DETECTABLE — stands.**
               Consequences: nothing is licensed, as before. The clause for new cells (|M_c| above the cost, the part
               after the first day agreeing, one sign in both folds) is now met only by the score at 7 days, barely
               (+21.8 against 17.6; a reference row) and by oi_chg_1w at 7 days (−22.7); oi_turn and the forecast no
               longer meet it. R23 was registered on the first read's numbers; its own re-execution follows.

### R23 — the open-interest score at a 7-day hold on months nobody has read: stage 1 of two, the confirmation folds behind a stop (registered 2026-09-29 on Vadim's "(A1)", before the universe of those months was chosen, before any 5m bar or metrics file of them was fetched and before the code was written; read 2026-09-29: CLEARS — M +66.7 bps a leg, centre +14.1, M_c +52.6, se 21.6, u 2.43, one-sided p 0.002, both halves and the part after the first day positive; stage 2 is not run, F3+F4 untouched; RE-EXECUTED 2026-09-30 in actual returns: does NOT clear — GO ON by the gate: M +20.4, M_c +30.7, se 27.2, u 1.13, p 0.12, the second half negative, +3.5 without the two collapse months)
Question:      R22 left one number leaning: on F1+F2 the names R21's open-interest score ranks highest earned, over the
               next 7 days, 59 bps a leg more than the names it ranks lowest (41 of it the timing's, 1.5 times its
               noise) against a round trip of 17.6 — on the cells that chose the score. On cells that did not choose
               it, is that still there? A ceiling audit (Principle 2): no model, no book. ONE number, its direction
               fixed here.
Stages:        two. STAGE 1 (this registration's read): the months before F1 that have open interest. The archive's
               metrics begin 2021-12-01 for every name but BTC (DATA.md; listed 2026-09-29), so: 2021-12 → 2023-04,
               71 weeks — the size of R22's sample. STAGE 2, only by the gate below and only on Vadim's separate go:
               the same number on the outside names of F3+F4 (2024-09 → 2026-01), read POOLED with stage 1. Stage 2's
               universe and downloads are written as their own block before any file of it is fetched; that block
               may not change the signal, the direction, the hold, the statistic, the null, the cost or the pooled
               rule, all fixed here.
Scored days:   2021-12-10 → 2023-04-23, 500 whole days, fixed by the calendar: the first is 9 days after the first
               metrics row (the 7-day window of oi_chg_1w and `audit.WARMUP`), the last is the last day whose 7-day
               label ends before F1 begins. The market is loaded with its end at 2023-05-01 00:00 UTC: nothing at or
               after F1's first instant can be read. Two halves, fixed here: 2021-12-10 → 2022-08-16 and 2022-08-17 →
               2023-04-23, 250 days each.
Universe:      `universe.characteristics`, unchanged — R18's rule: at the start of each 30-day block (the first
               starts 2021-12-10; 17 blocks, the last cut at the last scored day), the 60 USDT perpetuals with the
               largest median daily quote volume over the 30 days before it, a daily bar on each of those days, the
               twelve left out. Daily bars before the block only. Frozen as `ft2/screen_members_pre.csv` and
               committed BEFORE any 5m kline or metrics file is fetched for these months.
Cells:         built from the members and the candles (no run exists on these months): the hourly decision bars of
               the scored days × the block's members with a close at t. Y holds every name's label on every bar, as
               in R22, so that a shift moves whole rows.
Hold:          one in the family: 2,016 bars (7 days). 288 and 864 bars are reference rows.
Label:         R22's, by `horizon.labels`, unchanged: what a long earns before trading costs — the move from the
               close one bar after t to the close `hold` bars later, minus the funding a long pays over those bars.
Signal:        one, R21's score by R22's own code (`horizon`'s SCORE): s = r(oi_turn) − ½·[r(oi_chg_1d) +
               r(oi_chg_1w)], r = the rank as a share among the bar's cells that have all three; the three features
               by `audit.features`, unchanged. DIRECTION, fixed here from R21 and R22: POSITIVE — the names the
               score ranks high earn more than the names it ranks low.
               Not in the family, reference rows without a verdict: oi_turn, oi_chg_1w, oi_chg_1d alone at 7 days;
               all four at 1 and 3 days. Not read at all: the two long/short numbers (R22 (D3): the names', not the
               timing's) and the forecast (no model is fitted on these months).
Statistic:     R22's M by `horizon._tenths`, unchanged: per bar with ≥ 20 cells that have the signal and the label,
               the mean label of the tenth highest by the signal minus that of the tenth lowest, halved — bps per
               leg; averaged per day; M = the mean over days.
Null:          R22's: every admissible circular shift of the scored days (gap 15 days) — 471 shifts on 500 days.
               centre and se = the mean and the standard deviation of M over the shifts; M_c = M − centre; u = M_c /
               se. p = the share of shifts whose u is at least the real one, ONE-SIDED (the direction is fixed).
               The HAC se over days is reported beside the null's and decides nothing.
Cost:          17.6 bps per leg, R22's bar, unchanged. Weakness, stated now: it was measured on 2023–24 trades; no
               tape and no depth exist for these names in 2022, so what a round trip cost then is not known.
Validity:      read first, or the run is void:
               (1) every fetch ends with 0 errors and 0 bad checksums;
               (2) R22 comes back: R22's output is set aside before the ingest, `ft2 horizon r18_transferbook_1d
               --holds 864 2016` is re-run after the ingest and with the new code, and m, centre and se of every
               row equal the saved ones to 1e-9 (the slices are rewritten whole and `horizon` is changed: this says
               neither moved a number). It reads nothing new;
               (3) every cell's name is a member of its block and none is one of the twelve; every cell is on the
               hourly grid inside the scored days; every scored day holds 24 bars; the shifts number 471;
               (4) the score is present on ≥ 90 % of the cells (open interest really is there).
Described:     decides nothing. M before centring and the funding's part; M per half; the mean and the median label
               against the peers in each tenth, the top and the bottom tenth apart; the part earned after the first
               day; the rank IC at the hold with its HAC t; members per block; the share of cells a shift keeps; M
               with the calendar months 2022-05 and 2022-11 left out (the two collapses of that year: is it two
               weeks or the whole sample?). The reference rows by the same tables.
Commands:      on the work VM, in this order —
                 `vm.sh run universe --screen --pre` → `vm.sh pull` → copy output/universe_screen_pre_members.csv to
                   ft2/screen_members_pre.csv, commit
                 `vm.sh bg r23_klines archive klines/5m fundingRate --universe pre --monthly --start 2021-11-01 --end 2023-04-30`
                 `vm.sh bg r23_metrics archive metrics --universe pre --start 2021-12-01 --end 2023-04-30`
                 on the VM: `cp -r output/horizon/r18_transferbook_1d output/horizon/r22_saved`
                 `vm.sh run ingest klines funding_archive metrics --universe all` (`all` now holds these members too)
                 `vm.sh run horizon r18_transferbook_1d --holds 864 2016`, then `scripts/r23_check_r22.py` (validity (2))
                 `vm.sh bg r23 horizon --pre --holds 2016` → output/horizon/pre/horizon.md
Folds read:    of FP and F0 (`folds.PREHISTORY`: "the first honest read of a label-free rule found on F1+F2"), the
               days 2021-12-10 → 2023-04-23, for names outside the twelve, once. What was read of these months
               before: the twelve's candles (R4, R6, R8 — not members here); the candles of R10's 32 names from
               2022-08 as training history of R12's and R13 A's fits. No open-interest number and no 7-day label of
               any name. F3, F4, F5: not touched by stage 1.
Gate:          validity PASS, then, for the score at 7 days:
               CLEARS if M_c > 17.6 AND u ≥ 2 AND p ≤ 0.05 AND M > 0 in each half AND the part earned after the
               first day > 0. A candidate on cells that did not choose it; it licenses no trade. Next registration,
               on Vadim's go: the smallest book that trades it at a 7-day hold through the harness, priced (R21's
               pattern); F3+F4 stay whole for that book's confirmation. Stage 2 is not run.
               GO ON if it does not clear and M_c > 17.6: stage 2 is OFFERED to Vadim (it spends F3+F4 for this
               question; his go, not the gate's). If run, the verdict is the pooled one: with w = each stage's share
               of the scored days, M_c(pooled) = w₁·M_c₁ + w₂·M_c₂ and se(pooled) = √(w₁²·se₁² + w₂²·se₂²) (the two
               samples lie 16 months apart); CLEARS if M_c(pooled) > 17.6 AND u(pooled) ≥ 2 AND M_c₂ > 0 AND the part
               after the first day > 0 in stage 2; else NOT DETECTABLE with its MDE, or CLOSED if M_c(pooled) +
               1.96·se(pooled) < 17.6. R22's cells never enter a pooled number: they chose the score.
               PARKED if 17.6 − 1.96·se ≤ M_c ≤ 17.6: it did not come back above its cost on cells that did not
               choose it. No stage 2, no fold spent. Not "no effect" (Principle 5): the MDE is reported.
               CLOSED if M_c + 1.96·se < 17.6: whatever is there cannot pay the round trip.
               The two ways to a yes (stage 1 alone; pooled after a GO ON) together keep the chance of a false yes
               under 5 %: each asks u ≥ 2, and the second is reached one time in four when nothing is there.
               Whatever the verdict: no variant on these cells — no other hold, tenth, window, signal, side or
               weighting; a reference row licenses nothing.
Power:         stated before the read, and it is weak for stage 1 alone. R22's se for this number was 26.9 on 485
               days; 2022 was the more violent year, so the expected se is 25–35 and the MDE (2.8 se) 70–98. To
               CLEAR, M_c must reach 50–70; R22 measured 41 on the cells that chose it, which flatters it. If the
               truth is 41: CLEARS about one time in four, GO ON or better four in five. If it is 20: CLEARS one
               in ten, GO ON or better one in two. If nothing is there: CLEARS one in fifty, PARKED or CLOSED three
               in four. CLOSED needs an se under 9: out of reach. Pooled with stage 2 (se about 19–25): a truth of
               41 clears about one time in two.
Expectation:   validity PASS; 110–150 names are a member at least once; about 700,000 cells; the score on ≥ 97 % of
               them. The score at 7 days: M between −15 and +60, centre +5 … +25, M_c between −25 and +50, se
               25–35, u between −1.0 and +1.8; the bottom tenth, not the top, carries whatever is there, as in R22.
               One day, reference: M +3 … +15. 2022-05 and 2022-11 left out: M lower by up to a third. Verdict:
               GO ON and PARKED about equally likely (four chances in ten each), CLEARS one to two in ten.
Result:        **Read 2026-09-29 (the run 03:01 → 03:11 UTC on the work VM; commit d80bd0e holds this block as written before
               the universe was chosen, e7a7b45 the frozen members before any 5m or metrics file was fetched, 28b2c61
               the code and its tests before any label of these months was computed; output/horizon/pre, 471 shifts):
               the score at 7 days CLEARS the gate. A candidate on cells that did not choose it; it licenses no
               trade. Stage 2 is not run; F3, F4, F5 are untouched.**
               Validity first: PASS. (1) both fetches 141 of 141 names, 0 errors, 0 bad checksums (62,125 new files).
               (2) R22 came back: re-run after the ingest by the unchanged `run`, 21 rows, 694,501 cells, largest
               difference 0.0 on m, centre, se (`output/horizon/r22_check.json`); and `scripts/r23_check_inputs.py`:
               every row the three slices held before the ingest is in them after it, unchanged. (3) 717,222 cells of
               141 names on 500 whole days; 0 cells of a non-member, 0 of the twelve, 0 at or after the end; 471
               shifts. (4) the score is there on 98.5 % of the cells. Two deviations, neither touching a number of
               R23: the ingest was changed before it ran to hold the symbol as a category (commit 85923e8, tested; (2) is
               the check on real data), and the first version of the input check was killed for memory and re-written
               name by name. The read is logged (`output/backtest/confirmation_reads.csv`: R23, FP and F0).
               The family — M · centre · M_c · se · u · one-sided p · H1, H2 · after the first day (bps a leg):
                 oi_score  7d  +66.7 · +14.1 · +52.6 · 21.6 · +2.43 · 0.002 · +105.5, +27.9 · +56.1     CLEARS
               (704,453 cells with the score and a label; interval of M_c [+10.3, +95.0]; MDE 60.5; none of the 471
               shifted books reached +66.7 — the largest +57.1, one in twenty +47.7.)
               Reference rows, outside the family, no verdict (M · M_c · se · u):
                 oi_score   1d +23.3 · +20.7 ·  4.9 · +4.21      3d +46.4 · +39.2 · 11.5 · +3.40
                 oi_turn    1d +27.4 · +23.2 ·  6.1 · +3.82      3d +65.9 · +54.4 · 15.1 · +3.59      7d +86.8 · +65.2 · 32.5 · +2.00
                 oi_chg_1w  1d −21.1 · −20.7 ·  6.0 · −3.48      3d −42.7 · −41.0 · 14.8 · −2.76      7d −53.2 · −47.7 · 31.3 · −1.52
                 oi_chg_1d  1d −14.7 · −14.8 ·  4.1 · −3.59      3d  −4.6 ·  −4.8 ·  7.6 · −0.63      7d  −9.5 ·  −9.4 · 10.8 · −0.87
               Every one has the sign R20 and R22 saw on F1+F2.
               Described, decides nothing (the report's tables; `signals.csv`, `tenths.csv`, `blocks.csv`):
               (D1) the two halves are far apart: M +105.5 in 2021-12-10 → 2022-08-16 and +27.9 in 2022-08-17 →
               2023-04-23. With a centre of about 14 the second half alone sits near the cost, not clearly above it.
               (D2) the two collapses of 2022: with the calendar months 2022-05 and 2022-11 left out M is +43.4 —
               35 % lower, so they carry a third of it and the rest is not theirs. LUNA and LUNA2/1000LUNC are
               members (the archive keeps names that were later delisted); FTT never ranked among the 60.
               (D3) where the money is: on BOTH ends here, and in order. The label against the bar's peers by the
               score's tenth, lowest to highest, mean: −86, −62, −24, −15, −2, +12, +40, +39, +45, +45; median: −220,
               −177, −128, −119, −101, −87, −54, −35, −25, −16. In R22 only the lowest tenth carried it and tenths three
               to nine had no order.
               (D4) the two standard errors: the null's 21.6, the HAC se over days 26.6. By the HAC se M_c reads 1.97
               times its noise and M from zero 2.5.
               (D5) funding's part of M −3.5; rank IC at the hold +0.044 (HAC t 3.2; the top tenth pays the round
               trip at 0.013; the mean move against the peers is 607 bps); a shift keeps 94.7 % of the cells; 58–60
               members with a bar in every block, 55–60 with the score.
               Against the expectation: validity, the names (141), the cells and the coverage as expected; the centre
               inside its band. M (+66.7 against −15 … +60), M_c (+52.6 against −25 … +50) and u (2.43 against −1.0 …
               +1.8) ABOVE their bands; the se NARROWER than expected (21.6 against 25–35). "The bottom tenth, not
               the top, carries whatever is there" was WRONG (D3). The one-day reference above its band (+23.3
               against +3 … +15). "2022-05 and 2022-11 left out: lower by up to a third": 35 %. The verdict CLEARS
               had been given one to two chances in ten.
               Reading: **on 71 weeks that did not choose it, the open-interest score did at a 7-day hold what it did
               on the cells that chose it (+59 there, +67 here; after centring +41 and +53): the names it ranks
               high earned more over the next week than the names it ranks low, by about three times the round trip
               of 17.6, in both halves and beyond what any of 471 re-timed books reached. What this does NOT say:
               that it pays after costs — the cost of trading these names in 2022 is not known, the second half is
               near the cost, no book has been priced, and R21's book lost money at one day on a ranking that was
               also real.**
               Consequences: the score at a 7-day hold is a candidate; it licenses no trade. Stage 2 is not run and
               the pooled rule is not used. Next, on Vadim's go: a registration for the smallest book that trades the
               score at a 7-day hold through the harness, priced (R21's pattern) — its cells, its cost model and its
               gate are that registration's; F3+F4 stay whole for its confirmation. No variant is read on these
               cells under this registration — no other hold, tenth, window, signal, side or weighting; the
               reference rows license nothing.
Re-executed:   **2026-09-30, the re-execution `actual` (§3; the run 06:49 → 06:54 UTC on the work VM, the registered command
               with `--name pre_actual --reexecute actual`; commit a5c47a1 holds the corrected unit and the protocol
               before the run; output/horizon/pre_actual, 471 shifts; logged as R23/actual, FP and F0, beside the
               first read's rows): in actual returns the score at 7 days does NOT clear. By the gate: GO ON — M_c is
               above the cost without clearing. The first read's CLEARS was the unit.**
               Validity first: PASS — (3) and (4) as in the first read: 717,222 cells of 141 names on 500 whole days,
               0 cells of a non-member, 0 of the twelve, 0 at or after the end, 471 shifts, the score on 98.5 % of
               the cells; and the same cells (`same_as_first_read.json`): 12 rows, the cells, days, shifts, the
               share a shift keeps and the rank IC of every row equal the first read's, largest difference 0.0. (1)
               and (2) were checks of the fetch and the ingest and are not repeated (§3). No deviation.
               The family — M (first read, in logs) → M · centre · M_c · se · u · one-sided p · H1, H2 · after the
               first day (bps a leg):
                 oi_score  7d  (+66.7) → +20.4 · −10.2 · +30.7 · 27.2 · +1.13 · 0.12 · +53.3, −12.4 · +18.7     GO ON
               (704,453 cells; interval of M_c [−22.7, +84.1]; MDE 76.3.) Three of the gate's five conditions fail:
               u (1.13 against 2), p (0.12 against 0.05) and the second half, which is negative.
               Reference rows, outside the family, no verdict (M first read → M · M_c · se · u):
                 oi_score   1d (+23.3) →  +5.3 ·  +6.4 ·  5.1 · +1.25     3d (+46.4) → +13.7 · +17.1 · 13.3 · +1.29
                 oi_turn    1d (+27.4) →  +7.0 ·  +8.3 ·  6.8 · +1.22     3d (+65.9) → +22.8 · +27.1 · 19.4 · +1.39     7d (+86.8) → +26.5 · +41.0 · 45.5 · +0.90
                 oi_chg_1w  1d (−21.1) →  −7.7 ·  −6.9 ·  5.7 · −1.21     3d (−42.7) → −18.0 · −15.2 · 15.6 · −0.98     7d (−53.2) → −35.8 · −28.1 · 35.8 · −0.78
                 oi_chg_1d  1d (−14.7) →  −3.4 ·  −3.3 ·  4.2 · −0.77     3d  (−4.6) →  +1.8 ·  +2.3 ·  7.9 · +0.30     7d  (−9.5) →  −0.6 ·  +1.1 · 12.2 · +0.09
               Every sign is the first read's except oi_chg_1d beyond a day; no row reaches 1.4 times its noise,
               where the first read had five rows above 3.
               Described, decides nothing:
               (E1) the two collapses of 2022 are nearly all of it: with 2022-05 and 2022-11 left out M is +3.5
               (first read +43.4). The second half alone is −12.4 (first read +27.9).
               (E2) the ranking is there and the money is not: the rank IC at the hold is unchanged, +0.044 (HAC t
               3.2), and the MEDIAN label against the peers still runs in order from −247 in the score's lowest
               tenth to −48 in its highest. The MEAN runs −27, −37, −14, −7, −1, +9, +27, +20, +19, +9 (first read
               −86, −62, −24, −15, −2, +12, +40, +39, +45, +45): the names the score ranks low usually fall
               behind, and the few of them that soar take most of it back from a sold position.
               (E3) funding's part of M −3.5 as before; the HAC se over days 27.0 (the null's 27.2).
               Reading: **on the 71 weeks that did not choose it, the score at a 7-day hold earns 20 bps a leg in
               actual returns where the log showed 67 — 1.1 times its noise, negative in the second half, and
               nothing without the two collapse months. R24 and R25 were registered on the first read's CLEARS; in
               the unit a position is paid in, that candidate was not there.**
               Consequences: the verdict of this read is GO ON, which by the registration OFFERS stage 2 to Vadim —
               the same number on the outside names of F3+F4, pooled with this one (pooled CLEARS needs M_c > 17.6
               and u ≥ 2). It is his go, not the gate's, and the situation has changed since the registration: those
               months were fetched and read by R25 for this score's book (its own re-execution follows), so they are
               no longer unread for the score. Claude's recommendation is written in P8 after R25's re-execution is
               read. No variant on these cells, as before.
               **Stage 2 is NOT RUN — Vadim, 2026-09-30: "(A1)".** The score at a 7-day hold is closed as a trade idea;
               F3+F4 are not read for this statistic.

### R24 — oibook at a 7-day hold: the open-interest score as a priced book, on both samples that have been read for it (registered 2026-09-29 on Vadim's go, before the pooled read was written and before the rule saw any bar at this hold; read 2026-09-29: CANDIDATE by the gate — taker net +17.2 [−16.7, +51.1] a trade on 5,054 trades, gross +38.6, flip p 0.025, gross positive in both samples; the net's own interval holds zero, and all of the hedged money is the short side; RE-EXECUTED 2026-09-30 in actual returns: NOT FUNDED — taker net −13.9 [−52.9, +25.1], hedged net −11.8, gross +7.5, flip p 0.42, both samples negative)
Question:      R23 found, on cells that did not choose it, that the names the score ranks highest earn over the next 7
               days 67 bps a leg more than the names it ranks lowest, before trading costs (R22, on the cells that
               chose it: 59). That is a measurement on every hourly cell. Traded — one position per name, fees, spread,
               impact and funding paid — does it leave money? R21 asked this at a one-day hold and the answer was no
               (net −17): the ranking was real and the book lost.
Rule:          `ft2/audit.py::OIBook` (`oibook`), R21's rule, UNCHANGED in code; one parameter differs, fixed here:
               hold = 2,016 bars (7 days). k = 6 a side (a tenth of sixty), hourly decisions (grid 12), one unit each,
               the i-th highest and the i-th lowest are one unit (both legs or neither). One position per pair: a name
               held is not entered again until its 7 days are over — so the book takes about one cell in 168 of those
               R22 and R23 measured, the ones at which both names of a unit are free.
Samples:       two, both already read for this score, so this is an exploration read on both:
               PRE — the months before F1: folds FP F0 with R23's frozen members (`ft2/screen_members_pre.csv`); no
               member exists before 2021-12-10, so that is where decisions begin. The market ends at F0's end,
               2023-05-01: a position decided in the last 7 days has no exit and is left out (`unpriced`) — nothing
               at or after F1's first instant is read.
               F12 — F1+F2 with R18's members (`ft2/screen_members.csv`): R21's run at the longer hold.
Cost:          R18's and R21's: the members have no tape; `ft2 costwide`'s pooled candle proxy, fitted on the
               twelve's tape days (2023 →) and, for PRE, applied to days of 2021-12 → 2023-04 — an extrapolation in
               time on top of the one in volume (it over-prices thin names, R10). Every money row is read as priced
               and with spread + impact doubled (re-priced from the run's own decisions). Fees VIP 0 (5 bps a side).
Validity:      read first, or the read is void: (1) `costwide` is re-run from 2021-12-01 and every row of the file as
               it was is in the new one, unchanged (`scripts/r24_check_costwide.py`); (2) `ft2 audit <run> --book` on
               each run: every decision on the hourly grid and on a member of its block, every accepted unit one long
               and one short leg, accepted longs = accepted shorts; (3) PRE has no decision before 2021-12-10 and no
               priced trade whose exit is at or after 2023-05-01.
Statistic:     the harness's, on the two runs' fills POOLED (`ft2 audit --pool`): mean net bps per trade with the
               interval clustered by day over both samples' days, its MDE; the same for gross, hedged and hedged net.
               The flip null pooled draw by draw (each run's draw weighted by its trades; 200 draws).
Commands:      on the work VM, one job at a time —
                 on the VM: `cp data/cost_daily_wide.parquet data/cost_daily_wide_before_r24.parquet`
                 `vm.sh run costwide --universe all --start 2021-12-01`, then `scripts/r24_check_costwide.py`
                 `vm.sh bg r24_pre backtest oibook --universe pre --folds FP F0 --registration R24 --param hold=2016 k=6 members=ft2/screen_members_pre.csv --execs taker maker --name r24_oibook_7d_pre`
                 `vm.sh run audit r24_oibook_7d_pre --book`
                 `vm.sh bg r24_f12 backtest oibook --universe screen --param hold=2016 k=6 --execs taker maker --name r24_oibook_7d_f12`
                 `vm.sh run audit r24_oibook_7d_f12 --book`
                 `vm.sh bg r24_pool audit --pool r24_oibook_7d_pre r24_oibook_7d_f12` → output/backtest/r24_pool/pool.md
Folds read:    FP+F0 (the pre-history, by registration, logged) and F1+F2 (exploration), names outside the twelve. No
               confirmation fold. No download.
Gate:          validity PASS, then on the taker book as priced, the two samples pooled:
               CANDIDATE if net > 0 AND hedged net > 0 AND flip p ≤ 0.05 AND gross > 0 in PRE and in F12. It licenses
               no trade and one next step: a confirmation registration on the members cut point-in-time for F3+F4,
               whose bars, funding and metrics are fetched then — spending those months for this question is Vadim's
               decision.
               CLOSED if the upper end of the net interval is below zero AND the maker net is ≤ 0: the score as a rank
               book at a 7-day hold on a volume-ranked universe is closed, on the data most favourable to it.
               Otherwise NOT FUNDED: no fold is spent on this book; the score stays what R23 left it, a measured
               candidate before costs; revived by a book the harness cannot run today (overlapping positions, so
               that every hourly cell is traded and entries net against exits — a harness change with its own
               registration), by a lower cost on these names, or by new cells.
               Whatever the verdict: no variant on these cells under this registration — no other k, weights, hold,
               grid, feature or side. The shuffle null is reported and does not decide (R21).
Described:     decides nothing. Each sample apart, and PRE's two halves; long and short apart; the maker book; costs
               doubled; trades a day and positions open; the share of the net the five best names carry; the pooled
               net with the trades decided in 2022-05 and 2022-11 left out.
Power:         stated before the read. A name is traded at most once in 7 days, so 60 members give at most about
               4,300 trades a sample; with 25–45 positions open, 1,500–3,000 a sample. A trade's move against its
               peers is about 600 bps in the mean at this hold and the positions of one week move together, so the
               expected se of the pooled net is 15–25 bps a trade and its MDE 42–70. The flip null is expected about
               as wide, centred on minus the cost: to pass it the net must reach about +10 … +25. If the truth
               before costs is what R22 and R23 measured (55–65 a trade) and costs are 20–28, a true net of +30 …
               +40 passes about two times in three; a true net of +15, one in three. CLOSED needs a net below about
               −40 and is out of reach unless the book loses heavily.
Expectation:   validity PASS. Per sample 1,500–3,000 trades (3–6 a day), 25–45 positions open on average. Gross: PRE
               +25 … +70, F12 +15 … +60, the pooled +25 … +60 — below the 59 and 67 of all cells, as R21's trades
               were below its cells. Costs as a taker: fees 10.0, spread and impact 8–16 (PRE the dearer), funding −1
               … −5 → pooled net +0 … +35, hedged net within 5 of it; maker net 4–10 higher; costs doubled 8–16
               lower. Flip p 0.01–0.30. The short side earns more than the long side. About two chances in five
               CANDIDATE, one in twenty CLOSED. Likeliest: a positive net that does not pass the flip null — NOT
               FUNDED.
Result:        **Read 2026-09-29 (the chain 06:45 → 07:58 UTC on the work VM; commit 3c94437 holds this block as written before
               the pooled read was built, db75795 the code and its tests before anything ran;
               output/backtest/r24_oibook_7d_pre, r24_oibook_7d_f12, r24_pool, 200 draws): by the gate, CANDIDATE. It
               licenses no trade and one next step, a confirmation on F3+F4 — Vadim's decision.**
               Validity first: PASS. (1) `costwide` re-run from 2021-12-01: all 89,103 rows of the file as it was are
               in the new one, largest difference 0.0; all 141 early members priced (spread and impact per side:
               median 6.3 bps, one day in twenty above 21). (2) book checks PASS — PRE: 145,644 decisions, 2,630 taken
               in 1,315 whole units, 141 names; F12: 139,212 decisions (R21's count), 2,508 taken in 1,254 units, 185
               names; none off the grid, none on a non-member. (3) PRE's first decision 2021-12-10 00:00, its last
               exit 2023-04-30 18:05; the saved fills re-priced to 0.0. One deviation from the commands: the five
               jobs were started as one chain (`vm.sh bgsh`), each after the one before it — the registered commands,
               in the registered order.
               Taker, as priced, pooled: **5,054 trades** on 222 names (5.1 a day on the days traded; 84 unpriced, see
               (D5)), right on 52 %. Gross **+38.61**, hedged +41.61; fees 10.00, spread and impact 8.84, funding −2.56
               → **net +17.20 [−16.73, +51.14]**, MDE 48.5; hedged net +20.21 [−14.74, +55.15]. Flip null −18.07 ±
               16.44, one in twenty +8.38: **flip p 0.025**. Shuffle null −18.65 ± 15.94, p 0.025 (does not decide).
               Per sample: PRE 2,584 trades, gross +44.60, net +21.90 [−25.28, +69.08]; F12 2,470 trades, gross
               +32.34, net +12.29 [−36.52, +61.11] — gross positive in both.
               Maker, pooled: gross +33.50, fees 4.29, other 0.50 → net +26.14 [−7.86, +60.14], flip p 0.030.
               Costs doubled (re-priced): net **+8.36** [−25.52, +42.25]; PRE +12.01, F12 +4.55.
               Described, decides nothing:
               (D1) the net's own interval holds zero: +17.2 is 1.0 times its day-clustered se (17.3). What passed is
               the flip test — the book's direction earns 35 bps a trade more than the same trades with each day's
               direction chosen by a coin (2.1 sd). That says the direction is right; it does not say with
               confidence that anything is left after costs.
               (D2) all of the hedged money is the SHORT side: short hedged +80.4, hedged net +64.6 [+19.4, +109.7];
               long hedged +2.9, hedged net −24.1 [−70.7, +22.5]. (Unhedged the long side lost 134 and the short
               side made 212: the market fell over these months.) The book is a bet against the names in a frenzy,
               as R21 and R22 described; what it buys adds nothing.
               (D3) PRE's halves: 2021-12-10 → 2022-08-16 gross +80.3, net +57.3 [−13.8, +128.3]; 2022-08-17 →
               2023-04-23 gross +9.7, net −12.6 [−72.4, +47.1]. Without the trades decided in 2022-05 and 2022-11:
               pooled gross +33.7, net +13.0 [−21.9, +47.9].
               (D4) the typical trade and the tail: a trade's net has a median of +62 (PRE) and +35 (F12) against
               means of +22 and +12, and a standard deviation near 1,500 bps. Names: the net summed over trades is
               +86,945 bps on 222 names, 122 positive; five best +98,228 (GALA, THETA, MANA, JASMY, AUDIO), five
               worst −105,635 (MATIC, TRB, AR, EGLD, SRM).
               (D5) the 84 unpriced trades: 70 were decided in the last 7 days of a sample (no exit inside it, as
               registered). Of the other 14, eleven have no exit price — nine around an archive gap in 2022-02, and
               the SHORTS of ANC (2022-05-07) and LUNA (2022-05-09), which stopped trading inside the hold: the book
               is not credited with the two collapses it was short of — and three have a price but no cost day
               (gross +712, +1,522, −911). Leaving them out does not flatter the book.
               (D6) positions open: 33.7 on average in PRE (at most 50), 23.6 in F12 (at most 48).
               Against the expectation: everything inside its band — trades (2,584 and 2,470), gross (+44.6, +32.3,
               pooled +38.6), costs (fees 10.0, spread and impact 8.8, funding −2.6), net (+17.2 against +0 … +35),
               the se (17.3 against 15–25), maker 8.9 higher, costs doubled 8.8 lower, flip p 0.025, the short side
               earning more — except positions open in F12 (23.6 against 25–45). The verdict CANDIDATE had been
               given two chances in five; the likeliest named was NOT FUNDED.
               Reading: **traded with costs, the score at a 7-day hold kept about 17 bps a trade on 5,054 trades —
               positive in both samples, positive with costs doubled, and beyond what the same trades earn with the
               direction left to a coin. It is not certified as profitable: the net is one times its noise, the
               second half of the early sample lost, and the whole of it is the short side. It is the first book in
               this project on names outside the twelve that did not lose money.**
               Consequences: a candidate on exploration data; no trade is licensed. The one next step the gate names
               is a confirmation registration on the members cut point-in-time for F3+F4 (bars, funding, metrics
               and costs fetched then) — spending those months for this question is Vadim's decision. Its power,
               stated now from these numbers: one sample of 69 weeks has a net se of about 24 and a flip null about
               23 wide, so a true net of +17 passes a flip test about one time in two and cannot exclude zero by its
               interval. No variant is read on these cells under this registration — no other k, weights, hold,
               grid, feature or side (a short-only book on (D2) would be one; as a hypothesis for the confirmation
               it would have to be written into that registration before F3+F4 is fetched).
Re-executed:   **2026-09-30, the re-execution `actual` (§3; the steps 06:54 → 07:44 UTC on the work VM, the registered
               commands with `--reexecute actual` and the names `…_actual`; commit a5c47a1 holds the corrected unit and
               the protocol before the run; output/backtest/r24_oibook_7d_pre_actual, r24_oibook_7d_f12_actual,
               r24_pool_actual, 200 draws; PRE logged as R24/actual, FP and F0, beside the first read's rows): in
               actual returns, by the gate, NOT FUNDED. The book lost in both samples. The first read's CANDIDATE
               was the unit.**
               Validity first: PASS. (2) book checks PASS, the first read's counts — PRE 145,644 decisions, 2,630
               taken in 1,315 whole units, 141 names; F12 139,212 decisions, 2,508 taken in 1,254 units, 185 names;
               none off the grid, none on a non-member. (3) PRE's first decision 2021-12-10 00:00, last exit
               2023-04-30 18:05; the fills re-priced to 0.0. The same trades (`same_as_first_read.json`, both
               runs, taker and maker): the decisions are identical row by row; every fill has the first read's
               times, prices, fees, spread and impact, and funding; the first read's fills re-priced with the
               actual return give this run's net to 1e-14. (1), the check of `costwide`'s re-run, is not repeated
               (§3): the cost file is the one the first read used. No deviation from the commands.
               Taker, as priced, pooled (first read, in logs → this read): **5,054 trades** on 222 names, right on
               52 %. Gross (+38.61) → **+7.52**, hedged (+41.61) → +9.61; fees 10.00, spread and impact 8.84,
               funding −2.56, unchanged → **net (+17.20) → −13.89 [−52.87, +25.10]**, MDE 55.7; hedged net (+20.21)
               → −11.79 [−51.31, +27.73]. Flip null −17.69 ± 18.92, one in twenty +12.82: **flip p (0.025) → 0.418**.
               Shuffle null −34.20 ± 18.41, p 0.129 (does not decide). Gate: net > 0 fails, hedged net > 0 fails,
               flip p ≤ 0.05 fails; gross is positive in both samples (+11.64, +3.21). Not CLOSED: the net
               interval's upper end is above zero.
               Per sample: PRE net (+21.90) → −11.07 [−61.45, +39.32]; F12 (+12.29) → −16.84 [−76.72, +43.04].
               Maker, pooled: net (+26.14) → −4.83 [−43.93, +34.26], flip p 0.418. Costs doubled: (+8.36) → −22.72.
               Described, decides nothing:
               (E1) the two sides against the market: short hedged net +44.4 [−8.5, +97.3] (first read +64.6 [+19.4,
               +109.7]), long −67.9 [−111.0, −24.8] (first read −24.1). The sold side no longer stands clear of zero,
               and what the book buys loses more than the sold side makes.
               (E2) PRE's halves: net +21.9 [−50.0, +93.8] and −43.3 [−112.0, +25.3] (first read +57.3, −12.6).
               Without the trades decided in 2022-05 and 2022-11: pooled net −15.8.
               (E3) the tail is the sold side's: the ten largest losses are all shorts of names that rose 80–209 %
               in the week (1000SHIB and 1000BONK of 2024-02-27: −20,789 and −15,964 bps; APT, GALA, ARK, TRB,
               BIGTIME, OP, TURBO, MATIC). With every short closed at the loss of its whole size at most — a
               different rule — the pooled net is −9.3 [−45.0, +26.3], flip p 0.34: a cap does not rescue it here.
               (E4) what the harness still rounds (`described.md`; §3): with the exit leg's costs and each funding
               payment counted on the position's value at that moment the pooled net is −13.83 against −13.89 —
               +0.05 bps a trade in the mean (exit costs +0.21, funding −0.16), though single trades move by up
               to 950 bps (the TRB short of 2023-10-19 paid 2,468 bps of funding, not 1,526). The rounding decides
               nothing on this book.
               (E5) names: the net summed over trades is −70,180 bps on 222 names, 118 positive; five best +79,744
               (THETA, JASMY, MANA, NEO, RNDR), five worst −111,263 (MATIC, APT, TRB, AR, FET).
               Against what §P8 said to expect from the re-pricing (R24 not funded; pooled −13.9, flip p 0.40): as
               expected, to the digit on the net; the flip p is the harness's own 200 draws.
               Reading: **traded with costs and counted as a position earns, the score at a 7-day hold lost 14 bps a
               trade on the two samples that had been read for it — both samples negative, and no better than the
               same trades with the direction left to a coin (four draws in ten did as well). The +17 that made it
               a candidate was the log unit. "The first book outside the twelve that did not lose money" is
               withdrawn: it lost.**
               Consequences: NOT FUNDED — by the registration no fold is spent on this book. One was: R25 was
               registered on the first read's CANDIDATE and read F3+F4 (its re-execution follows). No variant is
               read on these cells, as before.

### R25 — the confirmation read of oibook at a 7-day hold: names outside the twelve, F3+F4, once (registered 2026-09-29 on Vadim's decisions — F3+F4 only, the full book as it is — before the members of F3+F4 were chosen and before any 5m bar, funding or metrics file of an outside name in those months was fetched; read 2026-09-29: by the letter of the gate CONFIRMED (net +69.9, flip p 0.005) — and NOT a confirmation of money: the harness measures a trade in log returns, which flatters every short; re-priced with the actual return the same trades lose 39 a trade. The verdict is held until the read is re-executed on a corrected measure — Vadim's decision; RE-EXECUTED 2026-09-30 in actual returns: NOT CONFIRMED — net −39.4 [−189.3, +110.5], hedged net −39.0, gross −5.6, flip p 0.51; the book is parked)
Question:      R24's book — six names bought, six sold by the open-interest score, held 7 days, every cost paid — kept
               +17 bps a trade on the two samples that had been read for the score, and passed its flip test. Both
               samples had been looked at. On months nobody has read for names outside the twelve, does the same
               book, unchanged, leave money?
Rule:          `ft2/audit.py::OIBook` (`oibook`), UNCHANGED in code and in every parameter from R24: hold 2,016 bars,
               k = 6 a side, hourly decisions, one unit each, the i-th highest and the i-th lowest one unit, one
               position per pair. The score and its three features by `audit.features`, unchanged.
               Vadim's two decisions, 2026-09-29: the months are F3+F4 (F5 stays unread, in reserve); the number that
               decides is the FULL book's. The short side against the market (R24 (D2)) is reported beside it and
               decides nothing — that figure does not pay for its hedge, so it is not a book an account could run.
Universe:      `universe.screen_select(("F3", "F4"))`, unchanged — R18's rule: at the start of each 30-day block of
               F3 and F4 (the harness's own blocks), the 60 USDT perpetuals with the largest median daily quote
               volume over the 30 days before it, a daily bar on each of those days, the twelve left out. Daily bars
               before the block only. Frozen as `ft2/screen_members_f34.csv` and committed BEFORE any 5m kline,
               funding or metrics file of F3+F4 is fetched for a member.
Cost:          R24's: `ft2 costwide`'s pooled candle proxy (fitted on the twelve's tape days; the members have no
               tape), read as priced and with spread + impact doubled (re-priced from the run's own decisions). Fees
               VIP 0 (5 bps a side).
Validity:      read first, or the read is void: (1) every fetch ends with 0 errors and 0 bad checksums, and nothing
               dated 2026-01-01 or later is fetched; (2) every row the three archive slices and the cost file held
               before is in them after, unchanged (`scripts/r23_check_inputs.py`, `scripts/r24_check_costwide.py`,
               against copies taken before), and every member has rows in each source on F3+F4's days; (3) R24's
               saved fills, re-priced on the new slices and costs, come back to 1e-9 (`ft2 audit --pool` on R24's two
               runs under another name: numbers already read); (4) `ft2 audit <run> --book` PASS — every decision on
               the hourly grid and on a member of its block, whole units, longs = shorts; (5) no decision before the
               first block, no priced trade whose exit is at or after 2026-01-01 00:00.
Statistic:     the harness's, on the run's taker fills (`ft2 audit --pool <run> --confirm`): mean net bps per trade,
               interval clustered by day, MDE; gross, hedged, hedged net; the flip null, 200 draws.
Commands:      on the work VM (resized to 32 GB for this: the slices grow to about 72M rows), one job at a time —
                 `vm.sh run universe --screen --folds F3 F4` → `vm.sh pull` → copy output/universe_screen_members.csv to
                   ft2/screen_members_f34.csv, commit
                 on the VM: copies of data/{candles_5m_archive,funding_archive,metrics,cost_daily_wide}.parquet as *_before_r25
                 `vm.sh bg r25_klines archive klines/5m fundingRate --universe f34 --monthly --start 2024-08-01 --end 2025-12-31`
                 `vm.sh bg r25_metrics archive metrics --universe f34 --start 2024-08-01 --end 2025-12-31`
                 `vm.sh run ingest klines funding_archive metrics --universe all`, then `scripts/r23_check_inputs.py r25`
                 `vm.sh run costwide --universe all --start 2021-12-01`, then `scripts/r24_check_costwide.py r25`
                 `vm.sh run audit --pool r24_oibook_7d_pre r24_oibook_7d_f12 --name r25_recheck_r24`
                 `vm.sh bg r25 backtest oibook --universe f34 --folds F3 F4 --registration R25 --param hold=2016 k=6 members=ft2/screen_members_f34.csv --execs taker maker --name r25_oibook_7d_f34`
                 `vm.sh run audit r25_oibook_7d_f34 --book`
                 `vm.sh run audit --pool r25_oibook_7d_f34 --confirm --name r25_read` → output/backtest/r25_read/pool.md
Folds read:    F3+F4, for names outside the twelve, once, logged (`output/backtest/confirmation_reads.csv`). The
               twelve's F3+F4 were read by R16 for another question; no outside name's F3 or F4 has been read by
               anything. F5 is not touched and nothing of it is fetched.
Gate:          validity PASS, then on the taker book as priced:
               CONFIRMED if net > 0 AND hedged net > 0 AND flip p ≤ 0.05. It licenses no money. It licenses one next
               step, on Vadim's decision: a registration for paper trading this book forward (P7's pattern), with the
               hedge, the sizes and the money read fixed there.
               CLOSED if the upper end of the net interval is below zero AND the maker net is ≤ 0.
               Otherwise NOT CONFIRMED, with its MDE: the book is parked. F3+F4 are spent for this question; what
               could revive it is written into §7 then — F5 together with the months that accrue from now on (a new
               registration, Vadim's decision), or a measured lower cost on these names. A miss at this power is
               "not confirmed", not "no effect" (Principle 5).
               The per-fold sign is NOT in the gate, by design and stated now: each fold is 35 weeks, and a real
               effect of R24's size has the wrong sign in one of them about one time in four. F3 and F4 are
               reported apart.
               Whatever the verdict: no variant on these cells — no other k, weights, hold, grid, feature or side;
               the short side's row licenses nothing.
Described:     decides nothing. F3 and F4 apart; long and short apart, hedged; the maker book; costs doubled; trades
               a day and positions open; the unpriced trades and why; the share of the net the five best names
               carry; R24's and this run's fills pooled (5,054 + these), labelled as two-thirds exploration.
Power:         stated before the read, and it is about even odds. R24's samples, each about as long as this one, had
               a net se of 24.1 and 24.9 and a flip null about 23 wide centred on minus the cost: to pass, the net
               must reach about +18 … +22. If the true net is R24's +17: passes about 45 times in 100. If +30: two
               times in three. If nothing is there: one in twenty. The MDE will be near 68. CLOSED needs a net below
               about −47 and is out of reach unless the book loses heavily.
Expectation:   180–230 names are a member at least once, 80–130 of them new to the slices; validity PASS. 2,200–2,700
               trades, 22–34 positions open on average. Gross +0 … +55 (exploration numbers shrink when confirmed:
               R24's +38.6 is the upper middle of the band), costs as a taker 19–23 with funding, net −20 … +35,
               hedged net within 6 of it; maker net 6–10 higher; costs doubled 7–11 lower; flip p 0.02–0.6. The
               short side carries the hedged money again. About one chance in three CONFIRMED. Likeliest: a net
               between 0 and +20 that does not pass the flip test — NOT CONFIRMED.
Result:        **Read 2026-09-29 (the run 15:20 → 15:52 UTC on the work VM, made once; commit a8eb67e holds this block as written
               before the members were chosen, 04a968f the frozen members before any file of F3+F4 was fetched;
               output/backtest/r25_oibook_7d_f34, r25_read, 200 draws): by the letter of the gate, CONFIRMED. The
               number the gate reads is defective (D1): it is not what a position earns. THE VERDICT IS HELD — nothing
               is licensed, no paper trading is proposed — until the read is re-executed on a corrected measure.**
               Validity first: PASS. (1) both fetches 216 of 216 names, 83,381 new files, 0 errors, 0 bad checksums,
               no file dated 2026 for an outside name. (2) every row the three slices and the cost file held before
               is in them after, unchanged; no new row dated 2026-01-01 or later; all 216 members have rows in each
               source and a cost. (3) R24's 5,054 saved fills re-priced on the new slices: largest difference 0.0.
               (4) book check PASS: 138,996 decisions, 2,408 taken in 1,204 whole units, 208 names, none off the grid,
               none on a non-member. (5) first decision 2024-09-03 00:00, last exit 2025-12-31 22:05. One deviation:
               the run, its book check and the read were started as one chain, in the registered order.
               The gate's numbers, as the harness measures them (taker, as priced): 2,368 trades on 200 names (40
               unpriced: 38 decided in the last 7 days; BNX long +6,360 and AIA short +6,088 had no cost day), right
               on 52 %. Gross +103.77, hedged +104.88; fees 10.00, spread and impact 11.89, funding −11.96 → net
               +69.92 [−4.21, +144.05], MDE 105.9; hedged net +71.03; flip null −24.04 ± 30.47, flip p 0.005 (no draw
               reached it); F3 net +96.4, F4 +42.2; maker net +82.08; costs doubled +58.03; long hedged net +42.0,
               short +100.1; with R24's fills (7,422 trades) net +34.0 [+0.7, +67.3].
               (D1) THE DEFECT, found at this read because the result stood far outside its band. The harness
               (`backtest.price`, since P3) measures a trade's gross as side × log(exit / entry); `horizon.labels`
               (R22, R23) is the same move. A position of fixed size earns side × (exit / entry − 1). On small
               moves the two agree. Here they do not: the log OVERSTATES every short and UNDERSTATES every long, by
               about half the squared move — and this book's shorts are its most violent names (a week's move: 22 %
               sd on the short side against 14 % on the long; one trade in ten moves more than 25 %). AIA 4.9 → 1.0
               is +16,319 bps for a short in logs and +7,960 in fact; MYX 1.13 → 17.96 is −27,660 in logs and −148,956
               in fact.
               (D2) the same trades, re-priced with the actual return — decisions, prices, costs and funding the
               runs' own, the flip null drawn again (`scripts/r25_describe_simple.py` → r25_read/simple.md):
                                           gross     net  [interval]          flip p
                 this run, log            +103.8   +69.9  [ −4.2, +144.1]      0.005
                 this run, actual           −5.6   −39.4  [−189.3, +110.5]     0.59
                 this run, actual, capped  +66.3   +32.5  [ −39.8, +104.7]     0.02
                 R24 pooled, log           +38.6   +17.2  [ −16.7,  +51.1]     0.01
                 R24 pooled, actual         +7.5   −13.9  [ −52.9,  +25.1]     0.40
                 R24 pooled, actual, capped +12.1   −9.3  [ −45.0,  +26.3]     0.34
               "capped": every short closed with the loss of its whole size at most — what an exchange does to a
               position whose margin is its size. It is a different rule (a stop), not a correction, and it was
               looked at after the read: it decides nothing. One trade, the MYX short of 2025-09-04, is 63 of the
               105 bps between this run's capped and uncapped net.
               (D3) what the defect touches. R22's and R23's statistic (log labels): the top tenth against the
               bottom tenth was measured in the same units, and the bottom tenth — the names in a frenzy — is the
               more violent one, so part or all of the +59 and +67 is the same overstatement; not yet re-measured.
               R24: above. R21 (one day): net −17.3 in logs, −25.3 in fact. The twelve's candle ridge, the other way:
               R14 net +34.2 in logs, +39.2 in fact; R16 +33.1 and +41.2 — its money is on the long side, which the
               log understates. P7's ledger stores prices, not money (`serve.ledger`), so nothing live is touched;
               R17's money read must use the actual return.
               Against the expectation: the members (216), the new names (119), validity and trades (2,368) as
               expected; costs above their band (21.9 before funding, funding −12.0), as the cost check had said
               before the run; gross, net and flip p far outside their bands on the side of "too good" — which is
               what led to (D1). The se was 37.8 where 24 was expected.
               Reading: **the confirmation passed its gate on a number that is not money. Measured as a position
               earns, the book lost in all three samples it has been run on (−11, −17, −39 a trade), and the one
               sample that looks positive with a cap owes it to where the cap sits on a single trade. The idea that
               ran from R22 to here — names in a frenzy fall behind — may be in part an artefact of the unit it was
               measured in. Nothing is licensed.**
               Consequences: the verdict is HELD, not recorded as CONFIRMED and not as failed. What the project's
               rules ask for when a measurement is found defective is re-execution of the registered reads on the
               corrected measure, the new verdicts replacing these, both kept (P8 "What next"): Vadim's decision.
               F3+F4 are spent for this question either way; F5 is untouched.
Re-executed:   **2026-09-30, the re-execution `actual` (§3; the run 07:44 → 08:17 UTC on the work VM, its book check, the
               same-trades check and the read 08:17 → 08:33, the registered commands with `--reexecute actual` and
               the names `…_actual`; commit a5c47a1 holds the corrected unit and the protocol before the run;
               output/backtest/r25_oibook_7d_f34_actual, r25_read_actual, 200 draws; logged as R25/actual, F3 and
               F4, beside the first read's rows): in actual returns, by the gate, NOT CONFIRMED. The hold on the
               verdict is lifted: this is R25's verdict. The book is parked.**
               Validity first: PASS. (4) book check PASS, the first read's counts: 138,996 decisions, 2,408 taken in
               1,204 whole units, 208 names, none off the grid, none on a non-member. (5) first decision 2024-09-03
               00:00, last exit 2025-12-31 22:05; the fills re-priced to 0.0. The same trades
               (`same_as_first_read.json`, taker and maker): the decisions are identical row by row; every fill
               has the first read's times, prices, fees, spread and impact, and funding; the first read's fills
               re-priced with the actual return give this run's net to 1e-14. (1)–(3), the checks of the fetch and
               the ingest, are not repeated (§3). No deviation from the commands.
               The gate's numbers (taker, as priced; first read, in logs → this read): 2,368 trades on 200 names,
               right on 52 %. Gross (+103.77) → **−5.56**, hedged (+104.88) → −5.16; fees 10.00, spread and impact
               11.89, funding −11.96, unchanged → **net (+69.92) → −39.41 [−189.28, +110.46]**, MDE 214.1; hedged net
               (+71.03) → −39.01 [−189.75, +111.73]; flip null −24.49 ± 69.96, one in twenty +80.53, **flip p (0.005)
               → 0.512**. All three conditions of CONFIRMED fail. Not CLOSED: the net interval's upper end is above
               zero (maker net −27.23). Shuffle null −32.23 ± 55.33, p 0.62 (does not decide).
               F3 net +49.1 [−58.5, +156.7], F4 −132.1 [−412.7, +148.7] (first read +96.4, +42.2); costs doubled
               −51.30; with R24's re-executed fills (7,422 trades, two thirds exploration) net −22.0 [−76.8, +32.7].
               Described, decides nothing:
               (E1) the sample is far noisier in actual returns: the net's se is 76.5 bps where the log showed 37.8
               and 24 had been expected, and the MDE 214. One name does most of it — MYX: the shorts of 2025-08-04
               (0.43 → 1.71) and 2025-09-04 (1.13 → 17.96) lost 36,941 and 151,900 bps. The five worst names sum
               to −243,818 bps (MYX, H, KAITO, FARTCOIN, SUI), the five best to +88,815; the net summed over trades
               is −93,319 on 200 names, 100 of them positive.
               (E2) the two sides: long net −48.2, hedged net −70.2 [−165.4, +25.0]; short net −30.6, hedged net −7.8
               [−265.2, +249.6] (first read: short hedged net +100.1). Neither side earns against the market.
               (E3) with every short closed at the loss of its whole size at most — a different rule — net +32.5
               [−39.8, +104.7], flip p 0.02, as the first read's (D2) had it. Four shorts are capped; one of them (MYX,
               2025-09-04) is 58.7 of the 71.9 bps between the two (counted again here; (D2) wrote "63 of the
               105"). On R24's samples the same cap leaves −9.3 (R24 (E3)).
               (E4) what the harness still rounds matters HERE (`described.md`; §3). With each funding payment
               counted on the position's value at that moment, and the exit leg's costs on its value at the exit,
               the net is −66.7 [−251.4, +117.9], not −39.4: 27.3 bps a trade worse, all of it funding (−27.6;
               exit costs +0.3) and all of it on the sold side (−55 a short). Ten trades carry 87 % of it: the two
               MYX shorts paid 47,059 and 25,897 bps of funding on a position that had grown 16- and 4-fold, where
               the sum of the rates says 2,920 and 7,211. On R24's samples the same correction was +0.05. It
               changes no verdict — it makes this one worse — and it is written into §7 as a change the harness
               needs before another book of this kind is read.
               Against what P8 said to expect from the re-pricing (R25 not confirmed; −39.4, flip p 0.59): the net
               to the digit; the flip p is the harness's own 200 draws (0.51).
               Reading: **on 69 weeks nobody had read, counted as a position earns, the book lost 39 bps a trade
               (67 with funding counted on what the position had become), no better than a coin's direction. It
               is not shown to lose either: this sample can only see an effect above 214 bps, because a sold
               position in a name that rises sixteen-fold is what decides the mean. The chain R22 → R25 rested on
               the log unit at every link: the lean (R22), the candidate before costs (R23) and the candidate
               after costs (R24) are all gone in actual returns.**
               Consequences: NOT CONFIRMED — the book is parked, nothing is licensed, no paper trading is proposed.
               F3+F4 are spent for this question. As registered, what could revive it is a new registration on F5
               together with the months that accrue, or a measured lower cost — neither is proposed: the book
               lost on all three samples, and its gross before costs is +11.6, +3.2 and −5.6 — under its costs in each. A book
               with a protective stop is a new rule (P8 "What next"). No variant on these cells.

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
| 1 | **Historical book depth, tape and flow for the same twelve pairs** | Binance's public archive (`data.binance.vision`, USDⓈ-M futures; free, no key). **Coverage measured 2026-09-15:** depth within ±1..5 % of mid (`bookDepth`, 30 s) **2023-01-01 → today** for every pair (from listing for the younger ones), ~0.5 MB/day/pair; 5m open interest + long/short + taker ratios (`metrics`) 2021-12-01 → today (BTCUSDT alone from 2020-09-01; corrected 2026-09-29 from the archive's listing); the full tape (`aggTrades`) 2019-12 → today, **~136 GB zipped for our pairs from 2023-01** (BTC 14–27 MB/day); funding monthly since 2020. Best bid/ask (`bookTicker`) was discontinued in 2024 and **`bookDepth` does not replace it** (no touch prices in it) — the historical spread is estimated from the tape's bid–ask bounce. 1m klines back to 2019-12 (2.7 years more than the collector holds). | The single biggest gap in our data was that book, tape and flow existed for two months while candles existed for four years. This closes it back to 2023-01: P1's cost model is measured over 3.7 years instead of proxied, and book/flow features (§7) become testable in a powered walk-forward over F1–F5. **Done in P0b** (`bookDepth`, `metrics`, `fundingRate` ingested; DATA.md); the tape is streamed to a per-minute summary in P1 (`ft2 tape`, not kept raw). | P0b ✅ → P1, P2 |
| 2 | **Candles for a wider universe** (the top ~30–50 USDⓈ-M perps by volume, 5m and 1h) | same archive | Breadth: the plan's edge comes from many semi-independent bets, and a cross-sectional strategy on twelve names is thin. More names also gives a cleaner "market" factor. The collector need not record them for research; only for trading later. **Done 2026-09-22 for R10:** `ft2 universe` chose 40 (`ft2/universe.py::WIDE`, ranking in output/universe_wide.md), monthly 5m klines 2022-04 → 2024-08 and funding for the 32 the collector lacks are in `candles_5m_archive` / `funding_archive` (DATA.md); their cost is `ft2 costwide`'s pooled candle proxy. | R10 (P5 step 5) |
| 3 | **Spot klines for the same symbols** | same archive (spot) | Basis (perp minus spot) and its changes, a known carry/flow signal; also a cleaner index for the market factor. **Read as the exchange's premium index in R20 (2026-09-28), 188 names, per name against its peers at one day: CLOSED** (IC +0.000 and +0.006, upper bounds 0.008 and 0.017). Spot klines themselves were not fetched | R20 ✅ (premium index); spot klines parked |
| 4 | **Same pairs on a second venue** (Bybit / OKX perps, 1m klines) | their public archives | Cross-venue lead-lag at short horizons; only relevant if P2 funds a sub-15m horizon | parked |
| 5 | On-chain, news, sentiment | various | Low prior at these horizons, high engineering cost; not now | parked |
| 6 | **Open interest, funding and positioning as SCREENER characteristics** (Vadim's question 2026-09-27: "new features?") | the archive's `metrics` and `fundingRate`, every symbol, free | R15 found they add nothing as model inputs on the twelve. Not tested: as things a screener ranks names by (open interest over volume = crowded, funding at an extreme). Per name, so it has breadth. **Read directly against the next day's move in R20 (2026-09-28): funding closed; open interest over volume and open-interest change NOT DETECTABLE and the nearest (IC +0.033, −0.019, −0.016)**; `metrics` for the 188 members is on the work VM | R20 ✅ as a ceiling audit; as screens of a forecast still parked (the forecast has nothing to sort, R18) |
| 7 | **Market-wide daily series: spot-ETF net flows (BTC from 2024-01-11, ETH from 2024-07-23), stablecoin supply, Deribit implied volatility (DVOL), macro dates (FOMC, CPI)** (Vadim, 2026-09-27) | Farside tables (scrape), DefiLlama, Deribit API, a calendar; all free | One number a day for the whole market: ≈ 650 days of ETF history, so only an IC ≥ 0.1 is detectable, and it is a market-direction input where our surviving signal is pair-vs-peers. Best uses: (a) BTC/ETH against the alts the day after a large flow; (b) a regime switch or a size multiplier. Known-at time matters: a day's flow is published after the US close, usable from ≈ 03:00 UTC the next day. **US stock indices (S&P 500, Nasdaq; Vadim, 2026-09-27)** belong to this family with two differences: index futures trade almost round the clock on weekdays, so the series is intraday and covers all folds, and it is closed at weekends (a regime of its own). Still one number for the whole market: to reach pair-vs-peers it enters as EACH NAME'S trailing sensitivity to the index × the index's recent move, which is per name and has breadth — the same construction applies to the ETF flows. Source to audit: free minute history of the index ETFs or futures, and a live feed the serve host can read | parked — one ceiling screen for the family (P2 style, F2–F4 days), when R18 is read |
| 8 | **Scheduled per-name events: token unlocks, listings and delistings, exchange "monitoring" tags** | DefiLlama unlocks, Binance announcements | Known in advance, per name, and about exactly the young names R14's money sits in. Risk: the history of announcements is hard to reconstruct without hindsight | parked — after #3 and #6; needs a source audit first |

Rule for adding any of them: a raw download lands under `data/raw/external/<source>/`, is
ingested by `ft2 ingest` into its own parquet, and gets a row in DATA.md with its measured
extent and its integrity check before any phase reads it.
