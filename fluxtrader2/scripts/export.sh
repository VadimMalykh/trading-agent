#!/usr/bin/env bash
# fluxtrader2 — export raw market-data tables from the collector VM into fluxtrader2/data/raw/.
#
# This is fluxtrader2's own exporter. It reads the VM's Postgres tables as they are (no
# derived columns, no filtering beyond a time window) so that everything downstream is
# computed here. It is a plain read; it never writes to the VM's database.
#
# Usage (from the repo root):
#   ./fluxtrader2/scripts/export.sh candles_5m                       # full history, all pairs
#   FROM=2026-07-01 ./fluxtrader2/scripts/export.sh snapshots trades funding oi lsr
#   FROM=2026-08-05 TO=2026-08-10 ./fluxtrader2/scripts/export.sh levels   # raw ladder: slow, big
#
# Slices: candles_1m candles_5m candles_15m candles_1h snapshots levels trades funding oi lsr
# Env:    FROM (default 2022-08-01)  TO (default today, exclusive)  OUT (default fluxtrader2/data/raw)
#
# Two modes:
#   DIRECT (preferred, run ON the work VM): FT2_PG_HOST=10.212.0.2 ./export.sh …  — psql connects
#     to the collector's Postgres over the VPC (port 5432 is published on the collector host and
#     default-allow-internal covers 10.128.0.0/9) and `\copy` writes the gz file straight to OUT.
#   SSH CHAIN (from anywhere with gcloud): no FT2_PG_HOST — the mechanics below.
#
# Mechanics (each is a hard-won constraint of the ssh -> docker -> psql chain):
#  * The COPY is written to a gz file INSIDE the postgres container, copied out to the VM
#    host, then scp'd. Streaming through ssh is ~30x slower because Docker proxies stdout.
#  * `\copy` is a psql meta-command and must be one physical line; the query is shipped
#    base64-encoded because quotes do not survive the ssh -> shell -> docker chain.
#  * No ORDER BY on the big tables: sorting forces Postgres to materialise the result.
#    Consumers sort.
#  * Every downloaded file is gzip-tested and checked for at least one data row.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/google-cloud-sdk/bin:$PATH"
GCP_PROJECT="${GCP_PROJECT:-fluxtrader}"
GCP_ZONE="${GCP_ZONE:-me-central1-b}"
VM="${GCP_ALWAYS_ON:-fluxtrader-1}"

FROM="${FROM:-2022-08-01}"
TO="${TO:-$(date -u +%F)}"
OUT="${OUT:-$ROOT/fluxtrader2/data/raw}"
mkdir -p "$OUT"

REMOTE_TMP="/tmp/ft2_export"     # inside the postgres container
HOST_TMP='~/ft2_export'          # on the VM host (/tmp there is a small tmpfs)

query_for() {
  case "$1" in
    candles_1m|candles_5m|candles_15m|candles_1h)
      local iv="${1#candles_}"
      echo "SELECT symbol, interval, open_time, open, high, low, close, volume, close_time FROM candles WHERE interval = '$iv' AND open_time >= '$FROM' AND open_time < '$TO'" ;;
    snapshots)
      echo "SELECT symbol, ts, event_time, mid, spread, microprice, imbalance, bid_volume, ask_volume, bid_depth_near, ask_depth_near, bid_depth_far, ask_depth_far FROM orderbook_snapshots WHERE ts >= '$FROM' AND ts < '$TO'" ;;
    levels)
      echo "SELECT symbol, ts, event_time, transaction_time, last_update_id, depth, bids::text AS bids, asks::text AS asks FROM orderbook_levels WHERE ts >= '$FROM' AND ts < '$TO'" ;;
    trades)
      echo "SELECT symbol, window_start, trade_count, volume, buy_volume, sell_volume, vwap, high, low FROM market_trades WHERE window_start >= '$FROM' AND window_start < '$TO'" ;;
    funding)
      echo "SELECT symbol, ts, event_time, mark_price, index_price, last_funding_rate, next_funding_time FROM funding_rates WHERE ts >= '$FROM' AND ts < '$TO'" ;;
    oi)
      echo "SELECT symbol, ts, event_time, open_interest FROM open_interest WHERE ts >= '$FROM' AND ts < '$TO'" ;;
    lsr)
      echo "SELECT symbol, period, ts, top_long_short_ratio, global_long_short_ratio, taker_buy_sell_ratio, taker_buy_vol, taker_sell_vol FROM long_short_ratios WHERE ts >= '$FROM' AND ts < '$TO'" ;;
    *) echo "unknown slice: $1" >&2; exit 2 ;;
  esac
}

