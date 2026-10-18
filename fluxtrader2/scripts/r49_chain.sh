#!/usr/bin/env bash
# R49 (docs/PLAN.md §8): the time of day of R14's decisions — the held-out IC by hour on R14's saved forecast cells, the seen half (F1–F5)
# first and the pre-history (FP+F0) the confirmation half. Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r49 'bash scripts/r49_chain.sh'      # log: output/logs/r49.log
# Reads saved forecasts and saved fills against the candles' panel; no walk, no fit, no fold is read, the guard is not involved. The
# chain's exit (done or failed) arms a poweroff 30 min later.
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
step r49_hours python scripts/r49_hours.py --draws 2000
echo "$(date -u +%H:%M:%S) R49_CHAIN_DONE"
