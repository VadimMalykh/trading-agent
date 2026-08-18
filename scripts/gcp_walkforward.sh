#!/usr/bin/env bash
# Walk-forward robustness check for the 30m book-ON vs book-OFF edge — on a
# THROWAWAY VM, one command, self-cleaning. Companion to gcp_ablate.sh.
#
# WHY: gcp_ablate.sh found a large 30m top-5% dir_acc gap (book-ON lb=0.691 vs
# book-OFF lb=0.494) but on a SINGLE ~2.7d trailing val window (n≈575). Before
# investing in microstructure collection we confirm the gap holds across several
# DIFFERENT held-out periods. This runs the SAME dense-window A/B, primary 30m,
# over K rolling-origin folds (train strictly before each val window — no
# leakage) and prints a per-fold LB table + the min gap across folds.
#
# It mirrors gcp_ablate.sh exactly (dump -> temp VM -> restore -> run -> compare
# -> self-clean), differing only in: 30m only, and it sweeps --val-offset.
#
#   ./scripts/gcp_walkforward.sh                 # 40 epochs, seq 128, 5 folds
#   ./scripts/gcp_walkforward.sh 40 128 "0.0 0.2 0.4"   # epochs seq "offsets"
#   VAL_FRAC=0.2 ./scripts/gcp_walkforward.sh
#   KEEP_VM=1 ./scripts/gcp_walkforward.sh
#
# Anti-overfit knobs for the tiny dense-book regime (the model overfits within
# ~2-5 epochs; see docs/NEXT_TRAINING_PLAN.md "Walk-forward re-run"). These pass
# straight through to train_m2 via the ml_trainer container env:
#   WF_DROPOUT=0.4 WF_WEIGHT_DECAY=1e-3 WF_HIDDEN=48 ./scripts/gcp_walkforward.sh
# Restrict to the 4 longest book-history pairs (drop ZEC/PEPE short coverage):
#   WF_LONG_PAIRS_ONLY=1 ./scripts/gcp_walkforward.sh
#
#   status:  ./scripts/gcp_walkforward.sh --status
#   results: ./scripts/gcp_walkforward.sh --fetch [run_id]
#   list:    ./scripts/gcp_walkforward.sh --list
#
# Bucket layout (separate prefix from ablations):
#   gs://<bucket>/walkforward/<RUN_ID>.on.f<off>.log   book-ON arm, fold <off>
#   gs://<bucket>/walkforward/<RUN_ID>.off.f<off>.log   book-OFF arm, fold <off>
#   gs://<bucket>/walkforward/<RUN_ID>.compare.txt      per-fold LB table
#   gs://<bucket>/walkforward/latest.*                  convenience copies
#   gs://<bucket>/status/walkforward_latest.json        status marker
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud

: "${GCP_WF_INSTANCE:=fluxtrader-walkforward}"
WF_PREFIX="$GCS_BUCKET/walkforward"

if [[ "${1:-}" == "--list" ]]; then
  echo "==> walk-forward runs ($WF_PREFIX/<run_id>.compare.txt, oldest -> newest):"
  gcloud storage ls "$WF_PREFIX/" 2>/dev/null \
    | sed -n 's#.*/walkforward/\(.*\)\.compare\.txt$#\1#p' | sort || echo "(none yet)"
  exit 0
fi
if [[ "${1:-}" == "--status" ]]; then
  echo "==> bucket: $GCS_BUCKET"
  MARKER="$(gcloud storage cat "$GCS_BUCKET/status/walkforward_latest.json" 2>/dev/null || true)"
  [[ -z "$MARKER" ]] && echo "no walk-forward marker yet" || echo "last marker: $MARKER"
  VM_STATE="$(gcloud compute instances describe "$GCP_WF_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)' 2>/dev/null || true)"
  if [[ -n "$VM_STATE" ]]; then
    echo "wf VM $GCP_WF_INSTANCE: $VM_STATE (zone=$GCP_ZONE)"
    [[ "$VM_STATE" == "RUNNING" ]] && \
      echo "live: gcloud compute ssh $GCP_WF_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tmux attach -t fluxwf"
  else
    echo "wf VM $GCP_WF_INSTANCE: gone (self-deleted or never created)"
  fi
  echo ""
  echo "full logs + compare:  ./scripts/gcp_walkforward.sh --fetch"
  exit 0
