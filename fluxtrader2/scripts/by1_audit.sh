#!/usr/bin/env bash
# Decision BY1 (2026-11-02), the second half: after ft2/fundep_f12.csv / _f34.csv / _f5.csv are FROZEN and committed (and pushed by vm.sh bgsh),
# the audit — the frozen lists' counts, the eligibility rule on the F1+F2 list in R75's frame (every dropped cell named), the F3+F4 / F5 bars
# a Data line would fetch. Nothing after a t0 is read; nothing priced. The chain's exit arms a poweroff 30 min later.
#   ./fluxtrader2/scripts/vm.sh bgsh by1a 'bash scripts/by1_audit.sh'     # log: output/logs/by1a.log
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
FILES="ft2/fundep_f12.csv ft2/fundep_f34.csv ft2/fundep_f5.csv data/funding_archive.parquet data/candles_5m_archive.parquet data/cost_daily_wide.parquet ft2/screen_members.csv ft2/screen_members_f34.csv"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) frozen vs written: $(cmp -s ft2/fundep_f12.csv output/fundep/fundep_f12.csv && echo f12-same || echo f12-DIFFER) $(cmp -s ft2/fundep_f34.csv output/fundep/fundep_f34.csv && echo f34-same || echo f34-DIFFER) $(cmp -s ft2/fundep_f5.csv output/fundep/fundep_f5.csv && echo f5-same || echo f5-DIFFER)"
step fundep_audit python -m ft2 fundep audit
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) BY1_AUDIT_DONE"
