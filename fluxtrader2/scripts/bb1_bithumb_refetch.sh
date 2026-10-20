#!/usr/bin/env bash
# Decision BB1 step (i), the Bithumb REFETCH (2026-10-20): the first fetch wrote `to` in UTC and Bithumb reads a bare `to` as KST, so every
# 200-bar page lost its 9 newest bars (4.5 % of hours, a hole every page; the first audit's completeness 0.95 at best). ft2/krw.py now
# writes Bithumb's `to` shifted +9 h. This chain drops Bithumb's month files (the listing is kept), refetches every listed market in
# PARTS parallel partitions (the API is latency-bound at ≈ 1.3 s a call, far under its 10-a-second limit), then ingests and audits again.
#   ./fluxtrader2/scripts/vm.sh bgsh bb1r 'bash scripts/bb1_bithumb_refetch.sh'      # log: output/logs/bb1r.log
# The steps are named krw_bithumb_<action>[_pK], not bb1r. The chain's exit arms a poweroff 30 min later.
set -euo pipefail
PARTS="${PARTS:-8}"
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
if [[ ! -e output/logs/krw_bithumb_wipe.done ]]; then
  echo "$(date -u +%H:%M:%S) wipe  data/raw/external/bithumb/KRW-* ($(ls -d data/raw/external/bithumb/KRW-* 2>/dev/null | wc -l) markets); the first audit kept as krw_bithumb_audit_void1"
  rm -rf data/raw/external/bithumb/KRW-*
  for f in output/krw_bithumb_audit.md output/krw_bithumb_audit.json; do [[ -e "$f" ]] && mv "$f" "${f%.*}_void1.${f##*.}"; done
  rm -f output/logs/krw_bithumb_fetch.done output/logs/krw_bithumb_ingest.done output/logs/krw_bithumb_audit.done
  touch output/logs/krw_bithumb_wipe.done
fi
part() {   # the listed markets, sorted, every PARTS-th from $1
  python - "$1" "$PARTS" <<'PY'
import sys
from ft2 import krw
U = krw.universe("bithumb"); mf = krw.markets_file(U)
mk = sorted(mf.loc[mf["listed"] == True, "market"])  # noqa: E712
print(" ".join(mk[int(sys.argv[1])::int(sys.argv[2])]))
PY
}
for k in $(seq 0 $((PARTS - 1))); do
  step "krw_bithumb_fetch_p$k" python -m ft2 krw fetch --venue bithumb --listed-only --markets $(part "$k") &
done
wait
touch output/logs/krw_bithumb_fetch.done
step krw_bithumb_ingest python -m ft2 krw ingest --venue bithumb
step krw_bithumb_audit  python -m ft2 krw audit  --venue bithumb
echo "$(date -u +%H:%M:%S) BB1R_CHAIN_DONE"
