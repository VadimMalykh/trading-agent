# Book-era plan — the B-wave

**Status:** ✅ **B4** (2026-08-28), ✅ **B0** (2026-08-29), ✅ **B1** and ✅ **B2** (2026-08-31)
— **the measurement half of this wave is complete.** Both gates came back the same way and it is
the outcome §4.2 pre-registered: **the book era is too short to decide anything**, not "the book
is useless". B1 is `NOT EVALUABLE` (its n floor is unreachable by ~1%), B2 is `NOT YET DECIDABLE`
(the incumbent observable fails its own gate on this window). 🔴 **B3 is therefore BLOCKED, not
refused.** The wave's binding constraint is now **calendar**: §4.4's ≥90 days of book history,
≈2026-10-15. Runs **in parallel with M3**,
blocks nothing, and is blocked by nothing.
Indexed in [BACKLOG.md](./BACKLOG.md), which carries the revival trigger for each step.

🟢 **B4 is done, and B4.3 answered `DEPTH_OK` — the headline result of this wave so far.**
The collector fixes were verified live on `fluxtrader-1` on 2026-08-28 (§2 B4 records the
acceptance numbers), and the `@depth` WebSocket stream turns out to be **reachable** from the
VM's egress: 586 `depthUpdate` frames in a 60s window. **The 5s REST cadence is therefore not
the permanent fidelity ceiling this plan assumed it might be** — the pessimistic branch, in
which §1.2's fee-wall arithmetic was the only lever left at short horizons, does not apply. A
WS depth consumer is now a buildable option rather than a blocked one.

🟢 **Two things that landed on 2026-08-28 make B0 much cheaper than this plan assumed.** The
M3-4 export (`scripts/gcp_m3_export.sh`) already pulled, to `ml/train/output/m3_4/`, exactly
the slices B0 needs: the 20-level ladder, `orderbook_snapshots`, `market_trades`, 5m candles
and `funding_rates`, over 2026-08-05..28 for all 12 pairs. **B0 is now an alignment job on
data already on disk, not an export job** — and M3-0b shares that same pull, which is what
this plan meant by "one alignment, two consumers".
**GPU required:** **No, at any step.** B0–B2 are laptop `pandas`. B3 is LightGBM on CPU, on its own
throwaway VM (`gcp_gbt.sh`), which is explicitly designed to run concurrently with anything else.
**Keys required:** No.
**Related:** [M3_PLAN.md](./M3_PLAN.md) (B0 shares its side-table with M3-0b; B2 consumes its harness) ·
[NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) §1.7 (data status), §5 (the retired ON/OFF design) ·
[DATA_COLLECTION_AUDIT.md](./archive/DATA_COLLECTION_AUDIT.md) (what the collector keeps and drops)

*Written 2026-08-24. Holds only what is currently true and actionable. When a step's conclusions are
superseded, move the narrative to `docs/archive/TRAINING_HISTORY.md` and carry the surviving
conclusion forward — do not append a contradicting section.*

---

## §0 — READ THIS FIRST (plain language, no statistics required)

### 0.1 The question this wave exists to answer

We have been collecting order-book data since 2026-07-17. It is now ~38 days deep on the majors.
That is entirely inside the *validation* period of every model we have trained, so across the
training window those 12 columns are constant and get zeroed — the served model genuinely runs on
seven columns of price and volume.

The obvious idea is: **train a separate, smaller model only on the window where book data exists,
at a short horizon, and use it alongside the main model.** This document is the plan for finding
out whether that works, without spending a wave of training runs to discover it does not.

### 0.2 What we already know, in one paragraph

Two things point in opposite directions, and both are real.

**Pointing yes:** a read-only feature audit ran on 2026-08-04 with only ~9 days of book data and
came back **ESCALATE** — 31 stable, directional feature/pair/horizon hits, strongest `|Spearman|`
0.177. That was a genuine signal that something is in there. And the book question was formally
retired as a *design* (the ON/OFF walk-forward), not as a *question*; its designated replacement —
within-model attribution, filed as **O5** — was never run, because M2 froze first. There is real
unfinished business here.

**Pointing no:** the edge we can already measure gets rapidly worse as the horizon shortens, while
the fee does not move. At 4h the model earns +22 gross bps per trade on its best 2% of bars. At 1h
the same model earns **+2.6**. A round trip costs 14bps as a taker and 5bps as a maker. The 1m–5m
horizons where order-book data is supposed to shine are further down that same slope, and this is
mostly arithmetic rather than a fact about our model: at a 1-minute horizon the entire move you are
predicting is roughly 17bps wide, so a 14bps taker round trip eats almost all of it even if you
predict direction perfectly.

### 0.3 What we are therefore going to do

**Measure before training.** Three cheap laptop steps (B0–B2) that cost no GPU and no training run,
each with a number written down *in advance* that decides whether the next step happens. Only if
those pass do we spend one CPU training run (B3), and it is one run with a pre-registered gate, not
a search.

The single most important discipline: **report everything in basis points, not correlations.** A
Spearman rho of 0.05 sounds like a finding. The question that matters is whether the best 2% of
bars picked by that feature earn more than 14 basis points, and rho does not answer it. The
2026-08-04 audit's ESCALATE was measured in rho, escalated to a training run, and that run was
inconclusive. We are not repeating that loop.

### 0.4 The most likely outcome, stated up front so nobody is surprised

