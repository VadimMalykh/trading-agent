#!/usr/bin/env bash
# R62 (docs/PLAN.md §8): the Coinbase premium's deviation at breadth — the screener's F1+F2 members, the universe frozen in
# ft2/cb_members_r62.csv. Validity first (R60's frame reproduced on the twelve in the same run; known-at; membership; per-block coverage;
# the list's md5), then the registered feature on the kept members' cells, both nulls at 200 draws, the family of two, the gate at 1d with
# the twelve's maker bar as a number. F1+F2 only; no confirmation fold is read; the twelve's parquet is read, never written (md5 before
# and after). Serial on the work VM:
#   ./fluxtrader2/scripts/vm.sh bgsh r62 'bash scripts/r62_chain.sh'      # log: output/logs/r62.log
# The chain's exit arms a poweroff 30 min later.
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
echo "$(date -u +%H:%M:%S) list md5: $(md5sum ft2/cb_members_r62.csv)"
echo "$(date -u +%H:%M:%S) twelve's parquet before: $(md5sum data/coinbase_1h.parquet)"
FT2_JOBS=2 step r62 python -m ft2 ceiling --target pairs --family coinbase --universe members --draws 200
echo "$(date -u +%H:%M:%S) twelve's parquet after:  $(md5sum data/coinbase_1h.parquet)"
echo "$(date -u +%H:%M:%S) R62_CHAIN_DONE"
