#!/usr/bin/env bash
# STEP 4/5 — Check whether remote training is still running or finished
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
tmux ls 2>/dev/null || echo "(no tmux sessions)"
echo "--- status file ---"
if [[ -f $HOME/train_m2.status ]]; then
  cat $HOME/train_m2.status
else
  echo "NOT_DONE (still running or not started)"
fi
echo "--- checkpoint on VM ---"
ls -la $HOME/m2_multi.pt 2>/dev/null || echo "(no m2_multi.pt yet)"
echo "--- last 30 log lines ---"
tail -n 30 $HOME/train_m2.log 2>/dev/null || echo "(no log yet)"
'

echo ""
if gssh "$GCP_TRAIN_INSTANCE" "test -f \$HOME/train_m2.status" 2>/dev/null; then
  echo "RESULT: DONE — run ./scripts/gcp_5_finish.sh"
else
  echo "RESULT: STILL RUNNING — wait and re-run ./scripts/gcp_4_status.sh"
  echo "Optional live attach (SSH): gcloud compute ssh $GCP_TRAIN_INSTANCE --zone=$GCP_ZONE -- tmux attach -t fluxtrain"
fi
