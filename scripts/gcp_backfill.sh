#!/usr/bin/env bash
# Launch the historic data backfill on the always-on VM (fluxtrader-1) inside a
# remote tmux session, so it survives your SSH session and runs unattended.
#
# The backfill runs WHERE the DB lives (the always-on instance) via its local git
# checkout + docker compose — no VM spin-up, no dump/restore, no bucket artifacts.
#
#   ./scripts/gcp_backfill.sh                          # default: user's 1000-day run
#   ./scripts/gcp_backfill.sh --days 180 --funding     # custom window
#   ./scripts/gcp_backfill.sh --symbols BTCUSDT --intervals 1m --days 90
#   ./scripts/gcp_backfill.sh --repair-from 2026-07-17 --intervals 1m,5m,15m,1h
#
# Flags:
#   --symbols <list>   comma-separated pairs (default: the 8-pair set, or in repair
#                      mode EVERY symbol present in `candles`)
#   --intervals <list> comma-separated kline intervals (default: 1m,15m,1h)
#   --days <n>         lookback window in days (default: 1000)
#   --funding          also backfill funding rates
#   --skip-klines      funding only
#   --repair-from <d>  REPAIR mode: refetch every kline from this UTC date to now and
#                      OVERWRITE the stored OHLCV, ignoring gap detection and --days.
#                      This is the candle-poll defect repair (docs/CANDLE_POLL_DEFECT.md):
#                      the corrupt rows are PRESENT and wrong, so the default gap-filling
#                      mode reports them "already covered" and does nothing. In repair mode
#                      --symbols defaults to every symbol in `candles`, not the 8-pair set,
#                      because a repair that skips a collected pair leaves it corrupt.
#
# Watch progress from your Mac:  ./scripts/gcp_backfill_status.sh
# Live view (detach with Ctrl-b then d):
#   gcloud compute ssh fluxtrader-1 --zone=$GCP_ZONE --project=$GCP_PROJECT \
#     -- tmux attach -t fluxbackfill
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud

