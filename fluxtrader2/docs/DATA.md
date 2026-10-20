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
186 series and ≈ 25 … 36 members a block on F1+F2's blocks from 2023-10-30, Upbit ≈ 85 of 113 and ≈ 15 … 27.** What follows is
decision BC (P8).

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
