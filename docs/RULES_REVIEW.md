# Rules review, M3 re-assessment, and the cleanup inventory — 2026-09-04

**Status: ✅ DECIDED AND EXECUTED 2026-09-04.** The review (§0–§3) was delivered, Vadim answered
every question in §4 the same day, and the answers were carried out: [M3_PROTOCOL.md](./M3_PROTOCOL.md)
**§9 (Amendment 2)** is written and in force, the served constants are re-derived, the
checkpoint-binding guard and forward-ledger tagging are built and tested, the walk-forward folds
are plumbed and pre-registered ([WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md)), and the
approved cleanup is done.

**Progress on §6, updated 2026-09-04:** §6.1 (the deploy to `fluxtrader-1`) is **done** — one
correction was needed to the checklist itself: `regime.frozen_p80` is a **top-level** field on
`/api/health`, not a child of `.policy`, so `jq .policy` silently omits it. §6.3 (the document
restructuring) is **done**. §6.2 (the fold queue) has its **harness built and committed** —
`ml/train/m3/walkforward.py`, `M3_ERA=walkforward`, `m3 folds`, and validate's third acceptance
test — but **no fold has been trained**. That is the one thing left. Indexed in
[BACKLOG.md](./BACKLOG.md).

The three questions, verbatim in spirit:

1. Are the rules too tight? Can we be more flexible without losing the protection against
   overfitting?
2. Which documents, logs and scripts are still relevant, and what can go?
3. The candle data was wrong. Why not restart M3 and re-assess it on corrected validation —
   including trying a reinforcement-learning (RL) policy instead of the rule?

---

## §0 — In plain language, and the bottom line

**On the rules.** The bars are right and I would not lower any of them. What makes the rules feel
like a wall is not the bars, it is four things around them: the model-swap rule that was written
to *unblock* iteration is itself not in force because two of its decisions were never taken; the
only data allowed for confirming an idea is "forward time", which today produces nothing; the
promotion criterion ranks on the one statistic the project has since proven it cannot measure; and
there is no written rule for what to do when the *data* turns out to be wrong. All four are
fixable with decisions and one protocol amendment, not by loosening a threshold.

