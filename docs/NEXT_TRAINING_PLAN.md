# Training plan — what is true, what to run next

**Last updated: 2026-08-18** (after F3 walk-forward + F4 horizon run returned).

This document is the project's session-to-session memory. It contains only what is
**currently true and actionable**. The session-by-session narrative from 2026-07-23 →
2026-08-17 — every superseded plan, every rejected hypothesis, every raw results table —
now lives in **`docs/archive/TRAINING_HISTORY.md`**. Go there for "why was X decided";
do not act on anything in it.

**How to use this doc:**
- §0 — standing rules. Read before touching anything. Every rule cost us a real run.
- §1 — where we are, in numbers. The current reference points.
- §2 — **the run queue.** This is the "what do I type" section.
- §3 — what to bring back so a fresh session can decide.
- §4 — results ledger (one row per run, with a validity flag).
- §5 — levers that are closed, and why. Don't re-propose these.
- §6 — open code tasks.
- §7 — mechanics (scripts, promote, fetch).

---

## §0 — STANDING RULES

### 0.1 Data lives on the always-on VM, never the local DB

**The source of truth for ALL data is the always-on GCP VM `fluxtrader-1`.** Training,
eval, backfill and data-collection all run against the collector Postgres there. The
local `docker compose exec postgres` is a **throwaway dev DB** — it does NOT mirror the
VM's candle/book history, its whitelist, or the backfilled pairs. **Never reason about
pair readiness / history / row counts from the local DB.**

```sh
./scripts/gcp_data_collection_stats.sh          # the ONLY correct way to see what exists
# ad-hoc:
gcloud compute ssh --zone me-central1-b fluxtrader-1 --project fluxtrader -- \
  'cd ~/trading_agent && docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -c "SELECT …"'
```

The 4 extra pairs `AVAXUSDT,LINKUSDT,XRPUSDT,ADAUSDT` **do** have substantial backfilled
candle history on the VM. (Lesson 2026-08-16: an agent checked the local DB, saw partial
history, and wrongly declared them unusable.)

### 0.2 One change per run

Never change data AND architecture/selection/labels in the same run — the result becomes
un-attributable. This rule has voided E3a, E2b(v1) and E3-tb.

### 0.3 Verify these lines in EVERY log before trusting a run

Each line is here because its absence voided a real run.

| grep for | must say | voided |
|---|---|---|
| `=== resolved knobs:` + `knob K=V` | the env you intended | R3 |
| `Pair embedding:` | `ON dim=8`, not `off` | E3a, E3-tb |
| `Training pairs: [...]` | the intended set | F3 |
| `primary=` | matches intent | R3 |
| `Split global_time … train [..] val [..]` | **record it** — a backfill moves it | E2b comparability |
| `WARNING [norm] …` | how many columns degenerate, and which | — |
| `[norm] <pair>: max\|z\|=` | must NOT say `BROKEN SCALE` | all pre-`2e7b272` runs |
| `P&L sim: … hold=N bars` | N == horizon_minutes / bar_minutes | F4 prereq |
| `WARNING: at the SERVED gate` | absent — if present, the checkpoint never reaches the served confidence and would trade nothing | (new 2026-08-18) |
| `Fixed-coverage P&L` | present — if missing, the run predates C2 and cannot answer the cost question | (new 2026-08-18) |

### 0.4 Standing traps

1. Data lives on the VM, not the local DB (§0.1).
2. **Env knobs whose default ≠ the incumbent silently change the experiment.** Echo every
   knob. Prefer defaults that equal the incumbent. (`PAIR_EMBED_DIM` was fixed this way:
   default flipped 0 → 8.)
3. **Silent fallbacks** (`.get(x, default)`) on horizons/intervals/primary. Make them raise.
4. **A backfill landing mid-experiment moves the train/val split.** Pin and re-record it.
5. **Additive epsilons are not floors.** (`std = sqrt(var) + 1e-6` — the 2026-08-17 P0 bug.)
6. **A knob that is only applied `if [[ -z "$OTHER" ]]` is dead** if `$OTHER` has a
   default. That is exactly how `WF_LONG_PAIRS_ONLY` silently did nothing in F3 — see §1.3.

---

## §1 — WHERE WE ARE (2026-08-18)

### 1.1 The one-paragraph summary

The normalization bug is fixed and committed (`2e7b272`), so the lineage restarts there —
nothing measured before it on a global-time split is comparable to anything after it. The
first post-fix run (F4) tested the cost/horizon thesis and **partially confirmed it**:
gross P&L per trade scales with √horizon exactly as predicted, and 4h is the peak of the
horizon curve. But the absolute level is still ~0: **the gross, pre-cost edge is
indistinguishable from zero at every horizon and every operating point.** The fee
assumption is no longer the binding constraint — there is no gross edge for a lower fee
to protect. Separately, every log we have ever read reports P&L at a gate threshold that
sits below the mathematical floor of the confidence statistic, and therefore at a gate that
cannot fire and is not the one we serve — so the operating point has never actually been
measured.

