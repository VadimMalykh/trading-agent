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

The public archive (decision CD's probe, 2026-11-04, from the work VM): **no liquidation file for USDT-margined contracts** (`futures/um/daily/` holds aggTrades, bookDepth, bookTicker, indexPriceKlines, klines, markPriceKlines, metrics, premiumIndexKlines, trades — AI5 verified; two direct `liquidationSnapshot` files 404); **a coin-margined one exists** — `futures/cm/daily/liquidationSnapshot/<SYMBOL>/`, 45 `…USD_PERP` names (the large coins) plus the quarterlies, daily zips 2023-06-25 → 2024-10-14 (BTCUSD_PERP 472 files), one row an order: `time, side, order_type, time_in_force, original_quantity, price, average_price, order_status, last_fill_quantity, accumulated_fill_quantity`. Not fetched (F1+F2 and six weeks of F3 only; decision CD).

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

**Where it begins (listed 2026-09-29, file names only, 46 names — the twelve's nine old ones and
37 others): 2021-12-01 for every name listed before that day, from the listing day for a later
one; BTCUSDT alone goes back to 2020-09-01.** The exchange's own API keeps 30 days. So no open
interest, long/short or taker ratio exists for a name outside BTC before 2021-12-01.

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

### index_1m (HistData.com, 1 min; P8 B3) — `data/index_1m.parquet`: `(symbol, ts) → open, high, low, close`

The US stock index as a round-the-clock CFD, one-minute bid bars: `US500` (HistData's SPXUSD) and `US100` (NSXUSD), from
HistData.com's free yearly / monthly zips (`ft2 index fetch|ingest|inventory`, `ft2/index.py`; raw under
`data/raw/external/histdata/`). **The site calls the clock "EST without daylight saving"; it is not** — measured 2026-10-01
against Dukascopy's minutes, it is UTC−4 from the last Sunday of March to the last Sunday of October (the European calendar; the
file switches at 20:00 on the March Sunday and repeats 19:00–19:59 on the October Sunday) and UTC−5 otherwise; `hist_read`
converts by that rule. So converted, **the minutes are identical to Dukascopy's USA500.IDX/USD** (147,611 common minutes,
correlation 1.0000, level difference 0.0 bps): HistData mirrors Dukascopy's feed, whose own datafeed throttles bulk fetching
(a few files a minute, then 503s) and is kept only as the cross-check (`data/index_1m_dukascopy.parquet`, 2020-05-01 →
2020-10-07) and as a candidate live feed (an hour's tick file is up within the hour after it closes). Yahoo's ES=F hourly
bars (two years, about ten minutes behind): hourly return correlation 0.95, daily 0.99, level ÷ future 0.9957 (the basis).
`output/index_inventory.md` has the tables.

### etf_flows (Farside Investors, daily; P8 B3′, §9 #7) — `data/etf_flows.parquet`: `(asset, day, fund) → flow_musd, holiday`

The US spot bitcoin and ether ETFs' daily net flows, US$ millions, one row a US trading day, one column a fund, from Farside's
free all-data tables (`ft2 etf fetch|ingest|inventory`, `ft2/etf.py`; raw under `data/raw/external/farside/`, a dated copy per
fetch). **Measured 2026-10-01 (`output/etf_inventory.md`):** BTC 12 funds, 698 days 2024-01-11 → 2026-09-30 (682 trading days
+ 16 holiday rows); ETH 11 funds, 560 days 2024-07-23 → 2026-09-30. The funds sum to the total to 1e-13 on every row (the
parser refuses a page where they do not). US market holidays are rows with every fund blank until 2025-06-19 and absent after
(12 weekdays without a row from 2025-07-04 on, all holidays); they are flagged `holiday` and left out of `etf.totals`. ETH has
13 real zero-flow days. **Per fold (BTC trading days):** F2 161 (from 2024-01-11; F1 none), F3 165, F4 167, F5 174; ETH F2 29
— too few to explore, so ETH is not a feature of any exploration read. Daily total: BTC mean +82, sd 337, |total| > 300 on
31 % of days; ETH mean +25, sd 142; BTC and ETH totals correlate 0.49 (signs 0.41) on 560 common days.
**Known-at, measured on the Wayback Machine's snapshots of the live page** (`etf.known_at`, 36 snapshots read — the archive
throttles to a few an hour, so the early hours hold one or two samples each): the day's row is on the live page the same
evening, but its total is partial until the funds have all reported — 0 of 7 snapshots final within 5 h of the 21:00 UTC
close, 1 of 2 at 5–6 h, and **24 of 24 final from 9 h on**. Rule for any feature: **a day's flow is known from 09:00 UTC the
next calendar day** (12 h after the close); the all-data table is the final value and must not be read earlier. A fetch on
a holiday or before the US close sees a blank last row (the day in progress), which the parser drops.

### dvol (Deribit's 30-day implied volatility index, daily; P8 R54, §9 #7) — `data/dvol.parquet`: `(currency, day) → open, high, low, close`

Deribit's DVOL — the 30-day implied volatility of the currency's options, annualised %, one daily candle per UTC day — from the public,
keyless JSON-RPC endpoint `public/get_volatility_index_data` (`ft2 dvol fetch|ingest|inventory`, `ft2/dvol.py`; raw under
`data/raw/external/deribit/`, a dated JSON per fetch). **Measured 2026-10-18 (`output/dvol_inventory.md`):** BTC and ETH 2021-03-24 →
2026-10-17, 2,034 days each, no day missing inside, open 32–156 (BTC) and 31–193 (ETH), median 55 / 69; SOL 2022-05-04 → 2022-11-25
only (206 days; the index stopped) — no fold covered, so SOL is outside every read. F1–F5 covered 100 % for BTC and ETH. The candle's
`open` equals the previous candle's `close` on 93 % (BTC) / 91 % (ETH) of days (the rest differ in the last decimals: the index is
published continuously and the daily candle's open is the first print after midnight). **Rule for any feature: the value known at
00:00 UTC of day d is the OPEN of day d's candle; a registration reads `open` and nothing else of the row** (R54's validity (1)).

### deribit_options (Deribit's expired options by name, hourly trade bars; the AL1 audit 2026-10-18) — no table yet: `ft2 optsrc audit` → `output/optsrc_audit.md`, raw `data/raw/external/deribit/audit/`

What Deribit's public, keyless API serves of its OPTIONS history (`ft2/optsrc.py`; measured on the work VM 2026-10-18; every number in
`output/optsrc_audit.json`). `get_instruments?expired=true` lists only the instruments that expired TODAY (64 BTC, 74 ETH options on
2026-10-18); `get_last_trades_by_*` with `include_old` returns no old option trade (0 for BTC options on 2023-06-01). **What IS served:
`get_tradingview_chart_data` on an EXPIRED option addressed by its deterministic name** (`BTC-2JUN23-27250-C`: currency, the expiry as
day-without-zero + month + two-digit year, the strike, C/P; daily expiries settle at 08:00 UTC) — hourly OHLCV bars, trade-based
(`volume` in contracts, `cost` in the base currency; a bar without a trade carries the last price; 0.35 s a call). Probed one
at-the-money daily-expiry call and put per half-year and at each fold's first day: **served from 2020-05-01 on BTC (18 of 20 probe days)
and 2020-07-01 on ETH (17 of 20) — nothing for 2019-07 and 2020-01 (HTTP 400: no such instrument; the daily expiries did not exist) —
every fold's first day served.** On the probe days 61 % (BTC) / 56 % (ETH) of a leg's 24 bars hold a trade; the 00:00 bar holds a trade on
both legs on 10 of 18 (BTC) / 4 of 17 (ETH) days, so the price at a day's open is the LAST TRADE before it as often as a trade in the hour,
and a stale leg shows (ETH 2025-01-01: the call 0.040 against the put 0.0135 at the money) — any read must check put–call parity against
the perpetual's price and skip the day when it fails. The straddle's 00:00 price, median 1.98 % (BTC) / 2.60 % (ETH) of spot (a 32-hour
option: 00:00 of d to 08:00 of d + 1). Also served: the perpetual's 1-minute and hourly bars back to 2021 at least (the spot at 00:00 and
the settlement window). **No quote is in this history: the spread at the touch comes from Tardis's free days (below), the live book
(today: BTC's next-day straddle bid 0.0099 / ask 0.0112 BTC — the spread 13 bps of spot, 12 % of the mid; ETH 0.0175 / 0.0195 — 20 bps,
11 %) and Binance's 2023 end-of-hour file.** Fees (the instrument record, and Deribit's fee article found by search, not fetched):
options maker and taker 0.03 % of the underlying a contract, capped at 12.5 % of the premium; the delivery fee 0.015 % is a third-party
figure, unconfirmed; perpetuals 1.5 / 3.5 bps. The DVOL FUTURES (`BTCDVOL_USDC-<expiry>`, USDC-settled, monthly since 2023-09 by
Tardis's symbol list) are not a venue: the API lists the live one only (created 2026-09-23: 257 contracts in 25 days, open interest 151,
the book 37.4 / 39.9 — a 6.5 % spread).

### tardis (Tardis.dev — Deribit's full history, paid; the first day of each month free; the AL1 audit 2026-10-18) — no table yet; raw `data/raw/external/tardis/`

The coverage API (`api.tardis.dev/v1/exchanges/deribit`, keyless) lists Deribit since 2019-03-30: 556,894 symbols, 118,251 BTC and
122,057 ETH options by the year they start (BTC 2023 19,444, 2024 24,476), the option data types trades, quotes, book snapshots (5 / 25),
`options_chain` (the exchange's ticker per instrument: bid / ask / mark with their IVs, the underlying, the greeks — the columns measured
on 2023-06-01), incremental L2, liquidations, book ticker; 50 DVOL-futures symbols from 2023-09-20. **The CSV files
(`datasets.tardis.dev/v1/deribit/<type>/<yyyy>/<mm>/<dd>/<SYMBOL>.csv.gz`) are served WITHOUT A KEY for the first day of each month**
— measured 2026-10-18: 2023-05-01, 2023-06-01 and 2024-08-01 answer 200 for every type; 2023-05-15 and 2023-06-02 answer 401 "For
unauthorized requests, only historical CSV market datasets for the first day of each month are available". 41 such days lie inside
F1–F5 (16 in F1+F2). Sizes (MB, gz): the whole market's `options_chain OPTIONS` 1,311 (2023-05-01), 1,210 (2023-06-01), 4,503
(2024-08-01); `quotes OPTIONS` 65; `trades OPTIONS` 0.24; `book_snapshot_5 OPTIONS` 176; **one instrument's `quotes` 0.26, its chain
0.87** (BTC-2JUN23-27250-C on 2023-06-01: 21,639 quote updates in the day, 1,859 in hour 0; the first after 00:00 bid 0.009 / ask 0.010 —
the at-the-money straddle that minute 0.0095 / 0.0105 a leg: 20 bps of spot wide, 10 % of the mid). **The free tier has a DAILY transfer
limit and a file counts against it on REQUEST**: the VM's first audit asked for ≈ 75 whole-market files (≈ 50 GB in all) closed after
their headers and got HTTP 429 "This account has reached its data transfer limit", retry after 86,287 s — a read on the free days must
fetch per-instrument files only (a one-day straddle's two legs ≈ 0.5 MB a day). Price list (tardis.dev/#pricing,
docs.tardis.dev/faq/billing-and-subscriptions, 2026-10-18, a hand copy): the Options plan (Deribit's options among others) Academic
350 / Solo 700 / Professional 1,000 / Business 3,000 USD a month; MONTHLY billing serves 4 months of history, YEARLY 4 years (5 on
invoicing) — so F1+F2's 2023 → 2024 days need a yearly Solo (8,400 USD) or a yearly Academic (4,200; a university e-mail, CSV only); no
single exchange, no date range, no one-off purchase, no discount, no refund; a free trial of one month on 10 days of data (20 GB).

### binance_options (Binance's own options market — the archive and the live book; the AL1 audit 2026-10-18) — no table yet; raw `data/raw/external/binance_options/`

`data.binance.vision/data/option/daily/` holds two kinds and nothing else. **`EOHSummary/<UNDERLYING>/`** — per option and HOUR the
end-of-hour open / high / low / close, volume, **best bid and ask with their sizes and IVs**, mark and mark IV, the greeks, open interest
(26 columns; 6,046 rows, 272 instruments on 2023-07-17 for BTC): **BTCUSDT and ETHUSDT 2023-05-18 → 2023-10-23 only** (147 files each, 12
days missing inside), BNB, DOGE, XRP thinner; the archive stops there. At hour 00 of 2023-07-17 the next-day at-the-money straddle
(BTC-230718-30000) was 465 / 535 USDT — a spread of 14 % of the mid, 23 bps of spot, with 2.4 contracts at the touch. **`BVOLIndex/`** —
the exchange's implied volatility index, one row a SECOND, BTC and ETH 2023-06-20 → 2026-10-17 (1,190 files each, 26 days missing inside,
≈ 530 MB a name): a second implied beside DVOL, not a quote. The live market (`eapi.binance.com`, 1,566 options on 8 underlyings,
USDT-quoted) on 2026-10-18: BTC's next-day at-the-money straddle 865 / 875 USDT — **1.2 bps of spot, 1.1 % of the mid**; ETH 47.6 / 48.8 —
5 bps, 2.5 %: an order of magnitude tighter than Deribit's touch the same minute, with no public history to say since when. Tardis lists
`binance-european-options` from 2023-06-15 under the same plans and free days.

### straddle_1d (the one-day at-the-money straddle on BTC and ETH, F1+F2; R55) — `data/straddle_1d.parquet`: `(currency, day) → spot_00, strike, call, put, c_last, p_last, c_last_ts, p_last_ts, c_trades_24h, p_trades_24h, c_open_00, p_open_00, c_traded_00, p_traded_00, settle, settle_bars, parity, covered, skip`; `data/straddle_hedge.parquet`: `(currency, day, i) → ts, price`; `data/straddle_touch.parquet`: `(currency, day, leg) → name, first_ts, bid, ask, spread_med_h0, updates_h0, spot`

