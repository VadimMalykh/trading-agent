#!/usr/bin/env bash
# Shared helpers — sourced by gcp_1..gcp_5. Do not run directly.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/google-cloud-sdk/bin:$HOME/Downloads/google-cloud-sdk/bin:$PATH"

if [[ -f "$ROOT/scripts/gcp_env" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/scripts/gcp_env"
else
  echo "NOTE: optional config at scripts/gcp_env (copy from gcp_env.example)"
fi

: "${GCP_PROJECT:=fluxtrader}"
: "${GCP_ZONE:=me-central1-b}"
: "${GCP_REGION:=${GCP_ZONE%-*}}"          # me-central1-b -> me-central1
: "${GCP_ALWAYS_ON:=fluxtrader-1}"
: "${GCP_TRAIN_INSTANCE:=fluxtrader-train}"
: "${GCP_TRAIN_MACHINE:=e2-standard-4}"
: "${REMOTE_REPO_NAME:=trading_agent}"
: "${TRAIN_EPOCHS:=60}"
: "${TRAIN_SEQ_LEN:=128}"
: "${TRAIN_DEVICE:=cpu}"
# M2 defaults (Phase 1+2): 5/30/60 heads, primary 30m, majors preferred
: "${TRAIN_HORIZONS:=5,30,60}"
: "${TRAIN_PRIMARY:=30}"
# 6-pair set: 3 majors + DOGE/WLD/HYPE. Data audit (2026-07-24) confirmed all six
# have full ~180d 1m candles. Microstructure (book/trades/OI) spans only ~days for
# every pair (collector started recently) → zero-filled for most of history; the
# model tolerates missing microstructure. See docs/NEXT_TRAINING_PLAN.md.
: "${TRAIN_PAIRS:=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT}"

# --- V2 pipeline: artifacts via GCS bucket, code via git ---------------------
# Single-region bucket in the SAME region as the VMs (else you pay egress).
: "${GCS_BUCKET:=gs://fluxtrader-train-artifacts}"
# Reproducible code source. HTTPS so the VM can clone without your SSH key.
# For a PRIVATE repo, use: https://<PAT>@github.com/VadimMalykh/trading-agent.git
: "${GIT_REMOTE:=https://github.com/VadimMalykh/trading-agent.git}"
: "${GIT_REF:=main}"                       # branch or commit SHA to train/serve
# Keep the train VM alive after the job (1 = never auto delete/stop). Debug only.
: "${KEEP_VM:=0}"

# Local folder for OPTIONAL backup copies (--local-copy). Not on the hot path.
: "${EXPORT_DIR:=$HOME/fluxtrader-train-export}"

# App tables dumped for training / settings (not Timescale internals)
: "${DUMP_TABLES:=candles orderbook_snapshots market_trades funding_rates open_interest liquidations app_settings positions trades schema_migrations}"

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
  echo "project=$GCP_PROJECT  zone=$GCP_ZONE  region=$GCP_REGION"
  echo "always-on=$GCP_ALWAYS_ON  train-vm=$GCP_TRAIN_INSTANCE ($GCP_TRAIN_MACHINE)"
  echo "bucket=$GCS_BUCKET"
  echo "git=$GIT_REMOTE @ $GIT_REF"
  echo "train: epochs=$TRAIN_EPOCHS seq=$TRAIN_SEQ_LEN device=$TRAIN_DEVICE"
  echo "       horizons=$TRAIN_HORIZONS primary=${TRAIN_PRIMARY}m pairs=$TRAIN_PAIRS"
}
