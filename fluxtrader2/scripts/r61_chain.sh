#!/usr/bin/env bash
# R61 (docs/PLAN.md §8): the money shape of R60's found sign on F1+F2 — a description on R60's frames, nothing gated, no confirmation
# fold read. Needs R60's output/ceiling_coinbase/{screen,move_vs_cost}.parquet on the VM. Serial on the work VM:
#   ./fluxtrader2/scripts/vm.sh bgsh r61 'bash scripts/r61_chain.sh'      # log: output/logs/r61.log
# The chain's exit arms a poweroff 30 min later.
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
step r61 python scripts/r61_shape.py
echo "$(date -u +%H:%M:%S) R61_CHAIN_DONE"
