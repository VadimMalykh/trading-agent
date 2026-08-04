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

# --- helper: block until a SPECIFIC run id reaches a terminal state ------------
# Polls status/<run_id>.json (NOT latest.json) so a stale RUNNING marker from a
# previous, unrelated run can never be mistaken for this arm's result.
wait_for_done() {
  local label="$1" run_id="$2"
  if [[ -z "$run_id" ]]; then
    echo "    WARN: no run_id captured for '$label' — cannot poll; skipping wait."
    return 1
  fi
  echo "    waiting for '$label' (run=$run_id) — polling status/$run_id.json every 60s ..."
  local waited=0
  while true; do
    sleep 60; waited=$((waited + 60))
    local js state
    js="$(gcloud storage cat "$GCS_BUCKET/status/$run_id.json" 2>/dev/null || true)"
    state="$(printf '%s' "$js" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')"
    case "$state" in
      DONE)   echo "    → $label DONE"; return 0 ;;
      FAILED) echo "    → $label FAILED (see ./scripts/gcp_status.sh $run_id)"; return 1 ;;
      *)      printf '.' ;;
    esac
    # Safety valve: if no status object appears for a long time, the launch
    # likely stalled before writing its RUNNING marker (e.g. dump upload wedged).
    if [[ -z "$state" && "$waited" -ge 900 ]]; then
      echo ""
      echo "    WARN: no status marker for run=$run_id after $((waited/60))min."
      echo "          Launch may have stalled (dump upload / VM). Check: ./scripts/gcp_status.sh $run_id"
      return 1
    fi
  done
}

# --- helper: pull a specific run's log locally under a labeled name -------------
collect_log() {
  local label="$1" run_id="$2"
  if [[ -z "$run_id" ]]; then
    echo "    WARN: no run_id for '$label' — cannot fetch log."
    return 0
  fi
  if gcloud storage cp "$GCS_BUCKET/logs/$run_id.log" "$OUT_DIR/${label}_${run_id}.log" 2>/dev/null; then
    echo "    saved $OUT_DIR/${label}_${run_id}.log"
  else
    echo "    WARN: log for run=$run_id not in bucket yet."
  fi
}

run_arm() {
  local label="$1"; shift
  echo ""
  echo "=== ARM: $label ==="
  # Capture gcp_train.sh output so we can extract THIS run's id (printed as
  # "run_id=<id>"), then tee it to the terminal for live visibility.
  local launch_out run_id rc
  launch_out="$OUT_DIR/${label}_launch.out"
  # shellcheck disable=SC2086
  ./scripts/gcp_train.sh $GPU_FLAG "$@" "$EPOCHS" "$SEQ_LEN" 2>&1 | tee "$launch_out"
  rc=${PIPESTATUS[0]}
  if [[ "$rc" -ne 0 ]]; then
    echo "    ERROR: launch for '$label' exited rc=$rc — skipping this arm."
    return 1
  fi
  run_id="$(sed -n 's/.*run_id=\([0-9TZ]*\).*/\1/p' "$launch_out" | head -1)"
  if [[ -z "$run_id" ]]; then
    echo "    WARN: could not parse run_id from launch output ($launch_out)."
    return 1
  fi
  echo "    launched '$label' as run=$run_id"
  wait_for_done "$label" "$run_id" || true
  collect_log "$label" "$run_id"
}

run_arm "quant_off"      --quantile-head 0
run_arm "quant_w0.2"     --quantile-head 1 --quantile-weight 0.2
run_arm "quant_w0.5"     --quantile-head 1 --quantile-weight 0.5

echo ""
echo "==> quant A/B complete. Logs in $OUT_DIR"
echo "    Compare primary-30m fixed-cov wilson_lb + quantile band coverage across arms:"
echo "    grep -nE 'PRIMARY|cov0.05|Quantile calibration|Book-era|Walk-forward' $OUT_DIR/*.log"