**On M3.** Re-running M3 on corrected data is not a rule violation — it is what the rules require,
and I ran the pre-registered half of it today. **The rule still passes, by 0.4 bps.** The incumbent
policy (top 2% of bars by confidence, hold four hours, size by BTC's daily move) clears all six
Tier-1 criteria on repaired data with a worst window of −4.61 bps against a floor of −5. Its
pooled edge is +13.8 bps a trade after taker fees (was +15.0). The learned policy re-run is in
§2.3. **Nothing about the *models* needs restarting** — every checkpoint's training data ends
2025-12-10, seven months before the defect began; only the last month of the *validation* window
was corrupt, and that month sits in the one calendar window that was never the binding one.

**On RL.** It is not forbidden. It is unfundable on this data, for the same reason the simpler
learned policy lost in August: about 220 independent trading days cannot fit nine linear
coefficients without overfitting, let alone a sequential policy. The single investment that
changes that — for RL, for every parked idea, and for retraining — is **walk-forward folds over
the older history**, which turns ~220 independent days into roughly 800–1,000. That is the
recommendation this document keeps coming back to.

**On cleanup.** The repository is not large in bytes (docs 1.1 MB, local logs 4.6 MB). It is large
in *reading*: 30 documents, 18,000 lines of markdown, four of which each claim to be the place to
start. §3 lists every file with a verdict, and the real win is slimming three documents and
picking one entry point, not deleting bytes.

---

## §1 — Are the rules too tight?

### 1.1 What the rules are, in one table

| rule | where | what it protects against | verdict |
|---|---|---|---|
| Pre-register the grid, metric and decision rule before running; never edit after | M3_PROTOCOL §0 | picking the winner after seeing the results | **keep** — this is the whole defence against overfitting |
| Tier 1: six criteria, selection at taker, rank by worst window | M3_PROTOCOL §4.2 | a rule that only worked in one lucky stretch | keep the criteria; **the ranking axis is wrong for the next protocol** (§1.3 C) |
| Tier 2: clustered lower bound > 0, expected to fail | M3_PROTOCOL §4.3 | mistaking "best available" for "proven" | keep |
| ≥ 3 seeds, family median, never one seed | §8.3 C2, NEXT_TRAINING_PLAN §0.3 | seed luck | keep |
| Day-clustered standard errors, not per-trade | M3_PROTOCOL §2 | a 2.35× overstatement of precision | keep |
| The cut and ladder belong to a checkpoint, re-derived from its own split (C4) | §8.3 | the 2026-08-31 served-vs-scored defect | keep |
| `m3 validate` before any comparison (C3) | §8.3 | comparing across a changed harness | keep |
| One change per training run | NEXT_TRAINING_PLAN §0.2 | un-attributable results | keep |
| M2 frozen; no new M2 run without new *kinds* of data | NEXT_TRAINING_PLAN §5 | re-running eight refuted levers | keep as a **budget** rule (§1.4) |
| Exploratory lane: look at anything, label it, never cite it in a promotion | §8.2 | the bright line | keep — **and use it; nothing has run in it yet** |
| Champion–challenger C1–C5 | §8.3 | needing a fresh pre-registration per retrain | keep — **but it is not in force** (§1.3 A) |
| Everything in Docker; one GCP run at a time; data lives on the VM | AGENTS.md | operational mistakes that cost real runs | keep |

The protection you are worried about losing lives in the first, third, fourth and fifth rows. None
of the changes below touches them.

### 1.2 Where the friction actually comes from

Reading the backlog, every item marked "blocked by protocol" is blocked in the same way: *"needs a
pre-registration written first, on data the exploration did not touch."* The served-coverage
re-registration, the 240m book question, B3's floor — all three. Writing the pre-registration is an
hour of work; that is not the blocker. The blocker is the second clause. M3_PROTOCOL §8.2 says so in
its own words: *"the one genuinely untouched source is forward time … expect the confirmatory step
to wait on forward data."* And forward time has produced zero usable trades since the test began,
first because of the candle defect and now because the market has to cooperate. So the system, as
written, has **no confirmatory dataset at all** except waiting. That is what makes it feel like a
wall, and it is a structural gap, not an over-tight threshold.

### 1.3 The four fixes, ranked

**A. Put Amendment 1 in force — two decisions have been sitting since 2026-09-01.**
M3_PROTOCOL §8.6 left three questions open and said the champion–challenger rule "is not in force
until these are answered". RETRAIN_PLAN §8 answered Q3 (quarterly cadence) but **Q1 and Q2 were
never answered**, so as of today no retrained checkpoint can be promoted whatever it scores. The
recommendations were already written down there; they only need a yes. See §4, decisions 1–2.

**B. Give the confirmatory lane a dataset that exists: walk-forward folds over the older history.**
A model trained on data up to 2025-06 and scored on 2025-06→2025-12 produces out-of-sample
predictions on a period that **no M3 search has ever looked at** (every M3 number was measured on
2025-12→2026-09). Step the boundary back fold by fold and the policy can be scored out-of-sample
over years of history instead of 253 days. RETRAIN_PLAN §8 Q1 (d) and Q2 (B) already chose these
folds — but framed them as *precision for certifying a fresh checkpoint*. They are the same runs,
and they are also:

* the untouched data §8.2 says every exploratory finding needs before promotion;
* the only thing that makes a learned or RL policy decidable (§2.4);
* the only way to re-test any "closed" lever cheaply, since each fold is an independent check.

This should be written into the protocol as the **standing confirmatory dataset**, with the fold
shape decided first (RETRAIN_PLAN §7 B: anchored versus rolling fixed-width; **rolling fixed-width
recommended**, so every fold trains on the same amount of data and boundary age is the only thing
that moves). Cost: one training run per fold per seed, strictly serial, about 4.4 hours each on the
current GPU box (T1 ran 05:07→09:31 UTC). Four folds × three seeds ≈ 53 hours of wall clock.
Caveats to state up front: the newer pairs (HYPE, WLD, ZEC, 1000PEPE) do not exist in the older
folds, so early folds are majors-only; and older regimes differ — which is precisely the robustness
Tier 1 wants to see.

**C. Stop ranking on the statistic the project has proven undecidable — in the *next* protocol.**
Tier 1 ranks by worst-window net at taker and vetoes below −5 bps. RETRAIN_PLAN §5.3–5.4 then showed
that a single window's day-clustered interval is ±50–100 bps wide against a ~15 bps edge, and that
no ordering of w1..w4 is resolvable. Today's re-score makes the consequence concrete: the incumbent
passes P3 at **−4.61 against a −5 floor** — the promotion decision hangs on 0.4 bps of a number with
a ±50 bps interval. Pre-registered verdicts stand; that is the rule and it is right. But every
future pre-registration should rank on **the day-clustered lower bound of pooled net at taker**
(Tier 2's statistic, used as an axis rather than a pass/fail), keep worst-window only as a veto, and
calibrate that veto to the window's own error (veto when the window's clustered *upper* bound is
below zero, i.e. when it is significantly bad, not merely negative). With walk-forward folds,
"worst fold" over eight or more folds regains meaning that "worst of four" never had.

**D. Write the data-correction clause.** The candle defect was handled ad hoc, and the handling is
internally inconsistent: RETRAIN_PLAN §8 Q0 re-runs the M3-2 search on repaired data but says M3-3's
challengers "do not retroactively pass", while CANDLE_POLL_DEFECT §3 says all three verdicts are
"worth re-scoring". Either the repaired data is the population or it is not. The clean rule:

> When an input defect is found, the pre-registered protocol — every sub-protocol, the full grid, the
> same bar, the same folds — is **re-executed in full on the corrected data**. Eligibility (P4) is
> recomputed from the new trade counts before any P&L is read. The re-executed verdict replaces the
> original; both are kept; nothing is re-chosen. This is not an amendment. It is running the protocol
> on the data it was written for.

That is exactly the instinct behind question 3, and §2 does it.

### 1.4 What I would leave alone, and one thing to watch

* **M2's freeze** is a budget decision and a sound one: eight levers tested one at a time, three
  seeds where it mattered, two-sided brackets on capacity. A few rows in NEXT_TRAINING_PLAN §5 were
  closed on one run (context length, ensembling) and are "closed at this baseline", not refuted —
  the folds in B are the cheap way to re-test any of them if ever wanted. Do not reopen M2 for it.
* **The quarterly retrain cadence conflicts with the forward test as currently defined.** Every swap
  "restarts the forward clock" (§8.4), and at ~2 trades a day a forward ledger will never reach a
  usable count between swaps. Resolution: never discard the forward ledger on a swap. Tag every
  forward trade with the checkpoint and constants that produced it, and score **the recipe** pooled
  across checkpoints. That is walk-forward, live. See §4, decision 5.
* **The exploratory lane has never been used.** Two probes are already filed in BACKLOG (hour-of-day
  seasonality, market-neutral pairing). They cost a laptop hour each. Run them.

---

## §2 — M3 on corrected data: what was run today, and what it says

### 2.1 Why this is allowed, and why nothing about the models needs restarting

The rule against re-running is a rule against **re-choosing** after seeing results. Re-executing
the *same* pre-registered configurations, under the *same* decision rule, on data that was supposed
to be correct the first time, chooses nothing. It is §1.3 D applied.

What was actually wrong: the collector stored every candle from 2026-07-18 as a first-minute
snapshot. The training window of every checkpoint ends **2025-12-10**, so **no model was trained on
a corrupt bar**. The corruption sits in the last ~31 days of the 253-day validation window — 12% of
it, all inside calendar window w4, which was not the binding window for the incumbent (w3 is). The
three seeds were re-evaluated on the repaired database on 2026-09-04 (RETRAIN_PLAN §4), producing
new prediction dumps; those dumps are what the harness reads under `M3_ERA=repaired`.

One honest caveat, already recorded in RETRAIN_PLAN §5.1: the repaired dumps are not the same
calendar rows. Because the split is a fraction of a growing history, the validation window moved —
it now starts 2025-12-22 and ends 2026-09-03 (was 12-09 → 08-19). So "repaired" is the same
protocol on a slightly shifted population, and both eras are reported side by side.

### 2.2 The pre-registered re-score (M3-2), run 2026-09-04

```sh
M3_ERA=repaired ./scripts/m3.sh -m m3 validate   # C3: TEST 1 PASS, TEST 2 PASS
M3_ERA=repaired ./scripts/m3.sh -m m3 power      # eligibility: 16 of 36, the same sixteen
M3_ERA=repaired ./scripts/m3.sh -m m3 search     # the 40 pre-registered runs, Tier 1
```

Logs: `logs/Q0-repaired-all.log`; the generated report is
[M3_2_RESULTS_REPAIRED.md](./M3_2_RESULTS_REPAIRED.md) (pre-repair original:
[M3_2_RESULTS.md](./M3_2_RESULTS.md)).

**The verdict is unchanged in kind and slightly weaker in degree.**

| | pre-repair (2026-08-27) | repaired (2026-09-04) |
|---|---:|---:|
| primary grid: configs clearing Tier 1 | 1 of 36 (`cov0.02_hold240`) | 1 of 36 (the same one) |
| grid winner, worst window / pooled net at taker | −3.56 (w4) / +8.03 | **−4.98 (w4)** / +7.24 |
| incumbent `..._SIZED`, worst window / pooled net at taker | +0.25 (w3) / +15.03 | **−4.61 (w3)** / +13.82 |
| incumbent per seed, net at taker | all positive | +8.41 / +11.94 / +21.97 |
| incumbent Tier 2 (clustered 95% CI) | [−33.0, +63.1], FAIL | [−34.9, +62.6], FAIL |
| M3-3's bar (Tier 1 + beat the incumbent's worst window) | +0.25 | **restated to −4.61** |

