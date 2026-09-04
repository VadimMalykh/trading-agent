# Data Collection Audit (2026-08-05) (archived)

> **ARCHIVED 2026-09-04 — the 2026-08-05 audit of what the collector captures and drops.** Everything it recommended acting on has been acted on or is tracked as a row in [BACKLOG.md](../BACKLOG.md), which keeps the pointer for kline taker-buy volume.
> Kept because its central argument — microstructure data has no backfill, so a day not collected is gone forever — is the reason several collection decisions look the way they do.


**Purpose.** Decide what raw market data we should be collecting **now**, given the
hard constraint: **most microstructure data has no historical backfill** — a day not
collected (or collected lossily) is a day gone forever. This audits what the Elixir
collector captures today, what it silently drops, and what is worth acting on ASAP.

**One-line takeaway.** The biggest issue is not a missing stream — it is that streams
we *already* collect are **lossily compressed at write time** (esp. the order book:
20 levels pulled → 11 scalars stored, raw ladder discarded). Because these have no
backfill, that raw detail is unrecoverable. Fixing the collector to persist raw
(or richer) snapshots is higher-leverage and more time-sensitive than any new
derived feature.

---

## Backfillable vs collector-only (the decision axis)

The ONLY thing that matters for "collect ASAP" is whether a source has history:

| Source | Historical backfill? | Consequence |
|--------|----------------------|-------------|
| **Klines / OHLCV** | ✅ `/fapi/v1/klines` (paginated, months) — `ml/train/backfill_history.py` | Not urgent. Recompute anytime. |
| **Funding rate** | ✅ `/fapi/v1/fundingRate` (history) — backfill supports it | Not urgent. |
| **Agg-trades (ticks)** | ⚠️ Partial — public archive `data.binance.vision` has daily aggTrades CSVs; live REST `/aggTrades` is recent-only | Recoverable-ish, but only if we go pull the archive; NOT via live API. |
| **Book ticker (best bid/ask)** | ⚠️ Partial — `data.binance.vision` bookTicker archive (best bid/ask only, not full L2) | Recoverable-ish for L1; full L2 depth is NOT. |
| **Order book L2 depth** | ❌ No history anywhere | **Collect ASAP, and stop compressing.** |
| **Open interest** | ⚠️ Shallow — `/futures/data/openInterestHist` ~30-day retention, coarse granularity | Mostly collector-only; ~30d partial backfill. |
| **Long/short & taker ratios** | ⚠️ Shallow — `/futures/data/*Ratio` ~30-day retention | Collector-only beyond 30d. ✅ **Collected since 2026-08-24** (B4.2), incl. a one-time grab of the ~30d the exchange still held. |
| **Liquidations (forceOrder)** | ❌ No REST history; WS only | Collector-only; currently **blocked** (see below). |

Rule of thumb: **anything in the ❌ / ⚠️ rows should be collected at full fidelity
now**; the ✅ rows can wait.

---

## What the collector captures today

Two ingestion processes (`apps/fluxtrader/lib/fluxtrader/application.ex:14,17`):
- `MarketData.Collector` — polls Binance Futures **public REST** on timers
  (`collector.ex`). No API keys.
- `Binance.WebSocket` — `gun` consumer of the `!forceOrder@arr` WS (liquidations
  only, `websocket.ex`).

Poll intervals (`collector.ex:14-16`): book 5s, trades 5s, slow (funding+OI) 60s,
candles 60s.

| # | Stream | Source (REST unless noted) | Interval | Table | Stored fields |
|---|--------|----------------------------|----------|-------|---------------|
| 1 | Candles | `/fapi/v1/klines` 1m/5m/15m/1h | 60s (+500 backfill) | `candles` | symbol, interval, open_time, OHLC, volume, close_time |
| 2 | Order book | `/fapi/v1/depth?limit=20` | 5s | `orderbook_snapshots` | mid, spread, microprice, bid/ask_volume, imbalance, bid/ask_depth_near, bid/ask_depth_far (11 scalars) |
| 3 | Trades | `/fapi/v1/aggTrades?limit=200` | 5s | `market_trades` | window_start(5s), trade_count, volume, buy/sell_volume, vwap, high, low |
| 4 | Funding/mark | `/fapi/v1/premiumIndex` | 60s | `funding_rates` | mark_price, index_price, last_funding_rate, next_funding_time |
| 5 | Open interest | `/fapi/v1/openInterest` | 60s | `open_interest` | open_interest |
| 6 | Liquidations | WS `!forceOrder@arr` | event | `liquidations` | ts, side, price, quantity, order_id(="") — **0 rows, blocked** |