`ft2 straddle fetch|quotes|ingest|inventory` (`ft2/straddle.py`; raw one JSON a day a name under `data/raw/external/deribit/straddle/
<CUR>/`, the free-day quote files under `data/raw/external/tardis/quotes/<day>/`). **Fetched 2026-10-18 on the work VM** from Deribit's
public chart endpoint (DATA.md `deribit_options`): for each of F1+F2's 489 days and each name the perpetual's 1-minute bars over the 32
hours from 00:00 (1,920 bars in one call: the spot = the 00:00 bar's open; the hedge's prices = the close of the bar ending at each hour;
the settlement = the mean close 07:30 → 07:59 of d + 1, the perpetual's TWAP standing in for the index's), and the daily-expiry
at-the-money call and put (`<CUR>-<d+1>-<K>-C/P`, expiring 08:00 UTC of d + 1, K the served strike nearest the spot) as hourly bars over
[d − 1, d + 1 08:00). **Every day had a served pair (489 / 489 a name).** The entry price is each leg's LAST TRADE before 00:00 (the close
of the last hourly bar with volume that ends at or before 00:00): the median age of that trade is under an hour on both names; the
00:00 bar itself holds a trade on both legs on 323 (BTC) / 292 (ETH) of the days. **Covered** (both legs traded in the 24 hours before,
|C − P − (S − K) / S| ≤ 0.5 % of spot, ≥ 25 settlement bars, the path whole): **BTC 424 / 489 (87 %; F1 96 %, F2 78 %), ETH 438 / 489
(90 %; 96 %, 83 %)**; skipped: a leg untraded in the 24 hours 33 / 14, parity 32 / 37, settlement 0, path 0 — F2's thinner months are
2024's. The straddle at the last trades: median 1.97 % (BTC; p10 – p90 1.25 – 2.95) / 2.15 % (ETH; 1.34 – 3.20) of spot. **The touch**
(`straddle_touch`, Tardis's free first-of-month days, the two legs' `quotes` files, ≈ 0.3 MB each, fetched from the VM after its daily
limit reset): the at-the-money straddle's bid–ask at the first quote at or after 00:00 on each of the 16 days a name — **median 20 bps of
spot on both names** (BTC range 11 – 60, ETH 10 – 35; 7 – 21 % of the straddle's mid; the median spread over hour 0 the same 20). **Rule
for any read: the entry is the last trade before 00:00 and nothing after it; the settlement is the 07:30 → 07:59 TWAP; a day outside
`covered` is not a trading day.**

### varmonth (the monthly at-the-money straddle on BTC and ETH, 2020-05 → today; decision AQ2) — no table: raw one JSON a month a name under `data/raw/external/deribit/varmonth/<CUR>/<expiry>.json`; the priced rows `output/varmonth/all/months.csv`

`ft2 varmonth fetch|run` (`ft2/varmonth.py`). **Fetched 2026-10-19 on the work VM** from Deribit's public chart endpoint (DATA.md
`deribit_options`): for each monthly expiry (the last Friday of the month, 08:00 UTC; BTC from 2020-05-29, ETH from 2020-07-31; 76 / 74
months to 2026-09-25) one file holding the perpetual's hourly bars from the previous expiry's 08:00 to the settlement, the perpetual's
1-minute bars 07:30 → 08:00 of the settlement day, and the at-the-money monthly call and put (`<CUR>-<expiry>-<K>-C/P`, K the served
strike nearest the perpetual's close at 09:00 UTC after the previous expiry, the nearest strikes tried in turn) as hourly bars over the
48 hours around the entry. The entry is each leg's LAST TRADE at or before 09:00; the settlement the 1-minute TWAP 07:30 → 07:59 (≥ 25
bars). **Covered (both legs traded in the 24 h before, |C − P − (S − K) / S| ≤ 1 % of spot, the hourly path whole, the settlement window
whole): BTC 45 / 76, ETH 40 / 74**; skipped: a leg untraded in the 24 h 17 / 16, parity 13 / 14 (nearly all +1 … +2.8 %, the two legs'
last trades hours apart), no served pair 1 / 4 (2021-12 BTC; 2021-02 / 03 / 06 / 09 ETH); the uncovered months crowd 2020–21. The covered
straddle's median 11 % (BTC) / 14 % (ETH) of spot; the break-even vol 0.49 / 0.62 against the month's realised 0.50 / 0.65. **The touch**
(`live_touch`, the live book of the front monthly at-the-money straddle on the day of the run, `get_book_summary_by_currency`): 20 bps of
spot on both names (the same as R55's Tardis median on the daily straddle). **Rule for any read: the entry is the last trade at or before
09:00 after the previous expiry and nothing after it; the settlement is the 07:30 → 07:59 TWAP; a month outside `covered` is not a month.**
Re-fetch with `ft2 varmonth fetch` (a file already on disk is not fetched again; `--end` moves the last expiry).

### coinbase_1h (Coinbase Exchange spot, hourly, the twelve's <BASE>-USD products and USDT-USD; decision AT2, §9 #10) — `data/coinbase_1h.parquet`: `(product, symbol, ts, ts_known, open, high, low, close, volume)`

`ft2 coinbase products|fetch|ingest|audit` (`ft2/coinbase.py`; raw one JSON a product a month under `data/raw/external/coinbase/<PRODUCT>/`,
`daily.json` the daily bars from 2015 for the first bar, `products_<date>.json` the listing). **Fetched 2026-10-19 on the work VM** from
Coinbase Exchange's public, keyless REST API (`/products/<id>/candles`, 300 candles a call, `time` the bucket's START in seconds UTC; the
bucket in progress is served and is dropped on ingest). **Measured (`output/coinbase_audit.md`):** 13 of 13 products listed and online.
Hourly bars from 2023-04-01 (the first hour asked) on BTC, ETH, SOL, ADA, AVAX, LINK, DOGE, ZEC and USDT (first daily bars 2015-07-20,
2016-05-18, 2021-06-17, 2021-03-18, 2021-09-30, 2019-06-27, 2021-06-03, 2020-12-08, 2021-05-04); XRP from 2023-07-13 (relisted; F1 70 %);
PEPE from 2024-11-13 (F3 70 %); WLD from 2025-04-30 (F4 on); HYPE from 2026-02-05 (F5 87 %). Completeness 99.97 % of the hours 2023-05-01 →
2026-09-15 on the long names: two gaps of 6 hours common to every product (Coinbase's outages). **The premium** (at each hour's END, Coinbase's
close over Binance's 5m close ending at the same stamp, minus one, bps; 1000PEPE ÷ 1,000): the raw gap carries the USDT rate (USDT-USD median
0.99995, p1 0.99839, p99 1.00107 → +0.5 bps at the median, ± 16 at the tails), so the ADJUSTED premium (÷ USDT-USD of the same hour) is the
series — BTC +3.1 bps (sd 4.1), ETH +2.9 (4.2), SOL +3.6 (6.1), DOGE +3.3 (7.2), XRP +3.4 (8.1), AVAX +3.9 (9.9), LINK +3.4 (11.0), ADA +4.4
(18.3), PEPE +3.4 (20.1), ZEC +9.2 (48.5), WLD +9.4 (49.4); autocorrelation at 1 h 0.89 / 0.90 (BTC / ETH) down to 0.05 (PEPE), at 24 h 0.79 /
0.84 (BTC / ETH), 0.1–0.5 the rest; flat by hour of day; the mean cross-name correlation 0.46, the first component 25 %. **Rule for any
feature: a bar is read at `ts_known` = its start + 1 h and nothing earlier; the 5m decision bars inside an hour carry the last bar whose
`ts_known` ≤ t; the adjusted premium is the quantity, the raw one is not read; ZEC's and WLD's series are thin-book noise (sd ≈ 48 bps) and
a feature on them is described, not counted.** The serving lag after an hour boundary, measured 2026-10-19 14:00 UTC with six polls over 2.6 minutes (`coinbase.live_lag`): the completed bar ending 14:00 was served at the first poll, 22 s after the boundary, with the in-progress bucket beside it on every poll — the lag is under 22 s. R60 reads a bar only from `ts_known` + 5 min on, a margin of more than ten times that.

### coinbase_1h_members (Coinbase Exchange spot, hourly, the screener's members' <BASE>-USD products; decision AX1 (i), §9 #10) — `data/coinbase_1h_members.parquet`: the same columns as `coinbase_1h`

