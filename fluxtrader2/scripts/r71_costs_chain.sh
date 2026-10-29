#!/usr/bin/env bash
# R71's re-execution `costs` (docs/PLAN.md §8 R71, §3): the first read was VOID on validity (5) — 8 of 64 cells had no cost row (the proxy's rows for
# ALT, API3, COMP, CYBER, IOTA, LISTA, YGG end at 2024-08-31; their F3+F4 bars were fetched by BM1 after `costwide` last ran). The cure, costs only:
# `costwide --universe all --start 2021-12-01` on the slice as it stands, every old row unchanged (scripts/r24_check_costwide.py r71), then the
# chain again under --reexecute costs (logged R71/costs beside the first read, which stays). No price move, no label, no trade is touched by costwide.
#   ./fluxtrader2/scripts/vm.sh bgsh r71x 'bash scripts/r71_costs_chain.sh'      # log: output/logs/r71x.log
# The steps are named r71x_<action>. The chain's exit arms a poweroff 30 min later.
set -euo pipefail
mkdir -p output/logs output/listing output/backtest
trap 'nohup bash -c "sleep 1800; sudo poweroff" > /dev/null 2>&1 &' EXIT
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
FILES="ft2/krlistings_f12.csv ft2/krlistings_f34.csv ft2/screen_members.csv ft2/screen_members_f34.csv data/funding_archive.parquet"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES data/cost_daily_wide.parquet | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/krevent.py ft2/listing.py ft2/krlist.py ft2/horizon.py ft2/backtest.py ft2/score_ext.py ft2/cost.py | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger before: $(wc -l < output/backtest/confirmation_reads.csv) rows; R71 rows: $(grep -c ',R71' output/backtest/confirmation_reads.csv || true)"
if [[ ! -e data/cost_daily_wide_before_r71.parquet ]]; then cp data/cost_daily_wide.parquet data/cost_daily_wide_before_r71.parquet; echo "$(date -u +%H:%M:%S) cost file copied to cost_daily_wide_before_r71.parquet"; fi
step r71x_costwide   python -m ft2 costwide --universe all --start 2021-12-01
step r71x_costcheck  python scripts/r24_check_costwide.py r71
echo "$(date -u +%H:%M:%S) cost file after costwide: $(md5sum data/cost_daily_wide.parquet | cut -c1-32); check: $(python -c "import json;print(json.load(open('output/backtest/r71_costwide_check.json'))['status'])")"
step r71x_fingerprint python -m ft2 krevent fingerprint --name r71x
step r71x_recheck     python -m ft2 krevent recheck
step r71x_confirm     python -m ft2 krevent confirm --registration R71 --reexecute costs --name r71x
step r71x_check       python -m ft2 krevent check --name r71x
echo "$(date -u +%H:%M:%S) ledger after: $(wc -l < output/backtest/confirmation_reads.csv) rows; R71 rows: $(grep -c ',R71' output/backtest/confirmation_reads.csv || true)"
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES data/cost_daily_wide.parquet | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R71X_CHAIN_DONE"
