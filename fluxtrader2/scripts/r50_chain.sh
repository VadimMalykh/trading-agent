#!/usr/bin/env bash
# R50 (docs/PLAN.md §8): BTC's last hour as per-name information — stage 1 on F1+F2 (R18's members and the twelve), then stage 2 on F3+F4
# ONLY if stage 1 cleared a cell (stage1.json's run_stage2). Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r50 'bash scripts/r50_chain.sh'      # log: output/logs/r50.log
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
step r50_stage1 python scripts/r50_btchour.py stage1 --jobs 4
if python -c 'import json,sys; sys.exit(0 if json.load(open("output/audit/r50_btchour/stage1.json"))["run_stage2"] else 1)'; then
  echo "$(date -u +%H:%M:%S) stage 1 cleared a cell: stage 2 runs on F3+F4"
  step r50_stage2 python scripts/r50_btchour.py stage2 --jobs 4
else
  echo "$(date -u +%H:%M:%S) stage 1 cleared nothing: stage 2 NOT run, F3+F4 unread"
  python scripts/r50_btchour.py stage2 > output/logs/r50_stage2.log 2>&1 || true     # writes the NOTHING TO CONFIRM stub without loading F3+F4
fi
echo "$(date -u +%H:%M:%S) R50_CHAIN_DONE"
