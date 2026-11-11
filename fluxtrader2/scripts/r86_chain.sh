#!/usr/bin/env bash
# R86 (docs/PLAN.md §8): the volatility sort at a month — the members' trailing 4-week volatility and largest one-day move against their
# peers, held 14 and 28 days, in R43's frame (`ft2 horizon --vol`), the registered sign NEGATIVE. One step, F1+F2 only, nothing fetched.
#   ./fluxtrader2/scripts/vm.sh bgsh vol86 'bash scripts/r86_chain.sh'      # log: output/logs/vol86.log (the job's name differs from the step's)
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

echo "$(date -u +%H:%M:%S) git $(git rev-parse --short HEAD)"
FT2_JOBS=4 step r86_read ft2 horizon --vol
echo "$(date -u +%H:%M:%S) R86_CHAIN_DONE"
