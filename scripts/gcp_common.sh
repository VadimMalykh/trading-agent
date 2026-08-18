#!/usr/bin/env bash
# Shared helpers — sourced by gcp_1..gcp_5. Do not run directly.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/google-cloud-sdk/bin:$HOME/Downloads/google-cloud-sdk/bin:$PATH"

# Sourcing scripts/gcp_env must NOT clobber an inline override the user passed on
# the launcher (e.g.  TRAIN_PRIMARY=60 ./scripts/gcp_train.sh …). gcp_env now uses
# ':=' default-assignment so inline vars win, but guard against a stray `export
# VAR=…` slipping back in: snapshot the tunable knobs before sourcing and restore
# any that were already set. (A plain `export TRAIN_PRIMARY=30` in gcp_env silently
# voided R3/R4.)
_FLUX_OVERRIDE_KEYS="TRAIN_EPOCHS TRAIN_SEQ_LEN TRAIN_DEVICE TRAIN_HORIZONS \
TRAIN_PRIMARY TRAIN_PAIRS TRAIN_QUANTILE_HEAD TRAIN_QUANTILE_LEVELS \
TRAIN_QUANTILE_LOSS_WEIGHT GIT_REF GIT_REMOTE GCS_BUCKET KEEP_VM \
GCP_PROJECT GCP_ZONE GCP_TRAIN_ZONE"
for _k in $_FLUX_OVERRIDE_KEYS; do
  if [[ -n "${!_k:-}" ]]; then
    eval "_FLUX_SAVED_${_k}=\${${_k}}"
    eval "_FLUX_HAD_${_k}=1"
  fi
done

