#!/usr/bin/env bash
# Decision CX1 (PLAN P8, 2026-11-19): the wide names' cost MEASURED against costwide's pooled proxy — the fetch of the frozen
# sample's depth files and tape, then the estimator's calibration on the ladder and the measurement (ft2/cxcost.py). No label.
#   ./fluxtrader2/scripts/vm.sh bgsh cx1chain 'bash scripts/cx1.sh'      # log: output/logs/cx1chain.log (the job's name differs from the steps')
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
echo "$(date -u +%H:%M:%S) sample: $(md5sum ft2/cx1_sample.csv | cut -c1-32); cost rows: $(md5sum data/cost_daily_wide.parquet | cut -c1-32)"
df -h --output=avail . | tail -1; free -g | sed -n 2p
step cx1_fetch python -u -m ft2 cxcost fetch
step cx1_measure python -u -m ft2 cxcost measure
echo "$(date -u +%H:%M:%S) CX1_DONE"