Full column lists are in the migrations (`apps/**/priv/repo/migrations/2026071800*`).

---

## What we silently DROP at write time (the real cost)

Because these streams have no/weak backfill, every dropped field is (largely)
unrecoverable. Ordered by how much it hurts:

### 🔴 1. Order-book raw ladder — 20 levels pulled, 0 stored
- `Client.order_book(symbol, 20)` fetches **20 bid + 20 ask levels**
  (`collector.ex:158`, `client.ex:27-30`), but `BookFeatures.from_depth`
  (`book_features.ex:11-58`) reduces them to **11 scalar features** and **discards the
  raw price/qty ladder entirely**. `lastUpdateId` and payload timestamps also dropped.
- Consequences:
  - The near/far split is a coarse 2-bucket compression (top-5 vs rest). We can never
    reconstruct per-level depth, slope of the book, or alternative depth cutoffs.
  - `/fapi/v1/depth` supports `limit` up to **1000**; we request only **20**, so
    levels 21–1000 are never even pulled.
  - The book is **REST-polled at 5s**, not streamed — we miss all intra-5s book
    dynamics; the `@depth` diff WS stream is unused.
- **This is the single highest-value, most time-sensitive fix.** L2 depth has no
  backfill; the detail we throw away today is gone.

### 🟠 2. Agg-trades collapsed to 5s windows
- 200 aggTrades/poll are aggregated to one 5s row (`collector.ex:211-238`); per-trade
  `price/qty/time/side/aggId` are used transiently then dropped. No raw tick table.
- Partial mitigation: `data.binance.vision` archives daily aggTrades, so ticks are
  *somewhat* backfillable if we ever pull the archive — but not via live API and not
  for free (extra pipeline).

### 🟡 3. Kline extra fields (LOW urgency — backfillable)
- We read only indices 0–6 of each kline (`collector.ex:330-342`), dropping
  **quote-asset volume, number-of-trades, taker-buy base vol, taker-buy quote vol**.
- Taker-buy volume is a genuine order-flow signal, BUT klines are fully backfillable,
  so this is a cheap fix anytime — not time-sensitive.

### ✅ 4. Exchange timestamps — FIXED 2026-08-24 (B4.1)
- `orderbook_snapshots.ts`, `funding_rates.ts` and `open_interest.ts` are still
  `DateTime.utc_now()` (local receipt time), and deliberately so: `ts` is the key
  every training as-of join and the 1:1 `orderbook_levels` join already use.
- The exchange's own clock is now stored **alongside** it — `event_time` /
  `transaction_time` / `last_update_id` on `orderbook_snapshots`, `event_time` on
  `funding_rates` and `open_interest` (migration `20260824000001`). Rows collected
  before that date stay NULL, which is honest: their exchange time is genuinely
  unknown and must not be imputed.
- The skew is now measurable rather than assumed —
  `./scripts/gcp_data_collection_stats.sh` §2b prints p50/p95 of `ts - event_time`
  per symbol. Irrelevant at a 240m horizon; a large fraction of the prediction
  window at 1m, which is why it blocked trustworthy short-horizon work.

---

## Streams NOT collected at all that are worth starting

All of these are collector-only or shallow-retention → **starting them now begins an
otherwise-unrecoverable history**:

1. **L2 depth at fidelity** (see 🔴 above) — either store the raw 20-level ladder, or
   switch to the `@depth`/`@depth20` WS diff stream. Highest priority.
2. **Long/short & taker ratios** — `/futures/data/topLongShortAccountRatio`,
   `globalLongShortAccountRatio`, `takerlongshortRatio` (~30-day retention on the
   exchange → collector-only beyond that). Cheap 60s polls; known-useful sentiment/
   positioning features for the later RL policy. Not collected today.
3. **Raw tick trades** (optional) — a real per-trade table would preserve trade-size
   distribution / aggressor detail we currently 5s-average away. Lower priority given
   the archive partially covers it.
4. **Liquidations** — see below.

---

## Liquidations — BLOCKED (known, documented)

`liquidations` = **0 rows.** The WS consumer connects (101 upgrade + SUBSCRIBE ack)
but Binance **gates the WS data plane from datacenter/cloud egress**, so zero
market-data frames arrive (verified local + 2 GCP regions;
`docs/NEXT_TRAINING_PLAN.md`, liquidations section). There is no REST history for
force orders. Decision (2026-08-04): **document + defer** — the code is correct; it's
a network/vendor egress problem. Options, in preference order:
(a) third-party vendor REST (Coinglass/Coinalyze — also gives *history*);
(b) proxy the WS through non-datacenter egress (realtime only);
(c) drop liquidations from the feature set.
`order_id` is also hardcoded `""` in the writer (`websocket.ex`), so even when
unblocked, dedup relies only on `[symbol, ts]`.

