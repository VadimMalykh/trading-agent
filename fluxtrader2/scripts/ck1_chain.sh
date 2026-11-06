#!/usr/bin/env bash
# Decision CK1 (ii), the first half on the work VM: the raw DefiLlama file (scp'd from the laptop — the day's FIRST fetch, md5 45439f98…)
# ingested, the wallet list's commit days fetched (`fetch` keeps an existing day file), the events written (the lists to freeze). The bars
# and the audit run in a SECOND chain (ck1_audit.sh) after the lists are frozen and committed. Nothing after a t0 is read; nothing is priced.
#   ./fluxtrader2/scripts/vm.sh ssh 'cd ~/fluxtrader2 && source ~/ft2-venv/bin/activate && bash scripts/ck1_chain.sh'
set -euo pipefail
export PYTHONPATH=.
mkdir -p output/logs output/cexflow
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
echo "raw: $(md5sum data/raw/external/defillama_cex/binance-cex_*.json | tr '\n' ' ')"
step cexflow_fetch  python -u -m ft2 cexflow fetch
step cexflow_ingest python -u -m ft2 cexflow ingest
step cexflow_events python -u -m ft2 cexflow events
echo "$(date -u +%H:%M:%S) CK1_CHAIN_DONE"
