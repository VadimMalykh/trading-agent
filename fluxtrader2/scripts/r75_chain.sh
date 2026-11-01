#!/usr/bin/env bash
# R75 (docs/PLAN.md §8, registered 2026-11-01 on Vadim's "BV1"): the exchange's squeeze flag, bought — LONG the perpetual at the 66 at-floor
# shortenings of its funding-settlement interval on the FROZEN ft2/fundfreq_f34.csv, entered at the close of t0 + 10 min, held 1 / 3 / 7 days
# against the F3+F4 block's members, the funding received in y; F3+F4's FIRST read for the quantity (the guard rows before the funding archive
# and the market are loaded). No fetch: the archive slice's fingerprint before and after; the md5 of the frozen lists, the member list, the
# cost file and the funding slice before and after.
#   ./fluxtrader2/scripts/vm.sh bgsh r75 'bash scripts/r75_chain.sh'      # log: output/logs/r75.log
# The steps are named fundevent_<action>, not r75 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
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
FILES="ft2/fundfreq_f34.csv ft2/fundfreq_f5.csv ft2/screen_members_f34.csv data/cost_daily_wide.parquet data/funding_archive.parquet"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/fundevent.py ft2/fundfreq.py ft2/krevent.py ft2/listing.py ft2/krlist.py ft2/horizon.py ft2/backtest.py | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger before: $(wc -l < output/backtest/confirmation_reads.csv) rows; R75 rows: $(grep -c ',R75,' output/backtest/confirmation_reads.csv || true)"
step fundevent_fingerprint python -m ft2 fundevent fingerprint
step fundevent_run         python -m ft2 fundevent run --registration R75
step fundevent_check       python -m ft2 fundevent check
echo "$(date -u +%H:%M:%S) ledger after: $(wc -l < output/backtest/confirmation_reads.csv) rows; R75 rows: $(grep -c ',R75,' output/backtest/confirmation_reads.csv || true)"
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R75_CHAIN_DONE"
