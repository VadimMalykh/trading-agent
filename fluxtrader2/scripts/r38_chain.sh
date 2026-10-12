#!/usr/bin/env bash
# R38 (docs/PLAN.md §8): P5's forecast at 4 hours on the twelve, held out as R14, as a maker on the most volatile tenth of bars — stage 1
# on F1+F2 — and its two described twins (the same rule without the vol gate; the in-pair reference, R13's diagnostic). Serial on the
# work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r38 'bash scripts/r38_chain.sh'      # log: output/logs/r38.log
# Each step writes output/logs/<step>.log and, when it ends well, output/logs/<step>.done; a done step is not made again. Each run
# refits the ridge on 200 shuffled price paths for its noise floor (about an hour each on the e2-standard-8).
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
P="hold=48 min_bps=10"

# the registered rule: stage 1 on F1+F2, maker primary, taker and maker_ev beside
step r38_vol ft2 backtest ridgebook --param $P q_vol=0.9 --execs taker maker maker_ev --name r38_ridgebook_4h_ho12_vol

# described (a): the same rule without the vol gate — what the filter does
step r38_all ft2 backtest ridgebook --param $P --execs taker maker maker_ev --name r38_ridgebook_4h_ho12_all

# described (b): the in-pair reference at this hold (R13's diagnostic), with the gate
step r38_inpair ft2 backtest ridgebook --param $P q_vol=0.9 holdout=false --execs taker maker --name r38_ridgebook_4h_inpair_vol
echo "$(date -u +%H:%M:%S) R38_CHAIN_DONE"
