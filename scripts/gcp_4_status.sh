#!/usr/bin/env bash
# STEP 4/5 — Check whether remote training is still running, finished, or crashed
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

echo ""
echo "==> STEP 4: train status on $GCP_TRAIN_INSTANCE"

if ! gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
  --project="$GCP_PROJECT" --zone="$GCP_ZONE" >/dev/null 2>&1; then
  echo "Train VM does not exist. Run step 2–3 first."
  exit 1
fi

STATUS=$(gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
  --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)')
echo "VM status: $STATUS"
if [[ "$STATUS" != "RUNNING" ]]; then
  exit 1
fi

gssh "$GCP_TRAIN_INSTANCE" '
echo "--- tmux ---"
if tmux has-session -t fluxtrain 2>/dev/null; then
  echo "fluxtrain: ACTIVE"
  TMUX_ALIVE=1
else
  echo "fluxtrain: (no session — finished or crashed)"
  TMUX_ALIVE=0
fi
echo "--- status file ---"
if [[ -f $HOME/train_m2.status ]]; then
  cat $HOME/train_m2.status
else
  echo "(missing)"
fi
echo "--- checkpoint on VM ---"
ls -la $HOME/m2_multi.pt 2>/dev/null || echo "(no m2_multi.pt yet)"
echo "--- last 40 log lines ---"
tail -n 40 $HOME/train_m2.log 2>/dev/null || echo "(no log yet)"
echo "--- recent OOM (dmesg) ---"
sudo dmesg -T 2>/dev/null | grep -iE "Out of memory|Killed process.*python" | tail -5 || echo "(none or no sudo)"
'

echo ""
if gssh "$GCP_TRAIN_INSTANCE" "test -f \$HOME/train_m2.status && test -f \$HOME/m2_multi.pt" 2>/dev/null; then
  echo "RESULT: DONE — run ./scripts/gcp_5_finish.sh"
elif gssh "$GCP_TRAIN_INSTANCE" "tmux has-session -t fluxtrain 2>/dev/null" 2>/dev/null; then
  echo "RESULT: STILL RUNNING — wait and re-run ./scripts/gcp_4_status.sh"
  echo "Optional live attach: gcloud compute ssh $GCP_TRAIN_INSTANCE --zone=$GCP_ZONE -- tmux attach -t fluxtrain"
elif gssh "$GCP_TRAIN_INSTANCE" "test -f \$HOME/train_m2.log" 2>/dev/null; then
  echo "RESULT: FAILED — tmux gone, no DONE status (often OOM on 8GB)."
  echo "  Log: gcloud compute ssh $GCP_TRAIN_INSTANCE --zone=$GCP_ZONE -- tail -n 80 \$HOME/train_m2.log"
  echo "  Fix: set GCP_TRAIN_MACHINE=e2-standard-4 in scripts/gcp_env, delete train VM, re-run steps 2–3."
  exit 2
else
  echo "RESULT: NOT STARTED — run ./scripts/gcp_3_start_train.sh"
  exit 1
fi
