#!/usr/bin/env bash
# R64 (docs/PLAN.md §8, registered 2026-10-21 on Vadim's "BC1"): the Korean premium at breadth — R62's screen on Bithumb's BTC-relative
# premium on the screener's F1+F2 members, the sign POSITIVE, the family krprem_dev × 4h / 1d, both nulls at 200 draws; validity (1)
# reproduces R62's saved screen rows through the new source path first; the overlap with the Coinbase deviation described beside.
#   ./fluxtrader2/scripts/vm.sh bgsh r64 'bash scripts/r64_chain.sh'      # log: output/logs/r64.log
# The step is named r64_run, not r64 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
set -euo pipefail
mkdir -p output/logs
trap 'nohup bash -c "sleep 1800; sudo poweroff" > /dev/null 2>&1 &' EXIT
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
echo "$(date -u +%H:%M:%S) list md5: $(md5sum ft2/krw_members_r64.csv)"
echo "$(date -u +%H:%M:%S) R62's list md5: $(md5sum ft2/cb_members_r62.csv)"
echo "$(date -u +%H:%M:%S) R62's saved screen: $(md5sum output/ceiling_coinbase_members/screen.parquet)"
echo "$(date -u +%H:%M:%S) sources: $(md5sum data/krw_1h_bithumb.parquet data/krw_1h_upbit.parquet data/coinbase_1h_members.parquet | cut -c1-32 | tr '\n' ' ')"
FT2_JOBS=2 step r64_run python -m ft2 ceiling --target pairs --family krw --universe members --draws 200
echo "$(date -u +%H:%M:%S) R62's saved screen after: $(md5sum output/ceiling_coinbase_members/screen.parquet)"
echo "$(date -u +%H:%M:%S) R64_CHAIN_DONE"
