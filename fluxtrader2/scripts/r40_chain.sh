#!/usr/bin/env bash
# R40 (docs/PLAN.md §8, §3 "re-execution `maker_trade`"): the three maker reads made again with the `maker_trade` execution added and nothing
# else changed — R31 (ixhour4h, FP+F0+F1+F2, guarded), R38 (ridgebook at 4h with the vol gate, F1+F2), R32 (trend1d, FP+F0+F1+F2, guarded) —
# each followed by the check that its decisions and its taker / maker / maker_ev fills are the first read's row by row. Serial on the work VM,
# in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r40 'bash scripts/r40_chain.sh'      # log: output/logs/r40.log
# Each step writes output/logs/<step>.log and, when it ends well, output/logs/<step>.done; a done step is not made again (a guarded fold is
# read again once per tag), so the chain can be started again after a failure.
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
EX="taker maker maker_ev maker_trade"

# R31 — the index's last hour on the basket, maker: the registered command plus the exec, on its guarded folds under the tag
step r40_r31 ft2 backtest ixhour4h --folds FP F0 F1 F2 --registration R31 --reexecute maker_trade --execs $EX --name ixhour4h_maker_trade
step r40_r31_check python scripts/actual_check.py same ixhour4h ixhour4h_maker_trade

# R38 — the 4h ridge with the vol gate on F1+F2 (exploration; no guard)
step r40_r38 ft2 backtest ridgebook --param hold=48 min_bps=10 q_vol=0.9 --execs $EX --name r38_ridgebook_4h_ho12_vol_maker_trade
step r40_r38_check python scripts/actual_check.py same r38_ridgebook_4h_ho12_vol r38_ridgebook_4h_ho12_vol_maker_trade

# R32 — the basket's 30-day trend at one day on its guarded folds under the tag (its maker rows were described, not primary)
step r40_r32 ft2 backtest trend1d --folds FP F0 F1 F2 --registration R32 --reexecute maker_trade --execs $EX --name trend1d_maker_trade
step r40_r32_check python scripts/actual_check.py same trend1d trend1d_maker_trade
echo "$(date -u +%H:%M:%S) R40_CHAIN_DONE"
