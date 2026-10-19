#!/usr/bin/env bash
# R59 (docs/PLAN.md §8, decision AR1): R8 gated on the basket's volatility regime (V90 = −1, volatile), confirmed ONCE on F3+F4 under the
# guard; then the described calm half on the same bars and the report. Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r59 'bash scripts/r59_chain.sh'      # log: output/logs/r59.log
# F3+F4 are SPENT for R8 and its state variants after this whatever the verdict. The chain's exit arms a poweroff 30 min later.
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
step r59_read python -m ft2 backtest trendfall4h_v90 --folds F3 F4 --registration R59 --execs taker maker
step r59_calm python scripts/r59_read.py calm
step r59_report python scripts/r59_read.py report
echo "$(date -u +%H:%M:%S) R59_CHAIN_DONE"
