#!/usr/bin/env bash
# Book-ON vs book-OFF ablation on a THROWAWAY VM — one command, self-cleaning.
#
# The DECISIVE microstructure test (see docs/NEXT_TRAINING_PLAN.md "Dense-window
# ablation run"): train+eval M2 twice on the SAME dense live-book window
# (--require-book), once with the 11 microstructure features ON and once with
# them zeroed (--ablate-book). If book-ON adds held-out directional edge
# (top-5% dir_acc / Wilson LB on the primary 30m + 60m heads), the audit signal
# survives inside the model => escalate microstructure collection. If ~equal,
# the audit signal doesn't survive modeling => don't over-invest.
#
# Runs on its OWN instance ($GCP_ABLATE_INSTANCE, default fluxtrader-ablate),
# SEPARATE from the training VM ($GCP_TRAIN_INSTANCE) and the audit VM, so an
# ablation, an audit, and a training run can all happen at the same time without
# sharing a VM, Postgres, tmux session, or status marker.
#
# It mirrors scripts/gcp_train.sh / gcp_audit.sh:
#   1. fresh DB dump: always-on -> bucket
#   2. create (or reuse) the temp ablate VM
#   3. git clone GIT_REMOTE @ GIT_REF, pull dump, restore Postgres
#   4. run BOTH arms back-to-back inside the ml_trainer container:
#        arm A (book-ON):  train_m2.py --require-book
#        arm B (book-OFF): train_m2.py --require-book --ablate-book
#      each followed by eval_m2.py at fixed gate sweep
#   5. push both console logs + both checkpoints + a side-by-side comparison to
#      the bucket; NEITHER arm touches checkpoints/latest.pt (won't affect serving)
#   6. self-DELETE on success / self-STOP on failure   (never left billing)
#
# Returns immediately. Watch / fetch results:
#   ./scripts/gcp_ablate.sh                       # launch (40 epochs, seq 128)
#   ./scripts/gcp_ablate.sh 60 128                # epochs seq_len
#   TRAIN_PAIRS=BTCUSDT,ETHUSDT ./scripts/gcp_ablate.sh
#   KEEP_VM=1 ./scripts/gcp_ablate.sh             # debug: don't auto delete/stop VM
#
#   watch status:   ./scripts/gcp_ablate.sh --status
#   full logs:      ./scripts/gcp_ablate.sh --fetch [run_id]   (both arms + compare)
#   list runs:      ./scripts/gcp_ablate.sh --list
#
# Results in the bucket:
#   gs://<bucket>/ablations/<RUN_ID>.on.log      book-ON arm console
#   gs://<bucket>/ablations/<RUN_ID>.off.log     book-OFF arm console
#   gs://<bucket>/ablations/<RUN_ID>.compare.txt side-by-side dir_acc/wilson_lb
#   gs://<bucket>/ablations/<RUN_ID>.on.pt       book-ON checkpoint
#   gs://<bucket>/ablations/<RUN_ID>.off.pt      book-OFF checkpoint
#   gs://<bucket>/ablations/latest.*             convenience copies
#   gs://<bucket>/status/ablate_latest.json      status marker (separate)
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud

# Separate throwaway VM name so ablate never collides with train/audit.
: "${GCP_ABLATE_INSTANCE:=fluxtrader-ablate}"

# --- fetch / list modes (read results from the bucket, no VM needed) -------------
ABLATE_PREFIX="$GCS_BUCKET/ablations"
if [[ "${1:-}" == "--list" ]]; then
  echo "==> ablation runs ($ABLATE_PREFIX/<run_id>.compare.txt, oldest -> newest):"
  gcloud storage ls "$ABLATE_PREFIX/" 2>/dev/null \
    | sed -n 's#.*/ablations/\(.*\)\.compare\.txt$#\1#p' | sort || echo "(none yet)"
  exit 0
