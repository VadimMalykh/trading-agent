#!/usr/bin/env bash
# Decision BU1, the third step (2026-11-01, after the first audit found 25 of the 116 F3+F4 events without bars — the slice's non-member names
# end at 2024-08 — and 42 of the 71 shortenings without a cost row on day 0): the F3+F4 events' missing monthly 5m klines fetched and the
# slice re-ingested whole under krlist's fingerprint (R28's route), `costwide` recomputed for every name from 2023-01-01 (the pooled fit is
# the twelve's tape days — the old rows must come back to the digit, checked by scripts/costwide_check.py), then the audit again.
# F5's 2026 months are decision BV's own fetch. Nothing after t0 is read.
#   ./fluxtrader2/scripts/vm.sh bgsh bu1b 'bash scripts/bu1_fetch.sh'     # log: output/logs/bu1b.log
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
FILES="ft2/fundfreq_f34.csv ft2/fundfreq_f5.csv ft2/screen_members.csv ft2/screen_members_f34.csv data/funding_archive.parquet"
echo "md5 before: $(md5sum $FILES | tr '\n' ' ')"
echo "slice before: $(md5sum data/candles_5m_archive.parquet data/cost_daily_wide.parquet | tr '\n' ' ')"
cp -n data/cost_daily_wide.parquet data/cost_daily_wide_before_bu1.parquet
step fundfreq_bars_fetch python -m ft2 fundfreq bars --fetch
step costwide_all        python -m ft2 costwide --universe all --start 2023-01-01
step costwide_check      python scripts/costwide_check.py data/cost_daily_wide_before_bu1.parquet data/cost_daily_wide.parquet
rm -f output/logs/fundfreq_audit.done
step fundfreq_audit2     python -m ft2 fundfreq audit
echo "md5 after:  $(md5sum $FILES | tr '\n' ' ')"
echo "slice after:  $(md5sum data/candles_5m_archive.parquet data/cost_daily_wide.parquet | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) BU1_FETCH_DONE"
