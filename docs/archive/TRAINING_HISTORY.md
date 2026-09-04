# Training history archive (2026-07-23 → 2026-08-21)

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

## 2026-08-26 — R0, the promote, and the wrong-gate incident that preceded it (archived from §2)

Archived when the promote completed: seed 2 is served at gate 0.6311 and the live plan now
carries only the three operational facts that outlive the incident. The section below is
the text as it stood while the re-run was still the one open action. It is worth keeping
because the failure mode — a variable set in the Mac's shell that the remote
`docker compose` never sees — is a property of the deployment path, not of that one run.

### R0 — promote seed 2. Ran 2026-08-24, shipped at the WRONG GATE, must be re-run.

Q2 settled which checkpoint: the ensemble is **not** better than its best member, so the
pre-registered "drop the idea, promote seed 2" branch fires. Q0 already measured seed 2's
gate, and because `--eval-only` never pushes a checkpoint that gate is **not** in the
bucket copy — it must be passed explicitly.

🔴 **What actually happened on 2026-08-24.** The command below was run as written and the
checkpoint *did* land, but `ML_GATE_THRESHOLD=0.6311` never reached the VM: it was set in
the Mac's shell, while the remote `docker compose` interpolates `${ML_GATE_THRESHOLD}` from
the **VM's own `.env`**, which carries `0.55`. Seed 2 therefore went live gating at **0.55**
— not 0.6311, and not even the 0.58 fallback §1.5 warns about. The promote also aborted
before printing `/health` (`curl: (56)`): `serve.py` binds its port before finishing
`torch.load`, and `curl --retry` does not treat a connection reset as transient.

Both defects are fixed in `scripts/gcp_promote.sh`: the gate is now **persisted into the
VM's `.env`** (so it also survives the next unrelated `docker compose up`), `app` is
recreated alongside `ml_inference` when the gate changes because the Elixir signal gate
reads the same variable, `/health` is polled rather than raced, and the script **exits
non-zero unless the served `gate_threshold` equals the value you asked for.**

```sh
./scripts/gcp_promote.sh --list
ML_GATE_THRESHOLD=0.6311 \
  ./scripts/gcp_promote.sh --checkpoint m2_multi_20260819T142759Z_a186182b.pt
```

**Verification is now the script's exit code**, not an eyeballed line: a clean exit means
`/health` came back `ok=true` with `gate_threshold=0.6311`. ⚠️ Do **not** wait for
`gate_source` on this promote — that field was added by C13 (commit `5b8a5e2`), and the
promote deliberately pins serve code to the *checkpoint's own* commit, which for seed 2 is
`a186182b` and predates it. On this deployment the number is the only evidence there is.
⚠️ `checkpoints/latest.pt` is now **R3b's** checkpoint
(`m2_multi_20260823T135748Z_da7ef975.pt`, the 32-unit arm). Never promote `latest`.

**Anything the simulator logged between the 2026-08-24 promote and the re-run was produced
at gate 0.55.** Seed 2's coverage at 0.55 has not been measured, but it is by construction
*wider* than the 2% that 0.6311 realizes, and §1.3's table turns negative at taker cost
somewhere between cov 0.02 and cov 0.05. Treat that stretch of sim output as void; do not
let it become M3's first training data. (One `eval_m2.py --eval-only` on seed 2 would pin
the exact coverage if it ever matters.)

**Why seed 2 and not O8's 12-pair model,** even though 12 pairs is free (§1.9): O8 is a
single seed, its gate has not been derived under C13 against a held-out re-score the way
Q0 derived seed 2's, and it is not the checkpoint any of §1.3's banked numbers describe.
Promote the banked model now; **adopting 12 pairs is a separate, later, deployment change**
(next section) and it should not be bundled into the promote that unblocks M3.


---

## 2026-08-24 — the R/O-wave run queue, as it stood before it was executed

**Superseded.** Every item below has now run: O8 (12 pairs), R2 (magnitude-weighted
directional loss), R3a/R3b (encoder capacity 128 / 32). All four came back flat or negative
and the pre-registered exit condition fired, freezing M2 at the 3-seed 5m/seq384 baseline.
The surviving conclusions live in the live plan's §1.9 and §5; this is the queue text
verbatim, kept only for the pre-registered verdict bands it was judged against.

## §2 — THE RUN QUEUE

The R-wave's experiment is done and negative (§1.6). **Features are closed; do not queue
another column set.** What is left is four things: promote the model we have, add the four
pairs the experiment control has been holding out, run the loss-function arm that targets the
diagnosed economic failure, and run the capacity probe that has never been run. Training runs
are strictly serial (§7), so this is an ordered list and the wall clock is the sum (~13h GPU
end to end).

| item | what | cost | needs a GPU? |
|---|---|---|---|
| **R0** | promote seed 2 with its measured gate — **do this first, it is 5 minutes** | promote only | no |
| **O8** | **12 pairs instead of 8** — the only remaining lever that adds *information* | ~4h GPU | **yes** |
| **R2** | magnitude-weighted directional loss — ✅ **C3 shipped, unblocked** | ~3h GPU | **yes** |
| **R3** | encoder capacity probe, 2 runs — the closing formality | ~6h GPU | **yes** |
| ~~R1~~ | ❌ **ran 2026-08-22, decisive negative** (§1.6, §4) | — | — |

🔄 **Order changed 2026-08-22, and the reason is R1's.** The previous queue put the capacity
probe first. R1 showed that on this problem extra *parameters* convert into memorization
rather than signal — `loss_tr` 1.70 → 1.13 while `loss_va` climbed. So run the levers that
add **information** before the one that adds **capacity**: O8 adds 58% more training samples,
R2 changes what the loss optimizes for, and R3 — the only one that adds modelling power — goes
last, where its most likely job is to close M2 rather than to open it.

🔴 **The exit condition, stated in advance so nobody has to relitigate it.** If O8 and R3
both come back flat (within ±0.005 plateau-mean LB of 0.5239) **and** R2 does not move gross
bps/trade at cov 0.02 by more than +5, **M2 is frozen at the §1.3 baseline and every
remaining hour goes to M3.** That is the expected outcome; these three runs exist to make it
an evidenced conclusion rather than a tired one.

### R0 — promote seed 2. Unblocked, do it now.

Q2 settled which checkpoint: the ensemble is **not** better than its best member, so the
pre-registered "drop the idea, promote seed 2" branch fires. Q0 already measured seed 2's
gate, and because `--eval-only` never pushes a checkpoint that gate is **not** in the
bucket copy — it must be passed explicitly.

```sh
./scripts/gcp_promote.sh --list
ML_GATE_THRESHOLD=0.6311 \
  ./scripts/gcp_promote.sh --checkpoint m2_multi_20260819T142759Z_a186182b.pt
```

**Verify on the `/health` line the promote prints:** `gate_source` must be `env-override`
with threshold 0.6311 — **never `config-fallback`**, which serves 0.58 and loses money in
3 of 3 seeds (§1.5). ⚠️ `checkpoints/latest.pt` is now **R1's** checkpoint
(`m2_multi_20260821T182844Z_3dd6b357.pt`) — the 25-column model whose calibration is flat
in every bin. Never promote `latest`.

### O8 — 12 pairs. Promoted to first experiment.

**Why it moved to the front.** The 8-pair set was never a considered choice about *how much
data to use* — it is a **control**. §0.2 forbids changing data and model in the same run, so
once the 8 pairs were fixed for the E-wave they had to stay fixed for every one-variable
experiment that followed, or nothing would have been attributable. The one 12-pair attempt,
E3a, was **VOID** on unrelated grounds (truncated log, pair embedding accidentally off) and
was never redone. So it is intentional as a control and overdue as an experiment.

It is now the best of the remaining levers for the reason R1 gave us: this model **cannot fit
its own training set** (`loss_tr` flat at 1.72 for ~25 epochs) yet **overfits instantly** when
handed anything easy to memorize. That combination says the binding constraint is the
signal-to-noise ratio of the data, not the capacity of the encoder. More independent data is
the textbook response; more parameters is not, and R1 measured what more parameters buys.

**What it adds.** ADA / AVAX / LINK / XRP all have full 4-year history at 5m (§1.7), so this
is ~421k samples each: **2.90M → ~4.58M, +58%**. Crypto pairs are highly correlated, so the
gain in *effective independent* samples is smaller than 58% — expect a modest effect, not a
step change. It also gives the pair embedding four more pairs to place, and a 12-pair model is
a better product regardless of what the metric says.

```sh
FEATURE_GROUPS=legacy \
  CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 \
  EARLY_STOP_PATIENCE=20 SEED=1 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,XRPUSDT \
  ./scripts/gcp_train.sh --gpu 60 384
./scripts/gcp_status.sh
./scripts/gcp_logs.sh > logs/O8.log
```

⚠️ **Re-verify the four new pairs before launching** — §1.7's row counts were measured
2026-08-18 and a backfill may have landed since (§0.1, and it also moves the split):

```sh
cat > /tmp/q.sh <<'EOF'
cd ~/trading_agent && docker compose exec -T postgres psql -U fluxtrader -d fluxtrader <<'SQL'
SELECT symbol, min(open_time)::date, max(open_time)::date, count(*)
FROM candles WHERE interval = '5m'
  AND symbol IN ('ADAUSDT','AVAXUSDT','LINKUSDT','XRPUSDT')
GROUP BY 1 ORDER BY 1;
SQL
EOF
gcloud compute ssh --zone me-central1-b fluxtrader-1 --project fluxtrader -- bash -s < /tmp/q.sh
```

Each should show ~2022-08-18 → today and ~421k rows. **If any of the four is short, drop it
rather than launching a ragged set** — a late-listing pair is exactly what made HYPE the
smallest cell in every table since.

🔴 **Comparability — read this before ranking the result.** O8 changes the **validation
population**, not just the training set: four more pairs means more val bars and a different
pair mix, so its `cov05` slice is not selecting from the same universe as §1.3's and the
headline LB is **not** directly comparable (§0.6's lesson generalized from bar-interval to
pair-mix). Rank it two ways and report both:

1. **The honest primary comparison — re-aggregate on the original 8 pairs.** C9 dumps
   `eval_preds.parquet` with a `pair` column on every run, so filter to the 8 baseline pairs,
   take the top 5% *within that subset* by confidence, and compute `dir_acc` / Wilson-LB /
   gross bps. That is an apples-to-apples read against §1.3 and needs no code and no re-run.
   The Q1 harness already does exactly this kind of re-aggregation and reproduced the logged
   tables exactly, so the method is validated.
2. **The all-12 numbers as reported**, for the record and because a 12-pair model is what
   would actually be served.

**Verify** (§0.4 plus these): `Training pairs: [...]` lists **12**; `Feature groups: legacy
-> 19 columns`; `Samples:` ≈ **4.5–4.6M** (if it is ~2.9M the pair list did not reach the
VM); `Pair embedding: ON dim=8 n_pairs=12`; `hold=48 bars`; split recorded — **it will differ
from §1.3's**, which is expected and is why comparison (1) exists.

**Verdict, pre-registered.** On the 8-pair re-aggregation, against the family's plateau mean
**0.5239** (between-seed sd 0.0032):

- **≥ 0.534, plateau ≥15 epochs, calibration monotone** → data volume is live. Replicate at
  two more seeds, then consider the remaining whitelist pairs.
- **0.527–0.534** → real but small. Bank it, adopt 12 pairs as the baseline (it is free at
  serve time), and move on — do not start a pair-count ladder.
- **≤ 0.527** → data volume is not the constraint either. Combined with R1, that is a strong
  statement that M2 on OHLCV is finished, and it should be written into §5 as such.
- **Plateau collapses (<10 epochs)** → check whether its best `loss_va` beats
  1.0398–1.0404, exactly as §1.6 reads R1. If it does not, the arm is simply worse.

### R2 — magnitude-weighted directional loss. ✅ Unblocked, C3 shipped 2026-08-22.

**What it attacks.** The model's `dir_acc` at cov 0.05 is 0.559 but that converts to only
**+8.8 gross bps/trade**, because it is systematically right on smaller-than-average moves
(§7, cost arithmetic). Ranking accuracy and P&L have come apart, and every lever tried so far
has aimed at the first. C3 aims at the second: it weights each moved bar's directional CE by
its realized `|forward return|`, normalized per (pair, horizon) so the weight is about move
size and not about which pair or which horizon (§6 C3). Unlike N3's selection-time cousin —
which failed because it ranked a statistic with ~600 effective samples — this applies per
sample over 2.3M training bars, where the estimate is not the problem.

```sh
DIR_MAG_WEIGHT=1 FEATURE_GROUPS=legacy \
  CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 \
  EARLY_STOP_PATIENCE=20 SEED=1 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 384
./scripts/gcp_status.sh
./scripts/gcp_logs.sh > logs/R2.log
```

⚠️ **If O8 lands positive first, run R2 on the 12-pair set instead** — one variable at a time
means R2's control must be whatever the baseline is when it launches, not whatever it was
when this was written (§0.2).

**Verify** (§0.4 plus these): `knob DIR_MAG_WEIGHT=1` in the resolved-knobs echo;
`Magnitude-weighted directional loss: ON (power=1.0 clip=5.0)`; the three `dir-mag <h>m:`
lines, where **`scale` should be ~0.8–1.0 and `at_clip` should be a few percent at most** — an
`at_clip` above ~10% means the clip is binding on a large minority of bars and the weight has
become closer to a step function than to `|r|`, which is a different experiment; `mean|r|`
should rise with the horizon (60m < 240m < 1440m) and be in the tens-to-hundreds of bps.

**Verdict, pre-registered — and note this one is NOT ranked on LB.** R2 is a loss-function
change aimed at economics, so rank it on **gross bps/trade at cov 0.01 / 0.02 / 0.05** from
the `Fixed-coverage P&L` table, against the family's pooled **+19.4 / +22.0 / +8.8**. Report
plateau-mean LB alongside as a guard, not as the decision.

- **cov 0.02 gross ≥ +27 with LB no worse than 0.517** (i.e. within ~2 between-seed sd of
  0.5239) → the lever works: it bought economics without giving up ranking. Replicate at two
  more seeds.
- **cov 0.02 gross +22 to +27** → inside noise on ~1,780 trades. Not evidence. Do not run the
  `POWER=0.5` arm on the strength of it.
- **Gross improves but LB drops below ~0.510** → it traded ranking for magnitude. That is a
  real finding and it belongs to M3's sizing problem, not to M2 — record it and stop.
- **No movement in either** → the aux head's weighting is not the constraint. Closed.

### R3 — encoder capacity on the current baseline. **Last, and most likely a closer.**

**Why this is not barred by §5.** §5 closed capacity sweeps twice, and both closures are
now stale for the same reason. The first rested on O3 (a *context-length* run at 15m, not a
capacity run) and on N2 (a GBT, which says nothing about LSTM width). The second rested on
§0.3's "a single run cannot resolve anything under 0.04 LB" — **and that is no longer
true.** The plateau-restricted mean (§0.3, 2026-08-22) has a between-seed sd of **0.0032**
across the three baseline seeds (0.5235 / 0.5273 / 0.5209), so a single well-plateaued run
now resolves a ~0.01 effect. The measurement improved; the lever is re-openable on that
basis and on no other. It is also the only structural knob in `config.py` that has **never**
been varied on the 5m/seq384 baseline — `hidden_size=64, num_layers=2, dropout=0.2` were
inherited, not measured.

**Two runs, one variable each, both against §1.3.** Everything else is byte-identical to
the baseline, including `FEATURE_GROUPS` left **unset** (it defaults to the 30-column set,
so it must be pinned to `legacy` — see the verify list).

```sh
# R3a — double the width
FEATURE_GROUPS=legacy HIDDEN_SIZE=128 \
  CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 \
  EARLY_STOP_PATIENCE=20 SEED=1 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 384
./scripts/gcp_status.sh
./scripts/gcp_logs.sh > logs/R3a.log

# R3b — half the width (only after R3a has FINISHED; runs are serial, §7)
FEATURE_GROUPS=legacy HIDDEN_SIZE=32 \
  CANDLE_INTERVAL=5m PAIR_EMBED_DIM=8 \
  EARLY_STOP_PATIENCE=20 SEED=1 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 384
./scripts/gcp_status.sh
./scripts/gcp_logs.sh > logs/R3b.log
```

**Why both directions and not a ladder.** One run tells you nothing about the shape of the
curve. Two bracketing runs do: baseline in the middle, one arm up, one arm down. If the
plateau mean is flat across 32 / 64 / 128, capacity is not the binding constraint and the
question is answered for good. A monotone rise toward 128 would be the only result that
justifies a third run.

**Verify** (§0.4 plus these):
`Feature groups: legacy -> 19 columns` — **if it says 25 or 30 the run is not a baseline
comparison**; `hidden_size=128` (resp. `32`) on the architecture line; `Feature columns:
19`; `12/19 CONSTANT`; `Samples:` ≈ 2.9M; `hold=48 bars`; `Pair embedding: ON dim=8`;
split recorded.

**Verdict, pre-registered.** Rank on **plateau-restricted mean cov05 LB** against the
family's 0.5239 (between-seed sd 0.0032), report the all-epoch mean alongside, and require a
plateau of ≥15 epochs and a monotone `emp_up` table (§3 item 3c).

- **Either arm ≥ 0.534 with a ≥15-epoch plateau and monotone calibration** → capacity is
  live. Replicate that arm at two more seeds before believing it.
- **Both arms within ±0.005 of 0.5239** → capacity is not the constraint. **M2 is done.**
  Record it in §5 as closed *on measurement* this time, and stop.
- **Either arm's plateau collapses below ~10 epochs** → read it the way §1.6 reads R1:
  check whether its *best* `loss_va` beats 1.0398–1.0404. If it does not, the arm is worse,
  full stop, and no regularization follow-up is warranted.

### Still queued behind that, and only if O8, R2 or R3 reopens M2

- **O7 — triple-barrier redo.** Blocked on C4b, wider barriers (target ~30–40% flat), and a
  pinned dataset. A *label* lever — also unaffected by §1.6.
- **O5 — L2 ladder feature audit. Still demoted.** Book-derived columns are constant across
  99% of the train window and get zeroed. Revisit when book coverage passes ~6 months; the
  60-day milestone for BTC/ETH/SOL is ≈2026-09-15, so this is a 2027 item.

### For M3, not for M2 — and after R0 this is the main line of work

§1.8's `btc_absret_1d` finding is an **input to the policy milestone**, not a run in this
queue. When M3 starts, its observation vector should carry trailing market-move magnitude
(BTC |ret| over 24h, or the pooled-universe equivalent) alongside M2's per-horizon
probabilities, because conditioning on it moves the top-2% slice from +22.0 to +54.9 gross
bps/trade. Do **not** implement it as an M2 gate (§1.8, §5). With features closed and
capacity about to be, this is where the remaining upside in the project lives.

---



---

## 2026-08-22 — §1.6 as written after Q3, before R1 ran

Superseded by R1. Kept because it is the reasoning that *justified launching R1*, and
because its "the run was mis-specified, not the lever dead" reading was a reasonable call
on the evidence available at the time. R1 then tested exactly that reading and refuted it:
R1's best validation loss is worse than the baseline's at every epoch including epoch 1, so
the "add regularization and retry" escape hatch this section opened is closed. See the live
plan's §1.6 for the conclusion that replaced it.

### 1.6 🔴 The feature expansion failed, and the reason is fitting speed, not signal

