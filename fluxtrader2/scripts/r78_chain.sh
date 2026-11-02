#!/usr/bin/env bash
# R78 (docs/PLAN.md §8, registered 2026-11-02 on Vadim's "BZ1"): the extreme-funding episode SOLD at the crossing and held ONE day on the
# FROZEN ft2/fundep_f34.csv (296 bought-side cells, 294 expected after the calendar), in money — the perpetual sold at t0 + 10 min, the
# entry day's legs doubled, the F3+F4 block's members BOUGHT as the hedge, no stop; the gate on the 10 % TRIMMED mean with the heavy and
# the unflagged clauses; the guard rows (R78, F3) / (R78, F4) before the funding archive and the market are loaded. No fetch: the archive
# slice's fingerprint before and after; the md5 of the frozen lists, the member lists, the cost file and the funding slice before and after.
#   ./fluxtrader2/scripts/vm.sh bgsh r78 'bash scripts/r78_chain.sh'      # log: output/logs/r78.log (launch it in the background: bgsh blocks until the chain exits)
# The steps are named fundevent78_<action>, not r78 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff
# 30 min later. R78_TAG=<tag> runs a re-execution the plan names (logged as R78/<tag>).
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
FILES="ft2/fundep_f12.csv ft2/fundep_f34.csv ft2/fundep_f5.csv ft2/screen_members.csv ft2/screen_members_f34.csv data/cost_daily_wide.parquet data/funding_archive.parquet"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/fundevent.py ft2/fundep.py ft2/fundfreq.py ft2/krevent.py ft2/listing.py ft2/krlist.py ft2/horizon.py ft2/backtest.py | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger before: $(wc -l < output/backtest/confirmation_reads.csv) rows; R78 rows: $(grep -c ',R78' output/backtest/confirmation_reads.csv || true)"
TAG="${R78_TAG:-}"
step fundevent78_fingerprint python -m ft2 fundevent fingerprint --name r78
if [[ -n "$TAG" ]]; then
  step "fundevent78_confirm_$TAG" python -m ft2 fundevent confirm --registration R78 --reexecute "$TAG"
else
  step fundevent78_confirm     python -m ft2 fundevent confirm --registration R78
fi
step fundevent78_check       python -m ft2 fundevent check --name r78
echo "$(date -u +%H:%M:%S) ledger after: $(wc -l < output/backtest/confirmation_reads.csv) rows; R78 rows: $(grep -c ',R78' output/backtest/confirmation_reads.csv || true)"
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R78_CHAIN_DONE"
