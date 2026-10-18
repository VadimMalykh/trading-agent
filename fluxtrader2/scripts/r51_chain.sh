#!/usr/bin/env bash
# R51 (docs/PLAN.md §8): token unlocks on the members — stage 1 on F1+F2's promised events, then stage 2 on F3+F4's ONLY if stage 1
# cleared a row (stage1.json's run_stage2). The event lists were frozen and committed before this runs (`python scripts/r51_unlocks.py
# select`, pulled, copied to ft2/unlocks_*.csv). Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r51 'bash scripts/r51_chain.sh'      # log: output/logs/r51.log
# An audit on the candles: no walk, no fit, the guard is not involved — the registration is the guard. The chain's exit arms a poweroff
# 30 min later.
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
step r51_stage1 python scripts/r51_unlocks.py stage1
if python -c 'import json,sys; sys.exit(0 if json.load(open("output/audit/r51_unlocks/stage1.json"))["run_stage2"] else 1)'; then
  echo "$(date -u +%H:%M:%S) stage 1 cleared a row: stage 2 runs on F3+F4"
  step r51_stage2 python scripts/r51_unlocks.py stage2
else
  echo "$(date -u +%H:%M:%S) stage 1 cleared nothing: stage 2 NOT run, F3+F4 unread"
  python scripts/r51_unlocks.py stage2 > output/logs/r51_stage2.log 2>&1 || true     # writes the NOTHING TO CONFIRM stub without loading F3+F4
fi
echo "$(date -u +%H:%M:%S) R51_CHAIN_DONE"
