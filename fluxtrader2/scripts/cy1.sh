#!/usr/bin/env bash
# Decision CY1 (PLAN P8, 2026-11-19): the wide names' cost rows refitted on CX1's measurements — the cells again, the check on
# held-out names (a FAIL stops the chain: nothing rebuilt), the rebuild of data/cost_daily_wide.parquet (the old file kept as
# cost_daily_wide_before_cy1.parquet), the re-pricing of R90 / R97 (B) / R100 (B) on their saved fills (ft2/cycost.py). No label.
#   ./fluxtrader2/scripts/vm.sh bgsh cy1chain 'bash scripts/cy1.sh'      # log: output/logs/cy1chain.log (the job's name differs from the steps')
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
echo "$(date -u +%H:%M:%S) sample: $(md5sum ft2/cx1_sample.csv | cut -c1-32); cost rows before: $(md5sum data/cost_daily_wide.parquet | cut -c1-32)"
echo "fills: $(md5sum output/allbook/r90/fills.parquet output/allbook/r97/fills.parquet output/next60/r100/fills_h1_d10_raw.parquet | cut -c1-32 | tr '\n' ' ')"
step cy1_cells   python -u -m ft2 cycost cells
step cy1_check   python -u -m ft2 cycost check
step cy1_rebuild python -u -m ft2 cycost rebuild
step cy1_reexec  python -u -m ft2 cycost reexec
echo "$(date -u +%H:%M:%S) cost rows after: $(md5sum data/cost_daily_wide.parquet | cut -c1-32); CY1_DONE"
