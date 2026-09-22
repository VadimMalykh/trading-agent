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
**P0b (2026-09-15)** added the public archive from 2023-01-01: `metrics` 4,322,018 · `depth`
42,277,682 · `funding_archive` 73,251 rows (section "External data" below; archive files end
2026-09-13, the archive lags two days).

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

#### ladder (derived from `orderbook_levels`; `ft2 ingest levels`, P1) — `data/ladder/<symbol>.parquet`, one row per snapshot

The windowed export `FROM=2026-08-05 TO=2026-09-14 export.sh levels` (raw `levels.csv.gz`,
kept) reduced per snapshot to: the touch (`best_bid`, `best_ask`, `mid`, `spread_bps`), the
levels present and how far from mid the last one sits (`n_bid`, `n_ask`, `*_extent_bps`), the
notional resting within 0.2 % and 1 % of mid on each side (`usd_bid_02` … `usd_ask_1`, the same
bands as the archive `depth` table, for scaling impact back in time), and `slip_buy_<N>` /
`slip_sell_<N>`: the fill VWAP of a market order of N USDT versus mid in bps for
N ∈ {1k, 2.5k, 5k, 10k, 25k, 50k, 100k, 250k}, NaN when the ladder held less than N on that side
(censored, never extrapolated). Column semantics in `ft2/ladder.py`. Cadence measured on
2026-09-13: 7,006 rows per pair-day (≈ 12 s), not the ~5 s the collector aims for.

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

