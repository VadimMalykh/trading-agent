#!/usr/bin/env bash
# M3-4a / M3-0b — export the book + tape + price slice from the always-on VM.
#
# WHY THIS SCRIPT EXISTS. The raw L2 ladder (`orderbook_levels`) lives only on
# `fluxtrader-1` (AGENTS.md, "Data lives on the always-on VM") and is ~5.3 GB of jsonb.
# M3-4 does not need 100 levels a side; it needs the touch and the few levels behind it
# (docs/M3_4_PROTOCOL.md §2). So the reduction happens IN SQL on the VM and only the
# reduced, gzipped CSV crosses the wire — a ~40x saving over pulling the ladder.
#
# It exports FIVE slices in one pass because M3_PLAN.md §2 M3-4 says to: M3-4 needs the
# book and the tape, M3-0b needs 5m candles and funding, and BOOK_ERA_PLAN B0 needs the
# book columns. One alignment, three consumers.
#
# 🔴 NO `ORDER BY` on the three big tables, and that is not an oversight. Sorting 1.8M ladder
# rows forces Postgres to materialise the whole result before emitting a byte: the first
# attempt spilled 2.4 GB of temp files, ran for the better part of an hour without producing
# output, and did it on the live collector VM. Unsorted, the COPY streams from the first row.
# Every consumer sorts what it needs anyway (`m3 bookprep` sorts before differencing
# timestamps), so the ordering was buying nothing. The two small tables keep theirs.
#
# Three mechanics that are easy to get wrong and cost an hour each:
#   * psql's `\copy` is a META-COMMAND and must be on ONE physical line. The queries below
#     are therefore emitted single-line, however unreadable that makes them.
#   * Single quotes and `$$` are both mangled by the ssh -> remote-shell -> docker-exec
#     chain, so each query is shipped base64-encoded and decoded on the VM.
#   * The COPY must NOT be streamed through ssh. See the comment on `dump()` below — the
#     obvious streaming design runs ~30x slower because of Docker's stdout proxy.
#
# Usage:
#   ./scripts/gcp_m3_export.sh                       # 2026-08-05 .. today, all 12 pairs
#   FROM=2026-08-14 TO=2026-08-28 ./scripts/gcp_m3_export.sh
#   COLLECT=1 ./scripts/gcp_m3_export.sh             # fetch slices already staged on the VM
#
# ⚠️ Killing this script does NOT stop the export. `\copy ... TO PROGRAM` writes to a file
# inside the postgres container, so psql outlives the ssh channel. After an interruption,
# check the VM (`ls -l /tmp/m3_export` inside the container), wait for the file to stop
# growing, and re-run with COLLECT=1 rather than re-issuing hours of COPY.
#
# Runtime: about two hours for the default 23-day, 20-level, 12-pair window (~1.8M ladder
# rows), most of it Postgres detoasting jsonb. It is safe to run against the live collector:
# the COPY is a plain read and the VM's load stayed near 1.
#
# Output: ml/train/output/m3_4/*.csv.gz  (then: ./scripts/m3.sh -m m3 bookprep)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/google-cloud-sdk/bin:$PATH"
: "${GCP_PROJECT:=fluxtrader}"
: "${GCP_ZONE:=me-central1-b}"
: "${GCP_ALWAYS_ON:=fluxtrader-1}"
[[ -f "$ROOT/scripts/gcp_env" ]] && source "$ROOT/scripts/gcp_env"

# The ladder begins 2026-08-05 for the 8 served pairs (M3_PLAN §2 M3-4). Nothing before
# that date has a raw book, so it is the natural left edge for every slice: exporting the
# tape or the candles over a wider window would only create rows the book cannot match.
FROM="${FROM:-2026-08-05}"
TO="${TO:-$(date -u +%F)}"
# 20 levels, not 5. `m3 bookprep`'s audit only needs the touch, but M3_4_PROTOCOL §2.5 walks
# the ladder to price a $10k order's slippage, and five levels cannot hold one on the thin
# pairs — 1000PEPE keeps about $823 at the touch. Depth is nearly free here: the server-side
# cost is detoasting the 100-level jsonb, which happens whatever we project out of it, so a
# deeper export costs wire bytes and not query time. Exporting 5 and then re-exporting 20
# would cost two hours twice.
LEVELS="${LEVELS:-20}"

