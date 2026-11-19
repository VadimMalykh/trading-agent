#!/usr/bin/env bash
# R100 (PLAN §8, registered 2026-11-19): the frozen trees on the NEXT SIXTY — (A) validity, the forecast, the pooled IC and its gate,
# then (B) the twelve declared forms and the choice (ft2/next60.py). ONE read: `next60 a` writes the ledger row (R100, N60) and refuses
# a second run; `next60 b` refuses before (A) and after its own b.json.
#   ./fluxtrader2/scripts/vm.sh bgsh r100chain 'bash scripts/r100.sh'      # log: output/logs/r100chain.log (the job's name differs from the steps')
# The chain's exit (done or failed) arms a poweroff 30 minutes later; kill the `sudo poweroff` wrapper first if another chain follows.
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
echo "$(date -u +%H:%M:%S) git: $(cat output/logs/r100_commit.txt 2>/dev/null || echo unknown); model: $(md5sum ft2/r89_model.txt | cut -c1-32)"
echo "$(date -u +%H:%M:%S) lists: $(md5sum ft2/screen_next60_pre.csv ft2/screen_next60_f12.csv ft2/screen_next60_f34.csv ft2/screen_next60_f5.csv ft2/screen_next60_f5_coins.csv | cut -c1-32 | tr '\n' ' ')"
df -h --output=avail . | tail -1; free -g | sed -n 2p
step n60_a python -u -m ft2 next60 a
step n60_b python -u -m ft2 next60 b
echo "$(date -u +%H:%M:%S) R100_DONE"
