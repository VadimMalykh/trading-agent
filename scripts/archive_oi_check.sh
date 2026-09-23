#!/usr/bin/env bash
# X8 prerequisite 4 (NEXT_TRAINING_PLAN §2 X8): the archive-vs-collector identity acceptance.
#
# WHAT: read-only \copy of the collector's `open_interest` table (symbol, ts, open_interest)
#       from fluxtrader-1 -> ml/train/output/archive/collector_oi_<UTC date>.csv, then
#       `m3 archiveoi check` in the ml_analysis container: per pair, nearest collector row
#       within 5 min of each archive row; PASS = median rel. diff < 0.5% and p99 < 2% on
#       every pair. Exit 2 on FAIL — X8 is then void before it runs.
#
# Usage:  ./scripts/archive_oi_check.sh output/archive/metrics_um_5m_<sha8>.parquet
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PARQUET="${1:?parquet path relative to ml/train, e.g. output/archive/metrics_um_5m_<sha8>.parquet}"
OUT_DIR="$REPO_ROOT/ml/train/output/archive"
STAMP="$(date -u +%Y%m%d)"
CSV="$OUT_DIR/collector_oi_${STAMP}.csv"
mkdir -p "$OUT_DIR"

echo "→ exporting open_interest from $GCP_ALWAYS_ON …" >&2
gssh "$GCP_ALWAYS_ON" "cd ~/$REMOTE_REPO_NAME && docker compose exec -T postgres \
  psql -U fluxtrader -d fluxtrader -Atc \"\\copy (select symbol, ts, open_interest from open_interest order by symbol, ts) to stdout with csv header\"" \
  > "$CSV"
echo "→ $(($(wc -l < "$CSV") - 1)) rows -> $CSV" >&2

exec "$REPO_ROOT/scripts/m3.sh" -m m3 archiveoi check --parquet "$PARQUET" \
  --collector "output/archive/collector_oi_${STAMP}.csv"
