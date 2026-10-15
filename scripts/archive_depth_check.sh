#!/usr/bin/env bash
# X8c prerequisite 1 (NEXT_TRAINING_PLAN §2 X8c): the archive-vs-collector identity for the
# ±0.2 % depth band the `depth` feature group reads.
#
# WHAT: read-only \copy of the collector's band rows (orderbook_snapshots since the 500-level
#       deploy, 2026-10-12 02:17 UTC) from fluxtrader-1 -> ml/train/output/archive/
#       collector_depth_<UTC date>.csv, then `m3 archivebook check` in the ml_analysis container:
#       per served-depth pair and side, the archive's 30 s row vs the nearest collector row within
#       15 s, stale rows removed on both sides by the registered rule; PASS = median rel. diff
#       < 2 % and p99 < 10 % everywhere. Exit 2 on FAIL — X8c is then void before it runs.
#
# Usage:  ./scripts/archive_depth_check.sh [--since 'YYYY-MM-DD HH:MM'] [--series]
#         --series: X8c′ prerequisite 1′, the series-shaped bar (NEXT_TRAINING_PLAN §2 X8c′)
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SINCE="2026-10-12 02:17"
SERIES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --since) SINCE="$2"; shift 2 ;;
    --series) SERIES=(--series); shift ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done
OUT_DIR="$REPO_ROOT/ml/train/output/archive"
STAMP="$(date -u +%Y%m%d)"
CSV="$OUT_DIR/collector_depth_${STAMP}.csv"
mkdir -p "$OUT_DIR"

echo "→ exporting orderbook_snapshots band rows since $SINCE from $GCP_ALWAYS_ON …" >&2
gssh "$GCP_ALWAYS_ON" "cd ~/$REMOTE_REPO_NAME && docker compose exec -T postgres \
  psql -U fluxtrader -d fluxtrader -Atc \"\\copy (select symbol, ts, bid_band_0_2, ask_band_0_2, bid_band_1, ask_band_1, bid_band_2, ask_band_2, bid_band_3, ask_band_3, bid_band_4, ask_band_4, bid_band_5, ask_band_5, bid_reach_bps, ask_reach_bps from orderbook_snapshots where ts >= '$SINCE' and bid_band_0_2 is not null order by symbol, ts) to stdout with csv header\"" \
  > "$CSV"
echo "→ $(($(wc -l < "$CSV") - 1)) rows -> $CSV" >&2

exec "$REPO_ROOT/scripts/m3.sh" -m m3 archivebook check --collector "output/archive/collector_depth_${STAMP}.csv" "${SERIES[@]+"${SERIES[@]}"}"
