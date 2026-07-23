#!/usr/bin/env bash
# V2 STEP 2/3 — status of the current/last training run.
#
# Reads the run status + tail of the log from the bucket (works even after the
# train VM has self-deleted). If the VM is still alive, prints the tmux attach
# command for a live view.
#
#   ./scripts/gcp_status.sh            # latest run
#   ./scripts/gcp_status.sh 20260724T101500Z   # a specific run id
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud

RUN_ARG="${1:-}"

echo "==> bucket: $GCS_BUCKET"

# --- status marker --------------------------------------------------------------
STATUS_OBJ="$GCS_BUCKET/status/latest.json"
if [[ -n "$RUN_ARG" ]]; then STATUS_OBJ="$GCS_BUCKET/status/$RUN_ARG.json"; fi

STATUS_JSON="$(gcloud storage cat "$STATUS_OBJ" 2>/dev/null || true)"
if [[ -z "$STATUS_JSON" ]]; then
  echo "RESULT: no status marker yet → training likely STILL RUNNING (or never started)."
else
  echo "status: $STATUS_JSON"
fi

# derive run id + state for log tail / next-step hint
RUN_ID="$RUN_ARG"
STATE=""
if [[ -n "$STATUS_JSON" ]]; then
  STATE="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')"
  if [[ -z "$RUN_ID" ]]; then
    RUN_ID="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"run":"\([^"]*\)".*/\1/p')"
  fi
fi

# --- VM liveness ----------------------------------------------------------------
VM_STATE="$(gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
  --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)' 2>/dev/null || true)"
if [[ -n "$VM_STATE" ]]; then
  echo "train VM $GCP_TRAIN_INSTANCE: $VM_STATE"
  if [[ "$VM_STATE" == "RUNNING" ]]; then
    echo "live view:  gcloud compute ssh $GCP_TRAIN_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tmux attach -t fluxtrain"
    echo "            (detach without stopping: Ctrl-b then d)"
  elif [[ "$VM_STATE" == "TERMINATED" ]]; then
    echo "VM is STOPPED (likely a FAILED run kept for debug). Start + inspect:"
    echo "  gcloud compute instances start $GCP_TRAIN_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT"
    echo "  gcloud compute ssh $GCP_TRAIN_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tail -n 120 '~/train_m2.log'"
  fi
else
  echo "train VM $GCP_TRAIN_INSTANCE: gone (self-deleted or never created)"
fi

# --- log tail from bucket -------------------------------------------------------
if [[ -n "$RUN_ID" ]]; then
  echo ""
  echo "==> last 40 log lines ($GCS_BUCKET/logs/$RUN_ID.log):"
  gcloud storage cat "$GCS_BUCKET/logs/$RUN_ID.log" 2>/dev/null | tail -n 40 \
    || echo "(no log in bucket yet — still running; use the live view above)"
fi

echo ""
case "$STATE" in
  DONE)   echo "→ DONE. Promote:  ./scripts/gcp_promote.sh" ;;
  FAILED) echo "→ FAILED. VM stopped for debug (see above). Fix + re-run ./scripts/gcp_train.sh" ;;
  *)      echo "→ still running (or no marker). Re-run this to poll; the VM self-cleans when finished." ;;
esac
