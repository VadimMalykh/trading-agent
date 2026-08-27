# M3 Implementation Plan — the trading policy

**Status:** In progress — **M3-0a, M3-1 and M3-2 are complete** (§0.0). A rules baseline clears the pre-registered Tier-1 bar and M3-3 now has a benchmark. Unblocked: R0 promoted 2026-08-26.
**GPU required:** **No — not for any step in this document.** See §0.3.
**Keys required:** No.
**Related:** [M3_PROTOCOL.md](./M3_PROTOCOL.md) (**the pre-registration — read before running any search**) · [M3_2_RESULTS.md](./M3_2_RESULTS.md) (**M3-2's full generated results — all 40 runs**) · [PLAN.md](./PLAN.md) Phase M3 · [NEXT_TRAINING_PLAN.md](./NEXT_TRAINING_PLAN.md) §1.3/§1.5/§1.8 (the evidence M3 consumes) · [SIMULATION.md](./SIMULATION.md) (the live paper-sim stack) · [BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) (the parallel B-wave — shares M3-0b's side-table, and its B2 may hand M3 a new regime observable)

*Written 2026-08-24, at the moment M2 froze. This document is the plan for the whole
milestone; it holds only what is currently true and actionable. When a step's conclusions
are superseded, move the narrative to `docs/archive/TRAINING_HISTORY.md` and carry the
surviving conclusion forward — do not append a contradicting section.*

---

## §0.0 — STATUS: RESUME HERE

*This block is the session-to-session handoff. It holds only what is true **now**: what is
done, what the next command is, and what to bring back. When a step closes, its narrative
moves down into the step's own section or into `docs/archive/TRAINING_HISTORY.md` — it is
never left here contradicting a later result.*

**Last updated: 2026-08-27 (M3-2 complete).**

### Where the work stands

| step | state |
|---|---|
| **R0** (the blocker) | ✅ promoted 2026-08-26 — seed 2 served at gate 0.6311 |
| **M3-0a** — regime harness + policy backtester | ✅ **built, and both acceptance tests pass** |
| **M3-0b** — price/funding side-table | ⬜ not started, and not needed until barrier exits are wanted |
| **M3-1** — pre-registered protocol | ✅ **committed 2026-08-27 as [M3_PROTOCOL.md](./M3_PROTOCOL.md)**, before any search ran |
| **M3-2** — rules baseline | ✅ **run 2026-08-27, all 40 configurations** — [M3_2_RESULTS.md](./M3_2_RESULTS.md). A baseline passes Tier 1 |
| **M3-3** — learned policy | ⬜ **this is the next step** — it now has a benchmark to beat |

### How to run anything in M3

🔴 **Everything runs in Docker — nothing is installed on the host, including for
"just a pandas script".** M3 uses its own torch-free image (`ml/train/Dockerfile.analysis`,
compose service `ml_analysis`, ~200MB, builds in seconds) because it needs no torch, no DB
and no GPU. `scripts/m3.sh` wraps it and builds it on first use:

```sh
./scripts/m3.sh -m m3 validate          # the two acceptance tests — run first, always
./scripts/m3.sh -m m3 power             # the pre-registration facts (M3_PROTOCOL §2/§3/§4)
./scripts/m3.sh -m m3 search            # M3-2: all 40 pre-registered runs, scored (~4 min)
./scripts/m3.sh -m m3 policy --help     # score one policy spec
./scripts/m3.sh --shell                 # interactive
```

`ml/train` is bind-mounted into the container, so host edits take effect with no rebuild.
The four prediction dumps live in `ml/train/output/eval_dumps/` (gitignored, ~125MB); if
they are missing, re-fetch them:

```sh
mkdir -p ml/train/output/eval_dumps
for RUN in 20260818T185438Z 20260819T142759Z 20260820T025723Z 20260822T012619Z; do
  gcloud storage cp "gs://fluxtrader-train-artifacts/eval/$RUN/eval_preds.parquet" \
    "ml/train/output/eval_dumps/eval_preds_$RUN.parquet"
done
```

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

