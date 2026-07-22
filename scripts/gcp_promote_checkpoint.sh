#!/usr/bin/env bash
# Copy trained m2_multi.pt onto always-on model volume and restart ml_inference if present.
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

CKPT="${1:-${EXPORT_DIR:-$HOME/fluxtrader-train-export}/m2_multi.pt}"
if [[ ! -f "$CKPT" ]]; then
  echo "ERROR: checkpoint not found: $CKPT"
  echo "Usage: $0 [path/to/m2_multi.pt]"
  exit 1
fi

echo "==> Uploading $CKPT to $GCP_ALWAYS_ON ..."
gscp_to "$GCP_ALWAYS_ON" "$CKPT" /tmp/m2_multi.pt

gssh "$GCP_ALWAYS_ON" "set -e
  cd $REMOTE_REPO
  VOL=\$(docker volume ls -q | grep -E 'model_weights\$' | head -1)
  if [[ -z \"\$VOL\" ]]; then
    docker volume create trading_agent_model_weights
    VOL=trading_agent_model_weights
  fi
  docker run --rm -v \"\$VOL:/models\" -v /tmp:/in:ro alpine \
    sh -c 'cp /in/m2_multi.pt /models/m2_multi.pt && ls -la /models/m2_multi.pt'
  # restart inference if running
  if docker compose ps --status running 2>/dev/null | grep -q ml_inference; then
    docker compose restart ml_inference
    echo 'ml_inference restarted'
  else
    echo 'ml_inference not running — start with: docker compose up -d ml_inference'
  fi
"

echo "==> Checkpoint promoted on $GCP_ALWAYS_ON"
echo "    Check: curl -s http://127.0.0.1:8001/health  (on VM)"
