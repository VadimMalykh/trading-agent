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
#
# Flags:
#   --symbols <list>   comma-separated pairs (default: the 8-pair set)
#   --intervals <list> comma-separated kline intervals (default: 1m,15m,1h)
#   --days <n>         lookback window in days (default: 1000)
#   --funding          also backfill funding rates
#   --skip-klines      funding only
#
# Watch progress from your Mac:  ./scripts/gcp_backfill_status.sh
# Live view (detach with Ctrl-b then d):
#   gcloud compute ssh fluxtrader-1 --zone=$GCP_ZONE --project=$GCP_PROJECT \
#     -- tmux attach -t fluxbackfill
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud

SYMBOLS="${BACKFILL_SYMBOLS:-BTCUSDT,ETHUSDT,SOLUSDT,1000PEPEUSDT,DOGEUSDT,HYPEUSDT,WLDUSDT,ZECUSDT}"
INTERVALS="${BACKFILL_INTERVALS:-1m,15m,1h}"
DAYS="${BACKFILL_DAYS:-1000}"
FUNDING_FLAG=""
SKIP_KLINES_FLAG=""

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
    --*)
      echo "ERROR: unknown flag '$1'"; exit 1 ;;
    *)
      DAYS="$1"; shift ;;
  esac
done

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
echo "==> launching backfill on $GCP_ALWAYS_ON (zone=$GCP_ZONE)"
echo "    run_id=$RUN_ID  symbols=$SYMBOLS  intervals=$INTERVALS  days=$DAYS  funding=${FUNDING_FLAG:-off}  skip_klines=${SKIP_KLINES_FLAG:-off}"

gssh "$GCP_ALWAYS_ON" "cat > \$HOME/run_flux_backfill.sh <<PRELUDE
#!/bin/bash
export RUN_ID='$RUN_ID'
export GIT_REF='$GIT_REF'
export REMOTE_REPO_NAME='$REMOTE_REPO_NAME'
export SYMBOLS='$SYMBOLS'
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

echo \"=== backfill: symbols=\$SYMBOLS intervals=\$INTERVALS days=\$DAYS \$FUNDING_FLAG \$SKIP_KLINES_FLAG ===\"
docker compose --profile ml run --rm ml_trainer python backfill_history.py \\
  --symbols \"\$SYMBOLS\" \\
  --intervals \"\$INTERVALS\" \\
  --days \"\$DAYS\" \$FUNDING_FLAG \$SKIP_KLINES_FLAG

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
