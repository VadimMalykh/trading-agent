#!/usr/bin/env bash
# Decision BU1, the second half: after ft2/fundfreq_f34.csv / _f5.csv are frozen and committed (and pushed to the VM by vm.sh), count the
# event names' bars and write the audit. Nothing after t0 is read (the run-up row reads the 24 h BEFORE t0).
#   ./fluxtrader2/scripts/vm.sh bgsh bu1a 'bash scripts/bu1_audit.sh'     # log: output/logs/bu1a.log
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
FILES="ft2/fundfreq_f34.csv ft2/fundfreq_f5.csv ft2/screen_members.csv ft2/screen_members_f34.csv data/funding_archive.parquet data/candles_5m_archive.parquet data/cost_daily_wide.parquet"
echo "md5 before: $(md5sum $FILES | tr '\n' ' ')"
step fundfreq_bars  python -m ft2 fundfreq bars
step fundfreq_audit python -m ft2 fundfreq audit
echo "md5 after:  $(md5sum $FILES | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) BU1_AUDIT_DONE"