fi
if [[ "${1:-}" == "--status" ]]; then
  echo "==> bucket: $GCS_BUCKET"
  MARKER="$(gcloud storage cat "$GCS_BUCKET/status/ablate_latest.json" 2>/dev/null || true)"
  if [[ -z "$MARKER" ]]; then
    echo "no ablation marker yet (nothing has run, or run just starting)"
  else
    echo "last ablation marker: $MARKER"
  fi
  VM_STATE="$(gcloud compute instances describe "$GCP_ABLATE_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)' 2>/dev/null || true)"
  if [[ -n "$VM_STATE" ]]; then
    echo "ablate VM $GCP_ABLATE_INSTANCE: $VM_STATE (zone=$GCP_ZONE)"
    if [[ "$VM_STATE" == "RUNNING" ]]; then
      echo "live view:  gcloud compute ssh $GCP_ABLATE_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tmux attach -t fluxablate"
    elif [[ "$VM_STATE" == "TERMINATED" ]]; then
      echo "VM is STOPPED (a FAILED ablation kept for debug). Inspect:"
      echo "  gcloud compute instances start $GCP_ABLATE_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT"
      echo "  gcloud compute ssh $GCP_ABLATE_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tail -n 120 '~/ablate.log'"
    fi
  else
    echo "ablate VM $GCP_ABLATE_INSTANCE: gone (self-deleted or never created)"
  fi
  echo ""
  echo "full logs + compare:  ./scripts/gcp_ablate.sh --fetch"
  exit 0
fi
if [[ "${1:-}" == "--fetch" ]]; then
  RUN_ID="${2:-latest}"
  echo "==> ablation comparison ($ABLATE_PREFIX/$RUN_ID.compare.txt):"
  echo "--------------------------------------------------------------------------"
  gcloud storage cat "$ABLATE_PREFIX/$RUN_ID.compare.txt" 2>/dev/null \
    || { echo "(no compare yet — run still in progress or wrong id; try --list)"; exit 1; }
  echo ""
  echo "==> full arm logs:"
  echo "  book-ON :  gcloud storage cat $ABLATE_PREFIX/$RUN_ID.on.log"
  echo "  book-OFF:  gcloud storage cat $ABLATE_PREFIX/$RUN_ID.off.log"
  exit 0
fi

# --- parse args (epochs seq_len; pairs/horizons/primary via env, like gcp_train) -
EPOCHS="${1:-40}"
SEQ_LEN="${2:-128}"
PAIRS_ARG="${TRAIN_PAIRS:-}"
HORIZONS="${TRAIN_HORIZONS:-5,30,60}"
PRIMARY="${TRAIN_PRIMARY:-30}"

echo_cfg

RUN_ID="ablate-$(date -u +%Y%m%dT%H%M%SZ)"
PAIRS_FLAG=""
if [[ -n "$PAIRS_ARG" ]]; then PAIRS_FLAG="--pairs ${PAIRS_ARG}"; fi

echo ""
echo "==> run_id=$RUN_ID  epochs=$EPOCHS seq=$SEQ_LEN horizons=$HORIZONS primary=${PRIMARY}m pairs=${PAIRS_ARG:-DB-whitelist} device=cpu"
echo "    arms: A=book-ON (--require-book)   B=book-OFF (--require-book --ablate-book)"

# --- 0. sanity: bucket reachable -------------------------------------------------
if ! gcloud storage ls "$GCS_BUCKET" >/dev/null 2>&1; then
  echo "ERROR: bucket $GCS_BUCKET not accessible. See gcp_train.sh header for setup."
  exit 1
fi

# --- 1. ensure the (CPU) temp VM exists -----------------------------------------
echo ""
echo "==> ensure temp VM $GCP_ABLATE_INSTANCE ($GCP_TRAIN_MACHINE)"
_VM_CREATED=0
if gcloud compute instances describe "$GCP_ABLATE_INSTANCE" \
     --project="$GCP_PROJECT" --zone="$GCP_ZONE" >/dev/null 2>&1; then
  STATUS=$(gcloud compute instances describe "$GCP_ABLATE_INSTANCE" \
    --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)')
  echo "    exists (status=$STATUS)"
  if [[ "$STATUS" != "RUNNING" ]]; then
    gcloud compute instances start "$GCP_ABLATE_INSTANCE" \
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
  gcloud compute instances create "$GCP_ABLATE_INSTANCE" \
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
  if gssh "$GCP_ABLATE_INSTANCE" "echo ok" "$GCP_ZONE" >/dev/null 2>&1; then break; fi
  sleep 5
done
echo "==> waiting for Docker (first boot 1-3 min) ..."
for i in $(seq 1 60); do
  if gssh "$GCP_ABLATE_INSTANCE" "docker compose version" "$GCP_ZONE" >/dev/null 2>&1; then
    echo "    Docker OK"; break
  fi
  if [[ "$i" -eq 60 ]]; then echo "ERROR: Docker not ready."; exit 1; fi
  sleep 5
