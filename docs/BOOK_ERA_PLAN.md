# Book-era plan — the B-wave

**Status (2026-09-10):** ✅ B4 · ✅ B0, ✅ B1, ✅ B2 **re-run on the full era with repaired
candles** (§R) · 🟢 **B3 AUTHORISED — §4.1 passed as written; launch pending (needs a commit +
push, see §B3)**. Both gates passed by the letter of their pre-registration and **neither
result is distinguishable from zero at the window's own day-clustered resolution** — read §R's
results block before quoting either. The 2026-08-31 readings (`NOT EVALUABLE` / `NOT YET
DECIDABLE`) are superseded, and not only by more days: they were measured on the collector's
partial-bar candles (`CANDLE_POLL_DEFECT.md`), so their forward returns were not the market's.
They are archived in `archive/TRAINING_HISTORY.md`. Runs **in parallel with M3**, blocks
nothing, and is blocked by nothing. Indexed in [BACKLOG.md](./BACKLOG.md).

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

## §R — THE 2026-09-10 RE-RUN, REGISTERED BEFORE ANY NUMBER WAS READ

*Written 2026-09-10, before the export finished. BACKLOG's 2026-09-01 note said B1's n floor
was short by hours of collection, not weeks, because the export it ran on (2026-08-05..27,
23 days) was narrower than the data the VM already held. This section fixes the window and
says exactly what will and will not change, so that the re-run is a re-run and not a re-pick.*

**What changes — the inputs only:**

1. **The window.** Export from **2026-07-17** (the first `orderbook_snapshots` row on
   BTC/ETH/SOL) to **2026-09-10** exclusive, all twelve collected pairs. The four August pairs
   (ADA/AVAX/LINK/XRP) start 2026-08-14 and are masked before that by `has_book`, exactly as
   in the first run. Into a **separate directory** (`ml/train/output/book_era/`) so that
   `m3_4/` stays byte-identical for M3-4's reproduction. No ladder: the scalars come from
   `orderbook_snapshots`, which is why the era can open on 07-17 and not 08-05.
2. **The eleventh and tenth scalars.** The export gains the parked `open_interest` slice, so
   B0 builds `oi` and `oi_chg` with training's derivation and 8h cap. B1 scores all eleven
   (the list §B0 registered on 2026-08-24). B2's candidate list becomes the one §B2
   registered — `spread_bps`, `trade_count`, `trade_vol`, **`oi_chg`**, and the composite —
   rather than a fifth candidate added after seeing results; the composite is the mean of the
   candidates' market-wide percentiles, so it now averages four.
3. **B2's dumps.** The 2026-08-31 run joined the book era to the *pre-repair* dumps, whose
   validation window ends 2026-08-17, so B2 saw **12 days** of book era and its cells were
   19–78 trades. This run uses the **repaired** era (`M3_ERA=repaired`) — the same three
   banked checkpoints, re-scored, validation to 2026-09-03 — so B2 sees the era to 09-03.
   Declared here as the primary, before running. B0's acceptance test runs against the
   same dumps plus O8.

**What does not change — the criteria:**

* §4.1 exactly as written: top-**5%**, horizon **≤ 60m**, **> +5 bps**, **n ≥ 2,000**, sign
  agreeing across the halves. The half split stays the median timestamp.
* §4.2 exactly as written: marginal lift **> +30 gross bps** at cov 2%, a positive
  conditional lift, three seeds agreeing in sign. The day-clustered CI the harness now prints
  is a diagnostic so the reader can see what the window resolves; it is not a gate term.
* No coverage widening, no new horizon, no second B3 setting. If §4.1 passes, B3 runs once as
  §B3 specifies with `--tail-days` covering the era on the 8 main pairs; if it fails, B3 is
  refused on evidence and the wave closes at B2 per §4.4.

**What this can and cannot conclude:** a longer window makes §4.1 *evaluable*; it does not
make it pass. B2's cells grow roughly fourfold, so its resolution improves but a +15 bps
effect may still not clear +30 — record that as "not yet decidable" as §4.2 says.

**Commands, in order:**

```sh
OUT=ml/train/output/book_era FROM=2026-07-17 TO=2026-09-10 \
  ONLY=snapshots,trades,candles_5m,candles_1m,funding,oi ./scripts/gcp_m3_export.sh
export M3_EXPORT_DIR=/workspace/train/output/book_era M3_ERA=repaired
./scripts/m3.sh -m m3 bookera     > logs/b0_bookera_20260910.log
./scripts/m3.sh -m m3 bookaudit   > logs/b1_bookaudit_20260910.log
./scripts/m3.sh -m m3 bookregime  > logs/b2_bookregime_20260910.log
```