---

## Recommendations (prioritized) — separate the two questions

The user's question was "should we collect feature data ASAP so history accumulates?"
The answer splits cleanly:

### Derived features from data we ALREADY have → NOT time-sensitive, do NOT rush
- Longer-horizon return context (trailing 1h/4h/1d returns, longer rolling vol) and
  cross-pair/beta features are **computed from existing ~400d candles** — fully
  retroactive, zero collection lead time.
- Do these deliberately, one attributable training run at a time, **after** the Task-1
  staleness-fix baseline confirms the book edge recovers. Rushing them now only muddies
  attribution and risks premature `FEATURE_DIM` bumps (breaking checkpoint/serve).

### Raw collection at fidelity → TIME-SENSITIVE, act now (in order)
1. ✅ **DONE (2026-08-05) — Stop lossy-compressing the order book.** See
   "RAW ORDER-BOOK LADDER IMPLEMENTED" below.
2. ✅ **DONE (2026-08-24) — Poll long/short & taker ratios.** See "B4 COLLECTION
   FIXES" below.
3. ✅ **DONE (2026-08-24) — Store exchange event timestamps** alongside local `ts`
   for book/OI/funding. See "B4 COLLECTION FIXES" below.
4. **Resolve liquidations source** (vendor vs proxy) — highest *analytical* value but
   gated on a vendor/network decision, not code. `scripts/gcp_depth_ws_test.sh`
   (B4.3) now measures the egress side of that question directly.

Backfillable items (kline taker-buy volume, funding history) can be picked up anytime
and need no urgency.

---

## RAW ORDER-BOOK LADDER IMPLEMENTED (2026-08-05)

Fixes the #1 time-sensitive loss: the collector now captures the full L2 ladder
losslessly instead of discarding it. **NOT committed** (commit only when asked).

- **Depth raised 20 → 100** per book poll (`Client.order_book/2` default; also
  tunable via config `:fluxtrader, :book_depth_limit`, `collector.ex`).
- **New table `orderbook_levels`** (migration `20260805000001`): one row per
  snapshot, `bids`/`asks` as **JSONB arrays of `[price, qty]`** (best-first, no
  truncation), plus exchange `event_time` (`E`), `transaction_time` (`T`),
  `last_update_id`, and `depth`. Joins 1:1 to `orderbook_snapshots` on
  `(symbol, ts)` (unique index). Schema: `market_data/orderbook_level.ex`.
- **Scalar features preserved.** `BookFeatures.from_depth/2` now computes the 11
  scalars over only the **top 20** levels (`@scalar_levels`), so the served model's
  feature distribution is unchanged even though we fetch 100. `BookFeatures.raw_levels/3`
  extracts the full ladder + metadata, sharing the snapshot's `ts`.
- **Collector wiring** (`collector.ex`): `collect_book/1` writes the scalar snapshot
  then best-effort-inserts the raw ladder (a raw-ladder failure never drops the
  scalar row). Both `on_conflict: :nothing` on `(symbol, ts)`.

**Verified (real Binance depth, live DB):** compile clean (`--warnings-as-errors`);
migration applied; a live BTC poll fetched 100+100 levels, stored the full ladder
with correct best-bid/ask ordering + `last_update_id` + exchange timestamps; the two
tables join 1:1; JSONB is queryable (`jsonb_array_length`, `bids->0->>0`). Scalar
`bid_volume` correctly reflects top-20 only. Smoke-test rows cleaned up.

**Follow-ups (not done here):**
- Nothing on the Python/ML side consumes `orderbook_levels` yet — the model still
  reads the 11 scalars from `orderbook_snapshots`. New L2-derived features (book
  slope, per-level depth, deeper imbalance cutoffs) are a later, attributable
  feature run once enough raw history accrues.
- The 5s REST cadence is unchanged (intra-5s dynamics still unseen); moving to the
  `@depth` WS stream is a separate, larger change and is gated by the same
  datacenter-egress question as liquidations.
- Storage: JSONB ladders are larger than the scalar rows — monitor
  `orderbook_levels` growth; consider TimescaleDB compression / retention if needed.

## B4 COLLECTION FIXES (2026-08-24)

Implements B4 of `docs/BOOK_ERA_PLAN.md`: the collection changes whose *data* is
unrecoverable if deferred. Independent of B0–B3 and on nobody's critical path — the
point is that if the book wave concludes "wait for the calendar", the calendar should
accumulate better data meanwhile.