**The protocol is committed as [M3_PROTOCOL.md](./M3_PROTOCOL.md), before any search ran.**
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

**Full results: [M3_2_RESULTS.md](./M3_2_RESULTS.md) — all 40 pre-registered runs, both fee
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

### The next step, exactly

**M3-3 — the learned policy.** Its bar is now set and is not negotiable (M3_PROTOCOL §4.4):
pass all six Tier-1 criteria **and** beat **+0.25 bps worst-window net at taker**, which is
`cov0.02_hold240_rqnone_mcnone_SIZED`. Re-run `m3 validate` first — a learned policy compared
against a baseline computed by a changed harness is not a comparison. §2's M3-3 section holds
the observation vector; give it `btc_absret_1d` as a **continuous** observation, not a
threshold to rediscover, because §D1 is the evidence that the continuous form is the better
one.

**The parallel item, and it is worth more than any further knob: the maker-fee study
(§3.3).** Every candidate in M3-2 roughly doubles at 5 bps — the winner is +27.1 at maker
against +15.0 at taker. Whether 5-bps fills are actually obtainable for these pairs and sizes
is an untested assumption underwriting half the published economics, it is ranked risk #2,
and it is cheap to measure on the paper-sim stack. If maker fills are real, the decision
problem changes shape; if they are not, several M3-2 rows stop being interesting.

---

## §0 — READ THIS FIRST (plain language, no §0-of-the-training-plan required)

### 0.1 What M3 is

M2 produced a **signal**: for any bar, for any of three horizons, a probability that price
goes up, down, or stays flat. It does not decide anything. M3 is the part that **decides** —
whether to be in the market at all, on which side, how large, and when to get out.

The action space (from PLAN.md) is `flat` / `long` / `short` / `hold` / `exit`, with size
buckets later. The reward is PnL net of fees, funding, and penalties for drawdown and
overtrading.

### 0.2 Why M3 is where the money is

Every change we ever made to the *model* moved the edge by a few percent or not at all. One
observation about **when to trade** moved it by 4×:

| | top 5% of bars | top 2% of bars |
|---|---:|---:|
| all bars | +8.9 gross bps/trade | +22.0 |
| **only when BTC has moved >4.31% in the last 24h** | **+35.5** | **+54.9** |

Net of a 14bps taker round trip, that is the difference between **−5.2 bps (a losing
strategy)** and **+21.5 bps (a working one)** at 5% coverage. Three independently seeded
models agree closely (+34.8 / +32.5 / +38.7). This is the largest measured effect in the
project, and it is a statement about market state, not about the model — which is exactly
why it belongs here and not in M2 (NEXT_TRAINING_PLAN §1.8).

**M3's job is to turn that observation into a policy that survives contact with fees,
funding, position limits, and the fact that the effect is not uniform in time.**

### 0.3 The thing to internalise: M3 is a laptop project

All of this project's infrastructure is training-shaped — self-deleting GPU VMs, a status
bucket, log-fetching scripts. **None of it is on M3's critical path.**

Every eval run already dumps per-bar decision records to
`gs://fluxtrader-train-artifacts/eval/<run_id>/eval_preds.parquet`, and
`ml/train/reaggregate_preds.py` already reproduces `eval_m2.py`'s published numbers from
those dumps using nothing but `pandas`, `pyarrow` and `numpy` — no torch, no DB, no VM. Q1
found the 4× effect entirely that way.

A policy search is a search over *decisions made on already-computed predictions*. It needs
no model training. Budget zero GPU hours for §2 M3-0 through M3-2, and do not spin up a
train VM to do arithmetic.

### 0.4 The one-paragraph plan

Build the backtester before the policy; pre-register how it will be scored before searching
anything; ship an explicit rules baseline before anything learned; and only then ask whether
a learned policy beats it. The risk that ends M3 badly is not "the policy is not clever
enough" — it is **overfitting a five-knob policy to 3,700 trades and believing the number**.

---

## §1 — WHAT M2 HANDS OVER

### 1.1 The served signal

