#!/usr/bin/env bash
# R74 (docs/PLAN.md §8, registered 2026-11-01 on Vadim's "BS1"): the count cell confirmed once on F3+F4's members — R73's mix_cnt24_dev
# (the trailing-day trade count of the perpetual and Binance spot together against its month), relative, 1d, sign NEGATIVE, on R68's kept
# names among the F3+F4 members; R73's 132 saved rows reproduced first; the guard rows (R74, F3) / (R74, F4) before any F3+F4 bar; a
# one-cell family, both nulls at 200 draws; validity (1)–(7) first.
#   ./fluxtrader2/scripts/vm.sh bgsh r74 'bash scripts/r74_chain.sh'      # log: output/logs/r74.log
# The step is named r74_run, not r74 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
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
fp() { python -m ft2 mix fingerprint | tr -d '\n '; }
ledger() { grep -c '^[^,]*,R74,' output/backtest/confirmation_reads.csv || true; }
echo "$(date -u +%H:%M:%S) lists: $(md5sum ft2/spot_members_r68.csv ft2/screen_members_f34.csv ft2/screen_members.csv | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) perp table before: $(fp)"
echo "$(date -u +%H:%M:%S) R73's saved screen: $(md5sum output/ceiling_mix_members/screen.parquet)"
echo "$(date -u +%H:%M:%S) R60's saved bars: $(md5sum output/ceiling_coinbase/move_vs_cost.parquet)"
echo "$(date -u +%H:%M:%S) ledger R74 rows before: $(ledger); R74 header in PLAN: $(grep -c '^### R74 ' docs/PLAN.md)"
echo "$(date -u +%H:%M:%S) sources: $(md5sum data/perp_mix_1h.parquet data/spot_1h.parquet | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/mix_ext.py ft2/mix.py ft2/spot_ext.py ft2/spot.py ft2/cb_ext.py ft2/score_ext.py | cut -c1-32 | tr '\n' ' ')"
FT2_JOBS=2 step r74_run python -m ft2 ceiling --target pairs --family mix --universe members_f34 --draws 200
echo "$(date -u +%H:%M:%S) lists after: $(md5sum ft2/spot_members_r68.csv ft2/screen_members_f34.csv ft2/screen_members.csv | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) perp table after: $(fp)"
echo "$(date -u +%H:%M:%S) ledger R74 rows after: $(ledger)"
echo "$(date -u +%H:%M:%S) after: $(md5sum output/ceiling_mix_members/screen.parquet output/ceiling_coinbase/move_vs_cost.parquet data/perp_mix_1h.parquet data/spot_1h.parquet | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R74_CHAIN_DONE"
