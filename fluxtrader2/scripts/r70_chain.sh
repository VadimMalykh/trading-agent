#!/usr/bin/env bash
# R70 (docs/PLAN.md §8, registered 2026-10-29 on Vadim's "BN2"): the Korean listing of an existing perpetual, sold from the close of its
# first KRW hour, held 1 / 3 / 7 days against the block's members on the FROZEN ft2/krlistings_f12.csv (52 events, every one the gate's
# cell); the sign NEGATIVE; R28's frame. No fetch: the archive slice's fingerprint before and after the run (validity (1)), the md5 of
# the lists, the member list and the cost file before and after.
#   ./fluxtrader2/scripts/vm.sh bgsh r70 'bash scripts/r70_chain.sh'      # log: output/logs/r70.log
# The steps are named r70_<action>, not r70 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
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
FILES="ft2/krlistings_f12.csv ft2/krlistings_f34.csv ft2/screen_members.csv data/cost_daily_wide.parquet data/funding_archive.parquet"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/krevent.py ft2/listing.py ft2/krlist.py ft2/horizon.py ft2/backtest.py | cut -c1-32 | tr '\n' ' ')"
step r70_fingerprint python -m ft2 krevent fingerprint
step r70_run         python -m ft2 krevent run
step r70_check       python -m ft2 krevent check
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R70_CHAIN_DONE"
