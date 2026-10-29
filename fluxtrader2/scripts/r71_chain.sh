#!/usr/bin/env bash
# R71 (docs/PLAN.md §8, registered 2026-10-29 on Vadim's "BO1"): the confirmation read of R70's candidate on the FROZEN ft2/krlistings_f34.csv —
# sold at the close of the bar after the first KRW hour, held 1 day, no stop, priced at the entry day's doubled proxy, hedged with the F3+F4
# block's members, once (the guard rows before the market is loaded). No fetch: the archive slice's fingerprint before and after; the md5 of
# the lists, both member lists, the cost file and the funding slice before and after. `recheck` reproduces R70's pricing first (validity (3)).
#   ./fluxtrader2/scripts/vm.sh bgsh r71 'bash scripts/r71_chain.sh'      # log: output/logs/r71.log
# The steps are named r71_<action>, not r71 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
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
FILES="ft2/krlistings_f12.csv ft2/krlistings_f34.csv ft2/screen_members.csv ft2/screen_members_f34.csv data/cost_daily_wide.parquet data/funding_archive.parquet"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/krevent.py ft2/listing.py ft2/krlist.py ft2/horizon.py ft2/backtest.py ft2/score_ext.py | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger before: $(wc -l < output/backtest/confirmation_reads.csv) rows; R71 rows: $(grep -c ',R71,' output/backtest/confirmation_reads.csv || true)"
step r71_fingerprint python -m ft2 krevent fingerprint --name r71
step r71_recheck     python -m ft2 krevent recheck
step r71_confirm     python -m ft2 krevent confirm --registration R71
step r71_check       python -m ft2 krevent check --name r71
echo "$(date -u +%H:%M:%S) ledger after: $(wc -l < output/backtest/confirmation_reads.csv) rows; R71 rows: $(grep -c ',R71,' output/backtest/confirmation_reads.csv || true)"
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R71_CHAIN_DONE"