Q3 was the one-variable test of §1.6-as-it-stood (the model sees six live columns per bar).
It added eleven candle-derived columns — `ret_1h/4h/1d`, `vol_1h/4h/1d`, `btc_rel_ret_1h`,
`beta_btc_1d`, `xs_rank_1h`, `xs_disp_1h`, `has_market` — and lost:

| | 5m family (3 seeds, 19 cols) | Q3 (30 cols) |
|---|---:|---:|
| mean-of-epochs cov05 LB | **0.5219 ± 0.0014** | **0.5003** (n=28) |
| brier (240m, moved bars) | 0.250 | **0.2897** |
| calibration bin table | monotone in `emp_up` | **inverted** (0.495 → 0.465 as `mean_pred` 0.35 → 0.75) |
| ungated 3-class accuracy | 0.472 / 0.473 | 0.4553 |
| gross bps/trade @cov 0.01 / 0.02 | +19.4 / +22.0 | +19.7 / +17.6 |

Two independent pre-registered criteria reject it: LB ≤ 0.525 (§2's Q3 rule) and a
non-monotone `emp_up` (§3 item 3c).

🔴 **But the training trajectory says the run was mis-specified, not that the lever is
dead.** Every baseline run sits on a long plateau — `loss_tr` ≈ 1.72, `loss_va` ≈ 1.041 —
and *every good epoch lives inside it*. Q3 left the plateau at epoch 5:

| run | cols | plateau epochs | `loss_tr` first → last | mean LB, plateau | mean LB, all |
|---|---:|---:|---|---:|---:|
| O2 (s1) | 19 | 24 | 1.7284 → 1.2625 | 0.5235 | 0.5248 |
| P0-seed2 | 19 | 21 | 1.7288 → 1.4043 | 0.5273 | 0.5206 |
| P0-seed3 | 19 | 26 | 1.7286 → 1.2070 | 0.5209 | 0.5203 |
| **Q3** | **30** | **5** | **1.7210 → 1.0971** | **0.5000** | **0.5003** |

(plateau = epochs whose `loss_va` is within 0.02 of that run's minimum.) With 19 columns
the model *cannot* fit the train set — 1.72 flat for 25 epochs. With 30 it fits it, down to
1.10, while `loss_va` climbs monotonically from epoch 5 onward. Q3's selected epoch 8 is
already outside its own plateau, which is exactly why its ranking survives (top-5% dir_acc
0.551) while its probabilities do not. **Nothing in the run's configuration was changed to
absorb a 58% wider input** — same `DROPOUT`, `WEIGHT_DECAY`, `LR`, `HIDDEN_SIZE`.

Note this cuts both ways and neither reading is free: extra columns enable memorization
whether they carry signal or not, so the fast overfit is *not* evidence that the features
are informative — it is only evidence that the test did not measure what it intended to.

🔴 **One of the eleven columns is numerically defective and a second is merely fat-tailed**
(§6 C15) — both in the market-context group:

- **`beta_btc_1d` is degenerate for BTCUSDT.** Beta of BTC against itself is identically
  1.0. The column is 1.0 everywhere except a handful of warm-up / sub-floor-variance bars
  set to 0.0, which makes its raw std ~1e-3 — above the `1e-8` CONSTANT detector, so it is
  *not* zeroed — and the per-pair normalizer then turns those few bars into a **590σ**
  spike, winsorized at ±50. BTC's worst tail was 66σ (`hl_range`) before C12. The
  `ok_var = b_var > 1e-12` guard at `ml/train/data/features.py:436` is ~6 orders of
  magnitude below a real `var(ret_1)` (~2.3e-6 at 5m), so it floors nothing in practice.
- **`xs_disp_1h` carries a 122σ tail**, identical for every pair at a given bar, and became
  the worst column for ETH, SOL and ZEC (was 75 / 81 / 85σ on `hl_range`). 🔵 **On
  measurement this is a genuine fat tail, not a defect** — the tail is *populated* (347 rows
  beyond 5σ, 44 beyond 10σ on the val window), which is what a real market-wide volatility
  event looks like and is the same class as `hl_range`'s long-accepted 212–364σ. It is
  correctly winsorized at ±50 and no change was made to it (§6 C15.4). The reason to drop it
  is instead that Q1 ranks cross-sectional dispersion the *least* informative of nine
  observables tested (§1.8): C12 added the dispersion family, which is noise, and omitted
  the market-move-magnitude family, which is the one thing that separates.

The legacy columns are byte-identical between O2 and Q3 (`hl_range` tails 212.8 → 212.9,
363.5 → 363.8), confirming the change is isolated to the new columns.


---

## P-wave detail, as written 2026-08-21 — conclusions carried forward, narrative archived 2026-08-22

Moved here from the live plan on 2026-08-22. All three of its conclusions survive; only the
supporting detail was archived to keep the live plan short. The surviving statements are:
the 5m/seq384 3-seed baseline (live plan §1.3), "the resolution ladder is closed at 5m"
(§5), and "an absolute confidence gate is not a well-defined operating point" (which C13
shipped as a coverage target, and Q0 exercised).

### P2 — 1m bars, the full negative result

`logs/P2.log`, run `20260820T100042Z`, ckpt `m2_multi_20260820T100042Z_a186182b.pt`.
Valid: `knob CANDLE_INTERVAL=1m`, `seq 768` (12.8h), `PAIR_EMBED_DIM=8`, `SEED=1`, embed ON,
**14,507,307 samples** (11.6M / 2.9M — the plan predicted 8–9M and was low), `hold=240 bars`,
split re-recorded, early stop at epoch 38. Launched as a direction probe, not an attribution.

| | 5m family (3 seeds) | P2 (1m) |
|---|---|---|
| mean-of-epochs cov05 LB | 0.5219 ± 0.0014 | 0.5256 (n=38) — *inflated, 5× val rows* |
| **cov05 `dir_acc`** (the honest comparison) | 0.563 / 0.564 / 0.549 → **0.559** | **0.561** |
| gross bps/trade @cov 0.01 / 0.02 | **+19.4 / +22.0** | **+2.6 / +8.5** |
| brier (240m, moved bars) | 0.250 | **0.323** |
| ungated 3-class accuracy | 0.472 / 0.473 | 0.443 |
| wall clock | 2h36m / 3h17m | **20h16m** |

The calibration failure was the decisive finding: P2's probability output spread across the
entire [0,1] range — 160k bars in `[0.00,0.10)`, 162k in `[0.90,1.00]` — with `emp_up`
between **0.448 and 0.505 in every single bin**. The serial sim was meaningless at any gate
(80% coverage at `GATE_THRESHOLD=0.58`, net_ret −18). The strict caveat — that 1m *with* a
32h window (seq 1920) is untested — was noted and dismissed as unaffordable at 5× P2's
already-20h run.

### The serial-gate seed instability that produced C13

Serial-position sim (`hold=48 bars`, 1 position/pair, 14bps taker):

| seed | gate 0.58 (served) cov / net_ret / Sharpe | gate 0.62 cov / trades / net_ret / Sharpe |
|---|---|---|
| 1 (O2) | 4.8% / **−1.31** / −1.22 | 1.2% / 548 / **+0.99** / **+1.41** |
| 2 | 6.1% / **−0.91** / −0.85 | 2.5% / 595 / **+0.10** / +0.15 |
| 3 | 5.4% / **−0.34** / −0.31 | 1.7% / 497 / **+0.23** / +0.41 |

What replicated: the served gate of 0.58 loses money in 3 of 3 seeds and 0.62 is profitable
in 3 of 3. What did not: the magnitude — O2's +0.99 / Sharpe 1.41 was an epoch-selection
artifact, and the honest expectation was ≈ +0.4 net_ret, Sharpe ≈ 0.6. The reason the two
tables disagreed (fixed-coverage replicated, serial did not) is that a fixed *confidence
threshold* compares whatever fraction of each seed's confidence distribution sits above it —
1.2% / 2.5% / 1.7% here, 0.8% for O3 and 80% for P2. That is what made the gate a coverage
target in C13.

## Q-wave, as written 2026-08-22 — the feature expansion came back negative

The full narrative of the four Q items. The live plan carries the conclusions; this is the
reasoning and the raw numbers.

**Q0** (`logs/Q0.log`, run `20260821T083737Z`) re-scored seed 2 alone under C13 and derived
its coverage-targeted gate: `conf >= 0.6311` at target coverage 0.02, realizing dir_acc
0.578 / +18.68 gross bps/trade / +4.68 net at taker. Because `--eval-only` never pushes a
checkpoint, the gate was written only into the VM's local copy — the bucket checkpoint still
carries none, so the promote needs `ML_GATE_THRESHOLD=0.6311` passed explicitly.

**Q2** (`logs/Q2.log`) averaged the three seeds' probabilities. Matched against Q0 — the same
eval code on the same val split, which is the only fair comparison — the ensemble won on
ranking by an amount inside noise and lost on economics at four of five coverages:

| metric (240m, same split) | seed 2 alone (Q0) | 3-seed ensemble (Q2) |
|---|---:|---:|
| cov05 dir_acc / LB | 0.566 / 0.559 | 0.568 / 0.561 |
| cov02 dir_acc / LB | 0.578 / 0.568 | 0.581 / 0.570 |
| brier (240m, moved) | 0.2503 | 0.2498 |
| gross bps @cov 0.01 | +17.03 | +23.18 |
| gross bps @cov 0.02 | **+18.68** | +10.61 |
| gross bps @cov 0.05 | **+15.13** | +11.87 |
| gross bps @cov 0.10 | **+6.73** | +0.63 |
| gross bps @cov 0.20 | **+3.17** | −0.24 |
| net@taker at its own served gate | **+4.68** | −3.39 |

The pre-registered rule was "no better than the best member → drop the idea, promote seed 2".
brier moved by 0.0005 and dir_acc by 0.002; both are noise, and the P&L is worse. The one
real improvement is that averaging removed seed 2's misbehaving `[0.70,0.80)` calibration bin
(1,967 bars at mean_pred 0.728 vs emp_up 0.569), which is worth remembering if calibration
ever becomes the binding constraint. The mechanism behind the P&L loss is worth recording:
averaging probabilities pulls every bar toward the consensus, which preserves the *order* of the
directional signal but compresses exactly the outlier-confident bars where the large moves
are — the ensemble ranks direction slightly better and ranks economics distinctly worse.

**Q3** (`logs/Q3.log`, run `20260821T…`) — the 30-column feature run. Valid on every §0.4
check: `Feature columns: 30`, `[market] cross-pair context filled for 8/8 pairs` with
`mean has_market=1.000`, `Samples: 2,902,214`, `hold=48 bars`, `SEED=1`, embed ON dim=8,
split recorded (train → 2025-12-11 15:20, val → 2026-08-20 13:35), no new column in the
CONSTANT list beyond the two documented ones. It came back clearly negative: mean-of-epochs
cov05 LB **0.5003 ± 0.0176 (n=28)** against the family's 0.5219 ± 0.0014, and the calibration
bin table is inverted (`emp_up` falls from 0.495 to 0.465 as `mean_pred` rises from 0.35 to
0.75; brier 0.2897 vs 0.250) — which by the §3 rule rejects the run on its own.

The diagnostic that matters is the training trajectory, and it is what the live plan carries
forward. Baseline runs sit on a long flat plateau — `loss_tr` ≈ 1.72 and `loss_va` ≈ 1.041
for 21–26 epochs — and every good epoch lives inside it. Q3 left that plateau at epoch 5:

| run | cols | plateau epochs | `loss_tr` first → last | mean LB, plateau | mean LB, all epochs |
|---|---:|---:|---|---:|---:|
| O2 (s1) | 19 | 24 | 1.7284 → 1.2625 | 0.5235 | 0.5248 |
| P0-seed2 | 19 | 21 | 1.7288 → 1.4043 | 0.5273 | 0.5206 |
| P0-seed3 | 19 | 26 | 1.7286 → 1.2070 | 0.5209 | 0.5203 |
| **Q3** | **30** | **5** | **1.7210 → 1.0971** | **0.5000** | **0.5003** |

(plateau = epochs whose `loss_va` is within 0.02 of the run's minimum.) Q3's selected epoch 8
is already outside its own plateau, which is why its probabilities are garbage while its
top-5% ranking still holds up. Restricting to plateau epochs does not rescue it — 0.5000 on
n=5 — so the negative result is real and not an artifact of averaging in degraded epochs.

## O-wave, as written 2026-08-19 — superseded by the P-wave (2026-08-21)

Moved here from the live plan on 2026-08-21. **Three of its four claims did not survive
seed replication.** Read the live plan §1.2–§1.5 for what actually holds; this section is
kept only to show what a single seed made us believe and why.

What the P-wave changed:

- **"Window 2 inverts between 15m and 5m models"** — wrong. O2's low window-2 (0.535) was
  seed noise; seeds 2 and 3 score 0.618 and 0.592 there, in line with the 15m models.
- **"The 5m model is less regime-locked (spread 0.096 vs F4's 0.160)"** — mostly wrong.
  Seeds 2/3 spread 0.139 and 0.130. The 5m family averages ~0.12, a mild narrowing at most.
- **"Serial P&L +0.99 at gate 0.62, Sharpe 1.41"** — did not replicate in magnitude.
  Seeds 2/3 book +0.10 (Sharpe 0.15) and +0.23 (Sharpe 0.41) at the same gate. Only the
  *sign* replicated, and the reason is in live §1.5: an absolute confidence gate selects a
  different coverage in every seed.
- **What did replicate:** the mean-of-epochs LB level, and the fixed-coverage P&L at the
  top 1–2% of confidence — pooled +19.4 / +22.0 gross bps/trade across three seeds against
  O2's own +24.5 / +22.1.

### 1.2 The regime structure is real but softer, and partly a model artifact

`cov05 wilson_lb` on the primary 240m head, val window split into four ~2-month blocks:

| window | period | F4 (15m) | N3 (15m) | N2 (GBT, 15m) | **O2 (5m)** |
|---|---|---:|---:|---:|---:|
| 1 | 2025-12 → 2026-02 | 0.486 | 0.499 | 0.492 | **0.573** |
| 2 | 2026-02 → 2026-04 | **0.617** | **0.621** | **0.574** | 0.535 |
| 3 | 2026-04 → 2026-06 | 0.457 | 0.419 | 0.415 | 0.500 |
| 4 | 2026-06 → 2026-08 | **0.584** | **0.613** | 0.397 | **0.596** |

The previous version of this section claimed three independent models agreed on where the
edge lives, and treated that as the only unambiguously real effect in the dataset. O2
breaks it. What actually survives all four models is narrower:

- **Window 3 is the worst window** (all four), and **window 4 is a good one** (three of
  four; N2 is the exception).
- Windows 1 and 2 are **model-dependent**: they invert between the 15m models and the 5m
  model.

The "agreement" was among three models that shared a 15m bar grid and the same 771k
training samples — a shared blind spot reads as consensus. And O2's window spread is
**0.096** against F4's **0.160**: the higher-resolution model is *less* regime-locked, not
differently regime-locked, which is what you would expect if part of the window structure
was capacity rather than market state.

This does **not** kill the regime-analysis item — a 0.10 spread is still four to six times
the run-to-run noise of §0.3, and the top window is still worth ~5× maker cost. It changes
the question from "find the observable that flags the good regime" to "how much of this is
market state and how much is the model", and it means the analysis must run on **O2's**
prediction dump, not F4's. See **P1**.

### 1.3 🟢 Current reference numbers — O2 is the new baseline

Run `20260818T185438Z` · ckpt `m2_multi_20260818T185438Z_8c4b2a03.pt` · `logs/O2.log`
Config: `CANDLE_INTERVAL=5m`, seq 384 (= 32h context), `PAIR_EMBED_DIM=8`, `SEED=1`,
`EARLY_STOP_PATIENCE=20`, fixed labels, 8 pairs, horizons 60/240/1440, primary 240.
Split: `train [2022-08-19 21:45 → 2025-12-09 09:45]`, `val [2025-12-09 09:45 → 2026-08-17 18:35]`,
2,895,782 samples (2,316,625 / 579,157). Early stop at epoch 34, **selected epoch 14**.

| | 1h | **4h (primary)** | 24h |
|---|---:|---:|---:|
| cov05 dir_acc / Wilson-LB (selected epoch) | 0.544 / 0.537 | **0.563 / 0.557** | 0.582 / 0.575 |
| cov05 LB, mean ± sd over epochs (§0.3) | — | **0.525 ± 0.015** (n=34) | — |

**4h fixed-coverage P&L — the table that matters** (`net` is exactly `gross − trades ×
cost`, so no re-run changes fees):

| cov | trades | gross bps/trade | net @5bps maker | net @14bps taker | F4 gross, same cov |
|---|---:|---:|---:|---:|---:|
| 0.01 | 469 | **+24.50** | **+19.50** | **+10.50** | +2.61 |
| 0.02 | 708 | **+22.11** | **+17.11** | **+8.11** | +6.53 |
| 0.05 | 1361 | +3.50 | −1.50 | −10.50 | +6.50 |
| 0.10 | 2577 | −5.16 | −10.16 | −19.16 | −2.96 |
| 0.20 | 4489 | −3.13 | −8.13 | −17.13 | −4.38 |

The ordering is monotone-decreasing in confidence, which is what makes it usable — the
model's confidence ranks its own economics correctly. The matched-trade-count comparison
is the cleanest one available: **O2 at 469 trades earns +24.50 bps/trade where F4 at 466
trades earned +6.53.**

Serial-position sim at the same checkpoint (`hold=48 bars`, 1 position/pair):

| gate | coverage | trades | dir_acc | net_ret @14bps taker | win | Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| 0.58 (served) | 4.8% | 1318 | 0.565 | −1.31 | 0.502 | −1.22 |
| **0.62** | 1.2% | 548 | 0.556 | **+0.99** | 0.586 | **+1.41** |

⚠️ **The served gate is wrong for this model.** `GATE_THRESHOLD=0.58` is tuned to F4's
confidence scale; on O2 the profitable operating point is **0.62**. Do not promote O2
without moving the gate — see **C13** in §6.

Other health checks, all better than F4's:

- **Side split is balanced** — up 0.563 / down 0.563 at cov 0.05 (F4: 0.547 / 0.528). The
  model is no longer meaningfully long-biased.
- **Calibration improved but is still over-confident** — the `[0.60,0.70)` bin has
  `mean_pred 0.624` vs `emp_up 0.574` (F4: 0.636 vs 0.547). Still the wrong direction for
  sharpening; §5's entry stands.
- **No calendar confound** — book-era cov05 LB 0.545 vs pre-book 0.561; the edge is not
  concentrated in the 31-day book window.
- **Beats both trivial baselines** — momentum (sign of trailing 48 bars) cov05 LB 0.460;
  buy-and-hold pooled deeply negative (only HYPE and ZEC are positive over the window).

**Caveats that bound how much of this to believe** — all three are addressed by P0:

1. **n = 1 seed.** §0.3's own rule says a single run cannot resolve much; this run clears
   the bar on mean-of-epochs, but the P&L table does not have an equivalent error bar.
2. **The P&L is measured on an order-statistic epoch.** Epoch 14 was selected as max LB,
   +2.15 sd above the run's own mean. A replicate's epoch-14-equivalent will be worse.
3. **The +24.5 bps cell has ~470 trades across 8 correlated pairs.** With per-trade sd of
   roughly 150bps at 4h, the standard error is ~7bps if trades were independent and more
   like ~11bps once cross-pair correlation is accounted for. That is a ~2σ result, not a
   4σ one. It is the most promising cell in the project and it is not yet banked.

F4 (`20260817T221811Z`, `logs/O0-f4-rescore.log` for its re-scored tables) remains the
comparison point and is still reachable at
`checkpoints/m2_multi_20260817T221811Z_94614795.pt`.

### 1.4 O3 — longer context is worse; architecture is closed again

`logs/O3.log`, run `20260819T021020Z`. Valid: `seq=256`, `CANDLE_INTERVAL=15m`,
`PAIR_EMBED_DIM=8`, 964,483 samples, embed ON, split re-recorded. One variable vs F4.

Mean-of-epochs cov05 LB **0.4925 ± 0.0227** (n=24) against F4's **0.5058 ± 0.0162**. Not
merely flat — the per-epoch series drifts monotonically *down* (≈0.52 through epoch 5,
≈0.47 from epoch 16 on) and the selected epoch is 4 of 24. The failure signature is
consistent: coverage at the served 0.58 gate collapsed to **0.8%** (F4: 4.9%), and the side
split went lopsided at cov 0.05 — 6,266 down-gated vs 3,379 up-gated, with the **up side at
0.499, exactly coin flip**.

The pre-registered verdict fires the negative way: **the LSTM already has all the context
it can use at 15m.** N2's GBT gap is therefore about the GBT's 114-column static summary
throwing away information, not about recurrence being essential. Encoder capacity, context
length, and full architecture swaps all go back in the closed pile (§5). **Do not write a
transformer.**

Read O2 and O3 together and the shape is clear: **more, finer observations helped; more
window did not.** The model is limited by what each timestep tells it, not by how many
timesteps it sees.

### 1.5 The "flat training loss" diagnostic is falsified — stop using it

The previous plan reasoned that `loss_tr` barely moving (1.7318 → 1.7101 over F4's 11
epochs) proved the model was not data-starved and the bottleneck was entirely features.
O2 ran that experiment and the reasoning does not hold. O2's `loss_tr` was **equally flat
for its first 22 epochs** (1.7284 → 1.7184), then descended only because memorization
started at epoch 23, with `loss_va` diverging in lockstep (1.0404 → 1.3031 by epoch 34).
By the loss-curve indicator, O2 looked exactly like F4 in the region where its selected
epoch lives — and it was materially better.

**On a near-noise-floor task the training loss is dominated by the irreducible term and
carries no information about whether more data helps.** Judge the data lever on the
validation-selection metric. This also means O2's own late-epoch descent is not a reason
to add regularization: the selection metric already ignores those epochs.


---



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

---

## Superseded: §1.10 as written on 2026-08-27, before T6

⚠️ **Read the current `NEXT_TRAINING_PLAN.md` §1.10 instead.** This is the T-wave's
own write-up, kept because it is the worked example behind three of the project's
standing methodological rules. **Its central interval is the wrong estimand**: the
"−0.85 bps, 95% CI [−6.8, +5.1]" below is a day-weighted, shared-days-only statistic
reported next to trade-weighted means, and on the matching trade-weighted estimator
the interval is [−12.0, +11.5] — so the "+7.5 is outside that interval" conclusion
below does not hold. Do not quote any number from this section.

### 1.10 🟡 The universe: the +7.5 bps was one seed's luck, but 12 pairs is NOT refuted

**Two amendments on 2026-08-27, and you need both.** The first replaced a single-seed "+7.5
net bps/trade" headline with a three-seed replication that did not reproduce it. The second —
written the same evening after the first over-reached — is that **failing to replicate a
positive claim is not the same as showing the thing is worse**, and only the first of those
is supported here.

**Where it stands: the traded universe is an OPEN question, not a closed one.** The evidence
below excludes the original +7.5 claim and does not exclude a real benefit of up to +5 bps.
Nothing about the pair set should be closed on it, in either direction.

M3-2's winner (cov 0.02, hold 240m, sized by `btc_absret_1d` bar-quintile, no concurrency
cap), scored twice on the *same* three 12-pair dumps — T1, T2 and O8 — once restricted to
the 8 baseline pairs and once on all 12:

| universe | trades | tr/day | gross | **net @14 taker** | net @5 maker | Sharpe | maxdd | clusters |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| the 8 baseline pairs | 1,645 | 2.02 | +27.99 | **+9.29** | +21.31 | 0.67 | −2.83 | 169 |
| all 12 pairs | 2,475 | 3.05 | +27.71 | **+9.00** | +21.03 | 0.55 | −4.53 | 187 |

| seed | run | base-8 net@14 | 12-pair net@14 | universe effect |
|---|---|---:|---:|---:|
| O8 (was the only evidence) | `20260822T012619Z` | +13.93 | **+21.44** | **+7.5** |
| T1 | `20260827T050701Z` | +7.81 | +5.94 | −1.9 |
| T2 | `20260827T114122Z` | +4.91 | **−2.70** | −7.6 |

#### 🔴 What this DOES establish

**The +7.5 bps is dead.** Paired on the exit-day cluster — the only correct way to difference
two policies scored on overlapping days — the effect is **−0.85 bps with a 95% CI of
[−6.8, +5.1]** across 167 shared days. +7.5 is outside that interval. O8 reproduces its own
published numbers exactly, so nothing was miscomputed; it was **one draw from a distribution
far wider than the effect it appeared to show**, which is exactly what §0.3 keeps warning
about. That is a real finding and it is what the 8h of GPU bought.

#### 🔴 What this DOES NOT establish, and what an earlier version of this section wrongly claimed

**It does not show 12 pairs is worse.** The interval spans [−6.8, +5.1]. A benefit half the
size of the original claim is entirely compatible with this data.

**The P5 failure that an earlier draft used to "reject" 12 pairs is a coin flip.** P5 asks
that all three seeds be individually pooled-positive. Day-bootstrapped 2,000 times:

| universe | P(at least one seed pooled-negative) |
|---|---:|
| the 8 baseline pairs — which **passed** P5 | **53.8%** |
| all 12 pairs — which **failed** P5 | **58.6%** |

**The incumbent fails this criterion more often than not.** Per-seed cluster-robust SEs are
17.6–30.2 bps on 102–161 clusters, so a per-seed *sign* test is nearly uninformative. P5
earns its place in M3_PROTOCOL as a screen against configurations that only work on one seed
during a 40-config *search*; it does not have the power to arbitrate a deployment choice
between two universes, and it should not have been used for that.

**The comparison was also tilted toward 8 pairs.** M3-2's winning spec was searched on the
8-pair universe (`cli.py`'s `cmd_search` passes `pairs=dumps.BASE8`), *including* its choice
of `max_concurrent=None`. It was then applied verbatim to 12 pairs. The incumbent got tuning
the challenger never got — so part of what is being measured is "does an 8-pair-tuned policy
transfer", not "is a wider universe better".

#### 🟡 The one effect that is structural rather than noise, and it is a risk finding

Widening 8 → 12 pairs raised the pooled trade count 50% (1,645 → 2,475) but the number of
independent exit days only 11% (169 → 187), while max drawdown grew **−2.83 → −4.53** and the
clustered SE widened 20.5 → 23.2. **Extra pairs buy correlated trades inside existing
clusters, not independent days.** The mechanism is plain: these instruments are highly
correlated, the policy gates on a BTC-derived regime column, so it fires across the universe
at the same moments — and the winner spec has **no concurrency cap**, so a wider universe
means more simultaneous exposure to one move.

🟢 **Read that as an argument about position sizing, not about the pair set.** It says a
12-pair universe needs its concurrency cap re-examined; it does not say the four instruments
are bad. **This is the most decision-relevant thing the T-wave produced.**

#### What the per-pair texture says, with the standing caveat

Inside the wide run, the four new pairs are the profitable half: **+15.99 net on 841 trades
against the base-8's +5.41 on 1,634.** §1.3's rule still applies — per-pair numbers do not
replicate across seeds, and this is **not** a licence to cherry-pick pairs. But it is not
nothing either, and an honest reading is that the wide universe's problem is concentration
and tuning, not the instruments.

#### Two caveats that survive unchanged

- **Window 3 is still not fixed.** Its net stays around −18 to −22 on 143–168 trades and P3
  fails on both universes. The w3 hole is a shortage of *confident bars*, not of instruments.
- **12 pairs does not move the certification problem** (M3_PROTOCOL §2). Only forward time does.

#### Reproduce all of it

```sh
./scripts/m3.sh -m m3 validate     # acceptance tests first, always
./scripts/m3.sh -m m3 universe --runs 20260827T050701Z,20260827T114122Z,20260822T012619Z
```

🟢 **The methodological lesson, which is the durable output of the T-wave — and it cuts both
ways.** A headline "+7.5 bps, second-largest effect in the project" came from a within-run
comparison that was methodologically clean (same checkpoint, same seed, same calendar, only
the universe varying) and was still wrong, because the between-seed spread is larger than the
effect. **A clean comparison on one seed is a hypothesis, not a result.** But the correction
was then over-applied: a −0.3 bps point estimate and a coin-flip criterion were briefly
written up as a rejection. **A negative result needs the same scrutiny as a positive one —
report the CI on the *difference*, and check that a criterion has the power to decide before
letting it decide.**



---

# M3's status-block narrative, moved out of `docs/M3_PLAN.md` on 2026-09-04

**This is HISTORY. Do not act on it.** It is the "What M3-x established" blocks and the
"plan from here" ordering that used to sit in `M3_PLAN.md` §0.0, moved here under
RULES_REVIEW §6.3 so the live plan holds only what is currently true. Every surviving
conclusion is in that file's §2 per-step entries, and every open item is in `BACKLOG.md`.

⚠️ **Everything below was measured PRE-REPAIR** (before the 2026-09-04 candle repair). The
repaired re-score is `M3_2_RESULTS_REPAIRED.md` / `M3_3_RESULTS_REPAIRED.md`; it moved the
headline numbers by roughly a bar's width and changed no conclusion.

### What M3-0a established (2026-08-26)

**Both acceptance tests pass, so the harness is trustworthy and §1.4's risk #6 is closed.**

1. **Fixed-coverage reproduction: 15 of 15 cells match to the digit.** Every seed at every
   coverage reproduces the trainer's own logged `trades / gross_bps / win` — and the pooled
   trade-weighted table reproduces §1.3 exactly (1,081 / 1,783 / 3,718 / 7,104 / 13,462
   trades at +19.38 / +22.03 / +8.91 / +1.89 / −0.00 bps).
2. **The regime ladder is rebuilt and reproduces §1.8.** Quintiles of `btc_absret_1d` over
   the pooled cov05 trades: **−1.9 / −13.9 / +10.2 / +18.0 / +34.2** bps against the
   published −3.4 / −15.3 / +10.1 / +17.4 / +35.5, with `dir_acc`
   0.521 / 0.499 / 0.547 / 0.580 / 0.616 against 0.517 / 0.494 / 0.545 / 0.579 / 0.618.
   The rebuild derives the Q5 boundary at **0.0432** (published 0.0431), selecting **5.218%**
   of bars (published 5.2%). Per-seed Q5: +32.6 / +30.8 / +38.7 against +34.8 / +32.5 / +38.7.
   The residual ≈1bps gap is 24 pooled trades whose 24h lookback is incomplete at the start
   of the validation window; they are dropped rather than zero-filled.
3. **`fwd_ret` compounding re-verified** at 6.34e-09 max abs difference (§1.8 reported 3.2e-7),
   which is what licenses building every trailing observable from the dump instead of the DB.
4. **A tie-handling decision, made explicitly.** `torch.topk` breaks confidence ties at the
   coverage boundary in an order that is a kernel artifact and is not reproducible from
   numpy — it is why `reaggregate_preds.py` books 1,222 trades / +9.43 where seed 3's log
   says 1,223 / +9.60. The new harness selects **every bar at or above the k-th largest
   confidence** (tie-inclusive, deterministic) and reproduces that cell too. Exactly one
   boundary in 15 is contended, so this is a 1-trade-in-1,223 question — but it is now a
   documented definition rather than an accident of which library ran.

### What M3-1 established (2026-08-27)

**The protocol is committed as [M3_PROTOCOL.md](../M3_PROTOCOL.md), before any search ran.**
It fixes the split, the metric, the decision rule and the exact 40 configurations. Three
things came out of writing it that change how every later number must be read:

1. 🔴 **The pooled trade count is not the sample size.** Clustering on the exit calendar day,
   §1.3's cov05 slice has **220 clusters behind 3,718 trades** and a standard error **2.35×**
   the iid one: +8.91 gross carries a 95% CI of **[−10.63, +28.45]**. The "≈9.5bps SEM" this
   plan quoted was an iid figure and was optimistic by that factor. The consequence is
   pre-registered in §2 of the protocol: **this dataset cannot certify a policy at taker
   fees**, so the decision rule is built around robustness, not significance.
2. **A trade-count floor prunes the grid before any P&L was seen.** Requiring ≥100 pooled
   trades in *every* window leaves **16 of 36** configurations eligible. All in-regime configs
   below cov0.05 fail it, because w3 starves — the top-quintile filter leaves only 23–87
   trades there. The regime fires very unevenly across time, and the floor catches it.
3. **Two definitional defects in the M3-0a harness were fixed** before they could be baked
   into a search (both re-validated, TEST 1 and TEST 2 still pass):
   - `size_by_regime` bucketed by a quantile of *selected trades*, contradicting the
     "quantile of BARS" rule the hard threshold obeys. It now uses bar-level quintile edges.
   - `regime_col` with no threshold used to be an error; it now means "condition without
     filtering", which is what makes a sizing-only policy expressible at all.

### What M3-2 established (2026-08-27) — the headline, in plain language

**Full results: [M3_2_RESULTS.md](../M3_2_RESULTS.md) — all 40 pre-registered runs, both fee
assumptions, per window, per seed, per side.** The short version, no statistics required:

1. **There is a tradeable rule, and it is worth about +15 bps a trade after taker fees.**
   Enter on the top **2%** of bars by model confidence, hold **4 hours**, size the position
   by how much BTC has moved in the last 24h (a third of normal size in the calmest fifth of
   the market, up to five thirds in the wildest), no concurrency cap. Over 253 days and three
   seeds that is 1,773 trades, +33.8 bps gross, **+15.0 net at a 14-bps taker round trip**,
   Sharpe 0.93, ~2.3 trades a day per seed. It is positive in all four calendar windows.
2. 🔴 **The finding the whole milestone was built on did not survive in the form we expected.**
   "Only trade when BTC has moved >4.3% in a day" — §1.8's 4× effect, used as a hard on/off
   filter — **fails the bar in every one of its twelve configurations.** Not because it loses
   money: the two best versions are +18.3 and +9.4 bps net pooled. One fails because the
   filter leaves only 45 trades in an entire two-month window, the other because it is
   negative on one of the three seeds. Those two floors were fixed in advance, in M3-1, from
   trade counts alone.
3. **The soft version is what works.** Using the same market-move observable to *size* the
   trade, while still trading out of regime, passes everything the hard filter failed. This
   is the concrete, actionable result of M3-2: **the regime signal is a dial, not a switch.**
4. **The model's direction call is doing the work.** The same entries with the side taken
   from trailing momentum instead of from the model earn **−21.8 bps** instead of +15.0 — a
   **+36.9 bps** gap. Buy-and-hold on the same universe lost 13% over the period. The policy
   is not a repackaged beta bet.
5. **It still cannot be certified, exactly as pre-registered.** The clustered 95% interval on
   the winner is [−33.0, +63.1]. M3_PROTOCOL §2 said in advance that 253 days holding ~162
   independent trading days cannot prove a 15-bps edge net of a 14-bps round trip, and §4.3
   pre-registered that Tier 2 would fail. It did. **This is enough to be M3-3's benchmark and
   to justify paper trading; it is not enough to justify size.**

Two caveats that belong next to the headline: the sizing variant's mean size is 1.34, so per
unit of *notional deployed* it earns +11.2 rather than +15.0 bps; and its worst window (w3,
192 trades) is **+0.25 bps** — an absence of a loss, not a profit. Its max drawdown is also
larger than the flat-size version's (−4.59 against −2.76).

Three structural facts hold across the whole grid and should shape M3-3: **24-hour holds are
untradeable** (every one loses 61–198 bps in w4), **1-hour holds never cover fees**, and
**capping at 3 concurrent positions costs money in every single pairing** — on eight pairs
held serially the uncapped policy is already a real 8-slot portfolio, not leverage.

### What M3-3 established (2026-08-27) — the learned policy lost, and usefully

**Full results: [M3_3_RESULTS.md](../M3_3_RESULTS.md) — all 14 runs, both fee assumptions,
per window, per seed, per side. Protocol: [M3_3_PROTOCOL.md](../M3_3_PROTOCOL.md), committed
before the first fit ran.** The short version, no statistics required:

1. **Nothing learned beat the hand-written rule. Nothing learned even passed Tier 1.** The
   best of the eight fitted configurations reaches **−7.18 bps** on its worst window against
   the baseline's **+0.25**. M3_3_PROTOCOL §7 pre-registered this outcome and what follows
   from it: **M3-2's rule is M3's policy**, the grid is not widened, and a bigger model is
   not the remedy.
2. 🔴 **The extra observations did not just fail to help — they cost money.** The
   confidence-only ablation, fitted by the identical machinery on the one observation M3-2
   already used, **beats both fitted models in three of the four rule pairings.** Nine
   observations on ~188 independent trading days is over-specification, and running the
   ablation is what makes that visible rather than arguable.
3. 🔴 **The size of the edge does not hold still.** The mean gross edge available in the top
   decile of bars is **+7.6 / +18.4 / +3.7 / −7.5 bps** across the four windows — a **25.9
   bps swing, larger than the entire edge any policy here is chasing.** This is a fact about
   the evidence, not about a model. It is why the entry rule that thresholds an *absolute*
   predicted edge collapses (it simply stops firing in the low windows), and it is the
   strongest argument yet for keeping every condition **rank-based** (§1.3.3): an ordering
   survives what a level does not.
4. **M3-2's central finding replicated, in a stronger form.** Holding the entry set constant
   **bar for bar** — the ablation and the re-scored baseline enter the identical 1,796 trades
   — sizing by the regime observable is worth **+8.6 bps on the worst window** and **+8.5
   pooled**, and is the whole difference between failing Tier 1 and passing it. M3-2 reached
   that conclusion by comparing two grid rows; this holds everything else fixed.
5. **A harness check passed that was written to be able to fail.** §6 of the protocol
   predicted, before the run, that a one-feature fit with a positive coefficient must select
   exactly the bars the baseline selects. It did: 34,772 entry bars, identical. Had it not,
   the run would have been void rather than interesting.

The honest reading of why: the learned policy was given four genuinely new observations (the
60m and 1440m heads and whether they agree with the 240m side) and could not turn them into
anything. That is a real answer to a real question, and it cost one afternoon of laptop time
rather than a wave of GPU runs.


### The plan from here, in order

*Updated 2026-08-28, after M3-4 ran. Item 0 is closed and kept only as the record of why;
**item 1 is now DONE** and it did invalidate a published number, in the good direction; item 2
adds evidence nothing else can; **item 3 is now the last blocking piece of M3, and M3-4 made it
smaller.** Everything below is scoped to the 8 baseline pairs, which is what is served — and as
of T6 that is a settled scope, not a placeholder.*

#### 0. The 12-pair universe 🟢 **CLOSED 2026-08-27 — nothing further to run**

Two 12-pair seeds ran (T1, T2; ~8h GPU, serial) and T3 re-scored M3-2's winner on all three
12-pair dumps under the adoption rule pre-registered in
[NEXT_TRAINING_PLAN §2](../NEXT_TRAINING_PLAN.md): *adopt 12 pairs iff the wide run still
passes every Tier-1 criterion the narrow run passes and its worst window does not degrade.*

**Outcome: the +7.5 did not replicate, and T6 then closed the question as unresolvable.**
The adoption rule's P5 clause fired against adoption — but P5 is a coin flip at this sample
size, failing on the *incumbent* 8-pair universe 52.4% of the time, so it could not have
decided anything. T6 ran the three fair tests and found the effect within a couple of bps of
zero in every framing, against a resolution limit of ±37 bps (§0.6's second amendment).
**The served 8-pair universe stands. No further GPU and no further offline work.**

🔴 **What T6 found instead, and it is the more useful result:** the criterion that
actually binds this policy is **P3, the −5 bps worst-window floor**, which fails on *both*
universes in 88–98% of day-bootstraps. **Window 3 is the constraint, and no pair-set change
touches it.**

Two things this did close cleanly, both worth keeping:

- **The grid was not re-searched.** T3 scored the already-chosen winner spec, transcribed, on
  both universes of the same dumps, exactly as pre-registered. Re-running the 40 configs on a
  new pair population and taking the best is the shopping
  [M3_PROTOCOL §0](../M3_PROTOCOL.md) forbids — and T6 held the same line: it re-tuned
  *sizing* on a fixed policy and did not re-search the grid. Where T6 noticed that a tighter
  coverage looked better on these checkpoints, it recorded the observation and explicitly
  declined to act on it, because coverage is a searched dimension of the M3-2 grid.
- **A single-seed headline was killed by replication.** That part worked exactly as intended,
  and it is why the T-wave was worth the GPU.

🔴 **The lesson the retraction added:** a pre-registered criterion protects against shopping
for a favourable result; it does **not** make an underpowered test informative. Before letting
any Tier-1 clause close a direction, bootstrap its failure rate on **both** arms.

#### 1. M3-4 — the execution-cost study 🟢 **DONE 2026-08-28** (§2 M3-4, was ranked risk #2)

**Result: [M3_4_RESULTS.md](../M3_4_RESULTS.md); the reading is §0.8.** Crossing costs **9.84 bps
round trip, not 14**; the maker arm is **not worth building** (adverse selection eats the fee
rebate in 16 of 16 cells); **M3-5 should build a crossing executor and nothing else.** Risk #2
is closed. The sub-section below is kept as the record of what the question was and why it was
framed the way it was — it is history now, not a plan.

<details><summary>The original framing, preserved</summary>


**M3-4a is done** — [M3_4_PROTOCOL.md](../M3_4_PROTOCOL.md) is committed, before any fill
number, and `./scripts/m3.sh -m m3 bookprep` reproduces every fact it rests on. What remains is
running the study it pre-registers. **Read §0.7 before doing so: the protocol's audit changed
what the study is asking, and this sub-section's original framing is preserved below only for
the parts that survived.**

**The question, as M3_PLAN originally put it:** if we rest a limit order instead of crossing
the spread, do we actually get filled — and at what real cost? Every M3-2 candidate roughly
doubles at maker fees (the winner is **+27.1 at maker against +15.0 at taker**), so this
untested assumption underwrites half the published economics.

🔴 **That framing is now known to be too narrow, and the "roughly doubles" is not reachable.**
The touch spread is **0.01 bps on BTC** and 0.04 on ETH — one tick — so a resting order's
entire advantage there is the 2 bps/side fee rebate, capping the maker gain at about **4 bps
round trip**, not the 9 bps that 14-vs-5 implies. Meanwhile the *taker* side assumes 3 bps of
slippage per side, and a $10k order against BTC's **$402k resting at the touch** crosses for
0.005 bps. **The 14 is the more suspicious of the two numbers, and it is wrong in the
direction that makes every published M3 result too pessimistic.** §0.7 has the detail; the
protocol pre-registers both as decision quantities.

🔴 **Do it offline, from data we already have — not on the live paper-sim stack.** §3.3 used to
say "measure it on the paper-sim stack"; that is now known to be wrong, because
`apps/fluxtrader/lib/fluxtrader/trading/executor.ex` cannot place a limit order at all (§0.5.4).
Standing that up first would be days of order-simulation work before the first number arrives.

The data to answer it is **already collected**: the collector has written raw L2 order-book
ladders (`orderbook_levels` — best-first `[price, qty]` arrays, 100 levels a side) plus trade
aggregates with `high`/`low`/`buy_volume`/`sell_volume` (`market_trades`). It supports all
three questions directly: **fill probability** (did the tape trade at or through our resting
price inside the window), **queue position** (resting depth at our level against subsequent
same-side volume), and **adverse selection** (which way the mid moved right after the fills we
did get). It runs in the existing `ml_analysis` image via `scripts/m3.sh` — no GPU, no new
stack, no orders.

🔴 **Two corrections to what this section used to claim, both measured on the VM 2026-08-27,
and both change how M3-4a must be scoped.** It previously said "5-second ladders since
2026-07-17, ~40 days". Neither half is right:

| table | actual coverage |
|---|---|
| `orderbook_snapshots` (derived features) | from **2026-07-17** for BTC/ETH/SOL — this is the 40-day figure, and it is the *wrong table*, it carries no ladder |
| `orderbook_levels` (**the raw L2 ladder M3-4 needs**) | from **2026-08-05** for the 8 served pairs (**22 days**) · from **2026-08-14** for ADA/AVAX/LINK/XRP (**13 days**) |
| observed cadence | ~**10.7 s** per row, not 5 s — 8,037 rows/pair/day against the 17,280 a true 5-second poll would write, while `collector.ex` sets `@book_interval_ms 5_000` |

The cadence gap is not cosmetic: **fill probability is measured against how much of the tape
we can see, and a 10-second sampling interval sees half the book states a 5-second one does.**
M3-4a must resolve whether the collector is dropping polls or the write is conditional, and
state the sampling interval it assumes, before any fill number is quoted.

**Scope it to the 8 baseline pairs — that is what is served** — but produce per-pair numbers
for all 12 wherever the stored ladders allow at no extra cost. If 12 pairs were adopted, the
four new ones have 13 days of ladder against the majors' 22. Export all 12, but **pre-register
the primary result on the pairs with the full window and report the short-window four
separately** — do not silently pool two depths of evidence, and do not let a 13-day sample
decide a pair's cost.

🟢 **This instruction is why the 2026-08-29 widening cost one afternoon instead of a re-export.**
The run followed it exactly: all 12 measured, the primary pre-registered on the 8, the short
four reported separately and excluded from Q1's verdict. When the universe *was* adopted, the
numbers were already on disk and the study re-ran byte-identically. Note the distinction that
made them usable: **the §1.5 exclusion governs the VERDICT, not the CHARGING.** A per-pair cost
used to charge a trade is not a decision quantity, and a pair's own 14-day number beats a
constant pooled from eight *other* pairs — ADAUSDT measures 13.733 bps against that pooled
9.842. What remains forbidden is re-pooling the two depths into a single decision number, and
`@pooled` was left at the eight-pair value for exactly that reason.

Take it in the milestone's established two-step order:

- **M3-4a** — export the book/tape slice for the served pairs, then **pre-register** the
  study: the sampling interval, the fill definition, the queue model, the adverse-selection
  horizon, and the number that decides whether maker economics are real. Commit it before any
  measurement, exactly as M3-1 and M3-3a did.
- **M3-4** — run it, and publish the **realized effective round-trip cost per pair** next to
  the assumed 5 and 14 bps, then re-score the M3-2 grid at the measured cost.

**This is also the gate on any universe wider than 12.** The 14 bps is a single number applied
to every pair, and §0.6's gain is carried by mid-caps whose spreads are not the majors'. Until
M3-4 produces per-pair costs, adding instruments is buying edge against an unpriced liability.
The one thing worth doing *before* then is starting **collection** on any candidate pair, since
candles backfill four years on demand and order-book history does not — it begins the day the
collector is pointed at the pair, which is why the four newest pairs have 13 days and not 22.
Budget the disk first: `orderbook_levels` runs ~24 MB per pair per day (5.3 GB for the 1.78M
rows currently held), so 12 pairs is ~8.6 GB/month against 55 GB free on `fluxtrader-1` — about
six months of headroom, under four if the universe grows to twenty.

</details>

#### 2. M3-0b — the price/funding side-table 🟢 **DONE 2026-08-29**

**Result: [M3_0B_RESULTS.md](../M3_0B_RESULTS.md)**, implemented as `ml/train/m3/sidetable.py`
and run by `./scripts/m3.sh -m m3 sidetable`. It was built in one pass with the book columns
`BOOK_ERA_PLAN.md` B0 needs, as planned — one alignment, two consumers — so **B0 is closed and
B1 is unblocked** (`./scripts/m3.sh -m m3 bookera`).

Its four consumers, and what each turned out to be worth:

1. **The live brake** (M3-5's addition) — 🔴 **the finding.** The deployed 2% stop / 4% target
   costs **10.5 gross bps/trade**, +33.76 → +23.24, on a policy netting ~20. The stop fires
   three times as often as the target. It is catastrophe insurance whose premium is now known,
   not a defect to switch off, and the decision is filed in [BACKLOG.md](../BACKLOG.md).
2. **Barrier exits / C4b** — 🟢 **answered.** Every setting tried loses to the fixed 4h hold
   (best +9.2 vs +19.8 net bps), improving monotonically as the band widens back toward it.
   The mismatch C4b filed is real and points away from barriers, so accepting it costs nothing.
3. **The funding term** — 🟢 **+0.14 bps/trade**, a rounding error at a 4h hold; the headline
   moves +20.59 → +20.45. Lumpy rather than proportional: 45% of trades cross no settlement.
   ⚠️ HYPEUSDT settles every 4h, not 8 — the schedule is read per pair, never assumed.
4. **Position-state observations** — now possible, still un-run, and gated on a
   pre-registration rather than on data (§7 of the results).

⚠️ **This section said the data was "already on disk". That was wrong**, and the acceptance
test is what caught it: the M3-4 export covers the 23-day book era, and **96% of the policy's
trades fall outside it**. The price path was re-exported over 2025-11-15 .. 2026-08-30 into
`ml/train/output/m3_0b/`; `scripts/gcp_m3_export.sh` now documents the two windows explicitly.

#### 3. M3-5 — wire the rule to the executor 🟢 **DONE 2026-08-28**

**Result: [M3_5_INTEGRATION.md](../M3_5_INTEGRATION.md).** The M3-2 SIZED rule now exists once,
in `Trading.Policy`, and runs: `PolicyEngine` records every bar, ranks the trailing 14 days,
sizes on live BTC-volatility quintiles, holds four hours, and closes — every policy entry
through `RiskManager`'s hard limits in **every** mode, which closes §6's last exit criterion.
A flat-size control arm runs beside it, which is PLAN.md's M3 A/B (it was a *signal-only*
control until 2026-08-31 — see §4 of the integration doc for the re-registration). Costs charged are M3-4's
measured per-pair round trips, and there is no limit-order machinery, exactly as §0.8 item 3
directed.

**The second precondition is done:** `GET /api/health` reports bars seen, time since the last
gated signal, the live coverage cut and named skip reasons, so the correct silence §0.8 warned
about is now legible as correct rather than indistinguishable from a dead process.

🔴 **The first precondition is NOT done and is now filed in [BACKLOG.md](../BACKLOG.md):**
verifying the actual Binance USDⓈ-M VIP fee tier. Every M3 cost uses taker 4.0 / maker 2.0 bps
per side because that is what `metrics.py`'s 14 and 5 decompose to, and it has **never been
checked against the account**. `mix flux.fee_tier` now performs the check — signed
`/fapi/v1/commissionRate`, and written to fail loudly rather than print an unverified number —
but it needs `BINANCE_API_KEY` / `BINANCE_API_SECRET`, which the container does not have. A
wrong tier shifts every published M3 number by a constant.

🔴 **One thing M3-5 uncovered that nothing had asked:** the `auto` order path is **unsigned**.
`Binance.Client.post/2` sends neither the `X-MBX-APIKEY` header nor the HMAC-SHA256 signature
Binance requires on every TRADE endpoint, so a real order returns 401. The executor now says so
loudly at boot instead of looking like it is trading. Paper is unaffected; **anything beyond
paper is blocked on request signing**, which is filed in BACKLOG.md and is not M3 work.



---

# `NEXT_TRAINING_PLAN.md`'s narrative sections, moved here on 2026-09-04

**This is HISTORY. Do not act on it.** Moved under RULES_REVIEW §6.3 so the live training plan
holds only §0's standing rules and §1's reference numbers. These are the wave-by-wave readings
(§1.0, §1.2, §1.4–§1.7, §1.9, §1.10), the old front matter, the "what to bring back" and
results-ledger sections, and the completed code batches.

⚠️ **All of it is PRE-REPAIR** — see the header of this archive.

# Training plan — what is true, what to run next

**Last updated: 2026-08-27** (T5 and T6 both done. **T5 is fixed and shipped**: `/predict_all`
now serves only the checkpoint's own trained pairs. **T6 closed the universe question** — not
by deciding it, but by measuring that this evaluation period *cannot* decide it, and by
showing that what looked like a 12-pair gain is a confidence-cut effect. Preceded by the
T-wave — T1 and T2, two 12-pair seeds, both valid — and before that the closing wave: O8, R2,
R3a, R3b, all four flat or negative, the pre-registered exit condition fired, and **M2 is
frozen at the §1.3 baseline as a research object**. Before that: R1, and the Q-wave — Q0 gate
derivation, Q1 regime analysis, Q2 ensemble, Q3 feature expansion).

🟢 **If you are picking this up cold: M2 is frozen as research, §2's queue is empty, and
nothing is waiting on you here.** The one training run any plan still calls for is **B3**, and it
is **blocked** — see §2.  The served model is seed 2 on **8 pairs**
(`m2_multi_20260819T142759Z_a186182b.pt`, gate 0.6311). All remaining work is in
`docs/M3_PLAN.md`.

🔴 **Corrected 2026-09-03: the paragraph below is wrong about the cause.** Every candle stored
since 2026-07-18 is a partial first-minute bar (~10% of true volume, ~30% of true range), so the
"confidence dispersion collapses" observation is the model reading flat inputs, not a calm market.
The last 31 days of every eval dump's split are affected. Owner:
[CANDLE_POLL_DEFECT.md](../CANDLE_POLL_DEFECT.md). The original paragraph is kept for the record.

🔴 **One M2-relevant fact discovered on 2026-08-28, and it is not a defect.** The served
checkpoint has produced **no gated signal since 2026-06-29**. Monthly maximum confidence falls
from 0.66–0.80 (Dec–Jun) to 0.60–0.68 in July and **0.547–0.569 in August**, on all three
baseline seeds *and* on O8 independently — so it is a property of the market, not of a model.
It tracks volatility exactly: `btc_absret_1d` averages **0.0070** in August against 0.011–0.027
in every earlier month, and confidence *dispersion* collapses with it (sd 0.0127 vs
0.023–0.047). **The model is confident when the market moves, and the market has been quiet.**

That is §1.8's finding restated — the edge lives in volatile bars — and it means the model is
correctly sitting out. It is recorded here because (a) a two-month-silent live system is
indistinguishable from a broken one without a liveness check, and (b) any future eval whose
validation window lands in this calm stretch will look worse than the model is, for reasons
that have nothing to do with the change under test. Workings: `docs/M3_PLAN.md` §0.8.

🟢 **The traded universe: closed 2026-08-27, as unresolvable on this data.** After three
paired comparisons (§1.10) the 8-vs-12 effect sits within a couple of bps of zero in every
framing, and the decisive fact is a power measurement rather than a point estimate: the
evaluation period holds ~180 independent exit days, which resolves effects of about **±37
bps** at 80% power. The +7.5 bps anyone cared about is roughly a *third* of what this data
can see. **More seeds cannot fix that** — extra seeds and extra pairs both add correlated
trades inside the same days. Only a longer evaluation period can, and that is calendar, not
compute. **Do not queue more work on 8-vs-12.** Full workings: `docs/T6_RESULTS.md`.

⚠️ **One correction to the T-wave write-up, and it matters for how the next negative result
gets read.** §1.10 published "−0.85 bps, 95% CI [−6.8, +5.1]" and concluded the +7.5 was
excluded. That interval is reproduced exactly by T6 — but it comes from a **day-weighted,
shared-days-only** estimator sitting next to a **trade-weighted** table. On the estimator that
matches the published per-trade statistic the interval is [−12.0, +11.5], and **+7.5 is inside
it**. The T-wave did not refute the +7.5; it failed to replicate it, which is a weaker and
different thing. §1.10 has been amended.

**Every open and parked item across all wavefronts is indexed in [`docs/BACKLOG.md`](../BACKLOG.md)** — read that first if you want to know what exists without reading five plan documents.

**All research work is in M3, planned and tracked in `docs/M3_PLAN.md`** — start at that
file's §0.0 status block. This document remains the reference for what M2 measured and for
the standing rules in §0.

**One parallel wavefront exists: `docs/BOOK_ERA_PLAN.md`** (the B-wave, opened 2026-08-24).
It does not reopen M2 and it queues no `gcp_train.sh` run. It is a measurement-first
investigation of whether the ~38 days of order-book history supports a short-horizon model
or — more likely — a regime observable for M3. It runs on the laptop and on its own
throwaway VMs, concurrently with M3.

This document is the project's session-to-session memory. It contains only what is
**currently true and actionable**. The session-by-session narrative from 2026-07-23 →
2026-08-21 — every superseded plan, every rejected hypothesis, every raw results table —
lives in **`docs/archive/TRAINING_HISTORY.md`**. Go there for "why was X decided"; do not
act on anything in it.

### What this document is a plan *for* — read once, then stop worrying about it

Everything in this file is **milestone M2: the supervised signal model**. Its only job is
to emit, per pair and per bar, a calibrated directional probability at 1h / 4h / 24h. It
is **not the trading system and it never decides a trade.**

The trading decision belongs to **M3, a discrete policy (RL / bandit) over
flat / long / short / hold / exit**, which consumes M2's per-horizon probabilities and
confidences as *observations*. That is the design in `MODEL.md` §5.5 and `docs/PLAN.md`
§M3, and it has not changed.

Two consequences that keep coming up and are worth stating plainly:

- **"The model is barely break-even after costs" is not a project verdict.** M2 is a
  feature extractor for M3. A signal worth +6 gross bps/trade at 2% coverage is a usable
  observation for a policy that also controls *when to be in the market at all*, position
  size, and holding time — none of which M2 has any say over. The gate sweeps and
  fixed-coverage P&L tables in this doc exist to tell us whether the signal carries
  information, not to define a strategy.
- **Conversely, M2 must not grow policy features.** Anything about sizing, exits, risk
  budget, or execution style is M3's, and building it here would make the policy's job
  harder, not easier. When a lever in this doc starts to look like a trading rule
  (cost-aware checkpoint selection was one — §5), that is a signal it belongs downstream.

The one place M2's economics genuinely matter is the **taker/maker line** (§7): a signal
whose gross edge is under round-trip cost at *every* coverage gives M3 nothing to work
with. §1.3 is where that stopped being the case, and as of the P-wave it is measured on
three seeds rather than one.

The second place they matter is **calibration**, which the P-wave promoted to a
first-class acceptance criterion: M3 consumes probabilities, so a model that ranks well
while emitting meaningless probabilities (P2, §1.4) has not improved.

**How to use this doc:** if you are picking this up cold, the fastest path is
**§1.0 (plain-language state of play — no jargon, no §0 required)** →
**`docs/M3_PLAN.md` §0.0**, which is where the work continues and where current status
lives. Read §1.1, §0.3 and §0.6 when you need to know *why* the numbers are read
the way they are, or before you rank two runs against each other. §1.9 is the wave that
closed M2; §0 exists to stop a future session re-running what it already refuted.

- §0 — standing rules. Read before touching anything. Every rule cost us a real run.
- §1 — where we are, in numbers. The current reference points.
- §2 — **the run queue.** Empty: M2 is frozen and the promote is done. M3's queue is in
  `docs/M3_PLAN.md`.
- §3 — what to bring back so a fresh session can decide.
- §4 — results ledger (one row per run, with a validity flag).
- §5 — levers that are closed, and why. Don't re-propose these.
- §6 — open code tasks.
- §7 — mechanics (scripts, promote, fetch).

---


## §1 — WHERE WE ARE (2026-08-24)

### 1.0 Plain-language state of play — readable without §0

*If you read one section, read this one. §1.1 says the same thing in the document's own
vocabulary; everything below §1.1 is the evidence.*

**What the model is.** A small recurrent network (2-layer LSTM, 64 hidden units — about
56k parameters) that reads the last **384 five-minute candles (32 hours)** for one trading
pair and outputs, for each of three horizons (1h / 4h / 24h), a probability that price goes
up, down, or stays flat. 4h is the horizon we optimise. It does **not** decide trades —
that is M3's job (see the preamble).

**What it is worth.** Take the 5% of bars where it is most confident: it is right about
direction **55.9%** of the time, and those trades are worth about **+9 basis points each
before fees**. Narrow to the most confident 2% and it is **+22 bps**. A round trip costs
**14 bps** as a taker and **5 bps** as a maker. So: comfortably profitable at maker fees on
the top 2%, thin but positive at taker fees, and not usable at all if you trade more than
about the top 5% of bars. This is measured on three independently seeded models that agree
with each other, which is why we trust it.

**What the input actually is — this is the surprising part.** The feature list has 19
columns, but **12 of them are dead**. Order-book and trade-flow data only began being
collected in July 2026, which is entirely inside the *validation* period, so across the
training window they are constant and get zeroed out. The model is genuinely learning from
**seven live columns**: 1-bar return, high–low range, open–close range, log volume, funding
rate, a 15-bar return volatility, and one availability mask. That is it. Essentially price
and volume.

**What we have tried, and what happened.**

| tried | outcome |
|---|---|
| Finer bars (15m → 5m) | ✅ **worked** — the one real improvement, +0.016, replicated on 3 seeds |
| Finer still (1m) | ❌ no better at ranking, worse economics, broke the probabilities |
| Longer memory (32h → 64h) | ❌ worse |
| A gradient-boosted tree instead of the LSTM | ❌ much worse — sequence structure genuinely matters |
| Averaging 3 models together | ❌ compresses exactly the confident bars where the money is |
| Choosing the checkpoint by profit instead of accuracy | ❌ the profit estimate is too noisy to rank on |
| Adding 11 new derived columns (Q3) | ❌ rejected |
| Adding the best-behaved 6 of them (R1) | ❌ rejected, worse than Q3 — **§1.6, and this closes features** |
| Hyperparameter tuning (dozens of runs, the R/E waves) | ❌ the whole spread was inside the noise |
| **More pairs — 12 instead of 8, 58% more data (O8)** | ❌ **no better *as data*** — §1.9. ❌ **and closed as a traded universe too** — the +7.5 did not replicate, and T6's fair tests put the effect within a couple of bps of zero in every framing against a ±37 bps resolution limit. What a trade-count-matched test made look like a pair gain is the confidence cut, not the pairs. Not decided — *undecidable here* — so the incumbent stands — §1.10, `docs/T6_RESULTS.md` |
| **A loss that cares about move size (R2)** | ❌ **worse.** Made the model wildly overconfident and broke the probabilities — §1.9 |
| **A bigger encoder — 128 units (R3a)** | ❌ **worse.** Memorized the training set; worst calibration in the project — §1.9 |
| **A smaller encoder — 32 units (R3b)** | ❌ **identical.** Half the size, same result — the model was never capacity-limited — §1.9 |

**The one big thing that did work, and it is not a model change.** Q1 found that when
**Bitcoin has moved more than ~4.3% in the past 24 hours** — which happens on about 5% of
bars — the same model's top-5% trades are worth **+35 bps instead of +9**, and **+55
instead of +22** at the top 2%. Three seeds agree closely. That is a **4×**, and no change
we have ever made to the model itself has produced more than a few percent. It is a
statement about *when to be in the market*, so it belongs to the trading policy (M3), not
to the signal model.

**Where that leaves us — and this is now settled rather than provisional.** The last three
experiments were the ones the previous session queued to decide whether M2 was finished, and
they all said yes. More data did nothing. A loss aimed squarely at the economic weakness made
it worse. Making the network bigger made it worse; making it *smaller* changed nothing at all,
which is the clearest possible statement that the network was never the bottleneck. Seven
columns of price and volume support a small real edge, we have found it, and there is nothing
further to extract from these inputs.

**So M2 is done.** The recommendation is: promote the model we have (§2 R0, five minutes),
then spend everything on M3 — the trading policy — where the one big measured effect lives.
That effect is worth restating: conditioning on *whether the market has been moving* takes the
same model's top-2% trades from +22 to **+55 basis points**, roughly a 4× improvement, versus
the few-percent noise that every model change produced. The only thing that would reopen M2 is
**new data** — order-book history deep enough to fall inside the training window — and that is
a calendar problem, not a modelling one (§1.7). Expect it around 2027.

A seventh lever was tested on 2026-08-27 and is the one thing here that is **not** closed:
the **traded universe**. A single seed said that running the M3 policy over 12 instruments
instead of 8 earned +7.5 more net bps per trade at an identical model — the policy picks the
most confident 2% of bars out of whatever universe it is handed, so more instruments should
deepen the cross-section. Two more seeds were run to bank it and **the +7.5 did not
replicate**. T6 then ran the fair versions of the comparison and **closed the question the
only way this data allows: as unresolvable.** The 8-vs-12 effect is within a couple of bps of
zero however it is framed, and the evaluation period resolves ±37 bps at best — the +7.5 was
always a third of what could be seen. What looked like a 12-pair gain under a trade-count-
matched test turned out to be the *confidence cut*, not the pairs. **Closed; the served
8-pair universe stands** — §1.10, `docs/T6_RESULTS.md`.

### 1.2 The regime structure, re-read on six models

`cov05 wilson_lb` on the primary 240m head, val window split into four ~2-month blocks:

| window | period | F4 (15m) | N3 (15m) | N2 (GBT) | O2 (5m s1) | **P0 s2** | **P0 s3** | **P2 (1m)** |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2025-12 → 2026-02 | 0.486 | 0.499 | 0.492 | 0.573 | **0.621** | **0.593** | 0.542 |
| 2 | 2026-02 → 2026-04 | 0.617 | 0.621 | 0.574 | 0.535 | **0.618** | **0.592** | 0.506 |
| 3 | 2026-04 → 2026-06 | 0.457 | 0.419 | 0.415 | 0.500 | **0.482** | **0.491** | **0.607** |
| 4 | 2026-06 → 2026-08 | 0.584 | 0.613 | 0.397 | 0.596 | **0.596** | **0.621** | 0.623 |
| spread | | 0.160 | 0.202 | 0.177 | 0.096 | 0.139 | 0.130 | 0.117 |

Two of the O-wave's readings were single-seed artifacts and are withdrawn:

- **Window 2 does not invert between 15m and 5m.** O2's 0.535 was the outlier; seeds 2 and
  3 score 0.618 / 0.592, right on top of F4's 0.617. Only **window 1** is genuinely
  resolution-dependent: every 5m model finds edge there (0.573–0.621) where every 15m model
  is at coin flip (0.486–0.499). That is the sharpest thing this table says, and it is
  consistent with 5m simply being a better model rather than a differently-regime-locked one.
- **The 5m model is not meaningfully less regime-locked.** O2's 0.096 spread was the low
  draw; the 5m family averages ~0.12 against the 15m family's ~0.18. A real but small
  narrowing, not a change of kind.

What survives across all six directional models: **window 3 is the worst window and window
4 is a good one.** The single exception is P2, which inverts window 3 into its *best*
(0.607) — but P2's confidence scale is broken (§1.4), so its top-5% slice is not selecting
the same kind of bar as anyone else's and it should not be given a vote here.

A ~0.13 spread is still 5–8× the run-to-run noise of §0.3 and the top window is worth
several times maker cost. The regime analysis is still worth doing, and it is now **Q1** —
but it must run on **all three 5m seed dumps**, because this table is exactly the place
where one seed misled us. An observable that only separates windows for one seed is noise.

### 1.4 Resolution is closed at 5m — the surviving statement

P2 ran 1m/seq768 as the next rung and came back flat-to-worse on every axis that matters:
`dir_acc` at cov05 **0.561 against the 5m family's 0.559**, gross bps/trade at cov 0.01 /
0.02 of **+2.6 / +8.5** against **+19.4 / +22.0**, **brier 0.323 vs 0.250** with
`emp_up ≈ 0.48` in every probability bin, and 20h16m of wall clock against 2.5–3h. Its
headline LB (0.5256, the highest in the ledger) is the §0.6 trap: 2.9M val rows narrow the
Wilson interval without adding independent observations.

**Verdict, per the pre-registered rule: 5m is the resolution sweet spot. Frozen (§5).**
The full P2 tables and the untested-variant argument are in
`docs/archive/TRAINING_HISTORY.md`. Read O2 / O3 / P2 together and the shape is settled:
**finer observations helped once, from 15m to 5m, and then stopped; more window never
helped.**

### 1.5 The served gate is a coverage target — shipped, and seed 2's is 0.6311

C13 shipped this and Q0 exercised it. The finding that forced it: the same absolute
confidence threshold is 1.2% / 2.5% / 1.7% coverage across three seeds of one
configuration, 0.8% on O3 and 80% on P2, so **a global `GATE_THRESHOLD` constant is not a
well-defined operating point across checkpoints and never was** (§5). `eval_m2.py` now
measures the threshold realizing `SERVE_TARGET_COVERAGE` (default 0.02) and writes it into
the checkpoint; `serve.py` reads it and reports `gate_source`.

**Seed 2's measured gate is `conf >= 0.6311`**, realizing dir_acc 0.578, +18.68 gross
bps/trade, **+4.68 net at 14bps taker** (`logs/Q0.log`). ⚠️ `--eval-only` never pushes a
checkpoint, so that gate lives only in the log — the bucket copy still carries none, and
the promote must pass it explicitly (§2 R0).

⚠️ **"Passing it explicitly" means the VM's `.env`, not your shell.** `ML_GATE_THRESHOLD`
on the launcher was a no-op until 2026-08-24 — compose interpolates it on the *remote*
host — and the VM's `.env` value silently won. `gcp_promote.sh` now writes the value into
that file and fails the promote if `/health` disagrees, but if you ever change the gate by
hand, change it there and recreate **both** `ml_inference` and `app`: the Elixir
`Predict.gate_threshold/0` reads the same variable and gates independently.

### 1.6 🔴 Per-timestep candle features are closed — two arms, two rejections

Two runs tested the same lever from different sides. Both lost, and together they close it.
(Family columns are in O2 / seed2 / seed3 order throughout.)

| | 5m family (3 seeds, 19 cols) | Q3 (30 cols) | **R1 (25 cols)** |
|---|---:|---:|---:|
| plateau-restricted mean cov05 LB | **0.5239** (0.5235 / 0.5273 / 0.5209) | 0.5000 (n=5) | **0.4979** (n=11) |
| all-epoch mean cov05 LB | 0.5219 ± 0.0014 | 0.5003 (n=28) | **0.4889** (n=38) |
| plateau length (epochs) | 24 / 21 / 26 | 5 | **11** |
| **best `loss_va` ever reached** | **1.0404 / 1.0398 / 1.0401** | 1.0431 | **1.0451** |
| `brier` (240m, moved bars) | 0.250 | 0.2897 | **0.2863** |
| calibration bin table | monotone in `emp_up` | inverted | **flat — `emp_up` 0.48 in every bin 0.10→0.80** |
| gross bps/trade @ cov 0.01 / 0.02 | +19.4 / +22.0 | +19.7 / +17.6 | **+8.0 / +11.7** |
| selected epoch | inside its plateau | ep 8 (outside) | ep 18, `loss_va` 1.157 = **+0.11 above its own min** |

**R1 was a valid run.** Every §0.4 line is green: `Feature groups: legacy,multiscale ->
25 columns`, `Feature columns: 25`, `12/25 CONSTANT` with **no new column** in the list (all
six multiscale columns are live), `Samples: 2,902,678`, `hold=48 bars`, `Pair embedding: ON
dim=8`, split recorded, `Early stop at epoch 38` (not `1 + patience`). The knob reached the
VM and the run tested exactly what it was supposed to test.

🔴 **What R1 proves that Q3 could not.** Q3's short plateau supported a benign reading —
"the extra columns are informative, the run just overfits before it can use them, add
regularization and retry." R1 kills that reading, because **R1 never matches the baseline's
validation loss at any epoch, starting at epoch 1** (1.0451 vs 1.0398–1.0404, and its
epoch-1 value *is* its minimum). Regularization can lengthen a plateau; it cannot lower a
model onto a level it never reached in its best epoch, before capacity has been consumed at
all. The pre-registered "plateau collapses ⇒ run a `DROPOUT` arm at 25 columns" branch is
therefore **withdrawn, not executed** — it would spend 3h GPU to reach, at best, the
baseline.

🔴 **The mechanism, and it explains both runs.** At `seq_len 384` on 5m bars the window is
**32h**. Every multiscale column looks back at most a day: `ret_1d` and `vol_1d` need 288
bars, `ret_4h`/`vol_4h` 48, `ret_1h`/`vol_1h` 12 — all inside 384. So at the final timestep,
*the one the prediction is made from*, all six are **exact deterministic functions of the
`ret_1` and `hl_range` values already in the window**. They carry no information the encoder
did not already have. Only the earlier timesteps of the sequence reach further back (up to
56h) — and longer context is separately closed by O3 (§5). What they do add is six smooth,
strongly autocorrelated channels, which are enormously easier to memorize than noisy
`ret_1`: `loss_tr` sits at 1.70 through epoch 11 and then falls to 1.13 by epoch 38 while
`loss_va` climbs to 1.45. **Redundant re-parameterizations of the input are not free; they
are pure overfitting surface.** Q3 fits the same story with eleven columns instead of six.

**What is and is not closed.** *Own-pair* per-timestep candle features are closed —
there is nothing left to derive from a pair's own OHLCV inside a 32h window that the
encoder cannot already compute. *Cross-pair / external* information is the one thing
neither run tested cleanly (Q3's market-context group had a 590σ defect and no
regularization change), but Q1 independently measured the informative member of that family
— BTC trailing-move magnitude — and found it to be a *when to trade* observable that M3
owns, while the dispersion family C12 actually shipped ranks least informative of nine
(§1.8). So there is no arm here worth 3h of GPU.

🔵 **One incidental finding, recorded so it is not rediscovered.** C15's new spike detector
fires on `hl_range` for six of eight pairs (max|z| 66–364, 2–4 rows beyond 50σ out of
~420k), and `hl_range` is a **legacy** column — so the 3-seed baseline has carried this
since forever and R1 did not introduce it. The values are byte-identical to Q3's. It is 2–4
rows per pair, winsorized at ±50, so the practical impact is nil; it is logged as **C19**
(§6) at low priority. SOL and HYPE get the benign "populated tail" message at the same
`max|z|` because the detector is correctly rate-based, not count-based.

### 1.7 Data status (verified on the VM, 2026-08-18; exercised at 1m/5m by the P-wave)

**✅ The 1m/5m ragged-history problem is GONE.** A backfill has landed since the 2026-08-17
audit. Candle coverage now, per interval:

| pairs | 1m / 5m / 15m first bar | note |
|---|---|---|
| BTC, ETH, SOL, DOGE, ZEC, ADA, AVAX, LINK, XRP | **2022-08-18** | full 4 years, all three intervals |
| 1000PEPE | 2023-05-05 | listing date — unfixable, not ragged |
| WLD | 2023-07-24 | listing date |
| HYPE | 2025-05-30 | listing date |

Row counts at 5m: 420,7xx for each of the nine long pairs, and the full stats report
confirms **zero interior gaps for all 12 pairs × 1m/5m/15m/1h** (48/48 rows at
`gaps=0, missing_hours=0`). **Code task C6's "1m backfill to a common start" is therefore
DONE.** It also makes the 12-pair run genuinely cheap: ADA/AVAX/LINK/XRP have full 4-year
history at every interval.

**The P-wave exercised every interval and found no data problems.** P2 loaded 14.5M samples
at 1m (the 2026-08-19 plan predicted 8–9M and was low by ~60% — budget 1m runs accordingly
if they ever come back). The 5m seeds loaded ~2.90M each. One thing to keep in view:
**the val split moves between runs** because collection is continuous — the three 5m seeds
start val at 2025-12-09 09:45, 12-10 01:40 and 12-10 11:35. It is a few hours on an
8-month window and did not matter here, but any run intended as a *matched* comparison
(Q3 against §1.3) should record its split and, if the drift ever exceeds a few days, pin
the dataset instead.

Microstructure, **re-verified on the VM 2026-08-27** (the previous figures were 2026-08-17
and are superseded — re-verify again before any book run, the clock moves):

| source | coverage |
|---|---|
| `orderbook_snapshots` | BTC/ETH/SOL **41d** (from 2026-07-17) · DOGE/HYPE/WLD 37d · ZEC 33d · 1000PEPE 31d · ADA/AVAX/LINK/XRP **13d** (from 2026-08-14). Cadence ~1/10s. |
| `orderbook_levels` (raw L2) | 8 main pairs **22d** (from 2026-08-05) · ADA/AVAX/LINK/XRP **13d** (from 2026-08-14). 100 bid + 100 ask levels. **All 12 pairs now carry a ladder** — the 2026-08-17 audit predated the four new ones. |
| `market_trades`, `open_interest` | mirror snapshots |
| `funding_rates` | 2y9mo–3y11mo — the only microstructure source with real history, and the only one that is a live feature |
| `liquidations` | **0 rows** — WS egress blocked from datacenters. Dropped from all plans. |

⚠️ **The observed book cadence is ~10.7s, not the 5s `collector.ex` configures**
(`@book_interval_ms 5_000`, but 8,037 rows/pair/day against the 17,280 a true 5s poll writes).
Nothing in M2 depends on it; **M3-4 does**, and `docs/M3_PLAN.md` §2 M3-4 now carries the
correction and the requirement to resolve it before quoting a fill probability.

**Disk, measured the same day:** `orderbook_levels` is 5.3 GB for 1.78M rows (~3.0 KB/row,
~24 MB per pair per day), `candles` 5.4 GB, whole DB 12 GB against 55 GB free. At 12 pairs the
ladder grows ~8.6 GB/month — **about six months of headroom, under four at twenty pairs.**
Widening the collected universe needs a disk plan first, not after.

**60-day book milestone for BTC/ETH/SOL: ≈2026-09-15** on `orderbook_snapshots`; the raw
ladder reaches 60 days ≈**2026-10-04**, and that is the one M3-4 reads.

All O- and P-wave runs loaded candle counts consistent with the audit, and P2 exercised the
1m interval end to end without a data complaint, so **every interval the audit covers has
now been validated by a training run.** Re-verify only if a backfill lands.

---

### 1.9 🔴 The closing wave — O8, R2, R3a, R3b all flat or negative. M2 is frozen.

Four runs, one variable each, all against the §1.3 baseline. **The exit condition
pre-registered in §2 on 2026-08-22 fired exactly as written**, so M2 is closed on
measurement rather than on fatigue. Every run passed every §0.4 verification line — the
knobs reached the VM, the pair sets and column counts are the intended ones, `hold=48`,
splits recorded, no `BROKEN SCALE`, no new `DEGENERATE SPIKE`.

| run | lever | plateau mean LB (n) | best `loss_va` | brier | cov0.02 gross bps | verdict |
|---|---|---|---:|---:|---:|---|
| **baseline (3 seeds)** | — | **0.5239** (sd 0.0032) | 1.0398–1.0404 | 0.250 | **+22.0** | reference |
| **O8** | 12 pairs (+58% samples) | 0.5222 (17) †  | 1.0454 † | 0.2495 | +21.3 ‡ | ❌ flat — data volume is not the constraint |
| **R2** | `DIR_MAG_WEIGHT=1` | 0.5058 (12) | 1.0419 | **0.3156** | +18.8 | ❌ rejected — no economic gain, calibration destroyed |
| **R3a** | `HIDDEN_SIZE=128` | 0.5185 (26) | 1.0440 | **0.4187** | +12.0 | ❌ rejected — memorizes, calibration destroyed |
| **R3b** | `HIDDEN_SIZE=32` | 0.5199 (36) | 1.0420 | 0.2507 | +16.2 | ❌ flat — capacity is not the constraint |

† O8's LB and `loss_va` are measured on a **12-pair validation population** and are not
directly comparable to the baseline's — see the re-aggregation below.
‡ O8's P&L figure is the honest 8-pair re-aggregation, not its logged 12-pair number.

#### O8 — more data buys nothing, but 12 pairs is free

The re-aggregation §2 pre-registered was performed locally on O8's `eval_preds.parquet`
(`gs://fluxtrader-train-artifacts/eval/20260822T012619Z/`) with
**`ml/train/reaggregate_preds.py`** — committed this time, so the next session does not
rebuild it a third time (§7). **The harness was validated first by reproducing O8's logged
12-pair table exactly** — cov 0.01/0.02/0.05 gross came
back +24.76 / +23.63 / +6.85 and `dir_acc` 0.547 / 0.563 / 0.548 against the logged
+24.76 / +23.63 / +6.85 and 0.547 / 0.563 / 0.548 — so the 8-pair numbers below are on the
same footing as §1.3's.

| slice | cov | dir_acc | wilson_lb | trades | gross bps/trade |
|---|---:|---:|---:|---:|---:|
| **8 baseline pairs (the honest comparison)** | 0.01 | 0.561 | 0.546 | 291 | **+23.93** |
| | 0.02 | 0.566 | 0.556 | 608 | **+21.32** |
| | 0.05 | 0.540 | 0.533 | 1,340 | +6.81 |
| *§1.3 family, pooled 3 seeds* | 0.01 / 0.02 / 0.05 | — | — | — | *+19.38 / +22.03 / +8.91* |
| all 12 pairs, as served | 0.01 | 0.547 | 0.535 | 429 | +24.76 |
| | 0.02 | 0.563 | 0.555 | 871 | +23.63 |
| | 0.05 | 0.548 | 0.543 | 2,019 | +6.85 |
| the 4 new pairs alone | 0.02 | 0.560 | 0.546 | 266 | +28.31 |
| | 0.05 | 0.565 | 0.556 | 681 | +9.69 |

**Read it as: 58% more training data moved nothing.** On the original 8 pairs one seed of
O8 lands inside the 3-seed family's spread at every coverage — +23.9/+21.3/+6.8 against
+19.4/+22.0/+8.9 — which is what "no effect" looks like on this measurement. The verdict
metric confirms it: the 12-pair plateau mean is 0.5222, and at the selected epoch the
12-pair aggregation runs **+0.010 above** the 8-pair one (0.543 vs 0.533) because the four
new pairs happen to score better, so the pair-mix-corrected 8-pair plateau mean is ≈**0.512**
— inside §2's pre-registered "**≤ 0.527 → data volume is not the constraint either**" band.
Combined with R1, that is the strong statement §2 asked for: **M2 on OHLCV is finished.**

🟢 **One genuinely useful negative, though: adding four pairs costs nothing.** The majors'
edge did not degrade, the new pairs are individually as good as the old ones (LINK cov05
`dir_acc` 0.599, XRP 0.606, AVAX 0.557 against BTC's 0.612 and ZEC's 0.515), brier is 0.2495
and the calibration table is monotone. A 12-pair model is a strictly better *product* at the
same measured edge, and it is free at serve time. That is a deployment fact, **not** a
research result, and it should not be counted as an improvement.

🟡 **Read on 2026-08-27, and the qualifier is now half-withdrawn.** "Free" was measured with
M2's ruler, which averages over bars, and the M3 policy instead *picks* the most confident 2%
out of whatever universe it is given. Measured that way the O8 checkpoint looked worth +7.5
net bps/trade on 12 pairs. **The T-wave ran two more seeds and the +7.5 did not replicate**
(§1.10), and T6 showed the comparison cannot be resolved on this evaluation period at all.
What survives is the weaker original claim in this paragraph — a 12-pair model is at worst a
lateral move as a *product*, at the same measured edge. Whether it is slightly better or
slightly worse as a *policy* is now **closed as unanswerable here**, not open.

#### R2 — the magnitude-weighted loss ran correctly and did the opposite of its job

The instrumentation is green: `scale` 0.982–0.989, `at_clip` 0.56–0.77% (well under the 10%
that would have made it a step function), `mean|r|` rising 100.5 → 201.9 → 501.3 bps with the
horizon. So this is a clean measurement of the lever, not of a bug.

It **lost** economics at every coverage — +1.75 / +18.79 / +5.27 gross bps at cov 0.01/0.02/
0.05 against the family's +19.38 / +22.03 / +8.91 — while dropping the plateau mean to
0.5058. §2's pre-registered branch is **"no movement in either → the aux head's weighting is
not the constraint. Closed."**

The mechanism is worth recording because it is the third instance of one failure mode. The
weighting made the head **wildly overconfident**: the coverage-targeted gate landed at
`conf ≥ 0.9797` (the baseline's is 0.6311), 84% of bars clear 0.55, and the calibration table
is **flat at `emp_up` ≈ 0.47–0.51 in every bin from 0.05 to 0.95** with brier 0.3156 vs 0.250.
By §3 item 3c that rejects the run on its own, independent of P&L. Up-weighting large moves
teaches the head that confident-and-large is the same axis as confident-and-correct; it is
not, and the probability output — which is M2's entire deliverable to M3 — stops meaning
anything.

#### R3a / R3b — capacity is not the constraint, in either direction

**R3a (128 units) is the clearest memorization result in the project.** `loss_tr` falls to
**0.888** against the baseline's ~1.72 floor while `loss_va` never gets below **1.0440** —
worse than the family's 1.0398–1.0404 at *every* epoch. That is R1's mechanism reproduced
with parameters instead of columns, and it is why §5's transformer bar stands. Its brier is
**0.4187**, the worst in the ledger: 110,628 bars predicted at p(up)=0.023 and 106,168 at
p(up)=0.976, with `emp_up` flat at 0.47–0.50 across all ten bins. The confidence distribution
has collapsed to the corners while carrying no information. It also inverts §1.2's regime
pattern (window 3 becomes its *best* at 0.585, window 1 its worst at 0.500), which is the
signature of a model fitting something other than the shared structure.

**R3b (32 units) is the more interesting arm and it is a clean null.** Plateau mean 0.5199
over a **36-epoch plateau** — the longest in the project — brier 0.2507 against the
baseline's 0.2501, a monotone calibration table, and §1.2's window pattern reproduced almost
exactly (w1 0.549 / w2 0.621 / w3 0.457 / w4 0.622, against seed 3's 0.593/0.592/0.491/0.621).
Its economics are +20.07 / +16.20 / +4.74, inside single-seed spread of the family. **Half the
width, ~15k parameters instead of ~56k, and it matches.**

Both arms land below 0.5239 — R3b by 0.0040, R3a by 0.0054 — and neither comes near the
+0.011 that §2 required for "capacity is live". **Be precise about which branch fires:** R3b is
inside the pre-registered ±0.005 "flat" band; R3a is 0.0004 outside it, on the *negative* side.
So the literal reading is "one arm flat, one arm marginally worse", which lands in the same
place as "both flat" and more strongly — a lever cannot be live when its upward arm is the
losing one. The bracket also says something the ledger did not have before: 64 units is not a
tuned choice, it is **over-parameterized**, and the encoder is sitting on a flat top between 32
and 64 with a cliff into memorization above it.

#### What did NOT change, and should not be over-read

- **The book-era split is still underpowered, not alarming.** O8's book-era cov05 `dir_acc`
  of 0.476 looks bad next to pre_book's 0.552, but the three baseline seeds span
  0.571 / 0.486 / 0.624 on `n_dir` ≈ 1,500–2,000. O8 is inside that spread. This split has
  never had the power to say anything and still does not.
- **All four beat the momentum baseline**, which sits at `dir_acc` ≈ 0.47 (i.e. trailing-48-bar
  momentum is mildly *anti*-predictive at 4h). No run is a repackaged momentum rule.

---

### 1.10 🟢 The traded universe — closed 2026-08-27, as unresolvable on this data

**The question was: does trading 12 pairs instead of 8 make a better policy?** It arose from a
single 12-pair seed (O8) on which M3-2's winner earned **+7.5 net bps/trade more** than on the
8 baseline pairs — measured cleanly, within one run, with only the universe varying. Two more
12-pair seeds (T1, T2) were trained to replicate it, and T6 then ran the offline tests the
T-wave had skipped. **The answer is that this evaluation period cannot tell**, and the reason
is worth more than the answer would have been.

**Three paired comparisons, all on the same three 12-pair dumps** (T1 `20260827T050701Z`,
T2 `20260827T114122Z`, O8 `20260822T012619Z`), each restricting the same checkpoints to the
8 baseline pairs for the narrow arm so that model, seed and calendar are held fixed:

| comparison | 8 pairs | 12 pairs | difference (wide − narrow) | 95% CI |
|---|---:|---:|---:|---|
| **coverage-matched** — both at cov 0.02, so 12 pairs takes 50% more trades | +9.29 | +9.00 | **−0.29** | [−12.0, +11.5] |
| **trade-count-matched** — 12 pairs cut to cov 0.0129 for the same 1,645 trades | +9.29 | +19.51 | **+10.21** | [−15.6, +36.0] |
| **cut-matched** — both at cov 0.0129, which isolates the pairs from the cut | +22.02 | +19.51 | **−2.51** | [−17.9, +12.8] |

🔴 **The trade-count-matched "+10.21" is not a universe effect.** Matching the trade count
makes the wide arm 1.55x more *selective* as well as wider, and the third row separates the
two: **tightening the confidence cut is worth +12.7 bps on the 8-pair universe by itself**,
while the pairs, at a matched cut, are worth −2.5. The lever that moved was coverage, which
the 8-pair universe can pull too.

🟢 **What actually closes this is a power measurement, not any of those point estimates.** The
cluster-robust SE on the fair difference is **13.2 bps** over ~180 independent exit days, so at
80% power the comparison resolves effects of about **±37 bps and nothing smaller**. The +7.5
that started all this is roughly a *third* of what this data can see. **More seeds do not
help**: extra seeds and extra pairs both add trades that are correlated *inside days already
counted*, which is why widening 8 → 12 raised the trade count 50% (1,645 → 2,475) but the
independent-exit-day count only 11% (169 → 187). Only a longer evaluation period moves this,
and that is calendar, not compute. **Do not queue further work on 8-vs-12.**

⚠️ **Correction to the first T-wave write-up: the published interval was the wrong estimand.**
It read "−0.85 bps, 95% CI [−6.8, +5.1] across 167 shared days" and concluded +7.5 was
excluded. T6 reproduces that number exactly — from a **day-weighted, shared-days-only**
estimator, sitting beside a table of **trade-weighted** means. Equal-weighting days answers a
different question, and coincides with the per-trade difference only if every day carries the
same number of trades in both arms, which is exactly what changing the universe breaks;
restricting to shared days also discards the 22 days on which the two policies most differ.
On the estimator matching the published per-trade statistic the interval is **[−12.0, +11.5],
and +7.5 is inside it.** The T-wave **failed to replicate** the +7.5; it did not refute it.
Both estimators are committed in `m3/universe.py` so the distinction is code, not a memory of
whose script ran.

🟢 **The concurrency cap: re-tuned, and worth nothing.** The widened drawdown (−2.83 → −4.53)
looked like an argument for a cap. Over the pre-registered cap set `max_concurrent=None` wins
on **both** universes, and every cap in the wider ladder costs net bps. A cap does cut
drawdown — by refusing profitable trades.

🔴 **The criterion that actually binds is P3, not P5, and it is not about pairs.** P5
(all seeds pooled-positive) fails on the **incumbent** in 52.4% of day-bootstraps against
46.7% on the challenger — a coin flip, which is why an early draft's "12 pairs fails P5, so
reject it" was worthless. What fails on both arms, in the observed data and in 88–98% of
resamples, is **P3, the −5 bps worst-window floor**. **Window 3 is the binding constraint on
this policy and widening the pair set does not touch it** — its net stays around −18 to −22 on
143–168 trades. The w3 hole is a shortage of *confident bars*, not of instruments.

**Per-pair texture, with the standing caveat.** Inside the coverage-matched wide run the four
new pairs are the profitable half (+15.99 net on 841 trades against the base-8's +5.41 on
1,634). §1.3's rule still applies — per-pair numbers do not replicate across seeds — and this
is **not** a licence to cherry-pick pairs.

**12 pairs does not move the certification problem** (M3_PROTOCOL §2). Only forward time does.

#### Reproduce all of it

```sh
./scripts/m3.sh -m m3 validate          # acceptance tests first, always
./scripts/m3.sh -m m3 universe-fair     # T6: the three tests, the intervals, the power table
./scripts/m3.sh -m m3 universe --runs 20260827T050701Z,20260827T114122Z,20260822T012619Z
```

Full report, including the cap ladder and the per-criterion bootstrap table:
**`docs/T6_RESULTS.md`**.

🟢 **The methodological lessons, which are the durable output of the whole T/T6 sequence.**

1. **A clean comparison on one seed is a hypothesis, not a result.** O8's +7.5 was
   methodologically clean — same checkpoint, same calendar, only the universe varying — and
   the between-seed spread was still larger than the effect.
2. **A negative result needs the same scrutiny as a positive one.** A −0.3 bps point estimate
   and a coin-flip criterion were briefly written up as a rejection.
3. **Report the CI on the *difference*, and make sure the estimator matches the statistic you
   are claiming.** Getting this wrong understated the interval by ~2x and turned "did not
   replicate" into "refuted".
4. **Check a criterion's power before letting it decide** — measure its failure rate on the
   *incumbent* arm, not only on the challenger.
5. **Before running a comparison, ask what effect size the data can resolve.** Had that been
   asked first, the 8h of GPU that produced T1 and T2 would not have been spent: the answer
   was always going to be inside the noise.
---


## §3 — WHAT TO BRING BACK (for the next session)

🔴 **Dormant again as of 2026-08-27 — §2's queue holds no GPU run.** The T-wave was the
last thing this section was live for, and it has landed and been analyzed (§1.10, §2). **If
you are here to analyze a new experiment, something has gone wrong with §2's freeze; check
§5's "M2 as a research object" row before spending GPU.** The section is kept because the
checks below are the accumulated cost of every run that was wrongly declared good, and the
next wave — whenever the §1.7 data condition opens M2 — will need every one of them.

🟢 **Two procedural lessons the T-wave added, and they point in opposite directions — keep
both.** First: **a deployment decision needs the same seed replication as an experiment.**
§1.10's original +7.5 bps came from a within-run comparison that was methodologically clean —
same checkpoint, same seed, same calendar, only the universe varying — and it was still wrong,
because the between-seed spread is larger than the effect. A clean comparison on one seed is a
hypothesis, not a result. Second, and learned immediately afterwards by getting it wrong:
**a negative result needs the same scrutiny as a positive one.** The replication's −0.3 bps
point estimate and a Tier-1 failure were briefly written up as a rejection, before anyone
checked that the interval on the *difference* was [−6.8, +5.1] and that the deciding criterion
fails on the incumbent 53.8% of the time. **Report the CI on the difference, and bootstrap a
criterion's failure rate on both arms, before letting it close a direction.**

⚠️ **The ranking apparatus does not apply to a 12-pair run.** Do not compare a 12-pair
plateau mean to 0.5239 and do not rank one against the §1.3 family: a 12-pair aggregate runs
~+0.010 above an 8-pair one because the four new pairs happen to score better, for reasons
that have nothing to do with the model (§1.9's O8 note). A universe change is judged on the
policy, by the adoption rule, never on a line in the training log.

Two things in the log still decide validity, and both can void a run on their own:
`brier > ~0.27` on the 240m head or a flat calibration bin table (item 3c — it has rejected
four runs and caught all four before the P&L table did), and a `SERVED GATE` above ~0.90.

🔴 **One addition the closing wave earned, and it is now the fastest way to kill a bad run:**
read the `SERVED GATE (C13, coverage-targeted)` line first. The baseline's is `conf ≥ 0.6311`.
**A gate above ~0.90 means the confidence distribution has collapsed to the corners and the
calibration table will be flat**, whatever the LB says — R2 (0.9797) and R3a (0.9999) were both
diagnosable from that single line before any other number was read.

Save each run's full log under `logs/` **named after the queue item** (`Q3.log`, not
the run id), then open a **fresh session** and paste the paths. Do not summarize the logs
yourself — the numbers that matter are often not the headline ones.

```sh
./scripts/gcp_logs.sh <run_id> > logs/<queue-name>.log     # e.g. logs/P0-seed2.log
./scripts/gcp_logs.sh          > logs/<queue-name>.log     # omit the id for the latest run
```

⚠️ **Do not use `--save`.** It copies to `$EXPORT_DIR/<run_id>.log`, and `EXPORT_DIR`
defaults to `$HOME/fluxtrader-train-export` (`scripts/gcp_common.sh:102`) with no override
in `scripts/gcp_env` — so the file lands in the home directory under its raw run id, not in
`logs/` and not under the queue name a later session is told to look for. Redirect stdout
instead; that is how every log currently in `logs/` was produced.

**Self-check before you hand them over** — if any of these fails, the run is void and
should be relaunched rather than analyzed:

```sh
L=logs/T1-12pair-seed2.log                 # repeat for each run in the wave
grep -nE 'resolved knobs|knob |Pair embedding|Training pairs|primary=|Split global_time' $L
grep -nE 'WARNING \[norm\]|max\|z\||BROKEN SCALE' $L
grep -n  'P&L sim:' $L                     # hold must be horizon_min / bar_min (5m/240m ⇒ 48)
grep -n  'Early stop at epoch' $L           # must NOT be 1 + patience
grep -n  'Samples:' $L                      # 5m/8 pairs ⇒ ~2.90M; 5m/12 pairs ⇒ ~4.59M
grep -n  'epoch LB series' $L               # the §0.3 verdict metric, printed by C10
grep -n  'Feature columns:' $L              # the count you intended (19 for the T-wave)
grep -nE 'max\|z\|' $L                     # no new column above ~100 sigma (C15)
grep -n  'SERVED GATE' $L                   # T4 needs this value; >0.90 voids the run
```

**T-wave expectations specifically:** `Training pairs:` lists all 12 in the order given,
`Pair embedding: ON dim=8 n_pairs=12 (+1 OOV bucket)`, `Samples:` ≈ **4.59M**,
`Feature columns: 19`, `hold=48 bars`, and `12/19 CONSTANT` on every pair except
1000PEPE, which is `13/19` because `has_funding_oi` is constant for it too — that is exactly
what O8 printed and it is expected, not a defect. The `hl_range DEGENERATE SPIKE` on most
pairs is the known legacy exception C19 and does **not** void a run (§0.4).
If `n_pairs` says 8, the `TRAIN_PAIRS` env did not reach the VM and the run is void.

**Also compute the plateau-restricted mean (§0.3)** — with C17 unshipped this is manual, and
since Q3 it is the metric that decides the run:

```sh
grep -oE 'epoch [0-9]+  loss_tr=[0-9.]+ loss_va=[0-9.]+.*lb=[0-9.]+' $L | \
  sed -E 's/epoch 0*([0-9]+)  loss_tr=([0-9.]+) loss_va=([0-9.]+).*lb=([0-9.]+).*/\1 \2 \3 \4/' | \
  awk '{e[NR]=$1;va[NR]=$3;lb[NR]=$4;n=NR}
  END{m=99;for(i=1;i<=n;i++)if(va[i]<m)m=va[i];t=m+0.02;
      for(i=1;i<=n;i++){s+=lb[i]; if(va[i]<=t){np++;sp+=lb[i];last=e[i]}}
      printf "all: n=%d mean=%.4f | plateau: n=%d lastEp=%d mean=%.4f\n",n,s/n,np,last,sp/np}'
```

If a log predates C10 and has no `epoch LB series` line, compute it:

```sh
grep -oE 'epoch [0-9]+.*lb=[0-9.]+' $L | grep -oE 'lb=[0-9.]+' | cut -d= -f2 | \
  awk '{n++;s+=$1;q+=$1*$1;if($1>m)m=$1}END{printf "n=%d mean=%.4f sd=%.4f max=%.4f\n",n,s/n,sqrt(q/n-(s/n)^2),m}'
```

**What the next session will read, in order:**
1. The §0.4 verification lines — is the run valid at all.
2. **The per-epoch LB mean ± sd (§0.3), plateau-restricted AND all-epoch** — this is the
   verdict metric now, not the max. **Read the plateau length first:** under ~15 epochs and
   the run is not comparable to the baseline at all, whatever its LB says (§1.6, Q3). Pool
   across seeds when a wave has replicates.
3. `Fixed-coverage P&L` → **gross bps/trade** at cov 0.01–0.20, against 5bps maker **and**
   14bps taker. Since O2 the taker column is no longer automatically negative, so read it.
3b. `dir_acc` alongside every Wilson-LB whenever the arms differ in bar interval (§0.6).
   P2 is the cautionary example: highest LB in the ledger, flat `dir_acc`, worse economics.
3c. **`brier` on the 240m head, and the calibration bin table.** New with the P-wave — P2
   posted respectable `dir_acc` with a probability output that was pure noise as a
   probability (`emp_up ≈ 0.48` in every bin). M2's deliverable to M3 is a *calibrated*
   probability, so a run that improves ranking while destroying calibration has not
   improved. Reject any run whose bin table is flat in `emp_up`.
   🔴 **This check has now rejected four runs on its own — P2 (0.323), R1 (0.286), R2 (0.316)
   and R3a (0.419), against a baseline of 0.250 — and it caught all four *before* the P&L
   table did.** Three of them were changes that had nothing to do with calibration (a
   resolution change, a loss weighting, a width change), which is the point: on this problem
   the probability scale is the first thing to break and the last thing anyone thinks to look
   at. Treat `brier > ~0.27` as a rejection, not a caveat.
4. `--- Walk-forward edge on val window ---` win 1–4 → does the §1.2 regime pattern hold,
   and did anything narrow the window-2-vs-window-3 spread.
5. `Fixed-coverage directional edge` → is the ordering monotone in confidence.
6. `Side split` + `Long/short serial P&L` → one-sided?
7. `Book-era split` → is the edge a calendar confound?
8. `Momentum baseline` + `Buy-and-hold` → did it beat the trivial baselines.

---


## §4 — RESULTS LEDGER

⚠️ **Read §0.3 and §0.6 first.** Every `cov05 LB` below is `max over epochs` of a series
with sd ≈ 0.015–0.023, so differences under ~0.04 between single runs are not evidence —
use the parenthesised `mean±sd` column instead where it exists. And LB is not comparable
across bar intervals (§0.6): O2's LB benefits from 3× the val rows for the same 8 months.
**Post-`2e7b272` runs are a new lineage and are not comparable to anything above the
line.**

| Run | What | Primary | cov05 LB | Valid? | Verdict |
|---|---|---:|---:|---|---|
| **5m/seq384 family** — **O2** `20260818T185438Z` (s1) · **P0-seed2** `20260819T142759Z` · **P0-seed3** `20260820T025723Z` | **5m bars, seq 384 (32h), ~2.90M samples, 3 seeds** | 240m | **pooled mean-of-epochs 0.5219 (between-seed SEM 0.0014)** | ✅ **BANKED — the baseline** | The project's first replicated result. +0.016 ≈ 4σ over F4. Pooled fixed-coverage P&L **+19.4 / +22.0 gross bps/trade at cov 0.01 / 0.02** (1,081 / 1,783 trades) = +5.4 / +8.0 net at 14bps taker. Per-seed max LB 0.5565 / 0.5576 / 0.5425 — all order statistics, do not quote. Did **not** replicate: serial-sim magnitude (§1.5), side balance, book-era split, per-pair numbers. Served gate must become a coverage target (C13). §1.3 |
| **O8** `20260822T012619Z` | **12 pairs** (+ADA/AVAX/LINK/XRP), 4.59M samples (+58%) vs the 8-pair baseline | 240m | **plateau mean 0.5222 (n=17) on the 12-pair population; ≈0.512 pair-mix-corrected to the 8-pair universe** | ✅ valid, **flat — closes data volume** | 58% more training data moved nothing. Re-aggregated locally on `eval_preds.parquet` (harness validated by reproducing the logged 12-pair table exactly): on the **original 8 pairs** gross bps +23.9 / +21.3 / +6.8 at cov 0.01/0.02/0.05 vs the 3-seed family's +19.4 / +22.0 / +8.9 — one seed inside the family spread at every coverage. The 12-pair aggregation reads +0.010 higher than the 8-pair one at the selected epoch (0.543 vs 0.533) purely from pair mix, which is why the headline LB is not the verdict. Inside §2's pre-registered "≤ 0.527 ⇒ data volume is not the constraint" band. 🟢 **But adopting 12 pairs is free:** brier 0.2495, monotone calibration, majors undegraded, new pairs individually good (LINK cov05 0.599, XRP 0.606). A product win, not a research result. §1.9 |
| **T1** `20260827T050701Z` | 12 pairs, `SEED=2`, O8's recipe otherwise unchanged — a T-wave replication seed, not an experiment | 240m | plateau mean n/a — **not comparable** to 0.5239 (12-pair val population, §1.9). Logged: LB series n=34 mean 0.5131, selected epoch 14 | ✅ **valid** | 4.61M samples, 19 feature columns, `n_pairs=12`, brier 0.2496, monotone calibration bins, `SERVED GATE` 0.6288. Contributed to T3's three-seed universe test and to T6's fair re-run, which together closed 8-vs-12 as unresolvable on this evaluation period (§1.10). `logs/T1.log` |
| **T2** `20260827T114122Z` | 12 pairs, `SEED=3`, O8's recipe otherwise unchanged | 240m | as T1 — not comparable. Logged: LB series n=44 mean 0.5148, selected epoch 24 | ✅ **valid** | 4.61M samples, 19 feature columns, `n_pairs=12`, brier 0.2498, monotone calibration bins, `SERVED GATE` 0.6524. ⚠️ **The seed that briefly looked decisive:** +4.91 net bps/trade on 8 pairs, −2.70 on 12, failing Tier-1 P5. **Its cluster-robust 95% CI is [−37.3, +31.9]** — the sign carries no information, which is why P5 could not decide the universe (§1.10). `logs/T2.log` |
| **R2** `20260822T170844Z` | **`DIR_MAG_WEIGHT=1`** — directional CE weighted by realized \|forward return\|, normalized per (pair, horizon) | 240m | **plateau mean 0.5058 (n=12); all-epoch 0.5102±0.011 (n=37)** | ✅ valid, **negative — closes the lever** | Instrumentation green (`scale` 0.982–0.989, `at_clip` 0.56–0.77%, `mean\|r\|` 100.5/201.9/501.3bps rising with horizon), so this measures the lever and not a bug. It **lost** economics at every coverage: +1.75 / +18.79 / +5.27 gross bps at cov 0.01/0.02/0.05 vs +19.4 / +22.0 / +8.9. §2's "no movement in either ⇒ closed" branch. 🔴 **Calibration destroyed** — coverage-targeted gate at `conf ≥ 0.9797` (baseline 0.6311), 84% of bars above 0.55, `emp_up` flat at 0.47–0.51 in all ten bins, brier 0.3156 vs 0.250 ⇒ also rejected by §3.3c. Up-weighting large moves conflates "confident and large" with "confident and correct". §1.9 |
| **R3a** `20260823T053017Z` | **`HIDDEN_SIZE=128`** — double width, all else byte-identical to §1.3 | 240m | **plateau mean 0.5185 (n=26); all-epoch 0.5182±0.013 (n=58)** | ✅ valid, **negative** | The project's clearest memorization result: `loss_tr` → **0.888** against the baseline's ~1.72 floor while best `loss_va` = **1.0440**, worse than the family's 1.0398–1.0404 at *every* epoch — R1's mechanism reproduced with parameters instead of columns. Gross bps +13.4 / +12.0 / +3.5. 🔴 **brier 0.4187, the worst in the ledger**: 110,628 bars at p(up)=0.023 and 106,168 at 0.976 with `emp_up` flat at 0.47–0.50 — the confidence distribution collapsed to the corners carrying no information. Inverts §1.2's window pattern (w3 becomes its best at 0.585). §1.9 |
| **R3b** `20260823T135748Z` | **`HIDDEN_SIZE=32`** — half width, all else byte-identical to §1.3 | 240m | **plateau mean 0.5199 (n=36 — the longest plateau in the project); all-epoch 0.5194±0.013 (n=37)** | ✅ valid, **a clean null — with R3a this closes capacity for good** | −0.0040 vs 0.5239, i.e. flat. brier **0.2507** vs the baseline's 0.2501, calibration monotone, §1.2's window pattern reproduced almost exactly (0.549/0.621/0.457/0.622 vs seed 3's 0.593/0.592/0.491/0.621), gross bps +20.1 / +16.2 / +4.7 — inside single-seed family spread. **A quarter of the parameters (~15k vs ~56k) and it matches.** With R3a, the encoder sits on a flat top between 32 and 64 with a cliff into memorization above: `hidden_size=64` is not tuned, it is over-parameterized. §1.9 |
| **R1** `20260821T182844Z` | **25 columns** = 19 legacy + the 6 own-pair multi-scale (`ret_1h/4h/1d`, `vol_1h/4h/1d`); the well-conditioned half of C12 | 240m | **plateau mean 0.4979 (n=11); all-epoch 0.4889±0.016 (n=38)** | ✅ valid, **decisive negative — closes the lever** | −0.026 vs the family's plateau 0.5239 (between-seed sd 0.0032) ≈ 8σ. Worse than Q3 on every axis. 🔴 **Best `loss_va` = 1.0451, above the family's 1.0398–1.0404 at *every* epoch including epoch 1** — so this is not an overfitting story a `DROPOUT` arm could rescue, and that branch is withdrawn. Calibration flat (`emp_up` ≈ 0.48 in every bin 0.10→0.80; brier 0.286) ⇒ also rejected by §3.3c. Gross bps +8.0 / +11.7 at cov 0.01 / 0.02 vs +19.4 / +22.0. Selected ep 18 sits +0.11 `loss_va` above its own minimum. Mechanism: at seq 384 all six columns are exact functions of bars already in the window ⇒ zero information, six easy-to-memorize channels. §1.6 |
| **Q3** `20260821T…` | **30 candle-derived columns** (C12) vs the 19-col baseline — the feature expansion | 240m | mean 0.5003±0.018 (n=28); **plateau mean 0.5000, n=5** | ✅ valid, **decisive negative for THIS column set** | −0.022 against the family. **Calibration inverted** (`emp_up` 0.495→0.465 as `mean_pred` 0.35→0.75; brier 0.2897 vs 0.250) ⇒ rejected by §3.3c independently. Left its training plateau at **epoch 5** vs the baseline's 21–26 and selected a post-overfit epoch, so it is not a fair test of the lever — see §1.6. Two columns numerically defective (C15). Retest = R1. |
| **Q2** `20260821T…` | **3-seed probability ensemble** (C14) | 240m | cov05 LB 0.561 | ✅ valid, **lever closed** | Matched against Q0 on the same split: dir_acc +0.002, brier −0.0005 (both noise), gross bps **worse at 4 of 5 coverages** (cov02 +10.6 vs +18.7; cov05 +11.9 vs +15.1; cov10 +0.6 vs +6.7). Pre-registered "no better than the best member" ⇒ dropped. §5 |
| **Q0** `20260821T083737Z` | eval-only re-score of seed 2 under C13 | 240m | cov05 LB 0.559 | ✅ | Derived seed 2's coverage-targeted gate: **`conf >= 0.6311`**, dir_acc 0.578, +18.68 gross bps/trade, **+4.68 net at taker**. Gate written to the VM's local copy only — pass it explicitly on promote (§2 R0). |
| **Q1** *(local, no run)* | regime analysis on the three 5m dumps | 240m | — | ✅ **positive** | 9 observables × 3 seeds. Nothing clears the 0.60-AUC bar (max deviation 0.06), but **`btc_absret_1d`** has a monotone quintile ladder in bps *and* dir_acc with three-seed agreement: top quintile (BTC 24h \|ret\| ≥ 4.31%, 5.2% of bars) = **+35.5 gross bps/trade at cov05, +54.9 at cov02** vs +8.8 / +22.0 overall. Direction-free. **An M3 observable, not an M2 feature.** §1.8 |
| **P2** `20260820T100042Z` | **1m bars, seq 768 (12.8h)** — the next resolution rung | 240m | 0.5579 (mean 0.5256±0.015, n=38) — **LB is inflated, do not rank on it** | ✅ **decisive, negative** | Highest LB in the ledger on 5× the val rows, and flat where it counts: `dir_acc` cov05 **0.561 vs the 5m family's 0.559**; gross bps/trade +2.6/+8.5 at cov 0.01/0.02 vs +19.4/+22.0; **brier 0.323 vs 0.250 with `emp_up ≈ 0.48` in every probability bin** — calibration destroyed; 20h wall clock vs 2.5–3h. **Resolution ladder closed at 5m.** §1.4 |
| **O3** `20260819T021020Z` | 15m bars, **seq 256 (64h)** — context length | 240m | 0.531 (mean 0.4925±0.023, n=24) | ✅ **decisive, negative** | Worse than F4 on mean-of-epochs; per-epoch series drifts monotonically down; served-gate coverage collapsed 4.9%→0.8%; up side at 0.499. Longer context is dead and **architecture is closed again**. §1.4 |
| **O0** `eval-only re-score of F4` | F4 on today's eval code, CPU | 240m | 0.531 (reproduced exactly) | ✅ | Delivered F4's missing `Fixed-coverage P&L`: +2.61 / +6.53 / +6.50 / −2.96 / −4.38 gross bps at cov .01/.02/.05/.10/.20. Closes N3-vs-F4 — N3's +4.24 @cov05 is inside noise of F4's +6.50. |
| **F4** `20260817T221811Z` | 15m bars, seq 128, horizon ladder | 240m | 0.531 (mean 0.506±0.016, n=18) | ✅ **prior baseline, superseded by the 5m family** | 4h is the horizon peak. Best cell +6.5 gross bps/trade ≈ maker break-even, never positive at taker. WF .486/.617/.457/.584. C2 table now supplied by O0. |
| **N3** `20260818T031002Z` | cost-aware selection, `SEL_NET_WEIGHT=0.5 SEL_COST_BPS=5` | 240m | 0.523 (mean 0.499±0.016) | ✅ valid, **lever closed** | Selected epoch 1, stopped at 11. Score blend was ~88% cost term and the cost term ranks noise. Gross +4.2bps @cov05 — no better than F4. **Do not promote**; it overwrote `latest.pt`. §1.5 |
| **N2** `gbt-20260818T070504Z` | LightGBM 114-col static summary at 15m/4h | 240m | **0.4692** | ✅ decisive, **re-read after O3** | Below coin flip at every coverage; 0.04–0.06 worse than the LSTM. Originally read as "recurrence matters, try more context". O3 tested that and refuted it, so the surviving reading is narrower: **the 114-column static summary throws information away**, and this says nothing about needing a bigger architecture. §1.4 |
| **N1** `wf-20260818T063858Z` | book ON/OFF walk-forward, 4 long pairs, C4a floor active | 30m | — | ⚠️ **INCONCLUSIVE by its own rule** | 2 of 6 folds decidable; decidable gaps `+0.073`, `−0.122`. Book-OFF collapses to flat and cannot be scored. **Design retired**, see §5. |
| **F3** `wf-20260817T030350Z` | book ON/OFF, 8 pairs | 30m | — | ❌ superseded by N1 | Ran the wrong pair set (dead `WF_LONG_PAIRS_ONLY`), no decidability floor. |
| — | *norm fix `2e7b272` — lineage boundary* | | | | Everything below is measured through the `std=1e-6` bug unless noted. |
| E4-GBT `gbt-20260816T132201Z` | LightGBM, 114-col summary, 30m bars seq 128 (64h) | 30m | 0.5314 | ✅ (scale-invariant) | Tied the LSTM at 30m. N2 shows this does **not** carry to 4h. |
| E3-tb `20260816T023427Z` | triple-barrier labels | 30m | 0.530 | ❌ confounded | 3 variables changed; barriers mis-parameterized. Redo as O7. |
| E2b `20260813T114311Z` | pair-embed dim=8, 8 pairs | 30m | 0.566 | ❌ **retired** | Measured through the bug on a since-changed dataset. |
| E3b1 / E3b2 | pair-embed dim 4 / 16 | 30m | 0.559 / 0.554 | ❌ | Dim curve flat — and by §0.3 it was always going to be. |
| E2a′ / E2c | pair-set sweeps | 30m | 0.568 / 0.559 | ❌ | "More pairs > fewer" — conclusion may survive, evidence does not. |
| E1a / E1b | 4h / 1d primary at 1m bars | 240m / 1440m | 0.533 / 0.523 | ❌ | Rejected at the time for book-era collapse = the norm cliff. F4 supersedes. |
| R0–R6 | staleness fix, cost-sel, capacity, rebalance | 30m | 0.542–0.559 | ❌ | The "tuning ceiling" narrative; the whole 0.017 spread is under one §0.3 sd. |
| ablate `20260804T083752Z` | book ON/OFF, single dense window | 30m | ON 0.691 / OFF 0.494 | ✅ (`--require-book`) | The strong book result. Never replicated. Unconfirmed and now unfalsifiable by this design (§5). |
| E3a `20260814T144713Z` | 12 pairs | 30m | — | ❌ VOID | Log truncated + embed off. Redo as O8 — now cheap (§1.7). |

---


## §6 — OPEN CODE TASKS

**C0, C1, C2, C4a are DONE** (2026-08-18, committed in `5f4046e`) and were exercised by the
N-wave: C0's `CANDLE_INTERVAL` forwarding reached the GBT container, C1's served-gate
warning fired on N3, C2's fixed-coverage P&L table printed, C4a's decidability floor
correctly marked four N1 folds undecidable. **C6 is DONE** — a backfill landed and 1m/5m
now start 2022-08-18 for all nine long pairs (§1.7).

### The C-batch — DONE 2026-08-18

- ✅ **C7 — `gcp_train.sh --eval-only <ckpt-key>`.** Takes a bare filename, a
  `checkpoints/<name>.pt` key or a full `gs://` URL; verifies it exists **before** creating
  a VM (and lists the available keys if not). Restores the DB dump as usual, skips
  `train_m2.py`, evals the named checkpoint, and **never writes `checkpoints/latest.pt`**,
  so a re-score cannot be promoted by mistake. Implies `--cpu` unless `--gpu` is passed.
  Unlike a training run it does **not** swallow an eval failure — eval is the whole job, so
  a failure stops the VM for debugging instead of reporting DONE.
  - **Bundled fix:** `eval_m2.py` now takes `candle_interval` from the checkpoint meta
    instead of ambient config, and says so in the log. This is what makes re-scoring an old
    checkpoint meaningful at all — F4 is a 15m model and the config default is 1m.
  - **Bundled fix:** `--cpu` now forces `TRAIN_DEVICE=cpu`. It previously only chose the
    machine type, so a `TRAIN_DEVICE=cuda` in `scripts/gcp_env` would have run the GPU
    docker path on a CPU VM.
- ✅ **C8 — launcher control over `EARLY_STOP_PATIENCE`, and a real `SEED`.**
  1. `EARLY_STOP_PATIENCE` is in `FLUX_TRAIN_ENV_KEYS`.
  2. `SEED` (`config.py`, default 42) seeds `random`/`numpy`/`torch`/CUDA at the top of
     `train_m2.main`, is exposed as `--seed`, is forwarded via the allowlist, and is echoed
     in the log. Sweep `SEED=1,2,3` for the §0.3 error bars.
  - **Bundled fix:** `docker-compose.yml` defaulted `EARLY_STOP_PATIENCE` to 5 while
    `config.py` said 10, so with the knob unset the CPU path ran half the patience of the
    GPU path. Now both are 10.
  - ⚠️ **Still divergent, deliberately left alone:** compose defaults `BATCH_SIZE` to 128
    vs `config.py`'s 256. Set `BATCH_SIZE` explicitly on any CPU-vs-GPU comparison.
- ✅ **C9 — `eval_m2 --dump-preds`.** Writes `OUTPUT_DIR/eval_preds.parquet` with
  `(ts, pair, horizon, side, conf, p_up, fwd_ret, y3, has_book)` for every val bar and
  every horizon. `ts` is epoch **nanoseconds** UTC; `side` is -1/+1; `y3` is 0/1/2.
  `side`/`conf` come from the same directional signal the gate uses, so re-aggregating this
  table reproduces the printed fixed-coverage rows exactly. Falls back to `eval_preds.csv.gz`
  (same columns) if the image lacks a parquet engine — `pyarrow` was added to both
  requirements files, but a reused VM image may predate it. The eval runner is now on by
  default, so **every** run produces the dump, not just eval-only ones.
- ✅ **C10 — epoch-distribution summary.** Training ends with
  `epoch LB series @cov0.05: n=… mean=… sd=… max=… selected=epoch N (lb=…)` followed by
  `selected - mean = ±… (… sd)`. Read the second line first: a gap within ~1 sd is the
  order statistic, not a result.

### The C-batch — DONE 2026-08-21 (the Q-wave code, committed together)

- ✅ **C13 — safe promotion + a coverage-targeted served gate.** This was Q0.
  1. `gcp_promote.sh --checkpoint <key>` is now **required**; the bare form refuses and
     prints the promotable keys. Accepts a bare filename, `checkpoints/<name>.pt`, a
     `gs://` URL, or the literal `latest`. It also pins serve code to the commit
     encoded in the checkpoint's own filename (`m2_multi_<run>_<sha8>.pt`) rather than
     the ambient `GIT_REF`, so a named historical checkpoint is served by the code
     that wrote it. `--list` shows what is promotable.
  2. **The gate is a coverage target, not a probability.** `SERVE_TARGET_COVERAGE`
     (config, default **0.02**, in `FLUX_TRAIN_ENV_KEYS`) says what fraction of bars
     should trade. `eval_m2.py` measures the confidence threshold that realizes it on
     the val window, prints a `SERVED GATE (C13, coverage-targeted)` block with the
     realized dir_acc and gross/net bps, and **writes `meta.served_gate` into the
     checkpoint file**. Because the runner evals before uploading, a training run now
     ships a checkpoint carrying its own operating point. Every `*` marker, serve-gate
     row, long/short split and per-pair line in the log follows that derived gate
     instead of the config constant.
  3. `serve.py` reads `meta.served_gate`. Precedence: explicit env override >
     checkpoint > config default, each logged, and `/health` + every prediction now
     report `gate_source` (`checkpoint` / `config-fallback` / `env-override`) and
     `gate_target_coverage`.
  4. ⚠️ **`docker-compose.yml` no longer defaults `GATE_THRESHOLD`.** It was
     `${ML_GATE_THRESHOLD:-0.58}`, which as an override would have defeated all of the
     above on every deploy — trap §0.5.2 in a new costume. It is now
     `${ML_GATE_THRESHOLD:-}`, and an empty value means "use the checkpoint".
     The Elixir side already prefers serve's `gate_threshold` over its own env, so it
     follows automatically.
- ✅ **C14 — multi-checkpoint ensemble eval.** `--eval-only` (and `eval_m2.py
  --checkpoint`) take a comma-separated list. Members are averaged on **probabilities**,
  not logits — each member's softmax is averaged and stored back as log-probabilities,
  so every downstream table sees exactly the mean probability and calibration means what
  it says. Members must agree on candle interval, seq_len, feature_dim, the feature
  column list, horizons and primary; a mismatch **exits 2** with a diff rather than
  averaging two different experiments. Architecture differences only warn. The norm
  range report runs for every member, so `BROKEN SCALE` still guards each one. An
  ensemble's derived gate is reported but deliberately **not** written into any member.
- ✅ **C12 — `FEATURE_DIM` 19 → 30.** Eleven new columns, all candle-derived (§1.6
  explains why nothing microstructure-shaped can be added yet):
  - own-pair multi-scale: `ret_1h`, `ret_4h`, `ret_1d`, `vol_1h`, `vol_4h`, `vol_1d`
  - market context: `btc_rel_ret_1h`, `beta_btc_1d`, `xs_rank_1h`, `xs_disp_1h`,
    `has_market`
  - Windows are in **minutes** and converted per candle interval, so `ret_1d` is a day
    at 1m, 5m and 15m rather than a different span at each.
  - **Old checkpoints still work.** `FEATURE_COLS[:19]` is frozen as
    `LEGACY_FEATURE_COLS`, new columns are appended after the masks, and train records
    `meta.feature_cols`. eval/serve rebuild the checkpoint's own list, falling back to
    the legacy prefix for pre-C12 checkpoints. Verified byte-identical.
  - The cross-pair columns are computed in a **second pass** over all pairs (a ragged
    timestamp join, since pairs list on different dates), then patched into the
    existing float32 matrices, so peak memory is unchanged. Serving needs the same
    context, so it loads the universe through a candles-only path cached for
    `MARKET_CACHE_TTL_S` (default 30s). Train-vs-serve parity was verified exact
    (max |train − serve| = 0 on all five columns), and a failed context degrades to
    zeros with `has_market=0` rather than refusing to serve.

### The C-batch — DONE 2026-08-22 (unblocks R1)

- ✅ **C15 — the two Q3 conditioning defects.** Three changes, all in the market-context
  path, plus a detector that would have caught the first one:
  1. **`beta_btc_1d` no longer computes BTC's beta against itself.** It is `cov(r,r)/var(r)`
     = 1 identically, so it carried no information for that row; it was emitted as 1.0
     everywhere except a handful of warm-up / sub-floor bars at 0.0, giving a raw std of
     ~1e-3 — above the `1e-8` CONSTANT threshold, so it was never zeroed, and the
     normalizer rendered those few bars as a **590σ** spike. The BTC row now emits a clean
     constant and the existing degenerate handler zeroes it, exactly as it already did for
     `btc_rel_ret_1h` on that row. Verified: BTC's column is now single-valued and
     `std <= 1e-8`; other pairs' betas are unchanged and still computed.
  2. **The beta variance floor is relative, not absolute.** `b_var > 1e-12` sat ~6 orders
     of magnitude below a real `var(ret_1)` (≈2.3e-6 at 5m), so it floored nothing — trap
     §0.5.5 in yet another costume. It is now a fraction of BTC's own median rolling
     variance (`BETA_VAR_FLOOR_FRAC`, default 0.01), so it means the same thing at 1m, 5m
     and 15m and for a quiet pair as for a loud one. Verified: on normal data it masks
     exactly the one warm-up row, and on a deliberately dead 24h stretch it masks that
     stretch instead of dividing by ~1e-14.
  3. **`norm_range_report` now distinguishes a degenerate spike from a fat tail.** `max|z|`
     alone cannot: in test, a genuine heavy-tailed column reached **694σ** and a degenerate
     one only **573σ**. The discriminating signal is how *populated* the tail is. The report
     now counts rows beyond the clip and prints either
     `<== DEGENERATE SPIKE (7 of 2300000 rows beyond 50 sd)` or
     `(heavy tail … 69 rows beyond — a populated tail, not a spike)`. Add this to the §0.4
     scan; it is the check that would have caught `beta_btc_1d` from Q3's log alone.
  4. 🔵 **`xs_disp_1h` is NOT a defect — that claim in the first Q-wave writeup was wrong
     and is withdrawn.** Measured on the val window, cross-sectional dispersion has a
     genuinely *populated* tail (347 rows beyond 5σ, 44 beyond 10σ), which is the same class
     as `hl_range`'s long-accepted 212–364σ and is what a real market-wide volatility event
     looks like. Its 122σ is a fat tail, correctly winsorized at ±50. **No change made.**
     Q1 separately shows dispersion carries no economic signal (§1.8), so the reason to drop
     it is uselessness, not breakage — and R1 drops the whole group anyway.
- ✅ **C16 — `max_dd` is a drawdown again.** `eval_m2.py` built its equity curve from
  `sorted(day_net.values())` — the daily P&L sorted by **value**, so every losing day came
  first and `max_dd` was simply "the sum of all negative days", a deterministic artifact in
  **every log written before 2026-08-22**. Now `[day_net[d] for d in sorted(day_net)]`,
  which is chronological (`_ns_to_day` emits `YYYY-MM-DD`). **Bundled fix:** the running
  peak started at day 1's equity rather than at 0, so a strategy that lost from the first
  day was measured against its own first loss; the curve is now prepended with 0.
  `daily_sharpe` was never affected (mean and std are order-invariant). Verified against
  four hand-computed sequences. ⚠️ **Every `maxdd` printed before this fix should be
  ignored, not re-interpreted** — including those in §4's ledger and in the archive.
- ✅ **C18 — the `FEATURE_GROUPS` knob.** `FEATURE_COLS` was the unconditional
  concatenation of the three groups and `FEATURE_DIM` was asserted equal to its length, so
  running a subset meant editing source. `FEATURE_GROUPS` (default
  `legacy,multiscale,market`) now composes the list and `features.FEATURE_DIM_EFFECTIVE` is
  derived from it; the model, the checkpoint meta and the empty-bundle placeholders all
  follow the derived value. Details that matter:
  - **The default is byte-identical to the 30-column set** — verified — so this is a no-op
    unless set.
  - **Group order is canonical, never the order typed.** `market,legacy` resolves to
    `legacy,market`, because `LEGACY_FEATURE_COLS == FEATURE_COLS[:19]` is a serving
    contract.
  - **It raises rather than falling back** on an unknown group, on an empty spec, and on
    dropping `legacy` — a silent fallback on a feature-set knob would make a run
    un-attributable, which is the whole reason the knob exists (trap §0.5.3).
  - **`ALL_FEATURE_COLS` is new and is what reconstructs old checkpoints.** Rebuilding the
    columns of a checkpoint that recorded none is *positional*, so it must index the
    canonical 30, not whatever subset this process is configured for — otherwise a
    30-column checkpoint re-scored under `FEATURE_GROUPS=legacy,multiscale` would be
    rebuilt from a 25-entry list. `eval_m2.py` and `serve.py` both use it now.
  - **`FEATURE_GROUPS` is in `FLUX_TRAIN_ENV_KEYS`** (§7) — without that it would be a
    silent no-op on the GPU VM and R1 would quietly re-run Q3 (trap §0.5.7).
  - Training logs now echo `Feature groups: legacy,multiscale -> 25 columns (…)` next to
    `Training pairs:`.

### Later

- ⬜ **C20 — a 12-pair dump pool in `ml/train/m3/dumps.py`. Demoted 2026-08-27: it no longer
  blocks anything.** T3 ran entirely through `m3 universe --runs`, which already takes run
  ids, and T6's `m3 universe-fair` does the same (§1.10). 🟢 **It did not come back:** T6's cap
  re-tune ran on both universes through the same run-id path. If a universe grid re-run is
  ever attempted this is still the blocker. Build it if a future wave needs `cmd_search` / `cmd_learn` — whose grids are
  wired to the baseline pool — to run over a non-baseline population. If so, add a **second** pool (`T_RUNS` and a
  `load_t_wave()` beside `load_baseline()`) rather than editing `BASELINE_RUNS` or `BASE8`:
  every published M3-2 and M3-3 number must stay reproducible from the command that produced
  it. The T-wave dumps are `20260827T050701Z` (T1) and `20260827T114122Z` (T2).

- ⬜ **C17 — print the plateau-restricted epoch-LB mean.** C10 prints the all-epoch mean,
  which §0.3 now shows is not comparable between runs whose overfitting onset differs. Add
  `plateau: n=… lastEp=… mean=…` (epochs whose `loss_va` is within 0.02 of the run's
  minimum) to the same summary line, and warn when the plateau is under ~15 epochs. Until
  it ships, §3 has the one-liner that computes it.

- ⬜ **C19 — triage `hl_range`'s spike-shaped tail (low priority, no run blocked).** C15's
  detector fires on `hl_range` for six of eight pairs with `max|z|` 66–364 and only 2–4 rows
  beyond 50σ out of ~420k, which its rate-based rule correctly calls a spike rather than a
  populated tail (SOL at 6 rows and HYPE at 2-of-128k fall the other side and are labelled
  benign). `hl_range` is a **legacy** column, so the 3-seed baseline in §1.3 has carried this
  from the beginning and R1 did not introduce it — the values are byte-identical to Q3's.
  Handful-of-rows scale, winsorized at ±50, so the practical impact is nil. Worth one query
  on the VM to confirm those rows are real flash candles rather than a bad bar, and then
  either whitelist the column in the detector or drop the offending bars. **Do not treat a
  `DEGENERATE SPIKE` on `hl_range` as a reason to void a run** — update §0.4's row to say so
  when this is resolved.

- ✅ **C3 — magnitude-weighted directional loss. DONE 2026-08-22. Unblocks R2.**
  `DIR_MAG_WEIGHT=1` weights each moved bar's directional CE by its realized
  `|forward return|`, so being right on a large move counts for more than being right on a
  small one. Two design points carry the weight of the change:
  - **The weight is normalized per (pair, horizon)** against that cell's train-window mean
    `|r|`. 1000PEPE's typical move is ~10× BTC's and a 24h move is an order of magnitude
    larger than a 1h one, so a raw `|r|` weight would silently reweight the *pair mix* and
    the *horizon mix* rather than the move sizes — trap §0.5.8 in a new costume. Measured on
    a 3-pair fixture whose pairs differ 10× in `|r|`: per-pair mean weight comes out
    0.998 / 1.002 / 1.000, a 0.4% spread. Within a pair, top-quintile moves outweigh
    bottom-quintile by **25.7×**.
  - **`scale` renormalizes E[w] to exactly 1.0 on the train window** after the power and the
    clip, so `DIR_LOSS_WEIGHT` keeps its meaning and the printed loss stays comparable to an
    unweighted run. Verified `mean=1.000000`.
  - Knobs: `DIR_MAG_WEIGHT` (default **off**), `DIR_MAG_WEIGHT_POWER` (default 1.0 =
    P&L-proportional; 0.5 is the gentler arm), `DIR_MAG_WEIGHT_CLIP` (default 5.0 — one
    20σ bar must not own a batch's gradient). All three are in the launcher allowlist and
    are echoed by the generic `knob K=V` loop, on both the GPU and CPU paths.
  - **Off is byte-identical to the incumbent** — asserted, not assumed: the weighted
    reduction `sum(cw·w·ce)/sum(cw·w)` reduces exactly to
    `nn.CrossEntropyLoss(weight=dw)`'s `sum(cw·ce)/sum(cw)` when every `w` is 1, and the
    check compares the two to 12 decimal places.
  - A degenerate pair (all-zero returns) falls back to the global mean with a relative
    floor rather than dividing by ~0 — §0.5.5 applied to a divisor.
  - **Regression check:** `docker compose --profile ml run --rm --no-deps ml_trainer python
    check_c3_dir_mag.py` (7 groups, all passing). Re-run it if the directional loss or the
    class-weighting path is touched.
- ⬜ **C4b — barrier-aware `simulate_pnl`.** Under triple-barrier labels the model predicts
  a TP/SL outcome but `simulate_pnl` books `fwd_ret` at a fixed `hold_bars` — a policy
  mismatch. Walk forward to first TP/SL touch, else timeout. **Blocks O7.**
- ⬜ **C4a-remainder — matched-`n_dir` walk-forward comparison.** Lower priority now that
  the two-arm design is retired (§5), but the same idea is what would let O5's within-model
  attribution be scored fairly.
- ⬜ **C5 — `oi` conditioning.** `oi = log1p(open_interest)` is a *level*: near-constant in
  any short window, so ordinary drift becomes hundreds of sigma. Drop the raw level and keep
  `oi_chg`, or use a rolling-normalized version. Same question for `log_vol`. Only matters
  inside a dense-book arm, since both are currently dead in the global train window (§1.6).
- ⬜ **C11 — `torch==2.5.1+cpu` pin.** No longer resolves on the PyTorch CPU index, so
  `ml_trainer` fails a clean rebuild; `gcp_gbt.sh` works around it in the throwaway VM only.
  Fixing the pin properly changes served numerics → its own decision. (Split out of the old
  C6, whose backfill half is now done.)

---

---

# The arrival-rate finding, 2026-09-01 — SUPERSEDED, moved out of BACKLOG on 2026-09-04

**This is HISTORY. Do not act on it.** It was superseded on 2026-09-03: the silence it measured was the candle-poll defect, not the market. The repaired answer is that the cut does fire — last on 2026-08-31, longest dry spell 51.8 days.

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