done
gssh "$GCP_ABLATE_INSTANCE" \
  "sudo usermod -aG docker \$USER; sudo chmod 666 /var/run/docker.sock 2>/dev/null || true; command -v git >/dev/null || sudo apt-get install -y git; command -v tmux >/dev/null || sudo apt-get install -y tmux" \
  "$GCP_ZONE"

# --- 2. fresh dump: always-on -> bucket -----------------------------------------
echo ""
echo "==> fresh dump from $GCP_ALWAYS_ON -> $GCS_BUCKET/dumps/$RUN_ID.sql.gz"
gssh "$GCP_ALWAYS_ON" "set -e
  cd \$HOME/$REMOTE_REPO_NAME
  docker compose exec -T postgres pg_isready -U fluxtrader
  TFLAGS=''
  for t in $DUMP_TABLES; do TFLAGS=\"\$TFLAGS -t \$t\"; done
  docker compose exec -T postgres bash -c \"pg_dump -U fluxtrader -d fluxtrader --format=plain --no-owner --no-acl \$TFLAGS\" \
    | gzip > /var/tmp/fluxtrader_ablate.sql.gz
  ls -lh /var/tmp/fluxtrader_ablate.sql.gz
  gcloud storage cp /var/tmp/fluxtrader_ablate.sql.gz $GCS_BUCKET/dumps/$RUN_ID.sql.gz
  gcloud storage cp $GCS_BUCKET/dumps/$RUN_ID.sql.gz $GCS_BUCKET/dumps/ablate_latest.sql.gz
  rm -f /var/tmp/fluxtrader_ablate.sql.gz
" "$GCP_ZONE"

