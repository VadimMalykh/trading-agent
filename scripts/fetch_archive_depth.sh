#!/usr/bin/env bash
# X8c prerequisite 2 (NEXT_TRAINING_PLAN §2 X8c): the reduced bookDepth archive as ONE parquet,
# uploaded to the train bucket.
#
# WHAT: `m3 archivebook reduce` in the ml_analysis container over the per-pair parquets that
#       `m3 archivebook fetch` wrote (ml/train/output/archive/bookdepth/<SYM>.parquet) -> the
#       registered stale rule, one row per pair per 5m bar ->
#       ml/train/output/archive/bookdepth_5m_<sha8>.parquet -> gs://<bucket>/archive/.
#       The sha8 is the file's identity (meta["archive_depth"]).
#
# Usage:  ./scripts/fetch_archive_depth.sh [--no-upload]
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UPLOAD=1
[[ "${1:-}" == "--no-upload" ]] && UPLOAD=0

"$REPO_ROOT/scripts/m3.sh" -m m3 archivebook reduce | tee /tmp/archive_depth.$$.log
PARQUET="$(grep -oE 'wrote output/archive/bookdepth_5m_[0-9a-f]{8}\.parquet' /tmp/archive_depth.$$.log | tail -1 | cut -d' ' -f2)"
rm -f /tmp/archive_depth.$$.log
[[ -n "$PARQUET" ]] || { echo "ERROR: no parquet written" >&2; exit 1; }

if [[ "$UPLOAD" == "1" ]]; then
  require_gcloud
  DEST="$GCS_BUCKET/archive/$(basename "$PARQUET")"
  gcloud storage cp "$REPO_ROOT/ml/train/$PARQUET" "$DEST"
  echo ""
  echo "uploaded -> $DEST"
  echo "ARCHIVE_DEPTH=$DEST"
fi
