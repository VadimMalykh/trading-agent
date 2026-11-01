#!/usr/bin/env bash
# Decision BU1, the fourth step (2026-11-01): the `costwide --universe all` re-run of scripts/bu1_fetch.sh was VOID (the parquet it replaced
# held 46,852 rows of 7 names that `all` does not cover — the values on every common row identical to 0.0). Here `costwide` runs on the
# event names alone (the frozen lists' symbols; it writes its parquet whole) and scripts/costwide_merge.py folds those rows into the
# pre-BU1 parquet (every old row kept, the overlap checked to 1e-9); then the audit again. Nothing after t0 is read.
#   ./fluxtrader2/scripts/vm.sh bgsh bu1c 'bash scripts/bu1_cost.sh'      # log: output/logs/bu1c.log
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
FILES="ft2/fundfreq_f34.csv ft2/fundfreq_f5.csv data/funding_archive.parquet data/candles_5m_archive.parquet data/cost_daily_wide_before_bu1.parquet"
echo "md5 before: $(md5sum $FILES | tr '\n' ' ')"
NAMES=$(python - <<'PY'
import pandas as pd
print(" ".join(sorted(set(pd.concat([pd.read_csv("ft2/fundfreq_f34.csv"), pd.read_csv("ft2/fundfreq_f5.csv")])["symbol"]))))
PY
)
echo "event names: $(echo $NAMES | wc -w)"
step costwide_events python -m ft2 costwide --symbols $NAMES --start 2023-01-01
step costwide_merge  python scripts/costwide_merge.py data/cost_daily_wide_before_bu1.parquet data/cost_daily_wide.parquet data/cost_daily_wide.parquet
rm -f output/logs/fundfreq_audit3.done
step fundfreq_audit3 python -m ft2 fundfreq audit
echo "md5 after:  $(md5sum $FILES | tr '\n' ' ')"
echo "cost after: $(md5sum data/cost_daily_wide.parquet)"
echo "$(date -u +%H:%M:%S) BU1_COST_DONE"
