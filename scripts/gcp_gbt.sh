#!/usr/bin/env bash
# E4-GBT diagnostic baseline on a THROWAWAY VM — one command, self-cleaning.
#
# Runs on its OWN instance ($GCP_GBT_INSTANCE, default fluxtrader-gbt), SEPARATE
# from the train / audit / ablate VMs — nothing shared (VM, Postgres, tmux
# session, status marker), so a GBT run, a walk-forward and a training run can all
# be in flight at once.
#
# WHY A VM: the always-on collector VM is 2GB and also runs postgres + app +
# ml_inference. An 8-pair full-history gbt_baseline.py run needs ~2-4GB (the
# design matrix, not the bundle, dominates) so the kernel OOM-kills it mid-bundle
# — silently, with no report written. Same reason gcp_audit.sh exists. This
# mirrors that script:
#   1. fresh DB dump: always-on -> bucket
#   2. create (or reuse) the temp GBT VM
#   3. git clone GIT_REMOTE @ GIT_REF, pull dump, restore Postgres
#   4. run gbt_baseline.py inside the ml_trainer container
#   5. push console log + report JSON + a short summary + status marker to bucket
#   6. self-DELETE on success / self-STOP on failure   (never left billing)
#
# Returns immediately. Watch / fetch results:
#   ./scripts/gcp_gbt.sh                          # launch (E2b 8-pair set, 30m primary)
#   ./scripts/gcp_gbt.sh --tail-days 90           # bound history
#   ./scripts/gcp_gbt.sh --label-mode triple_barrier      # E3-flavored GBT
#   ./scripts/gcp_gbt.sh --flatten --max-train-rows 400000
#   GBT_PAIRS=BTCUSDT,ETHUSDT ./scripts/gcp_gbt.sh
#   GBT_PRIMARY=60 ./scripts/gcp_gbt.sh           # must be in GBT_HORIZONS
#   KEEP_VM=1 ./scripts/gcp_gbt.sh                # debug: don't auto delete/stop VM
#
#   watch status:   ./scripts/gcp_gbt.sh --status  (GBT VM liveness + marker)
#   results:        ./scripts/gcp_gbt.sh --fetch [run_id]   (summary + JSON)
#   full log:       ./scripts/gcp_gbt.sh --log [run_id]
#   list runs:      ./scripts/gcp_gbt.sh --list
#
# Any flag that is not one of the modes above is passed VERBATIM to
# gbt_baseline.py (--tail-days, --max-train-rows, --flatten, --label-mode,
# --n-estimators, --num-leaves, --learning-rate, --chunk-mb, --seed).
#
# (Training has its own ./scripts/gcp_status.sh — GBT does NOT show up there.)
#
# Results in the bucket:
#   gs://<bucket>/gbt/<RUN_ID>.log            console output
#   gs://<bucket>/gbt/<RUN_ID>.json           gbt_baseline report
#   gs://<bucket>/gbt/<RUN_ID>.summary.txt    the metric tables only (quick read)
#   gs://<bucket>/gbt/latest.*                convenience copies
#   gs://<bucket>/status/gbt_latest.json      status marker (separate from training)
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud

# Separate throwaway VM name so GBT never collides with train/audit/ablate.
: "${GCP_GBT_INSTANCE:=fluxtrader-gbt}"
# CPU + RAM bound, no GPU (LightGBM). e2-standard-4 = 4 vCPU / 16GB.
: "${GCP_GBT_MACHINE:=$GCP_TRAIN_MACHINE}"

# --- fetch / list modes (read results from the bucket, no VM needed) -------------
GBT_PREFIX="$GCS_BUCKET/gbt"
if [[ "${1:-}" == "--list" ]]; then
  echo "==> GBT runs ($GBT_PREFIX/<run_id>.log, oldest -> newest):"
  gcloud storage ls "$GBT_PREFIX/" 2>/dev/null \
    | sed -n 's#.*/gbt/\(.*\)\.log$#\1#p' | sort || echo "(none yet)"
  exit 0