### §R.1 — Results, read after the registration above was written

*Logs: `logs/b0_export_20260910.log`, `logs/b0_bookera_20260910.log`,
`logs/b1_bookaudit_20260910.log`, `logs/b2_bookregime_20260910.log`. Tables:
`ml/train/output/book_era/b1_bps_table.csv`, `b1_classification.csv` (gitignored).*

**In plain language.** The book era is now 54 days long instead of 23, on correct candles, and
both measurement gates could finally be evaluated. Both passed by the exact rule written down in
August. But the amounts involved are small relative to how noisy 54 days are: the best single
book feature earns about **+10 bps per trade** at a 1-hour horizon before costs, of which about
**+5.6** is simply the market drifting up over those weeks, and the remaining **+4.75** has a
95% confidence interval of roughly **−2.5 to +12**. That is "cannot rule out zero", not "an edge".
So what the passes *license* is exactly what the plan said a pass licenses: one CPU training
run (B3) to see whether a model combining all eleven features does better than any one of them,
and a hypothesis (B2's) to re-test later. **Nothing here is tradeable and nothing gets wired
into the live policy.** At the 5-minute horizon, where book data is supposed to shine, no
feature clears even the 5 bps maker cost line — the fee wall §1.2 predicted is measured, twice.

**B0.** 190,080 5m rows and 950,400 1m rows, 12 pairs, 2026-07-17..09-09, all eleven scalars.
Acceptance against the repaired dumps: **111,208 / 111,112 / 111,328 exact, no exceptions.**
O8 (dumped 2026-08-22, pre-repair candles) matches on only 42,859 of 121,188 — the mismatches
begin on 2026-07-17 and are the defect's signature, not an alignment fault; the harness now
labels pre-repair dumps as a control rather than a gate.

**B1 — §4.1 `PASS`.** Half split at 2026-08-13 11:57 UTC; n at cov 5% = **3,158** (floor 2,000,
so the gate could run). Best eligible slice: **`imbalance` @ 60m, +10.37 bps raw** on n=3,158,
sign agreeing across halves. Drift over all half-2 bars at 60m is **+5.62**, so the excess is
**+4.75, day-clustered 95% CI [−2.45, +11.94]** on 28 clusters. Three things to hold next to it:

* the rank correlations behind it are **0.005–0.015** — an order of magnitude below the
  magnitude correlations of the VOL-PROXY features (0.19–0.29);
* §4.1 takes the best of 30 distinct (feature, horizon ≤ 60m) cells, as registered; the reader
  should know the max was taken;
* at **5m nothing clears the maker line** (best raw +3.43, `oi_chg` at cov 1%), and at 15m the
  best excess is +1.5. §4.3's gate for B3 is stated at 5m/15m **net at maker**, so B3's likeliest
  verdict is a fail on the fee wall — its durable output is the feature importances (O5).

`oi_chg` @ 60m looks larger (+13.75 raw, +8.15 excess, CI [−2.41, +18.71]) but its sign
**flips** between halves (ρ −0.024 → +0.001), so it is ineligible by the registered rule.
The per-horizon sd on true candles: 1m 10.5 · 5m 22.4 · 15m 38.4 · 60m 75.4 · 240m 146.6 bps,
ratio to √t 0.94–1.05 — still slightly *slower* than √t at the long end. The 240m negative
control did not fire: every feature's excess there spans zero on ±30–50 bps CIs. VOL-PROXY
confirmed for `spread_bps` (vol_ρ **−0.19**), `trade_count` (+0.29), `trade_vol` (+0.26),
`funding_rate` (+0.20); `oi_chg` is a weak one (+0.01–0.02).

**B2 — §4.2 `PASS`, on `spread_bps_mkt_lo`.** 115,365 bars × 8 pairs, 07-17..09-09, repaired
dumps. The **low** tail of market-wide spread — the volatile tail, per B1's negative vol_ρ —
scores **+35.43 gross bps on n=153** at cov 2% against a no-gate baseline of **−7.85 (n=311)**:
lift **+43.29**, conditional lift inside calm-BTC bars **+27.89**, all three seeds agreeing;
at cov 5% the same cell reads +14.35, lift +31.96, conditional +21.87, seeds agreeing. Read the
resolution first: the gated arm's own day-clustered half-width is **±68.8 bps** (baseline
±67.0 on 41 clusters), so the lift is inside one half-width of zero. The orientation (`_lo`)
was chosen from B1's sign, which doubles the primary test count to ten. §4.2 said in advance
that a pass is **a hypothesis to re-test when the window is longer, not a policy term**, and
that is the only thing it is. Every other candidate, including the composite and `oi_chg`,
fails: lifts of −23 to +15.

