#!/usr/bin/env bash
# R81 (docs/PLAN.md §8, registered 2026-11-04 on Vadim's "CE1", after the F3+F4 Data line scripts/ce1_data.sh): the CONFIRMATION read of R80's
# candidate on the FROZEN ft2/upgrades_f34.csv (105 rows; ETH's two and ADA's Plomin row described, ADA's Chang row before the members' first
# block: 101 cells) — the name SOLD at the first 5m bar closing after the exchange's stated hour, held ONE day against the F3+F4 block's members;
# the gate on the 10 % TRIMMED mean of that hold alone; the guard rows (R81, F3) / (R81, F4) in the ledger BEFORE the market is loaded; the money
# row through the harness hedged with the members. No fetch: the archive slice's fingerprint before and after; the md5 of the frozen lists, the
# member lists and the cost file before and after; the ledger's line count before and after (+ 2).
#   ./fluxtrader2/scripts/vm.sh bgsh r81 'bash scripts/r81_chain.sh'      # log: output/logs/r81.log (launch it in the background: bgsh blocks until the chain exits)
# The steps are named upgevent81_<action>, not r81 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff
# 30 min later.
set -euo pipefail
mkdir -p output/logs output/listing
trap 'nohup bash -c "sleep 1800; sudo poweroff" > /dev/null 2>&1 &' EXIT
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
FILES="ft2/upgrades_f12.csv ft2/upgrades_f34.csv ft2/screen_members.csv ft2/screen_members_f34.csv data/cost_daily_wide.parquet"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/upgevent.py ft2/upgrades.py ft2/krevent.py ft2/fundevent.py ft2/listing.py ft2/krlist.py ft2/horizon.py ft2/backtest.py | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger lines before: $(wc -l < output/backtest/confirmation_reads.csv)"
step upgevent81_fingerprint python -m ft2 upgevent fingerprint --name r81
step upgevent81_run         python -m ft2 upgevent run --name r81
step upgevent81_check       python -m ft2 upgevent check --name r81
echo "$(date -u +%H:%M:%S) ledger lines after:  $(wc -l < output/backtest/confirmation_reads.csv)"
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R81_CHAIN_DONE"
