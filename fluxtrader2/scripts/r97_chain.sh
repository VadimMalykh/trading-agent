#!/usr/bin/env bash
# R97 (docs/PLAN.md §8, registered 2026-11-15 on Vadim's "CU1 + CU2"): the frozen trees' FILE read backward, ONCE, on the screener's members
# before F1 (2021-12-10 → 2023-04-23): (A) the forecast's IC and (B) R91's rule as a taker (`ft2 allgbm confirmpre`, guarded: (R97, FP) and
# (R97, F0)), then (C) R93's maker on the archive's trades of every name-day holding a leg (`ft2 allbook tapefetch|tape --name r97`).
#   ./fluxtrader2/scripts/vm.sh bgsh r97 'bash scripts/r97_chain.sh'      # log: output/logs/r97.log (launch in the background: bgsh blocks until the chain exits)
# The steps are named pre97_<action>, not r97. The chain's exit arms a poweroff 30 min later.
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
FILES="ft2/screen_members_pre.csv ft2/r89_model.txt data/candles_5m_archive.parquet data/cost_daily_wide.parquet data/funding_archive.parquet"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger: $(wc -l < output/backtest/confirmation_reads.csv) lines, R97 rows $(grep -c ',R97,' output/backtest/confirmation_reads.csv || true); R97 header in PLAN: $(grep -c "^### R97 " docs/PLAN.md); disk $(df -h --output=avail . | tail -1)"
step pre97_confirm python -u -m ft2 allgbm confirmpre
echo "$(date -u +%H:%M:%S) ledger after (A)/(B): $(wc -l < output/backtest/confirmation_reads.csv) lines, R97 rows $(grep -c ',R97,' output/backtest/confirmation_reads.csv || true)"
step pre97_fetch  python -u -m ft2 allbook tapefetch --name r97
step pre97_fetch2 python -u -m ft2 allbook tapefetch --name r97     # a second pass picks up transient errors; verified name-days are skipped
echo "$(date -u +%H:%M:%S) name-days on disk: $(find data/r97_tape -name '*.parquet' | wc -l)"
step pre97_tape   python -u -m ft2 allbook tape --name r97
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R97_CHAIN_DONE"
