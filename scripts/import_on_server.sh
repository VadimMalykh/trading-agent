#!/usr/bin/env bash
# Run ON the GCP VM (or any server with docker compose + this repo).
# Restores Postgres dump + model_weights volume.
#
# Usage (on server, inside repo root):
#   EXPORT_DIR=~/fluxtrader-export ./scripts/import_on_server.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

EXPORT_DIR="${EXPORT_DIR:-$HOME/fluxtrader-export}"
# gcloud scp --recurse of a folder named fluxtrader-export may nest once
if [[ ! -f "$EXPORT_DIR/fluxtrader.dump" && -f "$EXPORT_DIR/fluxtrader-export/fluxtrader.dump" ]]; then
  EXPORT_DIR="$EXPORT_DIR/fluxtrader-export"
fi

DUMP="$EXPORT_DIR/fluxtrader.dump"
MODELS_TGZ="$EXPORT_DIR/model_weights.tar.gz"

if [[ ! -f "$DUMP" ]]; then
  echo "ERROR: missing $DUMP"
  exit 1
fi

echo "==> Starting postgres..."
docker compose up -d postgres
for i in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U fluxtrader >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
docker compose exec -T postgres pg_isready -U fluxtrader

echo "==> Copy dump into postgres container..."
docker compose cp "$DUMP" postgres:/tmp/fluxtrader.dump

echo "==> Restoring database (may show harmless extension/owner warnings)..."
docker compose exec -T postgres \
  pg_restore -U fluxtrader -d fluxtrader --clean --if-exists --no-owner --no-acl \
  /tmp/fluxtrader.dump || true

docker compose exec -T postgres rm -f /tmp/fluxtrader.dump

echo "==> Remote counts:"
docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c "
SELECT 'candles', count(*) FROM candles
UNION ALL SELECT 'orderbook_snapshots', count(*) FROM orderbook_snapshots
UNION ALL SELECT 'market_trades', count(*) FROM market_trades
UNION ALL SELECT 'funding_rates', count(*) FROM funding_rates
UNION ALL SELECT 'open_interest', count(*) FROM open_interest
UNION ALL SELECT 'app_settings', count(*) FROM app_settings;
" | tee /tmp/counts_remote.txt

if [[ -f "$EXPORT_DIR/counts_local.txt" ]]; then
  echo "==> Compare to local counts file:"
  echo "--- local ---"
  cat "$EXPORT_DIR/counts_local.txt"
  echo "--- remote ---"
  cat /tmp/counts_remote.txt
fi

VOL=trading_agent_model_weights
docker volume create "$VOL" >/dev/null 2>&1 || true

if [[ -f "$MODELS_TGZ" ]]; then
  echo "==> Restoring model_weights volume ($VOL)..."
  docker run --rm \
    -v "${VOL}:/models" \
    -v "$EXPORT_DIR:/in:ro" \
    alpine sh -c "rm -rf /models/*; tar xzf /in/model_weights.tar.gz -C /models && ls -la /models"
else
  echo "==> No model_weights.tar.gz — skip models"
fi

echo "==> Starting app stack..."
docker compose up -d postgres app
# optional inference if model present
if docker run --rm -v "${VOL}:/models:ro" alpine test -f /models/m2_multi.pt 2>/dev/null; then
  docker compose up -d ml_inference || true
fi

echo "==> Done. Check:"
echo "  docker compose ps"
echo "  docker compose exec postgres psql -U fluxtrader -d fluxtrader -c 'SELECT max(ts) FROM orderbook_snapshots;'"
echo "  Stop local Mac collector after you verify GCP is writing new book rows."
