# fluxtrader2 — the data

Everything this project has. Measured, not assumed. **P0 ran 2026-09-15**: every table below
was exported to the work VM, ingested to parquet and checked by `ft2 inventory`; the full report
is `fluxtrader2/output/inventory.md` (regenerate with `vm.sh run inventory`). Summary of the
checks:

| check | result |
|---|---|
| duplicate keys, any table | 0 |
| interior gaps, candles 1m/5m/15m/1h, all pairs | 0 |
| 5m bars vs their five 1m bars (OHLCV equality) | consistent; only two symbol-months above 0.1% mismatch (ZEC 2024-05 at 0.10%, ZEC 2025-08 at 0.12%) — no partial-bar problem |
| book snapshots: local clock minus exchange clock (from 2026-08-24) | p50 ≈ 160 ms, p95 ≈ 320–360 ms on every pair — irrelevant at ≥ 5m horizons |
| tape windows at the poller cap (1000 trades, right-censored) | ≤ 0.5% on ten pairs, 1.8% on ZEC — P1 excludes or flags them |

Row counts after ingest: candles 1m 23,391,935 · 5m 4,678,346 · 15m 1,559,443 · 1h 389,860;
snapshots 4,575,460; trades 3,847,849; funding 702,209; oi 653,883; lsr 175,905.
Everything ends 2026-09-14 23:59 UTC (the export window is end-exclusive on the run date).

## Where it lives and how it gets here

- **Source:** the always-on collector VM `fluxtrader-1` (GCP, project `fluxtrader`, zone
  `me-central1-b`), Postgres database `fluxtrader`. It collects Binance USDⓈ-M perpetual
  futures data for twelve pairs, continuously. This project only reads it.
- **Export:** `./fluxtrader2/scripts/export.sh <slice>…` writes `fluxtrader2/data/raw/<slice>.csv.gz`.
  Windows via `FROM=`/`TO=`. Slices: `candles_1m candles_5m candles_15m candles_1h snapshots
  levels trades funding oi lsr`.
- **Processed:** `fluxtrader2/data/*.parquet`, produced by `ft2 ingest` (P0) from the raw files.
  Raw files are kept so that a parquet can always be rebuilt.
- **Nothing in `data/` is committed.**

## Pairs

BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, ADAUSDT, AVAXUSDT, LINKUSDT, DOGEUSDT, ZECUSDT,
1000PEPEUSDT, WLDUSDT, HYPEUSDT.

## Tables

### candles — `(symbol, interval, open_time) → open, high, low, close, volume, close_time`

Intervals 1m, 5m, 15m, 1h. This is the long history and the backbone of every phase.

| pair | first candle | 5m rows | 1m rows |
|---|---|---|---|
| BTC, ETH, SOL, XRP, ADA, AVAX, LINK, DOGE, ZEC | 2022-08-18 | ~428,650 each | ~2,143,300 each |
| 1000PEPE | 2023-05-05 | 353,781 | 1,768,904 |
| WLD | 2023-07-24 | 330,795 | 1,653,974 |
| HYPE | 2025-05-30 | 136,125 | 680,624 |

Last candle: current (staleness minutes). 15m and 1h are one-third and one-twelfth of the 5m
counts. The VM-side inventory on 2026-09-15 reports **zero interior gaps** on every pair and
interval; `ft2 inventory` re-measures that from the parquet and adds the 5m-vs-1m consistency
check (a partial-bar check), which the VM query cannot do.

### orderbook_snapshots — `(symbol, ts) → mid, spread, microprice, imbalance, bid/ask volume, near/far depth`

Scalar summaries of the top of book, roughly every 5 s. `event_time` (the exchange clock) is
present from 2026-08-24; before that only the local receipt time `ts` exists.

| pairs | first snapshot |
|---|---|
| BTC, ETH, SOL | 2026-07-17 |
| DOGE, HYPE, WLD | 2026-07-21 |
| ZEC | 2026-07-25 |
| 1000PEPE | 2026-07-27 |
| ADA, AVAX, LINK, XRP | 2026-08-14 |

Rows: 235k–479k per pair as of 2026-09-15.

### orderbook_levels — `(symbol, ts) → bids, asks (jsonb, up to 100 levels), depth, event_time, transaction_time, last_update_id`

