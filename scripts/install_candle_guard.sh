#!/usr/bin/env bash
# Install the daily candle integrity guard on fluxtrader-1 as a systemd timer.
#
#   ./scripts/install_candle_guard.sh              # install (or update) and show status
#   ./scripts/install_candle_guard.sh --run-now    # ...and fire one run immediately
#   ./scripts/install_candle_guard.sh --uninstall  # remove timer and unit
#
# systemd rather than cron: the VM is Ubuntu 26.04 with no cron daemon installed, and a
# timer is the better fit anyway -- Persistent=true makes a run missed while the VM was
# down fire on the next boot, which is exactly when an integrity check matters most.
#
# The guard itself is scripts/candle_guard.sh, running from the VM's git checkout, so
# updating it is a `git pull` and needs no reinstall.
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud

# 01:40 UTC: late enough that yesterday is unambiguously closed, early enough that a
# failure is waiting when the day starts. The randomized delay keeps twelve pairs of
# kline requests off the exact minute boundary.
ON_CALENDAR="${CANDLE_GUARD_ON_CALENDAR:-*-*-* 01:40:00}"
RUN_NOW=0
UNINSTALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-now) RUN_NOW=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    *) echo "ERROR: unknown flag '$1'"; exit 1 ;;
  esac
done

if [[ $UNINSTALL -eq 1 ]]; then
  echo "==> removing candle guard from $GCP_ALWAYS_ON"
  gssh "$GCP_ALWAYS_ON" "
    sudo systemctl disable --now candle-guard.timer 2>/dev/null || true
    sudo rm -f /etc/systemd/system/candle-guard.service /etc/systemd/system/candle-guard.timer
    sudo systemctl daemon-reload
    echo 'candle guard removed'
  " "$GCP_ZONE"
  exit 0
fi

echo "==> installing candle guard on $GCP_ALWAYS_ON (OnCalendar='$ON_CALENDAR')"

gssh "$GCP_ALWAYS_ON" "set -e
REPO=\$HOME/$REMOTE_REPO_NAME
test -x \$REPO/scripts/candle_guard.sh || { echo 'ERROR: scripts/candle_guard.sh missing or not executable — git pull on the VM first'; exit 1; }

sudo tee /etc/systemd/system/candle-guard.service >/dev/null <<UNIT
[Unit]
Description=Compare stored candles against Binance closed klines (docs/CANDLE_POLL_DEFECT.md)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User=\$USER
WorkingDirectory=\$REPO
ExecStart=\$REPO/scripts/candle_guard.sh
# The guard makes ~24 kline requests and waits on a container start; give it room, but
# never let a hung run sit forever and block the next day's check.
TimeoutStartSec=1800
UNIT

sudo tee /etc/systemd/system/candle-guard.timer >/dev/null <<UNIT
[Unit]
Description=Daily candle integrity check

[Timer]
OnCalendar=$ON_CALENDAR
RandomizedDelaySec=300
# Fire a missed run after downtime: a check skipped because the VM was off is exactly
# the window in which data is most likely to have gone wrong.
Persistent=true

[Install]
WantedBy=timers.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now candle-guard.timer
echo '--- timer ---'
systemctl list-timers candle-guard.timer --no-pager | head -3
" "$GCP_ZONE"

if [[ $RUN_NOW -eq 1 ]]; then
  echo ""
  echo "==> firing one run now (this starts the ml_trainer container; takes a few minutes)"
  gssh "$GCP_ALWAYS_ON" "
    sudo systemctl start candle-guard.service || true
    echo '--- status ---'
    systemctl status candle-guard.service --no-pager 2>&1 | tail -15
    echo '--- result ---'
    cat /var/tmp/candle_guard_status.json 2>/dev/null || echo '(no status file yet)'
  " "$GCP_ZONE"
fi

echo ""
echo "OK — candle guard installed on $GCP_ALWAYS_ON."
echo "Check:     gcloud compute ssh $GCP_ALWAYS_ON --zone=$GCP_ZONE --project=$GCP_PROJECT --command 'cat /var/tmp/candle_guard_status.json'"
echo "Log:       gcloud compute ssh $GCP_ALWAYS_ON --zone=$GCP_ZONE --project=$GCP_PROJECT --command 'tail -40 ~/candle_guard.log'"
echo "Run once:  ./scripts/install_candle_guard.sh --run-now"
echo ""
echo "It is QUIET on success and alerts on Telegram on failure. Note the one case it"
echo "cannot cover: if the VM is off or the timer is disabled, nothing runs and nothing"
echo "alerts. Surfacing candle_guard_status.json on /api/health would close that gap."
