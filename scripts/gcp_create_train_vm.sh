#!/usr/bin/env bash
# Create (or reuse) ephemeral CPU VM for training. Does not start train.
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

if gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
  --project="$GCP_PROJECT" --zone="$GCP_ZONE" >/dev/null 2>&1; then
  STATUS=$(gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)')
  echo "==> Instance $GCP_TRAIN_INSTANCE already exists (status=$STATUS)"
  if [[ "$STATUS" == "TERMINATED" ]]; then
    echo "==> Starting ..."
    gcloud compute instances start "$GCP_TRAIN_INSTANCE" \
      --project="$GCP_PROJECT" --zone="$GCP_ZONE"
  fi
else
  echo "==> Creating $GCP_TRAIN_INSTANCE ($GCP_TRAIN_MACHINE) ..."
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
apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
usermod -aG docker ubuntu 2>/dev/null || true
usermod -aG docker $(logname 2>/dev/null || echo vadim) 2>/dev/null || true
touch /var/log/fluxtrader-train-ready
'
  echo "==> Waiting for VM to become RUNNING ..."
  sleep 15
fi

echo "==> Waiting for SSH ..."
for i in $(seq 1 30); do
  if gssh "$GCP_TRAIN_INSTANCE" "echo ok" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

echo "==> Waiting for Docker (startup-script may take 1–3 min on first boot) ..."
for i in $(seq 1 60); do
  if gssh "$GCP_TRAIN_INSTANCE" "docker compose version" >/dev/null 2>&1; then
    echo "    Docker ready"
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "WARN: Docker not ready yet. SSH in and check: sudo journalctl -u google-startup-scripts"
    exit 1
  fi
  sleep 5
done

echo "==> Ensure docker usable without reboot (newgrp workaround) ..."
gssh "$GCP_TRAIN_INSTANCE" "sudo usermod -aG docker \$USER; sudo chmod 666 /var/run/docker.sock 2>/dev/null || true"

echo "==> Done. Train VM: $GCP_TRAIN_INSTANCE"
echo "    Next: ./scripts/gcp_run_train.sh"
