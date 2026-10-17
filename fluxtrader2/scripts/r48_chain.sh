#!/usr/bin/env bash
# R48 (docs/PLAN.md §8): the candle ridge on the pre-history, once — R14's registered rule walked over FP+F0 under the harness's
# confirmation guard (read once per registration: a second start skips the done step and never re-walks), then the state read.
# Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r48 'bash scripts/r48_chain.sh'      # log: output/logs/r48.log
# The chain's exit (done or failed) arms a poweroff 30 min later.
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
step r48_walk python -m ft2 backtest ridgebook --param hold=288 --folds FP F0 --registration R48 --execs taker maker --draws 200 --name r48_ridgebook_1d_ho12_pre
step r48_read python scripts/r48_pre.py
echo "$(date -u +%H:%M:%S) R48_CHAIN_DONE"
