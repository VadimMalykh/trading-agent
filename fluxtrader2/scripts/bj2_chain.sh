#!/usr/bin/env bash
# Decision BJ2 (docs/PLAN.md P8): Hyperliquid's hourly funding and mark premium per member — the SOURCE AUDIT. The venue's public info
# API (free, keyless; one row a settlement: the premium and the rate) for the twelve's and the screener's members' coins, 2023-04 → F5's
# end; Binance's own 1h premium index from the archive beside it (the stamp check, the "same quantity?" question); the ingest to one
# parquet each; the audit (coverage, the hourly regime, the member cover per block, the stamp and funding checks, the quantities' level /
# sd / persistence / hour of day, the deviations' correlation with Binance's premium deviation, cbprem_dev and R68's two on R62's kept
# names). Nothing registered, no fold read.
#   ./fluxtrader2/scripts/vm.sh bgsh bj2 'bash scripts/bj2_chain.sh'      # log: output/logs/bj2.log
# The steps are named hl_<action>, not bj2. The chain's exit arms a poweroff 30 min later.
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
FILES="ft2/screen_members.csv ft2/screen_members_f34.csv ft2/cb_members_r62.csv output/coinbase_members_premium.parquet output/spot_ratios.parquet data/funding_archive.parquet"
echo "md5 before: $(md5sum $FILES | tr '\n' ' ')"
step hl_symbols python -m ft2 hl symbols
step hl_fetch   python -m ft2 hl fetch
step hl_bnprem  python -m ft2 hl bnprem
step hl_ingest  python -m ft2 hl ingest
step hl_audit   python -m ft2 hl audit
echo "md5 after:  $(md5sum $FILES | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) BJ2_CHAIN_DONE"
