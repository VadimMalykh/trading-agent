#!/usr/bin/env bash
# X8 prerequisite 1 (NEXT_TRAINING_PLAN §2 X8): open-interest history from Binance's public
# archive, as ONE parquet, uploaded to the train bucket.
#
# WHAT: `m3 archiveoi fetch` in the ml_analysis container (Docker, nothing on the host) —
#       daily USDⓈ-M `metrics` files for the twelve traded pairs, 2022-08-01 -> the pinned
#       snapshot's date, sha256-verified, resumable (zips cached under
#       ml/train/output/archive/metrics_zips) -> ml/train/output/archive/metrics_um_5m_<sha8>.parquet
#       -> gs://<bucket>/archive/. The sha8 is the file's identity (meta["archive_oi"]).
# THEN: ./scripts/archive_oi_check.sh <parquet>   (prerequisite 4, must PASS before launch)
#
# Usage:  ./scripts/fetch_archive_metrics.sh [--end YYYY-MM-DD] [--no-upload]
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

END="2026-09-13"; UPLOAD=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --end) END="$2"; shift 2 ;;
    --no-upload) UPLOAD=0; shift ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done

"$REPO_ROOT/scripts/m3.sh" -m m3 archiveoi fetch --end "$END" | tee /tmp/archive_fetch.$$.log
PARQUET="$(grep -oE 'wrote output/archive/metrics_um_5m_[0-9a-f]{8}\.parquet' /tmp/archive_fetch.$$.log | tail -1 | cut -d' ' -f2)"
rm -f /tmp/archive_fetch.$$.log
[[ -n "$PARQUET" ]] || { echo "ERROR: no parquet written" >&2; exit 1; }

if [[ "$UPLOAD" == "1" ]]; then
  require_gcloud
  DEST="$GCS_BUCKET/archive/$(basename "$PARQUET")"
  gcloud storage cp "$REPO_ROOT/ml/train/$PARQUET" "$DEST"
  echo ""
  echo "uploaded -> $DEST"
  echo "ARCHIVE_OI=$DEST"
fi
