#!/usr/bin/env bash
#
# Full data-collection health check for the always-on GCP collector.
# Post-2026-08-05: also verifies the raw L2 ladder table (orderbook_levels)
# and its 1:1 join to orderbook_snapshots. See docs/DATA_COLLECTION_AUDIT.md.
#
# Every time-series section reports:
#   rows | first | last | ... | existence | staleness
# where existence = last - first in human-readable form (mo/d/h/m) and
# staleness = now() - last. Staleness/existence are kept as the last two
# columns.
#
# Rule of thumb for "healthy": last-row staleness should be within ~1 poll
# interval (book/trades 5s, funding/OI/candles 60s). Liquidations are expected
# EMPTY (WS blocked from datacenter egress — documented, not a bug).

gcloud compute ssh --zone "me-central1-b" "fluxtrader-1" --project "fluxtrader" -- bash -s <<'EOF'
cd ~/trading_agent && docker compose exec -T postgres psql -U fluxtrader -d fluxtrader <<'SQL'
CREATE OR REPLACE FUNCTION pg_temp.human_span(ts_a timestamp, ts_b timestamp)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT COALESCE(NULLIF(array_to_string(ARRAY[
           NULLIF(CASE WHEN t.years > 0 THEN t.years || 'y' END, ''),
           NULLIF(CASE WHEN t.mons  > 0 THEN t.mons  || 'mo' END, ''),
           NULLIF(CASE WHEN t.days  > 0 THEN t.days  || 'd'  END, ''),
           NULLIF(CASE WHEN t.hours > 0 THEN t.hours || 'h'  END, ''),
           NULLIF(CASE WHEN t.mins  > 0 THEN t.mins  || 'm'  END, '')
         ], ' '), ''), '0m')
  FROM (SELECT
          EXTRACT(YEAR   FROM age(ts_b, ts_a))::int AS years,
          EXTRACT(MONTH  FROM age(ts_b, ts_a))::int AS mons,
          EXTRACT(DAY    FROM age(ts_b, ts_a))::int AS days,
          EXTRACT(HOUR   FROM age(ts_b, ts_a))::int AS hours,
          EXTRACT(MINUTE FROM age(ts_b, ts_a))::int AS mins) t
$$;

\echo '=== 1. Candles (candles) ==='
SELECT symbol, interval,
       COUNT(*)                        AS rows,
       MIN(open_time)                  AS first,
       MAX(open_time)                  AS last,
       pg_temp.human_span(MIN(open_time), MAX(open_time)) AS existence,
       now() - MAX(open_time)          AS staleness
FROM candles GROUP BY symbol, interval ORDER BY symbol, interval;

\echo ''
\echo '=== 2. Order book — scalar snapshots (orderbook_snapshots) ==='
SELECT symbol,
       COUNT(*)            AS rows,
       MIN(ts)             AS first,
       MAX(ts)             AS last,
       pg_temp.human_span(MIN(ts), MAX(ts)) AS existence,
       now() - MAX(ts)     AS staleness
FROM orderbook_snapshots GROUP BY symbol ORDER BY symbol;

\echo ''
\echo '=== 3. Order book — RAW L2 ladder (orderbook_levels, new 2026-08-05) ==='
\echo '    avg_bid/ask_levels should be ~100; depth=100; staleness ~5s.'
SELECT symbol,
       COUNT(*)                                 AS rows,
       MIN(ts)                                  AS first,
       MAX(ts)                                  AS last,
       round(AVG(jsonb_array_length(bids)))     AS avg_bid_levels,
       round(AVG(jsonb_array_length(asks)))     AS avg_ask_levels,
       MAX(depth)                               AS depth,
       COUNT(*) FILTER (WHERE last_update_id IS NULL) AS missing_update_id,
       COUNT(*) FILTER (WHERE event_time IS NULL)     AS missing_event_time,
       pg_temp.human_span(MIN(ts), MAX(ts))      AS existence,
       now() - MAX(ts)                          AS staleness