vm() { gcloud compute ssh --zone "$GCP_ZONE" --project "$GCP_PROJECT" "$VM" --quiet -- "$@"; }

export_direct() {
  local name=$1 query; query="$(query_for "$name")"; local dest="$OUT/$name.csv.gz"
  echo "==> $name  [$FROM .. $TO)  direct from $FT2_PG_HOST" >&2
  PGPASSWORD="${FT2_PG_PASSWORD:-secret}" psql -h "$FT2_PG_HOST" -U fluxtrader -d fluxtrader \
    -v ON_ERROR_STOP=1 -q -c "\\copy ($query) TO PROGRAM 'gzip -c > $dest' CSV HEADER"
  gzip -t "$dest" || { echo "ERROR: $dest truncated" >&2; rm -f "$dest"; exit 1; }
  local n; n=$(gzip -dc "$dest" 2>/dev/null | head -2 | wc -l | tr -d ' ' || true)
  [[ "$n" -ge 2 ]] || { echo "ERROR: $name exported no rows" >&2; exit 1; }
  echo "    $(ls -lh "$dest" | awk '{print $5}')  -> $dest" >&2
}

export_slice() {
  if [[ -n "${FT2_PG_HOST:-}" ]]; then export_direct "$1"; return; fi
  local name=$1 query; query="$(query_for "$name")"
  local remote="$REMOTE_TMP/$name.csv.gz" host="$HOST_TMP/$name.csv.gz" dest="$OUT/$name.csv.gz"
  local b64
  b64="$(printf "\\\\copy (%s) TO PROGRAM 'gzip -c > %s' CSV HEADER\n" "$query" "$remote" | base64 | tr -d '\n')"
  echo "==> $name  [$FROM .. $TO)" >&2
  vm "
    set -e
    mkdir -p $HOST_TMP
    echo $b64 | base64 -d > /tmp/ft2_q.sql
    cd ~/trading_agent
    docker compose exec -T postgres mkdir -p $REMOTE_TMP
    docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -v ON_ERROR_STOP=1 -q < /tmp/ft2_q.sql
    docker compose cp postgres:$remote $host
    docker compose exec -T postgres rm -f $remote
    ls -lh $host
  " >&2
  echo "    downloading…" >&2
  gcloud compute scp --zone "$GCP_ZONE" --project "$GCP_PROJECT" --quiet "$VM:${host#\~/}" "$dest"
  if ! gzip -t "$dest" 2>/dev/null; then
    echo "ERROR: $dest is a truncated gzip" >&2; rm -f "$dest"; exit 1
  fi
  local n; n=$(gzip -dc "$dest" 2>/dev/null | head -2 | wc -l | tr -d ' ' || true)
  if [[ "$n" -lt 2 ]]; then echo "ERROR: $name exported no rows" >&2; exit 1; fi
  vm "rm -f $host" >&2
  echo "    $(ls -lh "$dest" | awk '{print $5}')  -> $dest" >&2
}

[[ $# -ge 1 ]] || { echo "usage: $0 <slice>…  (see header)" >&2; exit 2; }
for s in "$@"; do export_slice "$s"; done
echo "==> done" >&2; ls -lh "$OUT"
