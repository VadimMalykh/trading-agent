#!/usr/bin/env bash
# Decision CD1 (i), the second half: after ft2/upgrades_f12.csv / _f34.csv are frozen and committed (and pushed to the VM by vm.sh), count the
# event names' bars (the F1+F2 events' missing months fetched, the slice re-ingested under krlist's fingerprint) and write the audit.
# Nothing after a t0 is read; nothing is priced.
#   ./fluxtrader2/scripts/vm.sh ssh 'cd ~/fluxtrader2 && source ~/ft2-venv/bin/activate && nohup bash scripts/cd1_audit.sh > output/logs/cd1a.log 2>&1 < /dev/null &'
set -euo pipefail
export PYTHONPATH=.
mkdir -p output/logs
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
FILES="ft2/upgrades_f12.csv ft2/upgrades_f34.csv ft2/screen_members.csv ft2/screen_members_f34.csv data/cost_daily_wide.parquet"
echo "md5 before: $(md5sum $FILES | tr '\n' ' ')"
step upgrades_bars  python -u -m ft2 upgrades bars --fetch
step upgrades_audit python -u -m ft2 upgrades audit
echo "md5 after:  $(md5sum $FILES | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) CD1_AUDIT_DONE"
