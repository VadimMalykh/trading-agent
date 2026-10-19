#!/usr/bin/env bash
# R60 (docs/PLAN.md §8): the Coinbase spot premium per name as a ceiling screen on the twelve in P2's frame — validity first (P2's
# ret_1d row and null reproduced; known-at; coverage), then the level, the deviation from the trailing month and the 24-h change on the
# 8 liquid names, both nulls at 200 draws, the family of four, the gate at 1d. F1+F2 only; no confirmation fold is read. Serial on the
# work VM:
#   ./fluxtrader2/scripts/vm.sh bgsh r60 'bash scripts/r60_chain.sh'      # log: output/logs/r60.log
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
FT2_JOBS=3 step r60 python -m ft2 ceiling --target pairs --family coinbase --draws 200
echo "$(date -u +%H:%M:%S) R60_CHAIN_DONE"
