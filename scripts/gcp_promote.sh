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
#   ML_GATE_THRESHOLD=0.6311 ./scripts/gcp_promote.sh --checkpoint <key>
#       Serve at an explicitly measured gate. Needed for any checkpoint written
#       before C13 (commit 5b8a5e2), or measured with `eval_m2.py --eval-only`,
#       since neither carries a served_gate in the checkpoint's meta. The value is
#       persisted into the VM's .env and the promote FAILS if /health does not come
#       back serving exactly it.
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
# --- gate override: must reach the VM, and must PERSIST there ---------------------
# `ML_GATE_THRESHOLD=0.6311 ./scripts/gcp_promote.sh …` used to be a silent no-op.
# The value lived in the Mac's shell; the remote `docker compose` interpolates
# ${ML_GATE_THRESHOLD} from the VM's OWN environment and .env file, which this
# script never touched. On 2026-08-24 that shipped R0's seed-2 checkpoint at the
# VM's stale .env value of 0.55 — below even the 0.58 config fallback the plan
# warns loses money in 3 of 3 seeds.
#
# The fix writes the value into the VM's .env rather than exporting it for one
# command, because .env is what compose actually reads AND what survives the next
# unrelated `docker compose up` on that host. Both `app` (Elixir signal gate) and
# `ml_inference` (serve.py gate) read the same key, so both are recreated when it
# changes — a half-applied gate is two components disagreeing about the operating
# point.
GATE_OVERRIDE="${ML_GATE_THRESHOLD:-}"
if [[ -n "$GATE_OVERRIDE" ]]; then
  echo "==> gate override requested: ML_GATE_THRESHOLD=$GATE_OVERRIDE (will be persisted to the VM's .env)"
fi

