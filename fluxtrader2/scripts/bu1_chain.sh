#!/usr/bin/env bash
# Decision BU1 (docs/PLAN.md P8 decision BU): the funding-settlement-frequency CHANGE of a running perpetual as a per-name RULE event — the
# SOURCE AUDIT. Step 1 (`fundfreq_notices`) fetches catalog 49's "Settlement Frequency" / "Funding Rate" detail pages (cached under
# data/raw/external/binance_cms/detail/); step 2 (`fundfreq_events`) writes every interval change with its flags and the lists to freeze
# (output/fundfreq/events.csv, fundfreq_f34.csv, fundfreq_f5.csv). The chain STOPS there: the lists are frozen by hand as
# ft2/fundfreq_f34.csv / _f5.csv and committed before `bars` and `audit` run (scripts/bu1_audit.sh). Nothing after t0 is read.
#   ./fluxtrader2/scripts/vm.sh bgsh bu1 'bash scripts/bu1_chain.sh'      # log: output/logs/bu1.log
# The steps are named fundfreq_<action>, not bu1. The chain's exit arms a poweroff 30 min later.
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
FILES="ft2/screen_members.csv ft2/screen_members_f34.csv data/funding_archive.parquet data/candles_5m_archive.parquet data/cost_daily_wide.parquet"
echo "md5 before: $(md5sum $FILES | tr '\n' ' ')"
step fundfreq_notices python -m ft2 fundfreq notices --fetch
step fundfreq_events  python -m ft2 fundfreq events
echo "md5 after:  $(md5sum $FILES | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) BU1_CHAIN_DONE"
