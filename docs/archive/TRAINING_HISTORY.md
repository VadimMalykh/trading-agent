# Training history archive (2026-07-23 → 2026-08-19)

**This file is HISTORY. Do not act on anything in it.** It is the verbatim
session-by-session narrative that used to live at the top of
`docs/NEXT_TRAINING_PLAN.md`, moved here on 2026-08-18 so the live plan contains only
what is currently true and actionable.

Read it only when you need to answer "why was X decided / why was Y rejected" — the
live plan carries the conclusions, this file carries the reasoning and the raw numbers.

⚠️ **Two things invalidate large parts of this archive; check both before quoting any
number from it:**

1. **The normalization bug (found 2026-08-17).** Every global-time-split run before
   commit `2e7b272` divided 12–13 of 19 features by `std=1e-6`, so any metric measured
   on a val window that crosses 2026-07-17 (the book era) is an artifact. Runs affected:
   every `R*`, `E1*`, `E2*`, `E3*` and the `eval_m2_E2b*` gate sweeps. NOT affected:
   `gcp_ablate.sh` / `gcp_walkforward.sh` results (they use `--require-book`, which puts
   the book features inside the train window) and `E4-GBT` (LightGBM is scale-invariant).
2. **The eval gate sweep's bottom rows are dead (found 2026-08-18).** `conf =
   max(p_down, p_up) ≥ 0.5` by construction, so every `GATE_THRESHOLD` at or below 0.50
   trades every bar. Four of the six swept rows are therefore the same row, and every
   "P&L at the serve gate" line in this archive is printed at 0.40 — a gate that cannot
   fire, and not the 0.58 that `docker-compose.yml` actually serves. The conclusion
   "gates 0.35–0.50 are identical, therefore the head has no confidence spread" is an
   artifact of this plus the norm bug. Production serving was never affected.

Sections below are in reverse-chronological order, newest first, exactly as written at
the time.

---

## 2026-08-19 — the O-wave, and what it retired from the N-wave

Runs: **O0** (eval-only re-score of F4, `logs/O0-f4-rescore.log`), **O2** (5m bars,
seq 384, `logs/O2.log`, run `20260818T185438Z`), **O3** (15m bars, seq 256,
`logs/O3.log`, run `20260819T021020Z`). All three passed the §0.4 validity checks.

### What the O-wave overturned

**1. "The edge is regime-locked and three models agree on where" (old §1.2) is now a
four-model disagreement.** F4, N3 and N2 all put window 2 highest and window 1/3 low.
O2 does not:

| window | F4 (15m LSTM) | N3 (15m LSTM) | N2 (GBT) | **O2 (5m LSTM)** |
|---|---:|---:|---:|---:|
| 1 | 0.486 | 0.499 | 0.492 | **0.573** |
| 2 | 0.617 | 0.621 | 0.574 | 0.535 |
| 3 | 0.457 | 0.419 | 0.415 | 0.500 |
| 4 | 0.584 | 0.613 | 0.397 | 0.596 |

Only two facts survive all four models: **window 3 is the worst window, and window 4 is
a good one**. Windows 1 and 2 are model-dependent, and the three-model agreement that
looked so convincing was agreement among three models that shared the same 15m bar grid
and the same 771k training samples — i.e. it was partly a shared-blind-spot artifact, not
purely a property of the market. O2's window spread is 0.096 against F4's 0.160, so the
finer-resolution model is *less* regime-locked, not differently regime-locked.

The regime-analysis item (old O1) is not cancelled by this — but its framing changes from
"find the observable that flags the good regime" to "find out how much of the window
structure is model capacity rather than market state", and it must now be run on O2's
prediction dump rather than F4's.

**2. "N2 reopens architecture" (old §1.4) is retired.** N2's pre-registered reading was
that a GBT losing at 4h meant the LSTM's temporal modelling was contributing, and that the
cheap test was more context (O3). O3 ran it: seq 128 → 256 at 15m, one variable, and the
result is **worse** — mean-of-epochs LB 0.4925 ± 0.0227 (n=24) against F4's 0.5058 ±
0.0162 (n=18), with the per-epoch series drifting monotonically down (0.52 early → 0.47
late) rather than plateauing. The pre-registered verdict fires the other way: the LSTM
already has all the context it can use at 15m, N2's gap is about the GBT's 114-column
static summary rather than about recurrence, and architecture goes back in the closed pile.

O3 also degraded in ways worth recording because they are the signature of a model that
is being given more window than it can use: the confidence distribution collapsed
(coverage at the served 0.58 gate fell from F4's 4.9% to 0.8%), the side split went
lopsided (6,266 down-gated vs 3,379 up-gated at cov 0.05, with the up side at 0.499 —
coin flip), and the selected epoch was 4 of 24.

**3. "The model is not data-starved; flat `loss_tr` proves the bottleneck is features."**
This diagnostic is falsified and should not be used again. O2's `loss_tr` was just as flat
as F4's for its first 22 epochs (1.7284 → 1.7184) and only descended once memorization
started at epoch 23, with `loss_va` diverging in lockstep (1.0404 → 1.3031 by epoch 34).
By that indicator O2 looked exactly like F4. Yet O2's mean-of-epochs LB is +0.019 over F4
and its `dir_acc` at cov 0.05 is 0.563 against F4's 0.542. **A flat training loss on a
near-noise-floor task says nothing about whether more data helps.** Judge the data lever
on the validation-selection metric, never on the loss curve.

### O0 — F4's re-score, for the record

The re-score reproduced F4's headline exactly (cov05 dir_acc 0.542 / LB 0.531) and finally
produced the `Fixed-coverage P&L` table F4's own log predated. F4 at 4h:

| cov | trades | gross bps/trade | net @5bps maker | net @14bps taker |
|---|---:|---:|---:|---:|
| 0.01 | 226 | +2.61 | −2.39 | −11.39 |
| 0.02 | 466 | +6.53 | +1.53 | −7.47 |
| 0.05 | 1104 | +6.50 | +1.50 | −7.50 |
| 0.10 | 2010 | −2.96 | −7.96 | −16.96 |
| 0.20 | 3721 | −4.38 | −9.38 | −18.38 |

This closes the N3-vs-F4 question with numbers: N3's +4.24 bps at cov 0.05 against F4's
+6.50 — well inside noise, as §1.5 already concluded on other grounds. Cost-aware
selection stays closed.

### O2's 1440m head — why it is not the new operating horizon

O2's 24h head has the highest cov05 LB in the run (0.575 vs the 4h head's 0.557) and a
striking +15.46 gross bps/trade at cov 0.05. Do not act on it. Its P&L is **non-monotone
in confidence** — cov 0.01 is −24.13 bps/trade and cov 0.02 is −11.58, i.e. the most
confident 1% of 24h calls lose money while the next 4% make it. That is the classic
"right about direction on small moves, wrong on large ones" pathology, and it is also
only 396 trades over the whole 8-month window. The 4h head's table is monotone in the
right direction (+24.5 → +22.1 → +3.5 → −5.2 → −3.1) and that ordering is what makes it
usable. 240m remains the primary.

⚠️ **A third thing invalidates numbers throughout this archive (found 2026-08-18, from
the N-wave).** Every headline `cov05 wilson_lb` in this file — and in the live plan's
ledger above the N-wave — is `max over epochs` of a per-epoch series whose epoch-to-epoch
standard deviation is ≈ **0.016** and whose mean is flat. Measured on the two runs that
share a training configuration:

| run | epochs | mean LB | sd | max LB | max in sd above mean |
|---|---:|---:|---:|---:|---:|
| F4 | 18 | 0.5058 | 0.0162 | 0.5310 (ep 8) | +1.56 |
| N3 | 11 | 0.4987 | 0.0155 | 0.5230 (ep 1) | +1.57 |

Paired per-epoch difference F4 − N3 over epochs 1–11: mean **+0.010**, sd **0.018** — two
runs of the *same* configuration differ by more than most of the "effects" this archive
argues about. **Any comparison in this file that turns on a cov05-LB difference below
~0.04 is not supported by its evidence.** That includes the E2a′ 0.568 / E2b 0.566 /
E3b1 0.559 / E3b2 0.554 pair-set-and-embed-dim rankings, and R0–R6's "tuning ceiling".

---

## Retired 2026-08-18 — the book ON/OFF walk-forward, and cost-aware checkpoint selection

Both were live questions in the 2026-08-18 plan's first N-wave. Both are now closed;
kept here for the reasoning.

**Book ON/OFF walk-forward (`gcp_walkforward.sh`) — retired as a *design*, not as a
question.** Three attempts: the 2026-08-04 single dense window (ON 0.691 / OFF 0.494), F3
(`wf-20260817T030350Z`, 8 pairs, min gap −0.161), and N1 (`wf-20260818T063858Z`, corrected
to the 4 long-book pairs, with the C4a `n_dir ≥ 500` decidability floor active). N1's
result: **2 of 6 folds decidable, so INCONCLUSIVE by its own pre-registered rule**; the two
decidable folds gave gaps `+0.073` and `−0.122`. Book-OFF `n_dir` across the six folds was
`64, 88, 87, 24, 556, 655` against book-ON's `454, 627, 901, 765, 619, 751`.

The design cannot answer the question, and this is structural rather than fixable by a
re-launch: the book-OFF arm's characteristic failure is collapsing to an all-flat predictor
(`3cls_pred f=0.87–0.97` in the four undecidable folds), which spends its top-5% confidence
on truly-flat bars and leaves too few directional trades to score. Collapse is the modal
book-OFF outcome, and collapse is exactly what makes a fold undecidable — so the more the
book actually helps, the less measurable that help becomes. Replaced by within-model
attribution (feature audit / permutation importance on one dense-window model), which has
no cross-arm comparability problem.

**Cost-aware checkpoint selection (`SEL_NET_WEIGHT`) — closed as a lever.** N3
(`20260818T031002Z`) ran it at 4h/15m with `SEL_NET_WEIGHT=0.5 SEL_COST_BPS=5`, the
horizon where the R5 objection ("at 30m nothing clears cost so the term has nothing to
rank") no longer applies. The term was alive — `net_sc` moved 0.505 → 0.127 across epochs,
so the R1 dead-floor failure did not recur — but it selected epoch 1 and early stopping
ended the run at epoch 11. Two reasons, both fatal to the lever as specified:

1. **Dynamic-range mismatch.** Over the run, `edge_lb` spanned 0.473–0.523 (0.050) while
   `net_score` spanned 0.127–0.505 (0.378). At `net_weight=0.5` the blend is effectively
   ~88% net term. `SEL_NET_SCALE=0.002` is the culprit: the logistic squash
   `sigmoid(2·net/scale)` moves ~0.19 per 19bps of `net/trade`. Matching the two ranges
   needs `SEL_NET_SCALE≈0.04`, or `net_weight≈0.1` at the current scale.
2. **The term ranks noise.** `net_per_trade` is the mean of `side·fwd_ret` over ~9,650
   gated bars, but 4h forward returns on 15m bars overlap 16-fold, so there are ~600
   independent observations behind it. At a 4h return σ of ~100–150bps that is a standard
   error of ~4–6bps, against a total observed epoch-to-epoch range of 19bps. Epoch 1
   (+0.2bps) versus epoch 2 (−4.4bps) is well inside one standard error.

And it did not achieve its goal. At matched trade counts the epoch it chose is no more
profitable than F4's LB-chosen epoch: F4 @ gate 0.60 = 592 trades at **+6.2** gross
bps/trade; N3 @ gate 0.55 = 716 trades at **+6.0**; N3 @ cov 0.05 = 855 trades at **+4.2**.
Collateral: the epoch-1 checkpoint has a compressed confidence scale (gates zero bars at
the served 0.58 on the 1h head — the new C1 warning fired correctly) and its 4h side split
is 9,487 up / 161 down.

---

## ▶️▶️▶️▶️▶️▶️ START HERE (2026-08-17) — 🔴 NORMALIZATION BUG FOUND; MOST E-SERIES CONCLUSIONS ARE ARTIFACTS; BOOK NOW ≥30d

**Supersedes the 2026-08-16 section below.** E3-tb + E4-GBT returned. Analyzing them
turned up a **proven, decisive bug in per-pair feature normalization** that invalidates
the "recent book-era edge is ~0 / we're signal-limited / no cost-viable gate" narrative
the last five sessions were built on. Read this whole section before launching anything.

### 🔴 P0 BUG — train-only z-score divides 12–13 of 19 features by std=1e-6

`data/dataset.py:443` (and `:446`): `std = np.sqrt(dev_sum / n) + 1e-6`. The `+1e-6` is
an *additive* epsilon, not a floor. For a feature column that is **identically zero
across the whole TRAIN window**, this yields `mean=0, std=1e-6`, and
`apply_norm_to_bundle` then divides the ENTIRE matrix (train **and** val) by `1e-6`.

Which columns are identically zero in train? All the ones whose source only started
being collected in the last ~30 days. Current split (E3-tb):
`train [2022-08-25 → 2026-01-29]`, `val [2026-01-29 → 2026-08-16]`, but
`orderbook_snapshots` / `market_trades` / `open_interest` all start **2026-07-17** —
i.e. **zero overlap with train**. So in train these are all exactly 0:

`spread_bps, imbalance, micro_mid, bid_ask_vol_ratio, depth_near_imb, trade_count,
buy_sell_imb, trade_vol, oi, oi_chg, has_book, has_trades` = **12 of 19 features**
(plus `has_funding_oi`, constant-1 rather than constant-0 — see the note under the proof).

Only `ret_1, hl_range, oc_range, log_vol, funding, ret_std_15` are normalized sanely
(`funding` reaches back to 2023-11 / 2022-08, so it has variance).

Note the irony: `config.py:212` claims "The masks also protect per-pair z-score norm from
near-constant (mostly-zero) features when a source has little/no history." The masks do
nothing of the kind — **they are themselves two of the exploding columns.**

**PROOF — verified directly on the E3-tb checkpoint**
(`gs://fluxtrader-train-artifacts/checkpoints/m2_multi_20260816T023427Z_d5d5b67a.pt`,
`meta.feature_dim=19`, `meta.label_mode=triple_barrier`, `meta.pair_embed_dim=0`).
`meta.norm_stats['BTCUSDT']`:

```
ret_1              mean= 9.58e-07   std= 6.96e-04     sane
hl_range           mean= 7.39e-04   std= 7.73e-04     sane
oc_range           mean= 9.57e-07   std= 6.95e-04     sane
log_vol            mean= 4.382      std= 1.095        sane
spread_bps         mean= 0          std= 1e-06   <== DEGENERATE
imbalance          mean= 0          std= 1e-06   <== DEGENERATE
micro_mid          mean= 0          std= 1e-06   <== DEGENERATE
bid_ask_vol_ratio  mean= 0          std= 1e-06   <== DEGENERATE
depth_near_imb     mean= 0          std= 1e-06   <== DEGENERATE
trade_count        mean= 0          std= 1e-06   <== DEGENERATE
buy_sell_imb       mean= 0          std= 1e-06   <== DEGENERATE
trade_vol          mean= 0          std= 1e-06   <== DEGENERATE
funding            mean= 8.15e-05   std= 9.63e-05     sane
oi                 mean= 0          std= 1e-06   <== DEGENERATE
oi_chg             mean= 0          std= 1e-06   <== DEGENERATE
ret_std_15         mean= 5.56e-04   std= 4.20e-04     sane
has_book           mean= 0          std= 1e-06   <== DEGENERATE
has_trades         mean= 0          std= 1e-06   <== DEGENERATE
has_funding_oi     mean= 1          std= 1e-06   <== DEGENERATE (mean=1, see note)
```

