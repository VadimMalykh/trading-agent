#!/usr/bin/env bash
# R65 (docs/PLAN.md §8, registered 2026-10-22 on Vadim's "BD1"): two under-bar facts as ONE score on the screener's F1+F2 members —
# cbprem_dev (R62) and −bx_1h on the bars where BTC's last completed hour fell (R50 / R63) as the mean of two percentile ranks on R62's
# frame, the family score × 4h / 1d relative, both nulls at 200 draws, the sign POSITIVE, R62's gate; validity (1) R62's saved screen rows
# and (2) R50's reference rows reproduced first; each input alone, the halves, ρ and score3 (the Korean rank) described beside.
#   ./fluxtrader2/scripts/vm.sh bgsh r65 'bash scripts/r65_chain.sh'      # log: output/logs/r65.log
# The step is named r65_run, not r65 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
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
echo "$(date -u +%H:%M:%S) R62's list md5: $(md5sum ft2/cb_members_r62.csv)"
echo "$(date -u +%H:%M:%S) members md5: $(md5sum ft2/screen_members.csv)"
echo "$(date -u +%H:%M:%S) R64's list md5: $(md5sum ft2/krw_members_r64.csv)"
echo "$(date -u +%H:%M:%S) R62's saved screen: $(md5sum output/ceiling_coinbase_members/screen.parquet)"
echo "$(date -u +%H:%M:%S) R50's reference: $(md5sum output/audit/r50_btchour/reference.csv)"
echo "$(date -u +%H:%M:%S) sources: $(md5sum data/coinbase_1h_members.parquet data/krw_1h_bithumb.parquet | cut -c1-32 | tr '\n' ' ')"
FT2_JOBS=2 step r65_run python -m ft2 ceiling --target pairs --family score --universe members --draws 200
echo "$(date -u +%H:%M:%S) R62's saved screen after: $(md5sum output/ceiling_coinbase_members/screen.parquet)"
echo "$(date -u +%H:%M:%S) R50's reference after: $(md5sum output/audit/r50_btchour/reference.csv)"
echo "$(date -u +%H:%M:%S) R65_CHAIN_DONE"
