#!/usr/bin/env bash
# V2 STEP 1/3 — one command: create train VM, run a self-contained job, self-clean.
#
# The train VM job (in remote tmux 'fluxtrain'):
#   1. git clone GIT_REMOTE @ GIT_REF     (reproducible code)
#   2. pull fresh DB dump from the bucket (produced here from always-on)
#   3. restore Postgres on the train VM
#   4. train_m2.py + eval_m2.py
#   5. push checkpoint + full log + status marker to the bucket
#   6. self-DELETE on success / self-STOP on failure   (never left billing)
#
# Returns immediately. Watch:   ./scripts/gcp_status.sh
# Promote when DONE:            ./scripts/gcp_promote.sh
#
#   ./scripts/gcp_train.sh [epochs] [seq_len]
#   TRAIN_PAIRS=BTCUSDT,ETHUSDT ./scripts/gcp_train.sh 60 128
#   KEEP_VM=1 ./scripts/gcp_train.sh          # debug: don't auto delete/stop VM
#
# One-time bucket setup (run once):
#   gcloud storage buckets create "$GCS_BUCKET" --location="$GCP_REGION" \
#     --uniform-bucket-level-access
#   # let the train VM's service account read/write the bucket AND delete itself:
#   SA=$(gcloud compute instances describe "$GCP_TRAIN_INSTANCE" --zone="$GCP_ZONE" \
#        --format='get(serviceAccounts[0].email)')   # or the default compute SA
#   gcloud storage buckets add-iam-policy-binding "$GCS_BUCKET" \
#     --member="serviceAccount:$SA" --role=roles/storage.objectAdmin
#   gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
#     --member="serviceAccount:$SA" --role=roles/compute.instanceAdmin.v1
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
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
R="\$HOME/${REMOTE_REPO_NAME}"

PAIRS_FLAG=""
if [[ -n "$PAIRS_ARG" ]]; then PAIRS_FLAG="--pairs ${PAIRS_ARG}"; fi

echo ""
echo "==> run_id=$RUN_ID  epochs=$EPOCHS seq=$SEQ_LEN horizons=$HORIZONS primary=${PRIMARY}m pairs=${PAIRS_ARG:-DB-whitelist}"

# --- 0. sanity: bucket reachable -------------------------------------------------
if ! gcloud storage ls "$GCS_BUCKET" >/dev/null 2>&1; then
  echo "ERROR: bucket $GCS_BUCKET not accessible."
  echo "Create it once (same region as VMs):"
  echo "  gcloud storage buckets create $GCS_BUCKET --location=$GCP_REGION --uniform-bucket-level-access"
  exit 1
fi

# --- 1. ensure train VM exists (create w/ cloud-platform scope) ------------------
echo ""
echo "==> ensure train VM $GCP_TRAIN_INSTANCE"
if gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
     --project="$GCP_PROJECT" --zone="$GCP_ZONE" >/dev/null 2>&1; then
  STATUS=$(gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)')
  echo "    exists (status=$STATUS)"
  if [[ "$STATUS" != "RUNNING" ]]; then
    gcloud compute instances start "$GCP_TRAIN_INSTANCE" \
      --project="$GCP_PROJECT" --zone="$GCP_ZONE"
  fi
else
  echo "    creating $GCP_TRAIN_MACHINE (scopes=cloud-platform) ..."
  gcloud compute instances create "$GCP_TRAIN_INSTANCE" \
    --project="$GCP_PROJECT" \
    --zone="$GCP_ZONE" \
    --machine-type="$GCP_TRAIN_MACHINE" \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=50GB \
    --boot-disk-type=pd-balanced \
    --scopes=cloud-platform \
    --tags=fluxtrader-train \
    --metadata=startup-script='#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git tmux
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
for u in $(ls /home 2>/dev/null); do usermod -aG docker "$u" || true; done
touch /var/tmp/fluxtrader-docker-ready
'
fi

echo "==> waiting for SSH ..."
for _ in $(seq 1 40); do
  if gssh "$GCP_TRAIN_INSTANCE" "echo ok" >/dev/null 2>&1; then break; fi
  sleep 5
done
echo "==> waiting for Docker (first boot 1–3 min) ..."
for i in $(seq 1 60); do
  if gssh "$GCP_TRAIN_INSTANCE" "docker compose version" >/dev/null 2>&1; then
    echo "    Docker OK"; break
  fi
  if [[ "$i" -eq 60 ]]; then echo "ERROR: Docker not ready."; exit 1; fi
  sleep 5
done
gssh "$GCP_TRAIN_INSTANCE" \
  "sudo usermod -aG docker \$USER; sudo chmod 666 /var/run/docker.sock 2>/dev/null || true; command -v git >/dev/null || sudo apt-get install -y git; command -v tmux >/dev/null || sudo apt-get install -y tmux"

