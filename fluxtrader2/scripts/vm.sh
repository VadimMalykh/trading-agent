#!/usr/bin/env bash
# fluxtrader2 — manage the dedicated work VM and run commands on it.
#
# The work VM is where data lives and every CPU job runs (decided 2026-09-15: the MacBook is
# short on disk, its CPU is shared, and a VPN toggle can kill a long download). Nothing is
# installed in Docker on the VM; ft2 runs in a plain virtualenv there (see vm_setup.sh).
# The VM is STOPPED when idle — a stopped VM bills only its disk.
#
#   ./fluxtrader2/scripts/vm.sh create      # one-time: create the VM (spec below), then setup
#   ./fluxtrader2/scripts/vm.sh setup       # (re)install python venv + deps on the VM, idempotent
#   ./fluxtrader2/scripts/vm.sh start|stop|status
#   ./fluxtrader2/scripts/vm.sh push        # rsync fluxtrader2/ code up (never data/ or output/)
#   ./fluxtrader2/scripts/vm.sh pull        # rsync output/ down (results, reports)
#   ./fluxtrader2/scripts/vm.sh run <ft2 args…>     # python -m ft2 <args> on the VM, in tmux-less foreground
#   ./fluxtrader2/scripts/vm.sh bg <name> <ft2 args…>  # same, detached with nohup, log in output/logs/<name>.log
#   ./fluxtrader2/scripts/vm.sh ssh [cmd]   # interactive shell or a one-off command
#
# Env: FT2_VM (default fluxtrader2-work), GCP_PROJECT (fluxtrader), GCP_ZONE (me-central1-b).
# Same zone as the collector so the data export is VM-to-VM inside the region.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/google-cloud-sdk/bin:$PATH"
PROJECT="${GCP_PROJECT:-fluxtrader}"
ZONE="${GCP_ZONE:-me-central1-b}"
VM="${FT2_VM:-fluxtrader2-work}"
MACHINE="${FT2_MACHINE:-e2-standard-4}"     # 4 vCPU / 16 GB is enough for P0–P5; resize later if a job is CPU-bound for hours
DISK_GB="${FT2_DISK_GB:-200}"               # full-history 1m candles (~2 GB parquet) + public archives (tens of GB)
REMOTE_DIR="fluxtrader2"                    # ~/fluxtrader2 on the VM
SSH_HOST="$VM.$ZONE.$PROJECT"               # alias created by `gcloud compute config-ssh`

gssh() { gcloud compute ssh --zone "$ZONE" --project "$PROJECT" "$VM" --quiet -- "$@"; }
ensure_ssh_alias() {
  grep -q "Host $SSH_HOST" ~/.ssh/config 2>/dev/null || gcloud compute config-ssh --project "$PROJECT" --quiet >/dev/null
}

cmd="${1:-}"; shift || true
case "$cmd" in
  create)
    gcloud compute instances create "$VM" --zone "$ZONE" --project "$PROJECT" \
      --machine-type "$MACHINE" --image-family debian-12 --image-project debian-cloud \
      --boot-disk-size "${DISK_GB}GB" --boot-disk-type pd-balanced \
      --scopes cloud-platform --labels project=fluxtrader2
    echo "created; waiting for ssh…" >&2; sleep 30
    exec "$0" setup ;;
  setup)
    gcloud compute scp --zone "$ZONE" --project "$PROJECT" --quiet \
      "$ROOT/fluxtrader2/scripts/vm_setup.sh" "$ROOT/fluxtrader2/requirements.txt" "$VM:~/"
    gssh "bash ~/vm_setup.sh"
    exec "$0" push ;;
  start)  gcloud compute instances start "$VM" --zone "$ZONE" --project "$PROJECT" --quiet ;;
  stop)   gcloud compute instances stop  "$VM" --zone "$ZONE" --project "$PROJECT" --quiet ;;
  status) gcloud compute instances describe "$VM" --zone "$ZONE" --project "$PROJECT" \
            --format='value(status,machineType.basename(),networkInterfaces[0].networkIP,disks[0].diskSizeGb)' ;;
  push)
    ensure_ssh_alias
    rsync -az --delete --exclude data/ --exclude output/ --exclude __pycache__/ \
      "$ROOT/fluxtrader2/" "$SSH_HOST:$REMOTE_DIR/" && echo "pushed" >&2 ;;
  pull)
    ensure_ssh_alias
    mkdir -p "$ROOT/fluxtrader2/output"
    rsync -az "$SSH_HOST:$REMOTE_DIR/output/" "$ROOT/fluxtrader2/output/" && echo "pulled output/" >&2 ;;
  run)
    "$0" push
    gssh "cd ~/$REMOTE_DIR && source ~/ft2-venv/bin/activate && PYTHONPATH=. python -m ft2 $*" ;;
  bg)
    name="$1"; shift
    "$0" push
    gssh "cd ~/$REMOTE_DIR && mkdir -p output/logs && source ~/ft2-venv/bin/activate && \
          PYTHONPATH=. nohup python -m ft2 $* > output/logs/$name.log 2>&1 & echo started \$!"
    echo "log: ./fluxtrader2/scripts/vm.sh ssh 'tail -f ~/$REMOTE_DIR/output/logs/$name.log'" >&2 ;;
  ssh)
    if [[ $# -eq 0 ]]; then gcloud compute ssh --zone "$ZONE" --project "$PROJECT" "$VM"; else gssh "$@"; fi ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
