#!/usr/bin/env bash
# Microstructure audit on a THROWAWAY VM — one command, self-cleaning.
#
# Runs on its OWN instance ($GCP_AUDIT_INSTANCE, default fluxtrader-audit),
# SEPARATE from the training VM ($GCP_TRAIN_INSTANCE). They share nothing — no
# VM, Postgres, tmux session, or status marker — so an audit and a training run
# can happen AT THE SAME TIME. Audit is temporary/occasional; training is the
# permanent flow (scripts/gcp_train.sh) and is untouched by this script.
#
# The always-on VM (2GB) OOM-kills audit_microstructure.py: it loads full book+
# candle history for every pair into pandas and the deep-dive holds several
# float64 copies per feature. So instead of running there (and risking live
# collection), this mirrors scripts/gcp_train.sh:
#   1. fresh DB dump: always-on -> bucket
#   2. create (or reuse) the temp train VM
#   3. git clone GIT_REMOTE @ GIT_REF, pull dump, restore Postgres
#   4. run audit_microstructure.py inside the ml_trainer container
#   5. push console log + microstructure_audit.json + status marker to the bucket
#   6. self-DELETE on success / self-STOP on failure   (never left billing)
#
# Returns immediately. Watch / fetch results:
#   ./scripts/gcp_audit.sh                 # launch (default horizons 5,30,60)
#   ./scripts/gcp_audit.sh --pairs BTCUSDT,ETHUSDT --horizons 5,15,30,60
#   ./scripts/gcp_audit.sh --min-rows 2000 --no-deep
#   KEEP_VM=1 ./scripts/gcp_audit.sh       # debug: don't auto delete/stop VM
#
#   watch status:   ./scripts/gcp_audit.sh --status  (audit VM liveness + marker)
#   full log:       ./scripts/gcp_audit.sh --fetch   (log + JSON from bucket)
#   list runs:      ./scripts/gcp_audit.sh --list
#
# (Training has its own ./scripts/gcp_status.sh — audit does NOT show up there.)
#
# Results in the bucket:
#   gs://<bucket>/audits/<RUN_ID>.log            console output
#   gs://<bucket>/audits/<RUN_ID>.json           microstructure_audit.json
#   gs://<bucket>/audits/latest.log|.json        convenience copies
#   gs://<bucket>/status/audit_latest.json       status marker (separate from training)
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud

# --- fetch / list modes (read results from the bucket, no VM needed) -------------
AUDIT_PREFIX="$GCS_BUCKET/audits"
if [[ "${1:-}" == "--list" ]]; then
  echo "==> audit runs ($AUDIT_PREFIX/<run_id>.log, oldest -> newest):"
  gcloud storage ls "$AUDIT_PREFIX/" 2>/dev/null \
    | sed -n 's#.*/audits/\(.*\)\.log$#\1#p' | sort || echo "(none yet)"
  exit 0
fi
if [[ "${1:-}" == "--status" ]]; then
  echo "==> bucket: $GCS_BUCKET"
  MARKER="$(gcloud storage cat "$GCS_BUCKET/status/audit_latest.json" 2>/dev/null || true)"
  if [[ -z "$MARKER" ]]; then
    echo "no audit marker yet (nothing has run, or run just starting)"
  else
    echo "last audit marker: $MARKER"
  fi
  VM_STATE="$(gcloud compute instances describe "$GCP_AUDIT_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)' 2>/dev/null || true)"
  if [[ -n "$VM_STATE" ]]; then
    echo "audit VM $GCP_AUDIT_INSTANCE: $VM_STATE (zone=$GCP_ZONE)"
    if [[ "$VM_STATE" == "RUNNING" ]]; then
      echo "live view:  gcloud compute ssh $GCP_AUDIT_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tmux attach -t fluxaudit"
    elif [[ "$VM_STATE" == "TERMINATED" ]]; then
      echo "VM is STOPPED (a FAILED audit kept for debug). Inspect:"
      echo "  gcloud compute instances start $GCP_AUDIT_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT"
      echo "  gcloud compute ssh $GCP_AUDIT_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tail -n 120 '~/audit.log'"
    fi
  else
    echo "audit VM $GCP_AUDIT_INSTANCE: gone (self-deleted or never created)"
  fi
  echo ""
  echo "full log + JSON:  ./scripts/gcp_audit.sh --fetch"
  exit 0