# --- 3. write remote self-cleaning ablation job and launch in tmux --------------
echo ""
echo "==> launching self-cleaning ablation job in remote tmux 'fluxablate'"
gssh "$GCP_ABLATE_INSTANCE" "cat > \$HOME/run_flux_ablate.sh <<PRELUDE
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
export PAIRS_FLAG='$PAIRS_FLAG'
export KEEP_VM='$KEEP_VM'
export MODEL_VOLUME_NAME='$MODEL_VOLUME_NAME'
PRELUDE
cat >> \$HOME/run_flux_ablate.sh << 'ENDSCRIPT'
set -Eeuo pipefail
LOG=\$HOME/ablate.log
: > \"\$LOG\"
exec > >(tee -a \"\$LOG\") 2>&1

meta() { curl -s -H 'Metadata-Flavor: Google' \"http://metadata.google.internal/computeMetadata/v1/instance/\$1\"; }

finish() {
  local status=\"\$1\"
  echo \"=== finish: \$status \$(date -u) ===\"
  gcloud storage cp \"\$LOG\" \"\$GCS_BUCKET/ablations/\$RUN_ID.driver.log\" || true
  printf '{\"status\":\"%s\",\"git_sha\":\"%s\",\"run\":\"%s\",\"ended\":\"%s\",\"kind\":\"ablate\"}\n' \
    \"\$status\" \"\${GIT_SHA:-}\" \"\$RUN_ID\" \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > /tmp/status.json
  gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/\$RUN_ID.json\" || true
  gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/ablate_latest.json\" || true

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

printf '{\"status\":\"RUNNING\",\"git_sha\":\"%s\",\"run\":\"%s\",\"started\":\"%s\",\"kind\":\"ablate\"}\n' \
  \"\${GIT_SHA:-}\" \"\$RUN_ID\" \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > /tmp/status.json
gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/\$RUN_ID.json\" || true
gcloud storage cp /tmp/status.json \"\$GCS_BUCKET/status/ablate_latest.json\" || true

echo \"=== ablate start \$(date -u) run=\$RUN_ID ===\"

echo \"=== checkout \$GIT_REMOTE @ \$GIT_REF ===\"
sudo rm -rf \$HOME/\$REMOTE_REPO_NAME
git clone --branch \"\$GIT_REF\" \"\$GIT_REMOTE\" \$HOME/\$REMOTE_REPO_NAME \
  || git clone \"\$GIT_REMOTE\" \$HOME/\$REMOTE_REPO_NAME
cd \$HOME/\$REMOTE_REPO_NAME
git checkout \"\$GIT_REF\"
GIT_SHA=\"\$(git rev-parse HEAD)\"
echo \"git_sha=\$GIT_SHA\"

echo \"=== pull dump from bucket ===\"
mkdir -p \$HOME/fluxtrader-train-export
gcloud storage cp \"\$GCS_BUCKET/dumps/ablate_latest.sql.gz\" \$HOME/fluxtrader-train-export/fluxtrader_ablate.sql.gz

echo \"=== reset + restore postgres ===\"
docker compose down -v || true
docker compose up -d postgres
for i in \$(seq 1 60); do docker compose exec -T postgres pg_isready -U fluxtrader && break; sleep 2; done
for i in \$(seq 1 30); do docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -c 'SELECT 1' >/dev/null 2>&1 && break; sleep 2; done
sleep 2
gunzip -c \$HOME/fluxtrader-train-export/fluxtrader_ablate.sql.gz \
  | docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -v ON_ERROR_STOP=0

CANDLES=\$(docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"SELECT count(*) FROM candles;\" 2>/dev/null | tr -d '[:space:]' || true)
BOOK=\$(docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -At -c \"SELECT count(*) FROM orderbook_snapshots;\" 2>/dev/null | tr -d '[:space:]' || true)
echo \"candles=\$CANDLES book=\$BOOK\"
if ! [[ \"\$CANDLES\" =~ ^[0-9]+\$ ]] || [[ \"\$CANDLES\" -lt 1000 ]]; then echo \"ERROR: restore failed (candles=\$CANDLES)\"; exit 1; fi
if ! [[ \"\$BOOK\" =~ ^[0-9]+\$ ]] || [[ \"\$BOOK\" -lt 100 ]]; then echo \"ERROR: restore failed (book=\$BOOK)\"; exit 1; fi

# compose declares model_weights as external -> must exist before 'run'.
docker volume create \"\${MODEL_VOLUME_NAME:-trading_agent_model_weights}\" >/dev/null 2>&1 || true

# ---- run one arm: \$1=arm-tag (on|off)  \$2..=extra train flags ----
# CRITICAL correctness notes:
#  * train_m2.py hardcodes its checkpoint to \$MODEL_DIR/m2_multi.pt (it does NOT
#    honor MODEL_PATH). We give each arm its OWN MODEL_DIR under the bind-mounted
#    output dir so NEITHER arm ever writes the served /models/m2_multi.pt.
#  * The decisive held-out metric is produced by train_m2.py ITSELF: with
#    --require-book its per-epoch line 'sel@cov0.05 dir_acc=.. lb=.. n_dir=..' is
#    computed on the DENSE-window primary-horizon val split — exactly the A/B
#    number we want. eval_m2.py is NOT used here: it re-splits the FULL history
#    (book-absent) and can't ablate, so it would measure the wrong thing.
run_arm() {
  local tag=\"\$1\"; shift
  local extra=\"\$*\"
  local armlog=\$HOME/ablate_\$tag.log
  echo \"=================================================================\"
  echo \"=== ARM \$tag : train_m2.py --require-book \$extra  (primary=\${PRIMARY}m) ===\"
  echo \"=================================================================\"
  docker compose --profile ml run --rm \
    -e HORIZONS_MINUTES=\$HORIZONS -e PRIMARY_HORIZON=\$PRIMARY -e SEQ_LEN=\$SEQ_LEN \
    -e MODEL_DIR=/workspace/train/output/ablate_\$tag \
    -e FLUX_GIT_SHA=\$GIT_SHA \
    ml_trainer python train_m2.py --device cpu --epochs \$EPOCHS --seq-len \$SEQ_LEN \
      --horizons \$HORIZONS --primary \$PRIMARY \$PAIRS_FLAG --require-book \$extra \
    2>&1 | tee \"\$armlog\"

  gcloud storage cp \"\$armlog\" \"\$GCS_BUCKET/ablations/\$RUN_ID.\$tag.log\" || true
  gcloud storage cp \"\$armlog\" \"\$GCS_BUCKET/ablations/latest.\$tag.log\" || true
  local ckpt=\$HOME/\$REMOTE_REPO_NAME/ml/train/output/ablate_\$tag/m2_multi.pt
  if [[ -f \"\$ckpt\" ]]; then
    gcloud storage cp \"\$ckpt\" \"\$GCS_BUCKET/ablations/\$RUN_ID.\$tag.pt\" || true
  fi
}

# train_m2's fixed-coverage dir_acc line is computed for the PRIMARY horizon only.
# To cover both 30m and 60m (the plan's PENDING table) we run each arm once per
# horizon-as-primary on the SAME dense window: 2 arms x {30,60} = 4 short CPU runs.
# Tags: on30/off30 (primary=30m), on60/off60 (primary=60m).
for _prim in 30 60; do
  PRIMARY=\"\$_prim\" run_arm on\$_prim
  PRIMARY=\"\$_prim\" run_arm off\$_prim --ablate-book
done

echo \"=== build side-by-side comparison ===\"
COMPARE=\$HOME/ablate_compare.txt
# best_line: the SAVED (best) epoch's dense-window fixed-coverage line. train_m2
# prints the 'epoch NN ... sel@cov0.05 dir_acc=.. lb=..' line and THEN '  saved -> '
# only when that epoch improves the sel-score, so the LAST 'epoch ..' line that is
# immediately followed by a 'saved ->' line is the promoted checkpoint's held-out
# result. grep -B1 the final save and keep the epoch line.
best_line() {  # \$1 = arm log
  local blk
  blk=\$(grep -E -B1 'saved ->|saved →' \"\$1\" 2>/dev/null | grep -E '^epoch ' | tail -1)
  if [[ -n \"\$blk\" ]]; then echo \"\$blk\"; else
    grep -E '^epoch .*sel@cov' \"\$1\" 2>/dev/null | tail -1 || echo '(no epoch line)'
  fi
}
{
  echo \"Book-ON vs Book-OFF ablation — run=\$RUN_ID git=\${GIT_SHA:0:8}\"
  echo \"epochs=\$EPOCHS seq=\$SEQ_LEN horizons=\$HORIZONS pairs=\${PAIRS_FLAG:-DB-whitelist}\"
  echo \"dense window (--require-book); OFF arm zeroes the 11 book features.\"
  echo \"Metric = train_m2 dense-window val, fixed top-5% coverage, PRIMARY horizon.\"
  echo \"================================================================\"
  echo \"\"
  for _prim in 30 60; do
    echo \"--- primary \${_prim}m : best (max sel-score) epoch, dense-window val ---\"
    echo \"  book-ON  : \$(best_line \$HOME/ablate_on\$_prim.log)\"
    echo \"  book-OFF : \$(best_line \$HOME/ablate_off\$_prim.log)\"
    echo \"\"
  done
  echo \"(Full per-epoch curves in the .on{30,60}.log / .off{30,60}.log arm logs.)\"
  echo \"================================================================\"
  echo \"DECISION RULE: if book-ON primary-30m/60m top-5% dir_acc (read with its\"
  echo \"Wilson LB 'lb=', not the point estimate) is materially > book-OFF, the book\"
  echo \"edge survives inside the model -> ESCALATE microstructure collection.\"
  echo \"If ~equal (tiny window: overlapping Wilson LBs), the audit signal does NOT\"
  echo \"survive modeling yet -> keep collecting, don't over-invest.\"
} > \"\$COMPARE\"
cat \"\$COMPARE\"
gcloud storage cp \"\$COMPARE\" \"\$GCS_BUCKET/ablations/\$RUN_ID.compare.txt\"
gcloud storage cp \"\$COMPARE\" \"\$GCS_BUCKET/ablations/latest.compare.txt\"
echo \"compare -> \$GCS_BUCKET/ablations/\$RUN_ID.compare.txt\"

echo \"=== ablate finished \$(date -u) ===\"
ENDSCRIPT
chmod +x \$HOME/run_flux_ablate.sh
tmux kill-session -t fluxablate 2>/dev/null || true
tmux new-session -d -s fluxablate \"bash \$HOME/run_flux_ablate.sh\"
echo 'tmux session fluxablate started'
tmux ls
sleep 8
echo '--- log so far ---'
tail -n 30 \$HOME/ablate.log 2>/dev/null || echo '(starting...)'
" "$GCP_ZONE"

echo ""
echo "OK — ablation started on $GCP_ABLATE_INSTANCE (run=$RUN_ID)."
echo "This is a SEPARATE VM from training ($GCP_TRAIN_INSTANCE) and audit — the"
echo "three never share a VM, Postgres, tmux session, or status marker."
echo "It trains BOTH arms (book-ON then book-OFF) and writes a side-by-side compare."
echo "Neither arm touches checkpoints/latest.pt, so SERVING IS UNAFFECTED."
echo "The VM will DELETE itself on success, STOP itself on failure (KEEP_VM=$KEEP_VM)."
echo "Mac may sleep now."
echo "  status:  ./scripts/gcp_ablate.sh --status"
echo "  live:    gcloud compute ssh $GCP_ABLATE_INSTANCE --zone=$GCP_ZONE --project=$GCP_PROJECT -- tmux attach -t fluxablate"
echo "  results: ./scripts/gcp_ablate.sh --fetch $RUN_ID     (compare + arm logs)"
