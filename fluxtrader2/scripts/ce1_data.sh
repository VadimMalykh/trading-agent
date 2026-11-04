#!/usr/bin/env bash
# Decision CE1 (i) (docs/PLAN.md P8 decision CE, 2026-11-04): the F3+F4 Data line of the upgrade family, NOTHING PRICED — the 42 F3+F4 event
# windows without bars (the non-member names' months) fetched from the archive's monthly 5m klines and the slice re-ingested whole under
# krlist's fingerprint (a hole fill inside a name's old extent fails the extent rule and is decided by R78's row check, scripts/cd1_rowcheck.py);
# the bars counted again; `costwide --symbols` for EVERY name of the frozen ft2/upgrades_f34.csv from 2023-01-01 (R78's route — costwide writes
# its parquet whole) merged into the parquet it replaces by scripts/costwide_merge.py (every old row kept, the overlap to 1e-9); `upgrades audit`
# again for the counts. No bar after a t0 is joined to a label; no price of a cell is read. The frozen lists are not touched.
#   ./fluxtrader2/scripts/vm.sh bgsh ce1d 'bash scripts/ce1_data.sh'      # log: output/logs/ce1d.log (launch it in the background: bgsh blocks until the chain exits)
# The steps are named upgrades_*_f34 / costwide81_* (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
set -euo pipefail
export PYTHONPATH=.
mkdir -p output/logs output/upgrades
trap 'nohup bash -c "sleep 1800; sudo poweroff" > /dev/null 2>&1 &' EXIT
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
FILES="ft2/upgrades_f12.csv ft2/upgrades_f34.csv ft2/screen_members.csv ft2/screen_members_f34.csv"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) slice before: $(md5sum data/candles_5m_archive.parquet data/cost_daily_wide.parquet | cut -c1-32 | tr '\n' ' ')"
cp -n data/cost_daily_wide.parquet data/cost_daily_wide_before_ce1.parquet || true
step upgrades_bars_f34     python -u -m ft2 upgrades bars --fetch --tags f34 || echo "$(date -u +%H:%M:%S) upgrades_bars_f34 exited non-zero (the extent fingerprint, if it is that) → the row check decides"
step upgrades_rowcheck_f34 python -u scripts/cd1_rowcheck.py output/logs/upgrades_bars_f34.log
cp output/logs/upgrades_rowcheck_f34.log output/upgrades/rowcheck_f34.json
step upgrades_count_f34    python -u -m ft2 upgrades bars
NAMES=$(python - <<'PY'
import pandas as pd
print(" ".join(sorted(set(pd.read_csv("ft2/upgrades_f34.csv")["symbol"]))))
PY
)
echo "$(date -u +%H:%M:%S) costwide names: $(echo $NAMES | wc -w) (every name of the frozen f34 list; the twelve's take their own file)"
step costwide81_events python -u -m ft2 costwide --symbols $NAMES --start 2023-01-01
step costwide81_merge  python -u scripts/costwide_merge.py data/cost_daily_wide_before_ce1.parquet data/cost_daily_wide.parquet data/cost_daily_wide.parquet
rm -f output/logs/upgrades_audit.done
step upgrades_audit    python -u -m ft2 upgrades audit
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) slice after:  $(md5sum data/candles_5m_archive.parquet data/cost_daily_wide.parquet | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) CE1_DATA_DONE"
