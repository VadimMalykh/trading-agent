#!/usr/bin/env bash
# R36 (docs/PLAN.md §8): the slow book at a longer hold with the power of 188 names — the archive's bookDepth for the screener members
# whose book is not yet in hand (the 158 of ft2/screen_members.csv outside R10's forty), 2023-04-01 → 2024-08-31, ingested per name, then
# R35's read on the members' cells. Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r36 'bash scripts/r36_chain.sh'      # log: output/logs/r36.log
# Each step writes output/logs/<step>.log and, when it ends well, output/logs/<step>.done; a done step is not made again, so the chain can
# be started again after a failure (the fetch resumes by itself: a file with its .ok is skipped). Every depth parquet in hand before the
# fetch (the twelve's and R10's 32) must come back unchanged: their md5s are taken first and compared after the ingest (a difference stops
# the chain before the read). The read exits 2 on a validity failure — VOID, no marker.
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
# the members whose book is not in hand: the 188 minus the 30 that are in R10's forty (R34 fetched those) — frozen into a file first
step r36_list bash -c 'python -c "from ft2.universe import screen_symbols, NEW; print(\" \".join(s for s in screen_symbols() if s not in set(NEW)))" > output/logs/r36_fetch_list.txt; wc -w output/logs/r36_fetch_list.txt'
FETCH="$(cat output/logs/r36_fetch_list.txt)"
echo "$(date -u +%H:%M:%S) names to fetch: $(wc -w <<< "$FETCH")"

# every depth parquet in hand, as it is before anything is fetched
step r36_md5_before bash -c 'md5sum data/depth/*.parquet > output/logs/r36_md5_before.txt; wc -l output/logs/r36_md5_before.txt'

# the fetch: daily files, sha256-checked, resumable; a day before a listing is missing, not an error; exit 1 on any failed file → again
step r36_fetch ft2 archive bookDepth --symbols $FETCH --start 2023-04-01 --end 2024-08-31

# the ingest: one parquet per name from that name's own zips; nothing else is named, so nothing else is touched
step r36_ingest ft2 ingest depth --symbols $FETCH

# the files in hand before: identical, or the chain stops here
step r36_md5_after bash -c 'md5sum $(cut -d" " -f3- output/logs/r36_md5_before.txt) > output/logs/r36_md5_after.txt; diff output/logs/r36_md5_before.txt output/logs/r36_md5_after.txt && echo "every depth file in hand before the fetch is unchanged"'

# the read on the 188 (validity first; exit 2 = void). The md5 check inside the read uses the file above.
FT2_JOBS=4 step r36_read ft2 horizon --book --universe screen --holds 864 2016
du -sh data/raw/external/binance/bookDepth data/depth; df -h ~ | tail -1
echo "$(date -u +%H:%M:%S) R36_CHAIN_DONE"
