#!/usr/bin/env bash
# R77 (docs/PLAN.md §8, registered 2026-11-02 on Vadim's "BY1 at 2 %"): the extreme-funding EPISODE bought WITHOUT the exchange's flag — LONG
# the perpetual at the first settlement past 2 % a day on the FROZEN ft2/fundep_f12.csv (60 cells, 58 expected), entered at the close of
# t0 + 10 min, held 1 / 3 / 7 days against the F1+F2 block's members, the funding received in y; the GATE on the 10 % TRIMMED mean; no guard
# (the exploration folds). No fetch: the archive slice's fingerprint before and after; the md5 of the frozen lists, the member list, the cost
# file and the funding slice before and after.
#   ./fluxtrader2/scripts/vm.sh bgsh r77 'bash scripts/r77_chain.sh'      # log: output/logs/r77.log (launch it in the background: bgsh blocks until the chain exits)
# The steps are named fundevent77_<action>, not r77 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
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
FILES="ft2/fundep_f12.csv ft2/fundep_f34.csv ft2/fundep_f5.csv ft2/screen_members.csv data/cost_daily_wide.parquet data/funding_archive.parquet"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/fundevent.py ft2/fundep.py ft2/fundfreq.py ft2/krevent.py ft2/listing.py ft2/horizon.py ft2/backtest.py | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger before: $(wc -l < output/backtest/confirmation_reads.csv) rows; R77 rows: $(grep -c ',R77,' output/backtest/confirmation_reads.csv || true)"
step fundevent77_fingerprint python -m ft2 fundevent fingerprint --name r77
step fundevent77_run         python -m ft2 fundevent run --registration R77
step fundevent77_check       python -m ft2 fundevent check --name r77
echo "$(date -u +%H:%M:%S) ledger after: $(wc -l < output/backtest/confirmation_reads.csv) rows; R77 rows: $(grep -c ',R77,' output/backtest/confirmation_reads.csv || true)"
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R77_CHAIN_DONE"