### 1.2 Current reference numbers — F4 (the new baseline)

Run `20260817T221811Z` · ckpt `m2_multi_20260817T221811Z_94614795.pt` · `logs/F4.log`
Config: `CANDLE_INTERVAL=15m`, seq 128 (= 32h context), `PAIR_EMBED_DIM=8`, fixed labels,
8 pairs, horizons 60/240/1440, primary 240.
Split: `train [2022-08-19 21:45 → 2025-12-08 18:00]`, `val [2025-12-08 18:00 → 2026-08-16 22:45]`,
964,627 samples (771,701 / 192,926). **Pin this split; re-record it if a backfill lands.**

| | 1h | **4h (primary)** | 24h |
|---|---:|---:|---:|
| cov05 dir_acc / Wilson-LB | 0.518 / 0.507 | **0.543 / 0.531** | 0.525 / 0.513 |
| cov10 LB | 0.512 | 0.526 | 0.497 |
| cov01 LB | 0.505 | **0.471** ⚠️ below coin flip | 0.547 |
| gross bps/trade @ conf≥0.60 | +2.9 | **+6.2** | −33.2 |
| coverage @ conf≥0.60 | 0.6% | 2.6% | 11.0% |

Baselines in the same window: momentum (sign of trailing 16 bars) cov05 LB **0.457**;
buy-and-hold pooled **−8.005**. The model beats both. Both are negative.

**4h walk-forward across the val window: `0.484 / 0.623 / 0.454 / 0.583`.** Two of four
2-month windows are below coin flip. This is the single most important number in F4: the
headline 0.531 is the average of a wildly unstable series, not a persistent edge.

**Training barely fits.** `loss_tr 1.7317 → 1.7009` over 18 epochs, val loss flat, best at
epoch 8, and epoch 1 already scored 0.524. At 15m bars there are only 771k train samples.

**F4 is candle-only.** 12 of 19 features are constant in the train window and are
correctly zeroed by the F1 fix. F4 says nothing about microstructure.

### 1.3 F3 (book ON/OFF walk-forward) — FAILS its rule, but is NOT decidable

`logs/F3.log`, run `wf-20260817T030350Z`. Per-fold book-ON − book-OFF Wilson-LB gap:
`−0.035, −0.107, −0.161, +0.103, +0.273, −0.005`. **Min gap −0.161** → fails the
pre-registered "> +0.05 on all folds" rule.

Two defects mean this is "no evidence", not "proven no edge":

1. **`WF_LONG_PAIRS_ONLY=1` was silently ignored.** `gcp_walkforward.sh:99` applies it only
   `if [[ -z "$PAIRS_ARG" ]]`, but `PAIRS_ARG="${TRAIN_PAIRS:-}"` (line 86) and
   `scripts/gcp_env:51` pre-sets `TRAIN_PAIRS` to the 8-pair list. The knob is dead code.
   F3 therefore ran on 8 pairs including ZEC (22d book) and 1000PEPE (20d) — **shorter
   book history than the dense window**, which injects ragged `has_book` into the
   book-ON arm only. Third occurrence of trap §0.4.2.
2. **Every book-OFF arm is below the harness's own reliability floor.** Back-solving
   `checkpoint_score` from fold 0 (`lb=0.671`, `score=0.2470`) gives `min_gated = 500`.
   Book-OFF `n_dir` across the six folds: `184, 389, 186, 211, 417, 464` — **all six under
   500**, i.e. `checkpoint_score` itself down-weights them as untrustworthy, while
   `compare.txt` prints the raw unpenalized LB anyway. Book-ON: `1233, 487, 1463, 1844,
   764, 1515`.

The mechanism is visible: book-OFF collapses to flat (`3cls_pred f=0.78–0.93`, selected at
epoch 1–4) and concentrates its top-5% confidence on bars that are **truly flat**, leaving
~200 directional leftovers to score on. Book-ON's top-5% is ~51% truly-directional. The two
arms are not measuring the same population. "Picks bars that actually move" is the property
we want, and it is the one being penalized.

**So: the 2026-08-04 single-window result (ON 0.691 / OFF 0.494) did not replicate, and F3
cannot refute it either.** See N1 in the queue.

### 1.4 The gate sweep in eval is mostly dead rows, and its `*` marker lies

`gate.py:60-64`: `conf = max(p_down, p_up)` where `p_down + p_up = 1` (the flat column is
`-inf`). **So `conf ≥ 0.5` by construction** — any threshold at or below 0.50 trades every
bar.

- `scripts/gcp_train.sh:722,727` hardcodes `--gate 0.35,0.4,0.45,0.5,0.55,0.6`. **Four of
  six rows are below the floor and are the same row** — F4 shows `coverage 1.000` and
  byte-identical P&L for all four. Only 0.55 and 0.60 carry information.
