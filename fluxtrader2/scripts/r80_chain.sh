#!/usr/bin/env bash
# R80 (docs/PLAN.md §8, registered 2026-11-04 on Vadim's "CD1"): the scheduled network upgrade of a name SOLD at the first 5m bar closing after
# the exchange's stated hour on the FROZEN ft2/upgrades_f12.csv (93 rows; ETH's row described, KLAY 2024-08-29 by the calendar: 91 cells),
# held 1 / 3 / 7 days against the F1+F2 block's members; the gate on the 10 % TRIMMED mean. No fetch: the archive slice's fingerprint before
# and after; the md5 of the frozen lists, the member lists and the cost file before and after.
#   ./fluxtrader2/scripts/vm.sh bgsh r80 'bash scripts/r80_chain.sh'      # log: output/logs/r80.log (launch it in the background: bgsh blocks until the chain exits)
# The steps are named upgevent80_<action>, not r80 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff
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
step upgevent80_fingerprint python -m ft2 upgevent fingerprint --name r80
step upgevent80_run         python -m ft2 upgevent run --name r80
step upgevent80_check       python -m ft2 upgevent check --name r80
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R80_CHAIN_DONE"
