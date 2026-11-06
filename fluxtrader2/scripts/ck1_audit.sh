#!/usr/bin/env bash
# Decision CK1 (iii)/(iv), the second half: after ft2/cexflow_f12.csv / _f34.csv are frozen and committed (and pushed by vm.sh), count the
# event names' bars (the missing months of BOTH lists fetched — the members' months are in the slice; the slice re-ingested under krlist's
# fingerprint) and write the audit. The known-at step compares the raw files on disk (one file → "the second fetch is due").
#   ./fluxtrader2/scripts/vm.sh bgsh ck1a 'bash scripts/ck1_audit.sh'
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
FILES="ft2/cexflow_f12.csv ft2/cexflow_f34.csv ft2/screen_members.csv ft2/screen_members_f34.csv data/cost_daily_wide.parquet"
echo "md5 before: $(md5sum $FILES | tr '\n' ' ')"
step cexflow_bars    python -u -m ft2 cexflow bars --fetch --tags f12 f34 --flag member_at_t0
step cexflow_knownat python -u -m ft2 cexflow knownat
step cexflow_audit   python -u -m ft2 cexflow audit
echo "md5 after:  $(md5sum $FILES | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) CK1_AUDIT_DONE"
