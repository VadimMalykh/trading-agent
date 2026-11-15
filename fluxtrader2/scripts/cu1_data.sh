#!/usr/bin/env bash
# Decision CU1 (2026-11-15): the Data line for the screener's members BEFORE F1 (ft2/screen_members_pre.csv), then the features-only cover check.
# No label statistic, no forecast, no IC anywhere in this chain (ft2/predata.py; `ft2 allgbm cover --folds PRE`).
#   ./fluxtrader2/scripts/vm.sh bgsh cu1line 'bash scripts/cu1_data.sh'      # log: output/logs/cu1line.log (the job's name differs from the steps')
# The chain's exit (done or failed) arms a poweroff 30 minutes later; kill the `sudo poweroff` wrapper first if another chain follows.
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
FILES="data/candles_5m_archive.parquet data/spot_1h.parquet data/coinbase_1h_members.parquet data/krw_1h_bithumb.parquet"
echo "$(date -u +%H:%M:%S) list: $(md5sum ft2/screen_members_pre.csv)"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
for f in spot_1h coinbase_1h_members krw_1h_bithumb; do cp -n "data/$f.parquet" "data/${f}_before_cu1.parquet" || true; done
df -h --output=avail . | tail -1
step pre_spot     python -u -m ft2 predata spot
step pre_coinbase python -u -m ft2 predata coinbase
step pre_korea    python -u -m ft2 predata korea
step pre_klines   python -u -m ft2 predata klines
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
step pre_cover    python -u -m ft2 allgbm cover --folds PRE
echo "$(date -u +%H:%M:%S) CU1_DATA_DONE"
