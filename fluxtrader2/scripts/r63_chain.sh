#!/usr/bin/env bash
# R63 (docs/PLAN.md §8, decision AZ1): BTC's fall and the high-beta names — R50's `bx_1h` on the after-fall half of the bars, confirmed ONCE on
# F3+F4's members with the sign fixed NEGATIVE. The script reproduces R50's described F1+F2 rows by the mask path FIRST (a mismatch voids the
# run before any F3+F4 bar), appends the guard rows (R63, F3) and (R63, F4) to output/backtest/confirmation_reads.csv, then reads F3+F4 once.
# The twelve are not read. Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r63 'bash scripts/r63_chain.sh'      # log: output/logs/r63.log
# The step is named r63_run, not r63: the chain's own log keeps its lines. The chain's exit arms a poweroff 30 min later.
set -euo pipefail
mkdir -p output/logs
trap 'nohup bash -c "sleep 1800; sudo poweroff" > /dev/null 2>&1 &' EXIT
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
echo "$(date -u +%H:%M:%S) members md5: $(md5sum ft2/screen_members_f34.csv)"
echo "$(date -u +%H:%M:%S) R50 reference md5: $(md5sum output/audit/r50_btchour/reference.csv)"
echo "$(date -u +%H:%M:%S) reads before: $(grep -c . output/backtest/confirmation_reads.csv) rows, R63 rows: $(grep -c ',R63,' output/backtest/confirmation_reads.csv || true)"
step r63_run python scripts/r63_fall.py run --jobs 4
echo "$(date -u +%H:%M:%S) reads after:  $(grep -c . output/backtest/confirmation_reads.csv) rows, R63 rows: $(grep -c ',R63,' output/backtest/confirmation_reads.csv || true)"
echo "$(date -u +%H:%M:%S) R63_CHAIN_DONE"
