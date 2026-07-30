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
#   ./scripts/gcp_train.sh --gpu              # GPU mode (n1-standard-4 + T4)
#   ./scripts/gcp_train.sh --gpu 120 256      # GPU + custom epochs/seq-len
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

# --- parse --gpu flag --------------------------------------------------------
_GPU_MODE=0
_ARGS=()
for _a in "$@"; do
  if [[ "$_a" == "--gpu" ]]; then
    _GPU_MODE=1
  else
    _ARGS+=("$_a")
  fi
done
set -- "${_ARGS[@]+"${_ARGS[@]}"}"

_GCP_ZONE_ORIGINAL="$GCP_ZONE"
if [[ "$_GPU_MODE" == "1" ]]; then
  TRAIN_DEVICE=cuda
  GCP_TRAIN_MACHINE="$GCP_TRAIN_MACHINE_GPU"
  GCP_ZONE="$GCP_TRAIN_ZONE"
  GCP_REGION="${GCP_ZONE%-*}"
  export GCP_REGION
fi
echo_cfg

EPOCHS="${1:-$TRAIN_EPOCHS}"
SEQ_LEN="${2:-$TRAIN_SEQ_LEN}"
PAIRS_ARG="${TRAIN_PAIRS:-}"
HORIZONS="${TRAIN_HORIZONS:-5,30,60}"
PRIMARY="${TRAIN_PRIMARY:-30}"
QUANTILE_HEAD="${TRAIN_QUANTILE_HEAD:-0}"
QUANTILE_LEVELS="${TRAIN_QUANTILE_LEVELS:-0.1,0.5,0.9}"
QUANTILE_LOSS_WEIGHT="${TRAIN_QUANTILE_LOSS_WEIGHT:-0.2}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
R="\$HOME/${REMOTE_REPO_NAME}"

PAIRS_FLAG=""
if [[ -n "$PAIRS_ARG" ]]; then PAIRS_FLAG="--pairs ${PAIRS_ARG}"; fi

