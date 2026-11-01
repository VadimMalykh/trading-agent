#!/usr/bin/env bash
# Decision BW1 (2026-11-01), the Data line — NOTHING READ: the 2026 monthly 5m klines (2026-01 → 2026-09) of the frozen F5 list's names,
# F4's last block (2025-12-29, the hedge basket carried forward) and BTC, fetched from the archive and the slice re-ingested whole under
# krlist's fingerprint (every old name back row for row, or void); the funding archive's newer rows appended (every old row kept, checked);
# `costwide` for these names (it writes its parquet whole) folded into the parquet it replaced by scripts/costwide_merge.py (the overlap
# to 1e-9). The chain's exit arms a poweroff 30 min later.
#   ./fluxtrader2/scripts/vm.sh bgsh bw1 'bash scripts/bw1_fetch.sh'      # log: output/logs/bw1.log
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
FILES="ft2/fundfreq_f34.csv ft2/fundfreq_f5.csv ft2/screen_members_f34.csv"
DATA="data/candles_5m_archive.parquet data/cost_daily_wide.parquet data/funding_archive.parquet"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) data before: $(md5sum $DATA | cut -c1-32 | tr '\n' ' ') sizes $(stat -c %s $DATA | tr '\n' ' ')"
cp -n data/cost_daily_wide.parquet data/cost_daily_wide_before_bw1.parquet
cp -n data/funding_archive.parquet data/funding_archive_before_bw1.parquet
step fundevent_data   python -m ft2 fundevent data
NAMES=$(python -c "from ft2 import fundevent; print(' '.join(fundevent.data_names()['all']))")
echo "$(date -u +%H:%M:%S) names for costwide: $(echo $NAMES | wc -w)"
step costwide_bw1     python -m ft2 costwide --symbols $NAMES --start 2023-01-01
step costwide_merge_bw1 python scripts/costwide_merge.py data/cost_daily_wide_before_bw1.parquet data/cost_daily_wide.parquet data/cost_daily_wide.parquet
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) data after:  $(md5sum $DATA | cut -c1-32 | tr '\n' ' ') sizes $(stat -c %s $DATA | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) BW1_FETCH_DONE"
