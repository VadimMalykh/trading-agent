#!/usr/bin/env bash
# R84 (docs/PLAN.md §8, registered 2026-11-06 on Vadim's "CI2"): the confirmation read of the governance vote's END on the FROZEN
# ft2/govvotes_f34.csv's ≥ 200-voter cells (200 rows on 20 names; GHST 2025-12-30's 3-day exit past F4's end: 199 cells) — the name SOLD at
# the first 5m bar closing after the vote closes, held THREE DAYS (hindsight-generated on R83's described row) against the F3+F4 block's
# members (1 day described); the gate on the 10 % TRIMMED mean of the 3-day hold alone; the guard rows (R84, F3) / (R84, F4) appended to the
# ledger BEFORE the market is loaded; the money row described. No fetch: the archive slice's fingerprint before and after; the md5 of the
# frozen lists, the member lists and the cost file before and after; the ledger's line count before and after (+2).
#   ./fluxtrader2/scripts/vm.sh bgsh r84 'bash scripts/r84_chain.sh'      # log: output/logs/r84.log (launch it in the background: bgsh blocks until the chain exits)
# The steps are named govevent84_<action>, not r84 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff
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
LEDGER=output/backtest/confirmation_reads.csv
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger before: $(wc -l < $LEDGER) lines"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/govevent.py ft2/govlist.py ft2/upgevent.py ft2/krevent.py ft2/fundevent.py ft2/listing.py ft2/krlist.py ft2/horizon.py ft2/backtest.py | cut -c1-32 | tr '\n' ' ')"
step govevent84_fingerprint python -m ft2 govevent fingerprint --name r84
step govevent84_run         python -m ft2 govevent run --name r84
step govevent84_check       python -m ft2 govevent check --name r84
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger after: $(wc -l < $LEDGER) lines"
echo "$(date -u +%H:%M:%S) R84_CHAIN_DONE"
