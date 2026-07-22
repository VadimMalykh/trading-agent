#!/usr/bin/env bash
# Export local Postgres + model weights for GCP (or any remote) restore.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OUT="${EXPORT_DIR:-$HOME/fluxtrader-export}"
mkdir -p "$OUT"

echo "==> Export dir: $OUT"
echo "==> Dumping Postgres (custom format)..."

docker compose exec -T postgres pg_isready -U fluxtrader >/dev/null

docker compose exec -T postgres \
  pg_dump -U fluxtrader -d fluxtrader --format=custom -f /tmp/fluxtrader.dump

docker compose cp postgres:/tmp/fluxtrader.dump "$OUT/fluxtrader.dump"
docker compose exec -T postgres rm -f /tmp/fluxtrader.dump

echo "==> Also writing gzipped SQL (optional)..."
docker compose exec -T postgres \
  pg_dump -U fluxtrader -d fluxtrader | gzip > "$OUT/fluxtrader.sql.gz"

echo "==> Packing model_weights volume..."
VOL="${MODEL_VOLUME:-trading_agent_model_weights}"
if ! docker volume inspect "$VOL" >/dev/null 2>&1; then
  # try compose project prefix variants
  for v in $(docker volume ls -q | grep -E 'model_weights$' || true); do
    VOL="$v"
    break
  done
fi
echo "    using volume: $VOL"
docker run --rm \
  -v "${VOL}:/models:ro" \
  -v "$OUT:/out" \
  alpine tar czf /out/model_weights.tar.gz -C /models .

if [[ -d ml/train/output ]]; then
  echo "==> Copying ml/train/output..."
  rm -rf "$OUT/train_output"
  cp -R ml/train/output "$OUT/train_output"
fi

# row counts for verification after restore
echo "==> Writing local counts..."
docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c "
SELECT 'candles', count(*) FROM candles
UNION ALL SELECT 'orderbook_snapshots', count(*) FROM orderbook_snapshots
UNION ALL SELECT 'market_trades', count(*) FROM market_trades
UNION ALL SELECT 'funding_rates', count(*) FROM funding_rates
UNION ALL SELECT 'open_interest', count(*) FROM open_interest
UNION ALL SELECT 'app_settings', count(*) FROM app_settings;
" > "$OUT/counts_local.txt" || true

cat > "$OUT/MANIFEST.txt" <<EOF
exported_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
host=$(hostname)
files:
  fluxtrader.dump
  fluxtrader.sql.gz
  model_weights.tar.gz
  train_output/ (optional)
  counts_local.txt
EOF

echo "==> Done. Contents:"
ls -lh "$OUT"
echo ""
echo "Next: upload with scripts/upload_to_gcp.sh (set GCP_INSTANCE + GCP_ZONE)"
