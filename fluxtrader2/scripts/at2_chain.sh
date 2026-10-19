#!/usr/bin/env bash
# Decision AT2 (docs/PLAN.md P8): the Coinbase spot premium SOURCE AUDIT — the products, the hourly candles from 2023-04-01 and the daily
# bars from 2015 for each product, the ingest, the audit against Binance's 5m closes. Nothing priced, no fold read. Serial on the work VM:
#   ./fluxtrader2/scripts/vm.sh bgsh at2 'bash scripts/at2_chain.sh'      # log: output/logs/at2.log
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
step at2_products python -m ft2 coinbase products
step at2_fetch python -m ft2 coinbase fetch
step at2_ingest python -m ft2 coinbase ingest
step at2_audit python -m ft2 coinbase audit
echo "$(date -u +%H:%M:%S) AT2_CHAIN_DONE"