- `config.py:201-202` defaults `GATE_THRESHOLD` / `CONFIDENCE_THRESHOLD` to **0.40**, and
  `GATE_THRESHOLD` is **not** in `FLUX_TRAIN_ENV_KEYS`, so eval on the train VM always runs
  at 0.40 and prints `Directional gate: … (serve default GATE_THRESHOLD=0.4)` plus a `*`
  marker on that row. **That label is false.**
- ✅ **Production is NOT affected.** `docker-compose.yml:14,65` set both `ML_GATE_THRESHOLD`
  (Elixir app) and `ml_inference`'s `GATE_THRESHOLD` to **0.58**, raised deliberately on
  2026-07-23 for exactly this reason. The served gate does fire.

Net effect: every "P&L at the serve gate" line in every log — including F4's — is reported
at 0.40, a gate that cannot fire and is not the gate we serve. We have **never** printed the
P&L at the actual operating point (0.58). Fix is code task **C1**.

Also note F4's head *does* have real confidence spread (`conf ≥ 0.60` selects 2.6% of bars
at 4h; calibration mass reaches 0.80), which contradicts the archive's "the head emits no
confidence spread" — that reading came from the four dead rows plus the norm bug.

### 1.5 The cost/horizon arithmetic, corrected

Cost model: **taker = 14bps** round-trip (`FEE_RATE_BPS=4` + `SLIPPAGE_BPS=3`, ×2 sides);
**maker = 5bps** (`FEE_RATE_BPS=2` + `SLIPPAGE_BPS=0.5`, ×2).

`net_ret` is **exactly linear in cost** and trade selection is cost-independent
(`eval_m2.py:143`, `simulate_pnl` books `side*r − cost`). So maker numbers never need a
re-run — they are arithmetic:

```
net_ret(c) = net_ret(0.0014) + n_trades × (0.0014 − c)
```

F4 re-reported at maker cost:

| horizon | gate | trades | net @14bps | net @5bps | gross bps/trade |
|---|---|---:|---:|---:|---:|
| 1h | ≤0.50 | 48,232 | −68.41 | −25.00 | −0.18 |
| 1h | 0.60 | 413 | −0.46 | −0.09 | +2.9 |
| **4h** | ≤0.50 | 12,064 | −16.52 | −5.66 | +0.31 |
| **4h** | 0.55 | 3,070 | −5.48 | −2.72 | −3.9 |
| **4h** | 0.60 | 592 | −0.46 | **+0.07** | **+6.2** |
| 24h | ≤0.50 | 2,016 | −2.82 | −1.01 | ~0 |
| 24h | 0.60 | 621 | −2.93 | −2.37 | −33.2 |

One cell is positive: 4h @ conf 0.60, +1.2bps/trade over 592 trades in 8 months. Noise.

**The horizon thesis is confirmed in shape, refuted in level.** Gross/trade went 1.78bps
(E4-GBT, 30m) → ~6bps (F4, 4h): a 3.5× lift against √8 = 2.83 predicted. The physics is
right. The level is 2× short of maker cost and 2.3× short of taker cost at the *best*
operating point, and ≈0 everywhere else.

⚠️ **The theoretical break-even table in the archive is optimistic.** It assumes correct
and incorrect trades have the same E|r|. Measured gross at 4h/all-bars is **+0.31bps**
where `(2·0.508−1)·85bps` predicts **+1.4bps**. Two causes: the sim books true-flat bars
(the 4h flat band is ±60bps and covers ~54% of bars), and the model is systematically
right on smaller-than-average moves. **Always rank arms on measured gross bps/trade, not
on a dir_acc-derived break-even.** That is what C2 exists to print.

### 1.6 Data status (verified on the VM, 2026-08-17)

| source | coverage |
|---|---|
| `orderbook_snapshots` | BTC/ETH/SOL **31d** (from 2026-07-17 21:13) · DOGE/HYPE/WLD ~28d · ZEC ~24d · 1000PEPE ~22d · ADA/AVAX/LINK/XRP ~4d. Cadence ~1/10s. |
| `orderbook_levels` (raw L2) | all 8 main pairs **~13d** (from 2026-08-05), 100 bid + 100 ask levels, `missing_update_id=0`, `missing_event_time=0`. Clean. |
| `market_trades` | mirrors snapshots |
| `open_interest` | mirrors snapshots |
| `funding_rates` | 2y9mo–3y11mo — the only microstructure source with real history |
| `liquidations` | **0 rows** — WS egress blocked from datacenters. Dropped from all plans. |
| candles | 0 interior gaps, all 12 pairs, 1m/5m/15m/1h |

⚠️ **1m candle history is still ragged.** ETH 1m starts 2022-08-25 (2.09M bars); the other
7 start 2023-11-13 (1.45M) — so the first ~15 months of any 1m train window contain **ETH
only**. This is what moved the split and broke E2b comparability. F4 used 15m bars, where
the problem is smaller but not gone. Fix = F8/C5.

