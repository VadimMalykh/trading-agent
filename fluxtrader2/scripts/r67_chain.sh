#!/usr/bin/env bash
# R67 (docs/PLAN.md §8, decision BG's BG1, registered 2026-10-22): the Coinbase deviation cbprem_dev at a 3- and 7-day hold on the members'
# F1+F2 cells — R62's frame and list, the gate's bar the twelve's maker bar at each hold from the run's own |move|, p_family ≤ 0.025. The run
# checks the lists, reproduces R62's saved screen rows through the extended path, recomputes 2,000 long labels by hand, checks the bar code at
# 1d, known-at, membership and coverage FIRST; BG2's description (R61's money shape on the members) inside the same run.
#   ./fluxtrader2/scripts/vm.sh bgsh r67 'bash scripts/r67_chain.sh'      # log: output/logs/r67.log
# The step is named r67_run, not r67 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
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
echo "$(date -u +%H:%M:%S) R62's saved screen: $(md5sum output/ceiling_coinbase_members/screen.parquet)"
echo "$(date -u +%H:%M:%S) R60's saved bars: $(md5sum output/ceiling_coinbase/move_vs_cost.parquet)"
echo "$(date -u +%H:%M:%S) source: $(md5sum data/coinbase_1h_members.parquet | cut -c1-32)"
FT2_JOBS=2 step r67_run python -m ft2 ceiling --target pairs --family hold --universe members --draws 200
echo "$(date -u +%H:%M:%S) R62's saved screen after: $(md5sum output/ceiling_coinbase_members/screen.parquet)"
echo "$(date -u +%H:%M:%S) R60's saved bars after: $(md5sum output/ceiling_coinbase/move_vs_cost.parquet)"
echo "$(date -u +%H:%M:%S) R67_CHAIN_DONE"