- **Checkpoint:** `m2_multi_20260819T142759Z_a186182b.pt` (seed 2 of the 5m/seq384 family).
- **Served gate:** `conf >= 0.6311`, realizing ~2% coverage, dir_acc 0.578, +18.68 gross
  bps/trade, +4.68 net at 14bps taker.
- **Shape:** 2-layer LSTM, 64 hidden, ~56k params. Reads 384 five-minute bars (32h) for one
  pair. Emits per-horizon 3-class direction for **60 / 240 / 1440 minutes**; the optimised
  and served primary is **240m (4h) = 48 bars**.
- **Live endpoint:** `GET /health`, `GET /predict?symbol=…`, `GET /predict_all` on
  `ml_inference:8001`. `/predict` returns raw per-horizon confidences **alongside** the
  `gated` boolean, so a policy can ignore the serve-side gate without a serve change.

### 1.2 The offline artifacts M3 actually builds on

`eval_preds.parquet`, one row per (bar × horizon), written by `eval_m2.py --dump-preds`:

| column | meaning |
|---|---|
| `ts` | epoch **nanoseconds** UTC — the bar the decision is made **on**, not the exit |
| `pair` | categorical |
| `horizon` | 60 / 240 / 1440 (minutes) |
| `side` | −1 short / +1 long (the same signal the gate and every published P&L uses) |
| `conf` | gate confidence |
| `p_up` | softmax P(up) |
| `fwd_ret` | the return realized by a trade opened at this bar and held the full horizon |
| `y3` | realized class: 0 down / 1 flat / 2 up |
| `has_book` | whether this bar is in the order-book era |

Three seeds are available (`20260818T185438Z`, `20260819T142759Z`, `20260820T025723Z`).
**Use all three.** Pooling them is what turned Q1's finding from "2.5σ on a pooled SEM" into
"three independent models agree", and it is the only cheap source of replication M3 has.

🔴 **What the dump does NOT contain: price.** There is no OHLC path and no funding rate —
only `fwd_ret` at a fixed horizon. This is the single most important structural fact for
§2, because it means **fixed-hold policies can be backtested from the dumps alone, and
barrier/stop policies cannot.** Anything involving a stop-loss, a take-profit, a trailing
exit, or a funding charge needs a price/funding side-table joined on `(pair, ts)`. Plan for
that as a distinct step (M3-0b), not as an afternoon's work inside M3-0a.

### 1.3 The three findings that are *constraints*, not context

Each of these is a rule the policy must obey. They are not suggestions and each was paid
for with a wave of runs.

1. **The signal is only cost-viable in a narrow confidence band.** +19.4 / +22.0 gross
   bps/trade at the top 1% / 2% of bars, +8.9 at 5%, +1.9 at 10%, 0.0 at 20%. **Coverage is
   therefore a first-class decision variable of the policy**, not a threshold to tune away.
   The full table:

   | cov | trades | gross bps | net @5bps maker | net @14bps taker |
   |---|---:|---:|---:|---:|
   | 0.01 | 1081 | +19.38 | +14.38 | +5.38 |
   | 0.02 | 1783 | +22.03 | +17.03 | +8.03 |
   | 0.05 | 3718 | +8.91 | +3.91 | −5.09 |
   | 0.10 | 7104 | +1.89 | −3.11 | −12.11 |
   | 0.20 | 13462 | −0.00 | −5.00 | −14.00 |

2. **Calibration is fragile and over-confident.** In the `[0.60,0.70)` bin the model says
   0.640 / 0.626 and reality is 0.576 / 0.578. Three separate levers (P2, R2, R3a) improved
   or held *ranking* while destroying the probability *scale*. **If the policy consumes
   `p_up` as a probability — for Kelly-style sizing, for an expected-value calculation, for
   anything beyond an ordering — it must re-check brier and the bin table on the specific
   checkpoint it was handed.** Do not assume a model that ranks well is calibrated.

3. **Absolute confidence thresholds do not transfer between checkpoints.** The same
   probability is 1.2% / 2.5% / 1.7% coverage across three seeds of one configuration, 0.8%
   on O3 and 80% on P2. **The policy must condition on coverage rank, never on a raw
   confidence constant.** A policy written against `conf > 0.63` is a policy that silently
   breaks on the next checkpoint.