### B4.1 — exchange event timestamps (migration `20260824000001`)
`orderbook_snapshots` gains `event_time` (`E`), `transaction_time` (`T`) and
`last_update_id`; `funding_rates` and `open_interest` gain `event_time` (`time`).
Additive and nullable — `ts` keeps its exact meaning, so training's as-of joins, the
`(symbol, ts)` join to `orderbook_levels`, and every existing query are untouched.
`BookFeatures.from_depth/2` carries the metadata through; no scalar changes value.

### B4.2 — long/short & taker ratios (migration `20260824000002`)
New table `long_short_ratios`, one row per `(symbol, exchange 5m bucket, period)`,
fed by three `/futures/data` endpoints: `topLongShortAccountRatio`,
`globalLongShortAccountRatio`, `takerlongshortRatio`. Polled every 60s
(`Collector`), and each endpoint upserts **only its own column group**, so one
endpoint lagging or failing never blanks another's values — the taker series is
routinely a bucket behind the other two, so this is the normal case, not an edge one.

`ts` is the exchange bucket, not local time, so this table has no jitter to correct.
Added to `DUMP_TABLES` (`gcp_common.sh`) — it is collector-only history and a dump
without it silently loses everything past the exchange's ~30-day window.

**One-time backfill.** On first sight of a pair the collector grabs the ~30 days the
exchange still holds, off-process under `Task.Supervisor` (serial across pairs, 200ms
between pages, so it cannot crowd out the 5s book/trade polls). It pages **backward**
via `endTime`, which is not a style choice: verified live 2026-08-24, the endpoint
answers `startTime=30d ago, endTime=now, limit=500` with the newest 500 buckets
(~42h), *not* the oldest 500. Paging forward would have silently captured only the
last ~42h of a window we get exactly one chance at.

### B4.3 — is `@depth` egress-blocked? (`scripts/gcp_depth_ws_test.sh`)
A ~1 minute connectivity test, not a project. The 5s REST cadence is the fidelity
ceiling for all 1m/5m work and the `@depth` diff stream is the fix — but
`!forceOrder@arr` is already gated from datacenter egress (upgrade + SUBSCRIBE ack,
then zero data frames; hence `liquidations` = 0 rows), so nobody should design around
`@depth` before knowing which side of that line it is on.

`mix flux.depth_ws_test` subscribes to `@depth`, `@aggTrade` (control: does *any*
market data arrive?) and `!forceOrder@arr` (known-blocked reference) on one
connection and counts frames by type. The control is what makes the result
interpretable — "no depth frames" alone cannot separate "`@depth` is gated" from
"this host gets no WS data at all", and those imply completely different next steps.
Verdict is the last line: `DEPTH_OK` / `DEPTH_BLOCKED` / `WS_BLOCKED` /
`CONNECT_FAILED`. Nothing is written to the database.

**Status: not yet run** — it must run from the always-on VM, since that is the egress
that matters. Record the verdict in `docs/BOOK_ERA_PLAN.md` B4; a `WS_BLOCKED` answer
is a real result and closes the item.

### Verified before commit
Compile clean (`--warnings-as-errors`); both migrations applied; the three ratio
endpoints and the depth/premiumIndex/openInterest payloads checked live against
Binance (field names and shapes match the mapping exactly); `from_depth` run on a real
depth payload and persisted, with `last_update_id` = 1.14e13 confirming `bigint` was
required; the three-endpoint upsert verified to merge into one row and to leave the
other groups intact when a single endpoint re-polls. Smoke rows cleaned up.

**Not verified locally:** the collector's live REST path. This machine's egress runs
through a TLS-intercepting proxy whose CA the container does not trust, so
container-side HTTPS to Binance fails with `unknown_ca`. That is a local-environment
artifact — the VM has direct egress — but it means the poll loop's first real
exercise is on the VM after deploy. Watch the first `gcp_data_collection_stats.sh`
§2b and §9 for confirmation.

---

## Cross-refs
- Root-cause of the book-era edge collapse + staleness fix: `docs/NEXT_TRAINING_PLAN.md`
  "TASK 1".
- Liquidations block detail: `docs/NEXT_TRAINING_PLAN.md` (liquidations section).
- Collector: `apps/fluxtrader/lib/fluxtrader/market_data/collector.ex`,
  `.../market_data/book_features.ex`, `.../binance/{client,websocket}.ex`.
- Feature build (consumer side): `ml/train/data/features.py`, `ml/train/data/db.py`.
