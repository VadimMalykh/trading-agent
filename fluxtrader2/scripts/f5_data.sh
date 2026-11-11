#!/usr/bin/env bash
# Decision CO1 (2026-11-11): the Data line for F5's members (ft2/screen_members_f5.csv), then the features-only cover check.
# No label, no forecast, no IC anywhere in this chain (ft2/f5data.py; `ft2 allgbm cover --folds F5`).
#   ./fluxtrader2/scripts/vm.sh bgsh f5line 'bash scripts/f5_data.sh'      # log: output/logs/f5line.log (the job's name differs from the steps')
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
FILES="data/candles_5m_archive.parquet data/funding_archive.parquet data/metrics.parquet data/perp_mix_1h.parquet"
echo "$(date -u +%H:%M:%S) list: $(md5sum ft2/screen_members_f5.csv)"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
for f in funding_archive metrics perp_mix_1h; do cp -n "data/$f.parquet" "data/${f}_before_co1.parquet" || true; done
df -h --output=avail . | tail -1
step f5_klines  python -u -m ft2 f5data klines
step f5_funding python -u -m ft2 f5data funding
step f5_metrics python -u -m ft2 f5data metrics
step f5_mix     python -u -m ft2 f5data mix
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
step f5_cover   python -u -m ft2 allgbm cover --folds F5
echo "$(date -u +%H:%M:%S) F5_DATA_DONE"
