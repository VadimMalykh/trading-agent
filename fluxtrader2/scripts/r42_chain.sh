#!/usr/bin/env bash
# R42 (docs/PLAN.md §8): R14 on F5 once, and the pooled row with F3+F4 — then R43's read (scripts/r43_chain.sh's one step) so the VM
# powers off once, at the end. Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r42 'bash scripts/r42_chain.sh'      # log: output/logs/r42.log
# Each step writes output/logs/<step>.log and, when it ends well, output/logs/<step>.done; a done step is not made again. The chain's
# last exit (done or failed) arms a poweroff 30 minutes later (the R40 lesson); `vm.sh stop` before it is fine.
# Steps, as registered: the funding copy → the archive's 2026-09 fundingRate for the twelve → the ingest (the slice rewritten whole) →
# validity (3) → the F1+F2 walk made again (validity (1): R14's decisions) → the F5 read (the guard logs R42, F5) → the pooled row.
set -euo pipefail
mkdir -p output/logs
trap 'nohup bash -c "sleep 1800; sudo poweroff" > /dev/null 2>&1 &' EXIT      # armed on ANY exit, a failure included
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
ft2() { python -m ft2 "$@"; }
TWELVE="BTCUSDT ETHUSDT SOLUSDT XRPUSDT ADAUSDT AVAXUSDT LINKUSDT DOGEUSDT ZECUSDT 1000PEPEUSDT WLDUSDT HYPEUSDT"

step r42_fund_before cp data/funding_archive.parquet data/funding_archive_before_r42.parquet
step r42_fund_fetch ft2 archive fundingRate --symbols $TWELVE --monthly --start 2026-09-01 --end 2026-09-30
step r42_fund_ingest ft2 ingest funding_archive --universe all
step r42_fund_check python scripts/r42_funding_check.py
step r42_check_f12 ft2 backtest ridgebook --param hold=288 --folds F1 F2 --execs taker maker --draws 1 --name r42_check_f12
step r42_same python scripts/r42_same_check.py
step r42_read ft2 backtest ridgebook --param hold=288 --folds F5 --registration R42 --execs taker maker maker_ev maker_trade --name r42_ridgebook_1d_ho12_f5
step r42_pool ft2 pool r16_ridgebook_1d_ho12_f34 r42_ridgebook_1d_ho12_f5 --draws 2000 --name r42_pool --split 2026-05-01
echo "$(date -u +%H:%M:%S) R42_CHAIN_DONE"
FT2_JOBS=4 step r43_read ft2 horizon --mom --holds 4032 8064
echo "$(date -u +%H:%M:%S) R43_CHAIN_DONE"
