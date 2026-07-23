#!/usr/bin/env bash
# V2 STEP 3/3 — promote the trained checkpoint + serve code to the always-on VM.
#
# Pulls checkpoints/latest.pt from the bucket, installs it into the model volume
# on always-on, checks out the same GIT_REF for serve code, restarts inference.
# No VM teardown here — the train VM already self-deleted on success.
#
#   ./scripts/gcp_promote.sh                 # promote latest DONE run
#   ./scripts/gcp_promote.sh --local-copy    # also save a backup to EXPORT_DIR
#   ./scripts/gcp_promote.sh --force         # skip the DONE-status guard
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

LOCAL_COPY=0
FORCE=0
for a in "$@"; do
  case "$a" in
    --local-copy) LOCAL_COPY=1 ;;
    --force)      FORCE=1 ;;
    *) echo "unknown arg: $a"; exit 2 ;;
  esac
done

R="\$HOME/${REMOTE_REPO_NAME}"

# --- guard: only promote a DONE run ---------------------------------------------
STATUS_JSON="$(gcloud storage cat "$GCS_BUCKET/status/latest.json" 2>/dev/null || true)"
STATE="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')"
GIT_SHA="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"git_sha":"\([^"]*\)".*/\1/p')"
echo "==> latest run status: ${STATE:-<none>}  git_sha=${GIT_SHA:-<none>}"
if [[ "$FORCE" -ne 1 && "$STATE" != "DONE" ]]; then
  echo "ERROR: latest run is not DONE (state=${STATE:-none})."
  echo "Check ./scripts/gcp_status.sh, or pass --force to promote anyway."
  exit 1
fi

if ! gcloud storage ls "$GCS_BUCKET/checkpoints/latest.pt" >/dev/null 2>&1; then
  echo "ERROR: $GCS_BUCKET/checkpoints/latest.pt not found."
  exit 1
fi

# --- optional Mac backup --------------------------------------------------------
if [[ "$LOCAL_COPY" -eq 1 ]]; then
  mkdir -p "$EXPORT_DIR"
  gcloud storage cp "$GCS_BUCKET/checkpoints/latest.pt" "$EXPORT_DIR/m2_multi.pt"
  gcloud storage cat "$GCS_BUCKET/status/latest.json" > "$EXPORT_DIR/last_run.json" 2>/dev/null || true
  RUN_ID="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"run":"\([^"]*\)".*/\1/p')"
  [[ -n "$RUN_ID" ]] && gcloud storage cp "$GCS_BUCKET/logs/$RUN_ID.log" "$EXPORT_DIR/train_m2.log" 2>/dev/null || true
  echo "    backup → $EXPORT_DIR/"
fi

# --- promote on always-on: serve code (git) + checkpoint (bucket) ---------------
echo ""
echo "==> install checkpoint + serve code on $GCP_ALWAYS_ON (GIT_REF=$GIT_REF)"
gssh "$GCP_ALWAYS_ON" "set -e
  cd $R
  # Match the trained code exactly (serve.py must read checkpoint norm_stats + dir head)
  git fetch --all --quiet
  git checkout '$GIT_REF'
  git pull --ff-only || true

  gcloud storage cp '$GCS_BUCKET/checkpoints/latest.pt' /tmp/m2_multi.pt
  VOL='$MODEL_VOLUME_NAME'
  docker volume create \"\$VOL\" >/dev/null 2>&1 || true
  docker run --rm -v \"\$VOL:/models\" -v /tmp:/in:ro alpine \
    sh -c 'cp /in/m2_multi.pt /models/m2_multi.pt && ls -la /models/m2_multi.pt'

  docker compose up -d --force-recreate ml_inference
  echo ml_inference recreated
  sleep 4
  curl -sS --retry 5 --retry-delay 1 --retry-connrefused http://127.0.0.1:8001/health
  echo
"

echo ""
echo "OK — promoted."
echo "  Checkpoint installed on always-on model volume ($MODEL_VOLUME_NAME)."
echo "  Serve code @ $GIT_REF (git). Expect health: primary=$TRAIN_PRIMARY horizons=[$TRAIN_HORIZONS] norm=ckpt."