🔴 **The side-finding that matters more than the pass.** The **incumbent** observable,
`btc_absret_1d`, is **negative** on this era: marginal −20.23 (n=162, lift −12.38, seeds split)
at cov 2% and **−38.85 (n=330, lift −21.24, seeds agreeing)** at cov 5%, while the *calm*-BTC
subset earns +21.71 / +10.74. Q1's 4× effect is not merely absent on Jul–Sep 2026, it points
the other way — and the live policy's size ladder is keyed on that observable. On 54 days with
±67–115 bps CIs this is an observation for the forward test to check, not a finding; but it is
the strongest argument in this wave for a *contemporaneous* regime observable, and it is filed
in BACKLOG under the live policy, not here.

**What happens next, and only this:** B3 once, as §B3 specifies (the command there is updated
for the 55-day era and needs the `--tail-days` fix pushed to `main` first). No coverage change,
no second setting, no policy edit.

---

## §0 — READ THIS FIRST (plain language, no statistics required)

### 0.1 The question this wave exists to answer

We have been collecting order-book data since 2026-07-17. It is now ~55 days deep on the majors.
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

### 1.5 The data inventory, as measured on the VM 2026-09-10

| source | coverage |
|---|---|
| `orderbook_snapshots` (11 scalars, what training reads) | BTC/ETH/SOL **55d** (from 2026-07-17) · DOGE/HYPE/WLD 51d (07-21) · ZEC 47d (07-25) · 1000PEPE 45d (07-27) · ADA/AVAX/LINK/XRP 27d (08-14) |
| `orderbook_levels` (raw L2, 100+100) | 8 pairs from 2026-08-05. **Nothing on the Python side reads this yet.** |
| `market_trades`, `open_interest` | mirror the snapshots exactly (same first day per pair). `open_interest` is in the export since 2026-09-10 |
| 5m candles | 🔴 partial bars from 2026-07-18 to 09-03, **repaired 2026-09-04** (`CANDLE_POLL_DEFECT.md`). Any book-era number measured before the repair used the wrong forward returns |
| `funding_rates` | 2y9mo–3y11mo — real history, and already a live feature |
| `long_short_ratios` (B4.2) | **starts 2026-08-24**, plus the ~30d the exchange still held. Not in any model yet; collector-only from here. |
| `liquidations` | 0 rows, WS egress blocked from datacenters. Not in any plan. |

`./scripts/gcp_data_collection_stats.sh` is the slow full report; the fast version is the ad-hoc
query pattern in NEXT_TRAINING_PLAN §0.1.

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
| **B0** | Book-era side-table → parquet | ~1h laptop + one VM dump | no | ✅ **re-built 2026-09-10** on the full era, all eleven scalars |
| **B1** | Economic information check (the fixed audit) | ~1 afternoon laptop | no | ✅ **2026-09-10 — §4.1 PASS** (see §R.1 for what that does and does not mean) |
| **B2** | Book features as **M3 regime observables** | ~1 afternoon laptop | no | ✅ **2026-09-10 — §4.2 PASS on `spread_bps_mkt_lo`**, a hypothesis only |
| **B3** | One book-era GBT, pre-registered | ~1h on its own CPU VM | no | 🟢 **AUTHORISED** by B1; launch needs a push (§B3) |
| **B4** | Collection fixes (unrecoverable if deferred) | small Elixir change | no | ✅ **DONE — deployed and verified 2026-08-28** |

**B4 was independent of the rest and is complete** (see below): deployed, all three acceptance
checks passed, and B4.3 returned `DEPTH_OK`. Everything else can queue behind M3's attention.

### B0 — ✅ DONE, re-built 2026-09-10 on the full era

Code `ml/train/m3/sidetable.py`, command `./scripts/m3.sh -m m3 bookera` with
`M3_EXPORT_DIR=/workspace/train/output/book_era M3_ERA=repaired`. Export by
`scripts/gcp_m3_export.sh` (no ladder, `ONLY=snapshots,trades,candles_5m,candles_1m,funding,oi`,
~25 min) into its **own directory** so `m3_4/` stays byte-identical for M3-4.