The audit's strongest single finding was `spread_bps`, and the audit classified it **VOL-PROXY** —
it predicts *how big* the next move is, not *which way*. That is not useful to M2, which emits
direction. It is potentially very useful to **M3**, whose largest measured effect (Q1's 4×) is
exactly a "how volatile is it right now" regime switch, currently keyed off BTC's trailing 24h
move. A book-derived volatility observable would be *contemporaneous* rather than trailing.

So the most probable result of this wave is not "a second model". It is **one or two new regime
observables for M3's policy**. B2 is the step that tests that, and it is the highest-expected-value
item in this document. Budget attention accordingly.

---

## §1 — THE EVIDENCE THIS PLAN IS BUILT ON

### 1.1 🔴 The horizon curve — new, and it is the central fact

Every eval prints all three horizons; nobody had put them side by side. Gross bps/trade across the
three baseline seeds (`20260818T185438Z` / `20260819T142759Z` / `20260820T025723Z`), read from
`logs/O2.log`, `logs/P0-seed2.log`, `logs/P0-seed3.log`:

| horizon | cov 0.01 (s1/s2/s3) | cov 0.02 (s1/s2/s3) | mean @ cov 0.02 | clears 14bps taker? |
|---|---|---|---:|---|
| **60m** | +6.85 / +4.47 / +10.15 | +0.81 / +0.99 / +5.87 | **+2.6** | **no, at any coverage** |
| **240m** | +24.50 / +16.59 / +14.47 | +22.11 / +16.83 / +26.23 | **+21.7** | yes |
| 1440m | −24.13 / −6.12 / +41.62 | −11.58 / +22.68 / +14.48 | +8.5 | n=126–209, noise |

And P2 (the 1m-bar run, 14.5M samples — no data shortage whatsoever) at its 60m horizon:
gross bps/trade of **−0.67 / −0.54 / +0.43 / +1.41 / +0.58** across the five coverages,
`dir_acc` 0.516–0.526. Flat.

The edge builds with horizon, peaks at 4h, and at 1h is already ~8× too small to pay a taker round
trip. Note the 60m row is *worse* than pure volatility scaling predicts (≈+11 expected), so skill
itself decays at short horizons on top of the arithmetic.

### 1.2 The fee wall, in the units that decide it

At 240m the per-trade sd on the cov05 slice is 259bps and the model captures +22 — about **8.5% of
one standard deviation**. That capture rate is roughly scale-free; the move it is applied to is not.

| horizon | move sd (√t from 259bps @ 240m) | 8.5%-of-sd capture | vs 14bps taker | vs 5bps maker |
|---|---:|---:|---|---|
| 1m | ~17 bps | ~1.4 bps | no | no |
| 5m | ~37 bps | ~3.1 bps | no | no |
| 60m | ~130 bps | ~11 bps | no *(measured +2.6)* | marginal |
| 240m | 259 bps | ~22 bps | **yes** | yes |

Break-even at the current skill level lands near **97 minutes for taker and 12 minutes for maker**.
To make a 5m strategy work, capture would have to rise from 8.5% of a standard deviation to ~38% —
a 4.5× improvement in skill, not 4.5%.

🔴 **The √t column is an estimate, not a measurement.** B1 measures the real per-horizon sd from the
side-table and this table gets rewritten with actual numbers. If the real 5m sd is materially higher
than 37bps — plausible, since selected bars are volatile bars — the wall moves and B3's case
improves. Do not quote this table as measured until B1 has run.

### 1.3 The three attempts that already failed, and exactly what failed

This matters because the wave must not be a fourth instance of it.

| attempt | design | result |
|---|---|---|
| 2026-08-04 ablate | book ON/OFF, single dense window, 30m | ON lb 0.691 / OFF 0.494 — **one lucky 2.7-day window** |
| 2026-08-04 walk-forward | 3 folds | min fold gap **−0.030**; best epochs 2–5 with val loss already rising |
| F3 `wf-20260817T030350Z` | 8 pairs | min gap **−0.161** |
| N1 `wf-20260818T063858Z` | 4 long pairs, `n_dir ≥ 500` floor | **2 of 6 folds decidable**; gaps +0.073 and −0.122 → inconclusive |

The failure was structural and is worth stating precisely: **the book-OFF arm's characteristic
failure is collapsing to an all-flat predictor**, which spends its top-5% confidence on genuinely
flat bars and leaves too few directional trades to score. Collapse is what makes a fold
undecidable — so the more the book actually helps, the less measurable that help becomes. No
re-launch fixes that. `gcp_walkforward.sh` is not used anywhere in this document.

The archive's own diagnosis of the walk-forward was **"data quantity, not model"**, with a stated
trigger to re-run at ≥30 days of book history (≈2026-08-25). That trigger fires tomorrow. This
document is deliberately *not* "re-run the walk-forward at 30 days" — the design is retired for the
reason above, and 30 days does not repair a design that cannot decide.

### 1.4 The audit that said ESCALATE, and why re-running it unchanged is not enough

`ml/train/audit_microstructure.py` already exists, is read-only, and already does per-feature
Spearman + decile monotonicity + sign-accuracy + a stability and vol-control deep dive. It ran on
2026-08-04 (`logs/audit.log`, `audit-20260804T061143Z`) on ~9 days and concluded:

> => 31 STABLE+DIRECTIONAL signal(s) ... ESCALATE: this is genuine directional content beyond
> volatility. Next: dense-window ablation training run (book features on vs off).

We followed that advice, three times, and got nothing decidable. Before trusting the same verdict
again, note three defects in how it is measured:

1. **No multiple-comparison control.** 8 pairs × 3 horizons × 11 features ≈ 264 tests. At a
   per-test threshold of `|rho| > 0.03` and `LB > 0.51`, ~13 hits are expected from chance alone.
   31 hits is not obviously more than noise, and the doc does not say so.
2. **No holdout.** Rho is measured on the same rows used to notice it. A feature's sign must be
   fitted on one part of the book era and scored on another.
3. **No economic units.** Everything is in rho and dir_acc. The decision needs bps against a
   14bps/5bps cost line, and rho does not convert.

So B1 is a **re-run with those three fixes**, not a re-run.

### 1.5 The data inventory, as of 2026-08-24

| source | coverage |
|---|---|
| `orderbook_snapshots` (11 scalars, what training reads) | BTC/ETH/SOL **~38d** (from 2026-07-17) · DOGE/HYPE/WLD ~34d · ZEC ~30d · 1000PEPE ~28d · ADA/AVAX/LINK/XRP ~10d |
| `orderbook_levels` (raw L2, 100+100) | 8 pairs **~19d** (from 2026-08-05). **Nothing on the Python side reads this yet.** |
| `market_trades`, `open_interest` | mirror the snapshots |
| `funding_rates` | 2y9mo–3y11mo — real history, and already a live feature |
| `long_short_ratios` (B4.2) | **starts 2026-08-24**, plus the ~30d the exchange still held. Not in any model yet; collector-only from here. |
| `liquidations` | 0 rows, WS egress blocked from datacenters. Not in any plan. |

🔴 **Re-verify before B0** — this table is copied forward from 2026-08-18 plus elapsed days, not
freshly measured. `./scripts/gcp_data_collection_stats.sh` is the slow full report; the fast version
is the ad-hoc query pattern in NEXT_TRAINING_PLAN §0.1.

Rough sample budget at ~314 pair-days: **~90k samples at 5m**, ~450k at 1m — about **3%** of the
current baseline's 2.90M either way. A chronological 80/20 split leaves a **~7-day** validation
window. The book era is **11.0%** of the current val bars (63,539 of 579,157, from `logs/O2.log`).

### 1.6 Is it decidable at all? The power calculation, honestly

This is the crux of "is it worth trying", so it is written out rather than asserted.

**At the horizons the failed attempts used (30m–240m): no.** Restricted to the book era, cov 0.02
gives ~195 trades. With per-trade sd 259bps that is a SEM of 18.5bps and a 95% CI half-width of
**±36bps** — wider than the entire +22bps effect we are trying to detect. The book era literally
cannot distinguish "as good as the current model" from "zero". That is why three attempts produced
zero decidable verdicts, and it is not fixable by a better model.

**At 5m, and this genuinely cuts the other way: yes, plausibly.** A 5m-horizon book-era model has a
~18k-bar val slice, so cov 0.02 is ~360 trades — and per-trade sd falls to ~37bps because the move
is smaller. Naive SEM ≈ 1.9bps. Even collapsing the 8 highly-correlated pairs to ~1.5–2 effective
instruments (crypto is close to one factor, and their own §5 notes cross-pair correlation inflates
SE by ~1.6× over *8 months*; over 7 days it is worse) gives SEM ≈ 4.4bps, CI ≈ **±8.6bps** against a
14bps decision threshold. That is decidable.

**So the honest position is:** the short-horizon book question is *not* underpowered in the way the
previous attempts were. What blocks it is (a) the fee wall of §1.2 and (b) regime coverage — a
7-day validation window is **one** market regime, and the project's single largest measured effect
is that the edge depends on regime. B1 and B2 attack (a) directly and cheaply. Nothing attacks (b)
except the calendar.

---

## §2 — THE RUN QUEUE

Serial within this wave, parallel with M3. **Do not skip a gate.** Each item names what to run and
what to bring back.

| item | what | cost | GPU? | gated on |
|---|---|---|---|---|
| **B0** | Book-era side-table → parquet | ~1h laptop + one VM dump | no | nothing |
| **B1** | Economic information check (the fixed audit) | ~1 afternoon laptop | no | B0 |
| **B2** | Book features as **M3 regime observables** | ~1 afternoon laptop | no | B0, M3-0a |
| **B3** | One book-era GBT, pre-registered | ~1h on its own CPU VM | no | **B1 passing §4.1** |
| **B4** | Collection fixes (unrecoverable if deferred) | small Elixir change | no | ✅ **DONE — deployed and verified 2026-08-28** |

**B4 was independent of the rest and is complete** (see below): deployed, all three acceptance
checks passed, and B4.3 returned `DEPTH_OK`. Everything else can queue behind M3's attention.

### B0 — ✅ DONE (2026-08-29). The book-era side-table exists and passed its acceptance test.

**Built as an extension of M3-0b, in one alignment, exactly as this section asked** — the code
is `ml/train/m3/sidetable.py` and the command is `./scripts/m3.sh -m m3 bookera`. Full record:
[M3_0B_RESULTS.md](./M3_0B_RESULTS.md) §6.

* `book_era_5m.parquet` — 79,488 rows x 12 pairs, 2026-08-05..27
* `book_era_1m.parquet` — 423,130 rows x 12 pairs, 2026-08-05..29

🔴 **The mandatory acceptance test passed** on all four eval dumps: `fwd_ret_240` matches each
dump's own `fwd_ret` on a `(pair, ts)` join for every overlapping row (29,440 / 31,352 / 32,544
/ 55,524), exactly rather than to a tolerance — the dumps store `fwd_ret` as float32, so exact
equality after a float32 round-trip is the sharper test. It is run *separately* from M3-0b's
own acceptance test because the two tables are built from different exports.

