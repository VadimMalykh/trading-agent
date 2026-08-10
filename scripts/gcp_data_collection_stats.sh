#!/usr/bin/env bash
#
# Full data-collection health check for the always-on GCP collector.
# Post-2026-08-05: also verifies the raw L2 ladder table (orderbook_levels)
# and its 1:1 join to orderbook_snapshots. See docs/DATA_COLLECTION_AUDIT.md.
#
# Rule of thumb for "healthy": last-row staleness should be within ~1 poll
# interval (book/trades 5s, funding/OI/candles 60s). Liquidations are expected
# EMPTY (WS blocked from datacenter egress — documented, not a bug).

gcloud compute ssh --zone "me-central1-b" "fluxtrader-1" --project "fluxtrader" -- bash -s <<'EOF'
cd ~/trading_agent && docker compose exec -T postgres psql -U fluxtrader -d fluxtrader <<'SQL'
\echo '=== 1. Order book — scalar snapshots (orderbook_snapshots) ==='
SELECT symbol,
       COUNT(*)            AS rows,
       MIN(ts)            AS first,
       MAX(ts)            AS last,
       now() - MAX(ts)    AS staleness
FROM orderbook_snapshots GROUP BY symbol ORDER BY symbol;

\echo ''
\echo '=== 2. Order book — RAW L2 ladder (orderbook_levels, new 2026-08-05) ==='
\echo '    avg_bid/ask_levels should be ~100; depth=100; staleness ~5s.'
SELECT symbol,
       COUNT(*)                                 AS rows,
       MAX(ts)                                  AS last,
       now() - MAX(ts)                          AS staleness,
       round(AVG(jsonb_array_length(bids)))     AS avg_bid_levels,
       round(AVG(jsonb_array_length(asks)))     AS avg_ask_levels,
       MAX(depth)                               AS depth,
       COUNT(*) FILTER (WHERE last_update_id IS NULL) AS missing_update_id,
       COUNT(*) FILTER (WHERE event_time IS NULL)     AS missing_event_time
FROM orderbook_levels GROUP BY symbol ORDER BY symbol;

\echo ''
\echo '=== 3. Ladder join integrity (scalars_missing_ladder should be ~0) ==='
SELECT
  (SELECT COUNT(*) FROM orderbook_snapshots)  AS scalar_rows,
  (SELECT COUNT(*) FROM orderbook_levels)     AS level_rows,
  (SELECT COUNT(*) FROM orderbook_snapshots s
     LEFT JOIN orderbook_levels l USING (symbol, ts)
     WHERE l.ts IS NULL)                      AS scalars_missing_ladder;

\echo ''
\echo '=== 4. Trades (market_trades) ==='
SELECT symbol,
       COUNT(*)                     AS rows,
       MAX(window_start)            AS last,
       now() - MAX(window_start)    AS staleness
FROM market_trades GROUP BY symbol ORDER BY symbol;

\echo ''
\echo '=== 5. Candles (candles) ==='
SELECT symbol, interval,
       COUNT(*)                  AS rows,
       MAX(open_time)            AS last,
       now() - MAX(open_time)    AS staleness
FROM candles GROUP BY symbol, interval ORDER BY symbol, interval;

\echo ''
\echo '=== 6. Funding / mark (funding_rates) ==='
SELECT symbol,
       COUNT(*)            AS rows,
       MAX(ts)            AS last,
       now() - MAX(ts)    AS staleness
FROM funding_rates GROUP BY symbol ORDER BY symbol;

\echo ''
\echo '=== 7. Open interest (open_interest) ==='
SELECT symbol,
       COUNT(*)            AS rows,
       MAX(ts)            AS last,
       now() - MAX(ts)    AS staleness
FROM open_interest GROUP BY symbol ORDER BY symbol;

\echo ''
\echo '=== 8. Liquidations (liquidations) — EXPECTED EMPTY (WS egress blocked) ==='
SELECT COUNT(*) AS rows, MAX(ts) AS last FROM liquidations;
SQL
EOF