Three readings, all pre-registered in RETRAIN_PLAN §8 Q0 before the numbers:

1. **The incumbent passes P3, so it is still servable under its own bar.** But it passes by 0.4 bps
   on a statistic with a ±50 bps interval (§1.3 C). "Servable" here means "not shown to be broken",
   nothing stronger.
2. **M3-3's bar restates to −4.61.** The August learned runs' best worst-window was −7.18, so none
   passes even the restated bar. Under §1.3 D they are re-executed anyway (§2.3).
3. **The eligibility set did not move** — the same sixteen configurations, which is what a
   mechanical P4 should do when 12% of one window changes.

Two things reported, never selected on, that belong in view: the incumbent's **short side is
−12.69 bps at taker on 400 trades** (long +21.42 on 1,396); and its drawdown is larger than the
flat-size anchor's (−4.59 against −2.76), which is what sizing up into volatility buys.

### 2.3 The learned policy re-executed (M3-3)

```sh
M3_ERA=repaired ./scripts/m3.sh -m m3 learn      # the 14 pre-registered learned runs
```

Logs: `logs/Q0-learn-repaired.log`; report: [M3_3_RESULTS_REPAIRED.md](./M3_3_RESULTS_REPAIRED.md).

**The verdict is unchanged: no learned configuration passes Tier 1** — 0 of 8, on the same
leave-one-window-out folds, same nine observations, same two model classes.