`ft2 coinbase products|fetch --listed-only|ingest|audit --universe members` (`scripts/ax1_chain.sh`; the raw month files shared with the
twelve's under `data/raw/external/coinbase/<PRODUCT>/`; the twelve's `data/coinbase_1h.parquet` is never rewritten — a separate parquet).
The universe: every member base of `ft2/screen_members.csv` and `screen_members_f34.csv` (310 symbols; a 1000× / 1M× contract's base
with the multiple divided — 1000SHIB ÷ 1,000, 1MBABYDOGE ÷ 1,000,000) as a `<BASE>-USD` product, plus USDT-USD. **Fetched 2026-10-19 on
the work VM, 15:53 → 19:42 UTC** (an unlisted product answers 404 on every call, so `--listed-only` skips the 149 the listing does not
hold). **Measured (`output/coinbase_members_audit.md` / `.json`, `coinbase_members_premium.parquet`):** 161 of the 310 member bases are
listed (144 online, 17 delisted), 159 have hourly bars. Per 60-name block the members with a bar inside the block and ≥ 90 % of the
block's hours covered: 31 … 46 on F1+F2's 18 blocks (median ≈ 40; 2024-05 → 2024-08 the low, 31 … 35), 26 … 46 on F3+F4's 17
(2024-11 the low). Of the 159 with bars, 121 cover ≥ 90 % of their own member hours, 10 between 50 and 90 %, 27 under 50 % (listed on
Coinbase after their membership — 44 of the 159 first traded on Coinbase in 2025, 17 in 2024; the mean cover of F1 / F2 / F3 / F4 / F5
0.55 / 0.59 / 0.68 / 0.83 / 0.86, the median ≥ 0.9 in every fold). Completeness over 2023-05-01 → 2026-09-15 median 85 % (the late
listings), the hourly holes median 50 a name (Coinbase serves no bucket for an hour without a trade, so a thin product has holes; six names
have an unchanged close on more than 20 % of their hours — GTC 36 %, MASK 30 %, 1INCH 24 %, STRK, ENJ, BOND), the largest gap 289 h.
**The adjusted premium** (R60's definition) across the 158 names with a series: the level median +4.3 bps (a quarter of the names
between +1.9 and +7.3 — the twelve's +3 … +4 again), sd median 29 bps (18 names ≤ 15, 62 between 15 and 30, 73 above 30 — against the
twelve's 4 … 20 on the liquid names and 48 on ZEC / WLD); the autocorrelation at 1 h median 0.33, at 24 h 0.09. Two kinds of bad series,
both named by the sd: (a) **a different asset on the two venues** — a persistent offset with the autocorrelation at 1 h ≈ 1: OCEAN (mean
−396 bps, sd 1,110; the ASI merger), MKR (−157, sd 597, delisted 2026-01-12; the SKY migration), VOXEL (−130, sd 739), AUDIO (+33, sd 376),
ENJ (+200, sd 352, delisted 2024-06-14), GMT (+19, sd 124) — their premium is not a premium; (b) **thin books** — a wide sd with a low
autocorrelation (SPX sd 100 at 0.05; AVNT 157; MOVE 157; ORCA 82). The mean cross-name correlation of the premium 0.28 (the twelve's 0.46);
the first component is not computable on the ragged panel (NaN). By hour of day the mean is +2 bps at every hour but 22 UTC (+5.2) and
23 (+3.1). **The volume share (AX2, described):** Coinbase's hourly USD volume over Binance's hourly USDT volume on the perpetual, per
name — the median 2.1 % (p10 0.5 %, p90 6.4 % within a name; across names the quartiles 1.1 … 4.8 %), the log share's deviation from its
trailing month has sd 0.84 (a loud, name-specific quantity), and its correlation with the adjusted premium is nil (median −0.025, positive
on 26 % of the names) — US participation surging on a name does not move the price gap. The twelve's share is not computed (their audit
predates the column). **Rule for any feature: R60's rule holds (`ts_known` = the bar's start + 1 h; the adjusted premium; the last bar
whose `ts_known` ≤ t — so a thin name's premium is STALE for the hours it has no bar); a registration on the members names its sd cut in
advance — at the twelve's ZEC / WLD level (sd ≤ 48 bps) 121 of the 158 series stay and ≈ 37 … 43 members a block carry one on F1+F2, at
sd ≤ 30 (the twelve's liquid level) 80 stay and ≈ 24 … 34 a block; the six different-asset names fall at either cut.** What follows is
decision AY (P8).

### krw_1h_upbit, krw_1h_bithumb (Upbit's and Bithumb's KRW spot, hourly, the twelve's and the screener's members' KRW-<BASE> markets and KRW-USDT; decision BB1 (i), §9 #11) — `data/krw_1h_<venue>.parquet`: `(venue, market, symbol, ts, ts_known, open, high, low, close, volume_krw, volume, last_tick)`

`ft2 krw markets|fetch --listed-only|ingest|audit --venue upbit|bithumb` (`scripts/bb1_chain.sh`, the two venues in parallel; raw month files
under `data/raw/external/<venue>/<MARKET>/`, the listing beside them). The universe: KRW-<BASE> for every base of the twelve and of the 310
member bases (a 1000× / 1M× contract's base with the multiple divided), plus KRW-USDT — the control that turns a KRW price into a USDT one on
the venue itself. Both APIs are Upbit's shape (`/v1/candles/minutes/60?market=&to=&count=200`, newest first, strictly before `to`,
`candle_date_time_utc` the bar's START; an hour without a trade has no candle; the bucket in progress is served and is DROPPED on ingest).
**Two venue conventions found the hard way:** Upbit's `to` takes `Z` and is UTC; Bithumb's refuses a zone and reads the bare stamp as
KST, so the first Bithumb fetch (UTC stamps) lost the 9 newest bars of every 200-bar page — 4.5 % of hours, a hole every page, completeness
0.95 at best (`output/krw_bithumb_audit_void1.md`); refetched the same day with the stamp written +9 h. Bithumb's `timestamp` on a finished
bar is the bar's END, not a tick (23 % of its bars sat exactly there); Upbit's is the last tick (99.6 % inside the hour). Upbit's API
refuses TLS from the laptop and answers from GCP. The API is latency-bound at ≈ 1.3 s a call from the VM (far under its 10-a-second limit):
one market's 43 months take ≈ 4.3 min, so a venue is fetched in parallel partitions.
**Fetched 2026-10-20 on the work VM:** Upbit 07:07 → 13:29 UTC (136 markets; a helper took the tail), Bithumb 07:07 → 14:15 (void, the
KST stamps) and the refetch 14:25 → 15:57 in 8 partitions (`scripts/bb1_bithumb_refetch.sh`). **Measured (`output/krw_<venue>_audit.md` /
`.json`, `krw_<venue>_premium.parquet`):**
- **Listing and history.** Upbit lists 136 of the 322 bases asked (the twelve and the 310 member bases), Bithumb 195 — both more than
  Coinbase's 161 — every listed market with hourly bars; the first bar in 2023 / 2024 / 2025 / 2026 for 54 / 21 / 43 / 18 of Upbit's and
  96 / 39 / 54 / 6 of Bithumb's (the member names of F1+F2 reached Korea later than Coinbase on Upbit, earlier on Bithumb). Of the 310
  members, 70 cover ≥ 90 % of their own member hours on Upbit and 128 on Bithumb (Coinbase 121). **Per 60-name block (R62's frame, the
  members with ≥ 90 % of the block's hours):** Upbit 14 … 30 on F1+F2's 18 blocks (median ≈ 21; 2024-06 → 2024-08 the low) and 18 … 33
  on F3+F4's 17; Bithumb 21 … 39 on F1+F2 (median 31½; ≥ 30 on 12 of the 18, every block from 2023-10-30 on; the first five 21 … 31) and
  33 … 48 on F3+F4. Coinbase was 31 … 46 / 26 … 46.
- **Completeness.** Over 2023-05-01 → 2026-09-15 the median name 56 % (Upbit) / 76 % (Bithumb) — the late listings; the liquid names
  99.8 % on both. An hour without a trade has no candle, so a thin name has holes: the median name 26 holes over an hour on Upbit, 347 on
  Bithumb; the largest gap is the venue's own, 5 … 9 h on every Upbit name and 11 h on every Bithumb name (common outages). An unchanged
  close on 12 % (Upbit) / 8 % (Bithumb) of the median name's hours. Alignment: Upbit's `timestamp` is the last tick, inside the hour on
  99.6 % of bars (median 59.5 min after the start); Bithumb's is the bar's END on a finished bar (23 % exactly there, 77 % inside) — on both
  venues `candle_date_time_utc` is the START, and a bar is known at `ts_known` = start + 1 h and nothing earlier; the bucket in progress is
  served by both and dropped.
- **KRW-USDT, the control, is YOUNG:** listed on Bithumb 2023-12-07 and on Upbit 2024-06-07 (the rate 1,334 … 1,538 KRW, median ≈ 1,430),
  so the ADJUSTED premium (the name's KRW price over its USDT price on the same venue) exists on no F1+F2 hour before 2023-12 (Bithumb) /
  2024-06 (Upbit). The BTC-RELATIVE premium — the name's KRW/USDT ratio over BTC's, the FX and the market-wide Korean premium removed by
  construction — covers every hour of every name and is the quantity a within-hour rank screen reads; on the hours both exist the two agree
  on the liquid names (BTC's adjusted premium +3.5 … +4.2 bps, sd 9 … 12, the same on both venues).
- **The level.** The adjusted premium's median across names +5.2 bps on Bithumb (2023-12 →), +6.7 on Upbit (2024-06 →): the Korean price of
  a name sits a few bps ABOVE its USDT price on the same venue — Coinbase's +4.3 again, not a kimchi premium (that one lives in KRW-USDT
  against the dollar and is divided out). The market-wide premium (the median adjusted premium across names each hour) is +5 … +8 bps in
  every quarter but 2024Q4 (−2, sd 35) and 2025Q4 (+9 … +15, sd 28 … 35), sd over hours 16 … 19 bps, autocorrelation at 24 h 0.13 / 0.21.
  Flat by hour of day (the median name's mean 1 … 3 bps at every UTC hour, 6 … 7 at 22 … 00 UTC on Upbit; the KST day against the US
  hours 1.7 vs 1.5 on Bithumb, 2.9 vs 3.0 on Upbit).
- **The within-name variation — BB1's question.** The premium's sd per name, median across names: 36.7 bps adjusted / 35.2 BTC-relative on
  Bithumb (4 names ≤ 15, 45 between 15 and 30, 89 between 30 and 48, 33 between 48 and 100, 15 above), 35.4 / 36.6 on Upbit — against
  Coinbase's 29. Autocorrelation at 1 h 0.31 (Bithumb) / 0.47 … 0.56 (Upbit) against Coinbase's 0.33; at 24 h 0.07 / 0.17 against 0.09.
  Like for like on R62's own quantity (the deviation from the name's trailing 30-day mean; the different-asset and thin names out on every
  venue by the same cut, |mean| < 200 and sd < 300), the median name's sd of the deviation over F1+F2's hours: **Coinbase 17.5, Upbit 23.0
  (× 1.3), Bithumb 29.6 (× 1.7)**; the sd of the hourly change 20.3 / 25.1 / 38.8; over all hours 28.3 / 35.6 / 33.9 (× 1.2 — Coinbase's
  late-listed names are the noisy ones, Korea's are not). The cross-sectional sd of the BTC-relative premium within an hour on F1+F2: 32.7 bps
  across ≈ 85 names on Bithumb, 19.2 across ≈ 49 on Upbit. The mean cross-name correlation of the BTC-relative premium 0.16 (Bithumb) / 0.29
  (Upbit) against Coinbase's 0.28.
- **Bad series, by the same two signatures as Coinbase's:** (a) a different asset or unit on the two venues — a persistent offset with the
  autocorrelation at 1 h ≈ 1: STRAX (−9,250 bps on both venues; the 2024 token swap), WAVES (−310 … −340, sd 850), ENJ (−117, sd 490,
  Bithumb), CRV (+950, sd 5,360, Bithumb), KAVA (+386, sd 1,870, Upbit), AUDIO (Bithumb); (b) thin books — EDU (sd 1,874 at acf 0), CYBER,
  MINA, ORCA, MOVE, 0G, 1000FLOKI, REZ; PEPE's BTC-relative premium sits at +46 with sd 188 on Bithumb (a 1000× contract divided; the KRW
  price's tick). The audit's sd names them all; a registration cuts at a stated sd before any label is joined, as R62 did at 48.
- **The volume share (AX2's form, described):** the venue's hourly volume in USDT over Binance's hourly USDT volume on the perpetual, per
  name — **Upbit median 9.5 %** (p10 2.8 %, p90 25 % within a name; across names the quartiles 4.5 … 18 %; Coinbase was 2.1 %), Bithumb
  1.3 % (quartiles 0.6 … 2.7 %); the log share's deviation from its trailing month has sd 0.76 / 1.16; its correlation with the adjusted
  premium nil on both (median +0.016 / +0.002). Upbit is the larger market in these names by far; the premium does not follow its surges.
- **Serving, live:** both APIs serve the bucket in progress and the complete bars at the hour; the API is latency-bound (≈ 1.3 s a call from
  the VM, far under the 10 a second allowed), so a live hourly read is one call a name.
**Rule for any feature: R60's (`ts_known` = the bar's start + 1 h; the last bar whose `ts_known` ≤ t; a thin name's premium a MISSING
value where its bars are more than STALE hours apart); the quantity the BTC-RELATIVE premium (the adjusted one has no F1+F2 history on
either venue); a registration names its venue and its sd cut in advance — at R62's 48 on the BTC-relative sd, Bithumb keeps ≈ 130 of
186 series and ≈ 25 … 36 members a block on F1+F2's blocks from 2023-10-30, Upbit ≈ 85 of 113 and ≈ 15 … 27.** What followed:
decision BC → R64 (§8), read 2026-10-21: the Bithumb deviation CLOSED at 1d on the members (+0.002) and a fact of the hours (+0.007 at 1h,
+0.006 at 4h, both folds); Upbit's +0.015 at 4h; the Coinbase deviation on the same cells +0.014 at 1d. Parked in §7.

### krw_listings (the Korean LISTING of an existing Binance perpetual as a per-name EVENT — Upbit's and Bithumb's first hourly KRW bar; decision BM1 (i), §9 #13) — `ft2/krlistings_f12.csv`, `ft2/krlistings_f34.csv` (FROZEN 2026-10-24, commit 9f5c4b7, before any bar of an event's name was read for anything): `(venue, market, symbol, base, mult, t0, ts_known, fold, perp_first, perp_first_source, perp_age_days, first_korean, other_venue_t0, member_at_t0)`

`ft2 krlist events|bars [--fetch]|audit` (`ft2/krlist.py`; `scripts/bm1_chain.sh`; `tests/test_p8_krlist.py`). No new source: the events are
READ OFF `krw_1h_upbit` / `krw_1h_bithumb` (the columns market, symbol, ts, volume_krw — no price column is loaded), one candidate per market =
its first hourly bar t0. **The event rule:** t0 ≥ 2023-04-08 (the fetch's start + a 7-day MARGIN — Bithumb's first bars at 01:00 and 03:00 UTC
on 2023-04-01 (BNT, OGN) and INJ's on 04-04 are a thin market's late first trade, not listings; a first bar AT the fetch start is a listing
before the window); the perpetual's first bar from `candles_5m_archive` where the slice holds the name (every eligible event — 121 of 121
`archive 5m`), else the first day of the month after `um_first_month.csv`'s first month (an upper bound, so the age is a lower bound);
ELIGIBLE = the perpetual ≥ 30 days old at t0 (younger = a launch, R28's population, 74 candidates: SUI, WLD, PEPE a day old on Bithumb;
RENDER, S renamed contracts) AND t0 inside F1 … F4 (F5's 20 listed in `output/krlist/events.csv` and not frozen; 6 outside: F0's OP and
EGLD, four after F5). Flags: `first_korean` (the other venue has no bar before t0), `other_venue_t0`, `member_at_t0` (a member of the block
holding t0), `fold`, `base`, `mult` (a 1000× contract's base). **Known-at: t0 is the bar's START and the bar is final at `ts_known` = t0 + 1 h
(`krw_1h_*`'s rule); the decision bar of any registration closes at t0 + 60 min.** No announcement board was read: Bithumb's notices API
(`api.bithumb.com/v1/notices` → `feed-api.bithumb.com`) serves its latest FIVE whatever the parameters, Upbit's (`api-manager.upbit.com`)
sits behind Cloudflare and refuses a script, the Wayback Machine holds Upbit's announcement pages and was offline — the announcement-to-open
lag is NOT measured; the pump before t0 is a registration's own validity row (the run-up against the peers over t0 − 24 h → t0).
**Counted 2026-10-24 (`output/krlist/audit.md` / `.json`, `events.csv`, `bars.csv`, `crowd_size.csv`):** 224 candidate first bars, **121
ELIGIBLE — F1 25 (Bithumb 20 / Upbit 5), F2 27 (19 / 8), F3 31 (15 / 16), F4 38 (18 / 20): F1+F2 52, F3+F4 69.** A name's FIRST Korean
listing (`first_korean`): F1 22, F2 19, F3 17, F4 17 — 41 on F1+F2 (Bithumb 36 / Upbit 5), 34 on F3+F4 (24 / 10); the second venue's
listing 11 / 35 (Upbit listed the members' names late: its F3+F4 events are mostly second listings). 91 names, 30 on both venues; members of
the block at t0 55 of 121 (27 on F1+F2, 28 on F3+F4). The perpetual's age at t0 p10 / p50 / p90 51 / 228 / 910 days (medians by fold 274 /
168 / 313 / 147; the youngest 34). **Of the twelve: PEPE (Upbit 2024-11-14, F3) and WLD (Upbit 2025-09-09, F4), both second listings — their
Bithumb listings were launches (the perpetual a day old); none on F1+F2.** **The hour:** 68 of 121 first bars start 16 … 18 KST (07 … 09 UTC;
the full spread 10 … 22 KST plus two at 00) — a Korean afternoon opening; the decision bar closes 08 … 10 UTC. **Bars:** the window
t0 − 2 d → t0 + 8 d (2,880 5m bars) complete (≥ 95 %) for 111 of 121 before the fetch, 121 of 121 after — 12 (name, month) files fetched for
9 names (1000PEPE, ALT, API3, COMP, CYBER, IOTA, LISTA, WLD, YGG; 2024-11 → 2025-10), the slice re-ingested whole (83,275,262 rows, 598
names, 2019-12-31 → 2025-12-31) under the per-name fingerprint (rows, first, last, the sums of close and volume on each name's OLD extent;
rtol 1e-12): **598 of 598 names unchanged, pass** (`fingerprint_check.json`). The last F4 event 2025-12-16, its window inside the slice.
**The arriving crowd (volumes, not prices; AX2's form):** the venue's KRW volume over the first 24 bars from t0 in USDT (through KRW-USDT
where the venue lists it — Bithumb from 2023-12-07, Upbit from 2024-06-07 — else KRW-BTC over BTCUSDT's hourly close; the FX and the
market-wide premium together, a scale not a premium) against Binance's quote volume on the perpetual over the same hours: **Upbit's first
day median 0.335 of Binance's (p10 / p90 0.18 / 0.72; the ordinary day 0.095 — × 3.5), days 2 … 7 0.146 (× 1.5); Bithumb 0.087 (0.017 /
0.31; the ordinary 0.013 — × 6.7), days 2 … 7 0.025 (× 2)**; the median venue first-day volume 40 M USDT (Upbit 265 M, Bithumb 13 M)
against Binance's 311 M; two Bithumb listings out-traded Binance on the day (PENDLE 2.39, NEO 1.75); STRAX's perpetual had no Binance
volume (the 2024 swap) — 120 of 121 rows. The crowd is real on both venues and several times larger on Upbit, whose F1+F2 events are
few (13, 5 of them first listings). **A trap found on the way:** `candles_5m_archive` holds BTCUSDT only to 2022-08-19 (the members'
slice); the twelve's bars are the collector's `candles_5m` — the hourly Binance read (`krlist._hourly_binance`) takes both slices, the
archive's row where both hold one (the first run's crowd row was empty before the venues' KRW-USDT; rerun 06:11 UTC).
**Rule for any registration: the cell is an event of a FROZEN list (the first Korean listing per name the gate's cell — 41 on F1+F2; the
second venue's listing a described row); t0 and `ts_known` as frozen; nothing about an event's price was read here — the run-up, the
give-back and the venue split are the registration's. Decision BN DECIDED 2026-10-29 ("BN2"): R70 REGISTERED and READ the same day (PLAN §8) — CLEARS at 1 day, the sold side −242 bps against the members (the run-up before the bar +644 at the median); R71 READ 2026-10-29 on the frozen F3+F4 list (64 cells; the first run VOID on validity (5) — the seven F1+F2-only members had no cost row past 2024-08-31 after BM1's fetch, `costwide` re-run under §3's `costs`: 271,624 rows, 584 names, every old row unchanged, the file before kept on the VM as `cost_daily_wide_before_r71.parquet`): NOT CONFIRMED — H −135.5 a position [se 328], u −0.41; F3 +422 / F4 −628; the give-back in the MEDIAN on both lists (y_1d median −452, 80 % below zero) and not in the mean (HYPER, MON, XPL ran on against the seller by 0.7 … 1.5× the size, HYPER's funding −6,416 in a day); F3+F4 spent for this question, F5's listings the revival (PLAN §7). A trap of the lists: PYTH's two rows (F1+F2) and three pairs on F3+F4 are a same-name same-hour listing on both venues — one set of bars, two rows.**

### perp_mix_1h (the PERPETUAL's hourly participant mix per member — the trade count, quote volume, taker-buy quote volume, volume, last close and bar count, summed from the archive's monthly 5m kline zips already on the work VM; R73's Data line, decision BR1, 2026-11-01) — `data/perp_mix_1h.parquet`: `(symbol, ts, ts_known) → close, volume, quote_volume, count, taker_buy_volume, taker_buy_quote_volume, bars`

`ft2 mix ingest|audit|fingerprint` (`ft2/mix.py`; `tests/test_p8_mix.py`). **Source:** no new download — the archive's monthly 5m zips under
`data/raw/external/binance/klines/<SYM>/` (§9 #2's fetch for R23 / R25: the F1+F2 members through 2024-08, the F3+F4 members through
2025-12; 631 symbol directories, 3.1 GB; `.zip.ok` beside every file), whose column 9 `count` (the bar's number of trades) and column 8
`quote_volume` were never ingested (`candles_5m_archive` kept OHLCV). Every symbol of the two member files with zips (310 of 310), one
symbol at a time; the 5m bars whose END lies in (H, H + 1 h] summed into the hour `ts` = H, **known at `ts_known` = H + 1 h** (the
spot table's rule), `bars` = the number summed. **Built and audited 2026-11-01 on the work VM (≈ 25 min), BEFORE `ft2/mix_ext.py` was
written; no count joined to a label or a price.** **FINGERPRINT (R73's validity (1) compares the run's table against it):** 5,005,729 rows,
310 symbols, 2021-11-01 00:00 → 2025-12-31 23:00 UTC, Σ count 85,595,190,688, Σ quote_volume 22,598,540,430,854.01. **Measured
(`output/perp_mix_audit.md` / `.json`):** hours with fewer than 12 bars: median share 0.0000, max 0.0009 (PIEVERSE, BEAT, FOLKS — their
first hours); zero-trade hours: median share 0.0000, but COCOS 0.80 (a dead listing 2023-02 → 2024-05), TROY 0.61, STRAX 0.52 (the 2024
migration), REEF 0.32, FTM 0.24, BNX 0.22 — the log count is NaN only where a whole trailing day has no trade; the median name trades 7,330
times an hour at a median trade of 137 USDT. **The aggregation check** — the hour's `quote_volume` over Σ volume × close of the same hour
from `candles_5m_archive` on R68's 256 kept names: the median ratio 1.0000 on every name (range 0.99991 … 1.00005), the share of hours more
than 5 % off 1 at most 0.0005 — the same zips feed both, the hours line up. **The members' cover per block:** 60 of 60 on every F1+F2 block
but 2024-07-31 (59) and 2024-08-30 (57); F3+F4 59 … 60 (2025-12-29 0 — the zips end 2025-12-31 and the last block has no whole hour). **The
overlap with the spot table on R68's 256 kept names** (the combined quantity needs both bars in the hour): both bars on a median 93.3 % of a
kept name's perp hours; 13 names under 50 % (REEF 5 %, MORPHO 22 %, TOMO 25 %, BIGTIME 33 %, ONDO 37 %, TROY 39 %, PUMP / OMG / WAVES / FTM /
OCEAN / AUDIO 42 … 45 % — spot listed later or delisted; AUDIO / OCEAN / FTM / WAVES among R62's different-asset names); **the spot share
of the hour's count: median 0.172 across names (p10 0.115, p90 0.266)** — the perpetual carries five trades in six. **Rule for any
registration: a count is read at `ts_known` and no earlier; R73 (PLAN §8) is the registration — the two markets together, R68's frozen list,
two cells, the signs − / +; nothing here was joined to a price.** **Read 2026-11-01 (R73): the F1+F2 rows of the kept F1+F2 members were joined to P2's labels through `ft2/mix_ext.py` once; the fingerprint equal before and after the run; the F3+F4 rows (2024-09 → 2025-12) UNREAD, cut by `ceiling.END` — **read 2026-11-01 (R74, decision BS1): the F3+F4 rows of the 165 kept F3+F4 members joined to P2's labels once through `mix_ext.run_r74` (the guard rows (R74, F3) / (R74, F4) in the ledger first; the fingerprint equal before and after; the first run VOID at the hand check's sampler, no count joined, rerun): NOT CONFIRMED — the count cell −0.0034 (t −0.44) where F1+F2 read −0.0327; count × volume +0.962, count × size +0.322 on the 7.2 M scored cells; the mean size's LEVEL +0.039 at 1d on F3+F4 (0.000 on F1+F2) is hindsight, recorded in R74's Result, unregistered. Every row of this table is READ for the two DEV forms at 15m … 1d (the table has no F5: the zips in hand end 2025-12-31).** What the read said of this table: the count's deviation from its month IS the dollar volume's (+0.971 on 8.1 M scored cells), and a busy day has more AND larger trades (count × size +0.375) — the two columns are not two quantities at a day on these names.**

### spot_1h (Binance spot, hourly, the twelve's and the screener's members' `<BASE>USDT` markets; decision BH1, §9 #3) — `data/spot_1h.parquet`: `(spot_symbol, symbol, ts, ts_known, open, high, low, close, volume, quote_volume, count, taker_buy_volume, taker_buy_quote_volume)`

`ft2 spot symbols|fetch --listed-only|ingest|audit` (`scripts/bh1_chain.sh`; raw month files under `data/raw/external/binance_spot/klines/<SYMBOL>/`,
the listing beside them). The source: the public archive's `data/spot/monthly/klines/<SYMBOL>/1h/` — one zip a month, no header, the twelve
kline columns, closed bars only, CHECKSUM verified; **the stamps are milliseconds through 2024 and MICROSECONDS from 2025-01** (read by
magnitude). The universe: `<BASE>USDT` for every base of the twelve and the 310 member bases (the 1000× / 1M× prefix stripped, as
`coinbase.base`), the contract's own symbol where the spot market lists it as such (1000SATSUSDT, 1MBABYDOGEUSDT — quoted per 1,000 / 1 M
tokens on both markets, so no multiple applies), 2023-04 → F5's end; a bar starting at H is read at `ts_known` = H + 1 h and nothing
earlier. **Fetched 2026-10-22 on the work VM, 12:38 → 12:59 UTC** (272 symbols × ≤ 42 months, 0 errors; 2,746 months missing = the
listings after 2023-04), ingested 6,279,915 rows (2023-04-01 → 2026-09-30), audited 13:00 → 13:03 (rerun 13:10 → 13:13 with the
trailing-day forms added and the two prefixed names' stamp check corrected; the hourly rows identical to 0.0). **Measured
(`output/spot_audit.md` / `.json`, `spot_ratios.parquet` — the four ratios, their deviations and `cbprem_dev` per (ts_known, symbol)):**
- **Listing and history.** 272 of the 322 perpetuals have a spot pair in the archive — every one with hourly bars; the 50 without are
  futures-only listings (FARTCOIN, POPCAT, MOODENG, SPX, AI16Z, GOAT, …). Of the 188 F1+F2 members 183 have one; of R62's 121 kept names
  113 (the 8 without: ATH, FARTCOIN, MON, MOODENG, POPCAT, USELESS, VVV, ZETA). The first bar on or before F1's start for 157 names, in
  2023 for 178, 2024 for 45, 2025 for 48; 46 names end before 2026-09-30 (spot delistings — AGIX, MATIC, FTM, OCEAN, MKR, WAVES, …).
  Completeness over 2023-05-01 → 2026-09-15 median 85 % (the late listings; 44 % of the names ≥ 99 %), interior holes essentially none
  (the median name 0 gaps over 1 h, the maximum 1; the largest 198 h), zero-volume hours ≤ 0.05 %.
- **The members' cover per block** (a member counts with ≥ 90 % of the block's hours): **54 … 60 of 60 on F1+F2's 18 blocks** (59–60 through
  2023-10, 54–58 from 2023-11), 44 … 55 on F3+F4's 17 (2025-12 the low) — against Coinbase's 31 … 46 and 26 … 46 the widest per-name
  source in hand; 244 of the 260 members with bars cover ≥ 90 % of their own member hours, 9 between 50 and 90 %, 7 under 50 %.
- **The stamp check** (the spot close over the perpetual's 5m close ending at the same stamp): the basis median +4.2 bps across names (p10
  0.0, p90 +8.3; the twelve +2.9 … +5.2 — the spot a few bps over the perpetual), |basis| median 7.3 bps, the share past 50 bps median
  0.15 % — the stamps agree. Two bad series by the same check: STRAX (|basis| median 343 bps, half the hours past 50 — the 2024 token
  migration, a different asset on the two markets) and 0G (33 bps, 30 % past 50; 2,414 hours, thin).
- **The taker-buy share** (the hour's taker-buy quote volume over its quote volume) **is WHITE hour to hour:** the level 0.488 on every name
  (the names' means 0.480 … 0.496, no name outside 0.4 … 0.6; by hour of day 0.484 … 0.492 — flat; the cross-name mean per hour has sd
  0.030 and an autocorrelation at 24 h of 0.01), the within-name sd 0.10 … 0.13, the autocorrelation at 1 h median 0.07 (no name above
  0.3) and at 24 h 0.02; its deviation from the trailing month (cb_ext's DEV form) is the series itself (dev_sd 1.02, acf 24 h 0.01). The
  TRAILING-DAY share (Σ taker-buy quote over Σ quote of the last 24 bars): sd 0.032 within a name, autocorrelation at 24 h 0.15 (XRP
  0.40), the deviation's 0.10. **Correlation with `cbprem_dev` on R62's kept names: +0.01 hourly, +0.005 daily (no name |corr| ≥ 0.2) — not
  the Coinbase deviation again, by a mile**; cross-name mean correlation of the deviations 0.07 / 0.06 — a name-specific quantity.
- **The spot/perp ratio** (the log of the spot quote volume over the perpetual's in the same hour): spot turnover is ≈ 21 % of the
  perpetual's on the median name (the spot share of spot + perp 17.5 %; BTC 12 %, XRP 25 %; no name has spot above perp), within-name sd
  0.46 log hourly / 0.34 daily, PERSISTENT (autocorrelation at 24 h 0.53 hourly / 0.85 daily; the deviation's 0.25 / 0.56), an hour-of-day
  shape of ≈ 0.1 log (the spot share highest 07 … 12 UTC, lowest 00 … 05); **correlation with `cbprem_dev` −0.055 hourly / −0.08 daily
  (p10 −0.10 / −0.15; the extreme BNB +0.33) — not the Coinbase deviation again**; cross-name 0.10 / 0.15 (a common component in the daily
  form — the market's spot share moves together; a within-hour rank removes it). The two ratios' deviations are near-orthogonal (0.02 / 0.06).
- **Rule for any feature:** `ts_known` = the bar's start + 1 h; a trailing-day form reads 24 closed bars (≥ 20 present); STRAX and 0G are
  the two different-asset / thin series by the stamp check; a registration names its forms and signs in advance (decision BI).
- **Read (R73 / R74, 2026-11-01):** the `count` and `quote_volume` columns of the kept members' hours were summed with the perpetual's (`perp_mix_1h`) and joined to P2's labels once on F1+F2 (R73, 2023-05 → 2024-08) and once on F3+F4 (R74, 2024-09 → 2025-12; the guard rows in the ledger first); the fingerprint 6,279,915 rows / 272 symbols equal before and after both runs; the spot's share of the two markets' count 0.17. The F5 rows (2026) unread by any registration.

### hl_funding_1h, premium_1h (Hyperliquid's hourly funding and mark premium per name, the twelve's and the screener's members' coins; Binance's own 1h premium index beside; decision BJ2, §9 #12) — `data/hl_funding_1h.parquet`: `(coin, symbol, ts, ts_known, stamp, lag_s, rate, premium, frozen)`; `data/premium_1h.parquet`: `(symbol, ts, ts_known, open, high, low, close)`

`ft2 hl symbols|fetch|bnprem|ingest|audit` (`scripts/bj2_chain.sh`; raw `data/raw/external/hyperliquid/funding/<COIN>.json` one file a coin,
resumable, `.done` when complete; the listing `symbols_<date>.json` beside; Binance's month files under `data/raw/external/binance/premiumIndexKlines/<sym>/`
as `<sym>-1h-YYYY-MM.zip`, next to R20's 5m ones). The source: the venue's public info API (`POST api.hyperliquid.xyz/info`, keyless; `meta` the
listing, `fundingHistory` 500 rows a call at weight 20 of 1,200 a minute — 60 calls a minute, ≈ 0.9 s of latency each). **One row a funding
SETTLEMENT: every 8 hours from the venue's start 2023-05-12 to 2023-06-25, HOURLY since**; `premium` the venue's mark over its oracle (the hour's
sample average, a fraction; × 1e4 = bps), `rate` the funding paid at that settlement (the premium plus the interest term, clamped; per hour since
2023-06-25, per 8 hours before). `ts` = the settlement HOUR (the stamp floored), `ts_known` = `ts`: the row describes the hour ending at `ts` and
appears `lag_s` after it — **0.05 s median, 0.42 s at p99, 0.67 s at most on ordinary rows; on five dates every name's row came late at once
(2023-05-23 24 min, 2023-09-27 111 s, 2023-12-17 251 s, 2025-07-19 888 s, 2025-07-27 111 s)** — a feature reading at the hour misses those 469
rows of 3.4 M. The coin per perpetual: the base (`coinbase.base`), else `k<BASE>` (kPEPE, kSHIB, kBONK, kFLOKI, kLUNC, kNEIRO, kDOGS — the venue's
thousand-token contracts), else the alias JELLY (JELLYJELLY); **181 of the 322 symbols have a coin, all twelve among them; 32 are delisted there**.
The venue's PRICES are not in this source (its candle endpoint serves recent bars only; the S3 archive is not fetched) — nothing here is priced.
**Fetched 2026-10-23 on the work VM 07:14 → 09:11 UTC** (7,479 pages, 3.7 M rows, 0 errors; the first launch at a 1.1 s pause stopped after
three coins and relaunched at 0.15 s — the resumable steps picked up), Binance's 1h premium 09:11 → 09:22 (5,660 month files, 1,942 missing = the
listings after 2023-04; 4,080,440 bars 2023-04-01 → 2026-09-30), ingested 09:22 (3,737,038 rows 2023-05-12 → 2026-09-15), audited 09:22 → 09:24;
**the frozen-row mask added and the ingest + audit rerun 09:33 → 09:35** (the first audit, without it, counted the frozen rows as coverage;
overwritten). **Measured (`output/hl_audit.md` / `.json`, `hl_quantities.parquet` — the seven quantities, their deviations, Binance's premium
deviation, `cbprem_dev` and R68's two per (ts_known, symbol)):**
- **FROZEN rows — the trap of this source.** A coin delisted on the venue keeps emitting a settlement row every hour with a premium of EXACTLY 0
  for as long as the API is asked: STRAX 805 days of zeros after its last live row (2024-07-01), RNDR 785, MATIC 735, LOOM 641, BLZ 631, FTM 610,
  JELLY 537 (after 2025-03-26), eleven names frozen since 2025-04-11, …; 32 delisted names and 7 live ones with runs of zeros (HMSTR 30 % of its
  rows) — 317,826 rows of 3,737,038 (8.5 %) in 39 names. `frozen` = inside a run of ≥ 24 consecutive settlements at a premium of exactly 0
  (`hl.frozen_mask`); `hl.load` drops them by default and the audit reads them as absent (`last` is the last live row). A live name's zero share
  is 0.15 % (median).
- **Listing and history.** The first row on 2023-05-12 for 16 names, in 2023 for 81, 2024 for 55, 2025 for 41, 2026 for 4; 27 names have rows in
  the 8-hour weeks (up to 81 rows each); 32 names' live rows end before 2026-09 (the delistings: 5 in 2024, 17 in 2025, 10 in 2026). Completeness
  over 2023-05-01 → 2026-09-15 median 77 % (the late listings and the 8-hour weeks; no name 99 %: the venue starts 11 days into F1 and settles
  8-hourly for its first six weeks). Interior holes after the hourly regime began: the median name 1 gap over an hour, the largest 2 h on the
  majors; a few young names with holes up to 614 h.
- **The members' cover per block** (a member counts with ≥ 90 % of the block's hours): **0 of 60 on F1's first two blocks (2023-05-03, 06-02 —
  the 8-hour regime), then 18, 22, 26, 31, 36, 44, 45, 46, 48, 48, 47, 44, 48, 47, 50, 52 of 60 on F1+F2's remaining sixteen; 46 … 57 of 60 on
  F3+F4's seventeen** — between Coinbase's 31 … 46 and the spot's 54 … 60 on F1+F2, the spot's equal on F3+F4; 135 of the 169 members with rows
  cover ≥ 90 % of their own member hours, 20 between 50 and 90 %, 14 under 50 %.
- **The stamp check** (the venue's hour premium against Binance's 1h premium bar's open-high-low-close mean, by lag): **the best lag is 0 on 159
  of 181 names**, the lag-0 correlation median 0.69 (p25 0.61, p75 0.83; the profile by lag 0.56, 0.61, 0.65, **0.69**, 0.67, 0.63, 0.59 at −3 … +3);
  the 21 names whose best lag is ±1 or +2 have a flat profile (the lag-0 correlation within a few hundredths of the best — an hour average against a
  bar, not a shifted stamp; LINK 0.65, AVAX 0.64, LTC 0.68 among them). The stamps agree. The level: the venue's premium 0.6 bps ABOVE Binance's
  (median across names; p25 0.0, p75 1.6).
- **The funding check** (Binance's settled rate at each of its funding times against the venue's settlements summed over the same period, ≈ 3,000
  settlements a name): **correlation median 0.74 (p10 0.54, p90 0.93) on 179 names — the same quantity on two crowds at the 8-hour scale**; the
  venue pays more: 7.1 % a year against Binance's 3.7 (medians); HYPE the exception (0.04 — the venue's own token, its funding there pinned near the
  interest term, sd 0.7 bps a settlement), XPL / PUMP / PAXG young or thin (0.16 … 0.23).
- **The quantities on R62's 85 kept names** (bps; the level's median across names, the within-name sd, the autocorrelation at 1 h / 24 h, the
  deviation's sd and 24-h autocorrelation): `hl_prem` −1.1 (p10 −3.7, p90 +1.5; Binance's `bn_prem` −2.7), sd 6.8, 0.92 / 0.59, dev 1.16 / 0.49;
  `hl_fund` +0.08 an hour (≈ 7 % a year), sd 0.59, 0.85 / 0.40; `hl_prem24` (the trailing-day mean) sd 5.7, — / 0.83, dev 1.24 / 0.69; `hl_fund24`
  (the day's funding paid) +1.9 a day, sd 10.2, — / 0.71, dev 1.29 / 0.54; **`gap24` = `hl_prem24` − `bn_prem24`, the cross-venue lean: +1.6
  (p10 +0.4, p90 +3.3; the twelve +0.8 … +4.0 — the venue above Binance on every name), sd 3.4, — / 0.67, dev 1.16 / 0.56.** Twenty names have a mean
  premium past 5 bps (0G −22.5, AXS −15.8, OM / AVNT / MOVE ≈ −11, with sd 20 … 55 — thin or dying markets). Flat by hour of day (−1.8 … −1.5;
  Binance's −3.3 … −2.5).
- **Is it Binance's own premium again (R20 / R21's quantity, closed at 1d)?** At the HOUR half-shared: `hl_prem_dev` against `bn_prem_dev` median
  0.40 (p10 0.29, p90 0.52; 15 % of names ≥ 0.5). **At the DAY largely the same quantity: `hl_prem24_dev` against `bn_prem24_dev` median 0.65
  (p10 0.51, p90 0.76; 92 % of names ≥ 0.5), `hl_fund24_dev` 0.57 (76 %)** — by the audit's own rule (|corr| ≥ 0.5) the trailing-day forms ARE
  Binance's premium on another crowd. **The gap is a quantity of its own: `gap24_dev` against `bn_prem24_dev` −0.07, `cbprem_dev` −0.02, `tb24_dev`
  +0.04, `sr24_dev` +0.07 — orthogonal to every quantity read on the members**, cross-name mean correlation 0.15 (the premiums' 0.25 … 0.31: the
  market's lean, which the gap mostly removes). Against the Coinbase deviation every perpetual premium is NEGATIVE (`hl_prem_dev` −0.28, Binance's
  own −0.41: a spot-over-perpetual premium falls when the perpetual's premium rises — arithmetic, not information); against R68's two, nothing
  (`tb24_dev` +0.04) and little (`sr24_dev` +0.18).
- **Pooled:** the venue's premium's cross-name mean per hour −2.2 bps (p10 −6.4, p90 +6.3, sd 5.3, autocorrelation at 24 h 0.87), Binance's −3.3
  (sd 4.5, 0.75); the two means' correlation 0.85 — the crowd's market-wide lean is the same crowd's.
- **Rule for any feature:** read a row at its settlement hour (`ts_known` = `ts`) and tolerate the five late dates; a trailing-day form reads 24
  settlements (≥ 20 present); frozen rows are absent; the 8-hour weeks (2023-05-12 → 06-25) carry no hourly form; a registration names the form,
  the sign and the universe in advance (decision BK). `premium_1h` is Binance's own premium index per hour (the archive's bar; a bar starting at H
  read at H + 1 h) for every symbol of the listing, 2023-04 → 2026-09 — R20's 5m file (to 2024-08) is untouched.

### wiki_views (Wikipedia's daily pageviews of the token's article — attention per name from OUTSIDE every exchange; decision BP1, §9 #14) — `data/wiki_views.parquet`: `(base, symbol, article, day, views, present, ts_known)`; the article list FROZEN by hand `ft2/wiki_articles.csv` `(base, symbols, article, source, note)`

`ft2 wiki names|articles|probe|fetch|ingest|audit` (`ft2/wiki.py`; `scripts/bp1_chain.sh`; `tests/test_p8_wiki.py`). **Source:** the Wikimedia REST
API, per-article daily pageviews (`metrics/pageviews/per-article/en.wikipedia/all-access/user/<title>/daily/<from>/<to>`; free, keyless, a
User-Agent required; daily from 2015-07; one request per title for the whole range). **The universe:** the 322 bases of the twelve and of the
310 member bases (`coinbase.base`). **The names** (output/wiki_names.csv, 711 for 322 bases): the Korean venues' `english_name` from the saved
market lists (217) and CoinGecko's keyless `/coins/list` ranked by `/coins/markets` (494). **The articles:** every name and its "(cryptocurrency)"
/ "(blockchain)" suffix resolved on en.wikipedia with redirects and the intro's first sentences (the Wikipedia action API at ≈ 1 request a
second: 44 min on the work VM), plus the search API's top hits — 2,800 candidates, 946 exist (output/wiki_candidates.csv); the proposed pick
(output/wiki_pick.csv) was CHECKED BY HAND 2026-10-29 and frozen: **66 of 322 bases have an article — 34 the token's or protocol's own, 20 the
chain's, 4 the developer company's (Aptos Labs, Immutable, StarkWare, Numerai), 8 a meme coin's NAMESAKE (`source = proxy`: Bored Ape for APE,
Pepe the Frog for PEPE, Moo Deng, Peanut (squirrel), Chill Guy, Popcat, Comedian (artwork) for BAN, Vine (service)) — attention to the thing,
not the coin, counted apart; 63 distinct articles (Terra (blockchain) serves LUNC / LUNA2 / USTC, Polygon (blockchain) MATIC / POL); 256 none.**
Checked directly against the API 2026-10-29: Arbitrum, MakerDAO, Cosmos (blockchain), DFINITY / Internet Computer, Curve Finance, Synthetix,
Kyber Network, Ethereum Name Service, Fetch.ai, SingularityNET, Bittensor, THORChain, Starknet, ZKsync, LayerZero, Lido DAO, dYdX, SushiSwap,
Notcoin, Hyperliquid, Ondo Finance have NO article on en.wikipedia; Dogwifhat, Floki Inu, Fartcoin, Baby Doge Coin and Memecoin redirect to the
generic "Meme coin" (rejected); "Optimism (blockchain)" redirects to Ethereum; "Binance Coin" to the exchange (BNB takes the chain's article).
The 130 picks the search API proposed were almost all generic ("Cryptocurrency", "Tether", "Cryptocurrency and crime") and were rejected.

**Traps found on the way (both fixed before any number was read):** (i) **pageviews are counted under the TITLE OF THE DAY** — a renamed
article's history sits under its old names, which stay as redirects: the first fetch (the articles alone) showed 45 … 65 % empty days and a
median of 0 views on DOT, HBAR, LINK, NEO, TON, TRX, XRP, WLD, ARKM. The fetch now takes every title that redirects to the article
(`prop=redirects`; redirects.json; 343 titles beside the 63) and the ingest SUMS the article with its redirects per day (`present` = any title
had the day; redirect_share.json). The share of views that came in under a redirect: median 0.018, but above one half on 11 articles (TON 0.91,
NEO 0.84, Chill Guy 0.80, Hedera 0.79, Polkadot 0.75, Chainlink 0.75, Arkham 0.73, Tron 0.72, NEAR 0.61, World 0.61, XRP Ledger 0.58). (ii)
**the REST API is cached** (Varnish): the same URL answers for hours with the first response and its `Date` — the probe's asked start carries
the current hour; `Age` recorded. (iii) 8 fetch threads tripped the API's 429 on 14 of 406 titles (retried at 3; `THREADS = 3`). (iv) The API
OMITS days without data: zeros are filled from the later of 2021-12-01 and the article's creation (the first revision, which follows a move).

**Extent (2026-10-29, the work VM 20:55 → 21:38 UTC):** 93,994 rows, 66 symbols / 63 articles, 2021-12-01 → 2026-10-28, `ts_known` = day +
48 h. **Known-at, measured:** two probes on Bitcoin — at 19:45 and 20:55 UTC on 10-29 the API held 10-28 (19.8 h and 20.9 h after that day's
end) and NOT 10-29; the day's count arrives somewhere between the day's end and +19.8 h. **The UTC-morning probes (R72's two-valued rule):**
probe 1, 2026-10-30 06:00:34 UTC server Date, Age 0 (a fresh answer), last day present 2026-10-29, 6.01 h after that day's end — the previous
day's count IS present by 06:00 UTC on the first morning; probe 2, 2026-11-01 06:00:30 UTC server Date (the 10-31 morning was missed; the
rule asks two different days, not consecutive ones), Age 0, last day present 2026-10-31, 6.01 h after that day's end — the same on the second
morning. **THE STAMP IS 36 h** (`ts_known(d)` = d + 36 h, `KNOWN_AT_H = 36`, set 2026-11-01 before the run; the parquet re-ingested with
`--end 2026-10-29` so the rows, symbols, days and the sum of `views` are unchanged — a default `ingest` would have extended the grid to
10-31 and broken R72's fingerprint); the probes' JSON under `data/raw/external/wikipedia/probe_*.json` on the VM. **Coverage:** the twelve 11 of 12 (10 strict — HYPE none, PEPE the frog a proxy);
F1+F2's 188 members 39 (38 strict); F3+F4's 216 members 45 (38 strict); per block of 60 members: F1+F2 18 … 25 with an article (median 21;
strict 20; created AND with a day of views by the block's start — median 16, min 13), F3+F4 19 … 26 (median 24; strict 21; live 21, min 14).
20 of the 66 articles were created during or after F1 (AAVE 2023-06, GRT 2023-08, INJ 2023-09, PENGU 2024-02, IMX / ARKM 2024-04, CAKE
2024-08, MOODENG 2024-09, WLFI / CHILLGUY 2024-10, PNUT / PUMP / APT 2024-11, TRUMP 2025-01, 1INCH 2025-07, BNB / NEAR 2025-10, HMSTR 2025-12,
PYTH / SUI 2026-06). **Level:** the median article has 122 views a day (Bitcoin 5,466; 12 articles under 20 — noise at that size); days present
median 1.00; the thin ones 1INCH 0.27 (a 2025 stub, median 0 views), AAVE 0.43 (created 2023-06-11, no redirects, 59 % of days empty — deleted
and recreated, or a stub), PYTH 0.88 and SUI 0.68 (2026 stubs). **The DEV form** (log(1 + views) against its trailing 30 days in sd units, ≥ 15
days): within-name sd 1.09, acf1 0.51, acf7 0.27, |dev| ≥ 2 on 6.4 % of days; across names the deviation's mean correlation 0.17, the first
eigenvalue's share 0.21 — one modest common attention factor (a relative form removes it).

**Rule for any registration: the feature is `wiki_dev` (or another form) of a day's views read at `ts_known` = day + 36 h and no earlier (measured 2026-11-01, above; 48 h before the probes); the
cells the members with a STRICT article (own / chain / company) — a proxy is a described row; the twelve's articles are described, never a
cell (BB's clause: nothing on the twelve before R17); the audit's counts (≈ 20 strict names a block on F1+F2, 16 live at the block's start)
are the registration's; nothing here was joined to a price.** Decision BQ DECIDED "BQ1" 2026-10-30: **R72 (PLAN §8) is the registration** — `wiki_dev` on the 38 strict F1+F2 members, one cell, sign NEGATIVE; the stamp 48 h, or 36 h if the UTC-morning probe on TWO days shows the previous day's count present by 06:00 UTC (R72's Data line — the probes' results and the chosen stamp are recorded HERE before the run; nothing else of this section changes). **R72 READ 2026-11-01 (PLAN §8): NOT DETECTABLE** — relative 1d IC −0.0023 (t −0.22, se 0.0103, p_family 0.816; the folds' signs differ); validity PASS, the parquet's fingerprint 93,994 rows / 66 symbols / 2021-12-01 → 2026-10-28, the sum of `views` 45,821,671 (the run's number is the record), the stamp 36 h in every row; 31 of the 38 strict F1+F2 names carried a value (AAVE's every scored day 0 views; 1INCH, SUI, PYTH, APT, BNB, NEAR, IMX no cells), 12 … 18 a block. The attention line PARKED (PLAN §7); the series stays in hand; F3+F4's 38 strict members unread. Seen after the read (described, unregistered): the directional 1d row +0.044 (t 2.35) and the vol row at every horizon (t 2.4 … 3.4) — the market's attention, which the relative form removes.

### fund_freq_events (the FUNDING-SETTLEMENT-FREQUENCY CHANGE of a running Binance perpetual as a per-name RULE event — read off `funding_archive`'s `interval_h`; decision BU1, §9 #15) — `ft2/fundfreq_f34.csv`, `ft2/fundfreq_f5.csv` (FROZEN 2026-11-01, commit 30ef385, before any bar after an event was read for anything): `(symbol, base, mult, t0, ts_known, fold, dir, prev_h, new_h, perp_first, perp_first_source, perp_age_days, member_at_t0, fund_1d, fund_7d, n_1d, at_floor, cap_share_7d, batch, pair_of, episode_h, notice_release, notice_lag_h)`

`ft2 fundfreq events|notices [--fetch]|bars [--fetch]|audit` (`ft2/fundfreq.py`; `scripts/bu1_chain.sh`, `bu1_audit.sh`, `bu1_fetch.sh`, `bu1_cost.sh`;
`tests/test_p8_fundfreq.py`). No new source: an event is a settlement of `funding_archive` (598 names) whose `interval_h` differs from the
previous settlement's of the same name — **t0 = the FIRST settlement at the new interval**, a SHORTENING (the interval falls) or a LENGTHENING
(it rises). **The rule behind it, read from the exchange's own notices (catalog 49 on disk, `data/raw/external/binance_cms/list_49_*.json`;
81 "Settlement Frequency" / "Funding Rate" titles, their 81 detail pages fetched from the VM 2026-11-01 into `…/binance_cms/detail/`,
`output/fundfreq/notices.csv` 147 (notice, contract) rows):** until 2025-08 a change was announced per contract ("… Will Be Adjusted",
"… Will Be Resumed" — RVN, MASK, … on 2025-07-18); **from 2025-09-01 the revert is automatic** — "if the funding rate of a contract on hourly
settlement is ≤ |0.002 %| for 36 consecutive cycles, Binance Futures reverts the frequency to four hours on the 37th"; from 2026-01-02 the
same at |0.025 %| for 16 cycles. **Known-at: t0 is the settlement's own stamp (`fundingTime`), public at that second; `ts_known` = t0; the
decision bar of any registration is the first 5m bar that CLOSES after t0, the position entered one bar later.** A 2025-09-18 notice
(released 09-16) changed the funding FORMULA and the mark-price calculation — a caveat for every funding quantity across F4.
**The event rule:** the contract ≥ 30 days old at t0 (its first 5m bar in `candles_5m_archive`, every eligible event `archive 5m`; younger =
a launch, R28's population — 111 of the 318 changes, the launch-era interval settings); ELIGIBLE = that AND t0 inside F3 … F5 (decision BU3:
F3+F4 the FIRST read by registration, F5 the confirmation). F0 … F2's 33 are listed in `output/fundfreq/events.csv` and not frozen: **F1+F2
holds 60 shortenings, 14 of them the batch of 2023-10-12 (a policy change at zero funding, `batch`) and most of the rest launch-era — another
population, which is why BU3 exists.** Flags: `fund_1d` (the sum of the settled rates over the 24 h before t0 — the crowded side's sign; a
negative sum = the shorts paid), `fund_7d`, `at_floor` (fund_1d < 0), `cap_share_7d` (the share of the 7 days' settlements at ≥ 95 % of the
name's largest |rate| before t0), `member_at_t0` (a member of the screener's block holding t0 — F5 has no blocks), `pair_of` / `episode_h`
(a lengthening's shortening and the hours between), `notice_release` / `notice_lag_h` (the last notice naming the contract within 14 days
before t0; the rule era has none).
**Counted 2026-11-01 (`output/fundfreq/audit.md` / `.json`, `events.csv`, `bars.csv`, `runup.csv`, `costs.csv`; the chains 14:31 → 14:59
UTC on the work VM):** 318 changes on 172 names, **174 ELIGIBLE — F3 17 shortenings + 6 lengthenings, F4 54 + 39, F5 27 + 31: F3+F4 71
shortenings on 63 names, F5 27 on 25.** The trailing-day funding at a shortening is NEGATIVE on F3 15 of 17, F4 51 of 54, F5 27 of 27 (the
five others: BROCCOLIF3B +1.07 % and CTK +0.03 % of 2025-04, CUDIS +2.02 % and HIPPO +2.24 % of 2025-11, LIT's day empty); |fund_1d| q10 / q50 /
q90 1.98 / 2.64 / 5.12 % a day — the shorts paying 2–5 % a day and from t0 paying it 4 × (4h → 1h 43 of F4's 54, 8h → 1h 10; F3's 4h → 2h 9,
8h → 4h 7) to 8 × as often. The trigger row: the median name had 2.4 % of its week's settlements at its cap (the rate pinned at the cap is NOT
what triggers the change; the cap row is described, not the mechanism). The contract's age at t0 q10 / q50 / q90 54 / 277 / 1,357 days (15
under 90; F5's names old — median 1,396). Members of the block at t0: 9 of the 71 (REEF, BAN, LAYER, MASK, MYX ×2, BIO, AIA, LIGHT) — the
events are mostly NON-members (the hedge is the block's members either way). t0's hour: the 4-hour clock (01 / 05 / 09 / 13 / 17 / 21 UTC)
and the 8-hour one. **The notice era against the rule era:** 32 F3+F4 shortenings before 2025-09-01, 18 with a notice naming the contract
(lag q10 / q50 / q90 0.4 / 2.4 / 23.5 h; MYX's two 69 / 148 h are an earlier notice's), 14 without (2025-04 → 08: CTK, LAYER, BROCCOLIF3B,
LPT, WCT, RVN, MASK, FUN, VIC, HYPER, XTZ, API3, M, IP — the manual era's changes the lists' titles did not match); 39 in the rule era (2025-09
1, 10 5, 11 16, 12 17), none with a notice. The 45 F3+F4 lengthenings are every one paired to a shortening (the episode 63 / 699 / 1,735 h at
q10 / q50 / q90). **The run-up row (described, the 24 h BEFORE t0 only):** the name against its block's members +3,352 bps at the median
over the day before a shortening (q10 −2,877, q90 +12,780; F3 +3,756 / F4 +3,323; 72 % of events ≥ +2,000, 57 % ≥ +500, 20 % below zero) —
the shortening lands on a name that just rose a third against its peers in a day with the shorts paying the longs: a squeeze the rule flags.
**The bars:** `candles_5m_archive` held 91 of the 116 F3+F4 events' windows (the slice's non-member names ended 2024-08); the F3+F4 events'
missing months fetched 2026-11-01 (`fundfreq bars --fetch`, 25 names, R28's route) and the slice re-ingested whole under krlist's fingerprint
(PASS: 598 names before and after, every old row back; 83,541,041 rows, to 2026-01-31 — December's windows reach into January, so 5 F5
events of January have bars; F5's 2026 months are decision BV's own fetch) — **F3 23 of 23, F4 92 of 93 (LIT 2025-12-23 at 93 % — its
window runs past the slice's end), F5 5 of 58.** **The cost rows:** `costwide` run on the 90 event names from 2023-01-01 and MERGED into the
pre-BU1 parquet (`scripts/costwide_merge.py`: 35,628 overlapping rows identical to 0.0, 871 rows added, 584 names → `data/cost_daily_wide.parquet`,
the old copy `data/cost_daily_wide_before_bu1.parquet`; a first `--universe all` re-run was VOID by `scripts/costwide_check.py` — `all` does
not cover 7 of the old names); the shortenings' taker round trip on t0's day 18.8 bps at the median, on the day before 42.1 (the squeeze day
is dearer); missing on day 0: AERGO 2025-04-16, CTK 2025-04-30 and LIT (no bars) on F3+F4, every F5 event.

### F5 Data line for R76 (decision BW1, 2026-11-01; `ft2 fundevent data`, `scripts/bw1_fetch.sh`, 18:12 → 18:35 UTC on the work VM; `output/listing/r76_data/`)

Nothing read: the names are the frozen F5 list's 32 (`ft2/fundfreq_f5.csv`: 25 shortening names + 7 lengthening-only), F4's last member
block (2025-12-29, 60 names, the hedge basket carried forward into 2026) and BTC — 91 names. The 2026-01 → 2026-09 monthly 5m klines
from the archive (812 files fetched, 7 already on disk, 0 bad / missing); `candles_5m_archive` re-ingested whole under `krlist.fingerprint`
(PASS: 598 names before and after, 0 changed): 90,633,329 rows, 2019-12-31 → 2026-09-30 23:55. `funding_archive`: the names' newer rows
appended (47,757 rows on 83 names; every old row identical; the parquet 1,900,834 rows, 598 names, to 2026-09-30 23:00; 26 (name, month)
fundingRate files absent at the archive — listed after or delisted before). `cost_daily_wide`: `costwide --symbols` for the 91 names merged
into the parquet it replaced (78,767 new rows on 90 names, 55,278 overlapping rows identical to 0.0; 295,984 rows, 584 names; the old copy
`data/cost_daily_wide_before_bw1.parquet`, the funding's `data/funding_archive_before_bw1.parquet`). Coverage: all 58 F5 event windows
(t0 − 2 d → t0 + 8 d) complete at ≥ 95 %; every one of the 91 names at 100 % of the bars over 2026-01-01 → 2026-09-15. F5's end for R76:
2026-09-15 (the fold as defined; frozen at R76's read).

### fund_episodes (the EXTREME trailing-day funding of a running Binance perpetual WITHOUT the exchange's flag, as a per-name EVENT population — read off `funding_archive`'s settled rates; decision BY1, 2026-11-02) — `ft2/fundep_f12.csv`, `ft2/fundep_f34.csv`, `ft2/fundep_f5.csv` (FROZEN 2026-11-02, commit 7cf47a1, md5 75c0fbd0… / f5765782… / c1770dd4…, before any bar after a t0 was read for anything): `(symbol, base, mult, t0, ts_known, fold, side, thr, rate_t0, interval_h, fund_1d, n_1d, fund_7d, prior_episodes, days_since_prior, perp_first, perp_first_source, perp_age_days, member_at_t0, flag_t0, flag_lag_h, flagged_7d, cap_share_7d, cap_rate)`

`ft2 fundep events [--threshold 0.02]|audit` (`ft2/fundep.py`; `scripts/by1_events.sh`, `by1_audit.sh`; `tests/test_p8_fundep.py`; the brainstorm's count
`scripts/by_count3.py`). No new source: per name the 24-HOUR ROLLING SUM of the settled rate over `funding_archive` (598 names), the window
(ts − 24 h, ts] — the settlement's own rate counted, it is public at its stamp; **an EPISODE = the FIRST settlement at which |sum| ≥ 2 % a day,
and a new episode of the name only after 14 days without a settlement at or over the threshold** (a run of extreme days is one episode, its t0
the first crossing); the contract ≥ 30 days old at t0 by the EARLIER of its first 5m bar in `candles_5m_archive` and its first settlement (the
slice holds some non-members from 2023-04 only; `fundfreq` took the bar first — under the count's rule, the first settlement alone, 524, under
this one 525: one F0 episode moves). **Known-at: t0 is the settlement's own stamp (`fundingTime`), public at that second; `ts_known` = t0; a
registration's decision bar is the first 5m bar that CLOSES after t0, the position entered one bar later (R75's entry).** `side`: `bought`
when the sum is negative (the shorts paid — a long receives), `sold` when positive. Flags: `rate_t0` / `interval_h` (the crossing settlement's
own), `fund_1d` / `n_1d` (the sum and its rows: 3 on an 8-hour clock, 6 on a 4-hour one), `fund_7d`, `prior_episodes` / `days_since_prior`
(the name's earlier episodes at this threshold), `member_at_t0` (a member of the screener's block holding t0 — F1+F2's and F3+F4's 60;
F5 has no blocks), **the FLAG `flag_t0` / `flag_lag_h` / `flagged_7d` — a `fundfreq` SHORTENING of the name within ± 7 days of t0, the
exchange's answer (R75 / R76's events)**, `cap_share_7d` / `cap_rate` (fundfreq's trigger row). ELIGIBLE = the age AND t0 in F1 … F5, frozen
per fold pair (f12 R77's exploration list, f34 R78's confirmation, f5 a later one's); FP / F0's 48 and the 2 after F5's end are listed in
`output/fundep/events.csv`, not frozen.
**Counted 2026-11-02 (`output/fundep/audit.md` / `.json`, `events.csv`, `events_described.json`, `eligibility_f12.csv` / `_f34.csv` / `_f5.csv`;
the two chains 08:35 → 08:37 UTC on the work VM, 12 s and 15 s of compute):** 525 episodes on 230 names, **475 ELIGIBLE on 216 names —
F1 30 + F2 30 (all `bought`, 41 names), F3 100 + F4 209 (296 bought, 13 sold; 175 names), F5 106 (all bought)**; members at t0 F1 9, F2 3,
F3 10, F4 21, F5 3; **flagged within ± 7 days F1 6, F2 1, F3 12, F4 45, F5 31 = 95 of 475** — the flagged events are a fifth of the population
and the flag came AFTER the crossing in 77 of 95 (the lag q10 / q50 / q90 −39 / −1 / 0 h; before it in 4): the exchange's rule answers the
same condition this list reads at its first settlement. The interval at t0: 8h F1 25 / F2 10 / F3 32 / F4 22 / F5 36, 4h 4 / 20 / 66 / 164 / 65,
1h F4 23 / F5 5 (names already shortened), 2h 3. |fund_1d| at t0 q10 / q50 / q90 2.04 / 2.29 / 3.22 % a day (F1+F2 2.04 / 2.49 / 3.52; the
flagged shortenings' 2.64); the rate at t0 0.23 / 0.86 / 2.0 % a settlement (F1+F2 0.31 / 1.5 / 2.5); |fund_7d| 1.99 / 2.69 / 4.7 %. The
contract's age 68 / 448 / 1,797 days (F1+F2 123 / 542 / 1,122). Prior episodes: 196 first, 124 second, 69 third, 86 fourth or later (the
days since the prior 24 / 84 / 478); on F1+F2 33 first, 27 repeats (ONG, OGN, API3, TRB, GLM, NMR three each; the same-name gaps ≥ 16 days —
no two cells of a name inside one 7-day hold). The trigger row: the median name had 0 % of its week's settlements at its cap (q90 4.8 %) — the
rate is extreme by the day's sum, not pinned. t0's hour: the 8-hour clock (00 / 08 / 16 UTC: 295) and the 4-hour one (04 / 12 / 20: 155); 25
off-grid. F1+F2 per month 1 … 9 (2023-08 and 09 seven each, 2024-08 nine; 35 weeks of 70 hold an event). **The eligibility rule on the frozen
F1+F2 list (R75's frame: the decision bar at t0 + 5 min, the entry at t0 + 10 min, the 7-day exit before 2024-09-01, the first member block
2023-05-03, bars ≥ 95 % over t0 − 2 d → t0 + 8 d, `cost_daily_wide` on the entry day or the day before): 58 of 60 eligible — the two dropped
NAMED: 1000FLOKI 2024-08-30 00:00 and RDNT 2024-08-30 16:00 (the 7-day exit past F2's end; RDNT's window also holds a third of its bars); every
one of the 58 bought, with its own cost row on the entry day or the day before (58 of 58), bars complete; F1 30, F2 28; 11 members at t0; 7
flagged.** F3+F4 (R78's Data line, BU1's route): 294 of 309 pass the calendar (15 December-2025 cells' exits pass 2026-01-01), 254 of 309 have
their bars (F3 73 of 100, F4 181 of 209) — 41 names short, 78 (name, month) 5m files to fetch, then `costwide --symbols` for the names;
F5: 105 of 106 pass the calendar, 67 of 106 have bars — 29 names, 45 files. **R78's Data line RUN 2026-11-02 (PLAN §8 R78's Data line;
`output/listing/r78_data/`): the 78 files fetched and the slice re-ingested whole (91,257,137 rows, 598 names) — R28's extent fingerprint
read 11 of the 41 names as changed because their fetched months were HOLES inside their old extent; `krlist.rowcheck` (every old row re-derived
from the pre-existing zips back in the slice unchanged: 0 missing, 0.0 difference on the 11) is the rule for fills from here; `costwide
--symbols` for the 175 names of the f34 list merged (+1,942 rows, the overlap identical); after: 309 of 309 windows complete, own cost rows on
294 of 296 bought-side cells; the funding archive untouched (six delisted names' rows end before their last cell's exit).** Described
thresholds (counts only, never frozen): ≥ 1 % 992
episodes on 346 names (F1+F2 112, F3+F4 506, F5 169; 886 bought); ≥ 3 % 332 on 180 (F1+F2 43, F3+F4 203, F5 68).

### upgrade_events (the scheduled NETWORK UPGRADE / HARD FORK of a name, dated by the exchange to the minute, as a per-name EVENT — Binance's CMS catalog 157 "Maintenance Updates"; decision CD1, §9 #16) — `ft2/upgrades_f12.csv`, `ft2/upgrades_f34.csv` (FROZEN 2026-11-04 — first 3ab5dcd, re-frozen the same session after two mapping corrections found by the bars count, md5 511494694fdf206c30738eff20e4a2d9 / da570f4c030b8887c5e8bdc2b89a81cf; before any bar after a t0 was read for anything); **`ft2/upgrades_f5.csv` FROZEN 2026-11-06 (71c5567, md5 96ad48c443de5848f747ac6d69059bd7; 29 rows on 18 names, t0 2026-01-06 → 2026-08-25, the same rule — `ft2 upgrades events` re-run on the VM, `events.csv` identical; for R82, decision CF2; the F6 rows frozen by the same rule when F6 closes)**: `(symbol, base, mult, t0, ts_known, release, code, fold, block, perp_first, perp_first_source, perp_age_days, member_at_t0, lead_d, hardfork, multi, repeat_n, t_suspend, stated_how, title_date, title)`

`ft2 upgrades list [--fetch]|details [--fetch]|events|bars [--fetch]|audit` (`ft2/upgrades.py`; `scripts/cd1_audit.sh`, `cd1_rowcheck.py`;
`tests/test_p8_upgrades.py`). **The source:** catalog 157 of the exchange's CMS (`www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=157`,
13 pages of 50; reachable from the work VM; 614 titles 2022-02-15 → 2026-10-29, `data/raw/external/binance_cms/list_157_20261104.json`) —
388 titles "Binance Will Support the <Name> (<TICKER>) Network Upgrade [& Hard Fork] [- YYYY-MM-DD]", 362 with a ticker in the title, their
362 bodies fetched 2026-11-04 (`…/binance_cms/detail/<code>.json`, one every 3 s; the CMS answers 429 after ≈ 250 pages and the fetch
waits it out — 2 min, then 4). A two-chain notice ("the MANTRA (OM) and MultiversX (EGLD) Network Upgrades", 43 titles) is one row a
chain (`multi`), each parsed from the sentences naming it: 407 (notice, name) rows. **The event rule:** t0 = the UPGRADE's stated time,
parsed from the body as the first stamp in a sentence naming the upgrade / the hard fork / the block height / "take place" and NOT the
deposit suspension ("The network upgrade and hard fork will take place at the block height of 36,893,881, or approximately at 2025-06-19
01:28 (UTC)") — the suspension's stamp, one hour earlier on 182 of 198 eligible rows (q10 / q50 / q90 of t0 − t_suspend 1.0 / 1.0 / 1.0 h),
is kept beside as `t_suspend` and is NOT the event; an upgrade dated by a block height alone is OUT (21 rows, "the upgrade's time stated
as a block height only"), a body without a stamp OUT (8), a notice released after its stated time OUT (0 of the 348 with a perpetual of
ours), one cell a name per 7 days (a multi-day upgrade's follow-up collapsed, 2). The ticker → the perpetual listed in t0's month
(`um_first_month.csv`; the plain name over a 1000× one; a ticker whose every contract is dead at t0 takes the relaunch `<TICK>2USDT`
— LUNA → LUNA2USDT, the correction of the first freeze: two F1 rows carried LUNAUSDT, dead since 2022-05, with 0 bars); the perpetual's
first bar = the EARLIER of the slice's first 5m bar and the first day of the month after its first month (both upper bounds; the second
correction: after the fetch BTSUSDT's slice held one month, 2023-11, and the slice rule read a 2021 contract as 15 days old); ELIGIBLE =
the perpetual ≥ 30 days old at t0 (21 younger: launches, R28's population) AND t0 inside F1 … F4 (F5's 29 listed in `output/upgrades/events.csv`,
not frozen; 70 before F1 or after F5). **Known-at: the notice's `releaseDate` = `ts_known` — the upgrade's hour is public from then, 1.5
days ahead at the median (lead q10 / q25 / q50 / q75 / q90 0.45 / 0.6 / 1.59 / 5.4 / 9.17 days, none negative); the decision bar of any
registration is the first 5m bar that CLOSES after t0 (t0 on the hour on 62 of the 93 F1+F2 rows, off the 5-minute grid on 10).**
Flags: `fold`, `block` (the screener's block holding t0), `member_at_t0`, `lead_d`, `hardfork` (the title says "Hard Fork"), `multi`,
`repeat_n` (the name's earlier notices in the whole catalog), `title_date`, `stated_how`.
**Counted 2026-11-04 (`output/upgrades/audit.md` / `.json`, `details.csv`, `events.csv`, `bars.csv`, `costs.csv`, `rowcheck.json`; the chain
15:07 → 16:02 UTC on the work VM, the re-runs to 16:28):** 348 notices with a perpetual of ours, **198 ELIGIBLE on 59 names — F1 45 (hard
fork 26), F2 48 (32), F3 47 (29), F4 58 (39): F1+F2 93 on 38 names (members of the block at t0 37, a name's FIRST notice 14, two-chain rows
35; SEI 9, EGLD 7, OP 6, IOTX 5, ZEN 5), F3+F4 105 on 44 (members 22, first 14)**; the perpetual's age at t0 q10 / q50 / q90 237 / 1,028 /
1,729 days (the F1+F2 rows 170 / 918 / 1,365). **The hour:** 115 of 198 upgrades land 12 … 17 UTC (15:00 the mode, 28), 14 at 00:00;
the weekday 0 … 3 (Mon … Thu) 184 of 198 — the chains schedule a weekday afternoon; the title's date is t0's day on 60 of the 66 titled.
**The bars (the window min(release, t0 − 2 d) → t0 + 8 d):** the F1+F2 events' missing months fetched (`upgrades bars --fetch`, 21 monthly
files for 9 names — BTS, CTK ×4, DASH, ETH, IOTX ×5, KLAY ×3, ONE, QTUM ×2, LUNA2 held already) and the slice re-ingested whole
(91,441,457 rows, 598 names, 2019-12-31 → 2026-09-30); R28's extent fingerprint read CTK, DASH and QTUM as "changed" (rows gained INSIDE
their old extent — the fetched months filled holes, R78's case) and `krlist.rowcheck` PASSED all three (every old row re-derived from the
pre-existing zips back identical, `rowcheck.json`); the other 595 names unchanged. **After: F1+F2 93 of 93 complete; F3+F4 63 of 105
(the slice's non-member names end 2024-08 — the confirmation's own Data line, decision CE); the cells a registration can read (0o (i)):
F1+F2 92 — KLAY 2024-08-29's 7-day hold runs past F2's end; F3+F4 63 with bars, 105 inside the market.** **The cost rows** (`costwide`'s
taker round trip, `cost_daily_wide.parquet`): on t0's day for 75 of the 93 F1+F2 rows (median 16.5 bps, q10 / q90 9.7 / 37.9), none for
18 rows of 8 names never in a member block of 2023 … 24 (BTS, CTK, DASH, IOTX, KLAY, ONE, QTUM — and ETH, priced from the twelve's own
cost file at run time): R28's 46 is their bar. **No price of an event's name was read: the run-up, the INTO row (bought at the notice,
closed at the stated hour) and the give-back are R80's.** Decision CD DECIDED "CD1" 2026-11-04: R80 REGISTERED (PLAN §8) on these counts. **R80 READ 2026-11-04 (PLAN §8): the F1+F2 rows' bars after t0 joined to R70's label ONCE — 91 cells, VALIDITY PASS, CLEARS at 1d on the trimmed gate (M_trim −107); the fingerprint before and after 599 names (598 + BTSUSDT, the audit's fetch), 0 changed. F3+F4's 105 rows untouched by R80.** **Decision CE1's Data line (2026-11-04, `scripts/ce1_data.sh`, nothing priced): the F3+F4 windows' 62 missing (name, month) files on 23 names — 60 fetched, 2 on disk — and the slice re-ingested whole (91,964,753 rows, 599 names; the extent fingerprint read seven names as changed — 1000XEC, CTK, ENJ, FLOW, KAVA, MTL, ZIL, holes inside their old extents — and `krlist.rowcheck` PASSED all seven, every old row back at 0.0, `output/upgrades/rowcheck_f34.json`): F3+F4 105 of 105 windows complete, 105 inside the market, 101 cells (ETH's two and ADA's Plomin row the twelve's, ADA's Chang row 2024-09-01 before the F3+F4 members' first block 2024-09-03). The cost rows: `costwide --symbols` for the 44 names from 2023-01-01 merged into `cost_daily_wide.parquet` by `scripts/costwide_merge.py` (30,247 new rows on 41 names; the 28,459 overlapping rows identical to 0.0; 299,714 rows / 584 names after; the before-copy `data/cost_daily_wide_before_ce1.parquet` on the VM): 95 of the 105 rows have a day-0 row — the 10 without: ETH 2 and ADA 2 (the twelve's own file), CTK 3, GLMR, SC, STRAX. The frozen lists untouched (md5 as frozen). R81 REGISTERED (PLAN §8) on these counts and READ 2026-11-04 (the F3+F4 rows' bars after t0 joined to R70's label ONCE, 101 cells, the guard rows R81 and R81/into_window in the ledger; the fingerprint before and after 600 names, 0 changed): NOT CONFIRMED — under the bar. The kind PARKED (PLAN §7); the lists stay frozen, F5's 29 listed and never read.**

### gov_votes (the END of a protocol's GOVERNANCE VOTE on Snapshot, stated to the second, as a per-name EVENT — Snapshot's hub, free, keyless; decision CG1, §9 #17) — `ft2/govvotes_f12.csv`, `ft2/govvotes_f34.csv` (FROZEN 2026-11-06, 003389f, md5 be388f08d0b1e0ab257858659e6cbb72 / dd392bb32e13246092c96aef718af0a2, 3,117 / 2,096 rows; before any bar after an end was read for anything), `ft2/govvotes_f5.csv` (604 rows LISTED, not frozen; md5 58b3ca96a66e0a3cb431ac243f41ba61): `(symbol, base, mult, t0, ts_known, release, code, fold, block, perp_first, perp_first_source, perp_age_days, member_at_t0, lead_d, space, start, duration_d, votes, scores_total, n_choices, winner, passed, kind, flagged, repeat_n, cell_all, cell_big, title)`

`ft2 govlist spaces [--fetch]|proposals [--fetch]|events|bars [--fetch]|audit` (`ft2/govlist.py`; `scripts/cg1_chain.sh` to the freeze,
`cg1_audit.sh` after it; `tests/test_p8_govlist.py`). **The source:** Snapshot's hub (`hub.snapshot.org/graphql`, no key, no limit met):
the `ranking` query pages the 72,273 spaces by activity 20 at a time (`api/explore` answers an empty dict and `spaces(orderBy: …)`
ignores its order — the three probes of decision CG's count); 14,000 paged 21:51 → 22:02 UTC 2026-11-05 (`data/raw/external/snapshot/
ranking_20261105.json`); the proposals of the kept spaces by a `created_gt` cursor, 1,000 a call, 25 spaces a batch (`proposals_20261105.json`).
**The symbol join is NOISE until a rule is applied:** 1,409 spaces carry a symbol of ours with ≥ 5 proposals, on 207 bases, and test
spaces, personal spaces and NFT clubs register our tickers ("Commonwealth Test Space" for DYDX with 182 proposals over dYdX's verified 63,
"cocos" for MATIC, "dcl.governance.test" for MANA, "BTC tests"). The rule (the hand check of 2026-11-06, in the module): a space is the
base's protocol if Snapshot VERIFIED it and its name is the protocol's — 20 verified mismatches EXCLUDED by id with their reason
(`govlist.EXCLUDED`: `fabien.eth` for ETH, deHedge for DEGEN, Hyperlock for HYPER, ZecHub for ZEC …) — or if it is unverified and
hand-KEPT by name (`KEPT_UNVERIFIED`, 21: Fantom, Frax, IoTeX, Loopring, MANTRA, Celer, yearn …); every other unverified space is out
(1,303 of 1,409); the busiest of a base's remaining spaces is its pick (`output/govlist/spaces.csv`, the rest in `spaces_other.csv`).
**101 spaces (80 verified) on 101 bases, 10,988 proposals (10,985 closed).** 882 spaces with a derived or foreign symbol counted as unreached — among them REAL governance spaces the symbol join missed: PancakeSwap (CAKEVOTE, 3,741 proposals), Bancor (VBNT, 563), Frax's `frax.eth` (VEFXS, 521; Frax is in the lists by its unverified `fraxfinancegovernance.eth`), Sushi (SUSHIPOWAH, 233) — a join by NAME would add them; not chased, the lists are frozen DAOs whose token is not the base's symbol (Decentraland /
MANA, Curve / CRV …) are unreached by the join, counted in the audit, not joined. **The event rule:** t0 = the proposal's END (`end`, to the
second — the hour the vote closes and the tally is final), `ts_known` = `release` = `created` (the proposal's creation: its end, choices
and body are public from then), `code` = the proposal's id; the winner = the choice with the largest score, `passed` = the winner reads
as a yes (`PASS_RE`: for / yes / approve / accept …; NaN when no choice reads either way), the title's `kind` by regex in the order
gauge, grant, treasury, listing, parameter, election, else other (described, never a gate); `flagged` = Snapshot's own spam flag (252).
The ticker → the perpetual listed in the end's month (`upgrades.contract_for`, the first-bar rule of `upgrade_events`); ELIGIBLE = closed,
with stamps, created before the end, the perpetual ≥ 30 days old at the end, t0 inside F1 … F4 (F5 listed). The 7-day collapse is a
FLAG, nothing dropped: `cell_all` marks the first eligible vote of a name and then the first after each 7 days; `cell_big` the same over
the votes with ≥ 200 voters (`VOTES_MIN`); the registered population is a registration's to name from the flags. **Known-at: the end is
stated at the creation, 5.0 days ahead at the median on the ≥ 200-voter cells (lead q10 / q50 / q90 3.8 / 6.0 / 10.4 d; one of 119 d); the
decision bar of any registration is the first 5m bar that CLOSES after t0 (on the hour to the second on 123 of F1+F2's 331 in-window
big cells, on the minute on 38 more, off the minute on 170).**
**Counted 2026-11-06 (`output/govlist/audit.md` / `.json`, `events.csv`, `bars.csv`, `costs.csv`; the chains 21:51 → 22:08 and 22:09 → 05:43 UTC 2026-11-06 by the VM's clock — the bars step stopped at the extent fingerprint (22:20), the hand row check 22:21 → 22:22, the bars again 22:22 → 22:32, the audit crashed once on a batch of 97 ARB votes ending at one second (the keyed lookups fixed, 2a25bd4) and ran 05:42 → 05:43 UTC
on the work VM):** **5,213 ELIGIBLE rows — F1 332 / F2 329 / F3 362 / F4 316 `cell_all` cells, 171 / 163 / 139 / 61 `cell_big`; F5 604
listed (206 / 32).** `cell_big` F1+F2: 334 rows on 20 names (AAVE 57, APE 48, ARB 35, CVX 34, GTC 31; members at t0 159; passed 196 /
failed 135; other 154, gauge 43, election 42, listing 35, grant 25, parameter 19, treasury 13); `cell_all` F1+F2: 661 on 44 (members 214;
the median vote 59 voters, q90 2,067 — the ≥ 200 cut ≈ q70); F3+F4: `cell_big` 200 on 20 (members 98), `cell_all` 678 on 58. The
window's two ends on the frozen list: three big-cut ends before F1's first member block (AAVE 2023-05-01, CVX and JOE 05-02), one 1-day
exit past F2's end (AAVE 2024-08-31), two more at 3d (APE, ARB 08-29) — 330 / 328 cells. None of the twelve. **The bars (the window
min(created, end − 2 d) → end + 8 d):** F1+F2's `cell_big` windows 334 of 334 complete, `cell_all` 652 of 661 — 128 monthly files fetched for 16 names, 29 absent from the archive (AKRO, DODO, FXS), the slice re-ingested whole (93,090,545 rows, 600 names); the extent fingerprint read IOTX, LISTA, LRC and ONE as changed (hole fills inside their old extent, R78's case) and `krlist.rowcheck` PASSED all four (every old row back at 0.0, `output/govlist/rowcheck.json`), the second pass PASS on 600 names; F3+F4: `cell_big` 135 of 200 and `cell_all` 351 of 678 with bars (the slice's non-member names end 2024-08 — a confirmation's own Data line, decision CE's pattern). The 0o (i) cells at 1d: F1+F2 `cell_big` 333 (AAVE 2024-08-31 dropped by the market's end), `cell_all` 649 (AAVE, CVX, XVS 08-31); at 3d 331 / 647; at 7d 331 / 645 — the audit's rule checks the market's END; the window's START (the first member block, 2023-05-03) takes three big-cut rows more, counted by hand on the list: 330 / 328. **The cost rows** (`costwide`'s taker round trip, `cost_daily_wide.parquet`, rule
(a)'s B_i on the end day): the big cut's F1+F2 cells: 267 of 330 priced (80.9 %; the 63 unpriced on 7 names never in a member block — BAL, CVX, GLMR, GMX, IOTX, JOE, SPELL — take R28's 46), B_i q10 / q50 / q90 24.8 / 33.8 / 86.0, max 262; **B = 45.9 on the priced and 45.9 with the fallback** — F1 38.9 / F2 52.7, the members' cells 30.7 against the non-members' 67.8; the whole-vote cells 399 of 652 priced (61 % — under a 75 % line), B 51.0 priced / 49.1 with the fallback; the F3+F4 big cut 136 of 200 priced, B 113.5 (median 30.1, q90 398 — the 2025 perpetuals, R81's lesson (iii) again). **No price of an event's name was read: the creation row, the run-up and the drift after the end
are R83's.** Decision CH DECIDED "CH1" 2026-11-06: R83 REGISTERED (PLAN §8) on these counts. **R83 READ 2026-11-06 06:13 → 06:20 UTC (PLAN §8): the big cut's bars after an end joined to R70's label ONCE — 330 cells, VALIDITY PASS, NOT DETECTABLE at 1d (M_trim −24.4 ± 17.7 against B 45.9; the whole-vote cells 644, −17 ± 10, inside ±B; the creation row's median −111; the 3d described row −66 ± 28); the fingerprint before and after 608 names, 0 changed. F3+F4's 2,096 rows and F5's 604 untouched by R83. The kind PARKED (PLAN §7).** **Decision CI2's Data line (2026-11-06 07:21 → 07:37 UTC on the work VM, `scripts/ci2_data.sh`, nothing priced): the F3+F4 big cut's windows lacked 53 (name, month) files on 8 names (GMX 14, GTC 13, RDNT 8, METIS 7, ID 4, AMB 3, GHST 2, GLMR 2) — 50 fetched from the archive, 3 on disk, none absent (`govlist bars --fetch --tags f34 --flag cell_big`: the `--flag` added that session so the whole-vote rows' months stay out — the cell_big rows only) — and the slice re-ingested whole (93,090,545 → 93,527,441 rows, 608 names; the extent fingerprint read AMB, GLMR, ID and RDNT as changed — holes inside their old extents — and `krlist.rowcheck` PASSED all four, every old row back at 0.0, `output/govlist/rowcheck_f34.json`): F3+F4 `cell_big` 200 of 200 windows complete (F3 139 / F4 61, every one at 100 %), `cell_all` 416 of 678 (44 of 58 names; the rest's months not fetched); the 0o (i) cells: 200 at 1d, 199 at 3d (GHST 2025-12-30 20:15's exit past 2026-01-01), 198 at 7d (AAVE 2025-12-26 too); none before the F3+F4 members' first block 2024-09-03 (the first big row ends ON it, CVX 2024-09-03 00:00). The cost rows: `costwide --symbols` for the 20 big-cut names from 2023-01-01 (3.7 min) merged into `cost_daily_wide.parquet` by `scripts/costwide_merge.py` (15,065 new rows on 20 names; the 12,832 overlapping rows identical to 0.0; 301,947 rows / 586 names after; md5 23a89e59… → 68d7dc60…; the before-copy `data/cost_daily_wide_before_ci2.parquet` on the VM): 194 of the 200 rows have a row on their end day — the 6 without (CVX 2024-09-03, GLMR 2024-09-26, AMB 2025-03-10 / 03-17 / 03-25 / 04-15: no dollar-volume day within 7 d) take R28's 46; **rule (a)'s B on the 199 cells 131.2 on the 193 priced (97.0 %), 128.6 with the six at 46 — F3 102.1 / F4 195.5, the members' 98 cells 28.8 against the non-members' 241.1; B_i q10 / q50 / q90 24.9 / 40.1 / 361.1, max 1,140 (GHST; the names' medians AAVE 25 … GHST 398).** A side effect: the merge added the 2023–24 rows of names R83 priced at 46 (CVX, GLMR, GMX, GTC …) — the audit's recount of F1+F2's big cut now reads B 52.3 on 312 of 334 priced where R83 read 45.9 on 267 (R83's verdict is the run's own file; NOT DETECTABLE at either bar). The frozen lists untouched (md5 as frozen before and after). R84 REGISTERED (PLAN §8) on these counts, hindsight-generated (the 3-day hold from R83's described row), and READ 2026-11-06 07:47 → 07:55 UTC (the F3+F4 big cut's bars after an end joined to R70's label ONCE — 199 cells, the guard rows (R84, F3) / (R84, F4) in the ledger at 07:47 before the market; the fingerprint before and after 608 names, 0 changed): VALIDITY PASS, NOT CONFIRMED — UNDER THE BAR (M_trim,3d −42.6 ± 25.1 against B 128.6, F3 −47 / F4 −31; the 1d row −24 ± 22; the whole-vote cells 417 with bars, −32 ± 26). The kind CLOSED on F1 … F4 for this rule (PLAN §7); the lists stay frozen, F5's 604 listed and never read.**

### cex_balance (the exchange's OWN on-chain balance per token — DefiLlama's CEX adapter for Binance, free, keyless; decision CK1, §9 #18) — `ft2/cexflow_f12.csv`, `ft2/cexflow_f34.csv` (FROZEN 2026-11-06, b2e7671, md5 21789095c70d8f927d6fe5aa36981721 / 05209c7d0a2c55120fc9f1048b73848b, 1,159 / 2,955 rows; before any bar after a t0 was read for anything), `ft2/cexflow_f5.csv` (4,234 rows LISTED, not frozen; md5 3e514b0bed865b0ec084611580c38561): `(symbol, base, mult, t0, ts_known, release, code, fold, block, perp_first, perp_first_source, perp_age_days, member_at_t0, side, stamp_hour, gap_d, amount_before, amount_after, change, usd_before, usd_jump, chains_n, flag_10, flag_20, list_commit, repeat_n, days_since_prior, cell)`; `data/cex_balance.parquet` on the VM: `(stamp, day, base, chain, amount, usd)`

**Known-at, the registered week (2026-11-13):** the third fetch (`binance-cex_2026-11-13.json`, md5 e37d814a…, 47,027,749 bytes) against the 11-09 file — IDENTICAL, 641,265 amounts in both and equal, no stamp removed, the only keys gone the older file's live point (1,097); `output/cexflow/knownat_20261113.json`. The day's 00:00 point is in the file by 06:00 UTC (the probe of 11-11). **R85 READ the same day on `cexflow_f12.csv`'s 121 members' inflow cells: NOT DETECTABLE (PLAN §8 R85 Result); `cexflow_f34.csv` still unpriced.**

`ft2 cexflow fetch|ingest|events|bars [--fetch --tags f12 f34 --flag member_at_t0]|knownat|audit` (`ft2/cexflow.py`; `scripts/ck1_chain.sh` to the freeze, `ck1_audit.sh` after it; `tests/test_p8_cexflow.py`). **The source:** `api.llama.fi/protocol/binance-cex` (no key; 46,488,699 bytes in 6 s from the laptop) — the balances of Binance's LABELLED wallets per token per chain, one point a day from 2022-11-12 (1,454 days, two 1-day gaps), 45 chains, 1,245 tokens, 222 of the 310 member bases (the 88 absent are chains the adapter does not read: ATOM, FIL, ICP, INJ, EGLD, EOS, ETC, DASH, NEO, ONT, IOTA, MINA, FLOW, CFX, AR, RUNE, TIA, TAO, STX, LUNC …); `tokensInUsd` beside `tokens` (the day's price). The wallet list is a public file with a git history (`DefiLlama-Adapters/projects/binance/config.js` 81 commits 2022-11-10 → 2025-10-22, `index.js` 27; saved as `adapter_commits_<date>.json`). The raw file is SAVED whole (`data/raw/external/defillama_cex/binance-cex_20261106.json`, md5 45439f98290ee5a5345ccaf4ca2d2160, fetched 2026-11-06 09:05 UTC): the known-at probe's first half. **The stamp:** every point is dated 00:00 UTC of its day (4,114 of 4,114 eligible rows at minute 0; today's last point carries the run's second, 07:42) — the adapter dates the point to the DAY, so the hour at which a day's point APPEARS is not in the file: the forward probe (the re-fetch on or after 2026-11-13, then `ft2 cexflow knownat`) decides (a) whether the overlap is identical (a point-in-time source) and (b) the lag a registration's decision bar must add to t0 = 00:00 UTC; the Wayback holds 0 snapshots of the endpoint, so nothing is measurable backward. **The event:** per base the balance summed over chains (the `-staking` / `-borrowed` chains out); the change against the previous stamp (consecutive, ≤ 1.5 d apart; the series' first 30 days out); a row where |change| ≥ 5 % — `side` in (up) / out (down); flags at 10 % / 20 %; `list_commit` (the wallet list changed that day or the day before — 293 rows); the perpetual by `upgrades.contract_for` in the stamp's month, ≥ 30 days old; `member_at_t0`; the 7-day collapse per (name, side) as the `cell` flag. EXCLUDED by name: BNB (the exchange's own token; 33 rows). **The audit (2026-11-06 09:13 → 09:27 UTC on the work VM; `output/cexflow/audit.md` / `.json`):** 10,435 jumps on 359 bases, 4,114 eligible on 130 names (F5 4,234 listed); **the registered population — the MEMBERS' inflow cells — 305: F1 65 / F2 56 / F3 44 / F4 140 (F1+F2 121 on 23 names, F3+F4 184 on 46; F5 11)**; the members' outflow cells 96 / 152; the non-members' 211 / 626 (in). The names: AXS 24, FARTCOIN 22, XLM 20, FLOKI 18, SUI 14, ALGO / MKR / TRX 12 — the top five 32 %. Sizes on the members' inflow cells: |change| q50 7.8 % / 9.3 % (F1+F2 / F3+F4), q90 41 % / 95 %; |usd jump| q10 381 k / 5 k, q50 4.6 M / 2.1 M, q90 36 M / 35 M USD. **The revert within three stamps (DESCRIBED, post-t0): 38 % of the eligible rows; by name on the members' inflow cells TRX 0.59, AXS 0.57, MKR 0.56, ALGO 0.48, XLM 0.44, FLOKI 0.42** — the exchange's own rotations between labelled and unlabelled wallets are a population inside the population; never a filter at t0, a described split at the registration. **Bars** (t0 − 2 d → t0 + 8 d; the fetch scoped to the members' rows by `--flag member_at_t0`: 2 files asked, MATIC's 2024-09 / 2024-10 absent from the archive — the contract renamed POL — the slice re-ingested whole, 93,527,441 rows / 608 names, the fingerprint PASS, 10.2 min): the members' inflow cells complete 121 of 121 (F1+F2), 181 of 184 (F3+F4; MATIC's three without bars); the 0o (i) cells at 1d / 3d / 7d: F1+F2 121 / 120 / 119, F3+F4 181 / 180 / 177. **Rule (a)'s bar from the names' own cost rows on the t0 day: the members' inflow cells B 31.3 (F1+F2, 121 of 121 priced; B_i median 28.7, q90 42) and 35.0 (F3+F4, 180 of 184; median 28.1, q90 49)** — the members' kind on both fold pairs; the non-members' 40.6 / 125.8 beside (unpriced 1,756 of 4,114 rows, all non-members). Nothing priced after a t0; no label. **Known-at READ 2026-11-09 (decision CL):** a second fetch 08:00 UTC, 2.9 days after the first — 637,955 amounts in both files, 637,955 equal (`output/cexflow/knownat_20261109.json`); the only stamp gone the first file's own live point (07:02:23, the adapter's run at fetch time — `knownat` now reports it as `live_point_older`, not a removal); the day's 00:00 point present at 07:02 (11-06) and by 04:17 (11-09): the lag ≤ 7 h, the 06:00 bound by `scripts/cexflow_hourprobe.sh` (`output/cexflow/hourprobe.csv`). The 2026-11-13 fetch stands as the week's validity gate.

### unlock_events, unlock_asof (DefiLlama, token unlock schedules; P8, §9 #8) — `data/unlock_events.parquet`, `data/unlock_asof.parquet`: `(pid, name, symbol, gecko_id, max_supply, ts, kind, recipient, category, tokens)`, the second with `asof`

A token's vesting schedule as DefiLlama describes it: one row an event, `kind` = `cliff` (a block of tokens released at one
time; `tokens` = the block) or `linear` (a change of a release rate; `tokens` = the new weekly rate). `ft2 events
fetch|ingest|inventory` (`ft2/events.py`; raw under `data/raw/external/defillama/`). **Source:** the free dataset bucket's
`emissionsIndex` (one JSON, every covered token; the API's own `emissions` routes answer 402, paid). **Measured 2026-10-05
(`output/events_inventory.md`; no price is read by this module):** 359 protocols, 54,262 events (42,065 cliffs); a protocol's
cliffs on one UTC day are one event — 25,116 cliff days, 8,270 of at least 0.1 % of the maximum supply. A perpetual is joined
by its ticker (`events.base`: 1000PEPEUSDT → PEPE): 70 of the 188 F1+F2 members have a schedule, 88 of the 216 F3+F4 members,
41 of the 141 before F1, 7 of the twelve (not BTC, XRP, ADA, ZEC, PEPE).

**Today's file is NOT the history — `unlock_events` must not be read as what was known.** `unlock_asof` holds the same list as
defillama.com/unlocks published it, from 81 Wayback Machine snapshots 2023-03-31 → 2026-10-05 (37 protocols on the page in
2023-03, 124 by the end of 2023, 179 by the end of 2024, 274 by the end of 2025, 369 now; 7 more listed snapshots are not the page). Measured on them
(`events.known_at`, `output/events_known_at.csv`): of the cliffs today's file dates in the 30 days after a snapshot, on the
protocols that snapshot lists, the snapshot had **42–50 % with the same day (±1) and size (±5 %)** and 57–62 % with the day
(snapshots of 2023, 2024, 2025); of the cliffs a snapshot dated there, **38–46 % are not in today's file as dated**. On the
snapshots of 2026 the same numbers are 85 % and 1.6 %: the file is rewritten as it ages (a schedule re-modelled, a token re-keyed
— `events.align` finds a snapshot's protocol under today's id by ticker, CoinGecko id or name: Arbitrum 2785 → 3777, Aave 111
→ parent#aave). **A page until 2025-04 carries the whole schedule, years ahead; from 2025-05-26 only the next 30 days.**
**Rule for any feature: an unlock is used as the last snapshot at least 7 days before it dated it (`events.promised`), never
from today's file.** That table holds, on a member while it is a member, 36 cliff days in F1, 54 in F2, 58 in F3, 20 in F4, 5
in F5 — 22 names, the ten with the most holding 157 of 176 (a few large names, each once a month); today's file would
have said 70, 96, 110, 101 (there SUI, OP, APT, ARB and APE lead). F4 and F5 cannot be rebuilt: five snapshots between 2025-05-26 and 2025-12-19, each reaching 30 days, and 2026 has none
before 02-21.

### binance_events (Binance's announcements; P8, §9 #8) — `data/binance_events.parquet`: `(catalog, id, code, release, title, kind, symbol, effective)`, one row a ticker

The exchange's own announcement lists with each article's publication time (`release`, UTC, to the millisecond): catalog 48
"New Cryptocurrency Listing" (2,276 articles, 2017-07-21 →), 161 "Delisting" (439, 2022-02-17 →), 49 "Latest Binance News"
(4,439; read for the monitoring-tag notices only). Raw under `data/raw/external/binance_cms/`. **www.binance.com answers from
the work VM and resets the connection from Vadim's network.** `events.parse_title` reads a title into `kind` —
`perp_launch`, `perp_delist` (USDT-quoted perpetuals; `symbol` is the contract's base as written), `perp_other` (BUSD, USDC,
coin-margined), `spot_list`, `spot_delist`, `monitoring`, `other` — and where a title says "Multiple" the article's summary is
read (21 articles). Of 660 perpetual launch / delisting articles 2 stay without a contract; three contracts with non-ASCII
names and the TradFi / equity / index contracts of 2026 are left out on purpose. **Checked against the archive** (the first
monthly 1d file of each of 895 USDT perpetuals): a launch announcement released in the month a contract began or the month
before exists for 98 of 99 contracts of 2023, 128 of 131 of 2024, 229 of 241 of 2025 (76 of 81 of 2020, 38 of 59 of 2021, 23
of 26 of 2022; 2026 is mostly the equity contracts). On the 235 contracts whose 5m bars we hold from their first day the first
bar comes **3.5 h after the announcement at the median** (10 % under 0.8 h, 90 % under 48 h); one begins before it.
**Per fold of the release:** launches confirmed by the archive F1 66, F2 53, F3 147, F4 157, F5 69; on a USDT perpetual
already trading for 30 days — delisted F1 0, F2 15, F3 7, F4 29, F5 28; spot delisting of its token 3, 8, 11, 11, 34;
monitoring tag 1, 14, 28, 25, 54; spot listing of a token whose perpetual already trades 2, 5, 4, 18, 15. On a screener
member while it is a member these kinds number 24 in all folds together (10 monitoring tags, 8 spot listings, 6 delistings). A release time is point-in-time by
construction (the article's own clock; `lastUpdateTime` is separate and not used).

**The Wayback Machine and a script's User-Agent (measured 2026-10-05):** with a browser's User-Agent it served 6 pages in 90
minutes and answered 429 to the rest, from two addresses; with a plain one each page comes in two seconds (75 in 18 minutes).
`ft2/etf.py` still sends the browser string — its "the archive throttles to a few an hour" (above) was this, so the ETF
known-at could be re-measured on every snapshot if it is ever needed.

### Archive tables as measured (`ft2 inventory`, 2026-09-15)

| table | pairs | window (UTC) | rows | integrity (`output/inventory.md` has the per-pair tables) |
|---|---|---|---|---|
| `metrics` (5m) | 12 (from listing: PEPE 2023-05-05, WLD 2023-07-24, HYPE 2025-05-30) | 2023-01-01 → 2026-09-13 | 4,322,018 | 2 duplicate keys dropped; cadence exactly 5 min; 4–6 gaps > 10 min per pair, the largest 10.5 h and common to every pair (an archive outage, not ours; AVAX has 15); WLD and ZEC each miss one whole day |
| `depth` (30 s) | 12 (same starts) | 2023-01-01 → 2026-09-13 | 42,277,682 (from 438.8M long rows) | 0 duplicates; **0 rows missing a core ±1–5 % level**; 2,880 rows/day median on every pair; ±0.2 % bands on 668,748 rows per pair from **2026-01-15**; 2–5 whole days missing per long pair inside one common ~3-day archive hole (largest gap 2 d 22 h), plus ~11 short (> 60 s) gaps per day |
| `depth` (30 s) — **the 32 outside names of R10's forty** (R34, 2026-10-12) | +32 (`ft2/universe.py::NEW`, by `--symbols`; the twelve's files untouched, md5 before and after) | 2023-04-01 → 2024-08-31 (519 daily files asked; 516–518 received a name — one archive-hole day common to all, 2–3 on NEAR, TRX, MANA, AAVE, CRV, THETA; WAVES 436 and 83 missing from its delisting 2024-06-11; 0 failed) | ≈ 1.5 M rows a name at 30 s (`data/depth/<SYM>.parquet`, 13 GB in all with the twelve; the zips 14 GB in all) | the book covers 99 % of F1+F2's scored cells (WAVES 83 %); fetched for the breadth read of the demeaned ±1 % imbalance (R34: NOT DETECTABLE; the raw imbalance replicates); their cost is the candle proxy (`cost_daily_wide`), taker only — `ceiling.bar_cost` takes it for a name the tape never priced |
| `depth` (30 s) — **the screener members outside R10's forty** (R36, 2026-10-12) | +158 (`ft2/screen_members.csv` minus the 30 in `universe.NEW`, by `--symbols`; the 44 files in hand untouched, md5 before and after) | 2023-04-01 → 2024-08-31 asked; a member's files begin at its listing (122 of the 158 list inside the window — COCOS 55 days of book, IO 82, LISTA 73, MEW 76, BB 111 …), 0 failed files | ≈ 1.5 M rows a name-year at 30 s; `data/depth` 37 GB in all (+24 GB), the zips 39 GB in all (+25 GB); 89 GB free after | fetched for R36 (the slow book at 3 and 7 days on the members: NOT DETECTABLE, the lean absent on the 158 and present on the 30 of R10's forty); their cost is the candle proxy (`cost_daily_wide`), taker only, ≈ 30–33 bps a round trip on the tenths a book trades |
| `aggTrades` (archive, raw, every trade) — **the twelve over 2026-08-15 → 08-28** (R39, 2026-10-13) | 12 | 14 daily files a name, 168 in all, 0 failed, `data/raw/external/binance/aggTrades/<SYM>/` (zips kept; 1.4 GB) | the trades reproduce the per-minute tape parts' volume and count on every name-day to 5e-7 | fetched for R39 (the maker cost at the trade level, beside the raw ladder exports of the same days): the only raw trades on disk — the tape elsewhere is per-minute. Not a label source |
| `funding_archive` | 12 | listing → 2026-08-31 (BTC/ETH from 2020-01-01) | 73,251 | 0 duplicates; vs the collector's `funding_rates` at the same funding timestamp: **99.94–100 % identical rates** on 2,706–4,469 overlapping rows per pair; `interval_h` is 8 on ten pairs, **4 on HYPE, and 2/4/8 on SOL** in different periods |
| `tape` (1 min, P1) | 12 (PEPE 2023-05-05, WLD 2023-07-24, HYPE 2025-05-30) | 2023-01-01 → 2026-09-13 | 21,616,106 | streamed 2026-09-15 04:35–07:14 UTC, 0 fetch errors; **0 days missing on every pair**; 3 quiet runs > 2 min per pair, the largest 20 min and common to all (an exchange pause), ZEC 221 (thin book); per-day parts kept, raw zips not |
| `candles_5m_archive` (archive `klines/5m`, P5) | 9 (BTC, ETH 2019-12-31; XRP 2020-01-06, LINK 01-17, ADA 01-31, ZEC 02-05; DOGE 2020-07-10, SOL 09-14, AVAX 09-23) | 2019-12-31 → 2022-08-18 | 2,258,984 | fetched 2026-09-21, 7,846 daily files, 0 errors, checksums verified; 0 duplicates; interior gaps: XRP 2 (largest 3 d), ZEC 1 (1 d), none elsewhere; **on the 830 bars it shares with the collector (2022-08-18) close, high, low and volume are identical** — `ceiling.panel(start < F0)` puts it under the collector's bars. Costs for these days: `ft2 costpre` → `data/cost_daily_pre.parquet`, `output/cost_pre.md` (spread = P1's candle regression floored at the pair's 2023 median; impact = the 90 % quantile of the pair's 2023 days; no maker fill statistics). Plausible where it can be checked against tick sizes (DOGE 2020 ≈ 24 bps at $0.003), but it is an extrapolation: reads on these days report spread + impact doubled alongside |
| `candles_5m_archive` — **the wider universe** (R10, 2026-09-22) | +32 pairs (`ft2/universe.py::NEW`: the 40 of `ft2 universe` minus the 8 the collector records) | 2022-04-01 → 2024-08-31 (monthly archive files, `ft2 archive klines/5m --monthly`) | 10,398,440 in the slice (was 2,258,984) | 254,016–254,592 rows per pair, **0 gaps > 10 min, 140,832 bars each inside F1+F2** (output/r10_klines_check.md); WAVES delisted 2024-06-11 and simply ends. `funding_archive` gained the same 32 (277,639 rows). No tape, ladder or depth for them: their cost is `ft2 costwide`'s pooled candle proxy (output/cost_wide.md) — spread validated leave-one-pair-out on the twelve (median ratio 0.89–1.52, worst ZEC), **impact at 10k is NOT: ×0.25 on PEPE, ×5–6 on SOL and ZEC** (the thin-pair regime the 8 thinnest new pairs sit in), so the proxy over-prices thin names and every R10 read carries a `--cost-mult 2` twin. The FP pre-history (2020 → 2022-04) is not fetched for them until R10's gate passes |
| `candles_5m_archive` — **the screener's members** (R18, 2026-09-27) | +158 pairs: the 188 names that are among the 60 most-traded outside the twelve in at least one 30-day block of F1+F2 (`ft2/screen_members.csv`, frozen before the fetch; 30 of R10's 32 are among them) | 2022-08-01 (or listing) → 2024-08-31, monthly archive files | 33,566,740 in the slice, 199 names (was 10,398,440, 41) | 188 klines and 188 funding fetches, 0 errors, checksums verified; 98 names listed inside the window (their first months do not exist). **The slice is rewritten whole by `ft2 ingest klines --universe all`; the 41 older names came back with identical row counts.** `funding_archive`: 1,117,001 rows, 202 names (was 277,639, 44). `cost_daily_wide`: 89,103 pair-days, 190 names, the older 32 identical to the digit; a member's taker leg beyond the fee is 6.6 bps at the median (3.3–10.4 between the quartiles, 21 at worst), so a round trip costs a typical member ≈ 23 bps against ≈ 12.5 on the twelve. COCOS is flat on most of its days (halted): no regime, no features there, no forecast |
| archive slices — **the members of the months before F1** (R23, 2026-09-29) | +37 pairs: the 141 names that are among the 60 most-traded outside the twelve in at least one 30-day block of 2021-12-10 → 2023-04-23 (`ft2/screen_members_pre.csv`, frozen before the fetch; 103 of them are R18 members too) | klines/5m and funding 2021-11-01 (or listing) → 2023-04-30, monthly files; metrics 2021-12-01 (or listing) → 2023-04-30, daily files | `candles_5m_archive` 43,796,361 (was 33,566,740), 236 names; `metrics` 43,815,456 (was 26,897,086), 239 names; `funding_archive` 1,304,738 (was 1,117,001) | 62,125 new files, 0 errors, 0 bad checksums; 42 duplicate metrics keys dropped (as before). The slices are rewritten whole; `scripts/r23_check_inputs.py`: every row held before is there unchanged, no duplicate key, all 141 members have rows in each source on those days. The ingest now holds the symbol as a category from the first read (memory). Copies of the slices as they were: `data/*_before_r23.parquet` on the work VM — they did their job and can be deleted |
| `ft2/screen_hindsight.csv` — **the members' 2026 volume** (R19, 2026-09-27) | the 188 members, one row a name: `hind_musd`, the median daily quote volume over the window (a day without a bar = 0), and `hind_days` | 2026-01-01 → 2026-08-31, monthly 1d archive files | 188 | 38 names with a median of zero (gone or renamed; the archive keeps flat zero-volume bars for a delisted contract, so 180 names have a bar on all 243 days). Hindsight on purpose: read by R19's diagnostic only, never an input to a model or a tradable screen. Only quote volume is read |
| `metrics` (5m) — **the screener's members** (R20, 2026-09-28) | +188 pairs (`ft2/screen_members.csv`); the twelve unchanged | members: 2023-04-01 (or listing) → 2024-08-31, daily archive files; the twelve as before | 26,897,086 in the slice (was 4,322,018); 24,174,288 inside 2023-04 → 2024-08 on 199 names | 188 fetches, 0 errors, 0 bad checksums; files absent from the archive are days before a listing, plus 1–2 days on some old names (ZEN, XEM, XMR 2; XLM 1). 42 duplicate keys dropped. **The slice is rewritten whole by `ft2 ingest metrics --universe all`; the twelve's rows came back identical, value by value**, against `data/metrics_before_r20.parquet` (kept on the work VM). On R20's 694,501 cells the features built from it cover 99.7–99.9 % |
| `premium` (archive `premiumIndexKlines/5m`) — `data/premium.parquet`: `(symbol, open_time) → premium`, the bar's last premium index (perpetual over the spot index, minus one) (R20, 2026-09-28) | the 188 members; **not the twelve** (not fetched: R20's cells leave them out) | 2023-04-01 (or listing) → 2024-08-31, monthly archive files | 22,763,516 | 188 fetches, 0 errors, 0 bad checksums, 0 duplicates; up to 17 monthly files a name, fewer for names listed inside the window. Covers 100 % of R20's cells |
| `etf_flows` (Farside, daily; P8 B3′, 2026-10-01) | BTC (12 funds), ETH (11) | BTC 2024-01-11 → 2026-09-30, ETH 2024-07-23 → | 15,794 (BTC 698 days × 13, ETH 560 × 12) | funds = total to 1e-13 on every row; the holiday calendar as the US exchanges'; known-at measured on 36 Wayback snapshots: final from 9 h after the close (24 of 24), partial before — a flow is known from 09:00 UTC the next day |
| `index_1m` (HistData, 1 min; P8 B3, 2026-10-01) | US500, US100 | 2020-01-01 → 2026-09-24 (yearly zips 2020–2025, monthly 2026-01 → 09; the current month is not offered) | 4,482,652 (US100 2,257,516; US500 2,225,136) | 30 fetches, 0 errors; 388 rows swapped by a minute in the current year's files (sorted, the later kept). Hours (UTC): the week opens Sunday 22:00 in European summer / 23:00 in winter and closes Friday 20:15 / 21:15; a daily break 20:15–22:00 / 21:15–23:00; 1,070–1,080 traded minutes a weekday; US holidays closed or thin (Christmas Eve → the 27th, Good Friday). **Thin: 2023-02 → 2023-07 holds 19–24k rows a month against 27–30k elsewhere — whole hours missing inside sessions; 658 of the 1,501 gaps over 30 min are in 2023.** A feature read from it must say what it does on a stale minute |
| archive slices — **the launches of F1+F2** (R28, 2026-10-05) | +44 pairs: the 119 USDT perpetuals whose launch Binance announced in F1+F2 and which begin in the archive that month or the next (`ft2/launches_f12.csv`, frozen before the fetch; 75 were held already as members) | klines/5m and funding 2023-05-01 (or listing) → 2024-08-31, monthly files | `candles_5m_archive` 70,407,515 rows; `funding_archive` 1,580,248; `cost_daily_wide` 228,209 pair-days, 389 names (was 217,786, 346) | 119 of 119 names for both kinds, 0 errors, 0 bad checksums (422 kline and 394 funding files new). The slices are rewritten whole: 707 of 713 name-fingerprints identical (`scripts/r28_fingerprint.py`), the six others (CAKE, NMR, XVG — held until now only from 2024-08) identical on their old extent; every old row of the wide cost file unchanged. **`costwide` has no row on a contract's FIRST day** (89 of the launches get theirs the day after their first bar): a trade entered on the first day has no proxy cost. A launch's later days: 10.9 bps a taker leg beyond the fee at the median, 43 at the 95th percentile |
| archive slices — **the launches of F3+F4** (R29, 2026-10-05) | +197 pairs: the 304 USDT perpetuals whose launch Binance announced in F3+F4 (`ft2/launches_f34.csv`, frozen before the fetch; 107 were held already as members) | klines/5m and funding 2024-09-01 (or listing) → 2025-12-31, monthly files; nothing dated 2026 | `candles_5m_archive` 83,169,566 rows (was 70,407,515); `funding_archive` 1,851,907 (was 1,580,248); `cost_daily_wide` 271,317 pair-days, 584 names (was 228,209, 389) | 304 of 304 names for both kinds, 0 errors, 0 bad checksums (1,550 kline and 1,521 funding files new). 801 of 801 name-fingerprints unchanged; every old row of the cost file unchanged; R28 re-run to 0.0. These contracts are dearer than F1+F2's launches: 31 bps a taker leg beyond the fee at the median on their later days (187 at the 95th percentile) against 11 (43). COLLECT and MAGMA (released 2025-12-31) have no cost row |
| `unlock_events`, `unlock_asof` (DefiLlama; P8 §9 #8, 2026-10-05) | 359 protocols today; 81 snapshots of the page | events 2011 → 2102; snapshots 2023-03-31 → 2026-10-05 | 54,262 events today; 2,402,171 rows in the snapshots | a snapshot had 42–50 % of the cliffs that followed with the same day and size, and 38–46 % of what it dated is not in today's file as dated — only `unlock_asof` through `events.promised` is point-in-time; pages from 2025-05-26 reach 30 days |
| `binance_events` (Binance announcements; P8 §9 #8, 2026-10-05) | catalogs 48, 161, 49 | 2017-07-02 → 2026-10-02 (delistings from 2022-02-17) | 7,630 rows, 7,154 articles | 658 of 660 perpetual launch / delisting articles read into contracts; launches confirmed by the archive's first files for 98–99 % of 2023–2025 contracts; first bar 3.5 h after the release at the median |
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
