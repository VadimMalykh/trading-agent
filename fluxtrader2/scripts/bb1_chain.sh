#!/usr/bin/env bash
# Decision BB1 step (i) (docs/PLAN.md P8): the Korean premium SOURCE AUDIT — Upbit's and Bithumb's KRW markets for the twelve and the
# screener's members: the listing, the hourly candles from 2023-04-01 for every listed market (the two venues fetched in parallel — they
# are different hosts with their own limits), the ingest to one parquet a venue, the audit against the archive klines (cover per block, the
# stamp's alignment, the premium raw / adjusted / BTC-relative, the KRW volume share, the serving lag). Nothing registered, no fold read.
#   ./fluxtrader2/scripts/vm.sh bgsh bb1 'bash scripts/bb1_chain.sh'      # log: output/logs/bb1.log
# The steps are named krw_<venue>_<action>, not bb1. The chain's exit arms a poweroff 30 min later.
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
venue() {
  local v="$1"
  step "krw_${v}_markets" python -m ft2 krw markets --venue "$v"
  step "krw_${v}_fetch"   python -m ft2 krw fetch   --venue "$v" --listed-only
  step "krw_${v}_ingest"  python -m ft2 krw ingest  --venue "$v"
  step "krw_${v}_audit"   python -m ft2 krw audit   --venue "$v"
}
venue upbit &
venue bithumb &
wait
echo "$(date -u +%H:%M:%S) BB1_CHAIN_DONE"
