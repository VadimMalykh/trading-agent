#!/usr/bin/env bash
# fluxtrader2 — export the raw ladder (orderbook_levels) day by day, resumably, ON the work VM.
#   scripts/export_levels_days.sh 2026-08-05 2026-09-14      # [from, to) UTC days
# Each day lands in data/raw/levels/<day>/levels.csv.gz (a day already there is skipped), so an
# interrupted run (the VM powering off, a lost connection) loses at most one day. `ft2 ingest
# levels` reads the per-day parts when the single-file data/raw/levels.csv.gz is absent.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
d="$1"; end="$2"
while [[ "$d" < "$end" ]]; do
  next=$(date -u -d "$d + 1 day" +%F)
  if [[ -f "data/raw/levels/$d/levels.csv.gz" ]]; then echo "skip $d"; else
    FROM="$d" TO="$next" OUT="data/raw/levels/$d" FT2_PG_HOST="${FT2_PG_HOST:-10.212.0.2}" bash scripts/export.sh levels \
      || echo "FAILED $d (re-run to retry)"
  fi
  d="$next"
done
echo "levels-days-done $(date -u)"
