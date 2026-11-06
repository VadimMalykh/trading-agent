#!/usr/bin/env bash
# R83 (docs/PLAN.md §8, registered 2026-11-06 on Vadim's "CH1"): the END of a name's governance vote on Snapshot — the name SOLD at the first 5m
# bar closing after the vote closes on the FROZEN ft2/govvotes_f12.csv's ≥ 200-voter cells (334 rows; three early-May ends before the first member
# block and AAVE 2024-08-31 by the calendar: 330 cells), held 1 day against the F1+F2 block's members (3 days described); the gate on the 10 %
# TRIMMED mean of the 1-day hold alone; the whole-vote cells described through the same functions. No fetch: the archive slice's fingerprint
# before and after; the md5 of the frozen lists, the member lists and the cost file before and after.
#   ./fluxtrader2/scripts/vm.sh bgsh r83 'bash scripts/r83_chain.sh'      # log: output/logs/r83.log (launch it in the background: bgsh blocks until the chain exits)
# The steps are named govevent83_<action>, not r83 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff
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
FILES="ft2/govvotes_f12.csv ft2/govvotes_f34.csv ft2/screen_members.csv ft2/screen_members_f34.csv data/cost_daily_wide.parquet"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/govevent.py ft2/govlist.py ft2/upgevent.py ft2/krevent.py ft2/fundevent.py ft2/listing.py ft2/krlist.py ft2/horizon.py ft2/backtest.py | cut -c1-32 | tr '\n' ' ')"
step govevent83_fingerprint python -m ft2 govevent fingerprint --name r83
step govevent83_run         python -m ft2 govevent run --name r83
step govevent83_check       python -m ft2 govevent check --name r83
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R83_CHAIN_DONE"
