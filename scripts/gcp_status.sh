#!/usr/bin/env bash
# V2 STEP 2/3 — status of the current/last training run.
#
# Reads the run status + tail (last 40 lines) of the log from the bucket (works
# even after the train VM has self-deleted). If the VM is still alive, prints the
# tmux attach command for a live view.
#
# For the FULL log of any run, use ./scripts/gcp_logs.sh (see that script).
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
  # Labeled 'last marker' because it can lag the true state (only rewritten by the
  # job at start=RUNNING and finish=DONE/FAILED). Reconciled against the VM below.
  echo "last marker: $STATUS_JSON"
fi

# derive run id + state for log tail / next-step hint
RUN_ID="$RUN_ARG"
STATE=""
TRAIN_ZONE=""
ACCELERATOR=""
if [[ -n "$STATUS_JSON" ]]; then
  STATE="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')"
  TRAIN_ZONE="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"zone":"\([^"]*\)".*/\1/p')"
  ACCELERATOR="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"accelerator":"\([^"]*\)".*/\1/p')"
  if [[ -z "$RUN_ID" ]]; then
    RUN_ID="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"run":"\([^"]*\)".*/\1/p')"
  fi
fi
# Fall back to configured zone if status marker doesn't have one
[[ -z "$TRAIN_ZONE" ]] && TRAIN_ZONE="$GCP_ZONE"

# --- VM liveness ----------------------------------------------------------------
VM_STATE="$(gcloud compute instances describe "$GCP_TRAIN_INSTANCE" \
  --project="$GCP_PROJECT" --zone="$TRAIN_ZONE" --format='get(status)' 2>/dev/null || true)"
if [[ -n "$VM_STATE" ]]; then
  echo "train VM $GCP_TRAIN_INSTANCE: $VM_STATE (zone=$TRAIN_ZONE${ACCELERATOR:+, gpu=$ACCELERATOR})"
  if [[ "$VM_STATE" == "RUNNING" ]]; then
    echo "live view:  gcloud compute ssh $GCP_TRAIN_INSTANCE --zone=$TRAIN_ZONE --project=$GCP_PROJECT -- tmux attach -t fluxtrain"
    echo "            (detach without stopping: Ctrl-b then d)"
  elif [[ "$VM_STATE" == "TERMINATED" ]]; then
    echo "VM is STOPPED (likely a FAILED run kept for debug). Start + inspect:"
    echo "  gcloud compute instances start $GCP_TRAIN_INSTANCE --zone=$TRAIN_ZONE --project=$GCP_PROJECT"
    echo "  gcloud compute ssh $GCP_TRAIN_INSTANCE --zone=$TRAIN_ZONE --project=$GCP_PROJECT -- tail -n 120 '~/train_m2.log'"
  fi
else
  echo "train VM $GCP_TRAIN_INSTANCE: gone (self-deleted or never created)"
fi

# --- reconcile marker vs VM + live job ------------------------------------------
# The status marker is only rewritten by the job (RUNNING at start, DONE/FAILED at
# finish), so a stale DONE/FAILED from a previous run must not mislead. But the VM
# alone is not the source of truth either: a RUNNING VM does NOT mean a job is
# running: gcp_train.sh can leave a
# fully provisioned VM behind if the launcher dies (Ctrl-C, dropped SSH, laptop
# sleep) after creating it but before writing ~/run_flux_train.sh. That VM then
# idles — billing, with no tmux session — while this script used to report
# "RUNNING, do not launch another run". So probe the VM for the actual job.
EFFECTIVE="$STATE"
if [[ "$VM_STATE" == "RUNNING" ]]; then
  JOB=""
  if gcloud compute ssh "$GCP_TRAIN_INSTANCE" --project="$GCP_PROJECT" --zone="$TRAIN_ZONE" \
       --command="tmux has-session -t fluxtrain 2>/dev/null && echo JOB_UP || echo JOB_DOWN" \
       >/tmp/.flux_job_probe 2>/dev/null; then
    JOB="$(grep -o 'JOB_UP\|JOB_DOWN' /tmp/.flux_job_probe | head -1 || true)"
  fi
  rm -f /tmp/.flux_job_probe

  case "$JOB" in
    JOB_UP)
      EFFECTIVE="RUNNING"
      if [[ "$STATE" == "DONE" || "$STATE" == "FAILED" ]]; then
        echo ""
        echo "NOTE: marker says '$STATE' but tmux 'fluxtrain' is alive on the VM → that"
        echo "      marker is from a PREVIOUS run; a new run is in progress."
      fi
      ;;
    JOB_DOWN)
      EFFECTIVE="IDLE_VM"
      echo ""
      echo "WARNING: VM is RUNNING but there is NO tmux 'fluxtrain' session — no job is"
      echo "         running. The launcher most likely died after creating the VM but"
      echo "         before starting the job. The VM is idling and still billing."
      echo "         The marker above ('$STATE') is from the last run that actually ran."
      ;;
    *)
      echo ""
      echo "NOTE: VM is RUNNING but the SSH probe for tmux 'fluxtrain' failed, so whether"
      echo "      a job is running is UNKNOWN. Check by hand before launching:"
      echo "        gcloud compute ssh $GCP_TRAIN_INSTANCE --zone=$TRAIN_ZONE --project=$GCP_PROJECT -- tmux ls"
      EFFECTIVE="UNKNOWN_VM_UP"
      ;;
  esac
fi

# --- log tail from bucket -------------------------------------------------------
if [[ -n "$RUN_ID" ]]; then
  echo ""
  echo "==> last 40 log lines ($GCS_BUCKET/logs/$RUN_ID.log):"
  gcloud storage cat "$GCS_BUCKET/logs/$RUN_ID.log" 2>/dev/null | tail -n 40 \
    || echo "(no log in bucket yet — still running; use the live view above)"
  echo ""
  echo "full log:   ./scripts/gcp_logs.sh $RUN_ID     (all runs: ./scripts/gcp_logs.sh --list)"
fi

echo ""
case "$EFFECTIVE" in
  RUNNING) echo "→ RUNNING. Do NOT launch another run (one VM + shared bucket keys). Poll with this script; watch live via the log tail / tmux above." ;;
  DONE)    echo "→ DONE. Promote:  ./scripts/gcp_promote.sh" ;;
  FAILED)  echo "→ FAILED. VM stopped for debug (see above). Fix + re-run ./scripts/gcp_train.sh" ;;
  IDLE_VM) echo "→ IDLE VM. Nothing is training. Re-run ./scripts/gcp_train.sh — it REUSES a"
           echo "  RUNNING VM instead of recreating it, which matters during a GPU stockout."
           echo "  If you are done, stop it:  gcloud compute instances delete $GCP_TRAIN_INSTANCE --zone=$TRAIN_ZONE --project=$GCP_PROJECT" ;;
  UNKNOWN_VM_UP)
           echo "→ VM is up, job state UNKNOWN (SSH probe failed). Verify with 'tmux ls' above before launching." ;;
  *)       echo "→ no marker yet. If the VM is RUNNING a run just started; otherwise nothing is running." ;;
esac
