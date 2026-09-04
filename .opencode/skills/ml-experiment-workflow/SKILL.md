---
name: ml-experiment-workflow
description: Use when training, evaluating, backtesting, scoring or promoting the FluxTrader signal model (M2, a 5m multi-horizon LSTM) or the M3 trading policy — running train_m2.py / eval_m2.py, any scripts/gcp_*.sh remote run, any ./scripts/m3.sh command, or reading a run log. Also when the user mentions "M2", "M3", "checkpoint", "the cut", "Tier 1", "walk-forward", or "pre-registration".
---

# FluxTrader ML experiment workflow

This file is deliberately thin. **The project's conventions live in the repository, and they
change faster than a skill file does** — an earlier version of this skill still described a
30-minute primary horizon and a 0.58 gate three weeks after both were retired. Read these,
in this order, before running anything:

1. `AGENTS.md` — everything runs in Docker (never `pip install`, never host Python), one
   `gcp_train.sh` run at a time, real data lives on the always-on VM `fluxtrader-1`, never
   the local Postgres.
2. `docs/BACKLOG.md` — the single entry point: what is active, parked, closed, and every
   open decision.
3. `docs/M3_PROTOCOL.md` — the pre-registered evaluation rules (and their amendments).
   Nothing is scored or promoted outside them.
4. `docs/RETRAIN_PLAN.md` and `docs/WALKFORWARD_PROTOCOL.md` — how retraining and
   walk-forward folds are run and scored.
5. `docs/TRAINING.md` — the mechanics of a training or eval-only run and how to fetch its log.

## The two commands that matter

```bash
# offline policy analysis on the banked prediction dumps (torch-free image, ~seconds)
./scripts/m3.sh -m m3 validate          # always first
./scripts/m3.sh -m m3 <search|learn|fidelity|decay|power|...>
M3_ERA=repaired ./scripts/m3.sh -m m3 search    # era switch: prerepair (default) | repaired

# a remote training / eval run, strictly one at a time
./scripts/gcp_train.sh                  # then ./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> > logs/<name>.log   # never --save
```

## Standing facts (verify against the docs above before relying on them)

- Served model: seed 2, `m2_multi_20260819T142759Z_a186182b.pt`, 5m bars, seq 384, primary
  horizon **240m**. The trading rule is `Policy` in
  `apps/fluxtrader/lib/fluxtrader/trading/policy.ex`, with a **frozen** coverage cut and
  regime ladder derived from that checkpoint's own split — they belong to the checkpoint.
- When reading `eval_m2.py` output, **the 240m block is the one that counts.**
- Never quote a single-seed result as a finding; never re-pick a searched knob after
  seeing its result; label anything outside a pre-registration `EXPLORATORY`.
