#!/usr/bin/env bash
# Full pipeline from your Mac (gcloud auth required):
#   1) dump DB from always-on
#   2) create/start train VM
#   3) restore + train + eval
#   4) download checkpoint
#   5) promote to always-on
#   6) optional: delete train VM (--keep-vm to skip)
#
# Usage:
#   ./scripts/gcp_train_pipeline.sh
#   ./scripts/gcp_train_pipeline.sh --epochs 40 --seq-len 64
#   ./scripts/gcp_train_pipeline.sh --keep-vm
#   TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT ./scripts/gcp_train_pipeline.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/gcp_common.sh"
require_gcloud

EPOCHS="$TRAIN_EPOCHS"
SEQ_LEN="$TRAIN_SEQ_LEN"
KEEP_VM=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --epochs) EPOCHS="$2"; shift 2 ;;
    --seq-len) SEQ_LEN="$2"; shift 2 ;;
    --keep-vm) KEEP_VM=1; shift ;;
    --pairs) export TRAIN_PAIRS="$2"; shift 2 ;;
    -h|--help)
      sed -n '1,20p' "$0"
      exit 0
      ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

export TRAIN_EPOCHS="$EPOCHS"
export TRAIN_SEQ_LEN="$SEQ_LEN"
export EXPORT_DIR="${EXPORT_DIR:-$HOME/fluxtrader-train-export}"

echo "============================================"
echo " FluxTrader ephemeral CPU train pipeline"
echo "============================================"
echo_cfg
echo "EPOCHS=$EPOCHS SEQ_LEN=$SEQ_LEN KEEP_VM=$KEEP_VM"
echo "EXPORT_DIR=$EXPORT_DIR"
echo "============================================"

"$ROOT/scripts/gcp_dump_always_on.sh"
"$ROOT/scripts/gcp_create_train_vm.sh"
"$ROOT/scripts/gcp_run_train.sh" "$EPOCHS" "$SEQ_LEN"
"$ROOT/scripts/gcp_promote_checkpoint.sh" "$EXPORT_DIR/m2_multi.pt"

if [[ "$KEEP_VM" -eq 0 ]]; then
  "$ROOT/scripts/gcp_delete_train_vm.sh"
else
  echo "==> Keeping train VM ($GCP_TRAIN_INSTANCE). Delete later with ./scripts/gcp_delete_train_vm.sh"
fi

echo ""
echo "All done. Checkpoint on always-on model volume."
echo "If inference is up: docker compose restart ml_inference (on always-on)"
