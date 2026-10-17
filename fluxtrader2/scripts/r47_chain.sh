#!/usr/bin/env bash
# R47 (docs/PLAN.md §8): the mechanism behind R45 — IC by state on R14's saved forecasts, dispersion and correlation by state from the
# candles, the ceiling's saved daily ICs by state. Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r47 'bash scripts/r47_chain.sh'      # log: output/logs/r47.log
# Reads saved forecasts, a saved panel and the candles; no walk, no fit, no fold is read, the guard is not involved. The chain's exit
# (done or failed) arms a poweroff 30 min later.
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
step r47_mech python scripts/r47_mech.py
echo "$(date -u +%H:%M:%S) R47_CHAIN_DONE"
