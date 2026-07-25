#!/usr/bin/env bash

gcloud compute ssh --zone "me-central1-b" "fluxtrader-1" --project "fluxtrader" -- bash -s <<'EOF'
cd ~/trading_agent && docker compose exec postgres psql -U fluxtrader -d fluxtrader -c "SELECT symbol, MIN(ts) AS first_snapshot, MAX(ts) AS last_snapshot, MAX(ts) - MIN(ts) AS duration FROM orderbook_snapshots GROUP BY symbol ORDER BY symbol;"
EOF
