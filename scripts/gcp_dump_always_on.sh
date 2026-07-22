#!/usr/bin/env bash
# Dump Postgres (+ optional model weights) from the always-on VM to this machine.
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

OUT="${EXPORT_DIR:-$HOME/fluxtrader-train-export}"
mkdir -p "$OUT"

echo "==> Dumping DB on $GCP_ALWAYS_ON ..."
gssh "$GCP_ALWAYS_ON" "set -e
  cd $REMOTE_REPO
  docker compose exec -T postgres pg_isready -U fluxtrader
  docker compose exec -T postgres pg_dump -U fluxtrader -d fluxtrader --format=custom -f /tmp/fluxtrader.dump
  docker compose cp postgres:/tmp/fluxtrader.dump /tmp/fluxtrader.dump
  docker compose exec -T postgres rm -f /tmp/fluxtrader.dump
  docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"
    SELECT 'candles', count(*) FROM candles
    UNION ALL SELECT 'orderbook_snapshots', count(*) FROM orderbook_snapshots
    UNION ALL SELECT 'market_trades', count(*) FROM market_trades;
  \" > /tmp/counts_always_on.txt
"

echo "==> Downloading dump to $OUT ..."
gscp_from "$GCP_ALWAYS_ON" /tmp/fluxtrader.dump "$OUT/fluxtrader.dump"
gscp_from "$GCP_ALWAYS_ON" /tmp/counts_always_on.txt "$OUT/counts_always_on.txt" || true

echo "==> Packing model_weights on always-on (optional baseline) ..."
gssh "$GCP_ALWAYS_ON" "set -e
  VOL=\$(docker volume ls -q | grep -E 'model_weights\$' | head -1)
  if [[ -n \"\$VOL\" ]]; then
    docker run --rm -v \"\$VOL:/models:ro\" -v /tmp:/out alpine \
      tar czf /out/model_weights_before.tar.gz -C /models .
  fi
" || true
gscp_from "$GCP_ALWAYS_ON" /tmp/model_weights_before.tar.gz "$OUT/model_weights_before.tar.gz" 2>/dev/null || true

ls -lh "$OUT"
echo "==> Dump ready: $OUT/fluxtrader.dump"
echo "    Next: ./scripts/gcp_create_train_vm.sh && ./scripts/gcp_run_train.sh"
