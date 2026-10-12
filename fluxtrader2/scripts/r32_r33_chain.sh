#!/usr/bin/env bash
# R32 and R33 (docs/PLAN.md §8), the two reads registered 2026-10-12 on P8 decision H, run serially on the work VM, in the venv,
# from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r32r33 'bash scripts/r32_r33_chain.sh'      # log: output/logs/r32r33.log
# Each step writes output/logs/<step>.log and, when it ends well, output/logs/<step>.done; a done step is not made again (R32's
# FP and F0 are guarded folds, read once under R32), so the chain can be started again after a failure. R33 exits 2 when its
# validity fails — the read is then VOID and the step is not marked done.
set -euo pipefail
mkdir -p output/logs
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
ft2() { python -m ft2 "$@"; }

# R32 — trend1d, stage 1 on R6's bars (FP and F0 logged under R32 by the guard); taker primary, maker and maker_ev beside
step r32 ft2 backtest trend1d --folds FP F0 F1 F2 --registration R32 --execs taker maker maker_ev

# R33 — the demeaned ±1 % imbalance as a ceiling screen on P2's cells; validity first (exit 2 = void)
FT2_JOBS=3 step r33 ft2 ceiling --target pairs --family depth --draws 200
echo "$(date -u +%H:%M:%S) R32_R33_CHAIN_DONE"