fi
if [[ "${1:-}" == "--status" ]]; then
  echo "==> bucket: $GCS_BUCKET"
  MARKER="$(gcloud storage cat "$GCS_BUCKET/status/gbt_latest.json" 2>/dev/null || true)"
  if [[ -z "$MARKER" ]]; then
    echo "no GBT marker yet (nothing has run, or run just starting)"
  else
    echo "last GBT marker: $MARKER"
  fi
  VM_STATE="$(gcloud compute instances describe "$GCP_GBT_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)' 2>/dev/null || true)"
  if [[ -n "$VM_STATE" ]]; then
    echo "GBT VM $GCP_GBT_INSTANCE: $VM_STATE (zone=$GCP_ZONE)"
    if [[ "$VM_STATE" == "RUNNING" ]]; then
      echo "live view:  gcloud compute ssh $GCP_GBT_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tmux attach -t fluxgbt"
    elif [[ "$VM_STATE" == "TERMINATED" ]]; then
      echo "VM is STOPPED (a FAILED run kept for debug). Inspect:"
      echo "  gcloud compute instances start $GCP_GBT_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT"
      echo "  gcloud compute ssh $GCP_GBT_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tail -n 120 '~/gbt.log'"
    fi
  else
    echo "GBT VM $GCP_GBT_INSTANCE: gone (self-deleted or never created)"
  fi
  echo ""
  echo "results:  ./scripts/gcp_gbt.sh --fetch      full log:  ./scripts/gcp_gbt.sh --log"
  exit 0
fi
if [[ "${1:-}" == "--log" ]]; then
  RUN_ID="${2:-latest}"
  gcloud storage cat "$GBT_PREFIX/$RUN_ID.log" 2>/dev/null \
    || { echo "(no log — run still in progress or wrong id; try --list)"; exit 1; }
  exit 0
fi
if [[ "${1:-}" == "--fetch" ]]; then
  RUN_ID="${2:-latest}"
  echo "==> GBT summary ($GBT_PREFIX/$RUN_ID.summary.txt):"
  echo "--------------------------------------------------------------------------"
  gcloud storage cat "$GBT_PREFIX/$RUN_ID.summary.txt" 2>/dev/null \
    || { echo "(no summary yet — run still in progress or wrong id; try --list)"; exit 1; }
  echo ""
  echo "==> report JSON saved locally:"
  mkdir -p "$EXPORT_DIR"
  DEST="$EXPORT_DIR/gbt_baseline_${RUN_ID}.json"
  if gcloud storage cp "$GBT_PREFIX/$RUN_ID.json" "$DEST" 2>/dev/null; then
    echo "  $DEST"
  else
    echo "  (no JSON in bucket yet)"
  fi
  echo ""
  echo "full console log:  ./scripts/gcp_gbt.sh --log $RUN_ID"
  exit 0
fi

# --- args: --pairs consumed here (echoed + defaulted), rest passed through -------
# Default pair set = E2b's 8 pairs. The plan requires E4-GBT to use the SAME set
# E2b trained on, otherwise the "GBT vs LSTM" read is not attributable.
: "${GBT_PAIRS:=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT}"
# gbt_baseline.py reads horizons/primary from config.py env, not CLI. Pass them
# EXPLICITLY so the run can't silently inherit a different primary from the VM's
# .env and report a horizon the LSTM comparison isn't against (the R3 lesson).
: "${GBT_HORIZONS:=${TRAIN_HORIZONS:-5,30,60}}"
: "${GBT_PRIMARY:=${TRAIN_PRIMARY:-30}}"
: "${GBT_SEQ_LEN:=${TRAIN_SEQ_LEN:-128}}"
# Candle bar size. Same reason as the horizons above: gbt_baseline.py reads
# CANDLE_INTERVAL from config.py env and uses it for horizon_bars() and for the
# eval_m2 P&L hold. It was NOT forwarded, so a `CANDLE_INTERVAL=15m` on the
# launcher silently trained on 1m bars and produced a run that could not be
# compared to the 15m LSTM baseline it exists to be compared against.
: "${GBT_CANDLE_INTERVAL:=${CANDLE_INTERVAL:-1m}}"