if [[ -f "$ROOT/scripts/gcp_env" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/scripts/gcp_env"
else
  echo "NOTE: optional config at scripts/gcp_env (copy from gcp_env.example)"
fi

# Restore inline overrides that gcp_env may have clobbered via `export`.
for _k in $_FLUX_OVERRIDE_KEYS; do
  if [[ "$(eval "echo \${_FLUX_HAD_${_k}:-}")" == "1" ]]; then
    eval "${_k}=\${_FLUX_SAVED_${_k}}"
  fi
done
unset _k _FLUX_OVERRIDE_KEYS

: "${GCP_PROJECT:=fluxtrader}"
: "${GCP_ZONE:=me-central1-b}"
: "${GCP_REGION:=${GCP_ZONE%-*}}"          # me-central1-b -> me-central1
: "${GCP_ALWAYS_ON:=fluxtrader-1}"
: "${GCP_TRAIN_INSTANCE:=fluxtrader-train}"
# Separate throwaway VM for the microstructure audit (scripts/gcp_audit.sh).
# MUST differ from GCP_TRAIN_INSTANCE so audit + training can run in parallel
# without sharing a VM, Postgres, tmux session, or status marker.
: "${GCP_AUDIT_INSTANCE:=fluxtrader-audit}"
: "${GCP_TRAIN_MACHINE:=e2-standard-4}"
# GPU machine type and accelerator (used when gcp_train.sh --gpu is passed).
# n1-standard-4 + T4 is the best cost/speed ratio for LSTM training:
#   ~$0.19/hr (n1-standard-4) + ~$0.35/hr (T4) = ~$0.54/hr total
#   vs e2-standard-4 at ~$0.13/hr (CPU). GPU is ~10-20x faster for the LSTM loop.
# Alternatives: n1-standard-8+T4 (~$0.73/hr), g2-standard-4+L4 (~$0.70/hr, if available).
: "${GCP_TRAIN_MACHINE_GPU:=n1-standard-4}"
: "${GCP_TRAIN_ACCELERATOR:=type=nvidia-tesla-t4,count=1}"
# GPU zone — me-central1-b has no GPUs. Override to a zone that has T4/L4.
# Cross-region GCS transfer for the dump (~1-2GB) costs ~$0.08/GB = pennies.
: "${GCP_TRAIN_ZONE:=${GCP_ZONE}}"
: "${REMOTE_REPO_NAME:=trading_agent}"
: "${TRAIN_EPOCHS:=60}"
: "${TRAIN_SEQ_LEN:=128}"
: "${TRAIN_DEVICE:=cpu}"
# M2 defaults (Phase 1+2): 5/30/60 heads, primary 30m, majors preferred
: "${TRAIN_HORIZONS:=5,30,60}"
: "${TRAIN_PRIMARY:=30}"
# Auxiliary quantile head (p10/p50/p90 forward-return, pinball loss). Off by
# default; set TRAIN_QUANTILE_HEAD=1 to enable (Run B). Levels/weight optional.
: "${TRAIN_QUANTILE_HEAD:=0}"
: "${TRAIN_QUANTILE_LEVELS:=0.1,0.5,0.9}"
: "${TRAIN_QUANTILE_LOSS_WEIGHT:=0.5}"
# 6-pair set: 3 majors + DOGE/WLD/HYPE. Data audit (2026-07-24) confirmed all six
# have full ~180d 1m candles. Microstructure (book/trades/OI) spans only ~days for
# every pair (collector started recently) → zero-filled for most of history; the
# model tolerates missing microstructure. See docs/NEXT_TRAINING_PLAN.md.
: "${TRAIN_PAIRS:=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT}"

# --- V2 pipeline: artifacts via GCS bucket, code via git ---------------------
# Single-region bucket in the SAME region as the VMs (else you pay egress).
: "${GCS_BUCKET:=gs://fluxtrader-train-artifacts}"
# Reproducible code source. HTTPS so the VM can clone without your SSH key.
# For a PRIVATE repo, use: https://<PAT>@github.com/VadimMalykh/trading-agent.git
: "${GIT_REMOTE:=https://github.com/VadimMalykh/trading-agent.git}"
: "${GIT_REF:=main}"                       # branch or commit SHA to train/serve
# Keep the train VM alive after the job (1 = never auto delete/stop). Debug only.
: "${KEEP_VM:=0}"

# Local folder for OPTIONAL backup copies (--local-copy). Not on the hot path.
: "${EXPORT_DIR:=$HOME/fluxtrader-train-export}"

# App tables dumped for training / settings (not Timescale internals)
: "${DUMP_TABLES:=candles orderbook_snapshots market_trades funding_rates open_interest liquidations app_settings positions trades schema_migrations}"

require_gcloud() {
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "ERROR: gcloud not found. brew install --cask google-cloud-sdk && gcloud auth login"
    exit 1
  fi
  gcloud config set project "$GCP_PROJECT" >/dev/null
}

gssh() {
  local zone="${3:-$GCP_ZONE}"
  gcloud compute ssh "$1" --project="$GCP_PROJECT" --zone="$zone" --command="$2"
}

gscp_to() {
  local zone="${4:-$GCP_ZONE}"
  gcloud compute scp --project="$GCP_PROJECT" --zone="$zone" --recurse "$2" "$1:$3"
}

gscp_from() {
  local zone="${4:-$GCP_ZONE}"
  gcloud compute scp --project="$GCP_PROJECT" --zone="$zone" --recurse "$1:$2" "$3"
}

# Compose declares model_weights as external with this exact name
MODEL_VOLUME_NAME="${MODEL_VOLUME_NAME:-trading_agent_model_weights}"

echo_cfg() {
  echo "project=$GCP_PROJECT  zone=$GCP_ZONE  region=$GCP_REGION"
  echo "always-on=$GCP_ALWAYS_ON  train-vm=$GCP_TRAIN_INSTANCE ($GCP_TRAIN_MACHINE)  audit-vm=$GCP_AUDIT_INSTANCE"
  echo "bucket=$GCS_BUCKET"
  echo "git=$GIT_REMOTE @ $GIT_REF"
  echo "train: epochs=$TRAIN_EPOCHS seq=$TRAIN_SEQ_LEN device=$TRAIN_DEVICE"
  echo "       horizons=$TRAIN_HORIZONS primary=${TRAIN_PRIMARY}m pairs=$TRAIN_PAIRS"
  if [[ "${_GPU_MODE:-0}" == "1" ]]; then
    echo "       GPU: accelerator=$GCP_TRAIN_ACCELERATOR machine=$GCP_TRAIN_MACHINE_GPU"
  fi
}

# --- async shared dump ---------------------------------------------------------
# Every gcp_* script restores the same app tables into its throwaway Postgres, so
# there is ONE shared dump object (dumps/latest.sql.gz). It is refreshed on the
# always-on VM in a detached tmux session 'fluxtdump' and cached on the VM as
# /var/tmp/fluxtrader_dump_cache.sql.gz; a fresh-enough cache is reused, so
# back-to-back runs skip the dump entirely. The launcher returns in ~2s (dump is
# NOT in its critical path); each script's remote job waits for the artifact via
# an inline poll loop (see the "wait for dump" blocks in gcp_*.sh).
#
# Knobs (launcher env):
#   DUMP_MAX_AGE_MIN  cache reuse window (default 30; dump regen below this age)
#   DUMP_POLL_TRIES   remote-job wait iterations (default 240)
#   DUMP_POLL_SLEEP   remote-job poll interval in seconds (default 10)
#                     → default budget = 240 × 10s = 40 min, which covers the
#                       e2-small cold-dump time once VM provisioning overlaps it.
# NOTE: on a cache miss the OLD dumps/latest.sql.gz is deleted before the async
# job starts, so the remote poll can't mistake a stale object for a fresh dump.
# Run gcp_* scripts sequentially — a concurrent in-flight download would break.
: "${DUMP_MAX_AGE_MIN:=30}"
: "${DUMP_POLL_TRIES:=240}"
: "${DUMP_POLL_SLEEP:=10}"

ensure_dump() {
  # Call from the launcher after VM provisioning (gcp_train/audit/walkforward/
  # gbt/ablate). Uses _GCP_ZONE_ORIGINAL so a GPU-zone override on the train
  # script can't point the SSH at the wrong zone for the always-on VM.
  local zone="${_GCP_ZONE_ORIGINAL:-$GCP_ZONE}"
  echo "==> ensure shared dump from $GCP_ALWAYS_ON (cache ≤ ${DUMP_MAX_AGE_MIN}m) → $GCS_BUCKET/dumps/latest.sql.gz"
  gssh "$GCP_ALWAYS_ON" "set -e
    cd \$HOME/$REMOTE_REPO_NAME
    CACHE=/var/tmp/fluxtrader_dump_cache.sql.gz
    AGE=999999
    if [[ -f \$CACHE ]]; then AGE=\$(( \$(date +%s) - \$(stat -c %Y \$CACHE) )); fi
    if [[ \$AGE -lt $((DUMP_MAX_AGE_MIN * 60)) ]]; then
      echo \"    cache hit (\$(( AGE / 60 ))m old) → reuse\"
      if ! gcloud storage ls $GCS_BUCKET/dumps/latest.sql.gz >/dev/null 2>&1; then
        echo '    uploading cached dump to bucket'
        gcloud storage cp \$CACHE $GCS_BUCKET/dumps/latest.sql.gz
      fi
    else
      echo '    cache miss → async dump in tmux fluxtdump on $GCP_ALWAYS_ON'
      echo '    (launcher returns now; remote job polls for dumps/latest.sql.gz)'
      gcloud storage rm $GCS_BUCKET/dumps/latest.sql.gz 2>/dev/null || true
      cat > /var/tmp/fluxtdump.sh <<'FLUXDUMP'
#!/bin/bash
set -euo pipefail
cd \$HOME/$REMOTE_REPO_NAME
CACHE=/var/tmp/fluxtrader_dump_cache.sql.gz
echo \"=== async dump start \$(date -u) ===\"
docker compose exec -T postgres pg_isready -U fluxtrader
TFLAGS=''
for t in $DUMP_TABLES; do TFLAGS=\"\$TFLAGS -t \$t\"; done
docker compose exec -T postgres bash -c \"pg_dump -U fluxtrader -d fluxtrader --format=plain --no-owner --no-acl \$TFLAGS\" | gzip -1 > \$CACHE
ls -lh \$CACHE
gcloud storage cp \$CACHE $GCS_BUCKET/dumps/latest.sql.gz.new
gcloud storage mv $GCS_BUCKET/dumps/latest.sql.gz.new $GCS_BUCKET/dumps/latest.sql.gz
echo \"=== async dump done \$(date -u) ===\"
FLUXDUMP
      chmod +x /var/tmp/fluxtdump.sh
      tmux kill-session -t fluxtdump 2>/dev/null || true
      tmux new-session -d -s fluxtdump 'bash /var/tmp/fluxtdump.sh'
    fi
  " "$zone"
}
