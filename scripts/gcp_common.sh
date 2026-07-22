#!/usr/bin/env bash
# Shared helpers for GCP scripts. Source this file; do not run directly.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT/scripts/gcp_env" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/scripts/gcp_env"
elif [[ -f "$ROOT/scripts/gcp_env.example" ]]; then
  echo "NOTE: copy scripts/gcp_env.example → scripts/gcp_env and edit, or export vars."
fi

: "${GCP_PROJECT:=fluxtrader}"
: "${GCP_ZONE:=me-central1-b}"
: "${GCP_ALWAYS_ON:=fluxtrader-1}"
: "${GCP_TRAIN_INSTANCE:=fluxtrader-train}"
: "${GCP_TRAIN_MACHINE:=e2-standard-2}"
: "${REMOTE_REPO:=~/trading_agent}"
: "${REMOTE_EXPORT:=~/fluxtrader-train-export}"
: "${TRAIN_EPOCHS:=40}"
: "${TRAIN_SEQ_LEN:=64}"
: "${TRAIN_DEVICE:=cpu}"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

require_gcloud() {
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "ERROR: gcloud not found. Install Google Cloud SDK and: gcloud auth login"
    exit 1
  fi
  gcloud config set project "$GCP_PROJECT" >/dev/null
}

gssh() {
  local instance="$1"
  shift
  gcloud compute ssh "$instance" --project="$GCP_PROJECT" --zone="$GCP_ZONE" --command="$*"
}

gscp_to() {
  local instance="$1"
  local src="$2"
  local dst="$3"
  gcloud compute scp --project="$GCP_PROJECT" --zone="$GCP_ZONE" --recurse "$src" "${instance}:${dst}"
}

gscp_from() {
  local instance="$1"
  local src="$2"
  local dst="$3"
  gcloud compute scp --project="$GCP_PROJECT" --zone="$GCP_ZONE" --recurse "${instance}:${src}" "$dst"
}

echo_cfg() {
  echo "GCP_PROJECT=$GCP_PROJECT ZONE=$GCP_ZONE"
  echo "ALWAYS_ON=$GCP_ALWAYS_ON TRAIN=$GCP_TRAIN_INSTANCE ($GCP_TRAIN_MACHINE)"
}
