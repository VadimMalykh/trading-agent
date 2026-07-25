#!/usr/bin/env bash
# Fetch FULL training logs from the GCS bucket (works even after the train VM
# self-deleted). Complements gcp_status.sh, which only tails 40 lines.
#
# Logs live at:  gs://<bucket>/logs/<RUN_ID>.log
# Status marker: gs://<bucket>/status/<RUN_ID>.json  (and .../latest.json)
#
#   ./scripts/gcp_logs.sh                 # full log of the LATEST run (from latest.json)
#   ./scripts/gcp_logs.sh 20260724T144653Z   # full log of a specific run id
#   ./scripts/gcp_logs.sh --list          # list all run ids (newest last) + status
#   ./scripts/gcp_logs.sh --save          # also save latest log to $EXPORT_DIR
#   ./scripts/gcp_logs.sh <run_id> --save # save a specific run's log
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud

RUN_ARG=""
SAVE=0
LIST=0
for a in "$@"; do
  case "$a" in
    --list) LIST=1 ;;
    --save) SAVE=1 ;;
    -*) echo "unknown arg: $a" >&2; exit 2 ;;
    *) RUN_ARG="$a" ;;
  esac
done

echo "==> bucket: $GCS_BUCKET"

# --- list mode: enumerate every run in the bucket -------------------------------
if [[ "$LIST" -eq 1 ]]; then
  echo "==> runs (logs/<run_id>.log, oldest → newest):"
  gcloud storage ls "$GCS_BUCKET/logs/" 2>/dev/null \
    | sed -n 's#.*/logs/\(.*\)\.log$#\1#p' | sort || {
      echo "(no logs in bucket yet)"; exit 0; }
  echo ""
  echo "latest status: $(gcloud storage cat "$GCS_BUCKET/status/latest.json" 2>/dev/null || echo '<none>')"
  echo ""
  echo "Full log:  ./scripts/gcp_logs.sh <run_id>"
  exit 0
fi

# --- resolve run id: explicit arg, else the 'run' field of latest.json ----------
RUN_ID="$RUN_ARG"
if [[ -z "$RUN_ID" ]]; then
  STATUS_JSON="$(gcloud storage cat "$GCS_BUCKET/status/latest.json" 2>/dev/null || true)"
  if [[ -z "$STATUS_JSON" ]]; then
    echo "No status/latest.json in bucket — nothing has run yet, or run is still starting."
    echo "List what's there:  ./scripts/gcp_logs.sh --list"
    exit 1
  fi
  RUN_ID="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"run":"\([^"]*\)".*/\1/p')"
  STATE="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')"
  echo "latest run: $RUN_ID  (status=${STATE:-?})"
fi

LOG_OBJ="$GCS_BUCKET/logs/$RUN_ID.log"

# --- optional local save --------------------------------------------------------
if [[ "$SAVE" -eq 1 ]]; then
  mkdir -p "$EXPORT_DIR"
  DEST="$EXPORT_DIR/${RUN_ID}.log"
  if gcloud storage cp "$LOG_OBJ" "$DEST" 2>/dev/null; then
    echo "saved → $DEST"
  else
    echo "ERROR: log not found: $LOG_OBJ"
    echo "The run may still be in progress (log lands in the bucket only when the"
    echo "job finishes). While the VM is alive, watch live:  ./scripts/gcp_status.sh"
    exit 1
  fi
fi

# --- print full log -------------------------------------------------------------
echo "==> full log ($LOG_OBJ):"
echo "--------------------------------------------------------------------------"
if ! gcloud storage cat "$LOG_OBJ" 2>/dev/null; then
  echo "ERROR: log not found: $LOG_OBJ"
  echo ""
  echo "Possible reasons:"
  echo "  - run still in progress (log is uploaded only at finish; use gcp_status.sh"
  echo "    for the live tmux view while the VM is alive)"
  echo "  - wrong run id (list them:  ./scripts/gcp_logs.sh --list)"
  exit 1
fi