**Bring-back, as this section required:** row counts per pair per interval and the non-stale
fraction per feature are printed by the command. Book freshness is **0.9994 on the eight main
pairs and 0.6028 on ADA/AVAX/LINK/XRP** at 5m — the expected reading, and a useful check: those
four joined the collector on 2026-08-14, which is 14 of the window's 23 days (14/23 = 0.609).

⚠️ **Nine of the eleven scalars are built. `oi` and `oi_chg` are missing** because
`open_interest` is not one of the tables `scripts/gcp_m3_export.sh` pulls. That is a one-line
export change, **not** an alignment change, and it is filed in [BACKLOG.md](./BACKLOG.md). B1
and B2 can proceed on nine.

<details><summary>The original B0 specification, kept for reference</summary>

**Build this as an extension of M3-0b, not as a separate artifact.** M3-0b already calls for
exporting 5m candles + `funding_rates` for the eight served pairs to local parquet, joined on
`(pair, ts)`. Add the book columns to the same export and both wavefronts are served by one dump.

Export from the always-on VM (§0.1 of NEXT_TRAINING_PLAN: the VM is the source of truth, never the
local DB) over the book era for the 8 main pairs:

- `orderbook_snapshots` → the 5 scalars `features.py` already derives: `spread_bps`, `imbalance`,
  `micro_mid`, `bid_ask_vol_ratio`, `depth_near_imb`