Two smaller ones worth carrying:

- **The model's own trailing confidence is anti-predictive** (`mean_conf_1d` AUC 0.480 /
  0.471 / 0.499). A confident recent stretch is not a good stretch. Do not build a
  "the model is hot right now" term.
- **Side balance is not seed-stable** — seed 3's short side is a coin flip (0.502 vs 0.563
  long) while seeds 1 and 2 are balanced. Check long/short separately on whatever checkpoint
  is served; do not assume symmetry.

### 1.4 ✅ The Q1 harness was never committed — so M3-0a rebuilt it, and it is committed now

For the whole of M2, `btc_absret_1d` existed **only in `docs/`**: the script that computed
the regime observables and produced §1.8's numbers was never in the repository. That was
this milestone's risk #6, because every policy in M3 is built on top of it.

It is now `ml/train/m3/regime.py`, and it is pinned by an acceptance test rather than by
trust: `ml/train/m3/validate.py` reproduces §1.8's published quintile ladder and the 4.31%
threshold from the dumps alone (see §0.0 for the numbers). The construction is the one §1.8
describes — `fwd_ret` at horizon *h*, shifted back *h* minutes, is a lookahead-free trailing
return, and the horizons compound to 6.34e-09, so no DB round-trip is needed.

⚠️ **Only `btc_absret_1d` is pinned.** `regime.py` also rebuilds `btc_ret_1d`, `btc_ret_7d`,
`btc_sign_1d`, `rv_1d/7d/30d`, `xs_disp_4h` and `mean_conf_1d` so the AUC table can be
re-derived as a cross-check, but their definitions are reconstructions and no test holds
them in place. **`xs_corr_1d` and `xs_corr_7d` are not rebuilt at all.** Do not condition a
policy on any of them without first reproducing §1.8's AUC column for it. §1.8's own reading
is that none of them is worth conditioning on anyway — they were U-shaped, seed-unstable or
flat — so this is a gap in the cross-check, not in the policy's toolkit.

---

## §2 — THE SEQUENCE

Strictly ordered. Each step's output is the next step's input, and the ordering is the
protection against the failure mode in §0.4.

### M3-0a — ✅ DONE (2026-08-26). The harness exists and is validated.

**What was built,** all of it in the torch-free `ml_analysis` container (§0.0 says how to
run it):

| file | what it is |
|---|---|
| `ml/train/m3/dumps.py` | loading and **pooling** the per-seed dumps; the calendar windows; the BASE8 universe |
| `ml/train/m3/regime.py` | the rebuilt Q1 observables (§1.4) and the compounding check |
| `ml/train/m3/backtest.py` | the event-driven simulator — `PolicySpec` is the full list of the policy's degrees of freedom |
| `ml/train/m3/metrics.py` | P&L at both fee levels, drawdown, daily Sharpe, per-window and long/short splits |
| `ml/train/m3/validate.py` | **the two acceptance tests.** Run before believing any number |
| `ml/train/m3/cli.py` | `python -m m3 validate` / `python -m m3 policy` |
| `ml/train/Dockerfile.analysis`, `scripts/m3.sh` | the container everything runs in |

**Every degree of freedom §M3-0a called for is supported**: entry by coverage rank (never by
a confidence constant), serial positions per (seed, pair), time-based exits, both fee levels
side by side, a portfolio-wide concurrency cap, regime conditioning with the threshold
derived as a quantile of *bars*, and regime-scaled sizing.

**Three constraints the implementation makes explicit**, each of which a future session
should not have to rediscover:

1. 🔴 **Exits can only land on 60 / 240 / 1440 minutes**, because those are the horizons the
   dump carries `fwd_ret` for. `--hold-horizon` selects among them (a 4h signal held 1h is a
   legitimate policy). Any other hold length — and every stop, take-profit or trailing exit —
   needs M3-0b's price table. The simulator refuses rather than approximating, because a
   barrier policy scored against a fixed-horizon return is exactly the C4b mismatch.
