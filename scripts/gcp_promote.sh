#!/usr/bin/env bash
# V2 STEP 3/3 — promote a NAMED checkpoint + serve code to the always-on VM.
#
# Installs the checkpoint into the model volume on always-on, checks out matching
# serve code, restarts inference. No VM teardown here — the train VM already
# self-deleted on success.
#
#   ./scripts/gcp_promote.sh --checkpoint m2_multi_20260819T142759Z_a186182b.pt
#   ./scripts/gcp_promote.sh --checkpoint latest        # promote checkpoints/latest.pt
#   ./scripts/gcp_promote.sh --checkpoint <key> --local-copy   # also back up to EXPORT_DIR
#   ./scripts/gcp_promote.sh --checkpoint <key> --force        # skip the DONE-status guard
#   ./scripts/gcp_promote.sh --list                     # show promotable checkpoints
#
# 🔴 --checkpoint is REQUIRED and has no default. It used to promote
# `checkpoints/latest.pt` unconditionally, but EVERY training run overwrites that
# key, so "promote" meant "ship whatever finished last" — which at various points
# was O3 and then P2, the two worst models the project has produced. The operator
# now has to name what they are shipping.
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud
echo_cfg

LOCAL_COPY=0
FORCE=0
LIST=0
CKPT_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --local-copy) LOCAL_COPY=1; shift ;;
    --force)      FORCE=1; shift ;;
    --list)       LIST=1; shift ;;
    --checkpoint)
      [[ $# -ge 2 ]] || { echo "--checkpoint needs a value"; exit 2; }
      CKPT_ARG="$2"; shift 2 ;;
    --checkpoint=*) CKPT_ARG="${1#*=}"; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

list_checkpoints() {
  echo "Promotable checkpoints (newest last):"
  gcloud storage ls -l "$GCS_BUCKET/checkpoints/" 2>/dev/null | grep -E '\.pt$' || true
}

if [[ "$LIST" -eq 1 ]]; then
  list_checkpoints
  exit 0
fi

# --- resolve + guard the checkpoint key ------------------------------------------
STATUS_JSON="$(gcloud storage cat "$GCS_BUCKET/status/latest.json" 2>/dev/null || true)"
STATE="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')"
LATEST_RUN="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"run":"\([^"]*\)".*/\1/p')"
LATEST_SHA="$(printf '%s' "$STATUS_JSON" | sed -n 's/.*"git_sha":"\([^"]*\)".*/\1/p')"

if [[ -z "$CKPT_ARG" ]]; then
  echo "ERROR: --checkpoint is required; there is no default."
  echo ""
  echo "  checkpoints/latest.pt is overwritten by EVERY training run, so the bare"
  echo "  form used to ship whatever finished last regardless of whether it was any"
  echo "  good. Name the checkpoint you intend to serve."
  echo ""
  echo "  latest run: ${LATEST_RUN:-<none>} (status=${STATE:-none}, git=${LATEST_SHA:-?})"
  echo "  To promote exactly that run's output:  $0 --checkpoint latest"
  echo ""
  list_checkpoints
  exit 2
fi

case "$CKPT_ARG" in
  latest|latest.pt|checkpoints/latest.pt)
            CKPT_KEY="checkpoints/latest.pt" ;;
  gs://*)   CKPT_KEY="${CKPT_ARG#"$GCS_BUCKET"/}" ;;
  checkpoints/*) CKPT_KEY="$CKPT_ARG" ;;
  *)        CKPT_KEY="checkpoints/$CKPT_ARG" ;;
esac
CKPT_URL="$GCS_BUCKET/$CKPT_KEY"

if ! gcloud storage ls "$CKPT_URL" >/dev/null 2>&1; then
  echo "ERROR: checkpoint not found: $CKPT_URL"
  echo ""
  list_checkpoints
  exit 1
fi
echo "==> promoting checkpoint: $CKPT_KEY"

# The DONE guard only means anything for `latest`, which by definition is the most
# recent run's output. A named historical checkpoint is a finished artifact — the
# state of some later, unrelated run says nothing about it.
if [[ "$CKPT_KEY" == "checkpoints/latest.pt" ]]; then
  echo "    latest.pt == run ${LATEST_RUN:-<unknown>} (status=${STATE:-none}, git=${LATEST_SHA:-?})"
  if [[ "$FORCE" -ne 1 && "$STATE" != "DONE" ]]; then
    echo "ERROR: latest run is not DONE (state=${STATE:-none})."
    echo "Check ./scripts/gcp_status.sh, or pass --force to promote anyway."
    exit 1
  fi
elif [[ -n "$LATEST_RUN" ]]; then
  echo "    NOTE: this is NOT latest.pt (latest.pt is run ${LATEST_RUN})."
fi

# --- serve code must match the code that TRAINED this checkpoint -----------------
# Checkpoint keys are `m2_multi_<run_id>_<git_sha8>.pt`, so a named checkpoint
# carries its own commit. Using the ambient GIT_REF (or the latest run's sha) would
# check out serve code from a different commit than the one that wrote the file —
# and serve.py reads the checkpoint's norm_stats, meta and head layout, so a
# mismatch is exactly the kind of silent skew that voids a promotion.
PROMOTE_REF="$GIT_REF"
CKPT_SHA="$(basename "$CKPT_KEY" .pt | sed -n 's/.*_\([0-9a-f]\{8\}\)$/\1/p')"
if [[ -n "$CKPT_SHA" ]]; then
  PROMOTE_REF="$CKPT_SHA"
  echo "    serve code pinned to the checkpoint's own commit: $CKPT_SHA"
elif [[ "$CKPT_KEY" == "checkpoints/latest.pt" && -n "$LATEST_SHA" ]]; then
  PROMOTE_REF="$LATEST_SHA"
  echo "    serve code pinned to the latest run's commit: $LATEST_SHA"
else
  echo "    WARNING: cannot infer the checkpoint's commit — using GIT_REF=$GIT_REF."
  echo "             If serving misbehaves, that skew is the first thing to check."
fi

R="\$HOME/${REMOTE_REPO_NAME}"

# --- optional Mac backup --------------------------------------------------------
if [[ "$LOCAL_COPY" -eq 1 ]]; then
  mkdir -p "$EXPORT_DIR"
  gcloud storage cp "$CKPT_URL" "$EXPORT_DIR/m2_multi.pt"
  gcloud storage cat "$GCS_BUCKET/status/latest.json" > "$EXPORT_DIR/last_run.json" 2>/dev/null || true
  [[ -n "$LATEST_RUN" ]] && gcloud storage cp "$GCS_BUCKET/logs/$LATEST_RUN.log" "$EXPORT_DIR/train_m2.log" 2>/dev/null || true
  echo "    backup → $EXPORT_DIR/"
fi

# --- promote on always-on: serve code (git) + checkpoint (bucket) ---------------
echo ""
echo "==> install checkpoint + serve code on $GCP_ALWAYS_ON (ref=$PROMOTE_REF)"
gssh "$GCP_ALWAYS_ON" "set -e
  cd $R
  # Match the trained code exactly (serve.py must read checkpoint norm_stats + dir head)
  git fetch --all --quiet
  git checkout '$PROMOTE_REF'
  git pull --ff-only || true

  gcloud storage cp '$CKPT_URL' /tmp/m2_multi.pt
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
echo "OK — promoted $CKPT_KEY."
echo "  Checkpoint installed on always-on model volume ($MODEL_VOLUME_NAME)."
echo "  Serve code @ $PROMOTE_REF (git)."
echo ""
echo "🔴 Check the /health line above before walking away:"
echo "   gate_source=\"checkpoint\"      → healthy: served at the operating point it was"
echo "                                  measured at (gate_target_coverage says which)."
echo "   gate_source=\"config-fallback\" → this checkpoint has no served_gate in its meta."
echo "                                  Re-run eval_m2.py on it; the gate being used is a"
echo "                                  constant from some other model's confidence scale."
echo "   gate_source=\"env-override\"    → ML_GATE_THRESHOLD is set and is beating the"
echo "                                  measured gate. Unset it unless that is deliberate."
