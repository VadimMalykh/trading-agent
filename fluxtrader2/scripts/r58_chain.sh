#!/usr/bin/env bash
# R58 (docs/PLAN.md §8): the state audit on the saved fills of R8 (trendfall4h) and R32 (trend1d), then decision AQ2's described row
# (ft2 varmonth: the monthly straddle's history from Deribit's chart endpoint, then the pricing). Serial on the work VM, in the venv,
# from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r58 'bash scripts/r58_chain.sh'      # log: output/logs/r58.log
# R58 reads saved fills; no fold is read, the guard is not involved. The chain's exit (done or failed) arms a poweroff 30 min later.
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
step r58_state python scripts/r58_state.py
step varmonth_fetch python -m ft2 varmonth fetch
step varmonth_run python -m ft2 varmonth run
echo "$(date -u +%H:%M:%S) R58_CHAIN_DONE"