**60-day book milestone for BTC/ETH/SOL: ≈2026-09-15.**

---

## §2 — THE RUN QUEUE

All three runs below are launchable **now** — C0/C1/C2/C4a landed 2026-08-18 (§6). They use
three separate throwaway VMs, so run them concurrently.

⚠️ **These are the first runs on the new eval reporting.** Two outputs are new and are the
ones to read first: the **`Fixed-coverage P&L`** table (gross bps/trade + net at both cost
models, on the same slices as the edge table) and a possible **`WARNING: at the SERVED gate
0.58 this checkpoint gates ZERO bars`**. The latter is not a bug — it means the checkpoint's
confidence never reaches the served threshold, i.e. promoting it would trade nothing. It was
invisible before because the eval default gate sat below the `conf ≥ 0.5` floor.

### N1 — Corrected book ablation walk-forward (CPU, ~4–6h)

**Question:** does microstructure carry any edge — asked in a way F3 could actually answer?

Pass the pair set explicitly, because `WF_LONG_PAIRS_ONLY` is dead code (§1.3.1):

```sh
TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT \
WF_DROPOUT=0.4 WF_WEIGHT_DECAY=1e-3 WF_HIDDEN=48 \
  ./scripts/gcp_walkforward.sh
./scripts/gcp_walkforward.sh --status
./scripts/gcp_walkforward.sh --fetch          # → save to logs/N1.log
```

**Verify first:** the compare header must read
`pairs=--pairs BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT`. If it lists 8 pairs, the run is F3
again — kill it.

**Verdict rule (revised — the n_dir floor is now part of it):**
- A fold is **decidable** only if BOTH arms have `n_dir ≥ 500`. Report undecidable folds
  as undecidable; do not average them in.
- Among decidable folds: book-ON − book-OFF LB gap > +0.05 on **all** of them → book edge
  is real → microstructure becomes the priority (N4 / C6).
- Any decidable fold with gap ≤ 0 or overlapping LBs → stop investing in book features,
  keep collecting, re-check at 60d (≈2026-09-15).
- **If fewer than 3 folds are decidable, the run is inconclusive** — that is a real
  possible outcome, and it means the answer needs C4 (harness fix) plus more book history,
  not another launch of the same command.

### N2 — GBT at 4h: is the architecture question reopened? (CPU, ~2–3h)

**Question:** E4-GBT showed a 114-column static summary tying a 128-step LSTM at 30m — but
that LSTM was handicapped by the normalization bug. Now that the LSTM is fixed and we've
moved to 4h, does temporal modeling finally beat trees? This is the honest re-test of "is
architecture the bottleneck", and it is cheap.

✅ **C0 landed** — `gcp_gbt.sh` now forwards `CANDLE_INTERVAL` (it previously did not, so
`CANDLE_INTERVAL=15m` on the launcher silently trained on 1m bars). Nothing to do first.

```sh
CANDLE_INTERVAL=15m \
GBT_HORIZONS=60,240,1440 GBT_PRIMARY=240 \
GBT_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_gbt.sh
./scripts/gcp_gbt.sh --status
./scripts/gcp_gbt.sh --fetch                  # → save log to logs/N2.log
```

**Verify:** `=== resolved knobs: HORIZONS_MINUTES=60,240,1440 PRIMARY_HORIZON=240 …` and
that the P&L line says `hold=16 bars` (not 240).

**Verdict:**
- GBT cov05 LB ≈ F4's 0.531 (within ~0.01) → architecture is confirmed dead. Close the
  question permanently; all remaining headroom is in features, labels and cost.
- GBT clearly **worse** → the fixed LSTM's temporal modeling is now contributing →
  architecture work (temporal CNN / small transformer, `MODEL.md` §4.4) is back on the
  table as a real lever.
- GBT clearly **better** → we are still leaving signal on the table with the LSTM; switch
  the production path to trees for the candle track.

### N3 — Cost-aware selection at 4h (GPU, ~3–5h)

**Question:** F4's core failure is "dir_acc > 0.5 but gross ≈ 0" — the model is right on
small moves (§1.5). Selection currently maximizes Wilson-LB of hit-rate, which is exactly
the wrong objective. The machinery to select on net-return-per-trade already exists
(`train_m2.checkpoint_score`, `SEL_NET_WEIGHT`) and has **never been used at a horizon
where cost is amortizable** — it was tried once at 30m (R5), where nothing could clear cost
so the term had nothing to rank.

One variable vs F4: the selection objective.

```sh
CANDLE_INTERVAL=15m PAIR_EMBED_DIM=8 \
  SEL_NET_WEIGHT=0.5 SEL_COST_BPS=5 \
  TRAIN_HORIZONS=60,240,1440 TRAIN_PRIMARY=240 \
  TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT \
  ./scripts/gcp_train.sh --gpu 60 128
./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> --save         # → logs/N3.log
```