* `book_era_5m.parquet` — 190,080 rows × 12 pairs, 2026-07-17..09-09
* `book_era_1m.parquet` — 950,400 rows × 12 pairs
* **All eleven scalars.** `oi`/`oi_chg` come from the new `oi` export slice with training's
  derivation (`log1p` of the as-of level; change of the *aligned* level) and 8h cap.
* Freshness at 5m: BTC/ETH/SOL 0.953, DOGE/HYPE/WLD 0.923, ZEC 0.849, 1000PEPE 0.813, the four
  August pairs 0.487 — each exactly the fraction of the window the pair has been collected.

🔴 **Acceptance passed against the three repaired dumps: 111,208 / 111,112 / 111,328 exact.**
O8, dumped before the candle repair, matches 42,859 of 121,188 with the mismatches starting
2026-07-17 — the partial-bar defect's signature. The harness labels pre-repair dumps as a
control on a post-repair export rather than failing on them.

⚠️ **Operational, found on the way:** the VM's `/tmp` is a 980 MB tmpfs and a stale 821 MB
`/tmp/app.log` (dated 2026-09-05) filled it, so the first export died at the copy-out step.
The script now stages under the home directory on disk. The stale log is still there, holding
~800 MB of a 2 GB collector's RAM-backed tmpfs — worth deleting, not done here.

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

✅ **RUN 2026-09-10 on the full era, repaired candles.** Command
`./scripts/m3.sh -m m3 bookaudit` (same env as B0), log `logs/b1_bookaudit_20260910.log`.
Design unchanged from the registration: chronological half-split, sign and percentile map on
half 1, pairs pooled, everything in bps against the 5/14 bps lines, day-clustered CIs.

**Verdict on §4.1: `PASS` — B3 is authorised.** The full reading, including why the pass is
not an edge, is in **§R.1** above; do not quote the +10.37 without the +5.62 drift and the
[−2.45, +11.94] interval next to it.

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

✅ **RUN 2026-09-10 on the full era, repaired dumps (`M3_ERA=repaired`).** Command
`./scripts/m3.sh -m m3 bookregime`, log `logs/b2_bookregime_20260910.log`. Candidates are the
five registered on 2026-08-24, `oi_chg` now included; the harness prints each arm's
day-clustered half-width.

**Verdict on §4.2: `PASS` on `spread_bps_mkt_lo`** — the narrow-spread (volatile) tail of the
market-wide spread percentile: lift +43.29 at cov 2%, conditional +27.89, seeds agreeing, on
an arm whose own 95% half-width is ±68.8 bps. Per §4.2 this is **a hypothesis to re-test when
the window is longer**, never a policy term. Full reading in **§R.1**, including the
side-finding that the incumbent `btc_absret_1d` gate is *negative* on this era.

**What would make it a finding:** the same cell, same orientation, on a window long enough
that ±69 becomes ±30 or better — roughly four times the days, ≈ 2027-01 — **or** the forward
paper test's own ledger showing the same split. Re-run with the command above; change nothing.

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

🟢 **AUTHORISED 2026-09-10: B1 passed §4.1 as written.** One run, as specified below, with two
mechanical updates: `--tail-days 55` covers the era from 2026-07-17, and `gbt_baseline.py`'s
tail arithmetic was fixed the same day (it multiplied days by 1440 bars regardless of interval,
so `--tail-days 55` at 5m would have loaded 275 days). 🔴 `gcp_gbt.sh` clones `main` from
GitHub, so **that fix must be committed and pushed before launching** — otherwise the VM runs
the old code and the window is wrong. Recorded in [NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md)
§2, since B3 is the wave's only training run.

Expectation, written before the run: B1 measured no feature clearing even the maker line at 5m,
so §4.3 (net at maker at 5m/15m) is more likely to fail than pass; the run's most durable
output is the feature-importance table (O5's within-model attribution).

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
# needing --require-book; verify from the log that "Tail window" says ~15,840 5m
# candles/pair and the val window opens ~2026-08-29 (the last 20% of 55 days).
GBT_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
GBT_HORIZONS=5,15,60 GBT_PRIMARY=5 CANDLE_INTERVAL=5m \
  ./scripts/gcp_gbt.sh --tail-days 55 --num-leaves 15 --n-estimators 200 --learning-rate 0.03

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
