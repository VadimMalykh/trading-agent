#!/usr/bin/env bash
# X8b identity prerequisite (NEXT_TRAINING_PLAN §2 X8b): the archive-vs-collector acceptance
# for the three flow ratios the `flow` feature group reads.
#
# WHAT: read-only \copy of the collector's `long_short_ratios` (5m period; symbol, ts,
#       top_long_short_ratio, global_long_short_ratio, taker_buy_sell_ratio) from fluxtrader-1
#       -> ml/train/output/archive/collector_flow_<UTC date>.csv, then
#       `m3 archiveoi check-flow` in the ml_analysis container: per pair and series, nearest
#       collector row within 5 min of each archive row; PASS = median rel. diff < 0.5% and
#       p99 < 2% everywhere. Exit 2 on FAIL — X8b is then void before it runs.
#
# Usage:  ./scripts/archive_flow_check.sh output/archive/metrics_um_5m_<sha8>.parquet
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PARQUET="${1:?parquet path relative to ml/train, e.g. output/archive/metrics_um_5m_<sha8>.parquet}"
OUT_DIR="$REPO_ROOT/ml/train/output/archive"
STAMP="$(date -u +%Y%m%d)"
CSV="$OUT_DIR/collector_flow_${STAMP}.csv"
mkdir -p "$OUT_DIR"

echo "→ exporting long_short_ratios from $GCP_ALWAYS_ON …" >&2
gssh "$GCP_ALWAYS_ON" "cd ~/$REMOTE_REPO_NAME && docker compose exec -T postgres \
  psql -U fluxtrader -d fluxtrader -Atc \"\\copy (select symbol, ts, top_long_short_ratio, global_long_short_ratio, taker_buy_sell_ratio from long_short_ratios where period = '5m' order by symbol, ts) to stdout with csv header\"" \
  > "$CSV"
echo "→ $(($(wc -l < "$CSV") - 1)) rows -> $CSV" >&2

exec "$REPO_ROOT/scripts/m3.sh" -m m3 archiveoi check-flow --parquet "$PARQUET" \
  --collector "output/archive/collector_flow_${STAMP}.csv"