2. **Pooling is concatenation keyed on the seed, never a merge.** Two seeds gating the same
   bar are two observations, and one seed's open position must not block another's entry.
3. **Coverage selection is tie-inclusive** — every bar at or above the k-th largest
   confidence — so the slice is deterministic and re-derivable instead of depending on
   `torch.topk`'s kernel-level tie order (§0.0, point 4).

**Acceptance test result: both pass.** 15/15 fixed-coverage cells to the digit, the pooled
§1.3 table exactly, and §1.8's regime ladder within ≈1bps. Numbers are in §0.0.

**Still open inside M3-0a's scope, and deliberately deferred:** `xs_corr_1d` / `xs_corr_7d`
are not rebuilt (§1.4), and O8's 12-pair dump is downloaded but not yet folded into a pooled
search population (§5) — that decision belongs with M3-1's protocol, since it changes the
sample the search runs on.

### M3-0b — The price/funding side-table (only when barrier exits are actually wanted)

Export **once** from the always-on VM to local parquet: 5m candles and `funding_rates` for
the eight served pairs over the validation window. Join on `(pair, ts)`.

This unlocks three things that are impossible in M3-0a:

- **Barrier-aware exits** — walk forward to the first take-profit/stop-loss touch, else time
  out. This is the already-open task **C4b** in NEXT_TRAINING_PLAN §6, filed there as
  "under triple-barrier labels the model predicts a TP/SL outcome but `simulate_pnl` books
  `fwd_ret` at a fixed `hold_bars` — a policy mismatch". M3 is where that mismatch stops
  being theoretical.
- **Funding cost.** `funding_rates` is the one microstructure source with real history
  (2y9mo–3y11mo). At a 4h primary horizon, funding is a real term in the P&L, not a rounding
  error, and it is *signed* — it can pay you.
- **Slippage / fill realism** beyond a flat per-trade constant.

**Do not start here.** A fixed-hold policy that works is worth more than a barrier policy
that cannot be validated, and M3-0a's acceptance test is only expressible in fixed-hold terms.

**When you do build it, add the book columns in the same pass.** `docs/BOOK_ERA_PLAN.md` B0
needs exactly this export plus the 11 microstructure scalars over the book era, joined on the
same `(pair, ts)` grid with the same staleness caps. Building it once serves both wavefronts;
building it twice risks two different alignments and neither being evidence about the other.

### M3-1 — ✅ DONE (2026-08-27). The protocol is pre-registered.

**It is [M3_PROTOCOL.md](./M3_PROTOCOL.md), committed before any search ran.** §0.0 carries
what writing it established. The rest of this section is kept as the *rationale* for why the
step existed — the binding document is the protocol, and it is not edited once a search has
begun.

Write down, **and commit, before running a single search**: the split, the metric, the
decision rule, and the number of configurations that will be tried.

Why this is a step and not a paragraph:

- A policy has far more knobs than the model did — entry rank, hold length, exit rule,
  sizing curve, regime condition, per-pair and portfolio caps. The model waves could get
  away with "one change per run" because each run cost 3 GPU-hours. A policy search costs
  seconds per configuration, so the only thing standing between you and an overfit is a
  written-down protocol.
- The sample is small: **3,717 pooled cov05 trades across three seeds, per-trade sd 259bps.**
  A quintile's standard error is ≈9.5bps. Many plausible policies will differ by less than
  that.
- 🔴 **§1.8's caveat is a live warning, not a footnote.** `btc_absret_1d`'s ladder holds in
  three of four calendar windows and **fails in window 2 (Q5 = −10 bps), which is where 47%
  of its trades live.** A pooled number will tell you the rule is worth +35 bps. It is worth
  +35 bps in three windows and −10 in the one it fires hardest in. **Score walk-forward
  across calendar windows and report the worst window, not the mean.**
- Also pre-register the trivial baselines the policy must beat: buy-and-hold (≈−35 over the
  val window), trailing-48-bar momentum (dir_acc 0.469 — mildly *anti*-predictive), and
  M2's own ungated fixed-coverage table from §1.3.

### M3-2 — The rules baseline. Ship this before anything learned.

Under five parameters, all of them interpretable:

1. Enter only when confidence is in the **top-k% by coverage rank** (k the first parameter).
2. Only when the **regime observable is in its top quintile** (the threshold, ~4.31% BTC
   trailing-24h |return|, is the second — and it must be re-derived per split, not hard-coded).
3. **Size** flat, or scaled by regime quintile (third).
4. **Hold** to the 4h primary (48 bars), with an optional stop (fourth/fifth).

Two reasons this comes first rather than after a learned policy:

- Given a 4× effect that is already visible in a quintile table, a rules baseline may capture
  most of the value that exists. It would be an expensive way to find that out afterwards.
- Without it, a learned policy has no honest benchmark. You would have no way to distinguish
  "the policy learned something" from "the policy rediscovered the rule, and I fitted a
  neural network to do a comparison".

**Note the direction-free property:** Q1's Q5 effect is +36.9 on BTC-up days and +35.2 on
BTC-down days. The regime term is about the **magnitude** of the market move, not its sign.
A baseline that accidentally makes it directional is a bug.

**Outcome (2026-08-27): done, and the result is in [M3_2_RESULTS.md](./M3_2_RESULTS.md).**
Parameters 1 and 3 carried the milestone; parameter 2 — the hard top-quintile filter — did
not. Of the 36 pre-registered grid configurations exactly one clears Tier 1 and it uses
coverage alone; the twelve that apply the regime as an on/off filter all fail, two of them on
a single criterion each (an under-sampled window, and one seed going negative). The §3.2
sizing variant, which applies the same observable as a **size multiplier** rather than a
filter, also clears Tier 1 and outranks it. §0.0 carries the plain-language summary.

The direction-free property held: nothing in the winning configuration conditions on the sign
of the BTC move, and the momentum-side control (§3.2) confirms the *direction* comes from the
model — its side is worth +36.9 bps/trade over `sign(trailing 240m)` on the same entry bars.

### M3-3 — A learned policy, only if it beats M3-2

PLAN.md already locks the family: **offline / bandit-style on logged rollouts, not
end-to-end price RL.** Keep it there.

**Observation vector** (from NEXT_TRAINING_PLAN §2):

- M2's per-horizon probabilities and confidences — as **coverage rank**, per §1.3.3;
- trailing market-move magnitude (BTC |ret| over 24h, or the pooled-universe equivalent);
- position state: side, age, unrealized PnL;
- optionally realized-vol context (see §3.4).

Promote it over M3-2 only on the pre-registered rule from M3-1, judged on the **worst**
calendar window.

---

## §3 — DESIGN DECISIONS TO SETTLE BEFORE WRITING CODE

### 3.1 Where the gate lives — decide this first, it is architectural

Today `serve.py` gates and the Elixir app gates again, both off `ML_GATE_THRESHOLD`. If the
policy *also* gates, there are three gates in series and **the policy only ever sees bars M2
already approved** — it can never choose to widen coverage, which §1.3.1 makes a first-class
decision variable.

`/predict` already returns raw confidences next to `gated`, so the app can ignore the serve
gate with no serve-side change. **Recommendation: the policy owns coverage; `serve.py`'s
gate becomes a reported diagnostic, not a filter.** Make this an explicit decision rather
than something that happens by accident.

### 3.2 The objective — net bps/trade is not the exit criterion

PLAN.md's exit criterion is "controlled max DD and non-pathological trade rate", which is a
*different* objective from the bps/trade every M2 table reports. With ~5% of bars in-regime
the trade rate collapses and the equity curve gets lumpy: a policy can win on bps/trade and
still be untradeable. Decide up front whether M3 optimises net PnL, drawdown-adjusted PnL,
or PnL subject to a drawdown constraint — and score every candidate on all three.

### 3.3 🔴 The fee assumption may dominate every modelling decision

At taker (14bps) the whole cov05 slice is **−5.09** net and only the top 1–2% clears. At
maker (5bps) it is **+3.91**. In-regime at cov05 it is **+21.5** at taker. So the regime
condition is what makes taker viable — and conversely, *whether maker fills are actually
obtainable at 5bps for these pairs and sizes* is currently an **untested assumption that
silently underwrites half the published economics.**