FROM orderbook_levels GROUP BY symbol ORDER BY symbol;

\echo ''
\echo '=== 4. Ladder join integrity (scalars_missing_ladder should be ~0) ==='
SELECT
  (SELECT COUNT(*) FROM orderbook_snapshots)  AS scalar_rows,
  (SELECT COUNT(*) FROM orderbook_levels)     AS level_rows,
  (SELECT COUNT(*) FROM orderbook_snapshots s
     LEFT JOIN orderbook_levels l USING (symbol, ts)
     WHERE l.ts IS NULL)                      AS scalars_missing_ladder;

\echo ''
\echo '=== 5. Trades (market_trades) ==='
SELECT symbol,
       COUNT(*)                        AS rows,
       MIN(window_start)               AS first,
       MAX(window_start)               AS last,
       pg_temp.human_span(MIN(window_start), MAX(window_start)) AS existence,
       now() - MAX(window_start)       AS staleness
FROM market_trades GROUP BY symbol ORDER BY symbol;

\echo ''
\echo '=== 6. Funding / mark (funding_rates) ==='
SELECT symbol,
       COUNT(*)            AS rows,
       MIN(ts)             AS first,
       MAX(ts)             AS last,
       pg_temp.human_span(MIN(ts), MAX(ts)) AS existence,
       now() - MAX(ts)     AS staleness
FROM funding_rates GROUP BY symbol ORDER BY symbol;

\echo ''
\echo '=== 7. Open interest (open_interest) ==='
SELECT symbol,
       COUNT(*)            AS rows,
       MIN(ts)             AS first,
       MAX(ts)             AS last,
       pg_temp.human_span(MIN(ts), MAX(ts)) AS existence,
       now() - MAX(ts)     AS staleness
FROM open_interest GROUP BY symbol ORDER BY symbol;

\echo ''
\echo '=== 8. Liquidations (liquidations) — EXPECTED EMPTY (WS egress blocked) ==='
SELECT COUNT(*) AS rows,
       MIN(ts)  AS first,
       MAX(ts)  AS last,
       pg_temp.human_span(MIN(ts), MAX(ts)) AS existence,
       now() - MAX(ts) AS staleness
FROM liquidations;

\echo ''
\echo '=== 9. Candles — INTERIOR gaps (missed rows strictly between first/last) ==='
\echo '    gaps>0 means rows are missing INSIDE min..max — a backfill re-run will NOT fix those'
\echo '    (it only fills older-than-first + tail). Tails past the last row are NOT flagged here;'
\echo '    those are repaired by re-running gcp_backfill.sh. missing_hours = total missing span.'
WITH step_sec AS (
  SELECT symbol, interval, open_time,
         CASE interval
           WHEN '1m'  THEN 60
           WHEN '5m'  THEN 300
           WHEN '15m' THEN 900
           WHEN '1h'  THEN 3600
           WHEN '4h'  THEN 14400
         END AS step
  FROM candles
), diffs AS (
  SELECT symbol, interval, step, open_time AS gap_after,
         lead(open_time) OVER (
           PARTITION BY symbol, interval ORDER BY open_time
         ) AS nxt
  FROM step_sec
  WHERE step IS NOT NULL
)
SELECT symbol,
       interval,
       COUNT(*) FILTER (
         WHERE nxt IS NOT NULL AND nxt - gap_after > make_interval(secs => step)
       ) AS gaps,
       COALESCE(SUM(
         CASE WHEN nxt IS NOT NULL AND nxt - gap_after > make_interval(secs => step)
              THEN (EXTRACT(EPOCH FROM nxt - gap_after) - step) / 3600.0
         END
       ), 0)::bigint AS missing_hours
FROM diffs
GROUP BY symbol, interval
ORDER BY symbol, interval;
SQL
EOF