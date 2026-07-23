#!/usr/bin/env bash
# STEP 3/5 — Upload dump + code, restore DB, start train in tmux on train VM.
# Returns quickly. Training continues if Mac sleeps.
#
#   ./scripts/gcp_3_start_train.sh [epochs] [seq_len]
#   TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT ./scripts/gcp_3_start_train.sh 40 64
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

EPOCHS="${1:-$TRAIN_EPOCHS}"
SEQ_LEN="${2:-$TRAIN_SEQ_LEN}"
PAIRS_ARG="${TRAIN_PAIRS:-}"
HORIZONS="${TRAIN_HORIZONS:-5,30,60}"
PRIMARY="${TRAIN_PRIMARY:-30}"

DUMP_GZ="$EXPORT_DIR/fluxtrader_train.sql.gz"
if [[ ! -f "$DUMP_GZ" ]]; then
  echo "ERROR: missing $DUMP_GZ"
  echo "Run: ./scripts/gcp_1_dump.sh first (new plain-SQL dump format)"
  exit 1
fi

if ! gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
  --project="$GCP_PROJECT" --zone="$GCP_ZONE" >/dev/null 2>&1; then
  echo "ERROR: train VM missing — run ./scripts/gcp_2_create_train_vm.sh first"
  exit 1
fi

echo ""
echo "==> STEP 3: upload + start train in remote tmux"
echo "    epochs=$EPOCHS seq=$SEQ_LEN horizons=$HORIZONS primary=${PRIMARY}m pairs=${PAIRS_ARG:-DB-whitelist}"

gcloud compute scp --project="$GCP_PROJECT" --zone="$GCP_ZONE" --recurse \
  "$ROOT/docker-compose.yml" "$ROOT/ml" "$ROOT/scripts" \
  "${GCP_TRAIN_INSTANCE}:~/trading_agent_upload/"

gssh "$GCP_TRAIN_INSTANCE" "set -e
  mkdir -p \$HOME/${REMOTE_REPO_NAME} \$HOME/fluxtrader-train-export
  cp -a \$HOME/trading_agent_upload/docker-compose.yml \$HOME/${REMOTE_REPO_NAME}/
  rm -rf \$HOME/${REMOTE_REPO_NAME}/ml \$HOME/${REMOTE_REPO_NAME}/scripts
  cp -a \$HOME/trading_agent_upload/ml \$HOME/${REMOTE_REPO_NAME}/ml
  cp -a \$HOME/trading_agent_upload/scripts \$HOME/${REMOTE_REPO_NAME}/scripts
"

gscp_to "$GCP_TRAIN_INSTANCE" "$DUMP_GZ" "fluxtrader-train-export/fluxtrader_train.sql.gz"

PAIRS_FLAG=""
if [[ -n "$PAIRS_ARG" ]]; then
  PAIRS_FLAG="--pairs ${PAIRS_ARG}"
fi

# Remote train script — plain SQL restore into fresh volume (reliable)
# Local vars expanded here; remote heredoc body is fixed after expansion.
gssh "$GCP_TRAIN_INSTANCE" "cat > \$HOME/run_flux_train.sh << 'ENDSCRIPT'
#!/bin/bash
set -euo pipefail
cd \$HOME/trading_agent
LOG=\$HOME/train_m2.log
rm -f \$HOME/train_m2.status \$HOME/m2_multi.pt
: > \$LOG
exec > >(tee -a \"\$LOG\") 2>&1

echo \"=== train start \$(date -u) ===\"

echo \"=== reset postgres on TRAIN vm only ===\"
docker compose down -v || true
docker compose up -d postgres
for i in \$(seq 1 60); do
  docker compose exec -T postgres pg_isready -U fluxtrader && break
  sleep 2
done
# wait until superuser can connect to fluxtrader db
for i in \$(seq 1 30); do
  docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -c 'SELECT 1' >/dev/null 2>&1 && break
  sleep 2
done
sleep 2

echo \"=== restore plain SQL dump ===\"
gunzip -c \$HOME/fluxtrader-train-export/fluxtrader_train.sql.gz \
  | docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -v ON_ERROR_STOP=0

echo \"=== verify data ===\"
CANDLES=\$(docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"SELECT count(*) FROM candles;\" | tr -d '[:space:]')
BOOK=\$(docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"SELECT count(*) FROM orderbook_snapshots;\" | tr -d '[:space:]')
echo \"candles=\$CANDLES book=\$BOOK\"
if ! [[ \"\$CANDLES\" =~ ^[0-9]+\$ ]] || [[ \"\$CANDLES\" -lt 1000 ]]; then
  echo \"ERROR: restore failed (candles=\$CANDLES)\"
  exit 1
fi
if ! [[ \"\$BOOK\" =~ ^[0-9]+\$ ]] || [[ \"\$BOOK\" -lt 100 ]]; then
  echo \"ERROR: restore failed (book=\$BOOK)\"
  exit 1
fi

docker volume create trading_agent_model_weights 2>/dev/null || true

echo \"=== train_m2 epochs=${EPOCHS} seq=${SEQ_LEN} horizons=${HORIZONS} primary=${PRIMARY} ===\"
docker compose --profile ml run --rm \\
  -e HORIZONS_MINUTES=${HORIZONS} \\
  -e PRIMARY_HORIZON=${PRIMARY} \\
  -e SEQ_LEN=${SEQ_LEN} \\
  ml_trainer \\
  python train_m2.py --device ${TRAIN_DEVICE} --epochs ${EPOCHS} --seq-len ${SEQ_LEN} \\
    --horizons ${HORIZONS} --primary ${PRIMARY} ${PAIRS_FLAG}

echo \"=== eval_m2 ===\"
docker compose --profile ml run --rm \\
  -e HORIZONS_MINUTES=${HORIZONS} \\
  -e PRIMARY_HORIZON=${PRIMARY} \\
  -e SEQ_LEN=${SEQ_LEN} \\
  ml_trainer \\
  python eval_m2.py --checkpoint /models/m2_multi.pt --device ${TRAIN_DEVICE} \\
  --gate 0.35,0.4,0.45,0.5,0.55,0.6 || true

docker run --rm -v trading_agent_model_weights:/models -v \$HOME:/out alpine \\
  sh -c 'cp /models/m2_multi.pt /out/m2_multi.pt && ls -la /out/m2_multi.pt'

echo DONE > \$HOME/train_m2.status
echo \"=== train finished \$(date -u) ===\"
ENDSCRIPT
chmod +x \$HOME/run_flux_train.sh
tmux kill-session -t fluxtrain 2>/dev/null || true
rm -f \$HOME/train_m2.status \$HOME/m2_multi.pt
tmux new-session -d -s fluxtrain \"bash \$HOME/run_flux_train.sh\"
echo \"tmux session fluxtrain started\"
tmux ls
sleep 8
echo '--- log so far ---'
tail -n 40 \$HOME/train_m2.log 2>/dev/null || echo '(starting...)'
"

echo ""
echo "OK — training started on $GCP_TRAIN_INSTANCE (tmux: fluxtrain)."
echo "Mac may sleep. Monitor:  ./scripts/gcp_4_status.sh"
echo "When DONE:            ./scripts/gcp_5_finish.sh"