OUT="${OUT:-$ROOT/ml/train/output/m3_4}"
mkdir -p "$OUT"

# Staging directory, used with the same path inside the postgres container and on the VM.
REMOTE_TMP="/tmp/m3_export"

# --- the ladder projection: bids[0..LEVELS-1] -> b0p,b0q,b1p,b1q,...
book_cols() {
  local side=$1 letter=$2 i out=""
  for ((i = 0; i < LEVELS; i++)); do
    out+="($side->$i->>0)::float8 AS ${letter}${i}p, ($side->$i->>1)::float8 AS ${letter}${i}q, "
  done
  printf '%s' "$out"
}

# 1. The reduced ladder. event_time / transaction_time are the EXCHANGE clocks; they are
#    exported because book staleness (ts - event_time) is a measured quantity in the
#    protocol, not an assumption (M3_4_PROTOCOL §1.3).
Q_book="SELECT symbol, ts, event_time, transaction_time, last_update_id, depth, \
$(book_cols bids b)$(book_cols asks a)\
jsonb_array_length(bids) AS n_bid, jsonb_array_length(asks) AS n_ask \
FROM orderbook_levels WHERE ts >= '$FROM' AND ts < '$TO'"

# 2. Derived scalar features, joined 1:1 to the ladder on (symbol, ts).
Q_snapshots="SELECT symbol, ts, mid, spread, microprice, imbalance, bid_volume, ask_volume, \
bid_depth_near, ask_depth_near, bid_depth_far, ask_depth_far \
FROM orderbook_snapshots WHERE ts >= '$FROM' AND ts < '$TO'"

# 3. The tape. trade_count is exported BECAUSE it is the truncation flag: the collector asks
#    for at most 200 aggTrades per poll, so trade_count = 200 means the window is
#    right-censored and its high/low cover only the TAIL of the interval (M3_4_PROTOCOL
#    §1.2). A fill study that ignores that column is measuring a lie.
Q_trades="SELECT symbol, window_start, trade_count, volume, buy_volume, sell_volume, vwap, high, low \
FROM market_trades WHERE window_start >= '$FROM' AND window_start < '$TO'"

# 4. + 5. M3-0b's side-table: the price path between entry and exit, and the funding term.
Q_candles_5m="SELECT symbol, interval, open_time, open, high, low, close, volume, close_time \
FROM candles WHERE interval = '5m' AND open_time >= '$FROM' AND open_time < '$TO' ORDER BY symbol, open_time"

Q_funding="SELECT symbol, ts, mark_price, index_price, last_funding_rate \
FROM funding_rates WHERE ts >= '$FROM' AND ts < '$TO' ORDER BY symbol, ts"

echo "==> exporting $FROM .. $TO (top-$LEVELS levels a side) from $GCP_ALWAYS_ON" >&2

gcloud compute ssh --zone "$GCP_ZONE" --project "$GCP_PROJECT" "$GCP_ALWAYS_ON" --quiet \
  -- "mkdir -p $REMOTE_TMP" >&2

