#!/usr/bin/env bash
# Runs ON the fluxtrader2 work VM (Debian 12). Idempotent — this is also the reinstall runbook:
# on a fresh instance, `vm.sh setup` copies this file + requirements.txt up and runs it.
#
# What it installs and why:
#   python3-venv, python3-dev, build-essential  — a plain venv at ~/ft2-venv (no Docker on the VM)
#   postgresql-client                            — psql for the VM-to-VM data export (export.sh)
#   rsync, gzip, tmux, htop                      — code sync, archives, long jobs, looking at them
#   libgomp1                                     — LightGBM's OpenMP runtime
set -euo pipefail
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3-venv python3-dev build-essential postgresql-client rsync gzip tmux htop libgomp1 unzip curl
[[ -d ~/ft2-venv ]] || python3 -m venv ~/ft2-venv
~/ft2-venv/bin/pip install --quiet --upgrade pip
~/ft2-venv/bin/pip install --quiet -r ~/requirements.txt
mkdir -p ~/fluxtrader2/data/raw ~/fluxtrader2/output
~/ft2-venv/bin/python -c "import numpy, pandas, pyarrow, scipy, sklearn, statsmodels, lightgbm; print('ft2 venv ok')"