fi
if [[ "${1:-}" == "--fetch" ]]; then
  RUN_ID="${2:-latest}"
  echo "==> audit log ($AUDIT_PREFIX/$RUN_ID.log):"
  echo "--------------------------------------------------------------------------"
  gcloud storage cat "$AUDIT_PREFIX/$RUN_ID.log" 2>/dev/null \
    || { echo "(no log — run still in progress or wrong id; try --list)"; exit 1; }
  echo ""
  echo "==> microstructure_audit.json saved locally:"
  mkdir -p "$EXPORT_DIR"
  DEST="$EXPORT_DIR/microstructure_audit_${RUN_ID}.json"
  if gcloud storage cp "$AUDIT_PREFIX/$RUN_ID.json" "$DEST" 2>/dev/null; then
    echo "  $DEST"
  else
    echo "  (no JSON in bucket yet)"
  fi
  exit 0
fi

# --- parse audit args (passed through to audit_microstructure.py) ----------------
AUDIT_PAIRS="${AUDIT_PAIRS:-}"          # empty => DB whitelist (all pairs w/ book)
AUDIT_HORIZONS="${AUDIT_HORIZONS:-5,30,60}"
AUDIT_MIN_ROWS="${AUDIT_MIN_ROWS:-500}"
AUDIT_DEEP=1                            # deep dive on by default (0 => --no-deep)
_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pairs)     AUDIT_PAIRS="$2"; shift 2 ;;
    --horizons)  AUDIT_HORIZONS="$2"; shift 2 ;;
    --min-rows)  AUDIT_MIN_ROWS="$2"; shift 2 ;;
    --no-deep)   AUDIT_DEEP=0; shift ;;
    *)           _ARGS+=("$1"); shift ;;
  esac
done

echo_cfg

RUN_ID="audit-$(date -u +%Y%m%dT%H%M%SZ)"

# Build the audit flag string passed to the python script on the VM.
AUDIT_FLAGS="--horizons ${AUDIT_HORIZONS} --min-rows ${AUDIT_MIN_ROWS}"
if [[ -n "$AUDIT_PAIRS" ]]; then AUDIT_FLAGS="$AUDIT_FLAGS --pairs ${AUDIT_PAIRS}"; fi
if [[ "$AUDIT_DEEP" == "0" ]]; then AUDIT_FLAGS="$AUDIT_FLAGS --no-deep"; fi

echo ""
echo "==> run_id=$RUN_ID  pairs=${AUDIT_PAIRS:-DB-whitelist} horizons=$AUDIT_HORIZONS min_rows=$AUDIT_MIN_ROWS deep=$AUDIT_DEEP"

# --- 0. sanity: bucket reachable -------------------------------------------------
if ! gcloud storage ls "$GCS_BUCKET" >/dev/null 2>&1; then
  echo "ERROR: bucket $GCS_BUCKET not accessible. See gcp_train.sh header for setup."
  exit 1
fi