echo "==> install checkpoint + serve code on $GCP_ALWAYS_ON (ref=$PROMOTE_REF)"
_PROMOTE_LOG="$(mktemp -t fluxpromote)"
set +e
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

  GATE='$GATE_OVERRIDE'
  GATE_CHANGED=0
  if [[ -n \"\$GATE\" ]]; then
    touch .env
    PREV=\$(sed -n 's/^ML_GATE_THRESHOLD=//p' .env | tail -1)
    if [[ \"\$PREV\" != \"\$GATE\" ]]; then GATE_CHANGED=1; fi
    if grep -q '^ML_GATE_THRESHOLD=' .env; then
      sed -i \"s|^ML_GATE_THRESHOLD=.*|ML_GATE_THRESHOLD=\$GATE|\" .env
    else
      printf 'ML_GATE_THRESHOLD=%s\n' \"\$GATE\" >> .env
    fi
    echo \"    .env ML_GATE_THRESHOLD: \${PREV:-<unset>} -> \$GATE\"
  fi

  docker compose up -d --force-recreate ml_inference
  echo ml_inference recreated
  # The Elixir app gates independently (Predict.gate_threshold/0 reads the same
  # env var), so a changed gate that only reaches ml_inference leaves the two
  # halves on different operating points.
  if [[ \"\$GATE_CHANGED\" == 1 ]]; then
    echo '    gate changed -> recreating app so its signal gate matches'
    docker compose up -d app
  fi

  # serve.py binds the port BEFORE it finishes torch.load()ing the checkpoint, so
  # an early request is answered with a TCP reset (curl exit 56) — which curl's
  # --retry does NOT classify as transient, so the old 'sleep 4 + --retry' aborted
  # the promote before it ever printed a /health line. Poll instead.
  HEALTH=''
  for _ in \$(seq 1 30); do
    HEALTH=\$(curl -sS -m 3 http://127.0.0.1:8001/health 2>/dev/null || true)
    [[ -n \"\$HEALTH\" ]] && break
    sleep 2
  done
  if [[ -z \"\$HEALTH\" ]]; then
    echo 'ERROR: /health never answered within 60s. Check: docker compose logs ml_inference'
    exit 1
  fi
  echo \"HEALTH \$HEALTH\"
" 2>&1 | tee "$_PROMOTE_LOG"
_RC=${PIPESTATUS[0]}
set -e
if [[ "$_RC" -ne 0 ]]; then
  echo ""
  echo "ERROR: remote promote step failed (rc=$_RC). Nothing above is verified."
  exit "$_RC"
fi

# --- verify the served operating point, don't just print it ----------------------
HEALTH_JSON="$(sed -n 's/^HEALTH //p' "$_PROMOTE_LOG" | tail -1)"
SERVED_GATE="$(printf '%s' "$HEALTH_JSON" | sed -n 's/.*"gate_threshold"[: ]*\([0-9.]*\).*/\1/p')"
GATE_SOURCE="$(printf '%s' "$HEALTH_JSON" | sed -n 's/.*"gate_source"[: ]*"\([^"]*\)".*/\1/p')"
rm -f "$_PROMOTE_LOG"

echo ""
if ! printf '%s' "$HEALTH_JSON" | grep -q '"ok"[: ]*true'; then
  echo "🔴 FAILED — /health reports ok=false. The model did not load:"
  echo "   $HEALTH_JSON"
  exit 1
fi

if [[ -n "$GATE_OVERRIDE" ]]; then
  if [[ -z "$SERVED_GATE" ]]; then
    echo "🔴 FAILED — could not read gate_threshold from /health: $HEALTH_JSON"
    exit 1
  fi
  if ! awk -v a="$SERVED_GATE" -v b="$GATE_OVERRIDE" 'BEGIN{exit !(a==b || (a-b<1e-9 && b-a<1e-9))}'; then
    echo "🔴 FAILED — you asked for gate $GATE_OVERRIDE but the service is serving $SERVED_GATE."
    echo "   Check the VM's .env and environment for a competing ML_GATE_THRESHOLD."
    exit 1
  fi
  echo "✅ served gate = $SERVED_GATE (matches the requested override)"
else
  echo "   served gate = ${SERVED_GATE:-?} (no override requested; from checkpoint or config)"
fi

# gate_source only exists in serve.py from commit 5b8a5e2 (the C13 wave) onward.
# Checkpoints trained BEFORE that commit pin serve code that predates it, so the
# field is absent — that is expected, not a fault, but it means the operator has
# to verify the number rather than the label.
if [[ -z "$GATE_SOURCE" ]]; then
  echo "   NOTE: this serve commit ($PROMOTE_REF) predates C13, so /health carries no"
  echo "         gate_source field. The gate above is authoritative; verify the NUMBER."
else
  echo "   gate_source = $GATE_SOURCE"
fi


echo ""
echo "OK — promoted $CKPT_KEY."
echo "  Checkpoint installed on always-on model volume ($MODEL_VOLUME_NAME)."
echo "  Serve code @ $PROMOTE_REF (git)."
echo "  Operating point VERIFIED against /health above — this script now exits non-zero"
echo "  if the service is not serving the gate you asked for, so a clean exit IS the"
echo "  green light. (It used to only print /health, and a startup race meant it usually"
echo "  did not even manage that.)"
echo ""
echo "gate_source, when the serve commit is new enough to report it:"
echo "   \"checkpoint\"      → healthy: served at the operating point it was measured at"
echo "                       (gate_target_coverage says which)."
echo "   \"config-fallback\" → this checkpoint has no served_gate in its meta. Re-run"
echo "                       eval_m2.py on it, or pass the measured gate explicitly as"
echo "                       ML_GATE_THRESHOLD; the constant otherwise in use belongs to"
echo "                       some other model's confidence scale."
echo "   \"env-override\"    → ML_GATE_THRESHOLD is set and beats the measured gate."
echo "                       Correct for a pre-C13 checkpoint whose gate lives only in a"
echo "                       log (§1.5); wrong if you did not mean it."
