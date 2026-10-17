#!/usr/bin/env bash
# R44 stage 1 (docs/PLAN.md §8): the slow cross-section as a priced book on the members, F1+F2 — the 28-day book (gated), the 14-day
# book (described), the book checks, the read. Serial on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh r44 'bash scripts/r44_chain.sh'      # log: output/logs/r44.log
# Stage 2 (on a stage-1 PASS and Vadim's go only): STAGE=2 bash scripts/r44_chain.sh — the same steps on F3+F4's members under the
# registration (the guard logs R44, F3 and F4), ONCE. The chain's exit (done or failed) arms a poweroff 30 minutes later.
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
ft2() { python -m ft2 "$@"; }
if [[ "${STAGE:-1}" == "2" ]]; then
  U="--universe f34 --folds F3 F4 --registration R44"; P="members=ft2/screen_members_f34.csv"; T="f34"
else
  U="--universe screen --folds F1 F2"; P=""; T="f12"
fi
step r44_${T}_28d ft2 backtest mombook $U --execs taker --param hold=8064 $P --name r44_mombook_28d_$T
if [[ "${STAGE:-1}" == "2" ]]; then
  # Stage 2 has no described 14-day run: the 28-day run under R44 logs F3 and F4, and the harness reads a confirmation fold once per
  # registration (PLAN §3) — the first stage-2 chain stopped here on that refusal (output/logs/r44_f34_14d.log, 2026-10-17 11:53 UTC).
  step r44_${T}_book28 ft2 audit r44_mombook_28d_$T --book
  step r44_${T}_read python scripts/r44_read.py r44_mombook_28d_$T
else
  step r44_${T}_14d ft2 backtest mombook $U --execs taker --param hold=4032 $P --name r44_mombook_14d_$T
  step r44_${T}_book28 ft2 audit r44_mombook_28d_$T --book
  step r44_${T}_book14 ft2 audit r44_mombook_14d_$T --book
  step r44_${T}_read python scripts/r44_read.py r44_mombook_28d_$T r44_mombook_14d_$T
fi
echo "$(date -u +%H:%M:%S) R44_CHAIN_DONE"
