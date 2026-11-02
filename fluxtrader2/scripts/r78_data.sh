#!/usr/bin/env bash
# R78's Data line (docs/PLAN.md §8 R78, decision BZ1, registered 2026-11-02 BEFORE this runs): the F3+F4 episode names' missing monthly 5m
# klines (the audit's data_line_need.f34: 41 names, 78 files) fetched and the slice re-ingested whole under krlist's fingerprint (every old
# name on its old extent back row for row, or void), the funding archive checked and left; then `costwide --symbols` for EVERY name of the
# frozen ft2/fundep_f34.csv from 2023-01-01 (the 41 among them; BU1's route — costwide writes its parquet whole) merged into the parquet it
# replaces by scripts/costwide_merge.py (every old row kept, the overlap to 1e-9); then `fundep audit` again for the counts. Nothing after an
# episode's t0 is joined to anything; no price of a cell is read.
#   ./fluxtrader2/scripts/vm.sh bgsh r78d 'bash scripts/r78_data.sh'      # log: output/logs/r78d.log (launch it in the background: bgsh blocks until the chain exits)
# The steps are named fundevent78_<action> / costwide78_* (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
set -euo pipefail
mkdir -p output/logs output/listing
trap 'nohup bash -c "sleep 1800; sudo poweroff" > /dev/null 2>&1 &' EXIT
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
FILES="ft2/fundep_f12.csv ft2/fundep_f34.csv ft2/fundep_f5.csv ft2/screen_members.csv ft2/screen_members_f34.csv data/funding_archive.parquet"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) slice before: $(md5sum data/candles_5m_archive.parquet data/cost_daily_wide.parquet | cut -c1-32 | tr '\n' ' ')"
cp -n data/cost_daily_wide.parquet data/cost_daily_wide_before_r78.parquet || true
step fundevent78_data python -m ft2 fundevent data --registration R78
NAMES=$(python - <<'PY'
import pandas as pd
print(" ".join(sorted(set(pd.read_csv("ft2/fundep_f34.csv")["symbol"]))))
PY
)
echo "$(date -u +%H:%M:%S) costwide names: $(echo $NAMES | wc -w) (every name of the frozen f34 list)"
step costwide78_events python -m ft2 costwide --symbols $NAMES --start 2023-01-01
step costwide78_merge  python scripts/costwide_merge.py data/cost_daily_wide_before_r78.parquet data/cost_daily_wide.parquet data/cost_daily_wide.parquet
rm -f output/logs/fundep78_audit.done
step fundep78_audit    python -m ft2 fundep audit
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) slice after:  $(md5sum data/candles_5m_archive.parquet data/cost_daily_wide.parquet | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R78_DATA_DONE"
