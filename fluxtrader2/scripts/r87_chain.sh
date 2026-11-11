#!/usr/bin/env bash
# R87 (docs/PLAN.md §8): one LightGBM model on every per-name input in hand — the members' next day against their peers, held out by
# name group and by time (`ft2 allgbm run`). One step, F1+F2 only, nothing fetched.
#   ./fluxtrader2/scripts/vm.sh bgsh gbm87 'bash scripts/r87_chain.sh'      # log: output/logs/gbm87.log (the job's name differs from the step's)
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
FT2_JOBS=8 step r87_read ft2 allgbm run
echo "$(date -u +%H:%M:%S) R87_CHAIN_DONE"
