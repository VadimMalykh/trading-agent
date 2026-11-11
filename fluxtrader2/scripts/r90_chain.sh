#!/usr/bin/env bash
# R90 (docs/PLAN.md §8): R89's saved forecast as an hourly long-top-tenth / short-bottom-tenth book of F5's coins, priced ONCE
# (guarded; `ft2 allbook run`). Nothing fetched.
#   ./fluxtrader2/scripts/vm.sh bgsh book90 'bash scripts/r90_chain.sh'      # log: output/logs/book90.log (the job's name differs from the step's)
# The chain's exit (done or failed) arms a poweroff 30 minutes later; `vm.sh stop` before it is fine.
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

echo "$(date -u +%H:%M:%S) forecast: $(md5sum output/allgbm/r89/forecast.parquet); costs: $(md5sum data/cost_daily_wide.parquet | cut -c1-32)"
echo "$(date -u +%H:%M:%S) ledger R90 rows before: $(grep -c ',R90,' output/backtest/confirmation_reads.csv || true); R90 header in PLAN: $(grep -c "^### R90 " docs/PLAN.md)"
step r90_read python -u -m ft2 allbook run
echo "$(date -u +%H:%M:%S) ledger R90 rows after: $(grep -c ',R90,' output/backtest/confirmation_reads.csv || true)"
echo "$(date -u +%H:%M:%S) R90_CHAIN_DONE"