fi
if [[ "${1:-}" == "--fetch" ]]; then
  RUN_ID="${2:-latest}"
  echo "==> walk-forward comparison ($WF_PREFIX/$RUN_ID.compare.txt):"
  echo "--------------------------------------------------------------------------"
  gcloud storage cat "$WF_PREFIX/$RUN_ID.compare.txt" 2>/dev/null \
    || { echo "(no compare yet — run in progress or wrong id; try --list)"; exit 1; }
  exit 0
fi

# --- args: epochs seq_len "offsets"; val_frac + pairs via env --------------------
EPOCHS="${1:-40}"
SEQ_LEN="${2:-128}"
# More, finer folds by default (was "0.0 0.2 0.4"): one bad ~3d window no longer
# dominates the min-gap verdict. Step defaults to VAL_FRAC=0.2 → overlapping folds
# here, which is fine for a robustness read (each still trains strictly before its
# own val window). Requires ≥~30d dense book so each fold's val slice isn't tiny.
OFFSETS="${3:-0.0 0.1 0.2 0.3 0.4 0.5}"
VAL_FRAC="${VAL_FRAC:-0.2}"
PAIRS_ARG="${TRAIN_PAIRS:-}"
HORIZONS="${TRAIN_HORIZONS:-5,30,60}"
PRIMARY=30                       # this check is 30m-only (the arm with a real edge)

# --- anti-overfit / regularization knobs for the dense-book regime --------------
# Defaults preserve prior behavior (dropout 0.2, wd 1e-4, hidden 64). Override to
# fight the ~2-5 epoch overfit seen in wf-20260804T144400Z.
WF_DROPOUT="${WF_DROPOUT:-0.2}"
WF_WEIGHT_DECAY="${WF_WEIGHT_DECAY:-1e-4}"
WF_HIDDEN="${WF_HIDDEN:-64}"
# WF_LONG_PAIRS_ONLY=1 restricts to the 4 pairs with the longest book history
# (BTC/ETH/SOL/DOGE), dropping ZEC/PEPE/HYPE/WLD whose book coverage is SHORTER
# than the dense window and therefore injects ragged has_book into the book-ON arm
# only — which is precisely the comparison this script exists to make.
#
# BUG (found 2026-08-18, after it silently voided run wf-20260817T030350Z): this
# used to be gated on `-z "$PAIRS_ARG"`, but PAIRS_ARG comes from TRAIN_PAIRS,
# which gcp_env / gcp_common.sh ALWAYS default to the 8-pair set. So the guard was
# never satisfied and the flag was dead code — the run silently used 8 pairs while
# the launch command said "long pairs only". An explicit opt-in flag must beat a
# defaulted variable, so it is now unconditional and echoes what it did.
if [[ "${WF_LONG_PAIRS_ONLY:-0}" == "1" ]]; then
  if [[ -n "$PAIRS_ARG" && "$PAIRS_ARG" != "BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT" ]]; then
    echo "==> WF_LONG_PAIRS_ONLY=1 overrides TRAIN_PAIRS='$PAIRS_ARG'"
  fi
  PAIRS_ARG="BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT"
fi

echo_cfg

RUN_ID="wf-$(date -u +%Y%m%dT%H%M%SZ)"
PAIRS_FLAG=""
if [[ -n "$PAIRS_ARG" ]]; then PAIRS_FLAG="--pairs ${PAIRS_ARG}"; fi

echo ""
echo "==> run_id=$RUN_ID  epochs=$EPOCHS seq=$SEQ_LEN primary=30m val_frac=$VAL_FRAC"
echo "    folds (val_offset): $OFFSETS   pairs=${PAIRS_ARG:-DB-whitelist}  device=cpu"
echo "    arms per fold: A=book-ON (--require-book)  B=book-OFF (--require-book --ablate-book)"

