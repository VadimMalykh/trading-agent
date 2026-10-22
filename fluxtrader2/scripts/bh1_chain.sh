#!/usr/bin/env bash
# Decision BH1 (docs/PLAN.md P8): Binance's own SPOT market per member — the SOURCE AUDIT. The archive's spot monthly 1h klines
# (data.binance.vision, free, keyless; the taker-buy columns) for the twelve's and the screener's members' <BASE>USDT markets,
# 2023-04 → F5's end: the listing against the archive's spot prefixes, the fetch (resumable, checksums), the ingest to one parquet, the
# audit against the perpetual's 5m bars (the stamp check, the member cover per block, the taker-buy share and the spot/perp volume ratio
# per name with their deviations' correlation with cbprem_dev on R62's kept names). Nothing registered, no fold read.
#   ./fluxtrader2/scripts/vm.sh bgsh bh1 'bash scripts/bh1_chain.sh'      # log: output/logs/bh1.log
# The steps are named spot_<action>, not bh1. The chain's exit arms a poweroff 30 min later.
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
echo "md5 before: $(md5sum ft2/screen_members.csv ft2/screen_members_f34.csv ft2/cb_members_r62.csv output/coinbase_members_premium.parquet | tr '\n' ' ')"
step spot_symbols python -m ft2 spot symbols
step spot_fetch   python -m ft2 spot fetch --listed-only
step spot_ingest  python -m ft2 spot ingest
step spot_audit   python -m ft2 spot audit
echo "md5 after:  $(md5sum ft2/screen_members.csv ft2/screen_members_f34.csv ft2/cb_members_r62.csv output/coinbase_members_premium.parquet | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) BH1_CHAIN_DONE"
