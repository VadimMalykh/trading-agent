#!/usr/bin/env bash
# Upload export bundle to a GCE instance.
# Required env:
#   GCP_INSTANCE  e.g. fluxtrader-1
#   GCP_ZONE      e.g. europe-west1-b
# Optional:
#   GCP_PROJECT
#   EXPORT_DIR    default: $HOME/fluxtrader-export
set -euo pipefail

: "${GCP_INSTANCE:?Set GCP_INSTANCE (GCE instance name)}"
: "${GCP_ZONE:?Set GCP_ZONE (e.g. europe-west1-b)}"

EXPORT_DIR="${EXPORT_DIR:-$HOME/fluxtrader-export}"
REMOTE_DIR="${REMOTE_DIR:-~/fluxtrader-export}"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "ERROR: gcloud CLI not found."
  echo "Install: https://cloud.google.com/sdk/docs/install"
  echo "Then: gcloud auth login && gcloud config set project YOUR_PROJECT"
  exit 1
fi

if [[ ! -d "$EXPORT_DIR" ]]; then
  echo "ERROR: export dir missing: $EXPORT_DIR"
  echo "Run: ./scripts/export_local.sh first"
  exit 1
fi

PROJECT_ARGS=()
if [[ -n "${GCP_PROJECT:-}" ]]; then
  PROJECT_ARGS+=(--project="$GCP_PROJECT")
fi

echo "==> Uploading $EXPORT_DIR → ${GCP_INSTANCE}:${REMOTE_DIR} (zone=$GCP_ZONE)"
gcloud compute scp --recurse \
  "${PROJECT_ARGS[@]}" \
  --zone="$GCP_ZONE" \
  "$EXPORT_DIR" \
  "${GCP_INSTANCE}:${REMOTE_DIR}"

echo "==> Upload done."
echo "On the VM, from the repo directory run:"
echo "  EXPORT_DIR=~/fluxtrader-export ./scripts/import_on_server.sh"