`SEL_COST_BPS=5` (maker) not 14 (taker) on purpose: at 14bps every epoch is equally
unprofitable and the term degenerates to a constant, which is what made R5 useless.

**Verify:** per-epoch lines must show `net/trade=…bps net_sc=…` and `net_sc` must **move
between epochs** — if it is pinned at one value, the term is dead again and the run is
void (the R1 failure mode).

**Verdict:** compare `gross bps/trade` at matched coverage against F4's table in §1.2, not
dir_acc. Selection working = the chosen epoch has higher gross/trade than F4's even if its
LB is lower. That is the point.

### After the first wave

Read N1+N2+N3 together in a **fresh session**. They answer three independent questions
(is there book edge / is there architecture headroom / can selection find the profitable
epoch). The second wave depends on the answers:

- **N4 — L2 ladder feature audit (read-only, NO training, do this regardless of N1).**
  `orderbook_levels` now has ~13d × 100 levels × 8 pairs with zero integrity errors, and
  the 5 current book features are all *instantaneous snapshot levels* with no dynamics.
  Two known gaps, both fixable from data already on disk: (a) no order-flow imbalance
  (OFI), no book delta over the last N snapshots, no queue-depletion rate, no depth slope,
  no microprice drift — and at 30m+ horizons microstructure predictive power comes mostly
  from OFI and its persistence, not from a snapshot's static imbalance; (b)
  `_align_with_age` keeps only the *last* snapshot per bar and throws away ~5 of every 6,
  so per-bar aggregates (mean/std/range of imbalance within the bar, summed OFI, max
  spread) are free information. Run `audit_microstructure.py` on the candidates before
  spending a `FEATURE_DIM` bump. **This is what should drive the next ablation, not the
  current five features** — re-ablating a weak feature set is the least informative
  version of the test.
- **N5 — cross-pair / regime features** (`E5` in the archive; designed, never implemented,
  never run). Trailing 1h/4h/1d returns, longer rolling vol, BTC-beta. Free from candles,
  zero collection lead time. **This is the highest-EV feature lever right now** because it
  attacks F4's actual failure — the 4h edge swinging 0.454→0.623 across regimes — with
  data we already have. Needs `FEATURE_DIM` bump → its own attributable run.
- **N6 — magnitude-weighted directional loss** (code task C3). Train-time twin of N3.
- **N7 — triple-barrier redo.** Blocked on C4b (barrier-aware `simulate_pnl`), wider
  barriers (target ~30–40% flat; at `TB_TP_MULT=1.5` it was 12% at 30m / 5% at 60m, so the
  label degenerated into "which side moved first"), `PAIR_EMBED_DIM=8`, and a pinned
  dataset. Not before the first wave returns.

---

## §3 — WHAT TO BRING BACK (for the next session)

Save each run's full log under `logs/` with the queue name, then open a **fresh session**
and paste the paths. Do not summarize the logs yourself — the numbers that matter are
often not the headline ones.

```sh
./scripts/gcp_walkforward.sh --fetch  > logs/N1.log
./scripts/gcp_gbt.sh --log            > logs/N2.log
./scripts/gcp_logs.sh <run_id> --save          # writes logs/<run_id>.log → rename N3.log
```

**Self-check before you hand them over** — if any of these fails, the run is void and
should be relaunched rather than analyzed:

```sh
grep -nE 'resolved knobs|knob |Pair embedding|Training pairs|primary=|Split global_time' logs/N3.log
grep -nE 'WARNING \[norm\]|max\|z\||BROKEN SCALE' logs/N3.log
grep -n  'P&L sim:' logs/N3.log          # hold must be 4 / 16 / 96 bars at 15m
grep -n  'net_sc=' logs/N3.log | head    # N3 only: must vary between epochs
grep -n  'pairs=' logs/N1.log            # N1 only: must be the 4 long pairs
```

