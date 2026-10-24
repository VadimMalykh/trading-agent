#!/usr/bin/env bash
# Decision BM1 (docs/PLAN.md P8 decision BM): the Korean LISTING of an existing perpetual as a per-name EVENT — the SOURCE AUDIT, after the
# event lists were frozen (ft2/krlistings_f12.csv, _f34.csv) and committed. The bars of the event names over t0 − 2 d → t0 + 8 d: counted,
# the missing months fetched from the archive's monthly 5m klines and the slice re-ingested whole under a fingerprint (R28's route); then the
# audit (counts, ages, hours, the arriving crowd's volume share). Nothing priced, no fold read, nothing registered.
#   ./fluxtrader2/scripts/vm.sh bgsh bm1 'bash scripts/bm1_chain.sh'      # log: output/logs/bm1.log
# The steps are named krlist_<action>, not bm1. The chain's exit arms a poweroff 30 min later.
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
FILES="ft2/screen_members.csv ft2/screen_members_f34.csv ft2/krlistings_f12.csv ft2/krlistings_f34.csv data/krw_1h_upbit.parquet data/krw_1h_bithumb.parquet data/funding_archive.parquet"
echo "md5 before: $(md5sum $FILES | tr '\n' ' ')"
step krlist_bars  python -m ft2 krlist bars --fetch
step krlist_audit python -m ft2 krlist audit
echo "md5 after:  $(md5sum $FILES | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) BM1_CHAIN_DONE"
