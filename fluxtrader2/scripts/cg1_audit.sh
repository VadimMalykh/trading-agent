#!/usr/bin/env bash
# Decision CG1 (i), the second half: after ft2/govvotes_f12.csv / _f34.csv are frozen and committed (and pushed by vm.sh), count the event
# names' bars (the F1+F2 events' missing months fetched, the slice re-ingested under krlist's fingerprint) and write the audit.
#   ./fluxtrader2/scripts/vm.sh bgsh cg1a 'bash scripts/cg1_audit.sh'
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
FILES="ft2/govvotes_f12.csv ft2/govvotes_f34.csv ft2/screen_members.csv ft2/screen_members_f34.csv data/cost_daily_wide.parquet"
echo "md5 before: $(md5sum $FILES | tr '\n' ' ')"
step govlist_bars  python -u -m ft2 govlist bars --fetch
step govlist_audit python -u -m ft2 govlist audit
echo "md5 after:  $(md5sum $FILES | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) CG1_AUDIT_DONE"
