#!/usr/bin/env bash
# R52 (docs/PLAN.md §8, decision AF's AF1): the week INTO a promised unlock confirmed ONCE on F3+F4's frozen events (ft2/unlocks_f34.csv,
# committed before any bar) — one row, one-sided, the sign fixed NEGATIVE by the registration; R51's stage1.json the REFUTED reference only.
# Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r52 'bash scripts/r52_chain.sh'      # log: output/logs/r52.log
# An audit on the candles: no walk, no fit, the guard is not involved — the registration is the guard. F3+F4 is SPENT for unlocks after
# this whatever the verdict. The chain's exit arms a poweroff 30 min later.
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
test -s output/audit/r51_unlocks/stage1.json || { echo "R51's stage1.json missing: the REFUTED reference"; exit 3; }
step r52_confirm python scripts/r51_unlocks.py confirm
echo "$(date -u +%H:%M:%S) R52_CHAIN_DONE"
