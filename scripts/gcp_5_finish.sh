#!/usr/bin/env bash
# STEP 5/5 — Download checkpoint, install on always-on, delete train VM
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

KEEP_VM=0
if [[ "${1:-}" == "--keep-vm" ]]; then
  KEEP_VM=1
fi

R="\$HOME/${REMOTE_REPO_NAME}"
mkdir -p "$EXPORT_DIR"

echo ""
echo "==> STEP 5: finish (promote checkpoint, cleanup)"

if ! gssh "$GCP_TRAIN_INSTANCE" "test -f \$HOME/train_m2.status && test -f \$HOME/m2_multi.pt" 2>/dev/null; then
  echo "ERROR: training not finished (missing train_m2.status or m2_multi.pt on train VM)."
  echo "Check: ./scripts/gcp_4_status.sh"
  exit 1
fi

echo "==> download checkpoint from train VM ..."
gscp_from "$GCP_TRAIN_INSTANCE" "m2_multi.pt" "$EXPORT_DIR/m2_multi.pt"
# also try log
gscp_from "$GCP_TRAIN_INSTANCE" "train_m2.log" "$EXPORT_DIR/train_m2.log" 2>/dev/null || true
ls -lh "$EXPORT_DIR/m2_multi.pt"

echo "==> install checkpoint on always-on ($GCP_ALWAYS_ON) ..."
gscp_to "$GCP_ALWAYS_ON" "$EXPORT_DIR/m2_multi.pt" /tmp/m2_multi.pt
gssh "$GCP_ALWAYS_ON" "set -e
  cd $R
  VOL=\$(docker volume ls -q | grep -E 'model_weights\$' | head -1)
  if [[ -z \"\$VOL\" ]]; then
    docker volume create trading_agent_model_weights
    VOL=trading_agent_model_weights
  fi
  docker run --rm -v \"\$VOL:/models\" -v /tmp:/in:ro alpine \
    sh -c 'cp /in/m2_multi.pt /models/m2_multi.pt && ls -la /models/m2_multi.pt'
  if docker compose ps 2>/dev/null | grep -q ml_inference; then
    docker compose restart ml_inference || true
    echo ml_inference restarted
  else
    echo 'ml_inference not running — optional: docker compose up -d ml_inference'
  fi
"

if [[ "$KEEP_VM" -eq 0 ]]; then
  echo "==> deleting train VM $GCP_TRAIN_INSTANCE ..."
  gcloud compute instances delete "$GCP_TRAIN_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" --quiet
  echo "    deleted."
else
  echo "==> keeping train VM (--keep-vm). Delete later:"
  echo "    gcloud compute instances delete $GCP_TRAIN_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT --quiet"
fi

echo ""
echo "OK — training pipeline finished."
echo "  Checkpoint on always-on model volume + copy at $EXPORT_DIR/m2_multi.pt"
echo "  Log copy (if any): $EXPORT_DIR/train_m2.log"
echo "  Always-on collector was not stopped."
