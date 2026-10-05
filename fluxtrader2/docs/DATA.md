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
