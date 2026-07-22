#!/usr/bin/env bash
# STEP 3/5 — Upload dump + code, restore DB, start training INSIDE tmux on the train VM.
# This script returns quickly. Training continues on GCP even if your Mac sleeps.
#
# Optional args:  ./scripts/gcp_3_start_train.sh [epochs] [seq_len]
# Optional env:   TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

EPOCHS="${1:-$TRAIN_EPOCHS}"
SEQ_LEN="${2:-$TRAIN_SEQ_LEN}"
PAIRS_ARG="${TRAIN_PAIRS:-}"
R="\$HOME/${REMOTE_REPO_NAME}"

if [[ ! -f "$EXPORT_DIR/fluxtrader.dump" ]]; then
  echo "ERROR: missing $EXPORT_DIR/fluxtrader.dump — run ./scripts/gcp_1_dump.sh first"
  exit 1
fi

if ! gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
  --project="$GCP_PROJECT" --zone="$GCP_ZONE" >/dev/null 2>&1; then
  echo "ERROR: train VM missing — run ./scripts/gcp_2_create_train_vm.sh first"
  exit 1
fi

echo ""
echo "==> STEP 3: upload code + dump, start train in remote tmux (epochs=$EPOCHS seq=$SEQ_LEN)"

# Sync code
gcloud compute scp --project="$GCP_PROJECT" --zone="$GCP_ZONE" --recurse \
  "$ROOT/docker-compose.yml" "$ROOT/ml" "$ROOT/scripts" \
  "${GCP_TRAIN_INSTANCE}:~/trading_agent_upload/"

gssh "$GCP_TRAIN_INSTANCE" "set -e
  mkdir -p $R \$HOME/fluxtrader-train-export
  cp -a \$HOME/trading_agent_upload/docker-compose.yml $R/
  rm -rf $R/ml $R/scripts
  cp -a \$HOME/trading_agent_upload/ml $R/ml
  cp -a \$HOME/trading_agent_upload/scripts $R/scripts
"

gscp_to "$GCP_TRAIN_INSTANCE" "$EXPORT_DIR/fluxtrader.dump" "fluxtrader-train-export/fluxtrader.dump"

PAIRS_FLAG=""
if [[ -n "$PAIRS_ARG" ]]; then
  PAIRS_FLAG="--pairs $PAIRS_ARG"
fi

# Remote runner script (executed inside tmux)
gssh "$GCP_TRAIN_INSTANCE" "cat > \$HOME/run_flux_train.sh << 'EOS'
#!/bin/bash
set -euo pipefail
cd \$HOME/${REMOTE_REPO_NAME}
LOG=\$HOME/train_m2.log
exec > >(tee -a \"\$LOG\") 2>&1
echo \"=== train start \$(date -u) ===\"
docker compose up -d postgres
for i in \$(seq 1 60); do
  docker compose exec -T postgres pg_isready -U fluxtrader && break
  sleep 2
done
docker compose cp \$HOME/fluxtrader-train-export/fluxtrader.dump postgres:/tmp/fluxtrader.dump
docker compose exec -T postgres \
  pg_restore -U fluxtrader -d fluxtrader --clean --if-exists --no-owner --no-acl \
  /tmp/fluxtrader.dump || true
docker compose exec -T postgres rm -f /tmp/fluxtrader.dump
docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -c \
  \"SELECT count(*) AS candles FROM candles; SELECT count(*) AS book FROM orderbook_snapshots;\"
docker volume create trading_agent_model_weights 2>/dev/null || true
echo \"=== train_m2 epochs=${EPOCHS} seq=${SEQ_LEN} ===\"
docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device ${TRAIN_DEVICE} --epochs ${EPOCHS} --seq-len ${SEQ_LEN} ${PAIRS_FLAG}
echo \"=== eval_m2 ===\"
docker compose --profile ml run --rm ml_trainer \
  python eval_m2.py --checkpoint /models/m2_multi.pt --device ${TRAIN_DEVICE} \
  --gate 0.35,0.4,0.45,0.5,0.55,0.6 || true
docker run --rm -v trading_agent_model_weights:/models -v \$HOME:/out alpine \
  sh -c 'cp /models/m2_multi.pt /out/m2_multi.pt && ls -la /out/m2_multi.pt'
echo DONE > \$HOME/train_m2.status
echo \"=== train finished \$(date -u) ===\"
EOS
chmod +x \$HOME/run_flux_train.sh
rm -f \$HOME/train_m2.status \$HOME/m2_multi.pt
# kill old session if any
tmux kill-session -t fluxtrain 2>/dev/null || true
tmux new-session -d -s fluxtrain \"bash \$HOME/run_flux_train.sh\"
echo \"tmux session fluxtrain started\"
tmux ls
"

echo ""
echo "OK — training is running on $GCP_TRAIN_INSTANCE inside tmux (session: fluxtrain)."
echo "Your Mac can sleep or disconnect safely."
echo ""
echo "Monitor anytime:"
echo "  ./scripts/gcp_4_status.sh"
echo ""
echo "When status says DONE:"
echo "  ./scripts/gcp_5_finish.sh"