**Measure it early.** A short live study on the paper-sim stack — quoted vs filled, queue
position, adverse selection on the fills you do get — is cheap and could reorder the entire
milestone. Do not let it stay an assumption until after a policy is built on it.

### 3.4 Sizing needs a distribution — and there is a deferred branch waiting here

`docs/QUANT_AB_HANDOFF.md` closed the quantile head with an explicit **"defer, don't
discard"**: what it disproved is that a quantile head *sharing the directional trunk* pays
for itself (it steals encoder capacity and dents direction even at weight 0.2). It did not
disprove that quantiles are informative — the head calibrated fine.

Its stated condition for revisiting was "a healthy direction signal to size". That condition
is now **met** (§1.3 is banked, and the book-era collapse that handoff worried about was
later traced to the 2026-08-17 normalization bug plus a window far too short to read).

So M3 is precisely where that branch fires — but take it in the handoff's own order,
cheapest first:

1. **An analytic vol proxy** (realized vol / ATR-style bands) as the day-one risk context.
   The handoff's own advice: the policy may not need a *learned* distribution at all.
2. A **detached** quantile head (stop-gradient into the shared encoder) — the direct test of
   the capacity-theft failure mode — only if the analytic proxy is the binding limit.
3. A **standalone risk model** only if 2 justifies the infrastructure.

⚠️ `QUANT_AB_HANDOFF.md` is otherwise **stale** in its premises (its "Task 1 / book-era
collapse" framing was superseded). Read it for the quantile decision and its rationale only.

---

## §4 — RISKS, RANKED

| # | risk | why it is ranked here | mitigation |
|---|---|---|---|
| 1 | **Overfitting the policy to 3,717 trades** | seconds per configuration, ≈9.5bps quintile SEM, and five interacting knobs | M3-1's pre-registered protocol, scored on the **worst** window |
| 2 | **The maker-fee assumption is untested** (§3.3) | it is the difference between +3.91 and −5.09 at cov05 — it can invert conclusions | measure fills on the paper-sim stack early |
| 3 | **The regime rule is not uniform in time** | fails in window 2, where 47% of its trades live (§1.8) | never report pooled; require it to survive walk-forward |
| 4 | **Sample size is the binding constraint** | ~3,700 cov05 trades is thin for a policy search | see §5 — the 12-pair dump is free power |
| 5 | **Calibration drift on a future checkpoint** | policy consumes `p_up`; three levers have already broken the scale | rank-based conditioning (§1.3.3); re-check brier on any new checkpoint |
| ~~6~~ | ~~**The Q1 harness is unrecoverable / mis-rebuilt**~~ | ✅ **closed 2026-08-26** — rebuilt as `ml/train/m3/regime.py` and pinned by an acceptance test that reproduces §1.8's ladder (§1.4, §0.0) | — |

---

## §5 — SAMPLE SIZE: THE 12-PAIR DUMP IS FREE POWER

NEXT_TRAINING_PLAN §2 files the 12-pair adoption as an optional deployment change that
"buys coverage, not edge". **That valuation was made for M2. It is worth more to M3**, where
risk #4 says sample size is the binding constraint: four more instruments is roughly 50% more
trades to search a policy on, at unchanged measured edge.

Crucially this costs **nothing**, and that is not a hope — it is already demonstrated.
O8 ran the 12-pair configuration and its dump exists: `reaggregate_preds.py` was validated
*against it*, reproducing O8's fixed-coverage table to the digit (+24.76 / +23.63 / +6.85,
NEXT_TRAINING_PLAN §7). So the extra trades are in the bucket today and the harness that
reads them already works.

**Pull O8's dump in M3-0a alongside the three baseline seeds.** Retraining is not required
to get more trades to *search* on; the ~8h of GPU that a proper 3-seed 12-pair adoption
costs buys the ability to *serve* twelve pairs, which is a separate decision belonging to
NEXT_TRAINING_PLAN §2.

---

## §6 — EXIT CRITERIA

From PLAN.md, sharpened with what M2 measured:

