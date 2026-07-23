#!/usr/bin/env bash
# Shared helpers — sourced by gcp_1..gcp_5. Do not run directly.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ -f "$ROOT/scripts/gcp_env" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/scripts/gcp_env"
else
  echo "NOTE: optional config at scripts/gcp_env (copy from gcp_env.example)"
fi

: "${GCP_PROJECT:=fluxtrader}"
: "${GCP_ZONE:=me-central1-b}"
: "${GCP_ALWAYS_ON:=fluxtrader-1}"
: "${GCP_TRAIN_INSTANCE:=fluxtrader-train}"
: "${GCP_TRAIN_MACHINE:=e2-standard-2}"
: "${REMOTE_REPO_NAME:=trading_agent}"
: "${TRAIN_EPOCHS:=40}"
: "${TRAIN_SEQ_LEN:=64}"
: "${TRAIN_DEVICE:=cpu}"
# M2 defaults (Phase 1+2): 5/30/60 heads, primary 30m, majors preferred
: "${TRAIN_HORIZONS:=5,30,60}"
: "${TRAIN_PRIMARY:=30}"
: "${TRAIN_PAIRS:=BTCUSDT,ETHUSDT,SOLUSDT}"

# Local folder for dumps/checkpoints (on your Mac)
: "${EXPORT_DIR:=$HOME/fluxtrader-train-export}"

require_gcloud() {
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "ERROR: gcloud not found. brew install --cask google-cloud-sdk && gcloud auth login"
    exit 1
  fi
  gcloud config set project "$GCP_PROJECT" >/dev/null
}

gssh() {
  gcloud compute ssh "$1" --project="$GCP_PROJECT" --zone="$GCP_ZONE" --command="$2"
}

gscp_to() {
  gcloud compute scp --project="$GCP_PROJECT" --zone="$GCP_ZONE" --recurse "$2" "$1:$3"
}

gscp_from() {
  gcloud compute scp --project="$GCP_PROJECT" --zone="$GCP_ZONE" --recurse "$1:$2" "$3"
}

# Compose declares model_weights as external with this exact name
MODEL_VOLUME_NAME="${MODEL_VOLUME_NAME:-trading_agent_model_weights}"

echo_cfg() {
  echo "project=$GCP_PROJECT  zone=$GCP_ZONE"
  echo "always-on=$GCP_ALWAYS_ON  train-vm=$GCP_TRAIN_INSTANCE ($GCP_TRAIN_MACHINE)"
  echo "export-dir=$EXPORT_DIR"
  echo "train: epochs=$TRAIN_EPOCHS seq=$TRAIN_SEQ_LEN device=$TRAIN_DEVICE"
  echo "       horizons=$TRAIN_HORIZONS primary=${TRAIN_PRIMARY}m pairs=$TRAIN_PAIRS"
}