- `market_trades` → `trade_count`, `buy_sell_imb`, `trade_vol`
- `open_interest` → `oi`, `oi_chg`; `funding_rates` → `funding`
- 1m and 5m candles over the same window, for the forward returns

Resample onto both a 1m and a 5m bar grid using **the same asof-join and the same staleness caps as
training** — `_align_with_age` / `_stale_mask` with `BOOK_MAX_AGE_MIN=5`, `TRADES_MAX_AGE_MIN=5`,
`FUNDING_OI_MAX_AGE_MIN=480` (`ml/train/config.py`). Reuse `features.build_feature_frame` rather
than reimplementing the joins; a side-table built with different alignment than training is not
evidence about training.

Write `book_era_<interval>.parquet` with `(pair, ts, <11 book features>, fwd_ret_{5,15,60,240},
has_book)`.

🔴 **Acceptance test, not optional:** for the rows where a baseline eval dump also has data, the
side-table's `fwd_ret_240` must match the dump's `fwd_ret` to floating-point tolerance on a join
over `(pair, ts)`. This is the same discipline that made `reaggregate_preds.py` credible. If it
does not match, nothing downstream is evidence.

**Bring back:** row counts per pair per interval, first/last book timestamp per pair, the fraction
of rows where each feature is non-stale, and the acceptance-test diff.

</details>

### B1 — the economic information check (replaces "re-run the audit")

✅ **RUN 2026-08-31.** Command: `./scripts/m3.sh -m m3 bookaudit` (code `ml/train/m3/bookaudit.py`,
log `logs/b1_bookaudit.log`, tables `ml/train/output/m3_4/b1_bps_table.csv` and
`b1_classification.csv`). All four §B1 fixes are implemented: chronological half-split with the
sign and the percentile map fitted on half 1, pairs pooled as a nuisance dimension via a
within-pair percentile map, everything in bps against the 5/14 bps cost lines, and the real
per-horizon sd.

**Verdict on §4.1: `NOT EVALUABLE` — and that is a distinct outcome from FAIL.** §4.1 requires
`n >= 2,000` in a top-5% slice, which needs **>= 40,000 usable half-2 rows**; the book era
supplies **39,740**. The gate is short by about 1% and *cannot be run as written*. Recording that
as a FAIL would close B3 on a sample-size technicality rather than on evidence — the exact move
`negative-results-need-the-same-scrutiny` forbids. Either wait for the window to grow past the
floor, or re-pre-register the floor **before** looking at the numbers again, never after.

**What the evidence looks like anyway** (best sign-agreeing slice, offered as texture, not as a
verdict): `trade_vol` at 60m, **+24.07 bps raw**, but the book era's own drift is **+11.60 bps**,
so the part attributable to the feature is **+12.47 bps** — and its **day-clustered 95% CI is
[−6.06, +30.99]**, on only **12 day-clusters**. Every feature's excess at 60m spans zero.

🔴 **The clustering is the whole point, and it is what the 2026-08-04 audit lacked.** A 60-minute
forward return sampled on a 5-minute grid overlaps its twelve neighbours, and the same market
move is counted once per pair across correlated perpetuals. The naive `sd/sqrt(n)` put
`trade_vol` at roughly six sigma. The clustered interval puts it at less than 1.4. **Nothing here
is distinguishable from zero.** ⚠️ Even that is generous: 12 clusters is far below the G >= 30-40
where a cluster-robust SE is itself reliable.

**Three results worth carrying forward:**

1. **At 5m, nothing clears even the maker line.** The best cell across all features and coverages
   is `trade_vol` at **+4.41 bps** (cov 1%), against a 5 bps maker round trip and 14 bps taker.
   §1.1's horizon curve is confirmed on the book era's own data rather than extrapolated.
2. **The real per-horizon sd, replacing §1.2's sqrt(t) estimates** — the measurement §B1 point 4
   asked for:

   | horizon | sd (bps) | mean abs (bps) | sqrt(t) estimate | ratio |
   |---:|---:|---:|---:|---:|
   | 1m *(derived from 1m closes)* | 12.71 | 6.35 | 11.53 | 1.10 |
   | 5m | 25.77 | 14.59 | 25.77 | 1.00 |
   | 15m | 43.95 | 25.25 | 44.64 | 0.98 |
   | 60m | 86.67 | 50.88 | 89.28 | 0.97 |
   | 240m | 167.90 | 103.38 | 178.56 | 0.94 |

   Real sd grows **slightly slower** than sqrt(t). §1.2's fee wall at short horizons is therefore
   marginally *harder* than it assumed, not easier.
