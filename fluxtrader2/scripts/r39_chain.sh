#!/usr/bin/env bash
# R39 (docs/PLAN.md §8): the maker cost at the trade level on the twelve — the archive's daily aggTrades for 2026-08-15 → 2026-08-28
# (the window with the collector's full ladder for all twelve), then the read. Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r39 'bash scripts/r39_chain.sh'      # log: output/logs/r39.log
# Each step writes output/logs/<step>.log and, when it ends well, output/logs/<step>.done; a done step is not made again (the fetch
# resumes by itself: a file with its .ok is skipped). The read exits 2 on a validity failure — VOID, no marker. `ft2 tape --keep-zip` is
# NOT used: it skips any day whose per-minute part exists, and every day of the window does.
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
TWELVE="BTCUSDT ETHUSDT SOLUSDT XRPUSDT ADAUSDT AVAXUSDT LINKUSDT DOGEUSDT ZECUSDT 1000PEPEUSDT WLDUSDT HYPEUSDT"
START=2026-08-15; END=2026-08-28
df -h ~ | tail -1
ls data/raw/levels/ | sed -n '1p;$p'; ls data/raw/levels | wc -l

# the trades: daily files, sha256-checked, resumable; exit 1 on any failed file → the same command again
step r39_fetch ft2 archive aggTrades --symbols $TWELVE --start $START --end $END
du -sh data/raw/external/binance/aggTrades

# the read (validity first; exit 2 = void)
step r39_read ft2 makercost --start $START --end $END
df -h ~ | tail -1
echo "$(date -u +%H:%M:%S) R39_CHAIN_DONE"
