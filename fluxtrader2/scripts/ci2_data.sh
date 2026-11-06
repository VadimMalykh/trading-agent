#!/usr/bin/env bash
# Decision CI2 (i) (docs/PLAN.md P8 decision CI, 2026-11-06): the F3+F4 Data line of the governance kind for R84, NOTHING PRICED — the 65 F3+F4
# `cell_big` windows without bars (the slice's non-member names end 2024-08) fetched from the archive's monthly 5m klines (`--flag cell_big`:
# the whole-vote rows' months stay out, as the handoff scoped it) and the slice re-ingested whole under krlist's fingerprint (a hole fill inside
# a name's old extent fails the extent rule and is decided by R78's row check, scripts/cd1_rowcheck.py); the bars counted again; `costwide
# --symbols` for EVERY name of the frozen ft2/govvotes_f34.csv's `cell_big` rows from 2023-01-01 (costwide writes its parquet whole) merged into
# the parquet it replaces by scripts/costwide_merge.py (every old row kept, the overlap to 1e-9); `govlist audit` again for the counts. No bar
# after an end is joined to a label; no price of a cell is read. The frozen lists are not touched.
#   ./fluxtrader2/scripts/vm.sh bgsh ci2d 'bash scripts/ci2_data.sh'      # log: output/logs/ci2d.log (launch it in the background: bgsh blocks until the chain exits)
# The steps are named govlist_*_f34 / costwide84_* (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
set -euo pipefail
export PYTHONPATH=.
mkdir -p output/logs output/govlist
trap 'nohup bash -c "sleep 1800; sudo poweroff" > /dev/null 2>&1 &' EXIT
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
FILES="ft2/govvotes_f12.csv ft2/govvotes_f34.csv ft2/screen_members.csv ft2/screen_members_f34.csv"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) slice before: $(md5sum data/candles_5m_archive.parquet data/cost_daily_wide.parquet | cut -c1-32 | tr '\n' ' ')"
cp -n data/cost_daily_wide.parquet data/cost_daily_wide_before_ci2.parquet || true
step govlist_bars_f34     python -u -m ft2 govlist bars --fetch --tags f34 --flag cell_big || echo "$(date -u +%H:%M:%S) govlist_bars_f34 exited non-zero (the extent fingerprint, if it is that) → the row check decides"
step govlist_rowcheck_f34 python -u scripts/cd1_rowcheck.py output/logs/govlist_bars_f34.log
cp output/logs/govlist_rowcheck_f34.log output/govlist/rowcheck_f34.json
step govlist_count_f34    python -u -m ft2 govlist bars
NAMES=$(python - <<'PY'
import pandas as pd
L = pd.read_csv("ft2/govvotes_f34.csv")
print(" ".join(sorted(set(L[L["cell_big"].astype(bool)]["symbol"]))))
PY
)
echo "$(date -u +%H:%M:%S) costwide names: $(echo $NAMES | wc -w) (every name of the frozen f34 list's cell_big rows; the twelve's take their own file)"
step costwide84_events python -u -m ft2 costwide --symbols $NAMES --start 2023-01-01
step costwide84_merge  python -u scripts/costwide_merge.py data/cost_daily_wide_before_ci2.parquet data/cost_daily_wide.parquet data/cost_daily_wide.parquet
rm -f output/logs/govlist_audit.done
step govlist_audit    python -u -m ft2 govlist audit
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) slice after:  $(md5sum data/candles_5m_archive.parquet data/cost_daily_wide.parquet | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) CI2_DATA_DONE"