**13 of 19 columns degenerate; only 6 are normalized.** Identical for ETH, SOL and
`_global` (ETH's `has_funding_oi` std=0.0111, so that one column is pair-dependent).
Note `has_funding_oi` is centered at mean=1, so it maps to ~0 while it stays 1 — but any
bar where funding/OI goes stale becomes **−1e6**. The other 12 are centered at 0, so they
explode the moment their source appears in val. Repro:
```sh
gcloud storage cp gs://fluxtrader-train-artifacts/checkpoints/m2_multi_20260816T023427Z_d5d5b67a.pt /tmp/ck.pt
docker compose --profile ml run --rm -T -v /tmp/ck.pt:/tmp/ck.pt:ro ml_trainer python -c \
  "import torch;m=torch.load('/tmp/ck.pt',map_location='cpu',weights_only=False)['meta'];print(m['norm_stats']['BTCUSDT']['std'])"
```
The same 11-column signature is present in the older 16-feature
`m2_multi_epoch_snapshot.pt`, so **every checkpoint this project has ever produced on a
global-time split carries this defect.**

**Consequence.** The instant val crosses 2026-07-17, those inputs jump from 0 to
`value / 1e-6`:

| feature | raw scale | z after norm |
|---|---|---|
| `has_book` / `has_trades` | 1.0 | **1e6** |
| `imbalance`, `micro_mid`, `depth_near_imb` | O(1) | **~1e6** |
| `spread_bps` | ~0.5–2 | **~1e6** |
| `trade_vol` = log1p(vol) | ~10 | **~1e7** |
| `oi` = log1p(OI) | ~20 | **~2e7** |
| `trade_count` | ~1e2 | **~1e8** |

An LSTM fed 1e6–1e8-magnitude inputs saturates completely and emits a near-constant
output. **This is not a subtle effect — it is a hard cliff at the exact timestamp the
book era begins.**

### 🧹 WHAT THIS INVALIDATES (re-derive, do not trust)

Everything below was measured through the cliff and must be re-measured after the fix:

- ❌ **"tail-30d dir_acc = 0.477, below coin flip"** (`eval_m2_E2b1/2/3.json`). `--tail-days
  30` is *entirely* inside the book era → the model was evaluated exclusively on
  1e6-magnitude inputs. This is the flagship "there is no edge in the regime we trade"
  number and it is an artifact.
- ❌ **"the gate emits no confidence spread; gates 0.35–0.50 identical; 0.60 zero
  coverage"** — that is the signature of a saturated network emitting a constant, which
  is exactly what exploded inputs produce.
- ❌ **"E4 calibration diagnosis was wrong; head is correctly calibrated to ~zero
  signal; Brier 0.2505"** — Brier ≈ 0.25 with all mass in [0.48,0.53] is *also* the
  signature of a constant output. The conclusion ("you cannot calibrate signal into
  existence") may still be right, but the evidence for it does not survive.
- ❌ **"the recent/book-era WF fold decays"** (the metric that drove the whole E1→E3
  ladder, and the reason E2b beat E3b1/E3b2). The newest fold is the only fold that
  contains the cliff. Per-arm newest-fold LBs were compared as if they measured regime
  robustness; they were partly measuring how each arm degrades under input explosion.
- ⚠️ **"pair/dim tuning has hit its ceiling"** — plausible, but every arm was ranked on
  a partly-corrupted verdict metric.
- ✅ **STILL VALID: `gcp_ablate.sh` / `gcp_walkforward.sh` results.** Those use
  `--require-book`, which restricts *train* to the dense book window, so the book
  columns have real variance in train and std is sane. That is the ONE setup where
  normalization was correct — and it is the setup that found book-ON lb=0.691 vs
  book-OFF lb=0.494. Consistent: book features look informative exactly where they were
  correctly scaled, and worthless exactly where they were exploded.
- ✅ **STILL VALID: E4-GBT's numbers.** LightGBM is scale-invariant (splits are
  monotone-transform-invariant), so the norm bug cannot hurt it. GBT's 0.5314 is a clean
  read; the LSTM's 0.530 is a *handicapped* read.

### 🚨 P0 — THE SERVED MODEL IS ALSO AFFECTED

`serve.py:123-128` applies the checkpoint's saved `norm_stats` to live features via
`apply_feature_norm`. Live bars **do** have book/trade/OI data. So the promoted
checkpoint in the always-on UI is being fed ~1e6–1e8-magnitude inputs on 12 of 19
channels on every request. Whatever it is currently emitting is meaningless. This needs
checking/fixing before any live-signal read is trusted.

### 📊 E3-tb (triple-barrier) — VERDICT: CONFOUNDED, INCONCLUSIVE. Re-run.

`logs/E3-tb.log`, run `20260816T023427Z`. It was meant to change ONE variable vs E2b.
It changed **three**:

1. ✅ `LABEL_MODE=triple_barrier` (intended; verified in `resolved knobs`).
2. ❌ **`PAIR_EMBED_DIM` was omitted → `Pair embedding: off (pair-agnostic encoder)`**
   (log line, cf. E2b `Pair embedding: ON dim=8`). This is *literally the same mistake
   that voided E3a*, one session after it was documented. `PAIR_EMBED_DIM` is in
   `FLUX_TRAIN_ENV_KEYS` but defaults to `0`, so omitting it silently disables the
   feature that won E-round-2. **Root cause: the launch command written in this very
   document (the "E3 triple-barrier — GPU" block below) omits `PAIR_EMBED_DIM=8`.** Fix
   the class of bug, not the instance: change `config.py:139` to `PAIR_EMBED_DIM` default
   `8` (the live/promoted setting), so "forgot to pass it" degrades to the incumbent
   instead of to a silently different architecture.
3. ❌ **The dataset changed under us.** ETH 1m was backfilled from 669k → **2,090,599**
   bars (now starts 2022-08-25), so `Samples` went 9.98M → 11.42M, the train window
   start moved 2023-11-13 → 2022-08-25, and **the val boundary moved 2026-02-21 →
   2026-01-29**. E2b's `0.566` was measured on a different val window. Any E2b-vs-E3-tb
   comparison is invalid in both directions.

Numbers for the record (30m primary, ⚠️ dir_acc here is scored against *triple-barrier*
labels, so it is not the same quantity as E2b's fixed-Δt dir_acc):

| metric | E3-tb | E2b (old data, fixed labels) |
|---|---:|---:|
| cov05 dir_acc / lb | 0.533 / **0.530** | 0.566 |
| WF folds cov05 lb | .528 / .548 / .510 / **.539** | .568/.572/.560/**.548** |
| net_ret @gate0.4 | −106.1 (76,168 trades) | all-neg |
| early stop | epoch 17 (best 07/17) | epoch 19 |
| train class bal 30m | d .44 / **f .12** / u .44 | d .33 / f .35 / u .33 |
| train class bal 60m | d .48 / **f .05** / u .47 | d .32 / f .37 / u .32 |

Two real, actionable findings independent of the confounds:

- 🔧 **The barriers are mis-parameterized.** At `TB_TP_MULT=TB_SL_MULT=1.5`,
  `TB_VOL_WINDOW=15`, `TB_MIN_BARRIER=0.002`, the timeout ("flat") class is only **12%
  at 30m and 5% at 60m** — i.e. a barrier is hit almost always, so the label degenerates
  into "which side of the path moved first", not "was this a tradeable TP". Widen the
  band (`TB_TP_MULT=2.5–3.0`, and/or `TB_VOL_WINDOW=60`) to land flat around 30–40%.
- 🔧 **The P&L sim does not implement the barrier exit.** `eval_m2.simulate_pnl` books
  `fwd_ret` at a **fixed `hold_bars`** (`eval_m2.py:74-133`). Under TB labels the model
  predicts a TP/SL outcome but the simulator measures a fixed-Δt hold — a policy
  mismatch, so `net_ret=-106` is not the P&L of the strategy being labeled. Triple-barrier
  cannot be evaluated until `simulate_pnl` gains a barrier-aware exit (walk forward to
  first TP/SL touch, else timeout). **Do not re-run E3-tb before this exists** — the run
  cannot answer its own question.

### 📊 E4-GBT — VERDICT: no architecture headroom; ~all of the candle edge is static

`logs/E4-gbt.log`, run `gbt-20260816T132201Z`. Ran clean: knobs echoed correctly
(`HORIZONS=5,30,60 PRIMARY=30 SEQ_LEN=128`), 8-pair E2b set, `label_mode=fixed`,
5,680,167 moved train bars, D=114 compact-summary cols, peak rss 4.96GB (the memory
rework held). **Same dataset/split as E3-tb** (train 9,143,828 / val 2,285,958, val
starts 2026-01-30) → **E4-GBT and E3-tb ARE directly comparable to each other**, and
neither is comparable to E2b.

| metric | E4-GBT (trees, scale-invariant) | E3-tb (LSTM, same data) |
|---|---:|---:|
| cov05 dir_acc / lb | 0.5355 / **0.5314** | 0.533 / **0.530** |
| cov10 lb | 0.5279 | 0.526 |
| cov01 lb | **0.4892** ⚠️ | 0.532 |
| WF folds cov05 lb | .5557 / .5312 / .5068 / **.5172** | .528/.548/.510/**.539** |
| net @cov05 | −12.14 (9,932 trades) | — |

- **A 114-column static summary of the window matches a 128-step LSTM to within 0.0014
  LB.** Temporal sequence modeling is contributing ~nothing on candle features. Combined
  with the fact that the LSTM was *handicapped* by the norm bug and still tied, the
  honest read is: **architecture is not the bottleneck, and the candle-only edge is
  ~0.53 at 5% coverage.** No reason to spend another run on encoder capacity/shape.
- ⚠️ **GBT's confidence ordering is broken at the top:** cov01 lb **0.4892** < cov05
  0.5314 < cov10 0.5279. Its *most* confident predictions are its *worst* (below coin
  flip). Real signal is monotone in confidence. Treat GBT p(up) as a ranking with a
  garbage tail, and don't copy its calibration.
- Do NOT read this as "signal-limited, full stop". It bounds the **candle-only, fixed-Δt,
  30m** cell of the search space. It says nothing about book features (structurally
  untrainable in this split — see above), longer horizons, or barrier labels.

### 💰 THE REAL BLOCKER IS THE COST/HORIZON RATIO — and nobody has computed it

This is the most important number in the project and it is absent from every prior
section. Break-even for a directional strategy:

```
gross per trade = (2·acc − 1) · E|r_T|   must exceed   round-trip cost
E|r_T| ≈ 0.8 · σ_1m · √T                (σ_1m from the checkpoint norm stats:
                                         BTC 7.1e-4, ETH 9.4e-4, SOL 1.03e-3 → ~8.5e-4)
```

With σ_1m ≈ 8.5e-4 and the current cost model (`FEE_RATE_BPS=4` + `SLIPPAGE_BPS=3` per
side → **14bps round-trip**):

| horizon | E&#124;r&#124; | break-even acc @14bps (taker) | break-even acc @5bps (maker) |
|---|---:|---:|---:|
| 30m | ~30bps | **0.733** | 0.583 |
| 60m | ~42bps | 0.667 | 0.560 |
| 4h | ~85bps | 0.582 | **0.529** ✅ |
| 12h | ~147bps | 0.548 | 0.517 ✅ |
| 24h | ~208bps | **0.534** ✅ | 0.512 ✅ |

**We have been chasing 0.53–0.57 accuracy at a horizon that requires 0.73.** Every
single "all arms are net-negative" line in this document is explained by this table and
by nothing else. Confirmed empirically: the observed gross per trade at cov05 is
**+1.78bps** (GBT: net −12.22bps/trade + 14bps cost) — genuinely positive, just 7.9×
too small to pay the toll.

Two levers, and only two: **make E|r| bigger (longer horizon)** or **make cost smaller
(maker/limit execution)**. Accuracy tuning cannot close a 7.9× gap; that is why fourteen
runs of it produced nothing. Empirically accuracy is roughly *flat* in horizon (30m cov05
lb 0.530 vs 60m 0.529 in the same E3-tb run) while E|r| grows as √T — so horizon is
close to free edge. **4h with maker execution, or 24h with taker, is the first cell of
the space where a 0.535 model makes money.**

### 📚 DATA STATUS (verified on the always-on VM, 2026-08-17 02:38 UTC)

`./scripts/gcp_data_collection_stats.sh` → `/tmp/dcstats.txt`.

| source | coverage |
|---|---|
| `orderbook_snapshots` | **BTC/ETH/SOL 30d 5h ✅** (from 2026-07-17 21:13) · DOGE/HYPE/WLD 26d 23h · ZEC 22d 21h · 1000PEPE 20d 21h · ADA/AVAX/LINK/XRP 3d. Cadence ~1/10s (~6 per 1m bar). |
| `orderbook_levels` (raw L2) | **all 8 main pairs 11d 22h** (from 2026-08-05), **100 bid + 100 ask levels**, `missing_update_id=0`, `missing_event_time=0`. Clean. Cadence ~1/10s. |
| `market_trades` | mirrors snapshots (BTC/ETH/SOL 30d 5h) |
| `open_interest` | BTC/ETH/SOL 30d 5h · others 20–27d · extras 3d |
| `funding_rates` | 2y9mo–3y11mo (the only microstructure source with real history) |
| `liquidations` | **0 rows — still empty** (WS egress blocked). Drop it from all plans until the collector is fixed. |
| candles | 0 interior gaps, all 12 pairs, 1m/5m/15m/1h ✅ |

⚠️ **1m candle history is ragged across pairs.** ETH 1m starts **2022-08-25** (2.09M
bars) but BTC/SOL/DOGE/WLD/ZEC/1000PEPE 1m start **2023-11-13** (1.45M) — while BTC *5m*
goes back to 2022-08-25. So the first ~15 months of the current train window contain
**ETH only**. That is what moved the split and broke E2b comparability. Fix by
backfilling 1m to 2022-08-25 for all 8 (Binance has it — the 5m proves it) or by
trimming to the common start. Either way, **pin it before the next baseline**, and
re-pin the baseline whenever it changes.

### ✅ DECISION — ORDER OF OPERATIONS (2026-08-17)

**Nothing else is worth running until F1 lands.** Every verdict metric currently in use
is measured through the cliff.

**F1 — ✅ DONE 2026-08-17 (code only, NOT committed, NO run launched).**
- `config.py`: new `NORM_*` block — `NORM_DEGENERATE_STD` (1e-8), `NORM_CLIP` (50),
  `NORM_DEGENERATE_MODE` (`zero`|`passthrough`, default **zero**),
  `NORM_LEGACY_BROKEN_STD` (1.1e-6). Full rationale is in the comments there.
- `data/dataset.py`: new `finalize_train_std()` replaces the bare `+1e-6` at BOTH fit
  sites (M2 `fit_norm_from_bundle`, M1 `build_arrays`). It checks the **raw** std before
  the epsilon is added (checking after would never fire — `0 + 1e-6` is above any sane
  threshold) and rewrites degenerate columns to `std=1.0`. **Healthy columns keep the
  legacy `raw + 1e-6` value byte-for-byte**, so this is a no-op wherever scaling was
  already sane — verified in a unit check.
- `NORM_DEGENERATE_MODE=zero` (default): a train-constant column is pinned to **0** in
  train, eval AND serve via `zero_degenerate()`. This is the only train/val-consistent
  choice — the model was trained with that input pinned, so feeding it a real value at
  val/serve time is out-of-distribution for a channel it demonstrably learned nothing
  from. `passthrough` keeps the centered raw value (bounded by `NORM_CLIP`) and exists to
  measure how much the shift was costing. Measured on the dev DB: `passthrough` leaves
  junk of magnitude ~470 (`bid_ask_vol_ratio`) in the inputs; `zero` removes it.
- `NORM_CLIP=50` winsorizes everything as a second, cause-agnostic guard. It catches the
  NEAR-constant case the threshold cannot: a column with a small-but-nonzero std still
  produces huge z. Confirmed real — see the `oi` note below.
- `sanitize_norm_stats()` repairs **loaded** checkpoints, so `apply_norm_to_bundle` /
  eval / serve no longer explode when reading any pre-fix checkpoint.
- Loud `WARNING [norm] …` naming every degenerate (pair, feature), in train, eval and
  serve. Plus `[norm] <pair>: max|z|=… on '<worst column>'`, which names the offending
  feature — that is what made the `oi` problem below visible. It distinguishes
  `BROKEN SCALE` (>1000, i.e. a scaling bug) from `heavy tail, winsorized` (50–1000,
  legitimate on crypto returns), so it doesn't cry wolf.
- The `max|z|` report streams over row-chunks: `np.abs(arr)` on a 25M×19 float32 matrix
  would allocate ~1.9GB, exactly the kind of transient that has OOM-killed these runs.
- `PAIR_EMBED_DIM` default flipped `0 → 8` (see the E3-tb section: omitting it silently
  trained a different architecture and voided two runs in a row).

Verified (all in the `ml_trainer` container):
| check | result |
|---|---|
| healthy cols byte-identical to legacy `raw+1e-6` | ✅ |
| a real book row: `spread_bps` z | **1.2e6 → 1.2** |
| a real book row: `has_book` z | **1e6 → 1.0** |
| E3-tb ckpt sanitized: any `1e-6` left | ✅ none (13 cols repaired for BTC, 12 others) |
| `train_m2` end-to-end @ `CANDLE_INTERVAL=15m`, horizons 60/240/1440 | ✅ |
| `eval_m2` end-to-end, same | ✅ |
| main-track `max\|z\|` | **470 → 37.6** (worst is now `hl_range`, a real fat tail) |
| `--require-book` arm: real book features still live | ✅ only the 3 presence masks are constant (constant by construction there — they carry no information, so zeroing them loses nothing) |

**F2 — ✅ DONE 2026-08-17.** `serve.py` now runs `sanitize_norm_stats()` on the
checkpoint's stats at load, applies the same `zero_degenerate` + `clip_norm`, fixes the
same bug in the legacy rolling-fallback branch, logs a loud warning, and exposes
`norm_degenerate_cols` on `/health` (worst pair, not the sum across pairs).

Verified against the real promoted-lineage checkpoint (`m2_multi_20260816T023427Z`), with
a synthetic live window that has book data present, as live bars do:

| | before | after |
|---|---:|---:|
| live-window `max\|z\|` | ~3.5e8 | **1.32** |
| book/trade/OI channels | ~1e6–1e8 | **0.0** (what the model actually trained on) |
| `/health.norm_degenerate_cols` | — | `13` |

⚠️ **This makes serving non-degenerate, it does NOT make it good.** The model still never
learned from those 13 channels, so the live signal is effectively candle-only. A
trustworthy microstructure signal needs F5 (re-train) + re-promote. The startup warning
says exactly this so it can't be forgotten.

**🔧 NEW FINDING (from F1's max|z| report): `oi` is badly conditioned.** In the
`--require-book` dense window, `max|z|` is **526 (BTC) / 863 (DOGE) on `oi`** — a
legitimate heavy tail, not the norm bug, so `NORM_CLIP` winsorizes it. Cause:
`oi = log1p(open_interest)` is a *level*. Within any short window it is near-constant, so
its per-pair std is tiny, and an ordinary OI drift becomes hundreds of sigma. A level is
also non-stationary across the full history. `oi_chg` (the relative change) is the
correctly-conditioned feature and already exists. **Action for F6: drop the raw `oi`
level, or replace it with a rolling-normalized / differenced version.** Same question
applies to `log_vol`. Low risk, likely free accuracy in the dense-book arm.

**F3 — P1 RUN: Step A walk-forward book ON/OFF — NOW VALID, LAUNCH IT.** BTC/ETH/SOL
crossed 30d at ~2026-08-16 21:13 UTC; DOGE is at 27d. This is the one test whose
normalization was always sane, it is the gate on all microstructure investment, and it
is now unblocked.
```sh
WF_LONG_PAIRS_ONLY=1 WF_DROPOUT=0.4 WF_WEIGHT_DECAY=1e-3 WF_HIDDEN=48 \
  ./scripts/gcp_walkforward.sh
./scripts/gcp_walkforward.sh --fetch
```
Verdict rule (unchanged): book-ON − book-OFF Wilson-LB gap > ~0.05 on **ALL** folds →
book edge is robust → escalate microstructure. Any fold with gap ≤0 or overlapping LBs →
stop tuning book, keep collecting, re-check at ~60d (~2026-09-16).
Safe to run concurrently with F4 (separate VM, separate tmux, separate marker).

**F4 — P1 RUN: E6-horizon — attack the cost barrier (highest EV of any run in this doc).**
**Prereqs ✅ ALL DONE 2026-08-17 — the run is ready to launch as-is:**
- `eval_m2.py`: `BAR_SECONDS = 60` was **hardcoded**, silently assuming 1m candles. At
  `CANDLE_INTERVAL=15m` a 4h horizon (16 bars) would have used a **16-minute** hold, so
  `simulate_pnl`'s serial-position logic would have re-entered ~15× too often and every
  reported `net_ret` / trade count would have been garbage. Now derived from
  `CANDLE_INTERVAL` via `bar_seconds()`, which **raises** on an unknown interval instead
  of falling back. Verified: at 15m, holds print as `4 / 16 / 96 bars` = **1h / 4h / 24h**.
- `dataset.horizon_bars()` had the same silent `.get(interval, 1)` fallback → now raises
  on an unknown interval and warns when a horizon isn't a whole number of bars.
- `scripts/gcp_train.sh`: `CANDLE_INTERVAL` + the three `NORM_*` knobs added to
  `FLUX_TRAIN_ENV_KEYS` (`CANDLE_INTERVAL` was a real `config.py` knob honored
  everywhere in the code but was **not** forwarded to the GPU VM, so setting it would
  have silently trained on 1m).
- `FLAT_THRESHOLD_PER_HORIZON` already had 240 → 0.006, 1440 → 0.015. Smoke-tested at
  15m: class balance came out `down .23 / flat .54 / up .23` @4h — **flat-heavy but not
  degenerate**. Worth a look in the real run; if flat dominates, lower `FLAT_TH_4H`.
Then:
```sh
CANDLE_INTERVAL=15m PAIR_EMBED_DIM=8 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 128        # seq 128 × 15m = 32h context
```
15m bars keep the context/horizon ratio sane (32h of context for a 4h target) and cut
sample count ~15×, so this is a *cheap* run. **Read it against the break-even table
above, not against E2b's 0.566** — the question is "does cov05 dir_acc at 4h/24h clear
its break-even row", not "is accuracy higher".
Also re-report the same checkpoint at maker-cost assumptions:
`FEE_RATE_BPS=2 SLIPPAGE_BPS=0.5` (reporting-only knobs, no re-train).

**F5 — P1 RUN: re-baseline on the current dataset (do together with F1's verification).**
After F1, one run of the **exact E2b recipe** (fixed labels, `PAIR_EMBED_DIM=8`, 8 pairs)
on the current (ETH-backfilled) data. This becomes the new reference; the old 0.566 is
retired. Cheap and mandatory — without it nothing downstream is attributable.
Consider a second arm with `--ablate-book` to quantify how much the cliff was costing.

**F6 — P2: L2 ladder feature audit (cheap, read-only, no train).** `orderbook_levels` now
has 12d × 100 levels × 8 pairs with zero integrity errors. Two gaps in the current 5
book features, both fixable from data already on disk:
1. **They are all instantaneous levels, no dynamics.** No order-flow imbalance (OFI), no
   book delta over the last N snapshots, no queue-depletion rate, no depth slope /
   ladder shape, no microprice drift. Microstructure predictive power at 30m+ comes
   mostly from OFI and its persistence, not from a snapshot's static imbalance.
2. **~5 of every 6 snapshots are thrown away.** `_align_with_age` takes the *last*
   snapshot at/before each 1m bar and discards the rest. Per-bar aggregates (mean/std/
   range of imbalance within the minute, summed OFI, max spread) are free information.
Run `audit_microstructure.py` on candidate L2 features first (it already reports
Spearman ρ, monotonicity, sign-acc, and a vol-proxy vs directional split). The
2026-08-04 audit on 9d found `spread_bps` STABLE+DIRECTIONAL at ρ up to +0.165 (DOGE
60m) — the strongest single signal found anywhere in this project. Re-run it on 12d of
L2 + the new candidates before spending a `FEATURE_DIM` bump.

**F7 — P2: re-run E3-triple-barrier properly.** Blocked on: barrier-aware `simulate_pnl`
(see above), `PAIR_EMBED_DIM=8`, wider barriers (target ~30–40% flat), and a pinned
dataset. Not before F1/F5.

**F8 — P3: data hygiene.** Backfill 1m to a common 2022-08-25 start for all 8 pairs
(or trim ETH); fix or formally drop `liquidations`.

**Explicitly DROPPED:** encoder capacity / dim / layer sweeps (F4-GBT says architecture
is not the bottleneck), confidence calibration / temperature / focal loss (the
"under-confident head" was a saturated head), and raising `GATE_THRESHOLD` (the gate
sweep was run through the cliff — re-derive after F1 if it still matters).

### 📋 HANDOFF — START A FRESH SESSION HERE (state as of 2026-08-17)

**Status board.**

| id | what | state |
|---|---|---|
| F1 | normalization fix + degenerate-column guards + diagnostics | ✅ **code done, uncommitted, no run** |
| F2 | serve-path sanitize + `/health` field | ✅ **code done, uncommitted** |
| F4-prereq | `BAR_SECONDS`/`horizon_bars` from `CANDLE_INTERVAL`, env passthrough | ✅ **code done, uncommitted** |
| — | `PAIR_EMBED_DIM` default `0 → 8` | ✅ **code done, uncommitted** |
| F3 | walk-forward book ON/OFF | ▶️ **user launched 2026-08-17** — fetch results |
| F5 | re-baseline E2b recipe on current data | ⬜ not started (needs F1 committed) |
| F4 | E6-horizon run (15m bars, 4h primary) | ⬜ not started, **prereqs all landed** |
| F6 | L2 ladder feature audit + fix `oi` conditioning | ⬜ not started |
| F7 | triple-barrier redo (needs barrier-aware `simulate_pnl`) | ⬜ not started |
| F8 | 1m backfill to a common start; `liquidations` fix-or-drop | ⬜ not started |

**Uncommitted diff** (6 files): `ml/train/config.py`, `ml/train/data/dataset.py`,
`ml/train/serve.py`, `ml/train/eval_m2.py`, `scripts/gcp_train.sh`, this doc. All
syntax-checked; F1/F2/F4-prereq each verified end-to-end in the `ml_trainer` container
(tables above). **Nothing is committed and no training run was launched by the
implementing session.**

**Do this, in order:**

1. **Fetch F3.** `./scripts/gcp_walkforward.sh --status` then `--fetch`. Verdict rule:
   book-ON − book-OFF Wilson-LB gap > ~0.05 on **ALL** folds → book edge is real →
   escalate microstructure (F6 becomes P0). Any fold with gap ≤0 or overlapping LBs →
   stop tuning book, keep collecting, re-check at ~60d (≈2026-09-16).
   ⚠️ F3 was launched with the **pre-F1** code. That is fine and does not invalidate it —
   `--require-book` puts book features inside the train window, so their std was already
   sane there (this is the one path the bug never touched, see the § above). Two caveats
   when reading it: (a) it ran with `PAIR_EMBED_DIM=0`, so if F5/F4 later run at dim=8 the
   comparison to them is not clean — but the ON-vs-OFF gap *within* F3 is internally
   valid, which is the whole question; (b) the `oi` column is at 500–860σ there and was
   **not** winsorized pre-F1, so both arms carry that noise equally.
2. **Commit F1/F2/F4-prereq** as one reviewable change before launching anything that
   writes a checkpoint. F1 changes trained numerics by design, so every run after it is a
   new lineage — the commit is the lineage boundary and must exist first.
3. **Launch F5 (re-baseline) and F4 (E6-horizon) together.** They use separate throwaway
   VMs and don't collide. F5 gives the new reference number; F4 tests the cost/horizon
   thesis. Read F4 against the **break-even table**, not against E2b's 0.566.
4. **Then F6**, scoped by what F3 said.

**Verify in every future log before trusting a run** (each line is here because its
absence voided a real run):
- `=== resolved knobs: … ===` and the `knob K=V` echoes — env actually forwarded.
- `Pair embedding: ON dim=8` — not `off`. (Voided E3a **and** E3-tb.)
- `Training pairs: [...]` — the intended set.
- `primary=…` matches intent — the R3 silent-fallback lesson.
- `Split global_time … train [..] val [..]` — **record it.** The dataset moves under you
  when a backfill lands; that is what broke E2b comparability.
- `WARNING [norm] …` — how many columns are degenerate, and which. On the main track
  expect ~12–13 of 19 until the train window reaches the book era; under
  `--require-book` expect only the 3 presence masks.
- `[norm] <pair>: max|z|=…` — must NOT say `BROKEN SCALE`. A `heavy tail, winsorized`
  note is fine; check which column it names.
- `P&L sim: … hold=N bars` — N must equal `horizon_minutes / bar_minutes`.

**Standing traps in this repo** (all have burned a run):
1. Data lives on the always-on VM, never the local dev DB (see the top of this file).
2. Env knobs default to something other than the incumbent → an omission silently
   changes the experiment. Echo every knob; prefer defaults that equal the incumbent.
3. Silent fallbacks (`.get(x, default)`) on horizons/intervals/primary. Make them raise.
4. A backfill landing mid-experiment moves the train/val split. Pin and re-record it.
5. Additive epsilons are not floors. (This session's bug.)

---

## ▶️▶️▶️▶️▶️ (2026-08-16) — E3 BATCH ANALYZED; TUNING CEILING CONFIRMED; NEXT = WALK-FORWARD BOOK ON/OFF (data-gated ~08-17)

> ⚠️ **SUPERSEDED 2026-08-17.** Its verdicts on tail-30d edge, gate viability, head
> calibration and newest-fold WF decay were all measured through the normalization bug
> documented above. Kept for history; do not act on it.

**Supersedes the 2026-08-13 PM section below.** The E3 dim-sweep + the E-gate/cost eval
returned and are analyzed. Bottom line: **pair/dim tuning has hit its ceiling and E4
(calibration) is based on a wrong diagnosis — do NOT run it.** The next real decision is
the data-gated walk-forward book ON/OFF (Step A), which becomes valid ~2026-08-17.

### 📊 What E3 showed (verdict = 30m cov05 Wilson-LB + WF stability, esp. newest/book-era fold)

| Arm | dim / pairs | cov05 lb | WF folds (cov05 lb) | newest fold | WF spread | Verdict |
|-----|-------------|---------:|---------------------|------------:|----------:|---------|
| E3b1 | dim=4, 8p | 0.559 | .554/.578/.582/**.533** | 0.533 | 0.049 | **Reject.** Lowest peak; newest/book-era fold decays worst. Under-specialized. |
| **E2b (live)** | dim=8, 8p | **0.566** | .568/.572/.560/**.548** | 0.548 | 0.024 | Incumbent. Best headline, strong newest fold. |
| E3b2 | dim=16, 8p | 0.554 | .549/.566/.553/**.562** | **0.562** | **0.017** | **Marginally best book-era stability** (flattest WF, strongest newest fold) but lower headline. Non-promotable (still net-neg). Not worth the churn vs E2b for ~1 LB pt. |
| E3a | off, 12p | **VOID** | — | — | — | **Log truncated at eval start** (`logs/E3a.log` ends mid-eval; `logs/error.log` = failed `gcp_logs.sh` fetch of run `20260814T144713Z`). Also `PAIR_EMBED_DIM` was accidentally OMITTED → pair-embed OFF (plan said dim=8), so even if re-fetched it confounds "more pairs" with "dropped embedding". Re-run cleanly if the 12-pair question still matters. |

Dim curve is non-monotonic (peak acc @8, best book-era stability @16), but all gaps are
~1.5 LB pts — within noise. **No E3 arm is promotable; all are net-negative and all show
the same recent-era collapse. Keep E2b live.**

### 🚫 E-gate/cost — ANSWERED: there is NO cost-viable operating point (do not raise the gate)

The three `GATE_THRESHOLD=0.55/0.60/0.65 … eval_m2.py --tail-days 30` runs
(`logs/eval_m2_E2b1/2/3.json`) are the **same live E2b checkpoint on the same window** —
`GATE_THRESHOLD` w/o `--gate` only moves the `*` marker; use `--gate a,b,c` for a real
sweep in ONE run (see skill note). What the gate sweep on the recent (all-book-era) tail-30d shows:

- Gates **0.35–0.50 are identical** (cov=1.0, 2296 trades) — the dir head emits **no
  confidence spread** on recent data, so no sub-0.55 gate filters anything.
- Gate **0.55**: cov→4%, dir_acc **0.473 / LB 0.448** (*below coin flip*), net still neg.
- Gate **0.60**: **zero coverage** — head never exceeds 0.60 confidence.
- Tail-30d ungated dir_acc@cov05 = **0.477 / LB 0.454** — **below coin flip in the exact
  regime we trade.** (Training-log book-era LB ~0.53 was inflated by pre-book bleed + a
  larger window; the pure recent 30d is coin-flip-to-negative.)

### 🛑 E4 (calibration) — DIAGNOSIS WAS WRONG; DO NOT RUN AS PLANNED

The plan said "head is under-confident → sharpen it (temperature/focal/kill label
smoothing)". The code + data refute this:
1. **The directional head — the one that gates — already has NO label smoothing**
   (`train_m2.py:523-525`, plain weighted CE). `CLS_LABEL_SMOOTHING` only touches the
   unused 3-class head. So "disable label smoothing" is a no-op for the gate.
2. **The head is not under-confident — it's correctly calibrated to ~zero signal.**
   Tail-30d directional calibration (`eval_m2_E2b1.json`): all p(up) mass in [0.48,0.53];
   in the [0.50,0.60) bin mean_pred=0.532 vs empirical_up=**0.492** (over-, not under-,
   stated); **Brier 0.2505 ≈ 0.25 coin-flip baseline**.
3. Temperature scaling / focal loss would **sharpen an edgeless distribution → confident
   wrong predictions → worse P&L.** You cannot calibrate signal into existence.

### ✅ DECISION — NEXT IS STEP A (walk-forward book ON/OFF), data-gated to ~2026-08-17

The consistent pattern R0→E3: **the recent book-era edge is ~0; this is a data/feature
problem, not a model problem.** So the correct next step is the diagnostic that gates
everything downstream — does microstructure carry ANY real edge — NOT more tuning.

Book history (checked 2026-08-16 via `orderbook_snapshots`):

| Pair(s) | book age (2026-08-16) | ≥30d |
|---------|-----------------------|------|
| BTC/ETH/SOL | **29d 5h** | **~2026-08-17 (≈19h away)** |
| DOGE/WLD/HYPE | ~26d | ~08-20 |
| ZEC | ~22d | ~08-24 |
| 1000PEPE | ~20d | ~08-26 |

**Do NOT launch today** — even the majors are ~19h short of 30d; running now carves
tiny dense-book val slices per fold and re-measures noise (the exact fluke the plan
warns about). **~2026-08-17, once BTC/ETH/SOL cross 30d, launch long-pairs-only:**

```sh
WF_LONG_PAIRS_ONLY=1 WF_DROPOUT=0.4 WF_WEIGHT_DECAY=1e-3 WF_HIDDEN=48 \
  ./scripts/gcp_walkforward.sh
./scripts/gcp_walkforward.sh --fetch   # → logs/... compare table
```

**VERDICT RULE (unchanged):** book-ON − book-OFF Wilson-LB gap > ~0.05 on **ALL** folds
→ book edge robust → Step B. If ANY fold's gap ≤0 or LBs overlap → **STOP tuning, keep
collecting, re-check at ~60d.** Given the tail-30d coin-flip result, expect this may
fail; that is an acceptable (and informative) answer. Full 8-pair walk-forward ~08-26.

**If Step A fails:** the honest path is feature/data work (full-fidelity L2 book —
`orderbook_levels` accumulating since 08-05; long/short & taker ratios; liquidations),
NOT more model tuning. Triple-barrier labels (E3-label) is the one remaining *modeling*
lever worth trying — it changes WHAT we predict (tradeable TP/SL vs fixed-Δt sign) and
can create signal where fixed-Δt has none — but gate it behind Step A.

### 🟢 PARALLEL TRACK — book-independent levers to run WHILE waiting on walk-forward

The walk-forward wait does NOT block these; none need order-book data. Plan-recommended
order is E4-GBT FIRST (cheapest, gates the others).

**Status update 2026-08-16 (code only, NOT committed, NO run launched): E4-GBT and
E3-triple-barrier are now IMPLEMENTED.** E5-cross-pair is still unimplemented.
- `ml/train/gbt_baseline.py` — new standalone diagnostic. Reuses the M2 bundle, the
  SAME global time split + per-pair norm, trains a LightGBM BINARY up/down classifier
  on MOVED train bars (mirrors `train_m2.directional_loss`), maps p(up)→[down,flat,up]
  logits via `gate.dir_logits_to_three_class`, then runs the IDENTICAL
  `gate.fixed_coverage_metrics` + `eval_m2.simulate_pnl` + `side_split_metrics` +
  `walk_forward_edge` reporting so numbers are directly LSTM-comparable. Default input
  is a compact per-window summary (last bar + mean/std/min/max/delta over SEQ_LEN);
  `--flatten` uses the full window. `--tail-days`, `--label-mode`, GBT hyperparams
  exposed. Verified end-to-end in the ml_trainer container (3-pair/15d smoke).
- `lightgbm>=4.1.0` added to `requirements.txt` + `requirements.gpu.txt`. ⚠️ The image
  currently FAILS to rebuild on a PRE-EXISTING unrelated pin: `torch==2.5.1+cpu` local
  tag was dropped from the PyTorch CPU index (plain `2.5.1` still exists). lightgbm
  installs fine on top of the existing image; fix the torch pin before the next clean
  rebuild (separate decision — it affects served numerics). `scripts/gcp_gbt.sh` works
  around it by relaxing the pin in the throwaway VM's checkout only (see below).
- **2026-08-16 (later): the first 8-pair launch was OOM-killed on the always-on VM (2GB).**
  Two fixes landed: (a) `scripts/gcp_gbt.sh` — throwaway self-cleaning VM for this
  diagnostic, mirroring `gcp_audit.sh`; that is now the documented way to run it;
  (b) `gbt_baseline.py` memory rework — X is built only for the rows actually fitted
  (was: all train rows, then a boolean-mask copy = 2× peak), handed to LightGBM's native
  API as a constructed `Dataset` so the raw float32 matrix is freed before boosting, val
  streamed through `predict` in bounded chunks, unused bundle arrays (non-primary
  horizons, closes, book mask) dropped after the split, a `--max-train-rows` cap, and
  `[mem] rss=` traces at every step. Feature values are unchanged (verified
  bit-comparable) and the LightGBM params are exact equivalents of the previous
  `LGBMClassifier` kwargs, so it is the same experiment — just several times lighter.
  Also: the silent `PRIMARY_HORIZON ∉ HORIZONS_MINUTES` fallback now WARNS loudly — the
  aborted run had resolved to `primary=5m`, which is NOT E2b-comparable.
- `LABEL_MODE=fixed|triple_barrier` (default `fixed` = byte-identical legacy) +
  `TB_TP_MULT/TB_SL_MULT/TB_VOL_WINDOW/TB_MIN_BARRIER` added to `config.py`.
  `data/features.py` gains `triple_barrier_labels()` (vol-scaled TP/SL/timeout,
  close-to-barrier crossing, -1 invalid tail matches fwd-NaN) wired into
  `make_labels_and_returns(..., label_mode=LABEL_MODE)`; the quantile head still trains
  on the raw fixed-Δt forward return. Threaded through `dataset.py` (bundle meta records
  `label_mode`) and forwarded on GPU runs via `LABEL_MODE`/`TB_*` in
  `scripts/gcp_train.sh`'s `FLUX_TRAIN_ENV_KEYS`. Verified: labeler correct on synthetic
  up/down/timeout series; OFF path unchanged.

- **E4-GBT baseline — DIAGNOSTIC, do first (~2–3h, standalone, no serve risk).**
  Answers the single most important open question: **signal-limited vs model-limited?**
  New `ml/train/gbt_baseline.py`: reuse `build_feature_frame` + `make_labels`, flatten
  the last `SEQ_LEN` bars (or a compact summary: last-bar + a few rolling stats) per
  sample, train LightGBM (3-class or the up/down directional target to match the gated
  head), then run the SAME `gate.py` fixed-coverage sweep + `eval_m2.simulate_pnl` so
  numbers are directly comparable to the LSTM. Add `lightgbm` to `requirements*.txt`.
  Diagnostic only — do NOT wire into serve.
  - **Read:** GBT cov05 Wilson-LB + net P&L vs E2b (0.566 lb / all-neg P&L).
  - **Decision:** GBT ≈ LSTM and also can't clear cost → **signal-limited** → stop
    tuning architecture, pivot to data/features (book, cross-pair, taker ratios).
    GBT clearly BEATS LSTM → LSTM is leaving signal on the table → architecture is
    worth revisiting. GBT clearly WORSE → LSTM temporal modeling is helping; signal is
    just thin.
  - **Caveat:** candle-only + pooled val (pre-book-dominated), so a fail is the likely
    and still-useful "we're signal-limited" answer; a pass would be genuinely new info.
  - Run it with `./scripts/gcp_gbt.sh` (own throwaway VM, self-cleaning); safe to run
    concurrent with `gcp_walkforward.sh`. NOT on the always-on VM — 2GB, OOM-kills it.

- **E3-triple-barrier labels — MODELING (~half day code + 1 GPU run).** New labeler:
  for each bar walk forward to the horizon, label UP if +vol-scaled TP hit first, DOWN
  if -SL first, FLAT if timeout. Gate behind `LABEL_MODE=triple_barrier|fixed`
  (default `fixed` = current). Keep raw fwd-return for the quantile head. Update
  `make_labels*` callers in `dataset.py`. Standard fix for "right but not tradeable".
  **Sequence after E4-GBT:** if GBT says signal-limited, triple-barrier is the ONE
  modeling lever still worth a shot (it changes the target, not just the model); if
  GBT says model-limited, do it too but architecture work competes.

- **E5-cross-pair/regime features — FEATURE (~half day code + 1 GPU run).** Trailing
  1h/4h/1d returns, longer rolling vol, BTC-beta. `FEATURE_DIM` bump → checkpoint/serve
  change (attributable run of its own). Do AFTER E4-GBT triage. Free from candles,
  zero collection lead time (`docs/DATA_COLLECTION_AUDIT.md`).

**Recommended parallel plan:** build + run **E4-GBT** now (highest info/hour, unblocks
the E3-vs-E5 choice, no serve risk) alongside the ~08-17 walk-forward. Read both
together next session: walk-forward answers "does book carry edge?"; GBT answers "is
ANY candle signal there at all?". Together they tell you whether the ceiling is data,
features, or architecture.

### 🚀 HOW TO LAUNCH E4-GBT + E3 (exact commands — 2026-08-16)

> ⚠️ **DATA SOURCE OF TRUTH = the ALWAYS-ON GCP VM, never the local dev DB.** All
> training/eval/backfill run against the collector on `fluxtrader-1`
> (`gcloud compute ssh --zone me-central1-b fluxtrader-1 … docker compose exec -T
> postgres psql`). The local `docker compose exec postgres` is a throwaway dev DB and
> does NOT mirror the VM's candle/book history or the additional backfilled pairs. Do
> NOT check the local DB to reason about pair readiness — use
> `./scripts/gcp_data_collection_stats.sh` (which SSHes to the VM). See the standing
> note in the "DATA & ENVIRONMENT" section near the top of this file.

**Which pairs?** The **DB UI whitelist** (`app_settings.whitelist_pairs`) is the default
for both paths when `--pairs`/`TRAIN_PAIRS` is omitted. The 4 extra pairs
(`AVAXUSDT,LINKUSDT,XRPUSDT,ADAUSDT`) DO have substantial backfilled history on the VM
(user backfilled them — they are NOT short/ragged). Two independent decisions:

- **E4-GBT (diagnostic) and E3 (label A/B): use the SAME pair set E2b was trained on so
  results are attributable.** E2b = the 8-pair set
  (`BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT`). The point of
  each run is to isolate ONE variable (GBT: architecture; E3: the label). Changing the
  pair set at the same time makes the result un-attributable — exactly what voided E3a
  (pairs changed + embed accidentally off; line ~435). So keep these two on E2b's 8.
- **"More pairs" (now 12, since the extras are backfilled) is its own clean experiment
  (E3a).** With the extras confirmed to have history, E3a is now unblocked — run it
  standalone (one variable: the pair set) with `PAIR_EMBED_DIM=8` and the 12-pair
  `TRAIN_PAIRS` (see the E3 LADDER E3a command below). First confirm freshness/coverage on
  the VM with `./scripts/gcp_data_collection_stats.sh`.

**E4-GBT — THROWAWAY VM, run now (no GPU, no serve risk, safe concurrent with
walk-forward).** ⚠️ **Do NOT run this on the always-on VM.** That was tried
(2026-08-16) and the kernel OOM-killed it mid-bundle: the box is 2GB and already runs
postgres + app + ml_inference, while an 8-pair full-history run needs ~2-4GB (the design
matrix, not the bundle, dominates). The kill is SILENT — the log stops after
`Building bundle...` and no report is written. Same reason `gcp_audit.sh` exists.

```sh
./scripts/gcp_gbt.sh                       # E2b 8-pair set, horizons 5,30,60, primary 30m
./scripts/gcp_gbt.sh --status              # VM liveness + marker
./scripts/gcp_gbt.sh --fetch               # summary tables + report JSON (→ $EXPORT_DIR)
./scripts/gcp_gbt.sh --log                 # full console log
```

It mirrors `gcp_audit.sh`: fresh dump from always-on → own temp VM (`fluxtrader-gbt`,
e2-standard-4 = 4 vCPU/16GB) → restore → `gbt_baseline.py` in `ml_trainer` → push
log + JSON + summary to `gs://…/gbt/` → self-DELETE on success / self-STOP on failure.
Separate VM, tmux session and status marker from train/audit/ablate, so it can run
concurrently with the walk-forward. Never writes a checkpoint.

Notes:
- Defaults `--pairs` to E2b's 8 pairs (attributability) and passes
  `HORIZONS_MINUTES=5,30,60 PRIMARY_HORIZON=30 SEQ_LEN=128` EXPLICITLY, then echoes
  them as `=== resolved knobs: … ===`. This matters: `gbt_baseline.py` takes horizons
  from config env, and the always-on container's env made the aborted run print
  `primary=5m` — 5m numbers are NOT comparable to E2b's 30m. The script hard-errors if
  `GBT_PRIMARY ∉ GBT_HORIZONS`, and the python now prints a loud WARNING instead of
  silently falling back (the R3 lesson).
- Any other flag is passed through verbatim: `--tail-days N`, `--max-train-rows N`
  (both bound RAM), `--flatten` (full SEQ_LEN×F window), `--label-mode triple_barrier`
  (E3-flavored GBT), `--n-estimators/--num-leaves/--learning-rate/--seed`, `--chunk-mb`.
- The script builds `ml_trainer` on the temp VM. The pre-existing `torch==2.5.1+cpu` pin
  no longer resolves on the PyTorch CPU index, so the build falls back (in the temp VM's
  checkout ONLY, with a warning) to `torch==2.5.1`, then to unpinned CPU torch. Safe
  here: this diagnostic uses torch purely for the gate/P&L tensor math, never to train
  or load a model. Fixing the pin for real still affects TRAINED numerics → separate
  decision, untouched.
- Container path (only if you have a DB + ≥4GB free where you run it — the local dev DB
  is NOT the real data, see AGENTS.md):
  ```sh
  docker compose --profile ml run --rm \
    -e HORIZONS_MINUTES=5,30,60 -e PRIMARY_HORIZON=30 -e SEQ_LEN=128 \
    ml_trainer python gbt_baseline.py \
      --pairs BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
      --tail-days 90 --max-train-rows 400000 \
      --out /workspace/train/output/gbt_8pair.json   # → ml/train/output/ (bind mount)
  ```
- `gbt_baseline.py` prints `[mem] <step>: rss=… MB` at each stage, so if a run ever does
  get killed the log shows exactly which step blew the budget.

**E3 triple-barrier — GPU (launches a throwaway VM).** One change vs E2b: the label mode.

```sh
LABEL_MODE=triple_barrier \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 128
./scripts/gcp_logs.sh <run_id> --save        # → logs/E3-tb.log
```

VERIFY IN LOG BEFORE trusting the run (the E2b/R3 silent-no-op lesson):
- `=== resolved knobs: … LABEL_MODE=triple_barrier …` (env forwarded to the VM), and
- `Training pairs: [...the 8 pairs...]`.

Optional barrier tuning (defaults: symmetric 1.5× vol-scaled, 0.2% floor, 15-bar vol
window): `TB_TP_MULT / TB_SL_MULT / TB_VOL_WINDOW / TB_MIN_BARRIER` (all in
`FLUX_TRAIN_ENV_KEYS`, so they forward on `--gpu` runs).

**Verdict rules:**
- E3: compare 30m cov0.05 Wilson-LB + walk-forward NEWEST-fold lb vs E2b (**0.566** /
  **0.548**). Do NOT promote unless newest-fold lb ≥ 0.548 AND it holds across folds.
- E4-GBT: compare cov0.05 lb + net P&L vs E2b. GBT ≈ LSTM & net-neg → **signal-limited**
  (pivot to data/features); GBT ≫ LSTM → architecture headroom; GBT ≪ LSTM → temporal
  modeling is helping, signal is thin.

**Read both in a FRESH session** (token hygiene) and fill the RESULTS TABLE.

---

## ▶️▶️▶️▶️ START HERE (2026-08-13 PM) — E-ROUND-2 RETURNED; E2b IS THE WINNER; promote + launch E3

**Read this first — supersedes the 2026-08-13 (AM) section below.** The E-round-2 batch
(E2a′ / E2c / E2b′-for-real) is DONE and analyzed. Logs: `logs/E2a1.log` (E2a′ reseed),
`logs/E2c.log` (majors-only 4-pair), `logs/E2b.log` (pair-embed dim=8, 8 pairs — the
REAL E2b; the pair-embed code now exists and the config echo confirms
`Pair embedding: ON dim=8 n_pairs=8`). All ran GPU, 60 epochs, seq_len 128, primary 30m.

### 📊 What E-round-2 showed (verdict metric = 30m Wilson-LB @ fixed cov, HELD across WF folds)

Every arm is still net-negative in the P&L sim at the 0.4 serve gate (14bps cost eats the
~0.55 edge at full coverage) — unchanged ceiling. The discriminator is walk-forward
stability of the fixed-cov Wilson-LB, esp. the most-recent (book-era) fold.

| Arm | Run / log | cov05 lb | cov10 lb | WF folds (cov05 lb) | Verdict |
|-----|-----------|---------:|---------:|---------------------|---------|
| E2a′ 7-pair reseed | `logs/E2a1.log` | 0.568 | 0.557 | .590/.553/.568/**.542** | Reproduces E2a (~.003 off → edge is real, not seed noise). Edge front-loads in fold-1, decays to .542 by newest fold. |
| E2c majors-only 4-pair | `logs/E2c.log` | 0.559 | 0.550 | .545/.554/.565/**.512** | **Weakest.** Fewer pairs hurt; newest fold collapses to .512 (≈coin flip in book era). More pairs > fewer — REJECT dropping to 4. |
| **E2b pair-embed dim=8, 8 pairs** | `logs/E2b.log` | **0.566** | **0.556** | **.568/.572/.560/.548** | **✅ WINNER (most stable).** Tightest WF spread (0.024 vs ~0.05), strongest newest/book-era fold (.548). Pair-embed didn't raise peak edge but FLATTENED it across time = generalizing, not memorizing. Keeps all 8 pairs tradeable. |

**Decision:** E2b is the candidate to serve — chosen on walk-forward *stability* in the
book era (the regime we trade), not headline dir_acc. It's still net-negative at the 0.4
gate, so promotion here means "make it the served base model + then attack the cost/
calibration ceiling", not "it's profitable". Cost is still the true ceiling.

### 📌 ORDER OF OPERATIONS (2026-08-13 PM → next session)

1. **✅ DECIDED: promote E2b, then launch the E3 batch.** `latest.pt` currently = E2b
   (`run=20260813T114311Z`, sha `a26b032b`, verified in the bucket). **`gcp_promote.sh`
   only ever promotes `latest.pt` (no explicit-checkpoint arg) — so PROMOTE BEFORE
   launching any new run, or the new run overwrites `latest.pt` and E2b can't be
   promoted via the script.**
   ```sh
   ./scripts/gcp_promote.sh --local-copy   # installs on ALWAYS-ON GCP VM, restarts ml_inference there; --local-copy = Mac backup only
   docker compose restart app              # only if ML_GATE_THRESHOLD/env changed locally
   ```
2. **Validate candidate new pairs BEFORE E3a** — check freshness/coverage on the VM (NOT
   the local dev DB; see the DATA & ENVIRONMENT note at top):
   `./scripts/gcp_data_collection_stats.sh`. (Update 2026-08-16: the 4 extras
   AVAX/LINK/XRP/ADA were backfilled with substantial history, so they are candidates —
   confirm freshness, not history length.)
3. **Launch E3 batch** (independent throwaway VMs, safe concurrent). Fetch each with
   `./scripts/gcp_logs.sh <run_id> --save` → `logs/E3a.log` / `logs/E3b.log` /
   `logs/E3c.log`; FIRST grep each for the config echo (pairs + `PAIR_EMBED_DIM`) to
   confirm it took effect (the E2b-no-op lesson).
4. **Bring results back in a FRESH session**; update the RESULTS TABLE; pick winner by
   the verdict metric.

### 🎯 E3 LADDER — launch these (agreed 2026-08-13 PM; baseline to beat = E2b cov05 lb 0.566, WF newest-fold lb 0.548)

- [ ] **E3a — MORE PAIRS (extend the winning 8-pair set, keep pair-embed=8).** More-pairs
  monotonically helped WF stability (8 > 7 > 4); test if the trend continues. ⚠️ only
  include new pairs that pass the step-2 freshness check.
  ```sh
  PAIR_EMBED_DIM=8 \
    TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT,AVAXUSDT,LINKUSDT,XRPUSDT,ADAUSDT \
    ./scripts/gcp_train.sh --gpu 60 128
  ```
- [ ] **E3b / E3c — PAIR-EMBED DIM SWEEP** (same 8-pair set as E2b; dim=8 IS E2b, so only
  run the two new points). Find where per-pair specialization peaks.
  ```sh
  PAIR_EMBED_DIM=4  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT ./scripts/gcp_train.sh --gpu 60 128
  PAIR_EMBED_DIM=16 TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT ./scripts/gcp_train.sh --gpu 60 128
  ```
- [ ] **E-gate/cost — EVAL-ONLY (no GPU run needed).** All edge lives in the ≥0.55 tail;
  the 0.4 serve gate over-trades. Re-eval the now-live E2b at a higher gate / read the
  cov0.55 P&L row to find a cost-viable operating point; if net-positive there, raise
  `GATE_THRESHOLD` / `ML_GATE_THRESHOLD` in `docker-compose.yml`.
  ```sh
  GATE_THRESHOLD=0.55 docker compose --profile ml run --rm ml_trainer python eval_m2.py --checkpoint /models/m2_multi.pt
  ```
- [ ] **E4 — CALIBRATION (retrain; do AFTER E3 results, one change at a time).** The head
  is under-confident (no mass >0.60, brier ~0.249 in all runs) so the gate can't select
  a small high-edge slice. Attack via loss change: temperature scaling / focal loss /
  disable label smoothing. See TASK 2c below for the temperature-scaling plan.

**Do NOT promote any E3 checkpoint** until its WF newest-fold lb ≥ E2b's 0.548 AND it
holds across folds. E2b is the live baseline now.

---

## ▶️▶️▶️ (2026-08-13 AM) — E1/E2 batch analyzed; pair-embed implemented; launched E-round-2

**Superseded by the PM section above (E-round-2 results are now in).** Kept for history.

The E1a/E1b/E2a/E2b batch (launched 2026-08-12) is DONE and
analyzed; results are in the RESULTS TABLE below and in `logs/E1a.log … E2b.log`.
This session (a) analyzed those four runs and (b) **implemented the pair-embedding
code (TASK E2)** that E2b was supposed to test but couldn't, because the knob didn't
exist yet.

### 📉 What the E1/E2 batch showed (verdict per arm; details in RESULTS TABLE)

- **E1a (4h primary) — REJECT.** The 240m head is *weaker* than the served 30m head
  (cov0.05 lb .536) and its edge is a **book-era confound**: pre_book lb .536 but
  book-era lb **.460** (worse than coin flip). Longer horizon did NOT buy cost
  survival here. ⚠️ Its bottom-of-log fixed-cov table describes the **240m PRIMARY**,
  not the 30m the stack serves — not comparable to R6/E2a on the serve gate.
- **E1b (1d primary) — REJECT.** Unstable across time: WF fold-3 lb **0.390** vs
  fold-2 .590. The 1d momentum baseline (cov0.02 dir_acc .603) nearly matches the
  model → the 1d head is largely relearning trailing-return momentum, not adding edge.
- **E2a (drop HYPEUSDT) — PROMISING, NEEDS A CONFIRMING SEED.** Removing the worst
  pair (HYPE, ungated .389) lifted the top-confidence tail hard: **cov0.01 lb 0.624**
  vs R6's .551, and it stays ≥ baseline through cov0.10. Supports the
  "pooled encoder is dragged down by bad pairs" hypothesis. Caveats: small n_dir at
  cov0.01 and a soft WF fold-4 (.539) — one reseed decides if it's real or variance.
- **E2b (`PAIR_EMBED_DIM=8`) — INVALID / NO-OP.** `PAIR_EMBED_DIM` was **never read**
  by any code — there was no embedding to build — so the flag did nothing and E2b was
  a plain reseed of R6 (numbers match R6 within noise). **Root cause of the no-op:**
  the model had no pair identity AND, separately, `gcp_train.sh`'s `FLUX_TRAIN_ENV_KEYS`
  allowlist wouldn't have forwarded the var to the VM anyway. **Both are now fixed.**
- **Cost is still the ceiling.** Every arm is net-negative at the 0.4 serve gate; the
  only non-catastrophic P&L is the low-coverage ≥0.55 tail. Nothing here is promotable.

### ✅ Code implemented this session (2026-08-13, code only, NOT committed)

TASK E2 (pair embedding) is done and locally verified. See the updated "TASK E2" entry
below for the full description. Summary of touched files:
- `ml/train/config.py` — new `PAIR_EMBED_DIM` (default **0 = off = legacy-identical**).
- `ml/train/models/multi_horizon.py` — `nn.Embedding(n_pairs+1, dim)` (row `n_pairs`
  = OOV bucket), concatenated to the **pooled** LSTM state before the heads; `pair_idx`
  threaded through all `forward_*`. LSTM `input_size` unchanged → old checkpoints load.
- `ml/train/data/dataset.py` — `LazyMultiHorizonDataset` emits reserved `"__pair_idx"`.
- `ml/train/train_m2.py` — passes `pair_idx`, builds `pair_vocab`, saves
  `pair_embed_dim` + `pair_vocab` to checkpoint meta.
- `ml/train/eval_m2.py`, `ml/train/serve.py` — reconstruct the embed model, remap
  symbol→trained-vocab id (unknown → OOV).
- `scripts/gcp_train.sh` — added `PAIR_EMBED_DIM` to `FLUX_TRAIN_ENV_KEYS` (so the GPU
  run actually forwards it; this is what silently bit E2b).

Verified in Docker: OFF path byte-behavior unchanged; ON train→eval→serve round-trips;
unseen pair routes to OOV without crashing; an OLD (no-vocab) checkpoint still loads.

### 🎯 E-ROUND-2 LADDER — launch these (one change per run, highest-EV first)

Baseline to beat: **R6** 30m cov0.05 lb **0.547** / cov0.01 lb .551; E2a cov0.01 lb
**0.624**. Verdict metric unchanged: **30m Wilson-LB edge at the served gate + net P&L
at 14bps**, holding across WF folds, not headline dir_acc.

- [ ] **E2a′ — reseed the HYPE-drop (confirm, no code). ⬅️ START HERE.** Cheapest
  decisive test: does E2a's cov0.01 lb ≈ 0.62 replicate on a fresh seed?
  ```sh
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,ZECUSDT,1000PEPEUSDT \
    ./scripts/gcp_train.sh --gpu 60 128
  ```
- [ ] **E2c — majors-only (drop the 3 worst ungated pairs: HYPE .389 / WLD .392 /
  ZEC .391). No code.** Tests the pooling-averaging hypothesis harder than E2a.
  ```sh
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT ./scripts/gcp_train.sh --gpu 60 128
  ```
- [ ] **E2b′ — pair embedding, FOR REAL (code now exists).** The intended E2b. Keep
  the full 8-pair set so the embedding has all identities to specialize on:
  ```sh
  PAIR_EMBED_DIM=8 \
    TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
    ./scripts/gcp_train.sh --gpu 60 128
  #  VERIFY IN LOG (or it silently no-op'd again):
  #    "Pair embedding: ON dim=8 n_pairs=8 (+1 OOV bucket)"
  #    and the remote FLUX_TRAIN_ENV_KEYS echo lists PAIR_EMBED_DIM=8.
  ```
  Decision: if E2b′ ≥ E2a/E2c on cov0.05–0.10 lb AND holds across WF folds, prefer it
  (keeps all pairs tradeable). If a curated whitelist (E2a/E2c) wins instead, the fix is
  simply the served `WHITELIST_PAIRS`, no model change.
- [ ] **E-gate — higher serve gate as the DEFAULT (cheap, addresses "cost is the
  ceiling").** All edge lives in the ≥0.55 tail; the 0.4 serve gate over-trades. Re-eval
  the current best checkpoint at gate 0.55/0.58 and, if net-positive there, propose
  raising `GATE_THRESHOLD` / `ML_GATE_THRESHOLD` in `docker-compose.yml`. Eval-only:
  ```sh
  GATE_THRESHOLD=0.58 docker compose --profile ml run --rm ml_trainer \
    python eval_m2.py --checkpoint /models/m2_multi.pt
  ```
- [ ] **E-book240 — is E1a's 240m book-era collapse a stale-book artifact?** Before
  giving up on longer horizons, tighten staleness caps and re-run the book ON/OFF
  ablation / walk-forward at 240m (`gcp_ablate.sh` / `gcp_walkforward.sh` with
  `TRAIN_HORIZONS=30,60,240 TRAIN_PRIMARY=240` and lower `BOOK_MAX_AGE_MIN`). Low
  priority; only if E2* stalls.

Then E3 (triple-barrier) / E4 (GBT baseline) remain queued below as the "if per-pair
conditioning also fails" fork. **Do NOT promote any E1/E2 checkpoint.**

### 📌 ORDER OF OPERATIONS (round 2)
1. Launch **E2a′** and **E2c** (both no-code) and **E2b′** (code ready). They're
   independent → fine to run concurrently on separate throwaway VMs.
2. Fetch each with `./scripts/gcp_logs.sh <run_id> --save` → `logs/E2a2.log`,
   `logs/E2c.log`, `logs/E2b2.log`. **First grep each log for the config echo** to
   confirm pairs / `PAIR_EMBED_DIM` actually took effect (the E2b lesson).
3. Bring results back in a **fresh session**; update the RESULTS TABLE and pick the
   winner by the verdict metric.
4. The order-book walk-forward (data-gated, older section) still runs on its own track.

---

## ▶️▶️ START HERE (2026-08-12) — PARALLEL CANDLE-ONLY TRACK (run these NOW)

**Read this before the older "START HERE (2026-08-11)" section below.** That section
is still correct — the order-book walk-forward is data-gated and we keep collecting —
but it is NO LONGER the only thing we do while we wait. This session reframed the
project: **order-book data is not our only remaining hope, and it was never
evidence-ranked as the highest-EV lever** — it's just the one with a clean pending
experiment. The R0–R6 failure mode ("edge lives in `pre_book`, decays in the newest
window; the model is right but doesn't clear 14bps at 30-bar holds; the 3-class head
is near-useless and the shared LSTM averages incompatible per-pair regimes") points at
several **genuinely-untried, candle-only levers that need NO new data** (candles
backfill to ~400d). We run those in parallel with the book-history wait.

### Why these are worth running (diagnosis, one line each)
- The killer is **cost**, and cost **amortizes with horizon** — yet 4h/1d were NEVER
  run (only 5m/30m/60m). `hold_bars` is derived from the horizon (`eval_m2.py:595`),
  so a longer horizon automatically holds longer and clears 14bps more easily. This is
  config-only and the single highest-EV untried idea.
- The model is **one shared LSTM with NO per-pair embedding and NO cross-pair
  features** (`multi_horizon.py` — `pair_ids` are used only for eval splits/norm, never
  fed to the encoder). Per-pair base rates differ wildly (BTC ~0.64 vs HYPE ~0.38, HYPE
  *negative* edge). Pooling forces the encoder to average incompatible regimes.
- Labels are naive fixed-Δt forward-return sign. `MODEL.md` §4.3 *recommends*
  **triple-barrier** labeling (TP/SL/timeout) and it was never implemented — the
  standard fix for "right but not tradeable."
- We've only ever tried **LSTM**. A GBT (LightGBM/XGBoost) baseline on windowed
  features tells us fast whether we're **signal-limited or model-limited**.

### 🎯 EXPERIMENT LADDER — one change per run, highest-EV first

Baselines to beat (from `logs/`): R0 = `20260806T044341Z` / `09f2d771`
(30m dir_acc@cov0.05 lb 0.542); R6 best-of-batch 30m book-lb 0.559. **Verdict metric
for every arm below: 30m-equivalent (or the arm's primary horizon) Wilson-LB edge at
the live gate row AND net P&L at 14bps round-trip — not headline dir_acc.**
Cross-check the same reading-guide lines as the older sections (side split, book-era
split, walk-forward win1-4). Save each run's log to `logs/<ARM>.log` and record the
result in the RESULTS TABLE below.

- [ ] **E1 — Longer horizons (4h, 1d). ⬅️ START HERE. Config-only, no code, no new
  data.** Directly attacks the cost problem. Two arms (separate runs):
  ```sh
  # E1a — 4h primary (240m). Flat threshold 0.6% already set (config.py:70).
  TRAIN_HORIZONS=30,60,240 TRAIN_PRIMARY=240 ./scripts/gcp_train.sh --gpu 60 128
  #   Verify in log: "=== resolved knobs: … PRIMARY=240 …" and header "primary=240".

  # E1b — 1d primary (1440m). Flat threshold 1.5% added this session (config.py:71).
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=1440 ./scripts/gcp_train.sh --gpu 60 128
  #   Verify: header "primary=1440". NOTE 1d labels are sparse on ~400d history →
  #   watch n_dir at cov0.05; if <500 (MIN_GATED_FOR_CKPT) selection is untrustworthy.
  ```
  **Decision rule:** if a longer horizon shows Wilson-LB edge that **clears 14bps net**
  at its (longer) hold where 30m did not → cost was the ceiling → make that horizon the
  product and move to E-follow-ups on it. If still net-negative → cost isn't the only
  problem → E2/E3 matter more.

- [ ] **E2 — Per-pair conditioning (needs a small code change; see TASK E2 below).**
  Add a learned pair embedding to the encoder input so one model can specialize per
  pair instead of averaging BTC and HYPE. Cheapest first sub-step is FREE and needs no
  code:
  ```sh
  # E2a — drop the known-negative-edge pair(s) from training (no code). If this alone
  #        lifts the pooled edge, it confirms the pooling-averaging hypothesis.
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,ZECUSDT,1000PEPEUSDT \
    ./scripts/gcp_train.sh --gpu 60 128      # (drops HYPEUSDT)
  # E2b — pair embedding (AFTER implementing TASK E2). One env flag once wired:
  #   PAIR_EMBED_DIM=8 ./scripts/gcp_train.sh --gpu 60 128
  ```

- [ ] **E3 — Triple-barrier labels (needs code; see TASK E3 below).** Label tradeable
  TP/SL/timeout events instead of fixed-Δt sign. Standard fix for cost survival. Gate
  behind E1/E2 unless they both fail, since it's the biggest code change.

- [ ] **E4 — GBT sanity baseline (needs a small standalone script; see TASK E4).**
  LightGBM on flattened windowed features. Not a production path — a **diagnostic**:
  if a GBT with the same features/labels also can't clear cost, we're signal-limited
  (→ data/features, incl. the order book), not model-limited (→ architecture).

- [ ] **E5 — Cross-pair / regime features (free from candles; feature run).** Trailing
  1h/4h/1d returns, longer rolling vol, BTC-beta. `FEATURE_DIM` bump → checkpoint/serve
  change; do as its own attributable run only after E1-E4 triage. (Flagged in
  `docs/DATA_COLLECTION_AUDIT.md` as "fully retroactive, zero collection lead time.")

### 📌 ORDER OF OPERATIONS (what to actually do)
1. **Launch E1a now** (`./scripts/gcp_train.sh --gpu` line above), then `E1b`.
   These need nothing new. Poll `./scripts/gcp_status.sh`; fetch with
   `./scripts/gcp_logs.sh <run_id> --save` → `logs/E1a.log` / `logs/E1b.log`.
2. Bring results back **in a new session** (token hygiene) and paste the log path +
   which arm. Next session reads the RESULTS TABLE + reading-guide lines and decides
   E2 vs E3 vs stop.
3. The order-book walk-forward (older section) stays queued and runs on its own
   throwaway VM when book history ≥30d — **it does not block E1-E5 and E1-E5 do not
   block it.** They are independent tracks.

### 🧾 RESULTS TABLE (fill in as runs return — this is the session-to-session memory)

| Arm | Run ID / sha | Primary | dir_acc@cov0.05 (lb) | net P&L @14bps (best gate) | Verdict |
|-----|--------------|--------:|----------------------|----------------------------|---------|
| E1a 4h | `20260812T042319Z` / `e603b3d5` | 240 | 0.538 (0.533)* | all neg (best −1.66 @0.55) | **Reject.** 240m head WEAKER than 30m; its edge is in `pre_book` (lb .536) and **collapses in book era (lb .460)**. *fixed-cov table is for the 240m PRIMARY, not the served 30m. |
| E1b 1d | `20260812T072224Z` / `736f26c6` | 1440 | 0.527 (0.523)* | ~flat (−0.47 long @0.4) | **Reject.** Unstable: WF fold-3 lb **0.390** (< coin flip) vs fold-2 .590. Momentum baseline (cov0.02 .603) ≈ model → 1d head just relearns trailing-return momentum. |
| E2a drop-HYPE | `20260812T123234Z` / `5e6db5b9` | 30 | 0.557 (**0.552**) | all neg (−1.66 @0.55) | **Promising, needs reseed.** cov0.01 lb **0.624** (vs R6 .551), ≥ baseline through cov0.10. HYPE (worst ungated .389) polluted the pooled encoder. Small n_dir at cov0.01 + soft WF fold-4 (.539) → confirm with a seed. |
| E2b pair-embed (INVALID) | `20260812T164805Z` / `5e6db5b9` | 30 | 0.553 (0.549) | all neg (−7.33 @0.55) | **INVALID — no-op run.** `PAIR_EMBED_DIM` was never read by the code (no embedding existed), so this was a reseed of R6. Reran for real as E2b′ below. |
| E2a′ 7-pair reseed | `logs/E2a1.log` | 30 | 0.572 (**0.568**) | all neg | Reproduces E2a (~.003) → drop-HYPE edge is real, not seed noise. WF folds .590/.553/.568/**.542** — front-loads early, decays by newest fold. |
| E2c majors-only 4-pair | `logs/E2c.log` | 30 | 0.566 (0.559) | all neg | **Weakest — REJECT.** Fewer pairs hurt; newest WF fold .512 (≈coin flip in book era). More pairs > fewer. |
| **E2b′ pair-embed dim=8** | `20260813T114311Z` / `a26b032b` (`logs/E2b.log`) | 30 | 0.569 (**0.566**) | all neg (−8.97 @0.55) | **✅ WINNER — PROMOTE.** Tightest WF spread (.568/.572/.560/**.548**); pair-embed flattened edge across time (generalizing). All 8 pairs tradeable. Chosen on WF stability, not headline acc. Still net-neg → cost is the ceiling (see E-gate/cost + E4). |
| E3a more-pairs (12, embed OFF) | `20260814T144713Z` (`logs/E3a.log`) | 30 | **VOID** | — | **Log truncated at eval start** + `PAIR_EMBED_DIM` omitted (embed OFF, not dim=8 as planned). Re-run cleanly if 12-pair Q still matters. |
| E3b1 pair-embed dim=4 | `logs/E3b1.log` | 30 | 0.559 | all neg | **Reject.** Lowest peak; newest/book-era WF fold .533 (worst). WF folds .554/.578/.582/.533. Under-specialized. |
| E3b2 pair-embed dim=16 | `logs/E3b2.log` | 30 | 0.554 | all neg | **Marginal.** Best book-era WF stability (flattest spread .017, newest fold **.562**) but lower headline. Not worth churn vs E2b (~1 LB pt, both non-promotable). WF .549/.566/.553/.562. |
| E-gate/cost eval (E2b live) | `logs/eval_m2_E2b1/2/3.json` | 30 | tail-30d 0.477 (**0.454**) | all neg; **no cost-viable gate** | **ANSWERED — do not raise gate.** Gates .35–.50 identical (no conf spread); .55 → cov4% & LB .448 (<coinflip); .60 → zero cov. Recent-era edge ≈0. |
| E4 calibration | — | 30 | — | — | **CANCELLED — wrong diagnosis.** Dir head has NO label smoothing already; it's calibrated to ~0 signal (Brier .2505), not under-confident. Sharpening would worsen P&L. |
| E3 triple-barrier | _coded, not run_ (`LABEL_MODE=triple_barrier`) | tbd | | | |
| E4 GBT baseline | _coded, not run_ (`gbt_baseline.py`) | 30 | | | |

### 🔧 CODE TASKS (implement when its arm comes up — NOT all now)

- **TASK E2 — pair embedding ✅ IMPLEMENTED (2026-08-13, code only, NOT committed).**
  `nn.Embedding(n_pairs+1, PAIR_EMBED_DIM)` in `SharedEncoderMultiHead` (row `n_pairs`
  = OOV/unknown-pair bucket); the per-pair vector is concatenated to the **pooled**
  encoder state before the heads (LSTM `input_size` unchanged → old checkpoints load
  untouched). `pair_idx` threads through the dataset batch (`dataset.py` emits reserved
  `"__pair_idx"` key), the train + val loops, `eval_m2.py`, and `serve.py`. New config
  `PAIR_EMBED_DIM=0` (0 = off = byte-identical legacy). Checkpoint meta stores
  `pair_embed_dim` + ordered `pair_vocab`; `eval_m2.py` remaps eval-bundle series →
  trained-vocab id (unknown → OOV), `serve.py` maps the served symbol → id (unknown →
  OOV). Verified: OFF path unchanged, ON train→eval→serve round-trips, unseen pair →
  OOV without crash, and an OLD (no-vocab) checkpoint still loads. **Still TODO before
  the GPU run:** add `PAIR_EMBED_DIM` to `FLUX_TRAIN_ENV_KEYS` in `scripts/gcp_train.sh`
  (see the E2b′ command below — must confirm the env is forwarded to the VM).
- **TASK E3 — triple-barrier labels (~half day).** New labeler in
  `ml/train/data/features.py`: for each bar, walk forward to the horizon; label UP if
  +vol-scaled TP hit first, DOWN if -SL first, FLAT if timeout. Gate behind a config
  flag `LABEL_MODE=triple_barrier|fixed` (default `fixed` preserves current). Keep the
  raw fwd-return for the quantile head. Update `make_labels*` callers in `dataset.py`.
- **TASK E4 — GBT baseline (~2–3h, standalone).** New `ml/train/gbt_baseline.py`:
  reuse `build_feature_frame` + `make_labels`, flatten the last `SEQ_LEN` bars (or a
  small summary set) per sample, train LightGBM, run the SAME `gate.py` fixed-coverage
  + `eval_m2.simulate_pnl` reporting so numbers are comparable to the LSTM. Add
  `lightgbm` to `requirements.txt`. Diagnostic only — do not wire into serve.

### ⚙️ Enabling change already made this session
- `ml/train/config.py`: added `FLAT_THRESHOLD_PER_HORIZON[1440] = 0.015` (1d flat band;
  env `FLAT_TH_1D`) so the E1b 1d arm labels correctly instead of falling back to the
  0.2% default. **NOT committed** (commit-only-when-asked). No other code changed.

---

## ▶️ START HERE (2026-08-11) — WAITING ON DATA; nothing to launch now

**R0–R6 are all DONE and analyzed. The tuning ladder is exhausted — no arm produced
a cost-surviving edge. We are now blocked on book-history quantity for the ONE
remaining decisive test (Step A walk-forward). Do NOT launch more tuning arms.**

### What R4–R6 showed (2026-08-11; logs/R4.log, R4.1.log, R5.log, R6.log)

Harness fixes from TASK 3 worked: all four runs show the intended env in
`=== resolved knobs …` (no more R3-style silent drops).

| Run | Arm | Primary | 30m book lb / pre_book lb | WF win-4 lb | Best P&L | Verdict |
|-----|-----|--------:|---------------------------|------------:|---------:|---------|
| R4 | 60m horizon | 60m | 0.495 / 0.512 | 0.486 | all neg | **60m has ~0 OOS edge** (lb 0.497 @cov0.05); kills the "go longer horizon" thesis — the old "60m +0.060" was the void-R3/candle artifact |
| R4.1 | 5m horizon | 5m | 0.487 / 0.524 | — | −556 | **5m useless**; turnover annihilates it |
| R5 | cost-aware sel | 30m | 0.540 / 0.574 | 0.555 | −3.1 @0.55 | `net_sc` term now alive (0.19–0.28, tracks net/trade) but every epoch still net-neg; **one-mode** (down side n=0) |
| **R6** | label rebalance | 30m | **0.559 / 0.565** | **0.551** | −3.1 @0.55 | **best of batch**: first run where book-era lb ≈ pre_book (no collapse), **two-sided** (up 0.567 / down 0.551), WF flat+positive across all 4 folds (.568/.572/.558/.551) |

**The one new signal is R6's non-collapsing, two-sided, walk-forward-stable book
edge** — the profile the whole plan has been waiting to see. **BUT** three caveats
stop it being a real win:
1. **It's probably not the rebalance.** R6's `inv_freq clip=4.0` produced
   near-identity class weights (down=1.02/flat=0.96/up=1.02 — the classes are already
   near-balanced, so the knob was a near-no-op). So R6 ≈ R5 recipe; the book-lb lift
   is more likely **run variance + the much larger val window** (R5/R6 val = Feb→Aug,
   ~2.0M samples, vs the ~18-day book sliver in R0–R3) than the label change. The old
   book-collapse may have been partly a small-sample artifact the staleness fix +
   bigger window washed out. **This is a hypothesis, not a confirmed edge.**
2. **Still loses money.** Every gate is net-negative; only gate 0.55 @1.5% coverage
   is non-catastrophic (−3.1). A ~+7% hit-rate edge at cov0.05 still doesn't clear
   14bps at 30-bar holds. **Do NOT promote R6.**
3. It's a global-time split (one split), not the disjoint-fold walk-forward that the
   verdict rule requires.

**Conclusion:** tuning (horizon R4/R4.1, cost-selection R5, rebalance R6) has reported
"no edge to tune." The only thing left that can move the needle is whether a real
book/microstructure edge exists — and R6 gives the first *weak positive* on it. That
must be confirmed by Step A (disjoint-fold walk-forward), which is **data-gated**.

### 🔴 WHY WE'RE WAITING (data-collection check, 2026-08-11)

Ran `scripts/gcp_data_collection_stats.sh`. Scalar order book history
(`orderbook_snapshots`, what training consumes) by pair:

| Pair(s) | book history (2026-08-11) | hits 30d ≈ |
|---------|---------------------------|-----------|
| BTC / ETH / SOL | **24d 20h** (from 2026-07-17) | **2026-08-16** |
| DOGE / WLD / HYPE | ~21d 14h (from 2026-07-21) | ~2026-08-20 |
| ZEC | 17d 12h (from 2026-07-25) | ~2026-08-24 |
| 1000PEPE | 15d 11h (from 2026-07-27) | ~2026-08-26 |

- **The ≥30d-per-traded-pair gate is NOT met yet.** Even the 4 longest pairs
  (`WF_LONG_PAIRS_ONLY=1` = BTC/ETH/SOL/DOGE) are only ~22–25d. With `--require-book`
  each of the 6 folds would carve a tiny dense-book val slice → exactly the
  "one lucky ~3d window" fluke that voided the 2026-08-04 walk-forward. Running today
  would re-measure noise, not answer the question.
- All feeds are **fresh** (book/trade staleness <10s, funding/OI <1m) — no new outage.
- **Separate note — raw L2 ladder** (`orderbook_levels`, the high-fidelity feed that
  fixes the lossy 11-scalar compression) started 2026-08-05, so only **~6.5d** exists
  and it is NOT yet a training input. This is the *future* high-value data (Step B+),
  accumulating ~1d/day; it is not on the critical path for Step A.

### ✅ WHAT WE DO NEXT AND WHEN (decision layer)

1. **NOW → ~2026-08-16: do nothing / keep collecting.** No tuning arms (they're
   exhausted). Let book history cross 30d. Optional cheap sanity only: re-run
   `scripts/gcp_data_collection_stats.sh` to watch the earliest `first_snapshot` age.
2. **~2026-08-16 (majors ≥30d): first walk-forward attempt, long-pairs-only.** BTC/
   ETH/SOL/DOGE cross 30d first; run the diagnostic restricted to them for a sharp,
   dense-book read without the noisier short-history pairs dragging folds:
   ```sh
   WF_LONG_PAIRS_ONLY=1 WF_DROPOUT=0.4 WF_WEIGHT_DECAY=1e-3 WF_HIDDEN=48 \
     ./scripts/gcp_walkforward.sh
   ./scripts/gcp_walkforward.sh --fetch
   ```
3. **~2026-08-26 (all 8 pairs ≥30d): full walk-forward** (the plan's canonical Step A):
   ```sh
   WF_DROPOUT=0.4 WF_WEIGHT_DECAY=1e-3 WF_HIDDEN=48 ./scripts/gcp_walkforward.sh
   ./scripts/gcp_walkforward.sh --fetch
   ```
   **VERDICT RULE (unchanged):** book-ON − book-OFF Wilson-LB gap > ~0.05 on **ALL**
   folds → book edge robust → go to Step B. If ANY fold's gap ≤0 or LBs overlap →
   **STOP tuning, keep collecting, re-check at ~60d.** R6's global-split result makes
   a pass *plausible* but not likely — treat it as a genuine test, not a formality.
4. **Only if Step A passes → Step B / Step C** as below.

**Why not just promote R6 and trade it now?** It's net-negative at every gate; serving
it changes nothing tradeable and would only add cost/turnover. Promotion waits for a
checkpoint that clears cost in the walk-forward.

### 📅 AFTER END OF AUGUST (≥30d book history) — the microdata ladder

Plan agreed 2026-08-09: do R4–R6, report back, then wait for ~30d of book data
(~2026-08-25) before the data-dependent steps below. Run these IN ORDER; each
gates the next. Mechanics/commands live in the pinned "⏰ ACTION QUEUED —
WALK-FORWARD RE-RUN" section (~line 596) and "Microstructure readiness roadmap"
(~line 730) — this is the up-to-date decision layer over them.

1. **Step A — Walk-forward diagnostic (the gate for everything).** When earliest
   `first_snapshot` ≥ 30d old (check `scripts/gcp_data_collection_stats.sh`):
   ```sh
   WF_DROPOUT=0.4 WF_WEIGHT_DECAY=1e-3 WF_HIDDEN=48 ./scripts/gcp_walkforward.sh
   ./scripts/gcp_walkforward.sh --fetch
   ```
   **VERDICT RULE:** book-ON − book-OFF Wilson-LB gap > ~0.05 on **ALL** folds →
   the book edge is robust → go to Step B. If ANY fold's gap ≤0 or LBs overlap →
   **STOP tuning, keep collecting, re-check at ~60d.** Do NOT over-invest.
   - Updated context from R0–R3 (2026-08-09): the staleness fix did NOT lift the
     book-era edge toward pre_book in the global-split eval (book lb stayed ~0.48–
     0.53, recent walk-forward window 4 weakest). So the prior "edge is real, just
     needs data" assumption is now IN DOUBT — Step A is a genuine test, not a
     formality. Expect it may fail the verdict rule; that's an acceptable answer.

2. **Step B — Microstructure-rich full run (ONLY if Step A passes).** At ~60–90d
   book history, retrain on the window where microstructure is dense (not zero-
   filled) and compare against the candle-only baseline. This is the first run where
   the book features can actually carry signal. One change per run still applies.
   Watch the same book-era / walk-forward-window-4 overfit checks.

3. **Step C — Reassess RL (M3) — ONLY after Step B shows a tradeable, cost-surviving
   edge.** No point building the policy layer on a model with ~0 net edge. If Steps
   A/B keep failing, the honest conclusion is the candle+book feature set is not
   enough and the next move is feature/data work (see `docs/DATA_COLLECTION_AUDIT.md`:
   full-fidelity order book, long/short & taker ratios, liquidations vendor), NOT
   more model tuning.

**One-line summary of the whole plan:** R4–R6 now → wait → Step A walk-forward
(pass/fail gate) → Step B microstructure run (only if A passes) → Step C RL (only if
B is tradeable). Each arrow is a real stop/go decision, not a formality.

---

## 🧭 TASK 3 — R0–R3 RESULTS ANALYSIS + HARNESS FIXES (2026-08-09) — READ FIRST

This is the newest section. It supersedes TASK 2's "just launch R0–R3" plan: R0–R3
were run (`logs/R0.log … R3.log`) and analyzed. **None produced a cost-surviving
edge; two collapsed; two experiments were void/no-ops.** Below is the read, the
fixes made this session (code, NOT committed, no run launched), and the next plan.

### What the five runs showed (all eval on primary 30m unless noted)

| Run | Env | Best sel_score | eval dir_acc@cov0.05 (lb) | Verdict |
|-----|-----|---------------:|--------------------------:|---------|
| R0 baseline | `--gpu 60 128` | 0.542 (ep5) | 0.549 (0.542) | Best of batch; still net-negative P&L at 14bps every gate |
| R1 cost-aware | `SEL_NET_WEIGHT=0.5 SEL_COST_BPS=14` | 0.269 | 0.529 (0.522) | **cost term was a dead no-op** (`net_sc=0.000` every epoch) |
| R2 capacity | `NUM_LAYERS=3 HIDDEN_SIZE=128` | 0.518 | 0.496 (0.491) | **mode-collapsed to all-flat** (val_acc frozen 0.417/0.425/0.445) |
| R2.1 cap+seq | `NUM_LAYERS=4 HIDDEN_SIZE=128 … 256` | 0.518 | 0.517 (0.509) | **same collapse**; only aux dir-head produced spread |
| R3 "prim 60" | `TRAIN_PRIMARY=60` | 0.519 | 0.559 (30m) | **VOID — trained primary=30m** (env never took effect); ≈R0 replica |

### Root findings (priority order)

1. **R3 never tested 60m.** Its log header says `primary=30`. The "longer-horizon"
   experiment did not happen; R3 just reproduced R0 (reassuring: 30m dir_acc
   0.549→0.559). Cause: `TRAIN_PRIMARY=60` did not reach `train_m2.py --primary`
   (the header would have said 60). **Fixed** below.
2. **Cost-aware selection (R1) is broken by design at this signal level.** Old
   `net_score = clip(0.5 + net_per_trade/scale, 0, 1)`; since NO model clears 14bps
   at cov0.05, `net_per_trade≈-14bps` every epoch → clip pins `net_score=0.000` all
   run. So `sel = 0.5*edge_lb + 0.5*0` — you didn't add a P&L signal, you halved and
   de-noised the edge score (why R1 sel_score fell to ~0.25 and selection wandered).
   **Fixed** below (smooth logistic, monotonic in the negative region).
3. **R2/R2.1 capacity increase caused mode collapse, not learning.** `val_acc` pinned
   at the base rate `[0.417,0.425,0.445]` for the whole run = 3-class argmax always
   predicts flat. Bigger GRU + the too-gentle `sqrt_inv_freq clip=2.0` weights
   (down=1.04/flat=0.89/up=1.06 — almost no pressure) let CE be minimized by dumping
   everything in the 39–41% flat majority. Confusion matrices confirm whole zero
   columns. Adding capacity to a collapsing recipe is wasted compute. **Collapse-guard
   logging added** below so this is visible at epoch 1, not at eval.
4. **The 3-class head is near-useless everywhere; the directional aux head carries
   all the signal.** Even R0's 30m confusion matrix never predicts "up" (zero column).
   Ungated 3-class acc 0.45–0.46. The tradeable product is the directional-head gate.
5. **Whatever edge exists lives in `pre_book` and decays in the newest window.** Every
   run: `pre_book` lb ~0.52–0.55 vs `book` era ~0.48–0.53, and walk-forward window 4
   (newest, only one with real book coverage) is consistently weakest (R0 .537 → R3
   .480). The staleness fix (TASK 1) did NOT lift book-era edge to pre_book levels.
   This is the crux: **the edge is strongest exactly where we have least book data /
   won't trade.** Strong hint the "edge" is partly memorized regime, not microstructure.
6. **Selection is noisy.** sel_score bounces epoch-to-epoch on ~10–20k directional
   samples with lb≈0.50; the "best" checkpoint is often a lucky epoch.

### Honest conclusion

At 30m on this feature set, out-of-sample book-era directional edge is ~0 after the
staleness fix, and every P&L sim is deeply negative at 14bps. **Chasing capacity /
cost-selection / horizon before confirming a real, out-of-sample, book-era edge is
premature.** The gating question for everything downstream is: *does ANY cost-
surviving edge exist in the regime we'll actually trade?* So far: probably not, or
barely.

### Fixes made this session (2026-08-09) — code only, NOT committed, NO run launched

All verified with `py_compile` (via `python:3.11-slim` container — no ml_trainer
image locally) and `bash -n`; net_score mapping spot-checked numerically.

- **P0a — fail-loud knob plumbing (`scripts/gcp_train.sh`, `ml/train/train_m2.py`).**
  The remote training log now echoes every resolved knob (`=== resolved knobs: …`
  + `knob K=v` lines) BEFORE training, so a silently-dropped env var (the R3
  `TRAIN_PRIMARY` failure) is visible in the log we keep. `train_m2.py` now prints a
  loud `WARNING` when the requested `--primary` is not in `--horizons` and it falls
  back (the silent fallback at `train_m2.py:313` is what voided R3). Added a comment
  block documenting that `TRAIN_PRIMARY/TRAIN_HORIZONS/TRAIN_PAIRS` are consumed on
  the launcher and forwarded as CLI flags (NOT via `FLUX_TRAIN_ENV_KEYS`).
  **Keep primary ∈ horizons or it falls back.**
- **P0b — smooth cost-aware `net_score` (`ml/train/train_m2.py:checkpoint_score`,
  `config.py`).** Replaced `clip(0.5+net/scale,0,1)` with
  `net_score = sigmoid(2*net_per_trade/SEL_NET_SCALE)`. Strictly monotonic across the
  whole negative region (net=-14bps→0.198, -12bps→0.232, 0→0.5, +20bps→0.881), so the
  less-unprofitable epoch always ranks higher even when all epochs lose to cost. This
  makes R1's arm actually do something. `SEL_NET_SCALE` default unchanged (0.002).
- **P1 — collapse-guard logging (`ml/train/train_m2.py`).** Every epoch line now ends
  with `3cls_pred[d=.. f=.. u=..] dir_pred_up=..`: the primary-horizon 3-class argmax
  prediction rates + the directional head's predicted-up rate. `f≈1.00` or `u≈0.00`
  is the R2 collapse signature; `dir_pred_up` tells us WHICH head collapsed (the
  3-class one collapsed in R2 while the dir head still spread). No behavior change.
- **P1 — label-rebalance is already env-tunable** (`CLS_WEIGHT_MODE`,
  `CLS_WEIGHT_CLIP`, `CLS_LABEL_SMOOTHING` ∈ `FLUX_TRAIN_ENV_KEYS`). Defaults left
  intact (they preserve the served-model recipe); rebalancing becomes an explicit
  launch arm (R6 below), not a silent default change.

File:line anchors (this branch): `train_m2.py` primary-fallback warning (~line 313);
`checkpoint_score` net_score logistic (~line 285); collapse-guard block (~line 572,
`cls_rate_str`); `gcp_train.sh` resolved-knobs echo (just before the `train_m2` run
line) + `TRAIN_PRIMARY` comment (~line 90). `math` now imported in `train_m2.py`.

### 🚀 NEXT LAUNCH PLAN (do these; ONE change per run; all print collapse-guard now)

**Priority is DIAGNOSIS, not tuning.** The first job answers whether a real edge
exists; only then do the tuning arms make sense.

```sh
# R4 — TRUE 60m horizon (redo the void R3). 60m amortizes 14bps better & showed the
#      best edge historically. primary MUST be in horizons.
TRAIN_PRIMARY=60 TRAIN_HORIZONS=5,30,60 ./scripts/gcp_train.sh --gpu 60 128
#   Verify in log: "=== resolved knobs: … PRIMARY=60 …" and header "primary=60".

# R5 — cost-aware selection, NOW that net_score actually ranks (redo R1).
SEL_NET_WEIGHT=0.5 SEL_COST_BPS=14 ./scripts/gcp_train.sh --gpu 60 128
#   Verify: per-epoch "net_sc=" is NO LONGER 0.000 every epoch and moves with net/trade.

# R6 — anti-collapse label rebalance (fixes the R2/R2.1 failure mode) THEN capacity.
#      Do the rebalance FIRST at baseline capacity to confirm it stops collapse:
CLS_WEIGHT_MODE=inv_freq CLS_WEIGHT_CLIP=4.0 CLS_LABEL_SMOOTHING=0.1 \
  ./scripts/gcp_train.sh --gpu 60 128
#   Verify: 3cls_pred[d/f/u] all well off 0/1 (no all-flat). If collapse is fixed,
#   ONLY THEN retry capacity WITH the rebalance:
# CLS_WEIGHT_MODE=inv_freq CLS_WEIGHT_CLIP=4.0 CLS_LABEL_SMOOTHING=0.1 \
#   NUM_LAYERS=3 HIDDEN_SIZE=128 ./scripts/gcp_train.sh --gpu 60 128
```

**The real gating experiment (P2 diagnostic — arguably do BEFORE R4–R6):** a clean
multi-fold walk-forward that reports mean±std of book-era vs pre_book lb and net/trade
at fixed coverage. Use the existing `gcp_walkforward.sh` (see the pinned WALK-FORWARD
section) once ≥30d book history exists (~2026-08-25). **Decision rule:** if book-era
lb is not >0.50 out-of-sample across ALL folds, stop tuning and keep collecting data —
capacity/horizon/cost-selection cannot manufacture an edge that isn't there.

### 📋 WHEN RESULTS COME BACK (fresh-session recovery — read these log lines)

For each run save `logs/<name>.log`, tell me the arm, and I'll read, in order:
1. `=== resolved knobs: …` + `knob …` → confirm the intended env ACTUALLY applied
   (this is how we catch the next R3-style silent drop).
2. Per-epoch `3cls_pred[d/f/u] dir_pred_up` → did it collapse? which head?
3. Per-epoch `net_sc=` (R5) → is the cost term alive (not 0.000) and ranking?
4. Eval `Fixed-coverage directional edge` 30m lb @cov0.05/0.10 vs R0 (0.542).
5. Eval `Book-era split` book vs pre_book lb → did anything lift the BOOK era?
6. Eval `Walk-forward` win1–4 lb, esp. **window 4** (recent) → stable or decaying?
7. Eval `Side split` + `Long/short P&L` → still one-sided?

Baselines to compare: R0 = `20260806T044341Z` / sha `09f2d771` (`logs/R0.log`);
older clean baseline `20260805T025536Z` / `6e6d358e` (`logs/latest_fixed.log`).

**State as of 2026-08-09:** P0/P1 fixes above are on a working branch, **NOT
committed, NO run launched** (commit-only-when-asked). Next action: commit, then
launch R4 (and/or the walk-forward diagnostic).

---

## 🔥 TASK 1 — DIAGNOSE THE BOOK-ERA EDGE COLLAPSE (current top priority, 2026-08-05)

**Why this is #1:** the quant A/B (`quant_ab_20260804T144531Z`, see
`docs/QUANT_AB_HANDOFF.md`) confirmed the real blocker is NOT the quantile head — it
is that the model's directional edge lives in the **pre_book** era and collapses to
≈0.49 (coin flip / negative) in the recent **book** era.

Evidence (quant_off arm, PRIMARY 30m, book-era split of fixed-cov 0.05 edge):
- pre_book: n=771,734  dir_acc=0.555  **lb=0.548**
- book:     n=165,600  dir_acc=0.508  **lb=0.491**  ← negative edge

The edge (~+0.03–0.04) is real but tiny and exists only where we do NOT need it (old
regime). The recent book era — the regime we'll actually trade — is where it fails.
This is a distribution-shift / feature-quality problem, **not** a capacity problem
(the model early-stops at epoch 11–12, train/val loss move together, val_acc barely
off base rate → no underfitting; bigger model would just overfit the small book era).

**Hypothesis to test first — stale/misaligned microstructure in the recent era.**
The asof joins in `ml/train/data/features.py` forward-fill the last known book/trade
snapshot (`book.reindex(feat.index, method="ffill")`, ~`features.py:96`; trades
~`:120`). The `has_book`/`has_trades`/`has_funding_oi` masks only flag **absence**,
not **staleness** — a book snapshot that is hours old still reads `has_book==1` and
gets forward-filled into every bar. If recent book data is sparser or more bursty
than assumed, the model trained mostly on pre_book is fed stale features off its
training distribution in the book era.

**Diagnosis steps (read-only, no training — all in the ml_trainer container):**
1. **Book/trade freshness distribution, pre_book vs book era.** For each pair,
   compute the age (bar_time − last_snapshot_time) that the asof-ffill introduces,
   and its distribution in each era. A large right tail in the book era confirms
   staleness. (Add a temporary freshness column alongside the existing ffill, or a
   standalone query script — do NOT change the served feature path yet.)
2. **Feature distribution drift pre_book vs book** for the book features
   (`data.features.BOOK_FEATURES`): mean/std/quantiles per era per pair. Large shifts
   (esp. `spread_bps`, the one STABLE+DIRECTIONAL feature from the audit) explain
   off-distribution behavior.
3. **Per-pair book-era edge** (already in eval output — cross-read which pairs drive
   the collapse; alts with the shortest book history are the prime suspects).
4. **Confirm no leakage/label issue in the book era** (flat-rate, forward-return
   distribution per era) so we're not chasing a label artifact.

**Decision rule:**
- If book-era features are demonstrably stale/misaligned → fix is FEATURE work
  (staleness/age features so the model can discount stale book; possibly a max-age
  cutoff that reverts to mask=0). This is the high-leverage path; do it before any
  model/architecture change.
- If features are clean but the *distribution* simply shifted → it's a data-quantity
  / regime problem (dovetails with the queued walk-forward re-run at ≥~30d book
  history) → keep collecting; do not over-invest in the model.
- Only if features are clean AND enough book history exists AND edge still collapses
  → then (and only then) consider a modest architecture change (temporal CNN / small
  transformer + per-pair embeddings). No evidence yet that LSTM capacity is the
  bottleneck, so this is explicitly deferred.

**Explicitly NOT doing now (from this planning session):**
- More candle history (400d→more): low value — adds more of the pre_book regime we
  already have edge in; model isn't data-hungry (early-stops). Skip.
- Bigger model (more layers/hidden): negative EV — no underfitting; overfits the
  small book window (see the walk-forward overfitting note above). Don't.
- Full architecture swap: premature — gated on Task 1 showing capacity is the ceiling.
- More pairs: modest, *robustness* value only; do it alongside the Task-1 fix, not as
  a fix by itself.
- Quantile head: keep OFF; defer to RL via a **detached** head — see
  `docs/QUANT_AB_HANDOFF.md` "Quantile head for the future RL policy".

**Also fix (housekeeping):** `scripts/quant_ab.sh` zone-resolution bug that skipped
the w0.5 arm (VM in `us-central1-c`, launcher looked elsewhere → 404). Needed before
any future multi-arm run.

### ✅ TASK 1 DIAGNOSIS DONE (2026-08-05) — ROOT CAUSE FOUND: stale-ffilled book data

Ran read-only queries against the local Postgres (which holds the real book data,
565k snapshots 2026-07-17→08-04, matching the training dump). Findings:

1. **Normal book cadence is healthy** — snapshots every ~7–16s (p50 7.3s, p95 16s),
   comfortably sub-1m-bar for all 8 pairs.
2. **BUT there is a ~6.4-DAY book-collection OUTAGE: 2026-07-29 03:29 → 08-04 14:03**,
   on ALL 8 pairs, and on ALL THREE feeds (orderbook, market_trades, open_interest —
   identical max gap 9274 min). Plus a ~12.3h outage on 07-20 and a few ~30–37min
   ones. This is a collector outage, not a query artifact.
3. **The ffill has no age cap** (`features.py:96,120,142,153` use
   `reindex(method="ffill")`), so during the outage a SINGLE frozen snapshot is
   forward-filled across ~6 days of 1m bars — and every one of those bars still reads
   **`has_book=1`**. The masks flag absence, never staleness, so the model cannot
   tell fresh book from 6-day-old book.
4. **Distribution proof (BTC, book era):** bucketing book-era bars by ffill age —
   fresh(≤2m) `spread_bps` sd=0.011, imbalance mean +0.027; **stale(>1h)
   `spread_bps` sd=0.000, imbalance mean +0.367** (a frozen, extreme, non-
   representative snapshot). Off-distribution garbage stamped as present.
5. **Scale:** the 6.4d outage alone poisons **13,232** of the eval's **165,600**
   book-era bars; on recent-30d BTC ~**9.2%** of bars are >1h-stale and only ~62% are
   truly fresh (≤2m). This overlaps exactly the val "book era" and walk-forward
   window 4 where the 30m edge collapsed to lb≈0.49.

**Conclusion:** the book-era edge collapse is **primarily a data-quality (stale
ffill) artifact, not a model-capacity or a pure-regime-shift problem.** The model was
trained/evaluated on book features that are frozen-stale for a large, mislabeled-as-
present fraction of the recent window. This fully explains why more layers / more
candle history would not help, and why the quantile head was never the issue.

**Recommended fixes (feature work — do before any model/arch change), in order:**
1. **Add a book-staleness cap + age feature.** ✅ **DONE (2026-08-05).** See "STALENESS
   CAP IMPLEMENTED" below.
2. **Re-run the quant_off baseline** with the staleness fix and re-check the
   **book-era split** — success = book-era 30m wilson_lb rises toward the pre_book
   ~0.548 (or at least stops being negative). This is the direct verification.
   **← NEXT ACTION.** Launch: `./scripts/gcp_train.sh --gpu 60 128` (quant off is
   the default); then `grep -nE 'Book-era|PRIMARY|cov0.05|Walk-forward' logs/<run>.log`.
3. **Fix the collector outage root cause** so future data doesn't have multi-day
   holes (separate infra task; see collector `apps/fluxtrader/**`). NB: the
   2026-07-29→08-04 hole was a FULL collection outage — **candles too** had an
   8776-min gap (BTC candles resume 08-04 05:44; book only 14:03), so ~500 bars/pair
   had candles-but-stale-book. Until the collector is hardened, the staleness cap
   makes training robust to holes regardless.

### STALENESS CAP IMPLEMENTED (2026-08-05) — scope: cap only, FEATURE_DIM unchanged (19)

Chosen scope (per user): **cap only, no new `book_age` column** — non-breaking, no
checkpoint/serve/model-input changes. (A continuous age feature can be added later as
its own dim-bumping run if wanted.)

- `ml/train/config.py`: new caps `BOOK_MAX_AGE_MIN=5`, `TRADES_MAX_AGE_MIN=5`,
  `FUNDING_OI_MAX_AGE_MIN=480` (8h — funding/OI are legitimately low-frequency; do
  NOT apply the book cap to them). `0` disables a cap (legacy unbounded ffill).
- `ml/train/data/features.py`:
  - `_align_with_age(src, grid)` — asof-ffills a source onto the candle grid AND
    ffills the source's own timestamp, so per-bar `age_min = grid_time −
    ffilled_source_time`; pre-first-row bars get `age=+inf`.
  - `_stale_mask(age, cap)` — True where age > cap (or absent).
  - Book / trades / funding / OI blocks now zero their features on stale bars AND set
    the presence mask (`has_book` / `has_trades` / `has_funding_oi`) to 0 there. So a
    frozen snapshot forward-filled across an outage now honestly reads MISSING.
- **No downstream changes:** `FEATURE_DIM` stays 19, column order unchanged; every
  caller (`dataset.py`, `serve.py`, `audit_microstructure.py`) uses
  `build_feature_frame` and gets the fix transparently. Serving also now rejects
  stale book — correct.

**Verification (ml_trainer container, real DB = training dump):**
- `py_compile` clean on all touched + dependent files.
- Cap ON: the 499 candles-present/book-stale bars (08-04 05:44→14:02) → `has_book=0`,
  all book features 0; post-resume bars (14:04+) → `has_book=1`. Cap OFF (=0): same
  499 bars read `has_book=1` with stale `spread_bps` ffilled (the reproduced bug).
- Normal day (07-25): 0% stale. All 8 pairs build; book-era `has_book=1` fraction is
  now HONEST: BTC/ETH/SOL 0.90, DOGE/WLD/HYPE 0.64, ZEC 0.31, 1000PEPE 0.15
  (previously all ~1.0 regardless of staleness).

**NOT committed** (per user workflow: commit only when asked).

**Re-confirms the deferrals:** more candle data / bigger model / arch swap remain the
wrong moves — none address stale ffill. More pairs still only add robustness. The
walk-forward re-run (queued ~08-25) should be done AFTER the staleness fix, else it
re-measures the same poisoned data.

## 💰 TASK 2 — COST-AWARE SELECTION + CAPACITY ARM (2026-08-06)

Context: the first successful GPU run (`20260805T025536Z`, sha `6e6d358e`, see
`logs/latest_fixed.log`) trained clean and beat the momentum / buy-and-hold
baselines, BUT:
- 30m directional edge is real yet thin: fixed-cov 0.05 lb≈0.551, edge ≈+0.05–0.06.
- **Every gate loses money in the eval P&L** (30m net_ret −43.8 even at gate 0.60):
  a ~+5% hit-rate edge does not clear the 14bps round-trip at these holds.
- Train/val loss still moving together at early-stop (33) and the aux head never
  emits confidence >0.5 → the directional task is **under**fit, so on GPU capacity
  is now a legitimate lever (this run supersedes the earlier CPU-era "don't grow the
  model" caution, which assumed overfitting — see TASK 1; the staleness fix already
  addressed the book-era confound that motivated that caution).

Two changes implemented on this branch (NOT committed; no run launched yet).

### 2a. Cost-aware checkpoint selection ✅ IMPLEMENTED (code only)

**Problem.** `checkpoint_score` (`train_m2.py`) ranks epochs purely on the Wilson-LB
of directional **hit-rate** at top-5% confidence. Hit-rate ignores trade SIZE: 55%
right on tiny moves loses after cost; 52% right on large moves wins. Selection was
optimizing the wrong quantity relative to the eval P&L.

**Change.** Added an optional cost-aware term blended into the selection score:
```
sel = (1 - SEL_NET_WEIGHT) * edge_lb_score + SEL_NET_WEIGHT * net_score
```
- New `gate.fixed_coverage_net_return(logits, fwd_ret, coverage, cost)` — mean **net
  return per gated trade** over the top-`coverage` bars by directional confidence,
  after a round-trip `cost`. It is a per-bar top-coverage proxy (NOT the serial eval
  sim): ignores holds / one-position-per-pair, so it's comparable across epochs but
  is an **upper bound** on the turnover-limited eval P&L. Flat-true bars are included
  (a real trade books its return regardless of the flat band).
- `net_score = clip(0.5 + net_per_trade / SEL_NET_SCALE, 0, 1)`, same small-sample
  (`MIN_GATED_FOR_CKPT`) down-weight as the edge term.
- `train_m2.py` now collects the primary-horizon forward return in the val pass
  (always available as the `ret_<h>` batch key) and passes it to `checkpoint_score`.
- New config knobs (all env-overridable, **default OFF** = byte-identical legacy
  behavior): `SEL_NET_WEIGHT=0.0`, `SEL_COST_BPS=14`, `SEL_NET_SCALE=0.002`.
- Per-epoch log gains `net/trade=+X.Xbps net_sc=…` when `SEL_NET_WEIGHT>0`.

**Design notes / caveats.**
- Kept the cost SEPARATE from the eval cost model (`FEE_RATE_BPS`/`SLIPPAGE_BPS`) so
  we can stress selection without touching reporting.
- Deliberately did **not** replicate the serial simulator in the training loop
  (needs times+pair_ids per val batch, expensive, and the proxy is enough to *rank*).
  If the proxy and the serial sim disagree materially at eval, revisit.
- `SEL_NET_SCALE=0.002` (20bps/trade → score 1.0) is a guess; tune once we see real
  per-epoch `net/trade` values.

**How to use.** First a diagnostic run at `SEL_NET_WEIGHT=0` (unchanged selection)
just to read the new `net/trade` log column, then a proper arm:
```sh
# A/B: cost-aware selection on, primary 30m
SEL_NET_WEIGHT=0.5 SEL_COST_BPS=14 ./scripts/gcp_train.sh --gpu 60 128
# compare eval P&L / net_ret vs the 6e6d358e baseline at matched fixed-cov
```

### 2b. Encoder capacity knob ✅ IMPLEMENTED (code only)

**Change.** `SharedEncoderMultiHead` gained a `num_layers` arg (LSTM inter-layer
dropout auto-zeroed when `num_layers==1` to avoid the torch warning). New config
`NUM_LAYERS=2` (default preserves the served model). Threaded through `train_m2.py`
(construction + checkpoint meta), and reconstructed from meta in `serve.py` /
`eval_m2.py` (default 2 for pre-capacity checkpoints → backward compatible).

**Arms to try (one change per run, never with 2a in the same run):**
```sh
NUM_LAYERS=3 HIDDEN_SIZE=128 ./scripts/gcp_train.sh --gpu 60 128   # deeper+wider
HIDDEN_SIZE=256 ./scripts/gcp_train.sh --gpu 60 128                # wider only
```
Watch for book-era overfit (the historical risk): compare the book vs pre_book
fixed-cov split and walk-forward window 4. If edge_lb rises on train but the
book-era / recent walk-forward window does not, it's overfitting — back off.

**Longer-horizon lever (config-only, no code):** 60m already shows the best edge
(+0.060 @5% cov) and amortizes the 14bps better than 30m. Try `PRIMARY_HORIZON=60`
(and/or add 240m: `HORIZONS_MINUTES=5,30,60,240`) as a cheap arm.

### Verification done (no training)
- `py_compile` clean: `config.py gate.py train_m2.py serve.py eval_m2.py
  models/multi_horizon.py` (in `trading_agent-ml_trainer`).
- Functional: `fixed_coverage_net_return` + blended `checkpoint_score` on synthetic
  data (net metric computes; blend shifts score toward profitable-trade models);
  `SharedEncoderMultiHead` builds for `num_layers ∈ {1,2,3}` with no dropout warning.

### 2c. 🔭 FUTURE — CONFIDENCE CALIBRATION (documented, NOT implemented)

**Observation (from `logs/latest_fixed.log`, 30m calibration table).** The directional
head's confidence is **compressed and uncalibrated**: every moved bar lands in
`p(up) ∈ [0.30, 0.50)`, the head never emits confidence >0.5, and Brier≈0.25 (≈base
rate). Consequences:
- The serve/eval **absolute** gate (`GATE_THRESHOLD=0.40`) is meaningless — coverage
  is 1.0 at 0.35–0.50 then drops to 0 at 0.55 (no bar is that confident). Threshold
  gating effectively can't work; only the fixed-coverage top-k trick does.
- Any downstream RL policy that consumes p(up)/confidence as a risk input gets a
  miscalibrated signal.

**Why deferred (not done now).** Cost-aware selection (2a) and capacity (2b) attack
the size/strength of the edge, which is upstream of calibration — there's no point
calibrating a confidence scale that we're about to change by retraining with a
different objective/capacity. Calibration is a post-hoc wrapper; do it once the edge
is worth trading.

**Plan when we get to it (own task, after 2a/2b land a tradeable edge):**
1. **Temperature scaling** (single scalar T on the directional logits) fit on a
   held-out slice of the val window — cheapest, monotonic, preserves ranking/edge,
   only rescales confidence. Store `T` in checkpoint meta; apply in `serve.py`
   (`predict_dir_proba`) and in `eval_m2.py` before the gate sweep.
2. If temperature is insufficient (still compressed), **isotonic regression** on
   p(up) vs empirical up-rate (per horizon, possibly per-pair given the large
   BTC-vs-alt spread in the log). Non-parametric, handles the compression, but needs
   enough held-out bars and can overfit small pairs → guard with min-n.
3. **Re-report the calibration table + Brier** after the fix (eval already computes
   it — see the "Directional head calibration" block) and only then re-tune the
   serve `GATE_THRESHOLD` to an absolute confidence that finally means something.
4. **Do NOT** fold calibration into the selection score — keep it a post-hoc,
   ranking-preserving wrapper so it can't distort which epoch is chosen. (Contrast
   with the existing quantile `cal_pen`, which is a different, band-coverage penalty.)

Open question: whether to calibrate per-pair. The per-pair eval shows very different
ungated base rates (BTC ~0.64 vs HYPE ~0.38) and HYPE actually has *negative* 30m
edge — per-pair calibration + possibly per-pair gate thresholds (or dropping no-edge
pairs) is the natural companion, but adds complexity; decide with data in hand.

### 2d. 🧪 "ONE-MODE" HYPOTHESIS + DIAGNOSTICS ✅ IMPLEMENTED (code only), 2026-08-06

**Hypothesis (user, 2026-08-06):** maybe the last ~400d was a mostly-bearish market so
the model "learned one mode" — predicts down and can't call ups.

**Current read of the evidence (from `logs/latest_fixed.log`) — likely NOT a bearish
label skew, but the symptom is partly real:**
- **Labels are balanced, not bearish.** Train class balance (log ~1030): 30m
  down=0.31 / flat=0.39 / up=0.30 (same at 5m/60m). A one-directional market would
  show down ≫ up. It doesn't — because these are 5/30/60-min moves across 8 pairs
  (val buy-and-hold is mixed: WLD +16.7, HYPE +10.3, ZEC +5.5 up; BTC/ETH/SOL/DOGE/
  PEPE down; pooled ≈ −1.1, i.e. roughly flat, not bearish).
- **The 3-class head DID collapse** — 30m/60m confusion matrices (log ~1131/1180) have
  an all-zero `up` column (never predicts up). But this is the known flat-mass class-
  collapse artifact (already fought with `sqrt_inv_freq` + label smoothing, cfg
  106-120), on a head that does NOT drive gating.
- **The directional head does NOT collapse** — its calibration table (log ~1163) shows
  p(up) spanning [0.30,0.50) with empirical up-rate 0.43–0.49, and per-pair dir_acc is
  two-sided (BTC 0.523, ZEC 0.517). Gating/edge come from THIS head. So the model
  isn't stuck short; one auxiliary head collapsed.

**Decisive test added (so we can confirm/refute on the next run, not argue from the
confusion matrix):** two directional-SYMMETRY diagnostics in `eval_m2.py`:
1. **`side_split_metrics` (gate.py)** → per-side (pred-up vs pred-down) `dir_acc /
   wilson_lb / n_gated / n_dir` at fixed cov 0.05. Printed as "Side split @ fixed-cov
   0.05 (did it learn one mode?)".
2. **`long_short_pnl_split` (eval_m2.py)** → the serial `simulate_pnl` run once
   long-only, once short-only, at the serve gate. Printed as "Long/short serial P&L".
Both are also written to `eval_m2.json` under each horizon
(`side_split_cov05`, `long_short_pnl`).

**How to READ the new output (interpretation rule):**
- **Two-sided / healthy:** up and down have comparable `n_dir` AND comparable
  `dir_acc` (both >0.5); long and short both trade with similar net_ret sign.
  → the "one-mode" hypothesis is REFUTED; edge is symmetric.
- **One-mode / confirmed:** one side has `n_gated`≈0 or `dir_acc`≈0.5 while the other
  carries all the edge; P&L is all long or all short.
  → hypothesis CONFIRMED; then the fix is on the **3-class head** (stronger/focal
  weighting, or drop it and gate purely off the directional head), NOT more data.
- Verified on synthetic tensors: a symmetric model prints balanced up/down
  (~486/514 gated, equal dir_acc) + balanced long/short P&L; a deliberately short-only
  model prints `up n_gated=0` and all edge on `down`. The diagnostic discriminates.

**My prior:** expect roughly two-sided on the directional head → hypothesis mostly
refuted, but the run will settle it. Either way the action differs (2a/2b vs 3-class
head fix), so this is worth measuring before the next training decision.

---

## 🚀 HOW TO RUN THE NEXT TRAINS (2026-08-06) — read before launching

All runs go through `./scripts/gcp_train.sh` (creates a GPU VM, pulls a fresh DB dump
from the always-on VM, restores Postgres, runs `train_m2.py` + `eval_m2.py`, pushes
the checkpoint + full log to the bucket, then self-deletes). Usage:
`./scripts/gcp_train.sh [--gpu] [epochs] [seq_len]` (defaults 60 / 128).

**IMPORTANT — tuning knobs now pass through env (added 2026-08-06).** The launcher
forwards a whitelist of env vars (`FLUX_TRAIN_ENV_KEYS` in `scripts/gcp_train.sh`) into
BOTH the GPU (`docker run`) and CPU (`docker compose`) containers, so `config.py` picks
them up. Set them on your Mac before the command. Whitelisted today:
`SEL_NET_WEIGHT SEL_COST_BPS SEL_NET_SCALE SEL_COVERAGE NUM_LAYERS HIDDEN_SIZE DROPOUT
LR WEIGHT_DECAY BATCH_SIZE CLS_WEIGHT_MODE CLS_WEIGHT_CLIP CLS_LABEL_SMOOTHING
DIR_LOSS_WEIGHT BOOK_MAX_AGE_MIN TRADES_MAX_AGE_MIN FUNDING_OI_MAX_AGE_MIN
FEE_RATE_BPS SLIPPAGE_BPS`. Add new knobs to that list when you create them.
(Before this change, arbitrary env did NOT reach the GPU container — only a hardcoded
QUANTILE/HORIZON allowlist did. If a knob "had no effect" on an older GPU run, this is
why.)

**Golden rule: ONE change per run** (repo convention — never change data AND arch/
selection in the same run, else you can't attribute the result).

Recommended sequence (each is a separate run; the side-split diagnostic 2d prints on
ALL of them for free):

```sh
# R0 — staleness-fix baseline (TASK 1). Default config; the reference point.
./scripts/gcp_train.sh --gpu 60 128

# R1 — cost-aware selection (2a). Targets net-of-cost P&L instead of hit-rate.
SEL_NET_WEIGHT=0.5 SEL_COST_BPS=14 ./scripts/gcp_train.sh --gpu 60 128

# R2 — capacity (2b). Deeper+wider encoder; watch book-era / walk-forward for overfit.
NUM_LAYERS=3 HIDDEN_SIZE=128 ./scripts/gcp_train.sh --gpu 60 128

# R3 — longer-horizon primary (2b lever, config-only). 60m amortizes cost better.
TRAIN_PRIMARY=60 ./scripts/gcp_train.sh --gpu 60 128
#   (TRAIN_PRIMARY / TRAIN_HORIZONS / TRAIN_PAIRS are read by gcp_train.sh directly.)
```

Monitor / retrieve:
```sh
./scripts/gcp_status.sh            # RUNNING / DONE / FAILED (reads bucket status/)
./scripts/gcp_promote.sh           # promote DONE checkpoint to serving
# full log of the latest run (what you pasted last time as logs/latest_fixed.log):
#   gs://fluxtrader-train-artifacts/logs/<RUN_ID>.log   and   .../status/latest.json
```

### 📋 WHEN YOU COME BACK WITH RESULTS (context recovery for a fresh session)

Paste the run's log (as before, e.g. save to `logs/<name>.log`) and tell me which arm
it was (R0–R3 above / which env knobs). To re-orient quickly, I will look at, in the
eval section of the log:
1. **Side split @ fixed-cov 0.05** + **Long/short serial P&L** (NEW, 2d) → is the edge
   two-sided? settles the one-mode question.
2. **Fixed-coverage directional edge** (30m primary): `wilson_lb` @ cov 0.05/0.10 vs
   the R0 baseline (`6e6d358e`: 30m lb≈0.551 @0.05).
3. **Book-era split** (`book` vs `pre_book` lb) → did the staleness fix (TASK 1) lift
   the book-era edge toward pre_book?
4. **Walk-forward** windows 1–4 lb → is the edge stable across time / recent window?
5. If cost-aware arm (R1): the per-epoch `net/trade=…bps net_sc=…` column + whether
   the P&L sweep `net_ret` improved vs R0 at matched coverage.
6. If capacity arm (R2): train vs val edge gap + book-era/WF-window-4 (overfit check).

Key file:line anchors for me (this branch): cost-aware selection
`ml/train/train_m2.py:checkpoint_score` + `gate.py:fixed_coverage_net_return`;
capacity `models/multi_horizon.py` (`num_layers`) + `config.py:NUM_LAYERS`;
symmetry diagnostics `gate.py:side_split_metrics` +
`eval_m2.py:long_short_pnl_split`; env passthrough `scripts/gcp_train.sh`
(`FLUX_TRAIN_ENV_KEYS`). Baseline run to compare against: `20260805T025536Z` /
sha `6e6d358e` / `logs/latest_fixed.log`.

**State as of 2026-08-06:** all of TASK 2 (2a–2d) + the env passthrough are
implemented on a working branch but **NOT committed and NO run launched** (per the
commit-only-when-asked workflow). Next action is yours: commit + launch R0…R3.

---

### Data-collection strategy → see `docs/DATA_COLLECTION_AUDIT.md` (2026-08-05)

Full audit of what the collector captures vs silently drops, framed by
backfillable-vs-collector-only. Headlines:
- **Derived features** (longer-horizon returns, cross-pair/beta) come from candles we
  ALREADY have → NOT time-sensitive; add deliberately, one attributable run at a time,
  AFTER the staleness-fix baseline.
- **Raw collection IS time-sensitive** (no backfill). Top item: the order book is
  **lossily compressed at write time** — 20 levels pulled, only 11 scalars stored, raw
  ladder discarded (`book_features.ex`). Every day of low-fidelity book history is
  unrecoverable. Also worth starting now: long/short & taker ratios (collector-only),
  exchange event timestamps. Liquidations remain blocked (vendor/egress decision).

---

 ## ⏰ ACTION QUEUED — WALK-FORWARD RE-RUN (blocked on data) — READ FIRST

> **STATUS 2026-08-11:** still blocked. Fresh `gcp_data_collection_stats.sh` shows the
> 4 longest pairs at ~24d20h (majors cross 30d ≈ 2026-08-16; full 8-pair ≈ 2026-08-26).
> Exact per-pair ages + the staged NOW→08-16→08-26 launch plan live in the updated
> "▶️ START HERE (2026-08-11)" section at the top — that is the current decision layer;
> the mechanics below are still correct.

**Why this is here:** the 2026-08-04 walk-forward (`wf-20260804T144400Z`) did **not**
confirm the 30m book edge. Per-fold Wilson-LB gaps (book-ON − book-OFF):

| fold (val window) | ON lb | OFF lb | gap |
|---|---:|---:|---:|
| 0.0 (08-01→08-04) | 0.625 | 0.537 | **+0.088** |
| 0.2 (07-29→08-01) | 0.552 | 0.477 | **+0.075** |
| 0.4 (07-26→07-29) | 0.486 | 0.516 | **−0.030** |

**MIN gap = −0.030** → fails the robustness rule (min gap must be > ~0.05 on ALL
folds). The earlier single-window ablation (ON lb=0.691) was one lucky ~2.7d
window. The edge shows in the two newest folds but flips negative in the oldest,
and best epochs land at 2–5 with val loss already rising → **overfitting on a
tiny dense-book sample**, not a stable edge.

**Root cause is DATA QUANTITY, not the model.** With `--require-book`, samples
only exist where book data exists: as of 2026-08-05 that's ~18 days
(2026-07-17→08-04, ~164k samples), which the 3 folds carve into ≤130k train /
~33k val slices each. Book history grows ~1 day/day.

**❗ NOT a stale-dump bug (checked 2026-08-05).** The walk-forward dump is taken
fresh from always-on each run; `wf_latest.sql.gz` held 1,045,291 orderbook rows
through 2026-08-04, matching live DB. The "microstructure only to 01.08" someone
noticed is just the **train/val split boundary of fold 0.0** (train ends 08-01,
val = 08-01→08-04), i.e. correct no-leakage behavior — not the data ceiling.

**TRIGGER TO RE-RUN:** when continuous book history ≥ **~30 days**
(≈ **2026-08-25**; check via `scripts/gcp_data_collection_stats.sh` — earliest
`first_snapshot` across the traded pairs should be ≥ 30d old). That gives each of
the finer folds a non-trivial val slice.

**Re-run command (fixes already wired in — see "Fixes wired in" below):**
```sh
# stronger regularization for the tiny dense regime + 6 finer folds (defaults)
WF_DROPOUT=0.4 WF_WEIGHT_DECAY=1e-3 WF_HIDDEN=48 \
  ./scripts/gcp_walkforward.sh
# optional sharper read on the 4 longest-history pairs only:
WF_LONG_PAIRS_ONLY=1 WF_DROPOUT=0.4 WF_WEIGHT_DECAY=1e-3 WF_HIDDEN=48 \
  ./scripts/gcp_walkforward.sh
# fetch: ./scripts/gcp_walkforward.sh --fetch
```

**VERDICT RULE (unchanged):** min LB gap across ALL folds > ~0.05 → the 30m book
edge is robust → proceed to microstructure-rich collection/run. If any fold's gap
is ≤0 or LBs overlap → still not robust → keep collecting, do **not** over-invest.
If the gap holds *only* once dropout/wd are cranked and hidden shrunk, note that
the effect is small and capacity-sensitive.

**Fixes wired in this session (2026-08-05) so the re-run is one command:**
- `DROPOUT` env now drives LSTM + all head dropout (`ml/train/config.py`,
  `models/multi_horizon.py`, threaded through `train_m2.py`; default 0.2 = served
  candle model unchanged). Stamped into checkpoint `meta` + printed at startup.
- `gcp_walkforward.sh` now: defaults to **6 finer folds**
  (`0.0 0.1 0.2 0.3 0.4 0.5`); passes `WF_DROPOUT`/`WF_HIDDEN` (as env) and
  `WF_WEIGHT_DECAY` (as `--weight-decay`) into each arm; supports
  `WF_LONG_PAIRS_ONLY=1` (BTC/ETH/SOL/DOGE); records the reg config in the compare
  header. `--weight-decay`, `--patience`, `HIDDEN_SIZE` were already tunable.
- **NOTE:** these only affect the throwaway walk-forward VM/arms. Serving and the
  candle model defaults are untouched.

---

## TL;DR

- Training is **compute-bound, never memory-bound** (feature RAM ~48 MiB via lazy
  windowing in `ml/train/data/dataset.py:501`). So the answer to "downsize RAM or
  use it for speed?" is: **neither** — spend on vCPU.
- Baseline run (3 pairs, 180d) is **DONE** — see "Baseline reference". It has a
  modest but real edge at high confidence; serve gate was mis-tuned (raised to 0.58).
- Next run: **6 pairs + e2-standard-4 + gate 0.58**, prepared on branch
  `train-upgrade-e2std4-5pairs`. Merge to `main` then launch (pipeline trains from
  `GIT_REF=main`; reuses one VM name + `latest.*` bucket keys, so no parallel runs).
- Model-head experiment (quantile head) + presence-mask features come **later, as
  their own runs**.

> **SESSION HANDOFF (2026-07-27, end of session) — READ FIRST.**
> Two things are IN FLIGHT / AWAITING ANALYSIS next session:
>
> 1. **Dense-window book ablation (built + launched).** Both arms ran on always-on:
>    `--require-book` (book-ON) and `--require-book --ablate-book` (book-OFF), 8
>    pairs, dense live-book window (2026-07-17→07-27, ~70.4k samples, val ~14k /
>    ~2k per pair). **Only the setup headers were captured — the per-epoch dir_acc
>    lines and eval sections were NOT saved.** ACTION next session: get both full
>    logs (epoch `sel@cov0.05 dir_acc/lb` + eval `--- Horizon 30m/60m ---`
>    fixed-coverage tables) and compare book-ON vs book-OFF. This is the decisive
>    test of whether the audit's `spread_bps` signal survives inside the model.
>    - Verdict rule: book-ON 30m/60m top-5% dir_acc materially > book-OFF (read the
>      **Wilson LB**, val slice is small ~2k/pair) => book edge real inside model
>      => accelerate microstructure collection + plan the full microstructure-rich
>      run. If ~equal => audit signal is candle-confounded; don't over-invest yet.
>    - Note: dense window is flat-heavy (flat 0.59–0.63 vs 0.43 on 180d) — a recent
>      low-drift regime; factor this into reading the numbers.
>    - Re-run to regenerate logs if lost:
>      `docker compose --profile ml run --rm ml_trainer python train_m2.py \
>         --device cpu --epochs 40 --seq-len 128 --require-book [--ablate-book]`
>      (run on always-on; save FULL stdout each arm.)
>
> 2. **Quantile re-run (calibration-aware selection + weight 0.2) — STILL RUNNING.**
>    Launched via `TRAIN_QUANTILE_HEAD=1 ./scripts/gcp_train.sh`. ACTION next
>    session: fetch its log (`./scripts/gcp_logs.sh`), then judge against the
>    promotion criteria: 30m top-5% dir_acc within ~0.01 of Run A (0.554) AND
>    band[p10-p90] coverage ≈ 0.80 at the SAVED epoch (watch the `cal_pen`/`sel`
>    epoch lines + eval "Quantile calibration"). Promote to personal UI only if
>    both hold; else keep Run A served.
>
> ---
>
> **Current status (updated 2026-07-27) — read this first.** Presence masks,
> quantile head, 3-class weighting fix, and calibration-aware selection are all
> **implemented + committed on `main`**. See "Microstructure readiness roadmap"
> and "A/B results log" directly below for where things stand and what to do next.

---

## Microstructure readiness roadmap (2026-07-27)

**Why this section exists:** the model's edge is still **candle-driven**. The
order-book / trade-flow / OI features (11 of ~19) are zero-filled for ~95% of the
180-day training window because the live collector only started recently. The
real ceiling on signal quality is this data scarcity, not architecture.

**Current book/trade/OI collection state (from always-on Postgres, 2026-07-27):**

| Pair | book history |
|------|--------------|
| BTC / ETH / SOL | ~9 days |
| DOGE / WLD / HYPE | ~6 days |
| ZEC | ~2 days |
| 1000PEPE | ~40 min |

Collection grows ~1 day/day (no historical backfill exists for book/trades/OI —
only candles + funding can be backfilled).

**Why not train on it yet:** at ~9d vs 180d candles, the "present" region is a
sliver of each training window → zero-fill dominates, and per-pair z-score norm
is unstable on near-constant features. A book-driven edge cannot be learned yet.

**Readiness thresholds (rough):**
- **~30 days** continuous book history → enough to *test* a book edge in training
  (validate on ~1 week of dense-book bars, train on the rest).
- **~60–90 days** → comfortable for a real **microstructure-rich run** where the
  present region dominates windows and norm is stable.
- At current rate that's **~7–11 weeks out** (from 2026-07-27).

**What to do while waiting (in order):**
1. **Run the feature-signal audit** (`ml/train/audit_microstructure.py`) — decides
   *now* whether the book edge even exists, before waiting weeks. Read-only, no
   training. **Run it on the always-on VM** (that DB has the real ~9-day book data):
   ```sh
   # on always-on: fluxtrader-1
   docker compose --profile ml run --rm ml_trainer python audit_microstructure.py
   ```
   Decision rule (printed by the script): strongest book-feature |Spearman| >~0.03
   with `wilson_lb(sign_acc) > 0.51` on a pair with enough live rows ⇒ collecting
   more is worth it; all-noise ⇒ keep collecting, don't over-invest. Writes
   `output/microstructure_audit.json`. **Caveat: 2–9 days is a SMELL TEST only** —
   a slow-drifting feature (e.g. `oi`) can show spurious correlation on a trending
   window; treat positives as "worth more collection", never as final.
   - Local run 2026-07-27 (few-day window) already showed BTC 60m `oi`
     (rho≈−0.13, lb≈0.57) and `spread_bps` (rho≈+0.11, lb≈0.56) — a *preliminary*
     book signal. Re-run on always-on for the meaningful read.
   - **Deep dive (added 2026-07-27):** the audit now also runs a sub-window
     stability test (`--thirds`, default 3) and a volatility control (`--vol-buckets`,
     default 5; disable with `--no-deep`). Per feature it prints a verdict:
     - `STABLE/UNSTABLE`: same-sign Spearman across all sub-windows? (UNSTABLE ⇒
       regime/trend artifact)
     - `DIRECTIONAL/VOL-PROXY`: does the sign edge persist across `|fwd|` buckets
       after controlling for volatility? (bucketed test drives the verdict)
     - **Decision:** `STABLE+DIRECTIONAL` ⇒ genuine directional alpha ⇒ **escalate**
       to a dense-window ablation training run (book features on vs off) — do NOT
       wait for 60d to start validating. `STABLE+VOL-PROXY` ⇒ route the feature to
       the quantile/risk head (band width), not direction. `UNSTABLE` ⇒ keep
       collecting, re-audit at ~30d.
   - **Full-audit read (always-on, 2026-07-27):** `spread_bps` was the standout —
     positive, monotone, and strengthening with horizon across ALL pairs (60m ρ:
     BTC +0.10, SOL +0.13, DOGE +0.18, HYPE +0.20; LB up to ~0.56). The deep-dive
     smoke on the local window flagged `spread_bps` as **STABLE+DIRECTIONAL on
     every pair/horizon tested** (dir_buckets 5/5 on BTC 60m; negative vol_corr, so
     not merely a volatility proxy). Depth/imbalance book features were weak
     (|ρ|<0.05). `oi`/`funding` were strong-but-sign-inconsistent across pairs →
     treat as risk features, not directional, pending confirmation.
     → **Re-run the deep-dive audit on always-on** (real ~9-day, 13k-row window)
       to confirm on the larger sample, then act on the STABLE+DIRECTIONAL roll-up.
2. **Keep the collector running** toward the 60–90d target.
3. Presence masks (done) are the enabling plumbing — the model already tolerates
   missing microstructure and flags present-vs-missing per row.

**Then:** microstructure-rich training run at ≥60d → compare vs the candle-only
baseline → only then reassess **RL (M3)**.

---

## A/B results log (primary 30m, fixed-cov top-5% dir_acc @ selected epoch)

| Run | Change | dir_acc@5% | wilson_lb | sel_score | notes |
|-----|--------|-----------:|----------:|----------:|-------|
| Baseline (16-dim) | 3 majors → 6 pairs, 180d | 0.565 | 0.555 | 0.555 | pre-masks; **served? no** |
| Masks v1 (19-dim, old 3-class weights) | presence masks | 0.559 | 0.545 | 0.545 | ~wash; 3-class "down" collapse |
| **Run A** (masks + 3-class fix) | sqrt-inv-freq + clip + label-smooth | 0.554 | 0.544 | 0.544 | **PROMOTED / currently served** |
| **Run B** (+ quantile head @ w=0.5) | pinball aux head | 0.540 | 0.530 | 0.532 | regressed dir (~−0.014); band-cov unstable (0.63–0.81), saved epoch cov=0.68 → **not promoted** |

**Interpretation:** directional ceiling ~0.55 @ 5% coverage, still candle-driven.
Masks did not help *yet* (expected — dead until microstructure accumulates) but
did not break trading. The 3-class fix removed the "never predicts down" argmax
collapse without touching the directional path. The quantile head at weight 0.5
stole encoder capacity (dented direction) and selection saved a poorly-calibrated
epoch → fixed via the two changes below.

**Changes made after Run B (committed on `main`):**
- `QUANTILE_LOSS_WEIGHT` default **0.5 → 0.2** (lighter aux head).
- **Calibration-aware checkpoint selection**: when the quantile head is on, the
  selection score is multiplied by `1 - CAL_PENALTY_WEIGHT·min(1,|band_cov−target|/CAL_TOL)`
  (defaults 0.5 / band-width=0.80 / 0.10), so the saved & early-stop epoch is
  directionally good **and** calibrated. No effect when the head is off.

**Microstructure follow-up — VERDICT IN (always-on audit, 2026-07-27):**
- **`spread_bps` is STABLE+DIRECTIONAL on 11 pair/horizon combos** (every pair;
  30m/60m; ρ +0.09→+0.20 growing with horizon; sign-acc Wilson LB up to ~0.56),
  with **negative `vol_corr` everywhere (−0.10 to −0.24)** and `resid_rho ≈ raw ρ`
  → it is NOT a volatility proxy; `dir_buckets` 5/5 on several combos (edge holds
  across all volatility regimes). This is a genuine, cross-pair, horizon-scaling
  directional signal — the strongest microstructure finding by far.
- Other STABLE+DIRECTIONAL hits are singletons (mostly SOL: depth_near_imb,
  imbalance) — treat as suspect (multiple-testing / one-pair). Depth/imbalance/OI
  are weak or sign-inconsistent across pairs.
- Caveats: single ~9-day window (one regime); signal is at 30m/60m, weak at 5m;
  the model currently sees `spread_bps=0` for ~95% of history so it can't use this
  yet — which is exactly why the dense-window ablation matters.

**Dense-window ablation run — BUILT (this session). The decisive test:**
Train+validate ONLY on the live-book window (`has_book==1` across the whole
window) with book features ON vs OFF; if book-ON adds held-out directional edge,
the signal survives *inside the model* and we escalate microstructure collection.
New `train_m2.py` flags (validated locally):
```sh
# book-ON arm (dense window, all features):
docker compose --profile ml run --rm ml_trainer python train_m2.py \
  --device cpu --epochs 40 --seq-len 128 --require-book
# book-OFF arm (same window, microstructure zeroed):
docker compose --profile ml run --rm ml_trainer python train_m2.py \
  --device cpu --epochs 40 --seq-len 128 --require-book --ablate-book
```
- `--require-book`: restrict samples to bars whose full seq_len window has book data.
- `--ablate-book`: zero the 11 microstructure features (`data.features.BOOK_FEATURES`).
- meta stamps `require_book` + `ablated_features`.
- **Decision rule:** book-ON primary-30m/60m top-5% dir_acc materially > book-OFF on
  the held-out slice ⇒ book edge is real inside the model ⇒ accelerate collection /
  plan the microstructure-rich full run. If ~equal ⇒ the audit signal doesn't
  survive modeling; don't over-invest.
- NOTE: dense window is short (~9d majors / ~6d alts / ~13.6k live bars per major),
  so val slice is small — read dir_acc with its Wilson LB, not point estimates.
- These flags are NOT yet wired into `scripts/gcp_train.sh`; run via the ml_trainer
  container directly (local or on the train VM), or add a passthrough if you want to
  run them through the GCP pipeline.

**Ablation run COMPLETED 2026-08-04 (`gcp_ablate.sh`, run=ablate-20260804T083752Z git=5aee602a):**
- Both arms identical (clean A/B): 8 pairs, dense window `--require-book`,
  epochs=40 seq=128 horizons=5,30,60. OFF arm zeroes the 11 book features.
- Samples 161,651 | train 129,320 / val 32,331 | val window 2026-08-01 12:18 →
  2026-08-04 07:39 UTC (~2.7 days). Metric = top-5% selective dir_acc, read via
  Wilson LB (`lb=`), PRIMARY horizon, at the max-sel-score epoch.
- Logs: `logs/ablate_{compare,on30,off30,on60,off60}.log`.

  | horizon | book-ON top-5% dir_acc (lb) | book-OFF top-5% dir_acc (lb) | Δ (lb) | verdict |
  |---------|----------------------------:|-----------------------------:|-------:|---------|
  | 30m | 0.729 (**lb=0.691**) ep12 n=575 | 0.536 (lb=0.494) ep03 n=539 | **+0.197** | **book edge real** — LBs don't overlap |
  | 60m | 0.650 (lb=0.610) ep01 n=577 | 0.630 (lb=0.587) ep01 n=505 | +0.023 | no verdict — both arms peaked ep1 then decayed (no real training) |

- **Verdict:** at 30m the book edge clearly survives modeling (per decision rule
  ⇒ escalate microstructure). At 60m no conclusion (init noise, not learning).
- **Caveats:** single ~2.7d val window, thin high-confidence tail (n≈575), broad
  3-class val acc only ~0.50–0.53 — edge lives entirely in the top-5% slice.
  ⇒ **Walk-forward multi-window rerun DONE (2026-08-04) — INCONCLUSIVE.** Min LB
    gap = −0.030 across 3 folds (fails the >0.05 rule); best epochs 2–5 with rising
    val loss ⇒ overfitting on the ~18d dense sample. Data quantity, not model, is
    the bottleneck. See the pinned "WALK-FORWARD RE-RUN" section at the very top:
    re-run at ≥~30d book history (~2026-08-25) with the wired-in anti-overfit knobs
    before investing in collection.

**⚠️ Liquidations feed BLOCKED (2026-08-04):** `liquidations` table = 0 rows. Root
cause was (1) collector used REST `allForceOrders` (auth-gated, unusable for public
data) and (2) errors were silently swallowed. Both fixed: the REST poll is removed
and `FluxTrader.Binance.WebSocket` is now a real `gun`-based consumer of the WS
`!forceOrder@arr` stream (auto-reconnect, writes to `liquidations`). BUT Binance
**gates the WS data plane from cloud/datacenter egress**: verified from local +
`fluxtrader-1` (me-central1) + `fluxtrader-train` (us-central1) — all get a `101`
upgrade and a SUBSCRIBE ack but **zero market-data frames** (even `btcusdt@aggTrade`).
REST (`fapi`) returns 200 everywhere. So liquidations cannot be collected via current
access; there is no REST fallback and WS has no history anyway.
- **Decision (2026-08-04): document + defer.** The 30m book edge above exists
  WITHOUT liquidations, so this is not on the critical path. Options for later, in
  preference order: (a) third-party vendor REST (Coinglass/Coinalyze — also gives
  *history*, which WS never would); (b) proxy the WS through a non-datacenter
  egress (realtime only); (c) drop liquidations from the feature set.
- The WS consumer code is correct and ready — it will collect the instant it runs
  from an unblocked egress. Do NOT re-debug the code; it's a network/vendor decision.
- NOTE for M3: these features feed the RL policy later ("M2 describes the market;
  M3 decides the trade"). A permanently-empty `liquidations` column would be a dead
  RL input — resolve the source before the microstructure-rich run, not after.

**Next runs, in order:**
1. **Walk-forward re-run @ ≥~30d book history (~2026-08-25)** — the queued action.
   See the pinned "WALK-FORWARD RE-RUN" section at the very top for the trigger,
   one-line command, and verdict rule. This gates whether microstructure
   collection is worth accelerating.
2. **Quantile re-run** with the two fixes: `TRAIN_QUANTILE_HEAD=1 ./scripts/gcp_train.sh`
   (weight now defaults to 0.2). Promote **only if**: 30m top-5% dir_acc within
   ~0.01 of Run A (0.554) **AND** band[p10-p90] coverage ≈ 0.80 at the *saved*
   epoch (check the eval "Quantile calibration" line + the `cal_pen`/`sel` epoch
   log). Otherwise keep Run A served.
3. **Microstructure-rich run** once book history ≥ ~60d AND the walk-forward
   re-run (step 1) confirms a robust edge (see roadmap above).
4. **Reassess RL (M3)** only after the microstructure run.

**Serving state:** Run A is the model currently promoted to the personal UI (not
production). Do not promote Run B. Promote a future run only against the criteria
in step 1.

## Baseline reference (FINISHED — run 20260723T222840Z, git 2b208de)

- Pairs: BTCUSDT, ETHUSDT, SOLUSDT (3), 180 days, seq_len 128, primary 30m.
- Samples: 788,705 (train 630,964 / val 157,741). Val 2026-06-17 → 2026-07-23.
- **Best = epoch 13** (`sel_score=0.5546 dir_acc=0.569 lb=0.555 n_dir=4822`).
  Early-stopped at epoch 18 (no improve for 5 epochs). Clean run, no overfit.
- Final eval per horizon, fixed-coverage top-5% (comparable metric):

  | Horizon | ungated 3-class | top-5% dir_acc | top-5% wilson_lb |
  |---------|----------------:|---------------:|-----------------:|
  | 5m      | 0.527 | 0.568 | 0.554 |
  | 30m (primary) | 0.556 | 0.569 | 0.555 |
  | **60m** | 0.571 | **0.585** | **0.571** |

- **60m is the strongest horizon** on every confidence bucket (top-2% dir_acc
  0.588 / lb 0.566). Primary is 30m → we serve the middle performer. Open item:
  consider switching primary to 60m (decide after next run's per-pair eval).
- **Flat-bias:** the 3-class heads predict "flat" for the large majority of bars
  (see confusion matrices in the log); directional edge is recovered by the aux
  dir heads, which is why dir_acc > ungated tells the real story.
- **⚠️ Serve-gate finding (actionable):** the gate sweep shows gate ≤0.50 →
  coverage 1.000 → dir_acc ~0.521 (≈coin flip). Edge only appears at gate ≥0.55
  (30m gate 0.60 → dir_acc 0.560; 60m gate 0.60 → 0.579). The old serve gate 0.40
  traded ~everything at no edge. **→ raised `ML_GATE_THRESHOLD` 0.40 → 0.58.**
  Caveat: confidence scale drifts between models; re-check the gate sweep each run
  and re-tune. (Only `ML_GATE_THRESHOLD` changed; `CKPT_GATE_THRESHOLD` and
  `CONFIDENCE_THRESHOLD` left alone — checkpoint selection uses fixed-coverage
  `SEL_COVERAGE=0.05`, not the gate.)
- **Caveat:** trained on 180d candles but only ~7d of real microstructure, so the
  edge is essentially candle-driven (see "Data audit findings"). The real ceiling is
  likely microstructure data scarcity, not architecture → the microstructure-rich
  run remains the highest-leverage future step.

---

## Part 0 — Pull current best checkpoint for UI reference (safe, no job impact)

The best checkpoint lives only in the training VM's docker volume
(`trading_agent_model_weights` → `/models/m2_multi.pt`). It is **not** in the
bucket until the run finishes (`scripts/gcp_train.sh:229-235`) — that is why
`gcp_promote.sh` (status `<none>`) and
`gcloud storage cp .../checkpoints/latest.pt` both fail right now. Expected.

Copy it out (read-only w.r.t. the job):

```sh
# 1. On the training VM: copy checkpoint out of the docker volume to VM home
gcloud compute ssh fluxtrader-train --project=fluxtrader --zone=me-central1-b -- \
  'docker run --rm -v trading_agent_model_weights:/models -v $HOME:/out alpine \
     sh -c "cp /models/m2_multi.pt /out/m2_multi_epoch_snapshot.pt && ls -la /out/m2_multi_epoch_snapshot.pt"'

# 2. Copy from VM down to Mac
gcloud compute scp --project=fluxtrader --zone=me-central1-b \
  fluxtrader-train:~/m2_multi_epoch_snapshot.pt ./m2_multi_epoch_snapshot.pt
```

Cautions:
- Point-in-time snapshot; training keeps overwriting the file on each new best.
- **Do NOT use `scripts/gcp_promote.sh`** for UI reference — it recreates
  `ml_inference` on the always-on VM (`scripts/gcp_promote.sh:71`), i.e. puts the
  model in the serving path. Load the copied file in a **separate/dev inference**.
- Checkpoint is self-contained (stores `norm_stats` + head config).

### Serving this checkpoint in the always-on UI (dev-only, not production)

Serve path: `ml_inference` (`ml/train/serve.py`, port 8001) reads
`/models/m2_multi.pt` from the `trading_agent_model_weights` volume → Elixir
`Predict` (Finch, `apps/fluxtrader/lib/fluxtrader/ml/predict.ex`) → `SignalEngine`
→ `DashboardLive`. `serve.py` rebuilds the model from the checkpoint's own `meta`
(horizons/seq_len/feature_dim/hidden/dir_head) and only loads at startup.

```sh
# 1. Upload the pulled checkpoint to the always-on VM
gcloud compute scp --project=fluxtrader --zone=me-central1-b \
  ./m2_multi_epoch_snapshot.pt fluxtrader-1:/tmp/m2_multi.pt

# 2. Install into the model volume + restart inference (mirrors gcp_promote.sh:66-71)
gcloud compute ssh fluxtrader-1 --project=fluxtrader --zone=me-central1-b -- '
  cd ~/trading_agent &&
  docker volume create trading_agent_model_weights >/dev/null 2>&1 || true &&
  docker run --rm -v trading_agent_model_weights:/models -v /tmp:/in:ro alpine \
    sh -c "cp /in/m2_multi.pt /models/m2_multi.pt && ls -la /models/m2_multi.pt" &&
  docker compose up -d --force-recreate ml_inference &&
  sleep 4 && curl -sS http://127.0.0.1:8001/health
'
```

Healthy = `{"ok": true, "model_path": "/models/m2_multi.pt", "norm": "ckpt", ...}`.
Notes: overwrites whatever `m2_multi.pt` is currently served; predictions need live
features from the always-on DB, so keep the whitelist on pairs with recent data.
Later, run a second `serve.py` on another port/`MODEL_PATH` to separate dev-eval
from UI signals (no code change needed).

---

## Part 1 — Do NOT launch a second run in parallel

Pipeline reuses fixed VM name `fluxtrader-train` (`scripts/gcp_common.sh:19`) and
fixed bucket keys (`dumps/latest.sql.gz`, `status/latest.json`,
`checkpoints/latest.pt`). A second `gcp_train.sh` collides with the running job.
Prepare changes on a branch; launch only after the current run finishes.

---

## Part 2 — Baseline captured (DONE)

Baseline run finished and is recorded above ("Baseline reference"). Artifacts:
- log:        `gs://fluxtrader-train-artifacts/logs/20260723T222840Z.log`
- checkpoint: `gs://fluxtrader-train-artifacts/checkpoints/latest.pt`
  (= `checkpoints/m2_multi_20260723T222840Z_2b208de3.pt`)
- status:     `{"status":"DONE","git_sha":"2b208de...","run":"20260723T222840Z"}`

For future runs, re-capture the same way:
```sh
./scripts/gcp_status.sh
gcloud storage cat gs://fluxtrader-train-artifacts/logs/<RUN_ID>.log
```

---

## Part 3 — Infra changes (branch now, apply to next run)

RAM was never the bottleneck; this is purely CPU/wall-clock.

- `scripts/gcp_common.sh:20` — `GCP_TRAIN_MACHINE=e2-standard-2` → `e2-standard-4`
  (4 vCPU). Note: e2-standard-4 is fixed at 16 GB. For 4 vCPU with less RAM (cost),
  use `e2-custom-4-4096`.
- `scripts/gcp_env.example:13-14` — update stale "8GB is enough" RAM comment.
- `docker-compose.yml` (ml_trainer env) — add `BATCH_SIZE=128`, `OMP_NUM_THREADS=4`;
  reconcile the `SEQ_LEN=64` compose override vs. GCP's 128 (`scripts/gcp_common.sh:23`).
- `ml/train/train_m2.py` DataLoader (~lines 268-276) — pass `num_workers=2` +
  `persistent_workers=True` (arg exists at `train_m2.py:89`, defaults 0). Optionally
  add `torch.set_num_threads(N)` at startup (none exists today).
- Optional `ml/train/config.py:44` — bump default `BATCH_SIZE`.

Verify: short run (`--epochs 2`) comparing wall-clock/epoch + peak RAM
(`docker stats`) before/after; confirm larger batch doesn't degrade val metrics.
Larger batch may need a small LR nudge (`ml/train/config.py:46`).

---

## Part 4 — Data changes (branch now, run after baseline)

- **Next run pairs: BTC, ETH, SOL, DOGE, WLD, HYPE (6).** Audit passed for all six
  (see "Data audit findings" below). Set via `TRAIN_PAIRS` (`scripts/gcp_common.sh`).
  All six are enrolled in the always-on whitelist and in the dump (`DUMP_TABLES`
  covers all tables, `scripts/gcp_common.sh:44`).
- **Keep 180d for now.** 360d not useful yet — candles go back ~180d only, and
  microstructure is far shorter (below). Extending needs more candle history first.
- **Per-pair evaluation** is implemented (`ml/train/eval_m2.py`), enhanced to report
  fixed-coverage 0.05 `dir_acc / wilson_lb / n_dir` per pair. Use it to detect
  whether pooling higher-vol alts (DOGE/WLD/HYPE) degrades the majors' edge through
  the shared encoder. If it does → consider separate majors/alts models or weighting.
- Sequencing: Run 1 = 6 pairs / 180d / per-pair eval / e2-standard-4. Never change
  data AND architecture in the same run (can't attribute the change).

## Data audit findings (2026-07-24)

Queried the always-on VM Postgres (`fluxtrader-1`). Per-symbol row counts + spans:

| Pair | 1m candles | candle span | book/trades/OI/funding span |
|------|-----------:|-------------|-----------------------------|
| BTC  | 263,705 | Jan 22 → Jul 24 (~180d) | Jul 17 → Jul 24 (~7d) |
| ETH  | 263,694 | Jan 22 → Jul 24 | Jul 17 → Jul 24 (~7d) |
| SOL  | 263,683 | Jan 22 → Jul 24 | Jul 17 → Jul 24 (~7d) |
| DOGE | 259,784 | Jan 24 → Jul 24 | Jul 21 → Jul 24 (~3d) |
| WLD  | 259,746 | Jan 24 → Jul 24 | Jul 21 → Jul 24 (~3d) |
| HYPE | 259,765 | Jan 24 → Jul 24 | Jul 21 → Jul 24 (~3d) |

Key facts and their consequences:

- **All 6 pairs have full ~180d of 1m candles** (~260K rows). HYPE is valid — no
  reason to hold it out. → next run uses 6 pairs.
- **Microstructure is tiny for EVERY pair** (~3–7 days). The live collector
  (`apps/fluxtrader/lib/fluxtrader/market_data/collector.ex`) only began populating
  `orderbook_snapshots`, `market_trades`, `open_interest`, `funding_rates` recently.
  There is **no historical backfill** for book/trades/OI (only candles+funding can be
  backfilled via `ml/train/backfill_history.py`).
- **⚠️ Affects the CURRENT baseline model too.** For ~173 of 180 days, ~11 of 16
  features (`spread_bps, imbalance, micro_mid, bid_ask_vol_ratio, depth_near_imb,
  trade_count, buy_sell_imb, trade_vol, funding, oi, oi_chg`) are **zero-filled**
  (`ml/train/data/features.py:54-56,69-72,80-81,89-91`). The ~0.55 directional edge
  is therefore driven mainly by the 4 OHLCV-derived features; the orderbook edge is
  NOT meaningfully exercised yet.
- **Design decision:** the model tolerates missing microstructure via zero-fill.
  New pairs will always start with empty microstructure, so this must always work.
- **Normalization risk:** near-constant (mostly-zero) features → tiny std in per-pair
  z-score (`fit_norm_from_bundle`), which can amplify the few real values into
  spikes. Watch per-pair eval for instability.

### Follow-up work created by this finding
1. **Presence-mask features (Part 5 experiment):** add `has_book / has_trades /
   has_funding_oi` binary columns so the model distinguishes "genuinely zero" from
   "missing". Bumps `FEATURE_DIM` 16→~19 — coordinated change across
   `ml/train/data/features.py`, `ml/train/config.py` (`FEATURE_DIM`), and the model
   `input_size` (`ml/train/models/multi_horizon.py`). Requires retrain.
2. **Microstructure-rich run (weeks out):** once the collector has accumulated enough
   book/trades/OI history, do a run that actually tests the orderbook edge, and
   compare against the current candle-driven baseline.

---

## Part 5 — Model-head experiment (LATER, separate run)

Design principle: **"M2 describes the market; M3 (RL) decides the trade."** M2
outputs stay policy-agnostic (direction, confidence, forward distribution);
stops/takes/size belong to M3.

- Add **one per-horizon quantile head (p10/p50/p90 of forward return, pinball
  loss)** on the existing shared encoder (`ml/train/models/multi_horizon.py:40-69`),
  leaving current 3-class + directional heads untouched.
- Rationale for RL: quantiles/vol let the policy risk-normalize (the thing naive RL
  gets wrong). Avoid triple-barrier as the primary M2→RL input (pre-commits to fixed
  levels, constrains the policy); keep it as an eval label / rules fallback.
- Validate calibration first (do ~80% of outcomes fall in [p10,p90]?) and confirm
  the directional metric doesn't regress vs. baseline. Expect the first version to
  be rough — treat as "risk context," not precision.
- One change at a time, its own run.

---

## Execution order

1. **Now:** Part 0 (pull epoch checkpoint for UI); Part 3+4 code/config on a new
   git branch (no run launched).
2. **When current run finishes:** Part 2 (capture baseline).
3. **Then:** launch Run 1 (infra + 6 pairs + per-pair eval), compare to baseline.
4. **Later:** microstructure-rich run once book history accumulates, presence-mask
   features, and Part 5 (quantile head).

## How to stop the current run early (if ever needed)

Delete the instance directly — kills job + removes billing (boot disk) in one step:

```sh
gcloud compute instances delete fluxtrader-train --zone=me-central1-b --project=fluxtrader
```

Do NOT just kill tmux: a non-zero exit triggers `finish FAILED` which only STOPs
the VM (`scripts/gcp_train.sh:178-179`), leaving the boot disk billing.
