#!/usr/bin/env bash
# X14 prerequisite 1 (NEXT_TRAINING_PLAN §2 X14): the archive-vs-collector identity for the
# mark–index premium, in bps.
#
# WHAT: read-only \copy of the collector's funding_rates poll (symbol, ts, mark_price,
#       index_price; every ~78 s since 2026-07-17) from fluxtrader-1 ->
#       ml/train/output/archive/collector_prem_<UTC date>.csv, then `m3 archiveprem check` in the
#       ml_analysis container: per pair, the archive's 1m mark/index closes against the last
#       collector poll in the same minute; D = archive premium − collector premium, S = the
#       archive's own 1m change; PASS = median |D| <= median |S|, p99 |D| <= 1.5 x p99 |S|,
#       n >= 2,000, on every pair. Exit 2 on FAIL — X14 is then void before it runs.
#
# Usage:  ./scripts/archive_prem_check.sh [--since 'YYYY-MM-DD'] [--csv <existing export>]
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SINCE="2026-07-17"
CSV=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --since) SINCE="$2"; shift 2 ;;
    --csv) CSV="$2"; shift 2 ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done
OUT_DIR="$REPO_ROOT/ml/train/output/archive"
mkdir -p "$OUT_DIR"

if [[ -z "$CSV" ]]; then
  require_gcloud
  STAMP="$(date -u +%Y%m%d)"
  CSV="$OUT_DIR/collector_prem_${STAMP}.csv"
  echo "→ exporting funding_rates mark/index rows since $SINCE from $GCP_ALWAYS_ON …" >&2
  gssh "$GCP_ALWAYS_ON" "cd ~/$REMOTE_REPO_NAME && docker compose exec -T postgres \
    psql -U fluxtrader -d fluxtrader -Atc \"\\copy (select symbol, ts, mark_price, index_price from funding_rates where ts >= '$SINCE' and mark_price is not null and index_price is not null order by symbol, ts) to stdout with csv header\"" \
    > "$CSV"
  echo "→ $(($(wc -l < "$CSV") - 1)) rows -> $CSV" >&2
fi

exec "$REPO_ROOT/scripts/m3.sh" -m m3 archiveprem check --collector "output/archive/$(basename "$CSV")"
