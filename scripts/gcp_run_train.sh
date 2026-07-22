#!/usr/bin/env bash
# Upload dump + repo bits to train VM, restore DB, run train_m2 + eval_m2, pull checkpoint home.
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

EXPORT_DIR="${EXPORT_DIR:-$HOME/fluxtrader-train-export}"
EPOCHS="${1:-$TRAIN_EPOCHS}"
SEQ_LEN="${2:-$TRAIN_SEQ_LEN}"
PAIRS_ARG="${TRAIN_PAIRS:-}"

if [[ ! -f "$EXPORT_DIR/fluxtrader.dump" ]]; then
  echo "ERROR: missing $EXPORT_DIR/fluxtrader.dump"
  echo "Run: ./scripts/gcp_dump_always_on.sh first"
  exit 1
fi

if ! gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
  --project="$GCP_PROJECT" --zone="$GCP_ZONE" >/dev/null 2>&1; then
  echo "ERROR: train VM missing. Run: ./scripts/gcp_create_train_vm.sh"
  exit 1
fi

echo "==> Syncing repo (compose + ml + scripts) to train VM ..."
# lightweight sync — not full .git history required
gcloud compute scp --project="$GCP_PROJECT" --zone="$GCP_ZONE" --recurse \
  "$ROOT/docker-compose.yml" \
  "$ROOT/ml" \
  "$ROOT/scripts" \
  "${GCP_TRAIN_INSTANCE}:~/trading_agent_upload/"

gssh "$GCP_TRAIN_INSTANCE" "set -e
  mkdir -p $REMOTE_REPO
  cp -a ~/trading_agent_upload/docker-compose.yml $REMOTE_REPO/
  rm -rf $REMOTE_REPO/ml $REMOTE_REPO/scripts
  cp -a ~/trading_agent_upload/ml $REMOTE_REPO/ml
  cp -a ~/trading_agent_upload/scripts $REMOTE_REPO/scripts
  chmod +x $REMOTE_REPO/scripts/*.sh 2>/dev/null || true
"

echo "==> Uploading DB dump ..."
gssh "$GCP_TRAIN_INSTANCE" "mkdir -p $REMOTE_EXPORT"
gscp_to "$GCP_TRAIN_INSTANCE" "$EXPORT_DIR/fluxtrader.dump" "$REMOTE_EXPORT/fluxtrader.dump"

PAIRS_FLAG=""
if [[ -n "$PAIRS_ARG" ]]; then
  PAIRS_FLAG="--pairs $PAIRS_ARG"
fi

echo "==> On train VM: restore DB + train (epochs=$EPOCHS seq=$SEQ_LEN device=$TRAIN_DEVICE) ..."
gssh "$GCP_TRAIN_INSTANCE" "set -e
  cd $REMOTE_REPO
  docker compose up -d postgres
  for i in \$(seq 1 40); do
    docker compose exec -T postgres pg_isready -U fluxtrader && break
    sleep 2
  done
  docker compose cp $REMOTE_EXPORT/fluxtrader.dump postgres:/tmp/fluxtrader.dump
  docker compose exec -T postgres \
    pg_restore -U fluxtrader -d fluxtrader --clean --if-exists --no-owner --no-acl \
    /tmp/fluxtrader.dump || true
  docker compose exec -T postgres rm -f /tmp/fluxtrader.dump
  docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -c \
    \"SELECT count(*) AS candles FROM candles; SELECT count(*) AS book FROM orderbook_snapshots;\"

  # ensure model volume
  docker volume create trading_agent_model_weights 2>/dev/null || true

  echo '=== TRAIN START ==='
  docker compose --profile ml run --rm ml_trainer \
    python train_m2.py --device $TRAIN_DEVICE --epochs $EPOCHS --seq-len $SEQ_LEN $PAIRS_FLAG
  echo '=== TRAIN DONE ==='

  docker compose --profile ml run --rm ml_trainer \
    python eval_m2.py --checkpoint /models/m2_multi.pt --device $TRAIN_DEVICE \
    --gate 0.35,0.4,0.45,0.5,0.55,0.6 || true

  docker run --rm -v trading_agent_model_weights:/models -v /tmp:/out alpine \
    sh -c 'cp /models/m2_multi.pt /out/m2_multi.pt && ls -la /out/m2_multi.pt'
"

mkdir -p "$EXPORT_DIR"
echo "==> Downloading checkpoint ..."
gscp_from "$GCP_TRAIN_INSTANCE" /tmp/m2_multi.pt "$EXPORT_DIR/m2_multi.pt"
ls -lh "$EXPORT_DIR/m2_multi.pt"

echo "==> Train finished. Checkpoint at $EXPORT_DIR/m2_multi.pt"
echo "    Promote to always-on: ./scripts/gcp_promote_checkpoint.sh"
echo "    Delete train VM:      ./scripts/gcp_delete_train_vm.sh"