SYMBOLS="${BACKFILL_SYMBOLS:-}"
INTERVALS="${BACKFILL_INTERVALS:-1m,15m,1h}"
DAYS="${BACKFILL_DAYS:-1000}"
FUNDING_FLAG=""
SKIP_KLINES_FLAG=""
REPAIR_FROM=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --symbols)
      [[ $# -ge 2 ]] || { echo "ERROR: --symbols requires a value"; exit 1; }
      SYMBOLS="$2"; shift 2 ;;
    --intervals)
      [[ $# -ge 2 ]] || { echo "ERROR: --intervals requires a value"; exit 1; }
      INTERVALS="$2"; shift 2 ;;
    --days)
      [[ $# -ge 2 ]] || { echo "ERROR: --days requires a value"; exit 1; }
      DAYS="$2"; shift 2 ;;
    --funding)
      FUNDING_FLAG="--funding"; shift ;;
    --skip-klines)
      SKIP_KLINES_FLAG="--skip-klines"; shift ;;
    --repair-from)
      [[ $# -ge 2 ]] || { echo "ERROR: --repair-from requires a YYYY-MM-DD value"; exit 1; }
      [[ "$2" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "ERROR: --repair-from must be YYYY-MM-DD, got '$2'"; exit 1; }
      REPAIR_FROM="$2"; shift 2 ;;
    --*)
      echo "ERROR: unknown flag '$1'"; exit 1 ;;
    *)
      DAYS="$1"; shift ;;
  esac
done

# Only default the symbol list OUTSIDE repair mode. In repair mode an empty list is
# meaningful: backfill_history.py then repairs every symbol in `candles`, which is what
# we want, since the 8-pair default would silently leave the other four corrupt.
REPAIR_FLAG=""
if [[ -n "$REPAIR_FROM" ]]; then
  REPAIR_FLAG="--repair-from $REPAIR_FROM"
elif [[ -z "$SYMBOLS" ]]; then
  SYMBOLS="BTCUSDT,ETHUSDT,SOLUSDT,1000PEPEUSDT,DOGEUSDT,HYPEUSDT,WLDUSDT,ZECUSDT"
fi
SYMBOLS_FLAG=""
[[ -n "$SYMBOLS" ]] && SYMBOLS_FLAG="--symbols $SYMBOLS"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
echo "==> launching backfill on $GCP_ALWAYS_ON (zone=$GCP_ZONE)"
echo "    run_id=$RUN_ID  symbols=${SYMBOLS:-<every symbol in candles>}  intervals=$INTERVALS  days=$DAYS  funding=${FUNDING_FLAG:-off}  skip_klines=${SKIP_KLINES_FLAG:-off}  repair_from=${REPAIR_FROM:-off}"

gssh "$GCP_ALWAYS_ON" "cat > \$HOME/run_flux_backfill.sh <<PRELUDE
#!/bin/bash
export RUN_ID='$RUN_ID'
export GIT_REF='$GIT_REF'
export REMOTE_REPO_NAME='$REMOTE_REPO_NAME'
export SYMBOLS_FLAG='$SYMBOLS_FLAG'
export REPAIR_FLAG='$REPAIR_FLAG'
export INTERVALS='$INTERVALS'
export DAYS='$DAYS'
export FUNDING_FLAG='$FUNDING_FLAG'
export SKIP_KLINES_FLAG='$SKIP_KLINES_FLAG'
PRELUDE
cat >> \$HOME/run_flux_backfill.sh << 'ENDSCRIPT'
set -Eeuo pipefail
LOG=\$HOME/backfill.log
: > \"\$LOG\"
exec > >(tee -a \"\$LOG\") 2>&1

echo \"=== backfill start \$(date -u) run=\$RUN_ID ===\"
echo \"=== checkout \$GIT_REF ===\"
cd \$HOME/\$REMOTE_REPO_NAME
git fetch origin
git checkout \"\$GIT_REF\" 2>/dev/null || git checkout -b \"\$GIT_REF\" origin/\"\$GIT_REF\"
git reset --hard origin/\"\$GIT_REF\" 2>/dev/null || true
GIT_SHA=\"\$(git rev-parse --short HEAD)\"
echo \"git_sha=\$GIT_SHA\"

echo \"=== docker up ===\"
docker compose up -d postgres

echo \"=== backfill: \$SYMBOLS_FLAG intervals=\$INTERVALS days=\$DAYS \$FUNDING_FLAG \$SKIP_KLINES_FLAG \$REPAIR_FLAG ===\"
docker compose --profile ml run --rm ml_trainer python backfill_history.py \\
  \$SYMBOLS_FLAG \\
  --intervals \"\$INTERVALS\" \\
  --days \"\$DAYS\" \$FUNDING_FLAG \$SKIP_KLINES_FLAG \$REPAIR_FLAG

echo \"=== backfill finished \$(date -u) run=\$RUN_ID ===\"
ENDSCRIPT
chmod +x \$HOME/run_flux_backfill.sh
tmux kill-session -t fluxbackfill 2>/dev/null || true
tmux new-session -d -s fluxbackfill \"bash \$HOME/run_flux_backfill.sh\"
echo 'tmux session fluxbackfill started'
tmux ls
sleep 8
echo '--- log so far ---'
tail -n 30 \$HOME/backfill.log 2>/dev/null || echo '(starting...)'
" "$GCP_ZONE"

echo ""
echo "OK — backfill started on $GCP_ALWAYS_ON (run=$RUN_ID)."
echo "Watch:   ./scripts/gcp_backfill_status.sh"
echo "Live:    gcloud compute ssh $GCP_ALWAYS_ON --zone=$GCP_ZONE --project=$GCP_PROJECT -- tmux attach -t fluxbackfill"
