#!/usr/bin/env bash
# Delete ephemeral training VM (disk deleted with instance by default).
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

if ! gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
  --project="$GCP_PROJECT" --zone="$GCP_ZONE" >/dev/null 2>&1; then
  echo "Instance $GCP_TRAIN_INSTANCE does not exist — nothing to do."
  exit 0
fi

echo "==> Deleting $GCP_TRAIN_INSTANCE (zone=$GCP_ZONE) ..."
gcloud compute instances delete "$GCP_TRAIN_INSTANCE" \
  --project="$GCP_PROJECT" \
  --zone="$GCP_ZONE" \
  --quiet

echo "==> Deleted. Always-on $GCP_ALWAYS_ON is untouched."