Coverage measured 2026-09-15 (PLAN §9 #1). **P0b (2026-09-15) fetched and ingested** three
kinds for all twelve pairs from 2023-01-01 (from listing for the younger pairs); each raw file
keeps its archive name and a verified sha256 next to it (`.ok`), and `ft2 archive` is resumable
(the first run died on one connection reset; the fetcher now retries and continues). The first
run's log claimed "fetched for all pairs" while only three pairs of `metrics` had landed —
this table is what was measured after the re-run, by `ft2 inventory`.

### metrics (archive, 5m) — `data/metrics.parquet`: `(symbol, ts) → oi, oi_value, top_ls_count, top_ls_sum, global_ls, taker_ratio`

Open interest (contracts and USDT), top-trader long/short ratios (by accounts and by positions),
global long/short ratio, taker buy/sell volume ratio, one row per 5 minutes. Replaces the
collector's two-month `oi` and `lsr` tables for anything historical.

### depth (archive `bookDepth`, ~30 s) — `data/depth/<symbol>.parquet`: `(symbol, ts) → qty_m5..qty_m1, qty_m02, qty_p02, qty_p1..qty_p5, usd_*` (same 12 levels)

**What it is:** the cumulative quantity (`qty_*`, base units) and USDT notional (`usd_*`)
resting within ±1, ±2, ±3, ±4, ±5 % of the mid, bid side (`m`) and ask side (`p`), sampled
about every 30 s (2,880 rows/day; the archive's own description says 1-minute). **From
2026-01-15 the archive also carries ±0.2 % bands** (`*_m02`, `*_p02`; NaN before that date) —
much closer to the touch, and the level P1 should use for impact scaling where it exists.
**What it is not:** best bid/ask. There is no spread in this data — PLAN §9 originally assumed `bookDepth`
covered the discontinued `bookTicker`, and it does not. The historical spread comes from the
tape (below). The ±1 % band on BTC holds tens of millions of USDT, so this is a *liquidity
regime* measure and a scale for impact, not an impact measurement at the notionals we trade.

### funding_archive (archive monthly `fundingRate`) — `data/funding_archive.parquet`: `(symbol, ts) → rate, interval_h`

The settled funding rate per funding time, from each pair's listing (BTC/ETH 2020-01). Cross-
check against the collector's `funding_rates` at the same funding timestamp: **100 % identical
rates** on every overlapping row (see the table). `interval_h` is 8 on the majors; SOL and
others carry 4 h and 2 h intervals in some periods — a cost input P1 must not assume constant.

### tape (archive `aggTrades`, streamed by `ft2 tape` in P1) — `data/tape/<symbol>.parquet`, one row per minute

The raw tape is **~136 GB zipped** for twelve pairs from 2023-01 (measured 2026-09-15 from the
archive listing: BTC 14–27 MB/day, PEPE up to 45 MB/day in 2024-03) and does not fit the work VM
next to everything else, so it is never kept: each daily file is fetched, reduced to one row per
minute, and deleted. Columns: trade counts and volumes by aggressor side, notional, vwap/OHLC of
trade prices, `ask_last`/`bid_last` (last taker-buy and last taker-sell price: the touch as the
last trade on each side saw it), and `eff_spread_bps` — the mean realised bid–ask bounce
|Δprice|/mid over consecutive trades with opposite aggressors, in bps. Spot check on three
sample days (2026-09-15): BTC 2023-01-02 bounce 0.06 bps = exactly one 0.1 tick at 16,610;
ZEC 2023-06-01 2.6 bps (tick 0.01 at 32); ZEC 2026-08-01 0.2 bps. It is a *lower-ish* bound of
the effective spread (flips at the same price count as zero) and is validated against the
collector's quoted spread in their overlap in P1.

### Archive tables as measured (`ft2 inventory`, 2026-09-15)

| table | pairs | window (UTC) | rows | integrity (`output/inventory.md` has the per-pair tables) |
|---|---|---|---|---|
| `metrics` (5m) | 12 (from listing: PEPE 2023-05-05, WLD 2023-07-24, HYPE 2025-05-30) | 2023-01-01 → 2026-09-13 | 4,322,018 | 2 duplicate keys dropped; cadence exactly 5 min; 4–6 gaps > 10 min per pair, the largest 10.5 h and common to every pair (an archive outage, not ours; AVAX has 15); WLD and ZEC each miss one whole day |
| `depth` (30 s) | 12 (same starts) | 2023-01-01 → 2026-09-13 | 42,277,682 (from 438.8M long rows) | 0 duplicates; **0 rows missing a core ±1–5 % level**; 2,880 rows/day median on every pair; ±0.2 % bands on 668,748 rows per pair from **2026-01-15**; 2–5 whole days missing per long pair inside one common ~3-day archive hole (largest gap 2 d 22 h), plus ~11 short (> 60 s) gaps per day |
| `funding_archive` | 12 | listing → 2026-08-31 (BTC/ETH from 2020-01-01) | 73,251 | 0 duplicates; vs the collector's `funding_rates` at the same funding timestamp: **99.94–100 % identical rates** on 2,706–4,469 overlapping rows per pair; `interval_h` is 8 on ten pairs, **4 on HYPE, and 2/4/8 on SOL** in different periods |
| `tape` (1 min, P1) | 12 (PEPE 2023-05-05, WLD 2023-07-24, HYPE 2025-05-30) | 2023-01-01 → 2026-09-13 | 21,616,106 | streamed 2026-09-15 04:35–07:14 UTC, 0 fetch errors; **0 days missing on every pair**; 3 quiet runs > 2 min per pair, the largest 20 min and common to all (an exchange pause), ZEC 221 (thin book); per-day parts kept, raw zips not |
| `candles_5m_archive` (archive `klines/5m`, P5) | 9 (BTC, ETH 2019-12-31; XRP 2020-01-06, LINK 01-17, ADA 01-31, ZEC 02-05; DOGE 2020-07-10, SOL 09-14, AVAX 09-23) | 2019-12-31 → 2022-08-18 | 2,258,984 | fetched 2026-09-21, 7,846 daily files, 0 errors, checksums verified; 0 duplicates; interior gaps: XRP 2 (largest 3 d), ZEC 1 (1 d), none elsewhere; **on the 830 bars it shares with the collector (2022-08-18) close, high, low and volume are identical** — `ceiling.panel(start < F0)` puts it under the collector's bars. Costs for these days: `ft2 costpre` → `data/cost_daily_pre.parquet`, `output/cost_pre.md` (spread = P1's candle regression floored at the pair's 2023 median; impact = the 90 % quantile of the pair's 2023 days; no maker fill statistics). Plausible where it can be checked against tick sizes (DOGE 2020 ≈ 24 bps at $0.003), but it is an extrapolation: reads on these days report spread + impact doubled alongside |
| `candles_5m_archive` — **the wider universe** (R10, 2026-09-22) | +32 pairs (`ft2/universe.py::NEW`: the 40 of `ft2 universe` minus the 8 the collector records) | 2022-04-01 → 2024-08-31 (monthly archive files, `ft2 archive klines/5m --monthly`) | 10,398,440 in the slice (was 2,258,984) | 254,016–254,592 rows per pair, **0 gaps > 10 min, 140,832 bars each inside F1+F2** (output/r10_klines_check.md); WAVES delisted 2024-06-11 and simply ends. `funding_archive` gained the same 32 (277,639 rows). No tape, ladder or depth for them: their cost is `ft2 costwide`'s pooled candle proxy (output/cost_wide.md) — spread validated leave-one-pair-out on the twelve (median ratio 0.89–1.52, worst ZEC), **impact at 10k is NOT: ×0.25 on PEPE, ×5–6 on SOL and ZEC** (the thin-pair regime the 8 thinnest new pairs sit in), so the proxy over-prices thin names and every R10 read carries a `--cost-mult 2` twin. The FP pre-history (2020 → 2022-04) is not fetched for them until R10's gate passes |
| `ladder` (collector `orderbook_levels`, ~12 s, P1) | 12 | 2026-08-05 (ADA/AVAX/LINK/XRP 08-14) → 2026-09-13 | 3,388,622 | 40 per-day raw exports (3.5 GB gz, kept); 0 duplicates; the 100 levels reach only 1.7 bps from mid on BTC (4 on ETH, 13 on ZEC/HYPE) versus 70–480 bps on the thin pairs, so BTC/ETH ladders hold ~1–3 % of the archive's ±1 % notional and the archive band is what scales impact back in time |

## Folds (fixed 2026-09-15; `ft2/folds.py` is the code, this is the record)

| fold | window (UTC, end exclusive) | role | pairs present |
|---|---|---|---|
| FP | 2020-05-01 → 2022-08-18 | **pre-history** (added 2026-09-21, archive klines): starts 120 days after the archive so that a 120-day window is full; read once per registered question, like a confirmation fold — the first honest read for a label-free rule found on F1+F2 | 6 (BTC, ETH, XRP, LINK, ADA, ZEC) → 9 from 2020-09 |
| F0 | 2022-08-18 → 2023-05-01 | **warm-up**: training history for anything fitted, never scored by it; for a label-free rule it is read together with FP (`folds.PREHISTORY`) | 9 long pairs |
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
