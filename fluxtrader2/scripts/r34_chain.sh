#!/usr/bin/env bash
# R34 (docs/PLAN.md §8): the breadth step — the archive's bookDepth for the 32 names of R10's forty the collector never recorded
# (ft2.universe.NEW), 2023-04-01 → 2024-08-31, ingested per name, then R33's screen on them. Serial on the work VM, in the venv,
# from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r34 'bash scripts/r34_chain.sh'      # log: output/logs/r34.log
# Each step writes output/logs/<step>.log and, when it ends well, output/logs/<step>.done; a done step is not made again, so the
# chain can be started again after a failure (the fetch resumes by itself: a file with its .ok is skipped). The twelve's depth
# parquets must come back unchanged: their md5 is taken before the fetch and compared after the ingest (a difference fails the
# chain before the screen). The screen exits 2 on a validity failure — the read is then VOID and the step is not marked done.
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
NEW="GMTUSDT APEUSDT BNBUSDT NEARUSDT FTMUSDT SANDUSDT MATICUSDT DOTUSDT WAVESUSDT 1000SHIBUSDT GALAUSDT ETCUSDT AXSUSDT ATOMUSDT LTCUSDT TRXUSDT MANAUSDT AAVEUSDT CRVUSDT UNFIUSDT PEOPLEUSDT RUNEUSDT DYDXUSDT BCHUSDT FILUSDT EOSUSDT ZILUSDT THETAUSDT ENSUSDT UNIUSDT ALICEUSDT OGNUSDT"
TWELVE="BTCUSDT ETHUSDT SOLUSDT XRPUSDT ADAUSDT AVAXUSDT LINKUSDT DOGEUSDT ZECUSDT 1000PEPEUSDT WLDUSDT HYPEUSDT"
md5_twelve() { for s in $TWELVE; do [[ -e "data/depth/$s.parquet" ]] && md5sum "data/depth/$s.parquet"; done; }

# the twelve's depth files, as they are before anything is fetched
step r34_md5_before bash -c 'for s in '"$TWELVE"'; do [[ -e "data/depth/$s.parquet" ]] && md5sum "data/depth/$s.parquet"; done > output/logs/r34_md5_before.txt; wc -l output/logs/r34_md5_before.txt'

# the fetch: daily files, sha256-checked, resumable; exit 1 on any failed file → the same command again
step r34_fetch ft2 archive bookDepth --symbols $NEW --start 2023-04-01 --end 2024-08-31

# the ingest: one parquet per name from that name's own zips; the twelve are not named, so their files are not touched
step r34_ingest ft2 ingest depth --symbols $NEW

# the twelve's files after: identical, or the chain stops here
step r34_md5_after bash -c 'for s in '"$TWELVE"'; do [[ -e "data/depth/$s.parquet" ]] && md5sum "data/depth/$s.parquet"; done > output/logs/r34_md5_after.txt; diff output/logs/r34_md5_before.txt output/logs/r34_md5_after.txt && echo "the twelve'"'"'s depth files are unchanged"'

# the screen on the 32 (validity first: R33's rows on the twelve reproduced in the same run; exit 2 = void)
FT2_JOBS=3 step r34_screen ft2 ceiling --target pairs --family depth --universe new --draws 200
du -sh data/raw/external/binance/bookDepth data/depth; df -h ~ | tail -1
echo "$(date -u +%H:%M:%S) R34_CHAIN_DONE"
