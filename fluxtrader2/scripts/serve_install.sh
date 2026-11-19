#!/usr/bin/env bash
# Runs ON the serve host fluxtrader2-serve (Debian 12, systemd). Installs or updates the three systemd timers of P7
# (docs/SERVE.md). Idempotent — this is also the reinstall runbook: on a fresh host, `vm.sh setup` (venv) then
# `vm.sh serve-install` (push code + run this).
#
#   ft2-decide  HH:00:15 UTC  python -m ft2 serve decide   fetch closed bars, forecast the grid bar HH:00, write decisions
#   ft2-mark    HH:05:15 UTC  python -m ft2 serve mark     entry mark for HH:00's decisions, exit mark for yesterday's, quotes, funding
#   ft2-check   1st of month 01:30 UTC  python -m ft2 serve check   the harness re-run over the ledger's life, diffed against it
#   ft2-cexlive 06:00:30 UTC daily      python scripts/cexflow_live.py   R96's fetch (PLAN §8 R96): DefiLlama's Binance balance file as fetched,
#               gzipped → data/raw/external/defillama_cex_live/, one row in output/cexflow_live/fetch_log.csv; standard library only
#
# AccuracySec=1s: systemd's default timer accuracy is one minute, which would make every decision late.
# Persistent=true: a run missed while the host was down fires at boot (decide then records the bars as `late`, mark catches up).
set -euo pipefail
U="$(whoami)"
WD="$HOME/fluxtrader2"
PY="$HOME/ft2-venv/bin/python"
[[ -x "$PY" ]] || { echo "no venv at $PY — run vm.sh setup first" >&2; exit 1; }

unit() {   # name  description  action  OnCalendar  timeout-seconds
  sudo tee "/etc/systemd/system/ft2-$1.service" >/dev/null <<EOF
[Unit]
Description=fluxtrader2 serve: $2
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$U
WorkingDirectory=$WD
Environment=PYTHONPATH=$WD PYTHONUNBUFFERED=1
ExecStart=$PY ${6:--m ft2 serve} $3
TimeoutStartSec=$5
Nice=5
EOF
  sudo tee "/etc/systemd/system/ft2-$1.timer" >/dev/null <<EOF
[Unit]
Description=fluxtrader2 serve: $2 (timer)

[Timer]
OnCalendar=$4
AccuracySec=1s
Persistent=true

[Install]
WantedBy=timers.target
EOF
}

unit decide "decide at HH:00:15 UTC"        decide "*-*-* *:00:15"   280
unit mark   "mark at HH:05:15 UTC"          mark   "*-*-* *:05:15"   240
unit check  "monthly causal check"          check  "*-*-01 01:30:00" 3600
unit cexlive "R96 daily balance fetch 06:00:30 UTC" "$WD/scripts/cexflow_live.py" "*-*-* 06:00:30" 400 " "

# ft2-quotes: the all-names quote recorder (PLAN P8 decision CW2) — a long-running service, not a timer: one poll every 30 s on the clock.
# Restart=always: a crash or a reboot resumes at the next half-minute and appends to the day's file. Standard library only.
sudo tee /etc/systemd/system/ft2-quotes.service >/dev/null <<EOF
[Unit]
Description=fluxtrader2 serve: all-names best bid/ask every 30 s (decision CW2)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$U
WorkingDirectory=$WD
Environment=PYTHONUNBUFFERED=1
ExecStart=$PY $WD/scripts/quotes_live.py
Restart=always
RestartSec=5
Nice=10
MemoryMax=150M

[Install]
WantedBy=multi-user.target
EOF

# ft2-liq: the all-names liquidation recorder (PLAN P8 decision CX2) — a long-running service holding one websocket
# (`!forceOrder@arr`). Restart=always: a crash or a reboot reconnects within seconds and appends to the day's file. Standard library only.
sudo tee /etc/systemd/system/ft2-liq.service >/dev/null <<EOF
[Unit]
Description=fluxtrader2 serve: all-names liquidations, live (decision CX2)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$U
WorkingDirectory=$WD
Environment=PYTHONUNBUFFERED=1
ExecStart=$PY $WD/scripts/liq_live.py
Restart=always
RestartSec=5
Nice=10
MemoryMax=100M

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now ft2-decide.timer ft2-mark.timer ft2-check.timer ft2-cexlive.timer
systemctl list-timers 'ft2-*' --no-pager
# restart, not only enable: a code change to quotes_live.py takes effect (the gap is one or two polls)
sudo systemctl enable ft2-quotes.service
sudo systemctl restart ft2-quotes.service
systemctl is-active ft2-quotes.service
sudo systemctl enable ft2-liq.service
sudo systemctl restart ft2-liq.service
systemctl is-active ft2-liq.service
