#!/usr/bin/env bash
# R76 (docs/PLAN.md §8, registered 2026-11-01 on Vadim's "BW1"): the confirmation read of R75's candidate on the FROZEN ft2/fundfreq_f5.csv —
# the perpetual BOUGHT at t0 + 10 min at every at-floor shortening of F5 (26 positions), held 7 days, no stop, priced at the entry day's
# doubled proxy, hedged with F4's last block SOLD beside it, once (the guard row (R76, F5) before the funding archive and the market are
# loaded). No fetch: the archive slice's fingerprint before and after; the md5 of the lists, the member list, the cost file and the
# funding slice before and after.
#   ./fluxtrader2/scripts/vm.sh bgsh r76 'bash scripts/r76_chain.sh'      # log: output/logs/r76.log
# The steps are named fundevent_<action>_r76, not r76 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a
# poweroff 30 min later. R76_TAG=<tag> runs a re-execution the plan names (logged as R76/<tag>).
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
echo "$(date -u +%H:%M:%S) ledger before: $(wc -l < output/backtest/confirmation_reads.csv) rows; R76 rows: $(grep -c ',R76' output/backtest/confirmation_reads.csv || true)"
TAG="${R76_TAG:-}"
step fundevent_fingerprint_r76 python -m ft2 fundevent fingerprint --name r76
if [[ -n "$TAG" ]]; then
  step "fundevent_confirm_r76_$TAG" python -m ft2 fundevent confirm --registration R76 --reexecute "$TAG"
else
  step fundevent_confirm_r76     python -m ft2 fundevent confirm --registration R76
fi
step fundevent_check_r76       python -m ft2 fundevent check --name r76
echo "$(date -u +%H:%M:%S) ledger after: $(wc -l < output/backtest/confirmation_reads.csv) rows; R76 rows: $(grep -c ',R76' output/backtest/confirmation_reads.csv || true)"
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R76_CHAIN_DONE"
