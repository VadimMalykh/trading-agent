#!/usr/bin/env bash
# Quantile-head A/B: launch 3 comparable training runs and collect their logs.
#
# Arms (all same ref / epochs / seq-len so results are comparable):
#   1. quant OFF                 (baseline)
#   2. quant ON,  weight 0.2     (current main default)
#   3. quant ON,  weight 0.5     (old setting; stole encoder capacity in prior runs)
#
# The train VM is a SINGLE self-deleting instance, so the arms run SEQUENTIALLY:
# this script launches an arm, polls the status bucket until DONE/FAILED, copies
# that run's log locally under a labeled name, then launches the next arm.
#
# NOTE ON DATA SNAPSHOT: each gcp_train.sh launch pulls a FRESH DB dump, so the
# three arms will not see a byte-identical dataset unless the DB is quiesced.
# Differences are small over a few hours, and the comparison metrics (fixed-cov
# wilson_lb + quantile band coverage) are coverage-normalized, so back-to-back
# runs are adequate. For a byte-frozen snapshot, pin one dump: run arm 1, then set
# FREEZE_DUMP=1 to reuse gs://.../dumps/latest.sql.gz for arms 2-3 (see below).
#
#   ./scripts/quant_ab.sh [--gpu] [epochs] [seq_len]
#   ./scripts/quant_ab.sh --gpu 60 128
#
# Watch a run in progress in another terminal:  ./scripts/gcp_status.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
source "$ROOT/scripts/gcp_common.sh"

# --- args: pass --gpu through; first two bare positionals = epochs seq_len ------
GPU_FLAG=""
POS=()
for a in "$@"; do
  case "$a" in
    --gpu) GPU_FLAG="--gpu" ;;
    --*)   echo "ERROR: unknown flag '$a'"; exit 1 ;;
    *)     POS+=("$a") ;;
  esac
done
EPOCHS="${POS[0]:-${TRAIN_EPOCHS:-60}}"
SEQ_LEN="${POS[1]:-${TRAIN_SEQ_LEN:-128}}"

OUT_DIR="$ROOT/logs/quant_ab_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"
echo "==> quant A/B: gpu='${GPU_FLAG:-no}' epochs=$EPOCHS seq_len=$SEQ_LEN ref=$GIT_REF"
echo "    logs → $OUT_DIR"

# --- helper: block until the latest run reaches a terminal state ---------------
wait_for_done() {
  local label="$1"
  echo "    waiting for '$label' to finish (polling status bucket every 60s) ..."
  while true; do
    sleep 60
    local js state
    js="$(gcloud storage cat "$GCS_BUCKET/status/latest.json" 2>/dev/null || true)"
    state="$(printf '%s' "$js" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')"
    case "$state" in
      DONE)   echo "    → $label DONE"; return 0 ;;
      FAILED) echo "    → $label FAILED (see ./scripts/gcp_status.sh)"; return 1 ;;
      *)      printf '.' ;;
    esac
  done
}

# --- helper: pull the finished run's log locally under a labeled name -----------
collect_log() {
  local label="$1"
  local run_id
  run_id="$(gcloud storage cat "$GCS_BUCKET/status/latest.json" 2>/dev/null \
    | sed -n 's/.*"run":"\([^"]*\)".*/\1/p')"
  if [[ -n "$run_id" ]]; then
    gcloud storage cp "$GCS_BUCKET/logs/$run_id.log" "$OUT_DIR/${label}_${run_id}.log" \
      && echo "    saved $OUT_DIR/${label}_${run_id}.log"
  else
    echo "    WARN: could not resolve run_id for '$label'"
  fi
}

run_arm() {
  local label="$1"; shift
  echo ""
  echo "=== ARM: $label ==="
  # shellcheck disable=SC2086
  ./scripts/gcp_train.sh $GPU_FLAG "$@" "$EPOCHS" "$SEQ_LEN"
  wait_for_done "$label" || true
  collect_log "$label"
}

run_arm "quant_off"      --quantile-head 0
run_arm "quant_w0.2"     --quantile-head 1 --quantile-weight 0.2
run_arm "quant_w0.5"     --quantile-head 1 --quantile-weight 0.5

echo ""
echo "==> quant A/B complete. Logs in $OUT_DIR"
echo "    Compare primary-30m fixed-cov wilson_lb + quantile band coverage across arms:"
echo "    grep -nE 'PRIMARY|cov0.05|Quantile calibration|Book-era|Walk-forward' $OUT_DIR/*.log"
