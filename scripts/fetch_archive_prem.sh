#!/usr/bin/env bash
# X14 prerequisite 2 (NEXT_TRAINING_PLAN §2 X14): the mark–index premium from Binance's public
# archive as ONE parquet, uploaded to the train bucket.
#
# WHAT: `m3 archiveprem fetch` then `m3 archiveprem reduce` in the ml_analysis container (Docker,
#       nothing on the host) — the monthly markPriceKlines + indexPriceKlines 5m files for the
#       twelve traded pairs, 2022-08 -> the archive's last complete month, sha256-verified,
#       resumable (zips cached under ml/train/output/archive/prem_zips), plus the 1m files over
#       the collector overlap for the identity check -> (mark ÷ index − 1) × 10⁴ per pair-bar,
#       stamped at the bar's close -> ml/train/output/archive/premium_5m_<sha8>.parquet
#       -> gs://<bucket>/archive/. The sha8 is the file's identity (meta["archive_prem"]).
# THEN: ./scripts/archive_prem_check.sh   (prerequisite 1, must PASS before launch)
#
# Usage:  ./scripts/fetch_archive_prem.sh [--no-fetch] [--no-upload]
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FETCH=1; UPLOAD=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-fetch) FETCH=0; shift ;;
    --no-upload) UPLOAD=0; shift ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done

if [[ "$FETCH" == "1" ]]; then
  "$REPO_ROOT/scripts/m3.sh" -m m3 archiveprem fetch
fi
"$REPO_ROOT/scripts/m3.sh" -m m3 archiveprem reduce | tee /tmp/archive_prem.$$.log
PARQUET="$(grep -oE 'wrote output/archive/premium_5m_[0-9a-f]{8}\.parquet' /tmp/archive_prem.$$.log | tail -1 | cut -d' ' -f2)"
rm -f /tmp/archive_prem.$$.log
[[ -n "$PARQUET" ]] || { echo "ERROR: no parquet written" >&2; exit 1; }

if [[ "$UPLOAD" == "1" ]]; then
  require_gcloud
  DEST="$GCS_BUCKET/archive/$(basename "$PARQUET")"
  gcloud storage cp "$REPO_ROOT/ml/train/$PARQUET" "$DEST"
  echo ""
  echo "uploaded -> $DEST"
  echo "ARCHIVE_PREM=$DEST"
fi
