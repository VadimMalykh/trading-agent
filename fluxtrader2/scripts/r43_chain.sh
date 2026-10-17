#!/usr/bin/env bash
# R43 (docs/PLAN.md §8): the slow cross-section — the members' 4- and 12-week return against their peers, held 14 and 28 days, in R22's
# frame (`ft2 horizon --mom`). One step; standalone for a re-run (scripts/r42_chain.sh runs the same step after R42's).
#   ./fluxtrader2/scripts/vm.sh bgsh r43 'bash scripts/r43_chain.sh'      # log: output/logs/r43.log
# The chain's exit (done or failed) arms a poweroff 30 minutes later (the R40 lesson); `vm.sh stop` before it is fine.
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
ft2() { python -m ft2 "$@"; }

FT2_JOBS=4 step r43_read ft2 horizon --mom --holds 4032 8064
echo "$(date -u +%H:%M:%S) R43_CHAIN_DONE"
