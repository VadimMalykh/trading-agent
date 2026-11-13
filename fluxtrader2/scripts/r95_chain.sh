#!/usr/bin/env bash
# R95 (docs/PLAN.md §8, registered 2026-11-13 on Vadim's "CS1"): the NON-EVENT CONTROL of R94 — each of R94's 326 cells against its own name's
# quiet days (no balance move within 3 days on either side) within ±45 days, y at 3 days against the F3+F4 members; D = the trimmed mean of
# the differences; the checks that read no bar (the control table's count 7,933 / 48 names) BEFORE the guard rows (R95, F3) / (R95, F4);
# F1+F2 beside as exploration. No fetch: the fingerprint and the md5s before and after; the ledger +2.
#   ./fluxtrader2/scripts/vm.sh bgsh r95 'bash scripts/r95_chain.sh'      # log: output/logs/r95.log (launch it in the background: bgsh blocks until the chain exits)
# The steps are named cexevent95_<action>, not r95 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff
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
echo "$(date -u +%H:%M:%S) ledger before: $(wc -l < $LEDGER) lines; R95 rows $(grep -c ',R95,' $LEDGER || true); R95 header in PLAN: $(grep -c '^### R95 ' docs/PLAN.md)"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/cexevent.py ft2/cexflow.py ft2/govevent.py ft2/upgevent.py ft2/krevent.py ft2/fundevent.py ft2/listing.py ft2/krlist.py ft2/horizon.py ft2/backtest.py | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) gate (b) LAG_H = $(python -c 'import ft2.cexevent as c; print(c.LAG_H)') h — R85's Gate (b) line"
echo "$(date -u +%H:%M:%S) gate (a) knownat: $(python -c 'import json; k=json.load(open("output/cexflow/knownat.json")); print(k["verdict"][:40], "|", k["files"][-1], "| differ", k["differ"])')"
step cexevent95_fingerprint python -m ft2 cexevent fingerprint --name r95
step cexevent95_control     python -m ft2 cexevent control --name r95
step cexevent95_check       python -m ft2 cexevent check --name r95
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger after: $(wc -l < $LEDGER) lines"
echo "$(date -u +%H:%M:%S) R95_CHAIN_DONE"
