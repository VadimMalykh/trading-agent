#!/usr/bin/env bash
# R94 (docs/PLAN.md §8, registered 2026-11-13 on Vadim's "CM1"): the confirmation read of the exchange-balance kind on the FROZEN
# ft2/cexflow_f34.csv's members' cells, BOTH sides (336 rows; MATIC's six out by name, four at the calendar's end: 326 cells) — each SOLD at
# the first 5m bar closing after t0 + 6 h, held THREE DAYS (hindsight-generated on R85's described rows) against the F3+F4 block's members
# (1 day described); the gate on the 10 % TRIMMED mean of the 3-day hold alone with both folds AND both sides negative; the checks that read
# no bar BEFORE the guard rows (R94, F3) / (R94, F4); the money row described. No fetch: the archive slice's fingerprint before and after;
# the md5 of the frozen lists, the member lists and the cost file before and after; the ledger's line count before and after (+2).
#   ./fluxtrader2/scripts/vm.sh bgsh r94 'bash scripts/r94_chain.sh'      # log: output/logs/r94.log (launch it in the background: bgsh blocks until the chain exits)
# The steps are named cexevent94_<action>, not r94 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff
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
FILES="ft2/cexflow_f12.csv ft2/cexflow_f34.csv ft2/cexflow_f5.csv ft2/screen_members.csv ft2/screen_members_f34.csv data/cost_daily_wide.parquet"
LEDGER=output/backtest/confirmation_reads.csv
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger before: $(wc -l < $LEDGER) lines; R94 rows $(grep -c ',R94,' $LEDGER || true); R94 header in PLAN: $(grep -c '^### R94 ' docs/PLAN.md)"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/cexevent.py ft2/cexflow.py ft2/govevent.py ft2/upgevent.py ft2/krevent.py ft2/fundevent.py ft2/listing.py ft2/krlist.py ft2/horizon.py ft2/backtest.py | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) gate (b) LAG_H = $(python -c 'import ft2.cexevent as c; print(c.LAG_H)') h — R85's Gate (b) line"
echo "$(date -u +%H:%M:%S) gate (a) knownat: $(python -c 'import json; k=json.load(open("output/cexflow/knownat.json")); print(k["verdict"][:40], "|", k["files"][-1], "| differ", k["differ"])')"
step cexevent94_fingerprint python -m ft2 cexevent fingerprint --name r94
step cexevent94_run         python -m ft2 cexevent run --name r94
step cexevent94_check       python -m ft2 cexevent check --name r94
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger after: $(wc -l < $LEDGER) lines"
echo "$(date -u +%H:%M:%S) R94_CHAIN_DONE"
