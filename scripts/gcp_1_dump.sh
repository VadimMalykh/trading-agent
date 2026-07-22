#!/usr/bin/env bash
# STEP 1/5 — Dump app tables from always-on VM → Mac
# Uses plain SQL of application tables only (avoids Timescale catalog restore crashes).
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

mkdir -p "$EXPORT_DIR"
R="\$HOME/${REMOTE_REPO_NAME}"

# App tables used for training / settings (not Timescale internals)
TABLES="candles orderbook_snapshots market_trades funding_rates open_interest liquidations app_settings positions trades schema_migrations"

echo ""
echo "==> STEP 1: dump app tables from $GCP_ALWAYS_ON"
gssh "$GCP_ALWAYS_ON" "set -e
  cd $R
  docker compose exec -T postgres pg_isready -U fluxtrader
  # Build -t flags
  TFLAGS=''
  for t in $TABLES; do TFLAGS=\"\$TFLAGS -t \$t\"; done
  docker compose exec -T postgres bash -c \"
    pg_dump -U fluxtrader -d fluxtrader --format=plain --no-owner --no-acl \\
      \$TFLAGS
  \" | gzip > /tmp/fluxtrader_train.sql.gz
  ls -lh /tmp/fluxtrader_train.sql.gz
  docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"
    SELECT 'candles', count(*) FROM candles
    UNION ALL SELECT 'orderbook_snapshots', count(*) FROM orderbook_snapshots
    UNION ALL SELECT 'market_trades', count(*) FROM market_trades;
  \" > /tmp/counts_always_on.txt
"

gscp_from "$GCP_ALWAYS_ON" /tmp/fluxtrader_train.sql.gz "$EXPORT_DIR/fluxtrader_train.sql.gz"
gscp_from "$GCP_ALWAYS_ON" /tmp/counts_always_on.txt "$EXPORT_DIR/counts_always_on.txt" || true

# keep legacy name pointer for clarity
rm -f "$EXPORT_DIR/fluxtrader.dump"
ls -lh "$EXPORT_DIR/fluxtrader_train.sql.gz"
echo ""
echo "OK — counts on always-on:"
cat "$EXPORT_DIR/counts_always_on.txt" 2>/dev/null || true
echo ""
echo "Next: ./scripts/gcp_2_create_train_vm.sh   (if VM already exists, skip to step 3)"
echo "      ./scripts/gcp_3_start_train.sh"