# 🔴 The export writes a gz file on the VM and then scp's it — it does NOT stream the COPY
# through ssh. The streaming version is the obvious design and it is roughly 30x slower:
# `docker compose exec -T`'s stdout is proxied through the Docker daemon's hijacked HTTP
# stream, and with a wide row that pipe backpressures so hard that Postgres sits in
# `wait_event = ClientWrite` and the whole export moves at ~1.4 MB/min. Measured on the
# 20-level ladder that projected to about nineteen hours. Writing to the container's disk
# first takes the daemon proxy and the ssh channel off the database's critical path, and scp
# then moves the finished file at link speed.
dump() {
  local name=$1 query=$2 dest="$OUT/$1.csv.gz"
  local remote="$REMOTE_TMP/$name.csv.gz"

  # COLLECT=1 skips the COPY and fetches whatever is already staged. This exists because
  # killing this script LOCALLY does not stop the export: `\copy ... TO PROGRAM` writes to a
  # file inside the container, so psql outlives the ssh channel and keeps going. After an
  # interrupted run the right move is to wait for the VM-side file to stop growing and then
  # re-run with COLLECT=1 — re-issuing the COPY would throw away hours of completed work.
  if [[ "${COLLECT:-0}" == "1" ]]; then
    echo "  -> $name (collect only)" >&2
    fetch "$name" "$remote" "$dest"
    return
  fi
  # `\copy ... TO PROGRAM` runs the program on psql's side — inside the postgres container —
  # so it needs no superuser, unlike server-side `COPY ... TO PROGRAM`.
  local b64
  b64="$(printf "\\\\copy (%s) TO PROGRAM 'gzip -c > %s' CSV HEADER\n" "$query" "$remote" \
         | base64 | tr -d '\n')"
  echo "  -> $name" >&2
  gcloud compute ssh --zone "$GCP_ZONE" --project "$GCP_PROJECT" "$GCP_ALWAYS_ON" --quiet -- "
    set -e
    echo $b64 | base64 -d > /tmp/m3_q.sql
    cd ~/trading_agent
    docker compose exec -T postgres mkdir -p $REMOTE_TMP
    docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -v ON_ERROR_STOP=1 -q < /tmp/m3_q.sql
    docker compose cp postgres:$remote $remote
    docker compose exec -T postgres rm -f $remote
    ls -lh $remote
  " >&2

  fetch "$name" "$remote" "$dest"
}

# Pull one finished slice off the VM and check it is neither empty nor truncated.
fetch() {
  local name=$1 remote=$2 dest=$3
  echo "     downloading…" >&2
  gcloud compute scp --zone "$GCP_ZONE" --project "$GCP_PROJECT" --quiet \
    "$GCP_ALWAYS_ON:$remote" "$dest"

  # `gzip -t` is not optional. A COPY interrupted part-way leaves a VALID-LOOKING .gz whose
  # last member is truncated; without this check the next `bookprep` would cache a parquet
  # built from a partial export and every table would be silently wrong.
  if ! gzip -t "$dest" 2>/dev/null; then
    echo "ERROR: $dest is a truncated gzip — the VM-side COPY had not finished." >&2
    echo "       Wait for $remote to stop growing, then re-run with COLLECT=1." >&2
    rm -f "$dest"
    exit 1
  fi

  # A psql error exits non-zero above (set -e), but an EMPTY result is silent and would be
  # discovered only when the study produced no rows. Fail loudly here instead.
  # `head -2` closes the pipe, gzip dies of SIGPIPE (141), and `set -o pipefail` would turn
  # that into a fatal script exit. `|| true` keeps the early close harmless.
  local n
  n=$(gzip -dc "$dest" 2>/dev/null | head -2 | wc -l | tr -d ' ' || true)
  if [[ "$n" -lt 2 ]]; then
    echo "ERROR: $name exported no data rows — check the date window" >&2
    exit 1
  fi

  gcloud compute ssh --zone "$GCP_ZONE" --project "$GCP_PROJECT" "$GCP_ALWAYS_ON" --quiet \
    -- "rm -f $remote" >&2
  echo "     $(ls -lh "$dest" | awk '{print $5}')" >&2
}

# ONLY=a,b restricts the run to named slices. Together with COLLECT=1 this is what makes an
# interrupted export recoverable: collect the long ladder that is already finished on the VM,
# then run the four cheap slices that never started.
#   COLLECT=1 ONLY=book_top20 ./scripts/gcp_m3_export.sh
#   ONLY=snapshots,trades,candles_5m,funding ./scripts/gcp_m3_export.sh
wanted() {
  [[ -z "${ONLY:-}" ]] && return 0
  [[ ",$ONLY," == *",$1,"* ]]
}

for slice in "book_top${LEVELS}" snapshots trades candles_5m funding; do
  wanted "$slice" || continue
  case "$slice" in
    book_top*)  dump "$slice" "$Q_book" ;;
    snapshots)  dump "$slice" "$Q_snapshots" ;;
    trades)     dump "$slice" "$Q_trades" ;;
    candles_5m) dump "$slice" "$Q_candles_5m" ;;
    funding)    dump "$slice" "$Q_funding" ;;
  esac
done

echo "==> done:" >&2
ls -lh "$OUT"
