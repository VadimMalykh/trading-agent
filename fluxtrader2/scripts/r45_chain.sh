#!/usr/bin/env bash
# R45 + R46 (docs/PLAN.md §8): the market's state on the saved decisions of R14, R32 and R44 (R45) and the entry slots on R14's F1+F2
# decisions (R46). Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r45 'bash scripts/r45_chain.sh'      # log: output/logs/r45.log
# Both read saved fills / decisions; no fold is read, the guard is not involved. The chain's exit (done or failed) arms a poweroff 30 min later.
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
step r45_state python scripts/r45_state.py
step r46_slots python scripts/r46_slots.py
echo "$(date -u +%H:%M:%S) R45_CHAIN_DONE"