# --- 2. fresh dump: always-on -> bucket -----------------------------------------
echo ""
echo "==> fresh dump from $GCP_ALWAYS_ON → $GCS_BUCKET/dumps/$RUN_ID.sql.gz"
gssh "$GCP_ALWAYS_ON" "set -e
  cd $R
  docker compose exec -T postgres pg_isready -U fluxtrader
  TFLAGS=''
  for t in $DUMP_TABLES; do TFLAGS=\"\$TFLAGS -t \$t\"; done
  docker compose exec -T postgres bash -c \"pg_dump -U fluxtrader -d fluxtrader --format=plain --no-owner --no-acl \$TFLAGS\" \
    | gzip > /tmp/fluxtrader_train.sql.gz
  ls -lh /tmp/fluxtrader_train.sql.gz
  gcloud storage cp /tmp/fluxtrader_train.sql.gz $GCS_BUCKET/dumps/$RUN_ID.sql.gz
  gcloud storage cp $GCS_BUCKET/dumps/$RUN_ID.sql.gz $GCS_BUCKET/dumps/latest.sql.gz
"

# --- 3. write remote self-cleaning job and launch in tmux ------------------------
# Mac-side values are injected as a small exported prelude; the quoted heredoc
# body then runs verbatim on the VM (so $SELF / metadata stay literal).
echo ""
echo "==> launching self-cleaning train job in remote tmux 'fluxtrain'"
gssh "$GCP_TRAIN_INSTANCE" "cat > \$HOME/run_flux_train.sh <<PRELUDE
#!/bin/bash
export RUN_ID='$RUN_ID'
export GCS_BUCKET='$GCS_BUCKET'
export GIT_REMOTE='$GIT_REMOTE'
export GIT_REF='$GIT_REF'
export REMOTE_REPO_NAME='$REMOTE_REPO_NAME'
export EPOCHS='$EPOCHS'
export SEQ_LEN='$SEQ_LEN'
export HORIZONS='$HORIZONS'
export PRIMARY='$PRIMARY'
export TRAIN_DEVICE='$TRAIN_DEVICE'
export PAIRS_FLAG='$PAIRS_FLAG'
export KEEP_VM='$KEEP_VM'
export MODEL_VOLUME_NAME='$MODEL_VOLUME_NAME'
PRELUDE
cat >> \$HOME/run_flux_train.sh << 'ENDSCRIPT'
set -Eeuo pipefail
LOG=\$HOME/train_m2.log
: > \"\$LOG\"
exec > >(tee -a \"\$LOG\") 2>&1

meta() { curl -s -H 'Metadata-Flavor: Google' \"http://metadata.google.internal/computeMetadata/v1/instance/\$1\"; }

finish() {
  local status=\"\$1\"
  echo \"=== finish: \$status \$(date -u) ===\"
  gcloud storage cp \"\$LOG\" \"\$GCS_BUCKET/logs/\$RUN_ID.log\" || true
  printf '{\"status\":\"%s\",\"git_sha\":\"%s\",\"run\":\"%s\",\"ended\":\"%s\"}\n' \
    \"\$status\" \"\${GIT_SHA:-}\" \"\$RUN_ID\" \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > /tmp/status.json
  gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/\$RUN_ID.json\" || true
  gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/latest.json\" || true

  local self zone
  self=\"\$(meta name)\"
  zone=\"\$(basename \"\$(meta zone)\")\"
  if [[ \"\${KEEP_VM:-0}\" == \"1\" ]]; then
    echo \"KEEP_VM=1 → leaving VM \$self running\"; return 0
  fi
  if [[ \"\$status\" == \"DONE\" ]]; then
    echo \"success → deleting self (\$self)\"
    gcloud compute instances delete \"\$self\" --zone=\"\$zone\" --quiet || true
  else
    echo \"failure → stopping self (\$self) for debugging\"
    gcloud compute instances stop \"\$self\" --zone=\"\$zone\" --quiet || true
  fi
}
trap 'code=\$?; finish \"\$([[ \$code -eq 0 ]] && echo DONE || echo FAILED)\"' EXIT

# Publish a RUNNING marker immediately so gcp_status.sh reflects THIS run while it
# trains, instead of showing the previous run's stale DONE until the finish trap.
printf '{\"status\":\"RUNNING\",\"git_sha\":\"%s\",\"run\":\"%s\",\"started\":\"%s\"}\n' \
  \"\${GIT_SHA:-}\" \"\$RUN_ID\" \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > /tmp/status.json
gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/\$RUN_ID.json\" || true
gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/latest.json\" || true

echo \"=== train start \$(date -u) run=\$RUN_ID ===\"

echo \"=== checkout \$GIT_REMOTE @ \$GIT_REF ===\"
rm -rf \$HOME/\$REMOTE_REPO_NAME
git clone --branch \"\$GIT_REF\" \"\$GIT_REMOTE\" \$HOME/\$REMOTE_REPO_NAME \
  || git clone \"\$GIT_REMOTE\" \$HOME/\$REMOTE_REPO_NAME
cd \$HOME/\$REMOTE_REPO_NAME
git checkout \"\$GIT_REF\"
GIT_SHA=\"\$(git rev-parse HEAD)\"
echo \"git_sha=\$GIT_SHA\"

echo \"=== pull dump from bucket ===\"
mkdir -p \$HOME/fluxtrader-train-export
gcloud storage cp \"\$GCS_BUCKET/dumps/latest.sql.gz\" \$HOME/fluxtrader-train-export/fluxtrader_train.sql.gz

echo \"=== reset + restore postgres on TRAIN vm ===\"
docker compose down -v || true
docker compose up -d postgres
for i in \$(seq 1 60); do docker compose exec -T postgres pg_isready -U fluxtrader && break; sleep 2; done
for i in \$(seq 1 30); do docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -c 'SELECT 1' >/dev/null 2>&1 && break; sleep 2; done
sleep 2
gunzip -c \$HOME/fluxtrader-train-export/fluxtrader_train.sql.gz \
  | docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -v ON_ERROR_STOP=0

CANDLES=\$(docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"SELECT count(*) FROM candles;\" 2>/dev/null | tr -d '[:space:]' || true)
BOOK=\$(docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"SELECT count(*) FROM orderbook_snapshots;\" 2>/dev/null | tr -d '[:space:]' || true)
echo \"candles=\$CANDLES book=\$BOOK\"
if ! [[ \"\$CANDLES\" =~ ^[0-9]+\$ ]] || [[ \"\$CANDLES\" -lt 1000 ]]; then echo \"ERROR: restore failed (candles=\$CANDLES)\"; exit 1; fi
if ! [[ \"\$BOOK\" =~ ^[0-9]+\$ ]] || [[ \"\$BOOK\" -lt 100 ]]; then echo \"ERROR: restore failed (book=\$BOOK)\"; exit 1; fi

docker volume create \$MODEL_VOLUME_NAME >/dev/null 2>&1 || true

echo \"=== train_m2 epochs=\$EPOCHS seq=\$SEQ_LEN horizons=\$HORIZONS primary=\$PRIMARY ===\"
docker compose --profile ml run --rm \
  -e HORIZONS_MINUTES=\$HORIZONS -e PRIMARY_HORIZON=\$PRIMARY -e SEQ_LEN=\$SEQ_LEN \
  -e FLUX_GIT_SHA=\$GIT_SHA \
  ml_trainer python train_m2.py --device \$TRAIN_DEVICE --epochs \$EPOCHS --seq-len \$SEQ_LEN \
    --horizons \$HORIZONS --primary \$PRIMARY \$PAIRS_FLAG

echo \"=== eval_m2 ===\"
docker compose --profile ml run --rm \
  -e HORIZONS_MINUTES=\$HORIZONS -e PRIMARY_HORIZON=\$PRIMARY -e SEQ_LEN=\$SEQ_LEN \
  ml_trainer python eval_m2.py --checkpoint /models/m2_multi.pt --device \$TRAIN_DEVICE \
    --gate 0.35,0.4,0.45,0.5,0.55,0.6 || true

echo \"=== push checkpoint to bucket ===\"
docker run --rm -v \$MODEL_VOLUME_NAME:/models -v \$HOME:/out alpine \
  sh -c 'cp /models/m2_multi.pt /out/m2_multi.pt'
CKPT_KEY=\"checkpoints/m2_multi_\${RUN_ID}_\${GIT_SHA:0:8}.pt\"
gcloud storage cp \$HOME/m2_multi.pt \"\$GCS_BUCKET/\$CKPT_KEY\"
gcloud storage cp \"\$GCS_BUCKET/\$CKPT_KEY\" \"\$GCS_BUCKET/checkpoints/latest.pt\"
echo \"checkpoint → \$GCS_BUCKET/\$CKPT_KEY\"

echo \"=== train finished \$(date -u) ===\"
# trap → finish DONE → uploads log+status, deletes VM
ENDSCRIPT
chmod +x \$HOME/run_flux_train.sh
tmux kill-session -t fluxtrain 2>/dev/null || true
tmux new-session -d -s fluxtrain \"bash \$HOME/run_flux_train.sh\"
echo 'tmux session fluxtrain started'
tmux ls
sleep 8
echo '--- log so far ---'
tail -n 30 \$HOME/train_m2.log 2>/dev/null || echo '(starting...)'
"

echo ""
echo "OK — training started on $GCP_TRAIN_INSTANCE (run=$RUN_ID)."
echo "The VM will DELETE itself on success, STOP itself on failure (KEEP_VM=$KEEP_VM)."
echo "Mac may sleep now. Monitor:  ./scripts/gcp_status.sh"
echo "When DONE:                   ./scripts/gcp_promote.sh"
