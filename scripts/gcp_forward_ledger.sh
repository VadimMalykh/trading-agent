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

[[ "${1:-}" == "--no-read" ]] && exit 0
exec "$REPO_ROOT/scripts/m3.sh" -m m3 forward --ledger "output/forward/paper_trades_${STAMP}.csv" \
  --bars "output/forward/policy_bars_${STAMP}.csv"