**What the next session will read, in order:**
1. The §0.3 verification lines — is the run valid at all.
2. `Fixed-coverage directional edge` per horizon → cov01/05/10 LB, and whether the
   ordering is monotone in confidence (a broken top tail is a real defect, see F4's 4h).
3. `--- Walk-forward edge on val window ---` win 1–4 → **stability is the verdict metric
   now**, not the headline LB.
4. The gate sweep's `net_ret` + `trades` at each row → gross bps/trade by the §1.5 formula.
5. `Side split` + `Long/short serial P&L` → one-sided?
6. `Book-era split` → is the edge a calendar confound?
7. `Momentum baseline` + `Buy-and-hold` → did it beat the trivial baselines.

---

## §4 — RESULTS LEDGER

Verdict metric has changed twice; the "valid?" column is what matters. **Post-`2e7b272`
runs are a new lineage and are not comparable to anything above the line.**

| Run | What | Primary | cov05 LB | Valid? | Verdict |
|---|---|---:|---:|---|---|
| **F4** `20260817T221811Z` | 15m bars, horizon ladder 1h/4h/24h | 240m | **0.531** | ✅ **current baseline** | Horizon thesis confirmed in shape (gross/trade ×3.5 vs 30m), refuted in level (still ≈0). 4h is the peak. WF unstable: .484/.623/.454/.583. |
| **F3** `wf-20260817T030350Z` | book ON/OFF walk-forward | 30m | — | ⚠️ **undecidable** | Min gap −0.161 → fails the rule, but ran the wrong pair set and every book-OFF arm is below `min_gated=500`. See §1.3. Re-run as N1. |
| — | *norm fix `2e7b272` — lineage boundary* | | | | Everything below is measured through the `std=1e-6` bug unless noted. |
| E4-GBT `gbt-20260816T132201Z` | LightGBM, 114-col static summary | 30m | 0.5314 | ✅ (scale-invariant) | Ties the LSTM's 0.530 on the same data → no architecture headroom *at 30m*. cov01 LB 0.4892 — its most confident calls are its worst. Re-tested at 4h as N2. |
| E3-tb `20260816T023427Z` | triple-barrier labels | 30m | 0.530 | ❌ confounded | Changed 3 variables (label + embed accidentally off + dataset moved). Barriers mis-parameterized (flat only 12%/5%). Redo as N7. |
| E2b `20260813T114311Z` | pair-embed dim=8, 8 pairs | 30m | 0.566 | ❌ **retired** | Was the incumbent; its 0.566 is measured through the bug on a since-changed dataset. Do not compare to it. |
| E3b1 / E3b2 | pair-embed dim 4 / 16 | 30m | 0.559 / 0.554 | ❌ | Dim curve flat within noise. Ranked on a corrupted verdict metric. |
| E2a′ / E2c | pair-set sweeps | 30m | 0.568 / 0.559 | ❌ | "More pairs > fewer" — conclusion probably survives, evidence does not. |
| E1a / E1b | 4h / 1d primary at 1m bars | 240m / 1440m | 0.533 / 0.523 | ❌ | Rejected at the time for book-era collapse — which was the norm cliff, not the horizon. **F4 supersedes and partially reverses this.** |
| R0–R6 | staleness fix, cost-sel, capacity, rebalance | 30m | 0.542–0.559 | ❌ | The whole "tuning ceiling" narrative. Re-derive if any of it matters. |
| ablate `20260804T083752Z` | book ON/OFF, single dense window | 30m | ON 0.691 / OFF 0.494 | ✅ (`--require-book`) | The strong book result. Did not replicate in walk-forward (2026-08-04 or F3). Treat as unconfirmed. |
| E3a `20260814T144713Z` | 12 pairs | 30m | — | ❌ VOID | Log truncated + embed accidentally off. The 12-pair question is still open and cheap. |

---

## §5 — CLOSED LEVERS (do not re-propose without new evidence)

| Lever | Status | Why |
|---|---|---|
| Encoder capacity / layers / hidden sweeps | **Closed** | R2/R2.1 mode-collapsed; E4-GBT tied a 114-col static summary against a 128-step LSTM. Reopen **only** if N2 says GBT is now clearly worse than the fixed LSTM. |
| Confidence calibration / temperature / focal loss | **Closed, new reason** | Old reason ("the head is calibrated to zero signal") was measured through a saturated network. F4's head has real spread — but its calibration table shows it **over**-stated: `[0.60,0.70)` bin mean_pred 0.636 vs empirical 0.547. Sharpening an over-confident head is the wrong direction. The actual fix is the gate (C1). |
| Raising `GATE_THRESHOLD` as an experiment | **Superseded by C1+C2** | The archive's "no cost-viable gate exists" was read off a sweep whose bottom four rows couldn't fire, on data behind the norm bug. The served gate is already 0.58. Re-derive the right operating point from C2's fixed-coverage P&L table, not from another sweep. |
| Quantile head | **Deferred** | Run B regressed direction ~0.014 and its band coverage was unstable. `MODEL.md` wants it as an RL risk input; revisit at M3, detached, not before. |
| `liquidations` feed | **Dropped** | 0 rows; Binance gates WS market data from datacenter egress (verified from 3 hosts). Not on the critical path — the 2026-08-04 book edge existed without it. Options if ever needed: third-party REST vendor (also gives history), or non-datacenter egress proxy. |
| More candle history | **Closed** | Adds more of the pre-book regime we already fit. The model early-stops; it is not data-starved in that direction. |
| Full architecture swap (transformer / TCN) | **Gated behind N2** | No evidence LSTM capacity is the bottleneck. N2 is the cheap test that would reopen it. |
| 12-pair training (E3a) | **Open, low priority** | Never cleanly run. The 4 extras are backfilled. One variable, one cheap run — worth doing eventually, not now. |

---

## §6 — OPEN CODE TASKS

**C0, C1, C2 and C4a are DONE (2026-08-18, uncommitted).** They are reporting/harness
only — no trained numerics change, no serving change — so the first wave can launch
against them immediately. C3/C4b/C5/C6 are deliberately NOT in that batch: each alters
trained numerics or feature semantics and so needs its own attributable change (§0.2).

- ✅ **C0 — DONE. Forward `CANDLE_INTERVAL` in `scripts/gcp_gbt.sh`.** New `GBT_CANDLE_INTERVAL`
  (defaults to `${CANDLE_INTERVAL:-1m}`), exported into the remote prelude, passed as `-e` to
  the container, and echoed in both `resolved knobs` and the summary header.
- ✅ **C1 — DONE. Eval gate sweep (reporting defect, not a production one).** Three parts,
  none of which change serving:
  1. `scripts/gcp_train.sh:722,727` — sweep `0.50,0.55,0.60,0.65,0.70,0.75` instead of
     `0.35,0.4,0.45,0.5,0.55,0.6`. Four of the current six rows are below the `conf ≥ 0.5`
     floor and duplicate each other.
  2. `config.py` — `GATE_THRESHOLD` / `CONFIDENCE_THRESHOLD` default `0.40` → **`0.58`**, to
     match the deployed `ML_GATE_THRESHOLD` in `docker-compose.yml:14,65`. Then the `*`
     marker and the "serve default" label finally point at the row we actually trade. This
     is trap §0.4.2 (default ≠ incumbent) in the reporting path.
  3. Add `GATE_THRESHOLD` (and the new maker-cost knobs) to `FLUX_TRAIN_ENV_KEYS` so the
     operating point can be swept from the launcher.
  Also shipped: `gate.gate_sweep`'s default thresholds and `eval_m2 --gate`'s default both
  moved above the floor, and eval now prints a loud **`WARNING: at the SERVED gate 0.58 this
  checkpoint gates ZERO bars`** when the confidence scale never reaches the served threshold
  — a promote-blocking fact that the old sub-floor default made invisible.
  Whether **0.58 is still the right operating point** is a separate question that C2's table
  now answers with numbers — do not change `ML_GATE_THRESHOLD` until you have read one.
- ✅ **C2 — DONE. Net P&L at fixed coverage, at both cost models.** `eval_m2` currently only
  simulates P&L at gate thresholds (`_add_pnl_rows`), so the cost-viable operating point
  cannot be read from the fixed-coverage table where every other verdict metric lives. Add
  `net_ret` / `n_trades` / **gross bps/trade** columns to the `FIXED_COVERAGES` table, and
  print each at taker (14bps) **and** maker (5bps). Retires the whole "re-run eval with
  `FEE_RATE_BPS=…`" class of question permanently.
  Shipped as `eval_m2.fixed_coverage_pnl`: the simulator runs ONCE at cost=0 and every cost
  model is derived as `gross - n_trades x cost`. **Verified exact** against a direct
  `simulate_pnl` run at each cost (identical to 1e-9, identical trade counts). New config
  knobs `MAKER_FEE_RATE_BPS=2` / `MAKER_SLIPPAGE_BPS=0.5`. Also written to `eval_m2.json`
  under `fixed_coverage_pnl`.
- **C3 — magnitude-weighted directional loss.** Weight the aux up/down CE by `|r_T|` so
  being right on a 200bps move counts more than on a 5bps move. Train-time twin of N3;
  directly attacks the §1.5 diagnosis. Gate behind a config flag defaulting to off.
- ✅ **C4a — DONE. Walk-forward compare guard.** Make `compare.txt` refuse to print (or clearly
  flag) an arm's LB when `n_dir < min_gated`. Shipped: a fold is now marked
  `[UNDECIDABLE — n_dir below floor 500 (ON=… OFF=…); EXCLUDED from verdict]`, the min gap is
  computed over decidable folds only, and the footer prints decidable/undecidable counts plus
  the revised rule (fewer than 3 decidable folds ⇒ INCONCLUSIVE). Floor overridable via
  `WF_MIN_DIR`. `WF_LONG_PAIRS_ONLY` is fixed too — it is now unconditional (an explicit
  opt-in flag must beat a defaulted variable) and echoes when it overrides `TRAIN_PAIRS`.
  ⬜ **Still open:** comparing arms at **matched n_dir** rather than matched coverage. The
  guard above prevents a wrong verdict; matched-n_dir would let more folds be decided.
- **C4b — barrier-aware `simulate_pnl`.** Under triple-barrier labels the model predicts a
  TP/SL outcome but `simulate_pnl` books `fwd_ret` at a fixed `hold_bars` — a policy
  mismatch, so the reported P&L is not the P&L of the strategy being labeled. Walk forward
  to first TP/SL touch, else timeout. **Blocks N7.**
- **C5 — `oi` conditioning.** `oi = log1p(open_interest)` is a *level*: near-constant within
  any short window, so its per-pair std is tiny and ordinary drift becomes hundreds of
  sigma (`max|z|` 526 BTC / 863 DOGE in the `--require-book` window — a legitimate heavy
  tail that `NORM_CLIP` is now winsorizing). Drop the raw level and keep `oi_chg`, or
  replace with a rolling-normalized/differenced version. Same question applies to
  `log_vol`. Cheap; likely free accuracy in any dense-book arm.
- **C6 — 1m backfill to a common start.** Backfill 1m to 2022-08-25 for all 8 pairs (Binance
  has it — the 5m series proves it) or trim ETH to the common start. Pin the split before
  the next baseline. Also: `torch==2.5.1+cpu` no longer resolves on the PyTorch CPU index,
  so `ml_trainer` fails a clean rebuild; `gcp_gbt.sh` works around it in the throwaway VM
  only. Fixing the pin properly changes served numerics → its own decision.

---

## §7 — MECHANICS

### Launch / monitor / fetch

| Job | Launch | Status | Fetch | VM |
|---|---|---|---|---|
| Train (GPU) | `./scripts/gcp_train.sh --gpu 60 128` | `./scripts/gcp_status.sh` | `./scripts/gcp_logs.sh <run_id> --save` | `fluxtrader-train` |
| Walk-forward | `./scripts/gcp_walkforward.sh` | `--status` | `--fetch` | `fluxtrader-walkforward` |
| GBT diagnostic | `./scripts/gcp_gbt.sh` | `--status` | `--fetch` / `--log` | `fluxtrader-gbt` |
| Single-window ablate | `./scripts/gcp_ablate.sh` | — | — | own VM |
| Feature audit | `./scripts/gcp_audit.sh` | — | — | own VM |
| Data stats | `./scripts/gcp_data_collection_stats.sh` | — | — | always-on |
| Promote | `./scripts/gcp_promote.sh --local-copy` | — | — | always-on |

Each of these creates its own throwaway VM with its own tmux session and status marker, so
**they are safe to run concurrently**. They all self-DELETE on success and self-STOP on
failure. `KEEP_VM=1` keeps the VM for debugging. Never run a training-sized job on the
always-on VM — it has 2GB and the kernel OOM-kills it silently.

⚠️ `gcp_promote.sh` only ever promotes `checkpoints/latest.pt`, and every new run
overwrites that key. **Promote before launching the next run**, or the checkpoint you
wanted becomes unreachable via the script.

### Env knob passthrough

`scripts/gcp_train.sh` forwards only the allowlist in `FLUX_TRAIN_ENV_KEYS`. Currently:

```
SEL_NET_WEIGHT SEL_COST_BPS SEL_NET_SCALE SEL_COVERAGE
NUM_LAYERS HIDDEN_SIZE DROPOUT LR WEIGHT_DECAY BATCH_SIZE
PAIR_EMBED_DIM NUM_WORKERS PREFETCH_FACTOR
CLS_WEIGHT_MODE CLS_WEIGHT_CLIP CLS_LABEL_SMOOTHING DIR_LOSS_WEIGHT
LABEL_MODE TB_TP_MULT TB_SL_MULT TB_VOL_WINDOW TB_MIN_BARRIER
CANDLE_INTERVAL NORM_DEGENERATE_STD NORM_CLIP NORM_LEGACY_BROKEN_STD
BOOK_MAX_AGE_MIN TRADES_MAX_AGE_MIN FUNDING_OI_MAX_AGE_MIN
FEE_RATE_BPS SLIPPAGE_BPS
```

**Add every new config knob to this list when you create it** — an unforwarded knob is a
silent no-op on the GPU VM, which is trap §0.4.2. Note `TRAIN_PRIMARY` / `TRAIN_HORIZONS` /
`TRAIN_PAIRS` are consumed on the *launcher* and forwarded as CLI flags instead.
`gcp_gbt.sh` and `gcp_walkforward.sh` have their own, narrower forwarding — check before
assuming a knob reaches them (this is exactly what C0 fixes).

### Where things live

- Checkpoints: `gs://fluxtrader-train-artifacts/checkpoints/` (+ `latest.pt`)
- Logs: `gs://fluxtrader-train-artifacts/logs/<RUN_ID>.log`
- Walk-forward compares: `…/walkforward/<run_id>.compare.txt`
- GBT reports: `…/gbt/<run_id>.json`
- Status markers: `…/status/latest.json`

### Related docs

- `docs/archive/TRAINING_HISTORY.md` — the full session narrative, 2026-07-23 → 2026-08-17.
- `docs/DATA_COLLECTION_AUDIT.md` — what the collector captures vs silently drops.
- `docs/QUANT_AB_HANDOFF.md` — quantile-head A/B and its deferral.
- `MODEL.md` — architecture contract; §4.3 labels, §4.4 architecture options.
- `AGENTS.md` — Docker-only workflow, data-lives-on-the-VM rule.
