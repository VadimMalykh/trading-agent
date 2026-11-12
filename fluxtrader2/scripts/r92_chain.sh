#!/usr/bin/env bash
# R92 (docs/PLAN.md §8): the maker at the TRADE level on R90's book — the archive's aggTrades for every name-day holding a leg
# (7,184), the legs' fates written and each zip deleted, then the guarded read ONCE (`ft2 allbook tape`).
#   ./fluxtrader2/scripts/vm.sh bgsh tape92 'bash scripts/r92_chain.sh'      # log: output/logs/tape92.log (the job's name differs from the steps')
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

echo "$(date -u +%H:%M:%S) fills: $(md5sum output/allbook/r90/fills.parquet); disk: $(df -h --output=avail . | tail -1)"
echo "$(date -u +%H:%M:%S) ledger R92 rows before: $(grep -c ',R92,' output/backtest/confirmation_reads.csv || true); R92 header in PLAN: $(grep -c "^### R92 " docs/PLAN.md)"
step r92_fetch python -u -m ft2 allbook tapefetch
step r92_fetch2 python -u -m ft2 allbook tapefetch          # a second pass picks up transient errors; verified name-days are skipped
echo "$(date -u +%H:%M:%S) name-days on disk: $(find data/r92_tape -name '*.parquet' | wc -l)"
step r92_read python -u -m ft2 allbook tape
echo "$(date -u +%H:%M:%S) ledger R92 rows after: $(grep -c ',R92,' output/backtest/confirmation_reads.csv || true)"
echo "$(date -u +%H:%M:%S) R92_CHAIN_DONE"