# --- 1. ensure the (CPU) temp VM exists -----------------------------------------
echo ""
echo "==> ensure temp VM $GCP_AUDIT_INSTANCE ($GCP_TRAIN_MACHINE)"
_VM_CREATED=0
if gcloud compute instances describe "$GCP_AUDIT_INSTANCE" \
     --project="$GCP_PROJECT" --zone="$GCP_ZONE" >/dev/null 2>&1; then
  STATUS=$(gcloud compute instances describe "$GCP_AUDIT_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)')
  echo "    exists (status=$STATUS)"
  if [[ "$STATUS" != "RUNNING" ]]; then
    gcloud compute instances start "$GCP_AUDIT_INSTANCE" \
      --project="$GCP_PROJECT" --zone="$GCP_ZONE"
  fi
  _VM_CREATED=1
fi

if [[ "$_VM_CREATED" == "0" ]]; then
  _STARTUP_CPU='#!/bin/bash
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
  echo "    creating $GCP_TRAIN_MACHINE in $GCP_ZONE ..."
  gcloud compute instances create "$GCP_AUDIT_INSTANCE" \
    --project="$GCP_PROJECT" \
    --zone="$GCP_ZONE" \
    --machine-type="$GCP_TRAIN_MACHINE" \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=50GB \
    --boot-disk-type=pd-balanced \
    --scopes=cloud-platform \
    --tags=fluxtrader-train \
    --metadata=startup-script="$_STARTUP_CPU"
fi

echo "==> waiting for SSH ..."
for _ in $(seq 1 40); do
  if gssh "$GCP_AUDIT_INSTANCE" "echo ok" "$GCP_ZONE" >/dev/null 2>&1; then break; fi
  sleep 5
done
echo "==> waiting for Docker (first boot 1-3 min) ..."
for i in $(seq 1 60); do
  if gssh "$GCP_AUDIT_INSTANCE" "docker compose version" "$GCP_ZONE" >/dev/null 2>&1; then
    echo "    Docker OK"; break
  fi
  if [[ "$i" -eq 60 ]]; then echo "ERROR: Docker not ready."; exit 1; fi
  sleep 5
done
gssh "$GCP_AUDIT_INSTANCE" \
  "sudo usermod -aG docker \$USER; sudo chmod 666 /var/run/docker.sock 2>/dev/null || true; command -v git >/dev/null || sudo apt-get install -y git; command -v tmux >/dev/null || sudo apt-get install -y tmux" \
  "$GCP_ZONE"

# --- 2. fresh dump: always-on -> bucket -----------------------------------------
echo ""
echo "==> fresh dump from $GCP_ALWAYS_ON -> $GCS_BUCKET/dumps/$RUN_ID.sql.gz"
gssh "$GCP_ALWAYS_ON" "set -e
  cd \$HOME/$REMOTE_REPO_NAME
  docker compose exec -T postgres pg_isready -U fluxtrader
  TFLAGS=''
  for t in $DUMP_TABLES; do TFLAGS=\"\$TFLAGS -t \$t\"; done
  docker compose exec -T postgres bash -c \"pg_dump -U fluxtrader -d fluxtrader --format=plain --no-owner --no-acl \$TFLAGS\" \
    | gzip > /tmp/fluxtrader_audit.sql.gz
  ls -lh /tmp/fluxtrader_audit.sql.gz
  gcloud storage cp /tmp/fluxtrader_audit.sql.gz $GCS_BUCKET/dumps/$RUN_ID.sql.gz
  gcloud storage cp $GCS_BUCKET/dumps/$RUN_ID.sql.gz $GCS_BUCKET/dumps/audit_latest.sql.gz
" "$GCP_ZONE"

# --- 3. write remote self-cleaning audit job and launch in tmux -----------------
echo ""
echo "==> launching self-cleaning audit job in remote tmux 'fluxaudit'"
gssh "$GCP_AUDIT_INSTANCE" "cat > \$HOME/run_flux_audit.sh <<PRELUDE
#!/bin/bash
export RUN_ID='$RUN_ID'
export GCS_BUCKET='$GCS_BUCKET'
export GIT_REMOTE='$GIT_REMOTE'
export GIT_REF='$GIT_REF'
export REMOTE_REPO_NAME='$REMOTE_REPO_NAME'
export AUDIT_FLAGS='$AUDIT_FLAGS'
export KEEP_VM='$KEEP_VM'
PRELUDE
cat >> \$HOME/run_flux_audit.sh << 'ENDSCRIPT'
set -Eeuo pipefail
LOG=\$HOME/audit.log
: > \"\$LOG\"
exec > >(tee -a \"\$LOG\") 2>&1

meta() { curl -s -H 'Metadata-Flavor: Google' \"http://metadata.google.internal/computeMetadata/v1/instance/\$1\"; }

finish() {
  local status=\"\$1\"
  echo \"=== finish: \$status \$(date -u) ===\"
  gcloud storage cp \"\$LOG\" \"\$GCS_BUCKET/audits/\$RUN_ID.log\" || true
  gcloud storage cp \"\$LOG\" \"\$GCS_BUCKET/audits/latest.log\" || true
  printf '{\"status\":\"%s\",\"git_sha\":\"%s\",\"run\":\"%s\",\"ended\":\"%s\",\"kind\":\"audit\"}\n' \
    \"\$status\" \"\${GIT_SHA:-}\" \"\$RUN_ID\" \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > /tmp/status.json
  gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/\$RUN_ID.json\" || true
  gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/audit_latest.json\" || true

  local self zone
  self=\"\$(meta name)\"
  zone=\"\$(basename \"\$(meta zone)\")\"
  if [[ \"\${KEEP_VM:-0}\" == \"1\" ]]; then
    echo \"KEEP_VM=1 -> leaving VM \$self running\"; return 0
  fi
  if [[ \"\$status\" == \"DONE\" ]]; then
    echo \"success -> deleting self (\$self)\"
    gcloud compute instances delete \"\$self\" --zone=\"\$zone\" --quiet || true
  else
    echo \"failure -> stopping self (\$self) for debugging\"
    gcloud compute instances stop \"\$self\" --zone=\"\$zone\" --quiet || true
  fi
}
trap 'code=\$?; finish \"\$([[ \$code -eq 0 ]] && echo DONE || echo FAILED)\"' EXIT

printf '{\"status\":\"RUNNING\",\"git_sha\":\"%s\",\"run\":\"%s\",\"started\":\"%s\",\"kind\":\"audit\"}\n' \
  \"\${GIT_SHA:-}\" \"\$RUN_ID\" \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > /tmp/status.json
gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/\$RUN_ID.json\" || true
gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/audit_latest.json\" || true

echo \"=== audit start \$(date -u) run=\$RUN_ID ===\"

echo \"=== checkout \$GIT_REMOTE @ \$GIT_REF ===\"
sudo rm -rf \$HOME/\$REMOTE_REPO_NAME
git clone --branch \"\$GIT_REF\" \"\$GIT_REMOTE\" \$HOME/\$REMOTE_REPO_NAME \
  || git clone \"\$GIT_REMOTE\" \$HOME/\$REMOTE_REPO_NAME
cd \$HOME/\$REMOTE_REPO_NAME
git checkout \"\$GIT_REF\"
GIT_SHA=\"\$(git rev-parse HEAD)\"
echo \"git_sha=\$GIT_SHA\"

echo \"=== pull dump from bucket ===\"
mkdir -p \$HOME/fluxtrader-train-export
gcloud storage cp \"\$GCS_BUCKET/dumps/audit_latest.sql.gz\" \$HOME/fluxtrader-train-export/fluxtrader_audit.sql.gz

echo \"=== reset + restore postgres ===\"
docker compose down -v || true
docker compose up -d postgres
for i in \$(seq 1 60); do docker compose exec -T postgres pg_isready -U fluxtrader && break; sleep 2; done
for i in \$(seq 1 30); do docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -c 'SELECT 1' >/dev/null 2>&1 && break; sleep 2; done
sleep 2
gunzip -c \$HOME/fluxtrader-train-export/fluxtrader_audit.sql.gz \
  | docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -v ON_ERROR_STOP=0

BOOK=\$(docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"SELECT count(*) FROM orderbook_snapshots;\" 2>/dev/null | tr -d '[:space:]' || true)
echo \"book_rows=\$BOOK\"
if ! [[ \"\$BOOK\" =~ ^[0-9]+\$ ]] || [[ \"\$BOOK\" -lt 100 ]]; then echo \"ERROR: restore failed (book=\$BOOK)\"; exit 1; fi

echo \"=== audit_microstructure.py \$AUDIT_FLAGS ===\"
docker compose --profile ml run --rm \
  -e FLUX_GIT_SHA=\$GIT_SHA \
  ml_trainer python audit_microstructure.py \$AUDIT_FLAGS

echo \"=== upload microstructure_audit.json (OUTPUT_DIR is bind-mounted) ===\"
# ml_trainer mounts ./ml/train:/workspace/train and OUTPUT_DIR=/workspace/train/output,
# so the JSON is already on the host under the checked-out repo.
JSON=\$HOME/\$REMOTE_REPO_NAME/ml/train/output/microstructure_audit.json
if [[ ! -f \"\$JSON\" ]]; then echo \"ERROR: audit JSON not found at \$JSON\"; exit 1; fi
gcloud storage cp \"\$JSON\" \"\$GCS_BUCKET/audits/\$RUN_ID.json\"
gcloud storage cp \"\$GCS_BUCKET/audits/\$RUN_ID.json\" \"\$GCS_BUCKET/audits/latest.json\"
echo \"audit json -> \$GCS_BUCKET/audits/\$RUN_ID.json\"

echo \"=== audit finished \$(date -u) ===\"
ENDSCRIPT
chmod +x \$HOME/run_flux_audit.sh
tmux kill-session -t fluxaudit 2>/dev/null || true
tmux new-session -d -s fluxaudit \"bash \$HOME/run_flux_audit.sh\"
echo 'tmux session fluxaudit started'
tmux ls
sleep 8
echo '--- log so far ---'
tail -n 30 \$HOME/audit.log 2>/dev/null || echo '(starting...)'
" "$GCP_ZONE"

echo ""
echo "OK — audit started on $GCP_AUDIT_INSTANCE (run=$RUN_ID)."
echo "This is a SEPARATE VM from training ($GCP_TRAIN_INSTANCE) — the two never"
echo "share a VM, Postgres, tmux session, or status marker, so you can run an"
echo "audit and a training job at the same time."
echo "The VM will DELETE itself on success, STOP itself on failure (KEEP_VM=$KEEP_VM)."
echo "Mac may sleep now."
echo "  status:  ./scripts/gcp_audit.sh --status"
echo "  live:    gcloud compute ssh $GCP_AUDIT_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tmux attach -t fluxaudit"
echo "  results: ./scripts/gcp_audit.sh --fetch $RUN_ID     (log + JSON)"
