#!/usr/bin/env bash
# Decision BY1 (2026-11-02), the first half: the episodes at ≥ 2 % a day listed from funding_archive with their flags, the lists per fold pair
# written to output/fundep/ (fundep_f12.csv / _f34.csv / _f5.csv) — pulled, FROZEN by hand into ft2/ and committed before scripts/by1_audit.sh.
# Nothing after a t0 is read; nothing priced. No poweroff: the audit follows within the hour.
#   ./fluxtrader2/scripts/vm.sh bgsh by1e 'bash scripts/by1_events.sh'     # log: output/logs/by1e.log
set -euo pipefail
mkdir -p output/logs
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
FILES="data/funding_archive.parquet data/candles_5m_archive.parquet data/cost_daily_wide.parquet ft2/screen_members.csv ft2/screen_members_f34.csv"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/fundep.py ft2/fundfreq.py | cut -c1-32 | tr '\n' ' ')"
step fundep_events python -m ft2 fundep events --threshold 0.02
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) lists: $(md5sum output/fundep/fundep_f12.csv output/fundep/fundep_f34.csv output/fundep/fundep_f5.csv | cut -c1-32 | tr '\n' ' ') rows $(wc -l < output/fundep/fundep_f12.csv) $(wc -l < output/fundep/fundep_f34.csv) $(wc -l < output/fundep/fundep_f5.csv)"
echo "$(date -u +%H:%M:%S) BY1_EVENTS_DONE"
