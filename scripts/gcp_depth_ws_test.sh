#!/usr/bin/env bash
#
# B4.3 (docs/BOOK_ERA_PLAN.md §2) — is Binance's @depth WebSocket stream reachable
# from the egress that would actually consume it?
#
# WHY THIS EXISTS: the collector polls REST depth every 5s, which is the fidelity
# ceiling for all 1m/5m work. The @depth diff stream is the fix, BUT the
# !forceOrder@arr stream is already known to be gated from datacenter egress
# (upgrade + SUBSCRIBE ack, then zero data frames — hence `liquidations` = 0 rows).
# Nobody should design around @depth until we know which side of that line it sits
# on. This is a ~1 minute connectivity test.
#
# The probe subscribes to @depth, @aggTrade (control: does ANY market data arrive?)
# and !forceOrder@arr (known-blocked reference) on one connection and counts frames
# by type. It writes nothing to the database.
#
# Runs on the ALWAYS-ON VM by default, because that host's egress is the one that
# matters. --local runs it in the local docker stack instead, which answers a
# different question (your laptop is not datacenter egress) but is useful for
# checking the probe itself works.
#
# Usage:
#   ./scripts/gcp_depth_ws_test.sh                       # 60s on the always-on VM
#   ./scripts/gcp_depth_ws_test.sh --seconds 120
#   ./scripts/gcp_depth_ws_test.sh --symbol ethusdt
#   ./scripts/gcp_depth_ws_test.sh --local
#
# Verdict is the last line: DEPTH_OK | DEPTH_BLOCKED | WS_BLOCKED | CONNECT_FAILED.
# Record it in docs/BOOK_ERA_PLAN.md B4 — a WS_BLOCKED answer is a real result and
# closes the item; it does not need re-running.
set -euo pipefail

GCP_PROJECT="${GCP_PROJECT:-fluxtrader}"
GCP_ZONE="${GCP_ZONE:-me-central1-b}"
GCP_ALWAYS_ON="${GCP_ALWAYS_ON:-fluxtrader-1}"
REMOTE_REPO_NAME="${REMOTE_REPO_NAME:-trading_agent}"

DURATION=60
SYMBOL=btcusdt
STREAMS=""
LOCAL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --seconds) DURATION="$2"; shift 2 ;;
    --symbol)  SYMBOL="$2";   shift 2 ;;
    --streams) STREAMS="$2";  shift 2 ;;
    --local)   LOCAL=1;       shift ;;
    -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

MIX_ARGS="--symbol ${SYMBOL} --seconds ${DURATION}"
if [[ -n "$STREAMS" ]]; then
  MIX_ARGS="${MIX_ARGS} --streams ${STREAMS}"
fi

# The exec timeout must outlast the probe's own listening window.
TIMEOUT=$((DURATION + 90))

if [[ "$LOCAL" == "1" ]]; then
  echo "==> local docker stack (NOT datacenter egress — see header)"
  exec docker compose exec -T app mix flux.depth_ws_test ${MIX_ARGS}
fi

echo "==> ${GCP_ALWAYS_ON} (${GCP_ZONE}), ~${DURATION}s"
echo "    the code must already be deployed there; if mix reports the task could"
echo "    not be found, update the VM's checkout first."
echo

gcloud compute ssh --zone "$GCP_ZONE" "$GCP_ALWAYS_ON" --project "$GCP_PROJECT" -- \
  "cd ~/${REMOTE_REPO_NAME} && timeout ${TIMEOUT} docker compose exec -T app mix flux.depth_ws_test ${MIX_ARGS}"
