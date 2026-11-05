#!/usr/bin/env bash
# Decision CG1 (i): the governance-vote audit's fetch on the work VM — the spaces by Snapshot's ranking, the proposals of the kept spaces —
# then the events written (the lists to freeze). The bars and the audit run in a SECOND chain (cg1_audit.sh) after the hand check of the
# spaces (EXCLUDED in ft2/govlist.py) and after the lists are frozen and committed. Nothing after a vote's end is read; nothing is priced.
#   ./fluxtrader2/scripts/vm.sh bgsh cg1 'bash scripts/cg1_chain.sh'
set -euo pipefail
export PYTHONPATH=.
mkdir -p output/logs output/govlist
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
step govlist_spaces    python -u -m ft2 govlist spaces --fetch
step govlist_proposals python -u -m ft2 govlist proposals --fetch
step govlist_events    python -u -m ft2 govlist events
echo "$(date -u +%H:%M:%S) CG1_CHAIN_DONE"