3. **The DIRECTIONAL / VOL-PROXY split, which is what §0.4 depends on.** `spread_bps`
   (`vol_rho` **−0.28**), `trade_count` (+0.30), `trade_vol` (+0.27) and `funding_rate` (+0.26) are
   strong magnitude signals with directional rho an order of magnitude smaller — **VOL-PROXY, as
   §0.4 predicted.** Note the **sign**: `spread_bps` correlates *negatively* with move size here,
   so its volatile tail is the **low** one; B2 tests both tails because of this.

⚠️ **Two housekeeping facts.** `imbalance` and `bid_ask_vol_ratio` are monotone transforms of each
other ((b−a)/(b+a) versus b/a), so every rank-based number is identical for the two — there are
**eight** distinct features here, not nine. And the **240m negative control fired**: every feature
shows large positive raw bps there (up to +99), which is the period's own **+62 bps drift**, not
information. That is exactly why the harness now reports raw *and* excess-over-drift; without the
drift row the 240m table reads as a discovery.

<details><summary>The original B1 specification, kept for reference</summary>

Laptop, `pandas` only, on `book_era_5m.parquet` and `book_era_1m.parquet`. Three fixes to §1.4's
three defects, and one new measurement:

1. **Holdout.** Split the book era in half chronologically. Determine each feature's sign and its
   decile mapping on **half 1 only**. Score on **half 2 only**. Report only half-2 numbers.
2. **Pool across pairs, do not scan them.** One pooled test per (feature, horizon) with pairs as a
   nuisance dimension, instead of 8 separate per-pair tests. This removes most of the 264-test
   multiple-comparison inflation at its source. If per-pair numbers are printed at all, print them
   as diagnostics with an explicit "not a test" label.
3. **Report in bps.** For each (feature, horizon), sort half-2 bars by the feature and report
   **mean signed return in bps** for the top 1% / 2% / 5% / 10%, alongside `n`, the per-trade sd,
   and the naive SEM. Put the 14bps and 5bps cost lines in the table so the reader cannot avoid the
   comparison.
4. **Measure the real per-horizon sd** at 1/5/15/60/240m and rewrite §1.2's √t estimates with it.

Keep the existing audit's vol-control (`resid_rho`, `vol_corr`, `dir_buckets`) — the
DIRECTIONAL/VOL-PROXY split is the most useful thing it produces, and §0.4 depends on it.

Horizons to score: **5, 15, 60, 240m.** Include 240m specifically as a negative control — we already
know what the answer there should look like, so a book feature that appears to beat the model at
240m is a bug indicator, not a discovery.

The existing script is the right starting point and should be extended in place rather than
rewritten:

```sh
# the read-only audit as it stands today, on 38 days instead of 9 (its own VM,
# concurrent with anything else) — run this FIRST as a baseline for comparison:
./scripts/gcp_audit.sh --horizons 5,15,60,240 --min-rows 2000
./scripts/gcp_audit.sh --status
./scripts/gcp_audit.sh --fetch          # log + microstructure_audit.json
```

Then apply fixes 1–4 as a local harness over B0's parquet. **Do not put the fixed version on a VM** —
it is `pandas` over ~90k rows and belongs on the laptop, for the same reason M3 does (M3_PLAN §0.3).

**Bring back:** the bps table (feature × horizon × coverage, half-2 only), the sd-by-horizon table,
the DIRECTIONAL/VOL-PROXY classification, and a one-line verdict against §4.1.

</details>

### B2 — book features as M3 regime observables *(highest expected value)*

✅ **RUN 2026-08-31.** Command: `./scripts/m3.sh -m m3 bookregime` (code
`ml/train/m3/bookregime.py`, log `logs/b2_bookregime.log`).

**Verdict on §4.2: `NOT YET DECIDABLE`.** No candidate clears the +30 gross bps bar at cov 2%.
🔴 **This is not a negative result, and §4.2 says so in advance** — the gate is deliberately set
where 38 days can resolve, and a real +15 bps effect would fail it too.

🟢 **The internal control is what makes that reading certain rather than a excuse.** The
**incumbent** observable, `btc_absret_1d` — the one Q1 measured at 4x across three seeds — scores
a **+25.16 bps lift on n=33 trades, with its three seeds SPLIT in sign.** The observable we
already know works fails its own gate on this window. That is proof the *window* cannot resolve
the question, not that the candidates are bad.

**Cell sizes are 19-78 trades.** §1.6's ±36 bps CI half-width was, if anything, optimistic.

**Texture, explicitly not a finding** (n is far too small, and the tail orientation was chosen
from the data, which doubles the test count): the *conditional* column — the book gate applied
inside the bars where `btc_absret_1d` is **not** in its own top quintile — is positive for
`trade_count_mkt` (+15.54), `trade_vol_mkt` (+16.98) and the composite (+21.51) at cov 2%. If
anything survives here it is the *orthogonality* hypothesis of §B2 — a contemporaneous observable
firing on the days the trailing one sleeps through — and that is the thing to re-test when the
window is long enough. Do not build a policy term on it.

**What would make this decidable:** calendar. §4.4's ≥90-day trigger (≈2026-10-15) is the
condition, and it is unchanged by this run.

---

<details><summary>The original B2 specification, kept for reference</summary>

This is the step §0.4 argues is most likely to pay, and it is the one that shares the most with M3.

Join B0's side-table to the three eval dumps on `(pair, ts)`, restrict to the book era, and ask
whether a book-derived observable reproduces or improves Q1's regime effect:

