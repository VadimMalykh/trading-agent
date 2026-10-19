#!/usr/bin/env bash
# Decision AX1 (i) (docs/PLAN.md P8): the Coinbase spot premium SOURCE AUDIT extended to the screener's members — the product listing,
# the hourly candles from 2023-04-01 and the daily bars from 2015 for each listed member base, the ingest to a SEPARATE parquet, the
# audit against the archive klines with the member-hours cover, the per-block breadth and the volume share described. Nothing
# registered, no fold read. Serial on the work VM:
#   ./fluxtrader2/scripts/vm.sh bgsh ax1 'bash scripts/ax1_chain.sh'      # log: output/logs/ax1.log
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
step ax1_products python -m ft2 coinbase products --universe members
step ax1_fetch python -m ft2 coinbase fetch --universe members --listed-only
step ax1_ingest python -m ft2 coinbase ingest --universe members
step ax1_audit python -m ft2 coinbase audit --universe members
echo "$(date -u +%H:%M:%S) AX1_CHAIN_DONE"