| | pre-repair (2026-08-27) | repaired (2026-09-04) |
|---|---:|---:|
| learned configs passing Tier 1 | 0 / 8 | 0 / 8 |
| best learned worst-window net at taker | −7.18 (`learnA_R2_S2`) | −6.6 (`learnA_R2_S1`) |
| the bar it had to beat | +0.25 | −4.61 (restated, §2.2) |
| confidence-only ablation beats both fitted models | 3 of 4 pairings | 3 of 4 pairings |
| swing of the top-decile gross edge across windows | 25.9 bps | 30.8 bps |

⚠️ The generated report prints the bar as "+0.25" because that constant is hard-coded in
`m3/learn.py` from the pre-repair M3-2 result; read it as −4.61. The reading does not change: the
best learned row is 2 bps below even the restated bar, and fails P1, P2, P3 and P5 outright.

Two things worth carrying forward. First, the ablation result — that the eight extra observations
*cost* money on ~190 independent days — replicates exactly, which is the strongest evidence in the
project about how much a learned policy can be fed here. Second, the level of the edge moves even
more between windows on repaired data (30.8 bps), which is why every entry rule that thresholds an
*absolute* predicted edge (R1) collapses and only rank-based rules survive.

### 2.4 Rule versus RL: what the evidence actually says, and what would change it

The design documents always said "discrete RL / bandit policy over flat, long, short, hold, exit".
M3-3 implemented the *direct method* — a ridge-regression value function over nine market
observations, with the policy derived from it — and its protocol argues correctly why that is not
a shortcut: the dumps hold the forward return for **every** bar, so the counterfactual reward of
every action is known exactly. With full feedback and a fixed four-hour hold, the bandit problem
*is* supervised regression; an RL algorithm would estimate the same quantity with more variance.

RL becomes a genuinely different problem only when there is **sequential state**: an exit decision
at each step, position inventory, concurrency. Two things are true about that today:

* It is now *expressible*. M3-0b built the five-minute price path inside every hold, which is what
  a learned exit needs. It did not exist in August.
* It is not *decidable* on this population. M3-3 showed nine linear coefficients on ~220
  independent days already overfit — the confidence-only ablation beat both fitted models. A
  learned exit has ~48 decisions per trade on the same 220 days and a reward with a 259-bps
  per-trade spread. The M3-0b slice also found every fixed barrier exit loses to the four-hour
  hold. An RL run today would return `NOT DECIDABLE`, as every recent test has, and the rules are
  not what stops it.

So the position is: **rule-based stands, not because RL is forbidden, but because it cannot be
scored yet.** The thing that makes it scoreable is §1.3 B — walk-forward folds turn ~220
independent days into roughly 800–1,000, at which point a learned policy (linear first, then
sequential) is a legitimate challenger under C1–C5. If Vadim wants a cheap probe before then, the
honest form is an **exploratory** learned exit on the side-table (hold/exit at each 5m step,
leave-one-window-out, against the fixed 4h hold), labelled `EXPLORATORY`, expected to be
undecidable, and useful only as a reason to write the fold protocol. See §4, decision 8.

---

## §3 — The cleanup inventory

Nothing here has been deleted or moved. The verdicts are proposals; §4 asks for approval on the
irreversible parts (local, gitignored files) and on the doc restructuring as a separate session.

### 3.1 Documents — three kinds, and what to do with each

**Live (keep, and keep current):** AGENTS.md · BACKLOG.md · M3_PLAN.md · M3_PROTOCOL.md ·
RETRAIN_PLAN.md · CANDLE_POLL_DEFECT.md · CANDLE_GUARD.md · REAL_MONEY_TRACK.md · BOOK_ERA_PLAN.md
· M3_5_INTEGRATION.md · TRAINING.md · PLAN.md · this file.

