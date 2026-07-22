#!/usr/bin/env bash
# STEP 1/5 — Dump Postgres from always-on VM → Mac (~/fluxtrader-train-export)
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

mkdir -p "$EXPORT_DIR"
R="\$HOME/${REMOTE_REPO_NAME}"

echo ""
echo "==> STEP 1: dump database from $GCP_ALWAYS_ON"
gssh "$GCP_ALWAYS_ON" "set -e
  cd $R
  docker compose exec -T postgres pg_isready -U fluxtrader
  docker compose exec -T postgres \
    pg_dump -U fluxtrader -d fluxtrader --format=custom -f /tmp/fluxtrader.dump
  docker compose cp postgres:/tmp/fluxtrader.dump /tmp/fluxtrader.dump
  docker compose exec -T postgres rm -f /tmp/fluxtrader.dump
  docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"
    SELECT 'candles', count(*) FROM candles
    UNION ALL SELECT 'orderbook_snapshots', count(*) FROM orderbook_snapshots
    UNION ALL SELECT 'market_trades', count(*) FROM market_trades;
  \" > /tmp/counts_always_on.txt
"

gscp_from "$GCP_ALWAYS_ON" /tmp/fluxtrader.dump "$EXPORT_DIR/fluxtrader.dump"
gscp_from "$GCP_ALWAYS_ON" /tmp/counts_always_on.txt "$EXPORT_DIR/counts_always_on.txt" || true

echo ""
echo "OK — dump saved:"
ls -lh "$EXPORT_DIR/fluxtrader.dump"
cat "$EXPORT_DIR/counts_always_on.txt" 2>/dev/null || true
echo ""
echo "Next: ./scripts/gcp_2_create_train_vm.sh"