The raw ladder, ~5 s cadence. First row **2026-08-05 03:41** for BTC, ETH, SOL, DOGE, HYPE, WLD,
ZEC, 1000PEPE and **2026-08-14 03:12** for ADA, AVAX, LINK, XRP; 235k–320k rows per pair on
2026-09-15. Large (several GB of jsonb on the VM); export it windowed and only when a phase needs
the ladder (P1's impact walk does).

### market_trades — `(symbol, window_start) → trade_count, volume, buy_volume, sell_volume, vwap, high, low`

Aggregated tape per ~5 s polling window. First window 2026-07-17 21:13 (BTC, ETH, SOL),
07-21 (DOGE, HYPE, WLD), 07-25 (ZEC), 07-27 (1000PEPE), 08-14 (ADA, AVAX, LINK, XRP);
174k–419k rows per pair. `trade_count` is a truncation flag: the poller asks for a bounded
number of trades per window, so a window at the cap is right-censored. P1 must respect that;
`ft2 inventory` reports the share of windows at the cap.

### funding_rates — `(symbol, ts) → mark_price, index_price, last_funding_rate, next_funding_time`

**Long history:** rows from **2022-08-19** for the nine long pairs (2023-05 PEPE, 2023-07 WLD,
2025-05 HYPE), 40k–71k rows per pair — sparse (funding-interval) before the book era, per
minute since. Exported over the full history in P0 (`funding.csv.gz`, 2022-08-19 →).

### open_interest — `(symbol, ts) → open_interest`

Per minute, book era only: from 2026-07-17 (BTC, ETH, SOL) through 08-14 (ADA, AVAX, LINK,
XRP), 36k–67k rows per pair.

### long_short_ratios — `(symbol, period, ts) → top_long_short_ratio, global_long_short_ratio, taker_buy_sell_ratio, taker_buy_vol, taker_sell_vol`

The exchange's 5m buckets, all twelve pairs from **2026-07-26**, ~14.7k rows each (the exchange
serves ~30 days; the collector keeps what it saw).

### liquidations — empty by design (the stream is not reachable from the VM). Ignore.

## External data — Binance public archive (`ft2 archive`, `data/raw/external/binance/`)

Coverage measured 2026-09-15 (PLAN §9 #1 has the full list). Being fetched in P0 for all
twelve pairs from 2023-01-01: `bookDepth` (1-minute depth at ± price levels), `metrics` (5m open
interest, long/short and taker ratios) and monthly `fundingRate`. The tape (`aggTrades`,
~5 MB/day for BTC) waits for P1. Each file keeps its archive name and a verified sha256; the
parquet ingestion of these lands in P0b with its own rows in this table.

| kind | pairs | window fetched | rows / integrity |
|---|---|---|---|
| *(filled when the fetch finishes)* | | | |

## Folds (fixed 2026-09-15; `ft2/folds.py` is the code, this is the record)

| fold | window (UTC, end exclusive) | role | pairs present |
|---|---|---|---|
| F0 | 2022-08-18 → 2023-05-01 | **warm-up**: training history only, never scored | 9 long pairs |
| F1 | 2023-05-01 → 2024-01-01 | **exploration** | + 1000PEPE (05-05), WLD (07-24) |
| F2 | 2024-01-01 → 2024-09-01 | **exploration** | 11 |
| F3 | 2024-09-01 → 2025-05-01 | **confirmation** | 11 |
| F4 | 2025-05-01 → 2026-01-01 | **confirmation** | + HYPE (05-30) = 12 |
| F5 | 2026-01-01 → 2026-09-15 | **confirmation** (frozen at its first registered read) | 12 |

Embargo: 2 days removed from the start of every scored fold (longer than the 1-day horizon plus
any feature lookback). Walk-forward rule: a model scored on a fold is fitted only on data before
that fold's start. Exploration reads F1+F2; confirmation folds are read once per registered
question (PLAN §3, §8). The book-era tables (2026-07 onward) fall entirely inside F5.

## Known caveats to verify in P0, not to assume

- Three pairs are shorter than the others (table above); cross-sectional targets need a
  rule for a missing pair.
- Two clocks exist in the book-era tables (local `ts`, exchange `event_time`); the difference
  is the collection jitter and matters below ~1m horizons.
- Candles are polled, not streamed; P0's partial-bar check is what decides whether any 5m
  window has bars that were written before the candle closed.