**Records (keep, read-only, never hand-edit):** M3_PROTOCOL.md · M3_3_PROTOCOL.md · M3_4_PROTOCOL.md
· M3_2_RESULTS.md · M3_3_RESULTS.md · M3_4_RESULTS.md · M3_0B_RESULTS.md · M3_FIDELITY_RESULTS.md ·
T6_RESULTS.md · the two `*_REPAIRED.md` results from today · archive/*.

**Archive (move to `docs/archive/` with a two-line header saying what superseded it):**

| file | why |
|---|---|
| `SPEC.md` (root, 2026-03-25) | the original system spec; everything it plans is either built or superseded by PLAN.md |
| `MODEL.md` (root, 2026-07-18) | design frozen on 07-18; weekly-retrain cadence, 1m/15m/1h horizons and "RL policy" are all superseded. Keep one paragraph "design as built" in PLAN.md |
| `docs/archive/M1_PLAN.md`, `docs/archive/M2_PLAN.md` | completed milestones |
| `docs/archive/SIMULATION.md` | the Phase-I signal simulation; superseded by M3_5_INTEGRATION |
| `docs/archive/QUANT_AB_HANDOFF.md` | a closed A/B from 08-05 (verdict: quantile head off) |
| `docs/archive/GCP_MIGRATE.md` | the one-off Mac→GCP migration; its 09-03 candle-guard note moves to CANDLE_GUARD.md first |
| `docs/archive/DATA_COLLECTION_AUDIT.md` | the 08-05 audit; one parked backlog row cites item 3 — keep that pointer, archive the rest |
| `docs/archive/M3_UI_PLAN.md` | built and deployed; its doctrine (empty-state, nil vs 0.00) is worth one paragraph in M3_5_INTEGRATION |

**Slim (the real payoff — the three documents that have grown by accretion):**

| file | lines | what happened | target |
|---|---:|---|---|
| `M3_PLAN.md` | 1,629 | §0.0 "RESUME HERE" is now 90 lines of stacked "Earlier:" paragraphs plus 700 lines of "What M3-x established" — the pattern the hygiene rule forbids. It also still says M3-5 is "not deployed" in three places | §0.0 → 40 lines pointing at BACKLOG; the "established" sections fold into §2's per-step entries or archive; ~800 lines |
| `NEXT_TRAINING_PLAN.md` | 1,766 | M2 is frozen. Keep §0 rules, §1.3/§1.8 reference numbers, §5 closed levers, §7 mechanics; the top block still says "served on 8 pairs" | ~500 lines |
| `BACKLOG.md` | 641 | an index that became a narrative (deploy-day defects, the twelve-pair widening, the arrival-rate finding are all told in full here) | tables only, ~250 lines; narratives move to their owning docs |

**Pick one entry point.** BACKLOG.md, M3_PLAN.md §0.0, NEXT_TRAINING_PLAN.md and RETRAIN_PLAN.md
each currently present themselves as where to start. Make it BACKLOG.md, and have README.md's
status section (still "Phase I light", July) point there in ten lines.

**One tracked file that actively misleads:** `.opencode/skills/ml-experiment-workflow/SKILL.md`
tells an agent the primary horizon is 30m, horizons are 5/30/60 and the gate is 0.58 — all
superseded since 2026-08-21. Delete it if opencode is no longer used; otherwise rewrite it to point
at AGENTS.md and BACKLOG.md (§4, decision 7).

### 3.2 Scripts

| script | verdict | why |
|---|---|---|
| `gcp_train / status / logs / promote / common / env*` | keep | the pipeline |
| `gcp_backfill*`, `gcp_data_collection_stats`, `gcp_m3_export`, `m3.sh`, `candle_guard`, `install_candle_guard` | keep | live |
| `gcp_gbt.sh` | keep | B3 is a LightGBM run and this is its launcher |
| `gcp_depth_ws_test.sh` | keep | the parked WS-depth consumer's probe |
| `gcp_walkforward.sh` | **keep — repurpose** | retired for the book ablation, but it is the only existing launcher that sweeps `--val-offset` over K folds on a throwaway VM: the closest thing to the fold runner §1.3 B needs |
| `gcp_ablate.sh`, `gcp_audit.sh` + `ml/train/audit_microstructure.py` | archive (`scripts/archive/`) | M2-era studies; the walk-forward *design* is retired in NEXT_TRAINING_PLAN §5 |
| `quant_ab.sh` | delete | closed A/B with a known zone bug |
| `export_local.sh`, `upload_to_gcp.sh`, `import_on_server.sh` | delete | the pre-bucket 5-step flow, which GCP_TRAIN_DESIGN says "has been removed" |

### 3.3 ML code and local artefacts

| item | verdict | why |
|---|---|---|
| `ml/train/train.py`, `eval.py`, `models/lstm.py` | delete; change `Dockerfile.train` CMD | M1 code; the Dockerfile's default command still runs `train.py` |
| `ml/train/check_c3_dir_mag.py` | delete | ad-hoc check for a closed lever |
| `ml/train/gate.py`, `gbt_baseline.py`, `reaggregate_preds.py`, `verify_candles.py` | keep | used by `m3/validate.py`, B3, the harness, the guard |
| `ml/train/output/m1_15m.pt`, `history*.json`, `probe*.json`, `eval_m2.json`, `microstructure_audit.json` | delete (local, gitignored) | M1/M2-era leftovers |
| `ml/train/output/m3_4/*.csv.gz` (547 MB) | delete after `bookprep` confirms it reads the parquet | `bookprep` caches parquet next to each csv and reads the parquet when present; the export takes ~2 h to regenerate, so **keep the parquet** |
| `ml/train/output/eval_dumps/` (9 dumps, 278 MB) | keep all | the three pre-repair dumps are the record of the corrupt tail; all are in the bucket too |
| `ml/train/output/m3_0b/`, `probe/` | keep | side-table; the `EXPLORATORY` probes |
| root: `erl_crash.dump` (5.4 MB), `m2_multi_epoch_snapshot.pt`, `.DS_Store`, empty `_build/`, `deps/` | delete (local, gitignored) | crash dump from 08-29; a July epoch snapshot; host-side leftovers |

### 3.4 Local logs (`logs/`, gitignored, 4.6 MB)

Every training log is also in the bucket at `gs://fluxtrader-train-artifacts/logs/<run>.log`, so
the local copies are a cache. Recommendation: **move, do not delete** — `logs/archive/` for
everything referenced only by `docs/archive/TRAINING_HISTORY.md` (E*, N*, O*, P0-*, P2.log, Q0/Q2/Q3,
R0, R1.log, R2*, R3*, R4*, R5, R6, runA/B*, ablate_*, F3/F4, audit.log, latest_fixed.log,
walfforward.log, error.log, `eval_m2_E2b*.json`, `quant_ab_*`). Keep in place: T1, T2, the
R1-repair set, P2-*, Q0-*, fidelity_*, b1/b2 — everything a live document cites.

### 3.5 The commands, for after approval

```sh
# local, gitignored, irreversible — §4 decision 6
rm -f erl_crash.dump m2_multi_epoch_snapshot.pt .DS_Store
rmdir _build deps
rm -f ml/train/output/{m1_15m.pt,history.json,history_m2.json,probe.json,probe_spearman.json,eval_m2.json,microstructure_audit.json}
mkdir -p logs/archive && cd logs && mv E*.log N*.log O*.log P0-*.log P2.log Q0.log Q2.log Q3.log \
  R0.log R1.log R2*.log R3*.log R4*.log R5.log R6.log runA*.log runB*.log ablate_*.log F3.log F4.log \
  audit.log latest_fixed.log walfforward.log error.log eval_m2_E2b*.json quant_ab_* archive/ && cd ..
# tracked, reversible via git — same decision
git rm -q scripts/quant_ab.sh scripts/export_local.sh scripts/upload_to_gcp.sh scripts/import_on_server.sh \
  ml/train/train.py ml/train/eval.py ml/train/models/lstm.py ml/train/check_c3_dir_mag.py
mkdir -p scripts/archive && git mv scripts/gcp_ablate.sh scripts/gcp_audit.sh scripts/archive/
# then: edit ml/train/Dockerfile.train CMD → train_m2.py; the doc moves are a separate session (§4 decision 7)
```

---

## §4 — The decisions, each as its own question — ✅ all answered 2026-09-04

| # | decision | answer | carried out as |
|---|---|---|---|
| 1 | §8.6 Q1, promotion evidence | **(c)** promote on backtest, keep on forward | M3_PROTOCOL §9.1, with the revert bar stated |
| 2 | §8.6 Q2, C2 margin | **(c)** margin above the between-seed spread **plus** a win on 2 of 3 axes | M3_PROTOCOL §9.1 |
| — | §8.6 Q3, cadence or trigger | **(b)** trigger: 65 days without a bar meeting the cut | M3_PROTOCOL §9.1; `Policy.retrain_trigger_days/0`; live at `/api/health` → `policy.retrain_trigger`; RETRAIN_PLAN §8 Q3 superseded |
| 3 | data-correction clause; today's re-execution as verdict of record | **yes** | M3_PROTOCOL §9.2; `policy.ex` cut `0.6296127438545227`, ladder p80 `0.025596268475055695`, `config_test.exs` updated |
| 4 | walk-forward folds | **as proposed** — rolling fixed-width | `TRAIN_FRACTION` plumbed end to end; WALKFORWARD_PROTOCOL.md pre-registered (4 folds × 3 seeds, queue in its §5) |
| 5 | keep the forward ledger across swaps | **yes** | migration `20260904000001`, `paper_trades.checkpoint` / `ladder_p80`, stamped on every open; M3_PROTOCOL §9.6 |
| 6 | local deletions and log moves | **approved** | done — §3.5's commands ran; `Dockerfile.train` CMD now `train_m2.py`; `scripts/archive/` holds the two M2-era studies |
| 7 | doc restructuring session; opencode | **approved**; opencode still used occasionally | the skill file is rewritten to point at AGENTS.md / BACKLOG.md; the restructuring brief is §6.3 |
| 8 | learned-exit probe now or later | *"What folds?"* — answered in WALKFORWARD_PROTOCOL §0; **defaulted to wait** for the folds | — |

Also built, because decisions 3 and 5 need it: **the checkpoint-binding guard** (RETRAIN_PLAN
Phase 0.2, M3_PROTOCOL §8.4 precondition 1) — `ml_inference` now hashes the weights it loads and
the policy refuses to enter a bar unless the hash matches the constants' checkpoint.

### The original questions, kept for the record

**1. M3_PROTOCOL §8.6 Q1 — what evidence promotes a challenger?**
(a) backtest Tier 1 + beating the incumbent; (b) N forward trading days; (c) **promote on backtest,
keep on forward** — swap on C1–C5, revert automatically if the forward ledger fails a stated bar.
*Recommend (c)*, as §8.6 already did. Without an answer the champion–challenger rule stays out of
force and no retrain can ever be served.

**2. M3_PROTOCOL §8.6 Q2 — what margin must C2 clear?**
(a) any positive margin on the family median; (b) **a margin exceeding the between-seed spread**;
(c) a margin plus a win on two of {worst-window, pooled, trade rate}. *Recommend (b).*

**3. Adopt the data-correction clause (§1.3 D) as Amendment 2, and accept today's re-execution as
the verdict of record?** Yes means the repaired-era results replace the August ones as M3-2's and
M3-3's verdicts (both kept), the bar is −4.61, and the constants in `policy.ex` are re-derived under
C4 from the repaired split (cut 0.6296, RETRAIN_PLAN §4). No means the August verdicts stand and
today's runs are informational. *Recommend yes.*

**4. Fund walk-forward folds as the standing confirmatory dataset (§1.3 B)?** This is the GPU
decision: ~4 folds × 3 seeds × ~4.4 h, serial, ≈ 53 hours wall clock, plus a fold-shape decision
first (*recommend rolling fixed-width*). It is the one investment that unblocks the parked
pre-registrations, retraining, and any learned policy. If no, everything above stays blocked on
forward time and that should be written down as the accepted state.

**5. Keep the forward ledger across checkpoint swaps (§1.4)?** Tag each forward trade with the
checkpoint and constants; score the recipe pooled across swaps. *Recommend yes* — otherwise a
quarterly cadence guarantees the forward test never accumulates.

**6. Approve the local deletions and log moves in §3.5?** The local files are gitignored and not
recoverable except the training logs (bucket). *Recommend yes.*

**7. Approve the document restructuring in §3.1 as its own session?** Archive eight documents, slim
three, make BACKLOG.md the single entry point, refresh README.md. It touches cross-links in most
documents, so it should be one focused session. *Recommend yes.* Sub-question: is opencode still in
use — delete or rewrite its skill file?

**8. Run an `EXPLORATORY` learned-exit probe now (§2.4), or wait for the folds?** Laptop-only, no
GPU, expected `NOT DECIDABLE`, useful as a reason to write the fold protocol. *Recommend wait* —
unless you want the shape of the problem visible before deciding on 4.

---

## §5 — What this review did not do — as of the review; see §6 for what was then done

* It did not edit M3_PROTOCOL.md. Amendment 2 (the data-correction clause and the ranking-axis
  proposal for future protocols) is drafted in §1.3 and is written into the protocol only after
  decision 3.
* It did not change `policy.ex`. The C4 re-derivation of the served constants on repaired data is
  pending decision 3 and restarts the forward clock (§8.4).
* It did not review `apps/` (the Elixir application, 76 files) for dead Phase-I code such as the
  original `SignalEngine` simulation; that is a separate pass.
* It did not delete or move anything.

---

## §6 — What remains, as an exact checklist

### 6.1 Deploy the re-derived rule and the guard to `fluxtrader-1` (step 8 of CANDLE_POLL_DEFECT §7)

Nothing on the VM has changed yet. The VM still serves the pre-repair cut (0.6319) and its
`ml_inference` does not yet report a checkpoint hash — so the moment the new app code is deployed
it will **refuse to trade** (`skips.checkpoint_unverified`) until `ml_inference` is also
redeployed. That is the guard working; deploy both.

```sh
# on the Mac — commit first (the working tree holds everything below)
git add -A && git commit   # message: the 2026-09-04 decisions; see git status

# on fluxtrader-1
cd ~/trading_agent
docker compose exec postgres psql -U fluxtrader -d fluxtrader -c "SELECT count(*) FROM paper_trades"
#   -> expected 0 (nothing traded under the frozen rule). NO TRUNCATE this time: the ledger
#      persists across swaps (M3_PROTOCOL §9.6). If it is not 0, back it up as §6.4 of
#      M3_FIDELITY_RESULTS does and keep the rows — they carry no checkpoint tag and are scored
#      separately.
docker compose stop app
git pull
docker compose up -d --build ml_inference          # serve.py now reports checkpoint_sha256
docker compose up -d --build app                   # runs the migration, serves the new constants
```

**Verify** on the VM. ⚠️ Two of the six checks are **not** under `.policy` — `regime` is a
sibling block, not a child of it (`HealthController.index/2`), so `jq .policy` silently omits
them. Ask for both:

```sh
curl -s localhost:4000/api/health | jq '{policy, regime}'
```


* `confidence_threshold == frozen_threshold == 0.6296127438545227`
* `checkpoint == frozen_checkpoint == "882cd4153c2d…"` and **`checkpoint_bound: true`**. If it is
  `false`, `/models/m2_multi.pt` on the VM is not `m2_multi_20260819T142759Z_a186182b.pt` —
  re-promote it with `./scripts/gcp_promote.sh --checkpoint m2_multi_20260819T142759Z_a186182b.pt`
  and do **not** touch the constants
* `regime.frozen_p80 == 0.025596268475055695` (top-level `.regime`, **not** `.policy`) — and `regime.quintile_edges` is the four-element ladder whose last element it is
* `retrain_trigger.n_days == 65`; `fired` should be **false** — the repaired data shows the cut
  last fired 2026-08-31, so `days_since` should read a few days
* `skips` holds no `checkpoint_mismatch` / `checkpoint_unverified` after the first tick
* the dashboard's "Cut (frozen)" pill reads **0.630**

The forward clock restarts at this deploy by definition: every row from here carries the
checkpoint tag, and the A/B is read on tagged rows.

### 6.2 The fold queue

[WALKFORWARD_PROTOCOL.md](./WALKFORWARD_PROTOCOL.md) §5, **F2 first**. Before the first launch:
clear the VM dump cache, and build the `M3_ERA=walkforward` harness support (§2 of that protocol)
in the same session that fetches the first dump — it must exist before any fold number is read.
Twelve serial runs at roughly four hours each; record each in §6 of the protocol from its own
`Split` line.

### 6.3 The document-restructuring session (decision 7) — ✅ DONE 2026-09-04

*What was actually done, against the brief below: all nine documents archived with headers and
every cross-link fixed (including the ones in `apps/` and `scripts/`); `M3_PLAN.md` §0.0 rewritten
to ~50 lines pointing at BACKLOG, its "What M3-x established" narrative archived and §0.6/§0.7/§0.8
moved to the end of §2 with their headings intact so external citations still resolve;
`NEXT_TRAINING_PLAN.md` slimmed from 1,766 to ~670 lines (§0, §1.1/§1.3/§1.8, §2, §5, §7) with the
rest archived, and its "served on 8 pairs" claim corrected; `BACKLOG.md` reduced from 674 to ~275
lines of tables, with six narratives moved to their owning documents; `README.md` rewritten to
point at BACKLOG. ⚠️ Two deviations, both deliberate: `M3_PLAN.md` came to ~1,280 lines rather
than the ~800 target, because the remaining length is §0.5's plain-language layer and §2's
per-step record, neither of which is accretion; and this file is **not** archived, because §6.2
is not finished.*

**The original brief:**

One session, in this order, nothing else in it:

1. Move to `docs/archive/` with a two-line "superseded by" header: `SPEC.md`, `MODEL.md`,
   `docs/archive/M1_PLAN.md`, `docs/archive/M2_PLAN.md`, `docs/archive/SIMULATION.md`, `docs/archive/QUANT_AB_HANDOFF.md`,
   `docs/archive/GCP_MIGRATE.md` (its candle-guard install note first moves into `CANDLE_GUARD.md`),
   `docs/archive/DATA_COLLECTION_AUDIT.md` (the BACKLOG row for kline taker-buy volume keeps its
   pointer), `docs/archive/M3_UI_PLAN.md` (its empty-state doctrine becomes one paragraph in
   `M3_5_INTEGRATION.md`). Fix every cross-link (`grep -rn` each filename under `docs/`).
2. Rewrite `M3_PLAN.md` §0.0 to ~40 lines pointing at BACKLOG; fold the "What M3-x established"
   sections into §2's per-step entries; remove the three "not yet deployed" statements. Target
   ~800 lines.
3. Slim `NEXT_TRAINING_PLAN.md` to §0 rules, §1.3/§1.8 reference numbers, §5 closed levers,
   §7 mechanics; move the rest to `archive/TRAINING_HISTORY.md`. Fix "served on 8 pairs".
   Target ~500 lines.
4. Turn `BACKLOG.md` back into an index: tables only; the deploy-day, twelve-pair-widening and
   arrival-rate narratives move to their owning documents. Target ~250 lines.
5. `README.md`: replace the "Phase I light" status with ten lines pointing at BACKLOG.md.
6. Add `RULES_REVIEW.md` itself to the archive list once §6.1 and §6.2 are done — it is a
   record, not a plan. ⚠️ **Not yet: §6.2's twelve runs have not been launched.** Archive it in
   the session that records the last fold in `WALKFORWARD_PROTOCOL.md` §6.
