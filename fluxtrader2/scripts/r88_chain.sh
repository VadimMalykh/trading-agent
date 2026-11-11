#!/usr/bin/env bash
# R88 (docs/PLAN.md §8): the frozen all-inputs ridge, fitted on F1+F2 members, scored ONCE on F3+F4 (guarded; `ft2 allgbm confirm`).
# name group and by time (`ft2 allgbm run`). One step, F1+F2 only, nothing fetched.
#   ./fluxtrader2/scripts/vm.sh bgsh conf88 'bash scripts/r88_chain.sh'      # log: output/logs/conf88.log (the job's name differs from the step's)
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

python -c "import lightgbm, sklearn; print('lightgbm', lightgbm.__version__, 'sklearn', sklearn.__version__)"
FT2_JOBS=8 step r88_read ft2 allgbm confirm
echo "$(date -u +%H:%M:%S) R88_CHAIN_DONE"
