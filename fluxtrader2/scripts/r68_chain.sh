#!/usr/bin/env bash
# R68 (docs/PLAN.md §8, registered 2026-10-22 on Vadim's "BI1"): Binance's own spot flow per member at one day — R62's screen on the
# trailing-day taker-buy share and the trailing-day spot/perp quote-volume ratio, each against its month, on the screener's F1+F2
# members; both signs POSITIVE; the family two cells × 1d; both nulls at 200 draws on each feature; validity (1)–(7) first.
#   ./fluxtrader2/scripts/vm.sh bgsh r68 'bash scripts/r68_chain.sh'      # log: output/logs/r68.log
# The step is named r68_run, not r68 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
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
echo "$(date -u +%H:%M:%S) lists: $(md5sum ft2/spot_members_r68.csv ft2/screen_members.csv ft2/cb_members_r62.csv | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R62's saved screen: $(md5sum output/ceiling_coinbase_members/screen.parquet)"
echo "$(date -u +%H:%M:%S) R60's saved bars: $(md5sum output/ceiling_coinbase/move_vs_cost.parquet)"
echo "$(date -u +%H:%M:%S) sources: $(md5sum data/spot_1h.parquet data/coinbase_1h_members.parquet | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/spot_ext.py ft2/spot.py ft2/cb_ext.py | cut -c1-32 | tr '\n' ' ')"
FT2_JOBS=4 step r68_run python -m ft2 ceiling --target pairs --family spot --universe members --draws 200
echo "$(date -u +%H:%M:%S) after: $(md5sum ft2/spot_members_r68.csv output/ceiling_coinbase_members/screen.parquet output/ceiling_coinbase/move_vs_cost.parquet data/spot_1h.parquet | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R68_CHAIN_DONE"
