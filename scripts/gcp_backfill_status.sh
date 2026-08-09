#!/usr/bin/env bash
# Status of the historic data backfill running on the always-on VM (fluxtrader-1).
#
# Prints whether the remote tmux session 'fluxbackfill' is alive, the last N log
# lines, and current candle/funding row counts per pair so you can see progress.
#
#   ./scripts/gcp_backfill_status.sh            # tail 40 lines
#   ./scripts/gcp_backfill_status.sh --tail 5   # custom tail length
set -euo pipefail
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/gcp_common.sh"
require_gcloud

TAIL="40"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tail) TAIL="$2"; shift 2 ;;
    --*) echo "ERROR: unknown flag '$1'"; exit 1 ;;
    *) echo "ERROR: unexpected arg '$1'"; exit 1 ;;
  esac
done

echo "==> $GCP_ALWAYS_ON (zone=$GCP_ZONE)"

RUNNING="$(gssh "$GCP_ALWAYS_ON" \
  "tmux has-session -t fluxbackfill 2>/dev/null && echo yes || echo no" "$GCP_ZONE" \
  | tr -d '[:space:]' || echo no)"

if [[ "$RUNNING" == "yes" ]]; then
  echo "tmux 'fluxbackfill': RUNNING"
  echo "live view:  gcloud compute ssh $GCP_ALWAYS_ON --zone=$GCP_ZONE --project=$GCP_PROJECT -- tmux attach -t fluxbackfill"
  echo "            (detach without stopping: Ctrl-b then d)"
else
  echo "tmux 'fluxbackfill': not running (finished, failed, or never started)"
fi

echo ""
echo "==> last $TAIL log lines (~/backfill.log):"
gssh "$GCP_ALWAYS_ON" "tail -n $TAIL \$HOME/backfill.log 2>/dev/null || echo '(no log yet)'" "$GCP_ZONE"

echo ""
echo "==> candles per pair/interval:"
gssh "$GCP_ALWAYS_ON" "cd \$HOME/$REMOTE_REPO_NAME && docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -c \"
  SELECT symbol, interval, min(open_time)::date AS since, max(open_time)::date AS until, count(*) AS rows
  FROM candles
  WHERE interval IN ('1m','15m','1h')
  GROUP BY 1,2 ORDER BY 2,1;\"" "$GCP_ZONE" 2>/dev/null || true

echo ""
echo "==> funding per pair:"
gssh "$GCP_ALWAYS_ON" "cd \$HOME/$REMOTE_REPO_NAME && docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -c \"
  SELECT symbol, min(ts)::date AS since, max(ts)::date AS until, count(*) AS rows
  FROM funding_rates GROUP BY 1 ORDER BY 1;\"" "$GCP_ZONE" 2>/dev/null || true
