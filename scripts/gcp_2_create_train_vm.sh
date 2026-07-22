#!/usr/bin/env bash
# STEP 2/5 — Create (or start) temporary train VM and install Docker
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

echo ""
echo "==> STEP 2: ensure train VM $GCP_TRAIN_INSTANCE exists"

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
  echo "    creating $GCP_TRAIN_MACHINE ..."
  gcloud compute instances create "$GCP_TRAIN_INSTANCE" \
    --project="$GCP_PROJECT" \
    --zone="$GCP_ZONE" \
    --machine-type="$GCP_TRAIN_MACHINE" \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=50GB \
    --boot-disk-type=pd-balanced \
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
# allow default login user to use docker
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
    echo "    Docker OK"
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "ERROR: Docker not ready. SSH in and check startup logs."
    exit 1
  fi
  sleep 5
done

# Ensure docker sock usable for the SSH user without re-login
gssh "$GCP_TRAIN_INSTANCE" \
  "sudo usermod -aG docker \$USER; sudo chmod 666 /var/run/docker.sock 2>/dev/null || true; command -v tmux >/dev/null || sudo apt-get install -y tmux"

echo ""
echo "OK — train VM ready: $GCP_TRAIN_INSTANCE"
echo "Next: ./scripts/gcp_3_start_train.sh"