- [x] The backtester reproduces §1.3's fixed-coverage table to the digit under a trivial
      fixed-hold policy (M3-0a acceptance test) — **done 2026-08-26, 15/15 cells** (§0.0).
- [x] The rebuilt regime harness reproduces §1.8's published quintile ladder (§1.4) —
      **done 2026-08-26** (§0.0).
- [x] The evaluation protocol is pre-registered and committed before any search ran (M3-1) —
      **done 2026-08-27**, [M3_PROTOCOL.md](./M3_PROTOCOL.md).
- [x] A rules baseline (M3-2) clears the pre-registered Tier-1 bar — in particular
      **worst-window net at taker ≥ −5 bps**, not just a positive pooled number
      (M3_PROTOCOL §4.2) — **done 2026-08-27**, [M3_2_RESULTS.md](./M3_2_RESULTS.md).
      1 of 36 grid configs passes (`cov0.02_hold240_rqnone_mcnone`, worst window −3.56),
      and so does the §3.2 sizing variant (worst window +0.25), which outranks it.
- [ ] Any learned policy beats that baseline on the pre-registered rule, judged on the worst
      window.
- [x] Max drawdown is controlled and the trade rate is non-pathological (PLAN.md) — the
      M3-2 winner runs 2.34 trades/day/seed at a −4.59 max drawdown; rule P6 makes the trade
      rate a promotion criterion and every table reports the drawdown next to it.
- [x] Long and short sides are reported separately — every table in
      [M3_2_RESULTS.md](./M3_2_RESULTS.md) §G breaks them out (the winner is +18.1 long /
      +2.7 short at taker, i.e. the long side carries it, which is why §3.3 forbids
      selecting on the split).
- [ ] The policy never bypasses the hard `RiskManager` limits.

---

## §7 — WHAT TO BRING BACK (for the next session)

*Results are deliberately analyzed in a fresh session for token hygiene, so a step is not
finished until the artifacts below exist.*

**M3-0a is done** — its artifacts are in the repository and its numbers are in §0.0. Nothing
to fetch. The dumps are already in `ml/train/output/eval_dumps/` and §0.0 carries the
re-fetch command if that directory is ever empty.

Any session that changes the harness must re-run and bring back:

```sh
./scripts/m3.sh -m m3 validate
```

If either test stops passing, **that is the only finding that matters** — stop and fix it
before touching a policy number.

**M3-1 is done** — the artifact is [M3_PROTOCOL.md](./M3_PROTOCOL.md) and every fact it
quotes is reproducible with `./scripts/m3.sh -m m3 power`. Nothing to fetch.

**M3-2 is done** — the artifact is [M3_2_RESULTS.md](./M3_2_RESULTS.md), regenerated in
one command and never hand-edited:

```sh
./scripts/m3.sh -m m3 validate
./scripts/m3.sh -m m3 search
cp ml/train/output/m3/M3_2_RESULTS.md docs/M3_2_RESULTS.md
```

⚠️ The protocol is **still frozen**. M3_PROTOCOL §0 applies to everything downstream: an
observation that a different metric would have been better goes into a *future*
pre-registration, never into a re-scoring of this run. Two such observations are already
logged in M3-2's write-up and must be treated that way — the per-notional normalisation of
the sizing variant (§D1), and the fact that §3.2/§4.2 do not say whether an addition may win
the §4.2 ranking (§A reports both readings rather than choosing one after the fact).

**Finishing M3-3 — bring back** the same table for the learned policy, produced by the same
harness: net bps/trade at both 5bps and 14bps, per calendar window with the worst called out,
per seed, trades/day/seed, max drawdown, daily Sharpe, long/short split, plus the Tier-1
pass/fail row and the clustered 95% CI. Then the one comparison that decides promotion:
**worst-window net at taker against +0.25 bps** (M3_PROTOCOL §4.4). Pooled-only numbers are
not a result.

---

*Updated: 2026-08-27 — M3-0a, M3-1 and M3-2 complete; M3-3 is next and the protocol stays
frozen. §0.0 is the live status block and the only place that needs reading to resume.*
