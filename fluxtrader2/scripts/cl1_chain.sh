#!/usr/bin/env bash
# R85 (docs/PLAN.md §8, registered 2026-11-09 on Vadim's "CL1"): the exchange's OWN on-chain balance jump — a member SOLD at the first 5m bar
# closing after the day's point is KNOWN (t0 + the lag, 8 h; 6 h only by the 06:00 UTC probe written into R85's "Gate (b) line") on the FROZEN
# ft2/cexflow_f12.csv's members' inflow cells (121 rows; none dropped at 1d, MATIC 2024-08-29 at 3d), held 1 day against the F1+F2 block's
# members (3 days described); the gate on the 10 % TRIMMED mean of the 1-day hold alone; the outflow mirror and the non-members' cells described.
# Gate (a) FIRST: output/cexflow/knownat.json must be the 2026-11-13 fetch's IDENTICAL verdict (the run voids before the market otherwise) —
# on the laptop: the curl of binance-cex_2026-11-13.json, `ft2.sh cexflow knownat`, then scp the 11-09 and 11-13 raw files AND
# output/cexflow/knownat.json to the VM (or run knownat on the VM after the scp). No fetch of bars: the archive slice's fingerprint before and
# after; the md5 of the frozen lists, the member list and the cost file before and after.
#   ./fluxtrader2/scripts/vm.sh bgsh cl1 'bash scripts/cl1_chain.sh'      # log: output/logs/cl1.log (launch it in the background: bgsh blocks until the chain exits)
# The steps are named cexevent85_<action>, not cl1 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff
# 30 min later.
set -euo pipefail
mkdir -p output/logs output/listing
trap 'nohup bash -c "sleep 1800; sudo poweroff" > /dev/null 2>&1 &' EXIT
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
FILES="ft2/cexflow_f12.csv ft2/cexflow_f34.csv ft2/cexflow_f5.csv ft2/screen_members.csv data/cost_daily_wide.parquet"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/cexevent.py ft2/cexflow.py ft2/govevent.py ft2/upgevent.py ft2/krevent.py ft2/fundevent.py ft2/listing.py ft2/krlist.py ft2/horizon.py ft2/backtest.py | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) gate (b) LAG_H = $(python -c 'import ft2.cexevent as c; print(c.LAG_H)') h — must equal PLAN §8 R85's Gate (b) line"
echo "$(date -u +%H:%M:%S) gate (a) knownat: $(python -c 'import json; k=json.load(open("output/cexflow/knownat.json")); print(k["verdict"][:40], "|", k["files"][-1], "| differ", k["differ"])')"
step cexevent85_fingerprint python -m ft2 cexevent fingerprint --name r85
step cexevent85_run         python -m ft2 cexevent run --name r85
step cexevent85_check       python -m ft2 cexevent check --name r85
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) CL1_CHAIN_DONE"