# Flags accumulate as a plain string (not an array) — bash 3.2 on macOS trips over
# empty-array expansion under `set -u`, and these flags never contain whitespace.
GBT_EXTRA=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pairs)
      [[ $# -ge 2 ]] || { echo "ERROR: --pairs requires a value"; exit 1; }
      GBT_PAIRS="$2"; shift 2 ;;
    *)
      GBT_EXTRA="$GBT_EXTRA $1"; shift ;;
  esac
done
GBT_ARGS="--pairs $GBT_PAIRS$GBT_EXTRA"

echo_cfg

RUN_ID="gbt-$(date -u +%Y%m%dT%H%M%SZ)"

echo ""
echo "==> run_id=$RUN_ID  pairs=$GBT_PAIRS"
echo "    horizons=$GBT_HORIZONS primary=${GBT_PRIMARY}m seq_len=$GBT_SEQ_LEN interval=$GBT_CANDLE_INTERVAL device=cpu"
echo "    gbt_baseline.py $GBT_ARGS"
if [[ ",$GBT_HORIZONS," != *",$GBT_PRIMARY,"* ]]; then
  echo "ERROR: GBT_PRIMARY=$GBT_PRIMARY is not in GBT_HORIZONS=$GBT_HORIZONS."
  echo "       gbt_baseline.py would fall back to the first horizon and report"
  echo "       numbers you can't compare to the LSTM. Fix one of the two."
  exit 1
fi

# --- 0. sanity: bucket reachable -------------------------------------------------
if ! gcloud storage ls "$GCS_BUCKET" >/dev/null 2>&1; then
  echo "ERROR: bucket $GCS_BUCKET not accessible. See gcp_train.sh header for setup."
  exit 1
fi

# --- 1. ensure the (CPU) temp VM exists -----------------------------------------
echo ""
echo "==> ensure temp VM $GCP_GBT_INSTANCE ($GCP_GBT_MACHINE)"
_VM_CREATED=0
if gcloud compute instances describe "$GCP_GBT_INSTANCE" \
     --project="$GCP_PROJECT" --zone="$GCP_ZONE" >/dev/null 2>&1; then
  STATUS=$(gcloud compute instances describe "$GCP_GBT_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)')
  echo "    exists (status=$STATUS)"
  if [[ "$STATUS" != "RUNNING" ]]; then
    gcloud compute instances start "$GCP_GBT_INSTANCE" \
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
  echo "    creating $GCP_GBT_MACHINE in $GCP_ZONE ..."
  gcloud compute instances create "$GCP_GBT_INSTANCE" \
    --project="$GCP_PROJECT" \
    --zone="$GCP_ZONE" \
    --machine-type="$GCP_GBT_MACHINE" \
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
  if gssh "$GCP_GBT_INSTANCE" "echo ok" "$GCP_ZONE" >/dev/null 2>&1; then break; fi
  sleep 5
done
echo "==> waiting for Docker (first boot 1-3 min) ..."
for i in $(seq 1 60); do
  if gssh "$GCP_GBT_INSTANCE" "docker compose version" "$GCP_ZONE" >/dev/null 2>&1; then
    echo "    Docker OK"; break
  fi
  if [[ "$i" -eq 60 ]]; then echo "ERROR: Docker not ready."; exit 1; fi
  sleep 5
done
gssh "$GCP_GBT_INSTANCE" \
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
    | gzip > /var/tmp/fluxtrader_gbt.sql.gz
  ls -lh /var/tmp/fluxtrader_gbt.sql.gz
  gcloud storage cp /var/tmp/fluxtrader_gbt.sql.gz $GCS_BUCKET/dumps/$RUN_ID.sql.gz
  gcloud storage cp $GCS_BUCKET/dumps/$RUN_ID.sql.gz $GCS_BUCKET/dumps/gbt_latest.sql.gz
  rm -f /var/tmp/fluxtrader_gbt.sql.gz
" "$GCP_ZONE"

# --- 3. write remote self-cleaning GBT job and launch in tmux --------------------
echo ""
echo "==> launching self-cleaning GBT job in remote tmux 'fluxgbt'"
gssh "$GCP_GBT_INSTANCE" "cat > \$HOME/run_flux_gbt.sh <<PRELUDE
#!/bin/bash
export RUN_ID='$RUN_ID'
export GCS_BUCKET='$GCS_BUCKET'
export GIT_REMOTE='$GIT_REMOTE'
export GIT_REF='$GIT_REF'
export REMOTE_REPO_NAME='$REMOTE_REPO_NAME'
export GBT_ARGS='$GBT_ARGS'
export GBT_HORIZONS='$GBT_HORIZONS'
export GBT_PRIMARY='$GBT_PRIMARY'
export GBT_SEQ_LEN='$GBT_SEQ_LEN'
export GBT_CANDLE_INTERVAL='$GBT_CANDLE_INTERVAL'
export KEEP_VM='$KEEP_VM'
export MODEL_VOLUME_NAME='$MODEL_VOLUME_NAME'
PRELUDE
cat >> \$HOME/run_flux_gbt.sh << 'ENDSCRIPT'
set -Eeuo pipefail
LOG=\$HOME/gbt.log
: > \"\$LOG\"
exec > >(tee -a \"\$LOG\") 2>&1

meta() { curl -s -H 'Metadata-Flavor: Google' \"http://metadata.google.internal/computeMetadata/v1/instance/\$1\"; }

finish() {
  local status=\"\$1\"
  echo \"=== finish: \$status \$(date -u) ===\"
  gcloud storage cp \"\$LOG\" \"\$GCS_BUCKET/gbt/\$RUN_ID.log\" || true
  gcloud storage cp \"\$LOG\" \"\$GCS_BUCKET/gbt/latest.log\" || true
  printf '{\"status\":\"%s\",\"git_sha\":\"%s\",\"run\":\"%s\",\"ended\":\"%s\",\"kind\":\"gbt\",\"primary\":\"%s\"}\n' \
    \"\$status\" \"\${GIT_SHA:-}\" \"\$RUN_ID\" \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"\$GBT_PRIMARY\" > /tmp/status.json
  gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/\$RUN_ID.json\" || true
  gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/gbt_latest.json\" || true

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

printf '{\"status\":\"RUNNING\",\"git_sha\":\"%s\",\"run\":\"%s\",\"started\":\"%s\",\"kind\":\"gbt\",\"primary\":\"%s\"}\n' \
  \"\${GIT_SHA:-}\" \"\$RUN_ID\" \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"\$GBT_PRIMARY\" > /tmp/status.json
gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/\$RUN_ID.json\" || true
gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/gbt_latest.json\" || true

echo \"=== gbt start \$(date -u) run=\$RUN_ID ===\"
echo \"=== host: \$(nproc) vCPU, \$(free -g | awk '/^Mem:/{print \$2}')GB RAM ===\"

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
gcloud storage cp \"\$GCS_BUCKET/dumps/gbt_latest.sql.gz\" \$HOME/fluxtrader-train-export/fluxtrader_gbt.sql.gz

echo \"=== reset + restore postgres ===\"
docker compose down -v || true
docker compose up -d postgres
for i in \$(seq 1 60); do docker compose exec -T postgres pg_isready -U fluxtrader && break; sleep 2; done
for i in \$(seq 1 30); do docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -c 'SELECT 1' >/dev/null 2>&1 && break; sleep 2; done
sleep 2
gunzip -c \$HOME/fluxtrader-train-export/fluxtrader_gbt.sql.gz \
  | docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -v ON_ERROR_STOP=0

CANDLES=\$(docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"SELECT count(*) FROM candles;\" 2>/dev/null | tr -d '[:space:]' || true)
echo \"candles=\$CANDLES\"
if ! [[ \"\$CANDLES\" =~ ^[0-9]+\$ ]] || [[ \"\$CANDLES\" -lt 1000 ]]; then echo \"ERROR: restore failed (candles=\$CANDLES)\"; exit 1; fi

# compose declares model_weights as external -> must exist before 'run'.
docker volume create \"\${MODEL_VOLUME_NAME:-trading_agent_model_weights}\" >/dev/null 2>&1 || true

echo \"=== build ml_trainer image ===\"
# lightgbm is in requirements.txt, so a clean build is all that's needed — EXCEPT
# that the pre-existing 'torch==2.5.1+cpu' pin no longer resolves on the PyTorch
# CPU index (see docs/NEXT_TRAINING_PLAN.md). Fixing that pin for real affects
# TRAINED numerics and is a separate decision, so relax it here only in this
# throwaway VM's checkout: gbt_baseline.py uses torch solely for the gate/P&L
# tensor math (topk, comparisons, arithmetic), never to train or load a model, so
# the torch build cannot move the GBT numbers.
if ! docker compose --profile ml build ml_trainer; then
  echo \"WARNING: build failed on the pinned torch — retrying with torch==2.5.1 (VM checkout only)\"
  sed -i 's/^torch==2\\.5\\.1+cpu\$/torch==2.5.1/' ml/train/requirements.txt
  if ! docker compose --profile ml build ml_trainer; then
    echo \"WARNING: still failing — retrying with an UNPINNED cpu torch (VM checkout only)\"
    sed -i 's/^torch==.*\$/torch/' ml/train/requirements.txt
    docker compose --profile ml build ml_trainer
  fi
  echo \"    torch pin used: \$(grep -E '^torch' ml/train/requirements.txt)\"
fi

echo \"=== resolved knobs: HORIZONS_MINUTES=\$GBT_HORIZONS PRIMARY_HORIZON=\$GBT_PRIMARY SEQ_LEN=\$GBT_SEQ_LEN CANDLE_INTERVAL=\$GBT_CANDLE_INTERVAL ===\"
echo \"=== gbt_baseline.py \$GBT_ARGS ===\"
REPORT=/workspace/train/output/gbt_\$RUN_ID.json
docker compose --profile ml run --rm \
  -e HORIZONS_MINUTES=\$GBT_HORIZONS -e PRIMARY_HORIZON=\$GBT_PRIMARY -e SEQ_LEN=\$GBT_SEQ_LEN \
  -e CANDLE_INTERVAL=\$GBT_CANDLE_INTERVAL \
  -e FLUX_GIT_SHA=\$GIT_SHA \
  ml_trainer python gbt_baseline.py \$GBT_ARGS --out \$REPORT

echo \"=== upload report (OUTPUT_DIR is bind-mounted) ===\"
# ml_trainer mounts ./ml/train:/workspace/train, so the JSON is already on the host.
JSON=\$HOME/\$REMOTE_REPO_NAME/ml/train/output/gbt_\$RUN_ID.json
if [[ ! -f \"\$JSON\" ]]; then echo \"ERROR: report not found at \$JSON\"; exit 1; fi
gcloud storage cp \"\$JSON\" \"\$GCS_BUCKET/gbt/\$RUN_ID.json\"
gcloud storage cp \"\$GCS_BUCKET/gbt/\$RUN_ID.json\" \"\$GCS_BUCKET/gbt/latest.json\"
echo \"report -> \$GCS_BUCKET/gbt/\$RUN_ID.json\"

echo \"=== build summary (metric tables only) ===\"
SUMMARY=\$HOME/gbt_summary.txt
{
  echo \"E4-GBT diagnostic — run=\$RUN_ID git=\${GIT_SHA:0:8}\"
  echo \"pairs/flags: \$GBT_ARGS\"
  echo \"horizons=\$GBT_HORIZONS primary=\${GBT_PRIMARY}m seq_len=\$GBT_SEQ_LEN interval=\$GBT_CANDLE_INTERVAL\"
  echo \"================================================================\"
  grep -E 'GBT baseline \\||WARNING|Train samples|Val window|Subsampled|Fitting LightGBM|\\[mem\\]' \"\$LOG\" || true
  echo \"\"
  sed -n '/=== Fixed-coverage/,\$p' \"\$LOG\" | sed '/^=== upload report/,\$d'
} > \"\$SUMMARY\"
cat \"\$SUMMARY\"
gcloud storage cp \"\$SUMMARY\" \"\$GCS_BUCKET/gbt/\$RUN_ID.summary.txt\" || true
gcloud storage cp \"\$SUMMARY\" \"\$GCS_BUCKET/gbt/latest.summary.txt\" || true

echo \"=== gbt finished \$(date -u) ===\"
ENDSCRIPT
chmod +x \$HOME/run_flux_gbt.sh
tmux kill-session -t fluxgbt 2>/dev/null || true
tmux new-session -d -s fluxgbt \"bash \$HOME/run_flux_gbt.sh\"
echo 'tmux session fluxgbt started'
tmux ls
sleep 8
echo '--- log so far ---'
tail -n 30 \$HOME/gbt.log 2>/dev/null || echo '(starting...)'
" "$GCP_ZONE"

echo ""
echo "OK — GBT diagnostic started on $GCP_GBT_INSTANCE (run=$RUN_ID)."
echo "SEPARATE VM from train/audit/ablate — nothing shared, safe to run concurrently."
echo "Diagnostic only: it never writes a checkpoint, so SERVING IS UNAFFECTED."
echo "The VM will DELETE itself on success, STOP itself on failure (KEEP_VM=$KEEP_VM)."
echo "Mac may sleep now."
echo "  status:  ./scripts/gcp_gbt.sh --status"
echo "  live:    gcloud compute ssh $GCP_GBT_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tmux attach -t fluxgbt"
echo "  results: ./scripts/gcp_gbt.sh --fetch $RUN_ID     (summary + JSON)"