- **Baseline to beat:** Q1's `btc_absret_1d > 4.31%` gate, which takes cov05 from +8.9 to +35.5
  gross bps/trade and cov02 from +22.0 to +54.9, replicated across three seeds.
- **Candidates:** `spread_bps` (the audit's strongest feature, and a vol proxy), `trade_count`,
  `trade_vol`, `oi_chg`, and a composite. All are **contemporaneous**, which is their whole appeal
  over a trailing 24h return.
- **The comparison that matters:** does the book observable add anything *conditional on*
  `btc_absret_1d`, or is it the same regime measured a second way? Report both the marginal and the
  conditional effect. A second measurement of the same regime is worth little; an orthogonal one is
  worth a lot.

🔴 **The power constraint from §1.6 binds hard here.** Restricted to the book era, cov02 is ~195
trades and the CI half-width is ±36bps — so this step can only detect an effect of Q1's size
(+33bps), not a subtle one. Pre-register that: a book regime observable is interesting only if it
moves the book-era cov02 slice by **more than +30 gross bps**, and even then it is a
hypothesis to re-test when the window is longer, not a finding to build a policy on. Say so in the
write-up; do not let an underpowered positive become a load-bearing assumption in M3.

**Depends on M3-0a** having landed (the harness with regime conditioning and the reproduce-§1.3
acceptance test). Do not build a second harness — extend M3's.

**Bring back:** the regime table (observable × coverage × {marginal, conditional-on-btc_absret_1d}),
per-seed as well as pooled, with `n_trades` on every row.

</details>

### B3 — one book-era model, gated on B1

🔴 **BLOCKED 2026-08-31: B1 returned `NOT EVALUABLE`, so §4.1 has neither authorised nor refused
B3.** B3 does not happen on an ungated basis. See the B1 section for the two ways forward (wait
for the window, or re-pre-register the floor first). Recorded in
[NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) §2, since B3 is the wave's only training run.

**Only if B1 clears §4.1.** If it does not, this step does not happen and the wave closes at B2.

**Architecture: LightGBM, not an LSTM, and this is not negotiable at this sample size.** Reasons,
in order:

- 90k samples at 5m is 3% of the baseline's 2.90M. R3a already demonstrated that this problem's
  model family memorizes the moment it is given capacity — `loss_tr` 1.72 → 0.888 with `loss_va`
  never once reaching baseline — on **thirty times more data**. An LSTM here will fit the 38 days
  and tell us nothing.
- E4-GBT already showed a GBT **ties** the LSTM at 30m, so we are not giving up known performance.
- `ml/train/gbt_baseline.py` and `scripts/gcp_gbt.sh` already exist, take `--tail-days`, run on
  **their own throwaway VM** explicitly designed to be concurrent with other work, and need no GPU.
  This is why B3 does not compete with M3 for anything.

```sh
# book era only, 5m primary, 8 main pairs. --tail-days bounds the window without
# needing --require-book; verify from the log that the loaded window matches §1.5.
GBT_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
GBT_HORIZONS=5,15,60 GBT_PRIMARY=5 CANDLE_INTERVAL=5m \
  ./scripts/gcp_gbt.sh --tail-days 38 --num-leaves 15 --n-estimators 200 --learning-rate 0.03

./scripts/gcp_gbt.sh --status
./scripts/gcp_gbt.sh --fetch     # summary + JSON
./scripts/gcp_gbt.sh --log       # full console log
```

Note the deliberately small `--num-leaves 15` and `--n-estimators 200` against the defaults of
63/400 — at 3% of the data the default is a memorization setting.

🔴 **One run. No sweep.** Not `--num-leaves` and not learning rate. §1.6 says the 5m setting resolves
to about ±8.6bps; a hyperparameter ladder inside that band measures seed noise, which is exactly the
mistake NEXT_TRAINING_PLAN §0.3 was written to prevent. If B3 lands near its gate rather than
clearly over or under, the answer is "wait for more calendar", not "try a third setting".

**Bring back:** the fixed-coverage P&L table at every horizon, `dir_acc`/Wilson-LB with `n_dir`, the
calibration bin table, the loaded sample count and date window, and LightGBM's feature importances —
the last is O5's within-model attribution, finally obtained, and is arguably the most durable output
of the whole wave regardless of whether the P&L clears.

### B4 — collection fixes ✅ implemented 2026-08-24, ✅ deployed and verified 2026-08-28

On the audit's unrecoverable list, none of it on the critical path for B0–B3. It matters because if
this wave says "wait for the calendar", we want the calendar to be accumulating *better* data, not
more of the same.

**Deployed to `fluxtrader-1` on 2026-08-28; all three acceptance checks pass.** The numbers are
recorded under "Acceptance, as measured" below. Nothing remains in B4.

1. ✅ **Exchange event timestamps.** `orderbook_snapshots` now stores `event_time` (`E`),
   `transaction_time` (`T`) and `last_update_id`; `funding_rates` and `open_interest` store
   `event_time` (migration `20260824000001`). `ts` deliberately keeps its old meaning — local
   receipt time, the key every as-of join and the 1:1 `orderbook_levels` join already use — so this
   is purely additive and nothing downstream changes. Pre-migration rows stay NULL, which is honest:
   their exchange time is genuinely unknown. The skew is now *measurable* rather than assumed;
   `gcp_data_collection_stats.sh` §2b prints p50/p95 of `ts - event_time` per symbol.

2. ✅ **Long/short & taker ratios.** New `long_short_ratios` table (migration `20260824000002`), one
   row per `(symbol, exchange 5m bucket, period)` fed by `topLongShortAccountRatio`,
   `globalLongShortAccountRatio` and `takerlongshortRatio` at 60s. Each endpoint upserts only its
   own column group, so the taker series routinely running a bucket behind the other two is the
   normal case rather than a data loss. Added to `DUMP_TABLES`.

   On first sight of a pair the collector also grabs the ~30 days the exchange still holds, in a
   supervised task (serial, 200ms between pages, cannot crowd out the 5s polls). 🔴 It pages
   **backward** via `endTime` — verified live 2026-08-24, the endpoint answers
   `startTime=30d ago, limit=500` with the newest ~42h, *not* the oldest 500. Forward paging would
   have silently captured 42h of a 30-day window we get one shot at.

3. ✅ **Is `@depth` egress-blocked? — NO. Verdict `DEPTH_OK`, measured 2026-08-28.**
   `scripts/gcp_depth_ws_test.sh --seconds 60`, run from the always-on VM because that host's
   egress is the thing being measured. The connection upgraded, stayed open for the full window,
   the SUBSCRIBE was ACKed, and **586 `depthUpdate` frames arrived, first at 748ms**.

   🟢 **This is the good branch, and it changes what is possible.** The plan was written against
   the risk that `@depth` sat on the same side of the line as `!forceOrder@arr` (upgrade + ACK,
   then silence — which is why `liquidations` has 0 rows). It does not. **The 5s REST cadence is
   not a hard fidelity ceiling**, so §1.2's fee-wall arithmetic is *not* the only lever left at
   short horizons, and a WS depth consumer is worth building when something needs it.

   ⚠️ One oddity, recorded rather than chased: the `@aggTrade` control stream reported **0 frames**
   in the same window, on a pair that trades continuously. That does not affect the verdict —
   depth frames demonstrably arrive, which is the question B4.3 asked — but it means the control
   did not do its job, and anyone building the WS consumer should re-check `@aggTrade` naming
   before assuming the trade stream is reachable too.

### Acceptance, as measured on 2026-08-28

| check | expected | measured |
|---|---|---|
| §2 `with_event_time` on new rows | climbing from 0 | **165,686 / 165,686 = 100%** over the last 2 days of `orderbook_snapshots` |
| §9 `long_short_ratios` exists and backfilled | ~30d within minutes of boot, then growing | **116,073 rows, 12 symbols, 2026-07-26 → 2026-08-28** (≈33d — the backward paging worked) |
| §9 missing columns small | small | `missing_top` 12, `missing_global` 12, **`missing_taker` 216** of 116,073 (0.19%) — the taker series running a bucket behind, exactly as predicted |
| B4.3 verdict | any verdict is an answer | **`DEPTH_OK`** — 586 depth frames / 60s |

**Bring back:** the §2b skew table (this is new information about our own data, not just a health
check), the §9 row counts and date span, and B4.3's verdict line. Record the verdict here — if it is
`WS_BLOCKED` or `DEPTH_BLOCKED`, the 5s REST cadence is the permanent fidelity ceiling for this
project and §1.2's fee-wall arithmetic is the only lever left at short horizons.

## §3 — WHAT TO BRING BACK (for a fresh session)

Results are analyzed in a fresh session for token hygiene, so each step's output must stand alone.

- **B0:** row counts per pair/interval, first/last book ts per pair, non-stale fraction per feature,
  the `fwd_ret_240` acceptance-test diff against a baseline dump.
- **B1:** the bps table (feature × horizon × coverage, **half-2 only**), sd by horizon, the
  DIRECTIONAL/VOL-PROXY split, the verdict against §4.1. Also `logs/audit_38d.log` from the
  unmodified re-run, for comparison against 2026-08-04's ESCALATE.
- **B2:** regime table (observable × coverage × marginal/conditional), per-seed and pooled,
  `n_trades` on every row, verdict against §4.2.
- **B3:** fixed-coverage P&L at every horizon, `dir_acc`/LB/`n_dir`, calibration bins, loaded sample
  count and window, feature importances, verdict against §4.3.
- **B4:** `gcp_data_collection_stats.sh` §2b (the p50/p95 `ts - event_time` skew — genuinely new
  information about our own data) and §9 (`long_short_ratios` span and row counts), plus
  `gcp_depth_ws_test.sh`'s verdict line. B4 has no gate: it is collection, not evidence.

Fetch training-style logs the usual way — `./scripts/gcp_logs.sh > logs/<name>.log`, never `--save`.
`gcp_audit.sh` and `gcp_gbt.sh` have their own `--fetch` / `--log` modes (§2).

---

## §4 — PRE-REGISTERED GATES

Written before any of it runs, which is the only time pre-registration means anything.

### 4.1 B1 → B3

**B3 happens if and only if** at least one book feature, on the **held-out second half**, at a
horizon **≤ 60m**, delivers a top-5% mean signed return above **+5 bps** (the maker cost line) with
`n ≥ 2,000`, **and** the same feature's sign agrees between half 1 and half 2.

If the best out-of-sample slice is under +5bps, no architecture recovers it — the information is not
there at the fidelity we collect it — and the wave closes at B2 with "re-check when the window is
months long". Do not negotiate this number downward after seeing the result.

### 4.2 B2

A book-derived regime observable is **worth carrying into M3** if it moves the book-era cov02 slice
by **more than +30 gross bps/trade**, per §1.6's ±36bps CI, **and** the effect survives conditioning
on `btc_absret_1d` (i.e. it is not the same regime measured twice), **and** the sign agrees across
all three seeds.

Anything smaller is not measurable on 38 days and must be recorded as "not yet decidable", never as
a negative result — the distinction matters, because a real +15bps effect would fail this gate.

### 4.3 B3

The book-era GBT is **worth pursuing further** if its 5m or 15m fixed-coverage P&L clears **+5 bps
net at maker** at cov ≤ 0.05, with `n_dir` above the project's usual 500-trade reliability floor.

It is **promoted to nothing** on this evidence regardless — a 7-day validation window in a single
market regime is not grounds to serve a model, and §1.6(b) is not repaired by a good result. A pass
here means "run it again when the window is 90 days", not "ship it".

### 4.4 The wave's exit condition

If B1 fails §4.1 **and** B2 fails §4.2, the book question is closed until **≥90 days of continuous
book history on the 8 main pairs** (≈2026-10-15), and this document is archived with that trigger
recorded. Do not open a B5.

---

## §5 — OUT OF SCOPE (do not re-propose inside this wave)

| thing | why not |
|---|---|
| **`gcp_walkforward.sh` book ON/OFF** | Retired as a design (§1.3). Three attempts, zero decidable verdicts, and the failure mode is structural: the book-OFF arm collapses to all-flat exactly when the book helps most. The 30-day trigger recorded in the archive does not repair it. |
| **Architecture search on book data** | §1.6 resolves to ~±8.6bps at 5m; a sweep inside that band measures initialization noise. R3a already showed this family memorizes when given capacity on 30× more data. One well-regularized GBT, one run. |
| **An LSTM on the book era** | 90k samples. See B3. |
| **Adding book features to the main M2 model** | Unchanged from NEXT_TRAINING_PLAN §5: they are constant across 99% of the train window and get zeroed. That is a calendar problem **for a model that keeps the full-history train window** — see the clarification below, because "calendar problem" has been read too broadly. |
| **Serving anything from B3** | §4.3. A 7-day val window in one regime is not a promotion case at any P&L. |
| **`orderbook_levels` (raw L2) features** | ~19 days, and nothing on the Python side reads it. This is O5's real home and it is a 2027 item. The scalars are the right target now. |
| **`liquidations`** | 0 rows, egress-blocked. Not in any plan. |

### Clarification, 2026-09-01 — what "a calendar problem" does and does not mean

Asked directly, and worth writing down because the short phrase above is misleading on its own:
*if the book era is too recent to sit in the train window, why not just train on a short recent
window instead of all history?*

**That is right, and it is not blocked by the calendar. It is B3.** The reasoning, in order:

1. **More history makes it worse, not better.** The split is a fraction of time-ordered samples
   (`VAL_FRACTION` 0.2, `--val-frac`). Train opens 2022-08 and val runs 2025-12 → 2026-08, so the
   boundary sits at start + 0.8·span. Adding *older* data moves that boundary **earlier** and makes
   the val window **longer** — back-filling ten years would put the boundary near 2024-08 and leave
   the book era even more solidly inside val. So downloading more history is the one move that is
   strictly counter-productive here.
2. **Training on a short recent window puts book data inside train, and that is exactly B3** —
   `./scripts/gcp_gbt.sh --tail-days 38`, which bounds the window without needing `--require-book`.
   The idea is already the plan's; what gates it is B1, not the calendar.
3. 🔴 **But not with the LSTM, and not at 1m/5m because the sample count allows it.** Two separate
   limits bite before data volume does:
   * **Architecture.** ~90k samples at 5m is 3% of the baseline's 2.90M. R3a showed this family
     memorizes when given capacity on **30× more data**. That is why B3 is LightGBM and why §5
     lists an LSTM on the book era as out of scope. E4-GBT showed a GBT *ties* the LSTM at 30m, so
     nothing known is given up.
   * **The fee wall, which no amount of data moves.** B1 measured the book era directly: **at 5m
     nothing clears even the 5 bps maker line.** A short horizon has more samples *and* smaller
     moves, and the moves have to clear the cost of trading them. This is why B3's gate (§4.3) is
     stated in **net bps at maker**, not in accuracy.
4. **The real scarcity is held-out rows and regimes, not training rows.** §4.1's floor is on the
   **held-out second half**, and §4.3 says a pass is *promoted to nothing* regardless, because a
   7-day val window in a single market regime is not grounds to serve a model.

⚠️ **The cautionary note that makes this concrete:** the M3 policy's current problem is precisely
that a model trained on one set of regimes went quiet when a new one arrived (see BACKLOG.md, "The
arrival-rate finding"). A model trained *and* validated inside a single calm two-month window is
more exposed to that failure, not less. Short-window training is the right way to get book features
into a model; it is not a way to get a **servable** model, and those are different goals.

---

---

## §6 — HOW THIS RUNS ALONGSIDE M3

- **M3 is a laptop project** (M3_PLAN §0.3) and needs no VM. So does B0–B2. They compete for
  *attention*, not compute.
- `gcp_audit.sh` (B1) and `gcp_gbt.sh` (B3) each run on **their own throwaway VM**, separate from
  the training VM, with separate status markers — both scripts' headers say explicitly that they can
  be in flight simultaneously with a training run.
- ⚠️ **`gcp_train.sh` runs remain strictly serial** — only one at a time, as always. Nothing in this
  document launches one, which is the main reason the two wavefronts do not collide.
- **B0 is shared work**: build it as M3-0b's side-table with book columns added, and both plans are
  served by one export. If M3 gets there first, B0 is a column addition rather than a new step.
- Sequencing recommendation: **B4 is written — deploy it** (unrecoverable data; it collects nothing
  until it is on the VM), do **B0** whenever M3-0b comes up, then **B1**, then **B2** once M3-0a's
  harness exists. B3 only on B1's gate.
