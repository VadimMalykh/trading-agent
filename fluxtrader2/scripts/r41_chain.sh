#!/usr/bin/env bash
# R41 (docs/PLAN.md §8): the funding settlement as a scheduled per-name event — the eleven's premium index fetched (HYPE has no bar in F1+F2),
# the members' rows fingerprinted, `premium.parquet` rebuilt whole with the 199 names, the fingerprint checked (validity (5)), then the read.
# Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r41 'bash scripts/r41_chain.sh'      # log: output/logs/r41.log
# Each step writes output/logs/<step>.log and, when it ends well, output/logs/<step>.done; a done step is not made again. The chain's last
# line arms a poweroff 30 minutes after the end (the R40 lesson: a chain must not leave the VM running); `vm.sh stop` before it is fine.
set -euo pipefail
mkdir -p output/logs
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
ft2() { python -m ft2 "$@"; }
ELEVEN="BTCUSDT ETHUSDT SOLUSDT XRPUSDT ADAUSDT AVAXUSDT LINKUSDT DOGEUSDT ZECUSDT 1000PEPEUSDT WLDUSDT"

step r41_fetch ft2 archive premiumIndexKlines/5m --symbols $ELEVEN --monthly --start 2023-04-01 --end 2024-08-31
step r41_fp_before python scripts/r41_premium_check.py before
step r41_ingest python -c "from ft2 import data; from ft2.__main__ import PAIRS; from ft2.universe import screen_symbols; print(data.ingest_premium([*PAIRS, *screen_symbols()]))"
step r41_fp_after python scripts/r41_premium_check.py after
step r41_read ft2 audit r18_transferbook_1d --family settle --twelve --jobs 4
echo "$(date -u +%H:%M:%S) R41_CHAIN_DONE"
nohup bash -c 'sleep 1800; sudo poweroff' > /dev/null 2>&1 &
