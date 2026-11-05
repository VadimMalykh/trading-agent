#!/usr/bin/env bash
# Export the forward paper ledger from fluxtrader-1 and run the pre-registered readings.
#
# WHAT: `paper_trades` (both arms, all columns) -> ml/train/output/forward/paper_trades_<UTC date>.csv,
#       then `m3 forward` over it inside the analysis container (M3_5_INTEGRATION.md §4.3).
# WHY:  the readings are subsets of the same trades, fixed before the ledger could suggest them;
#       this script is the "exact command" the registration points at. It changes nothing on
#       the VM — a read-only \copy over docker compose exec.
#
# Usage:  ./scripts/gcp_forward_ledger.sh            # export + read
#         ./scripts/gcp_forward_ledger.sh --no-read  # export only
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$REPO_ROOT/ml/train/output/forward"
STAMP="$(date -u +%Y%m%d)"
OUT="$OUT_DIR/paper_trades_${STAMP}.csv"
mkdir -p "$OUT_DIR"

echo "→ exporting paper_trades from $GCP_ALWAYS_ON …" >&2
gssh "$GCP_ALWAYS_ON" "cd ~/$REMOTE_REPO_NAME && docker compose exec -T postgres \
  psql -U fluxtrader -d fluxtrader -Atc \"\\copy (select * from paper_trades order by id) to stdout with csv header\"" \
  2>/dev/null > "$OUT"

ROWS=$(( $(wc -l < "$OUT") - 1 ))
echo "→ $ROWS rows -> $OUT" >&2
if [[ "$ROWS" -lt 0 || ! -s "$OUT" ]]; then
  echo "ERROR: empty export — is the VM reachable and the app stack up?" >&2
  exit 1
fi

# R5 (M3_5 §4.3) reconstructs a hold-extension counterfactual, which needs every served
# bar's side, confidence and price — `policy_bars`, one row per (pair, closed 5m bar).
BARS="$OUT_DIR/policy_bars_${STAMP}.csv"
echo "→ exporting policy_bars from $GCP_ALWAYS_ON …" >&2
gssh "$GCP_ALWAYS_ON" "cd ~/$REMOTE_REPO_NAME && docker compose exec -T postgres \
  psql -U fluxtrader -d fluxtrader -Atc \"\\copy (select pair, bar_ts, horizon_m, confidence, side, price, gated, regime from policy_bars order by bar_ts, pair) to stdout with csv header\"" \
  2>/dev/null > "$BARS"
echo "→ $(( $(wc -l < "$BARS") - 1 )) bars -> $BARS" >&2

# X23 (BOOK_WAVE2_PLAN §S1): the pair's own book at the decision instant, one row per
# (pair, bar_ts) of policy_bars at horizon 240 — the LAST snapshot at or before the scored
# bar's close, under forward.py's bar-key convention (bar_ts + 5 min from the 2026-10-21
# 15:02:33 UTC clock fix; bar_ts − 5 min before it, when bar_ts was the wall clock floored).
# `age_s` is the snapshot's age at that instant; the reader applies training's 5-minute cap
# and checks every trade's snapshot against the row's inserted_at. Read-only; ~3 s on the VM.
BOOK="$OUT_DIR/book_at_bars_${STAMP}.csv"
echo "→ exporting book_at_bars from $GCP_ALWAYS_ON …" >&2
gssh "$GCP_ALWAYS_ON" "cd ~/$REMOTE_REPO_NAME && docker compose exec -T postgres \
  psql -U fluxtrader -d fluxtrader -Atc \"\\copy (select b.pair, b.bar_ts, s.ts as snap_ts, extract(epoch from (b.bar_ts + (case when b.bar_ts >= timestamp '2026-10-21 15:02:33' then interval '5 minutes' else interval '-5 minutes' end)) - s.ts) as age_s, s.spread / s.mid * 1e4 as spread_bps, s.imbalance, case when coalesce(s.bid_depth_near, 0) + coalesce(s.ask_depth_near, 0) > 0 then (s.bid_depth_near - s.ask_depth_near) / (s.bid_depth_near + s.ask_depth_near) else 0 end as depth_near_imb from policy_bars b cross join lateral (select o.ts, o.mid, o.spread, o.imbalance, o.bid_depth_near, o.ask_depth_near from orderbook_snapshots o where o.symbol = b.pair and o.ts <= b.bar_ts + (case when b.bar_ts >= timestamp '2026-10-21 15:02:33' then interval '5 minutes' else interval '-5 minutes' end) order by o.ts desc limit 1) s where b.horizon_m = 240 order by b.bar_ts, b.pair) to stdout with csv header\"" \
  2>/dev/null > "$BOOK"
echo "→ $(( $(wc -l < "$BOOK") - 1 )) book-at-bar rows -> $BOOK (X23 reads it: m3 bookfilter --stage confirm)" >&2

[[ "${1:-}" == "--no-read" ]] && exit 0
exec "$REPO_ROOT/scripts/m3.sh" -m m3 forward --ledger "output/forward/paper_trades_${STAMP}.csv" \
  --bars "output/forward/policy_bars_${STAMP}.csv"