# --- 0. sanity: bucket reachable -------------------------------------------------
if ! gcloud storage ls "$GCS_BUCKET" >/dev/null 2>&1; then
  echo "ERROR: bucket $GCS_BUCKET not accessible. See gcp_train.sh header for setup."
  exit 1
fi

# --- 1. ensure the (CPU) temp VM exists -----------------------------------------
echo ""
echo "==> ensure temp VM $GCP_WF_INSTANCE ($GCP_TRAIN_MACHINE)"
_VM_CREATED=0
if gcloud compute instances describe "$GCP_WF_INSTANCE" \
     --project="$GCP_PROJECT" --zone="$GCP_ZONE" >/dev/null 2>&1; then
  STATUS=$(gcloud compute instances describe "$GCP_WF_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)')
  echo "    exists (status=$STATUS)"
  if [[ "$STATUS" != "RUNNING" ]]; then
    gcloud compute instances start "$GCP_WF_INSTANCE" \
      --project="$GCP_PROJECT" --zone="$GCP_ZONE"
  fi
  _VM_CREATED=1
fi

if [[ "$_VM_CREATED" == "0" ]]; then
  _STARTUP_CPU='#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git tmux
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
for u in $(ls /home 2>/dev/null); do usermod -aG docker "$u" || true; done
touch /var/tmp/fluxtrader-docker-ready
'
  echo "    creating $GCP_TRAIN_MACHINE in $GCP_ZONE ..."
  gcloud compute instances create "$GCP_WF_INSTANCE" \
    --project="$GCP_PROJECT" \
    --zone="$GCP_ZONE" \
    --machine-type="$GCP_TRAIN_MACHINE" \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=50GB \
    --boot-disk-type=pd-balanced \
    --scopes=cloud-platform \
    --tags=fluxtrader-train \
    --metadata=startup-script="$_STARTUP_CPU"
fi

echo "==> waiting for SSH ..."
for _ in $(seq 1 40); do
  if gssh "$GCP_WF_INSTANCE" "echo ok" "$GCP_ZONE" >/dev/null 2>&1; then break; fi
  sleep 5
done
echo "==> waiting for Docker (first boot 1-3 min) ..."
for i in $(seq 1 60); do
  if gssh "$GCP_WF_INSTANCE" "docker compose version" "$GCP_ZONE" >/dev/null 2>&1; then
    echo "    Docker OK"; break
  fi
  if [[ "$i" -eq 60 ]]; then echo "ERROR: Docker not ready."; exit 1; fi
  sleep 5
done
gssh "$GCP_WF_INSTANCE" \
  "sudo usermod -aG docker \$USER; sudo chmod 666 /var/run/docker.sock 2>/dev/null || true; command -v git >/dev/null || sudo apt-get install -y git; command -v tmux >/dev/null || sudo apt-get install -y tmux" \
  "$GCP_ZONE"

# --- 2. shared async dump: always-on -> bucket ---------------------------------
# ensure_dump (gcp_common.sh) reuses the always-on VM's cached dump when fresh
# (≤ DUMP_MAX_AGE_MIN) and otherwise regenerates it in a detached tmux session
# 'fluxtdump', so the launcher never blocks on pg_dump+gzip. The remote job
# polls for dumps/latest.sql.gz and snapshots it as dumps/$RUN_ID.sql.gz.
echo ""
ensure_dump

# --- 3. write remote self-cleaning walk-forward job and launch in tmux -----------
echo ""
echo "==> launching self-cleaning walk-forward job in remote tmux 'fluxwf'"
gssh "$GCP_WF_INSTANCE" "cat > \$HOME/run_flux_wf.sh <<PRELUDE
#!/bin/bash
export RUN_ID='$RUN_ID'
export GCS_BUCKET='$GCS_BUCKET'
export GIT_REMOTE='$GIT_REMOTE'
export GIT_REF='$GIT_REF'
export REMOTE_REPO_NAME='$REMOTE_REPO_NAME'
export EPOCHS='$EPOCHS'
export SEQ_LEN='$SEQ_LEN'
export HORIZONS='$HORIZONS'
export PRIMARY='$PRIMARY'
export VAL_FRAC='$VAL_FRAC'
export OFFSETS='$OFFSETS'
export PAIRS_FLAG='$PAIRS_FLAG'
export KEEP_VM='$KEEP_VM'
export MODEL_VOLUME_NAME='$MODEL_VOLUME_NAME'
export WF_DROPOUT='$WF_DROPOUT'
export WF_WEIGHT_DECAY='$WF_WEIGHT_DECAY'
export WF_HIDDEN='$WF_HIDDEN'
PRELUDE
cat >> \$HOME/run_flux_wf.sh << 'ENDSCRIPT'
set -Eeuo pipefail
LOG=\$HOME/wf.log
: > \"\$LOG\"
exec > >(tee -a \"\$LOG\") 2>&1

meta() { curl -s -H 'Metadata-Flavor: Google' \"http://metadata.google.internal/computeMetadata/v1/instance/\$1\"; }

finish() {
  local status=\"\$1\"
  echo \"=== finish: \$status \$(date -u) ===\"
  gcloud storage cp \"\$LOG\" \"\$GCS_BUCKET/walkforward/\$RUN_ID.driver.log\" || true
  printf '{\"status\":\"%s\",\"git_sha\":\"%s\",\"run\":\"%s\",\"ended\":\"%s\",\"kind\":\"walkforward\"}\n' \
    \"\$status\" \"\${GIT_SHA:-}\" \"\$RUN_ID\" \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > /tmp/status.json
  gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/\$RUN_ID.json\" || true
  gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/walkforward_latest.json\" || true

  local self zone
  self=\"\$(meta name)\"
  zone=\"\$(basename \"\$(meta zone)\")\"
  if [[ \"\${KEEP_VM:-0}\" == \"1\" ]]; then
    echo \"KEEP_VM=1 -> leaving VM \$self running\"; return 0
  fi
  if [[ \"\$status\" == \"DONE\" ]]; then
    echo \"success -> deleting self (\$self)\"
    gcloud compute instances delete \"\$self\" --zone=\"\$zone\" --quiet || true
  else
    echo \"failure -> stopping self (\$self) for debugging\"
    gcloud compute instances stop \"\$self\" --zone=\"\$zone\" --quiet || true
  fi
}
trap 'code=\$?; finish \"\$([[ \$code -eq 0 ]] && echo DONE || echo FAILED)\"' EXIT

printf '{\"status\":\"RUNNING\",\"git_sha\":\"%s\",\"run\":\"%s\",\"started\":\"%s\",\"kind\":\"walkforward\"}\n' \
  \"\${GIT_SHA:-}\" \"\$RUN_ID\" \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > /tmp/status.json
gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/\$RUN_ID.json\" || true
gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/walkforward_latest.json\" || true

echo \"=== walk-forward start \$(date -u) run=\$RUN_ID ===\"

echo \"=== checkout \$GIT_REMOTE @ \$GIT_REF ===\"
sudo rm -rf \$HOME/\$REMOTE_REPO_NAME
git clone --branch \"\$GIT_REF\" \"\$GIT_REMOTE\" \$HOME/\$REMOTE_REPO_NAME \
  || git clone \"\$GIT_REMOTE\" \$HOME/\$REMOTE_REPO_NAME
cd \$HOME/\$REMOTE_REPO_NAME
git checkout \"\$GIT_REF\"
GIT_SHA=\"\$(git rev-parse HEAD)\"
echo \"git_sha=\$GIT_SHA\"

echo \"=== wait for dump (async refresh on $GCP_ALWAYS_ON, cache ≤ ${DUMP_MAX_AGE_MIN}m) ===\"
mkdir -p \$HOME/fluxtrader-train-export
for i in \$(seq 1 ${DUMP_POLL_TRIES}); do
  if gcloud storage ls \"\$GCS_BUCKET/dumps/latest.sql.gz\" >/dev/null 2>&1; then break; fi
  if [[ \"\$i\" -eq ${DUMP_POLL_TRIES} ]]; then
    echo 'ERROR: dump not ready after polling — check async job:'
    echo \"  tmux attach -t fluxtdump on $GCP_ALWAYS_ON\"
    exit 1
  fi
  sleep ${DUMP_POLL_SLEEP}
done
gcloud storage cp \"\$GCS_BUCKET/dumps/latest.sql.gz\" \$HOME/fluxtrader-train-export/fluxtrader_wf.sql.gz
echo \"    dump ready → \$HOME/fluxtrader-train-export/fluxtrader_wf.sql.gz\"
gcloud storage cp \"\$GCS_BUCKET/dumps/latest.sql.gz\" \"\$GCS_BUCKET/dumps/\$RUN_ID.sql.gz\"

echo \"=== reset + restore postgres ===\"
docker compose down -v || true
docker compose up -d postgres
for i in \$(seq 1 60); do docker compose exec -T postgres pg_isready -U fluxtrader && break; sleep 2; done
for i in \$(seq 1 30); do docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -c 'SELECT 1' >/dev/null 2>&1 && break; sleep 2; done
sleep 2
gunzip -c \$HOME/fluxtrader-train-export/fluxtrader_wf.sql.gz \
  | docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -v ON_ERROR_STOP=0

CANDLES=\$(docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"SELECT count(*) FROM candles;\" 2>/dev/null | tr -d '[:space:]' || true)
BOOK=\$(docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"SELECT count(*) FROM orderbook_snapshots;\" 2>/dev/null | tr -d '[:space:]' || true)
echo \"candles=\$CANDLES book=\$BOOK\"
if ! [[ \"\$CANDLES\" =~ ^[0-9]+\$ ]] || [[ \"\$CANDLES\" -lt 1000 ]]; then echo \"ERROR: restore failed (candles=\$CANDLES)\"; exit 1; fi
if ! [[ \"\$BOOK\" =~ ^[0-9]+\$ ]] || [[ \"\$BOOK\" -lt 100 ]]; then echo \"ERROR: restore failed (book=\$BOOK)\"; exit 1; fi

docker volume create \"\${MODEL_VOLUME_NAME:-trading_agent_model_weights}\" >/dev/null 2>&1 || true

# ---- run one arm at one fold: \$1=tag(on|off) \$2=val_offset \$3..=extra flags ----
# Same correctness notes as gcp_ablate.sh: each run gets its OWN MODEL_DIR so the
# served /models/m2_multi.pt is never touched; the decisive metric is train_m2's
# own dense-window primary-30m 'sel@cov0.05 dir_acc=.. lb=..' line.
run_arm() {
  local tag=\"\$1\"; local off=\"\$2\"; shift 2
  local extra=\"\$*\"
  local ftag=\"\${off//./_}\"
  local armlog=\$HOME/wf_\${tag}.f\${ftag}.log
  echo \"=================================================================\"
  echo \"=== ARM \$tag  fold val_offset=\$off : train_m2 --require-book \$extra (primary=30m) ===\"
  echo \"=================================================================\"
  docker compose --profile ml run --rm \
    -e HORIZONS_MINUTES=\$HORIZONS -e PRIMARY_HORIZON=\$PRIMARY -e SEQ_LEN=\$SEQ_LEN \
    -e MODEL_DIR=/workspace/train/output/wf_\${tag}_\${ftag} \
    -e FLUX_GIT_SHA=\$GIT_SHA \
    -e DROPOUT=\$WF_DROPOUT -e HIDDEN_SIZE=\$WF_HIDDEN \
    ml_trainer python train_m2.py --device cpu --epochs \$EPOCHS --seq-len \$SEQ_LEN \
      --horizons \$HORIZONS --primary \$PRIMARY \$PAIRS_FLAG --require-book \
      --weight-decay \$WF_WEIGHT_DECAY \
      --val-frac \$VAL_FRAC --val-offset \$off \$extra \
    2>&1 | tee \"\$armlog\"

  gcloud storage cp \"\$armlog\" \"\$GCS_BUCKET/walkforward/\$RUN_ID.\$tag.f\$ftag.log\" || true
  gcloud storage cp \"\$armlog\" \"\$GCS_BUCKET/walkforward/latest.\$tag.f\$ftag.log\" || true
}

for off in \$OFFSETS; do
  run_arm on  \$off
  run_arm off \$off --ablate-book
done

echo \"=== build per-fold comparison ===\"
COMPARE=\$HOME/wf_compare.txt
# best_line: the SAVED (best) epoch's dense-window fixed-coverage line (same rule
# as gcp_ablate.sh) — the last 'epoch ..' line immediately followed by 'saved ->'.
best_line() {
  local blk
  blk=\$(grep -E -B1 'saved ->|saved →' \"\$1\" 2>/dev/null | grep -E '^epoch ' | tail -1)
  if [[ -n \"\$blk\" ]]; then echo \"\$blk\"; else
    grep -E '^epoch .*sel@cov' \"\$1\" 2>/dev/null | tail -1 || echo '(no epoch line)'
  fi
}
# lb_of: extract the 'lb=' number from a best_line
lb_of() { echo \"\$1\" | sed -n 's/.*lb=\\([0-9.]*\\).*/\\1/p'; }
# n_dir_of: extract 'n_dir=' — how many bars inside the top-5% slice have a TRUE
# directional label. This is the sample the Wilson LB is computed on.
#
# WHY IT GATES THE VERDICT (learned from wf-20260817T030350Z): train_m2's own
# MIN_GATED_FOR_CKPT floor is 500 — below that, checkpoint_score multiplies the LB
# by n_dir/500 because it does not trust it. This compare file printed the RAW,
# unpenalized LB regardless, so a fold could be 'decided' on a number the harness
# itself rejects. In that run ALL SIX book-OFF arms were under the floor (184-464)
# against book-ON's 487-1844: the OFF arm collapses to flat and spends its
# confidence on true-flat bars, leaving ~200 directional leftovers to score on. The
# two arms were not measuring the same population, and the run was undecidable.
n_dir_of() { echo \"\$1\" | sed -n 's/.*n_dir=\\([0-9]*\\).*/\\1/p'; }
WF_MIN_DIR=\${WF_MIN_DIR:-500}
{
  echo \"Walk-forward 30m book-ON vs book-OFF — run=\$RUN_ID git=\${GIT_SHA:0:8}\"
  echo \"epochs=\$EPOCHS seq=\$SEQ_LEN val_frac=\$VAL_FRAC folds(offset)=\$OFFSETS\"
  echo \"reg: dropout=\$WF_DROPOUT weight_decay=\$WF_WEIGHT_DECAY hidden=\$WF_HIDDEN\"
  echo \"pairs=\${PAIRS_FLAG:-DB-whitelist}. Rolling-origin: train strictly before each val window.\"
  echo \"Metric = train_m2 dense-window val, fixed top-5% coverage, primary 30m, Wilson LB.\"
  echo \"================================================================\"
  min_gap=\"\"
  n_decidable=0
  n_undecidable=0
  for off in \$OFFSETS; do
    ftag=\"\${off//./_}\"
    on_line=\"\$(best_line \$HOME/wf_on.f\$ftag.log)\"
    off_line=\"\$(best_line \$HOME/wf_off.f\$ftag.log)\"
    on_lb=\"\$(lb_of \"\$on_line\")\"; off_lb=\"\$(lb_of \"\$off_line\")\"
    on_n=\"\$(n_dir_of \"\$on_line\")\"; off_n=\"\$(n_dir_of \"\$off_line\")\"
    # A fold is DECIDABLE only if BOTH arms cleared the n_dir floor. Undecidable
    # folds still print their numbers (for diagnosis) but are excluded from the
    # min-gap verdict rather than silently dragging it.
    why=\"\"
    if [[ -z \"\$on_lb\" || -z \"\$off_lb\" ]]; then
      why=\"missing lb\"
    elif [[ -z \"\$on_n\" || -z \"\$off_n\" ]]; then
      why=\"missing n_dir\"
    elif (( on_n < WF_MIN_DIR || off_n < WF_MIN_DIR )); then
      why=\"n_dir below floor \$WF_MIN_DIR (ON=\$on_n OFF=\$off_n)\"
    fi
    gap=\"\"
    if [[ -n \"\$on_lb\" && -n \"\$off_lb\" ]]; then
      gap=\$(awk -v a=\"\$on_lb\" -v b=\"\$off_lb\" 'BEGIN{printf \"%.3f\", a-b}')
    fi
    if [[ -z \"\$why\" ]]; then
      n_decidable=\$((n_decidable + 1))
      if [[ -z \"\$min_gap\" ]] || awk -v g=\"\$gap\" -v m=\"\$min_gap\" 'BEGIN{exit !(g<m)}'; then min_gap=\"\$gap\"; fi
    else
      n_undecidable=\$((n_undecidable + 1))
    fi
    echo \"\"
    echo \"--- fold val_offset=\$off (val_frac=\$VAL_FRAC) ---\"
    echo \"  book-ON  : \$on_line\"
    echo \"  book-OFF : \$off_line\"
    if [[ -z \"\$why\" ]]; then
      echo \"  LB gap (on-off) = \${gap:-n/a}   [decidable: n_dir ON=\$on_n OFF=\$off_n]\"
    else
      echo \"  LB gap (on-off) = \${gap:-n/a}   [UNDECIDABLE — \$why; EXCLUDED from verdict]\"
    fi
  done
  echo \"\"
  echo \"================================================================\"
  echo \"DECIDABLE folds = \$n_decidable   UNDECIDABLE (n_dir < \$WF_MIN_DIR) = \$n_undecidable\"
  echo \"MIN LB gap across DECIDABLE folds = \${min_gap:-n/a}\"
  echo \"\"
  echo \"VERDICT RULE (revised 2026-08-18 — see docs/NEXT_TRAINING_PLAN.md N1):\"
  echo \"  0. A fold counts only if BOTH arms have n_dir >= \$WF_MIN_DIR. Below that\"
  echo \"     floor train_m2's own checkpoint_score down-weights the LB as untrusted,\"
  echo \"     so a raw LB from such an arm cannot decide anything.\"
  echo \"  1. Fewer than 3 decidable folds -> INCONCLUSIVE. Do not read the min gap.\"
  echo \"     The usual cause is the book-OFF arm collapsing to flat and spending its\"
  echo \"     top-5% confidence on true-flat bars. Needs more book history (or a\"
  echo \"     matched-n_dir comparison), NOT another launch of this same command.\"
  echo \"  2. Otherwise: min gap > ~0.05 across ALL decidable folds -> the 30m book\"
  echo \"     edge is robust, not a single-window artifact -> escalate microstructure.\"
  echo \"  3. Any decidable fold with gap <=0 or overlapping LBs -> the single-window\"
  echo \"     ablation was optimistic -> keep collecting, re-check at ~60d.\"
} > \"\$COMPARE\"
cat \"\$COMPARE\"
gcloud storage cp \"\$COMPARE\" \"\$GCS_BUCKET/walkforward/\$RUN_ID.compare.txt\"
gcloud storage cp \"\$COMPARE\" \"\$GCS_BUCKET/walkforward/latest.compare.txt\"
echo \"compare -> \$GCS_BUCKET/walkforward/\$RUN_ID.compare.txt\"

echo \"=== walk-forward finished \$(date -u) ===\"
ENDSCRIPT
chmod +x \$HOME/run_flux_wf.sh
tmux kill-session -t fluxwf 2>/dev/null || true
tmux new-session -d -s fluxwf \"bash \$HOME/run_flux_wf.sh\"
echo 'tmux session fluxwf started'
tmux ls
sleep 8
echo '--- log so far ---'
tail -n 30 \$HOME/wf.log 2>/dev/null || echo '(starting...)'
" "$GCP_ZONE"

echo ""
echo "OK — walk-forward started on $GCP_WF_INSTANCE (run=$RUN_ID)."
echo "SEPARATE VM from training/audit/ablate. Neither arm touches the served"
echo "checkpoint, so SERVING IS UNAFFECTED. Self-deletes on success, stops on failure."
echo "Runs 2 arms x $(echo $OFFSETS | wc -w | tr -d ' ') folds = short CPU runs each."
echo "Mac may sleep now."
echo "  status:  ./scripts/gcp_walkforward.sh --status"
echo "  live:    gcloud compute ssh $GCP_WF_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tmux attach -t fluxwf"
echo "  results: ./scripts/gcp_walkforward.sh --fetch $RUN_ID"