echo ""
echo "==> run_id=$RUN_ID  epochs=$EPOCHS seq=$SEQ_LEN horizons=$HORIZONS primary=${PRIMARY}m pairs=${PAIRS_ARG:-DB-whitelist} device=$TRAIN_DEVICE quantile_head=$QUANTILE_HEAD"

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
  # Check machine type matches (handles CPU↔GPU switch without manual delete)
  EXISTING_MACHINE=$(gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" \
    --format='value(machineType)' | awk -F/ '{print $NF}')
  # GCE field is guestAccelerators (not "accelerators"). Wrong name → empty →
  # g2+L4 looked like a CPU VM and triggered false "machine mismatch" deletes.
  EXISTING_ACCEL=$(gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" \
    --format='value(guestAccelerators[0].acceleratorType.basename())' 2>/dev/null || true)
  # g2 machine types always include an L4 even when guestAccelerators is sparse.
  if [[ -z "$EXISTING_ACCEL" && "$EXISTING_MACHINE" == g2-* ]]; then
    EXISTING_ACCEL="nvidia-l4"
  fi
  # Recreate only on CPU↔GPU switch, not GPU↔GPU (T4 n1 vs L4 g2 fallback).
  _MISMATCH=0
  if [[ "$EXISTING_MACHINE" != "$GCP_TRAIN_MACHINE" ]]; then
    if [[ "$_GPU_MODE" == "1" && -n "$EXISTING_ACCEL" ]]; then
      echo "    exists as GPU VM ($EXISTING_MACHINE + $EXISTING_ACCEL, status=$STATUS) → reuse"
    elif [[ "$_GPU_MODE" != "1" && -z "$EXISTING_ACCEL" ]]; then
      echo "    exists as CPU VM ($EXISTING_MACHINE, status=$STATUS) → reuse"
    else
      _MISMATCH=1
    fi
  fi
  if [[ "$_MISMATCH" == "1" ]]; then
    echo "    machine mismatch ($EXISTING_MACHINE ≠ $GCP_TRAIN_MACHINE) → deleting + recreating"
    gcloud compute instances delete "$GCP_TRAIN_INSTANCE" \
      --project="$GCP_PROJECT" --zone="$GCP_ZONE" --quiet
    # fall through to create below
  else
    # "exists as GPU/CPU VM" was already printed above if machine type differed
    if [[ "$EXISTING_MACHINE" == "$GCP_TRAIN_MACHINE" ]]; then
      echo "    exists (status=$STATUS)"
    fi
    if [[ "$STATUS" != "RUNNING" ]]; then
      if ! gcloud compute instances start "$GCP_TRAIN_INSTANCE" \
            --project="$GCP_PROJECT" --zone="$GCP_ZONE"; then
        echo "    start failed (likely GPU stockout) → delete + recreate in another zone"
        gcloud compute instances delete "$GCP_TRAIN_INSTANCE" \
          --project="$GCP_PROJECT" --zone="$GCP_ZONE" --quiet
        _VM_CREATED=0
      else
        _VM_CREATED=1
      fi
    else
      _VM_CREATED=1
    fi
  fi
else
  _VM_CREATED=0
fi

# If VM wasn't found in GCP_ZONE, search all zones in the region.
# Previous L4 fallback may have placed it in a different zone.
if [[ "${_VM_CREATED:-0}" == "0" && "$_GPU_MODE" == "1" ]]; then
  _FOUND_ZONE=$(gcloud compute instances list \
    --project="$GCP_PROJECT" \
    --filter="name=$GCP_TRAIN_INSTANCE" \
    --format="value(zone)" 2>/dev/null | head -1 || true)
  if [[ -n "$_FOUND_ZONE" ]]; then
    _FOUND_ZONE=$(basename "$_FOUND_ZONE")
    echo "    found $GCP_TRAIN_INSTANCE in $_FOUND_ZONE (not $GCP_ZONE) → adopting"
    GCP_ZONE="$_FOUND_ZONE"
    export GCP_ZONE
    STATUS=$(gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
      --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)')
    EXISTING_MACHINE=$(gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
      --project="$GCP_PROJECT" --zone="$GCP_ZONE" \
      --format='value(machineType)' | awk -F/ '{print $NF}')
    EXISTING_ACCEL=$(gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
      --project="$GCP_PROJECT" --zone="$GCP_ZONE" \
      --format='value(guestAccelerators[0].acceleratorType.basename())' 2>/dev/null || true)
    if [[ -z "$EXISTING_ACCEL" && "$EXISTING_MACHINE" == g2-* ]]; then
      EXISTING_ACCEL="nvidia-l4"
    fi
    echo "    exists ($EXISTING_MACHINE + ${EXISTING_ACCEL:-none}, status=$STATUS) → reuse"
    if [[ -n "$EXISTING_ACCEL" ]]; then
      GCP_TRAIN_MACHINE="$EXISTING_MACHINE"
      GCP_TRAIN_ACCELERATOR="type=${EXISTING_ACCEL},count=1"
    fi
    if [[ "$STATUS" != "RUNNING" ]]; then
      if ! gcloud compute instances start "$GCP_TRAIN_INSTANCE" \
            --project="$GCP_PROJECT" --zone="$GCP_ZONE"; then
        echo "    start failed (likely GPU stockout) → delete + recreate"
        gcloud compute instances delete "$GCP_TRAIN_INSTANCE" \
          --project="$GCP_PROJECT" --zone="$GCP_ZONE" --quiet
        _VM_CREATED=0
      else
        _VM_CREATED=1
      fi
    else
      _VM_CREATED=1
    fi
  fi
fi

if [[ "${_VM_CREATED:-0}" == "0" ]]; then
  # --- startup script (CPU or GPU) ---
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

  _STARTUP_GPU='#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

# --- Phase 1: Docker (runs every boot) ---
if ! command -v docker &>/dev/null; then
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
fi

# --- Phase 2: NVIDIA driver (skip if already working) ---
if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
  touch /var/tmp/nvidia-driver-installed
elif [ ! -f /var/tmp/nvidia-driver-installed ]; then
  apt-get update -y
  apt-get install -y ubuntu-drivers-common
  DEBIAN_FRONTEND=noninteractive ubuntu-drivers install --no-oem
  touch /var/tmp/nvidia-driver-installed
  reboot
fi

# --- Phase 3: nvidia-container-toolkit + Docker GPU runtime ---
if ! nvidia-container-toolkit --version &>/dev/null 2>&1; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --batch --yes --no-tty --dearmor \
      -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL "https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list" \
    | sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update -y
  apt-get install -y nvidia-container-toolkit
fi
# Reconfigure every boot once the driver is up. Docker 25+ --gpus uses CDI;
# missing /etc/cdi/nvidia.yaml → "no known GPU vendor found".
if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null \
    && command -v nvidia-ctk &>/dev/null; then
  mkdir -p /etc/cdi /var/run/cdi
  nvidia-ctk runtime configure --runtime=docker
  nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
  systemctl restart docker
fi

for u in $(ls /home 2>/dev/null); do usermod -aG docker "$u" || true; done
touch /var/tmp/fluxtrader-docker-ready
'

  # GPU mode: try multiple zones in the region for resource availability
  _GPU_ZONES=()
  if [[ "$_GPU_MODE" == "1" ]]; then
    _GPU_ZONES=($(gcloud compute zones list --project="$GCP_PROJECT" --filter="region=$GCP_REGION" --format="value(name)" 2>/dev/null | sort))
    # Move the preferred zone to the front
    _PREFERRED_ZONE="$GCP_ZONE"
    _GPU_ZONES=("$_PREFERRED_ZONE" "${_GPU_ZONES[@]/$_PREFERRED_ZONE/}")
    # Remove duplicates while preserving order
    _GPU_ZONES=($(echo "${_GPU_ZONES[@]}" | tr ' ' '\n' | awk '!seen[$0]++'))
  fi

  _create_vm() {
    local zone="$1"
    if [[ "$_GPU_MODE" == "1" ]]; then
      echo "    creating $GCP_TRAIN_MACHINE + $GCP_TRAIN_ACCELERATOR in $zone ..."
      gcloud compute instances create "$GCP_TRAIN_INSTANCE" \
        --project="$GCP_PROJECT" \
        --zone="$zone" \
        --machine-type="$GCP_TRAIN_MACHINE" \
        --accelerator="$GCP_TRAIN_ACCELERATOR" \
        --maintenance-policy=TERMINATE \
        --image-family=ubuntu-2204-lts \
        --image-project=ubuntu-os-cloud \
        --boot-disk-size=50GB \
        --boot-disk-type=pd-balanced \
        --scopes=cloud-platform \
        --tags=fluxtrader-train \
        --metadata=startup-script="$_STARTUP_GPU"
    else
      echo "    creating $GCP_TRAIN_MACHINE in $zone ..."
      gcloud compute instances create "$GCP_TRAIN_INSTANCE" \
        --project="$GCP_PROJECT" \
        --zone="$zone" \
        --machine-type="$GCP_TRAIN_MACHINE" \
        --image-family=ubuntu-2204-lts \
        --image-project=ubuntu-os-cloud \
        --boot-disk-size=50GB \
        --boot-disk-type=pd-balanced \
        --scopes=cloud-platform \
        --tags=fluxtrader-train \
        --metadata=startup-script="$_STARTUP_CPU"
    fi
  }

  if [[ "$_GPU_MODE" == "1" && ${#_GPU_ZONES[@]} -gt 0 ]]; then
    # Retry the full T4→L4 sweep across all zones; GPUs are often briefly
    # unavailable while other preemptible/spot VMs churn.
    _GPU_MAX_RETRIES="${GPU_MAX_RETRIES:-5}"
    _GPU_RETRY_DELAY="${GPU_RETRY_DELAY:-30}"
    _VM_CREATED=0
    for _attempt in $(seq 1 $_GPU_MAX_RETRIES); do
      if [[ "$_attempt" -gt 1 ]]; then
        echo ""
        echo "==> retry $_attempt/$_GPU_MAX_RETRIES (waiting ${_GPU_RETRY_DELAY}s) ..."
        sleep "$_GPU_RETRY_DELAY"
      fi

      echo "==> trying T4 across ${#_GPU_ZONES[@]} zones ..."
      for _zone in "${_GPU_ZONES[@]}"; do
        if _create_vm "$_zone"; then
          GCP_ZONE="$_zone"
          export GCP_ZONE
          _VM_CREATED=1
          break 2
        fi
        echo "    → zone $_zone unavailable"
      done

      echo "==> T4 exhausted, trying L4 (g2-standard-4) ..."
      _L4_MACHINE="g2-standard-4"
      _L4_ACCELERATOR="type=nvidia-l4,count=1"
      for _zone in "${_GPU_ZONES[@]}"; do
        echo "    creating $_L4_MACHINE + $_L4_ACCELERATOR in $_zone ..."
        if gcloud compute instances create "$GCP_TRAIN_INSTANCE" \
            --project="$GCP_PROJECT" \
            --zone="$_zone" \
            --machine-type="$_L4_MACHINE" \
            --accelerator="$_L4_ACCELERATOR" \
            --maintenance-policy=TERMINATE \
            --image-family=ubuntu-2204-lts \
            --image-project=ubuntu-os-cloud \
            --boot-disk-size=50GB \
            --boot-disk-type=pd-balanced \
            --scopes=cloud-platform \
            --tags=fluxtrader-train \
            --metadata=startup-script="$_STARTUP_GPU"; then
          GCP_ZONE="$_zone"
          export GCP_ZONE
          GCP_TRAIN_MACHINE="$_L4_MACHINE"
          GCP_TRAIN_ACCELERATOR="$_L4_ACCELERATOR"
          _VM_CREATED=1
          echo "    → L4 available in $_zone"
          break 2
        fi
        echo "    → zone $_zone unavailable"
      done
    done
    if [[ "$_VM_CREATED" == "0" ]]; then
      echo "ERROR: Could not create GPU VM (T4 or L4) in any zone in $GCP_REGION after $_GPU_MAX_RETRIES attempts."
      echo "Set GPU_MAX_RETRIES=$((_GPU_MAX_RETRIES + 2)) GPU_RETRY_DELAY=60 to keep trying."
      exit 1
    fi
  else
    _create_vm "$GCP_ZONE"
  fi
fi

echo "==> waiting for SSH ..."
# GPU first boot is slower (driver install + reboot): 120 × 5s = 10 min
_SSH_TRIES=40
if [[ "$_GPU_MODE" == "1" ]]; then _SSH_TRIES=120; fi
for _ in $(seq 1 $_SSH_TRIES); do
  if gssh "$GCP_TRAIN_INSTANCE" "echo ok" "$GCP_ZONE" >/dev/null 2>&1; then break; fi
  sleep 5
done
echo "==> waiting for Docker (first boot 1-3 min; GPU first boot 5-10 min) ..."
# GPU: driver install -> reboot -> container toolkit -> docker restart -> up to 10 min
_DOCKER_TRIES=60
if [[ "$_GPU_MODE" == "1" ]]; then _DOCKER_TRIES=120; fi
for i in $(seq 1 $_DOCKER_TRIES); do
  if gssh "$GCP_TRAIN_INSTANCE" "docker compose version" "$GCP_ZONE" >/dev/null 2>&1; then
    echo "    Docker OK"; break
  fi
  if [[ "$i" -eq $_DOCKER_TRIES ]]; then echo "ERROR: Docker not ready."; exit 1; fi
  sleep 5
done
gssh "$GCP_TRAIN_INSTANCE" \
  "sudo usermod -aG docker \$USER; sudo chmod 666 /var/run/docker.sock 2>/dev/null || true; command -v git >/dev/null || sudo apt-get install -y git; command -v tmux >/dev/null || sudo apt-get install -y tmux" \
  "$GCP_ZONE"

if [[ "$_GPU_MODE" == "1" ]]; then
  echo "==> waiting for GPU driver (nvidia-smi) ..."
  _GPU_TRIES=120
  for i in $(seq 1 $_GPU_TRIES); do
    if gssh "$GCP_TRAIN_INSTANCE" "nvidia-smi" "$GCP_ZONE" >/dev/null 2>&1; then
      echo "    GPU OK (already installed — skipped driver install)"
      break
    fi
    if [[ "$i" -eq $_GPU_TRIES ]]; then
      echo "ERROR: nvidia-smi not available after $((_GPU_TRIES * 5))s."
      echo "GPU driver may not have installed. Try stopping and starting the VM:"
      echo "  gcloud compute instances stop $GCP_TRAIN_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT"
      echo "  gcloud compute instances start $GCP_TRAIN_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT"
      exit 1
    fi
    sleep 5
  done
  gssh "$GCP_TRAIN_INSTANCE" "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader" "$GCP_ZONE"
  # Host driver OK is not enough: Docker must see the GPU. Fix CDI/runtime if needed.
  echo "==> ensuring Docker can access GPU ..."
  gssh "$GCP_TRAIN_INSTANCE" "set -e
    sudo mkdir -p /etc/cdi /var/run/cdi
    if ! command -v nvidia-ctk >/dev/null 2>&1; then
      curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey -o /tmp/nvidia-container-toolkit.asc
      sudo gpg --batch --yes --no-tty --dearmor \
        -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
        /tmp/nvidia-container-toolkit.asc
      curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
      sudo apt-get update -y
      sudo apt-get install -y nvidia-container-toolkit
    fi
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
    sudo systemctl restart docker
    for i in \$(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
    sudo chmod 666 /var/run/docker.sock 2>/dev/null || true
    # Prefer nvidia runtime — Docker 25+ --gpus goes through CDI and fails when
    # specs are missing: 'failed to discover GPU vendor from CDI'.
    if docker run --rm --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all \
         nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi; then
      echo '    docker GPU OK (runtime=nvidia)'
    elif docker run --rm --gpus all \
         nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi; then
      echo '    docker GPU OK (--gpus all)'
    else
      echo 'ERROR: host nvidia-smi OK but Docker cannot see GPU'
      ls -la /etc/cdi/ 2>/dev/null || true
      exit 1
    fi
  " "$GCP_ZONE"
fi

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
" "$_GCP_ZONE_ORIGINAL"

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
export QUANTILE_HEAD='$QUANTILE_HEAD'
export QUANTILE_LEVELS='$QUANTILE_LEVELS'
export QUANTILE_LOSS_WEIGHT='$QUANTILE_LOSS_WEIGHT'
export TRAIN_DEVICE='$TRAIN_DEVICE'
export PAIRS_FLAG='$PAIRS_FLAG'
export KEEP_VM='$KEEP_VM'
export MODEL_VOLUME_NAME='$MODEL_VOLUME_NAME'
export GCP_ZONE='$GCP_ZONE'
export GCP_TRAIN_ACCELERATOR='$GCP_TRAIN_ACCELERATOR'
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
  printf '{\"status\":\"%s\",\"git_sha\":\"%s\",\"run\":\"%s\",\"ended\":\"%s\",\"zone\":\"%s\",\"accelerator\":\"%s\"}\n' \
    \"\$status\" \"\${GIT_SHA:-}\" \"\$RUN_ID\" \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"\$GCP_ZONE\" \"\$GCP_TRAIN_ACCELERATOR\" > /tmp/status.json
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
printf '{\"status\":\"RUNNING\",\"git_sha\":\"%s\",\"run\":\"%s\",\"started\":\"%s\",\"zone\":\"%s\",\"accelerator\":\"%s\"}\n' \
  \"\${GIT_SHA:-}\" \"\$RUN_ID\" \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"\$GCP_ZONE\" \"\$GCP_TRAIN_ACCELERATOR\" > /tmp/status.json
gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/\$RUN_ID.json\" || true
gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/latest.json\" || true

echo \"=== train start \$(date -u) run=\$RUN_ID ===\"

echo \"=== checkout \$GIT_REMOTE @ \$GIT_REF ===\"
# Docker containers run as root and leave root-owned files (e.g. __pycache__
# *.pyc) in the bind-mounted repo. A plain 'rm -rf' as the non-root user then
# fails with 'Permission denied', which aborts the whole job under 'set -e'.
# Use sudo so the stale checkout is always removable.
sudo rm -rf \$HOME/\$REMOTE_REPO_NAME
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

# --- GPU vs CPU docker runner ------------------------------------------------
if [[ \"\$TRAIN_DEVICE\" == \"cuda\" ]]; then
  echo \"=== Docker GPU opts ===\"
  # --gpus all breaks on Docker 25+ when CDI specs are stale/missing.
  # nvidia runtime injects devices without Docker's CDI discovery path.
  _GPU_OPTS=\"--runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all\"
  if ! docker run --rm \$_GPU_OPTS nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1; then
    echo \"runtime=nvidia failed → refreshing CDI + trying --gpus all\"
    sudo mkdir -p /etc/cdi /var/run/cdi
    sudo nvidia-ctk runtime configure --runtime=docker || true
    sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml || true
    _GPU_OPTS=\"--gpus all\"
    docker run --rm \$_GPU_OPTS nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
  fi

  if docker image inspect ml_trainer_gpu >/dev/null 2>&1; then
    echo \"=== GPU image ml_trainer_gpu already present (skip rebuild) ===\"
  else
    echo \"=== building GPU image (Dockerfile.train.gpu) ===\"
    docker build -t ml_trainer_gpu -f ml/train/Dockerfile.train.gpu ml/train
  fi

  # compose run lacks GPU passthrough — plain docker run + bind-mount train code
  _DOCKER_GPU_RUN=\"docker run \$_GPU_OPTS --rm --network trading_agent_default\"
  _DOCKER_GPU_RUN=\"\$_DOCKER_GPU_RUN -v \$HOME/\$REMOTE_REPO_NAME/ml/train:/workspace/train\"
  _DOCKER_GPU_RUN=\"\$_DOCKER_GPU_RUN -v \$MODEL_VOLUME_NAME:/models\"
  _DOCKER_GPU_RUN=\"\$_DOCKER_GPU_RUN -e MODEL_DIR=/models\"
  _DOCKER_GPU_RUN=\"\$_DOCKER_GPU_RUN -e OUTPUT_DIR=/workspace/train/output\"
  _DOCKER_GPU_RUN=\"\$_DOCKER_GPU_RUN -e HORIZONS_MINUTES=\$HORIZONS\"
  _DOCKER_GPU_RUN=\"\$_DOCKER_GPU_RUN -e PRIMARY_HORIZON=\$PRIMARY\"
  _DOCKER_GPU_RUN=\"\$_DOCKER_GPU_RUN -e SEQ_LEN=\$SEQ_LEN\"
  _DOCKER_GPU_RUN=\"\$_DOCKER_GPU_RUN -e QUANTILE_HEAD=\$QUANTILE_HEAD\"
  _DOCKER_GPU_RUN=\"\$_DOCKER_GPU_RUN -e QUANTILE_LEVELS=\$QUANTILE_LEVELS\"
  _DOCKER_GPU_RUN=\"\$_DOCKER_GPU_RUN -e QUANTILE_LOSS_WEIGHT=\$QUANTILE_LOSS_WEIGHT\"
  _DOCKER_GPU_RUN=\"\$_DOCKER_GPU_RUN -e FLUX_GIT_SHA=\$GIT_SHA\"
fi

echo \"=== train_m2 epochs=\$EPOCHS seq=\$SEQ_LEN horizons=\$HORIZONS primary=\$PRIMARY quantile_head=\$QUANTILE_HEAD device=\$TRAIN_DEVICE ===\"
if [[ \"\$TRAIN_DEVICE\" == \"cuda\" ]]; then
  \$_DOCKER_GPU_RUN ml_trainer_gpu python train_m2.py --device cuda --epochs \$EPOCHS --seq-len \$SEQ_LEN \
    --horizons \$HORIZONS --primary \$PRIMARY \$PAIRS_FLAG
else
  docker compose --profile ml run --rm \
    -e HORIZONS_MINUTES=\$HORIZONS -e PRIMARY_HORIZON=\$PRIMARY -e SEQ_LEN=\$SEQ_LEN \
    -e QUANTILE_HEAD=\$QUANTILE_HEAD -e QUANTILE_LEVELS=\$QUANTILE_LEVELS -e QUANTILE_LOSS_WEIGHT=\$QUANTILE_LOSS_WEIGHT \
    -e FLUX_GIT_SHA=\$GIT_SHA \
    ml_trainer python train_m2.py --device cpu --epochs \$EPOCHS --seq-len \$SEQ_LEN \
      --horizons \$HORIZONS --primary \$PRIMARY \$PAIRS_FLAG
fi

echo \"=== eval_m2 ===\"
if [[ \"\$TRAIN_DEVICE\" == \"cuda\" ]]; then
  \$_DOCKER_GPU_RUN ml_trainer_gpu python eval_m2.py --checkpoint /models/m2_multi.pt --device cuda \
    --gate 0.35,0.4,0.45,0.5,0.55,0.6 || true
else
  docker compose --profile ml run --rm \
    -e HORIZONS_MINUTES=\$HORIZONS -e PRIMARY_HORIZON=\$PRIMARY -e SEQ_LEN=\$SEQ_LEN \
    ml_trainer python eval_m2.py --checkpoint /models/m2_multi.pt --device cpu \
      --gate 0.35,0.4,0.45,0.5,0.55,0.6 || true
fi

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
" "$GCP_ZONE"

echo ""
if [[ "$_GPU_MODE" == "1" ]]; then
  echo "OK — GPU training started on $GCP_TRAIN_INSTANCE ($GCP_TRAIN_MACHINE + $GCP_TRAIN_ACCELERATOR) (run=$RUN_ID, device=cuda)."
else
  echo "OK — training started on $GCP_TRAIN_INSTANCE (run=$RUN_ID)."
fi
echo "The VM will DELETE itself on success, STOP itself on failure (KEEP_VM=$KEEP_VM)."
echo "Mac may sleep now. Monitor:  ./scripts/gcp_status.sh"
echo "When DONE:                   ./scripts/gcp_promote.sh"
