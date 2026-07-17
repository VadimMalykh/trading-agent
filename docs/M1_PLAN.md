# M1 Implementation Plan

Session-resilient plan for **Phase M1: Data pipeline + supervised 15m baseline**.

See also: [PLAN.md](./PLAN.md) (full roadmap), `MODEL.md` (architecture), `SPEC.md` (system), `README.md` (status).

**Status:** In progress  
**Keys required:** No (public Binance Futures REST only)  
**GPU required:** No (CPU training in Docker)  
**Host installs:** None (Docker only)

---

## Goals

1. Ingest public market data: OHLCV, agg trades, top-20 book, funding, OI, liquidations  
2. Persist to TimescaleDB/Postgres  
3. Build feature windows (microstructure + OHLCV; no hand TA as core)  
4. Train supervised **15m** baseline (direction + confidence) in `ml_trainer`  
5. Offline walk-forward-style eval metrics  

**Out of scope for M1:** RL policy, multi-horizon, real orders, WebSocket (REST polling OK).

---

## Architecture (M1)

```
Binance Futures REST (public, no API key)
        │
        ▼
FluxTrader.MarketData.Collector  (Elixir, in `app` container)
  polls pairs every ~5–60s depending on stream
        │
        ▼
PostgreSQL / TimescaleDB
  candles, market_trades, orderbook_snapshots,
  funding_rates, open_interest, liquidations
        │
        ▼
ml_trainer container (Python/PyTorch, CPU)
  load → features → labels (15m) → train → eval → checkpoint
        │
        ▼
/models volume + ml/train/output/
```

---

## Steps (checklist)

### 1. Documentation
- [x] This plan (`docs/M1_PLAN.md`)
- [x] Architecture (`MODEL.md`)

### 2. Database
- [x] Migration: `market_trades` (windowed agg trade stats)
- [x] Migration: `orderbook_snapshots` (top-20 compressed features)
- [x] Migration: `funding_rates`
- [x] Migration: `open_interest`
- [x] Migration: `liquidations`
- [x] Ensure `candles` written on poll + historical backfill

### 3. Elixir ingest
- [x] Extend `Binance.Client`: aggTrades, depth, premiumIndex, openInterest, forceOrders
- [x] `MarketData.Collector` GenServer: poll + insert + kline backfill
- [x] Persist candles from poll/backfill
- [x] Wire into `Application` supervisor

### 4. ML pipeline (`ml/train`)
- [x] `config.py` — horizon, pairs, DB URL, seq length
- [x] `data/db.py` — load from Postgres
- [x] `data/features.py` — window features (OHLCV + book + flow + funding/OI)
- [x] `data/dataset.py` — sequences + 15m labels (direction)
- [x] `models/lstm.py` — classifier
- [x] `train.py` — train loop, CPU, checkpoint
- [x] `eval.py` — accuracy, confusion matrix
- [x] Docker: network to postgres, env `DATABASE_URL`, volume for models

### 5. Test
- [x] `docker compose up` — collector fills tables
- [x] SQL row counts > 0 for majors (e.g. candles ~6000 after backfill)
- [x] `docker compose --profile ml run --rm ml_trainer python train.py --device cpu`
- [x] Metrics printed; checkpoint written (`/models/m1_15m.pt`)

**Verified (2026-07-18):** train completed 5 epochs, ~1368 samples, best val acc ~0.39 (baseline pipeline works; accuracy improves with more book/trade history + longer train).

---

## Poll intervals (defaults)

| Stream | Interval | Notes |
|--------|----------|--------|
| Book top-20 | 5s | MODEL.md default |
| Agg trades → window | 5s | Aggregate since last poll |
| Candles 1m | 60s | Existing |
| Funding / premium | 60s | Slow-moving |
| Open interest | 60s | |
| Liquidations | 60s | force orders if available |

Pairs: `BTCUSDT`, `ETHUSDT`, `SOLUSDT` (whitelist config).

---

## Training defaults (M1)

| Param | Value |
|-------|--------|
| Horizon | 15m |
| Device | cpu |
| Sequence length | 32–64 windows |
| Classes | up / down / flat (flat if \|return\| < threshold, e.g. 0.1%) |
| Model | small LSTM |
| Split | time-ordered train/val (no shuffle) |
| Output | `/models/m1_15m.pt` or `ml/train/output/` |

If DB has little history yet, training may use **synthetic/bootstrap from recent klines only** and still run end-to-end; book/funding improve as data accumulates.

---

## Commands (all Docker)

```bash
# App + DB + collectors
docker compose up -d postgres app

# Check tables
docker compose exec postgres psql -U fluxtrader -d fluxtrader -c "\dt"
docker compose exec postgres psql -U fluxtrader -d fluxtrader \
  -c "SELECT count(*) FROM orderbook_snapshots;"

# Train (CPU)
docker compose --profile ml run --rm ml_trainer \
  python train.py --horizon 15 --device cpu --epochs 5

# Eval
docker compose --profile ml run --rm ml_trainer \
  python eval.py --checkpoint /models/m1_15m.pt
```

No API keys. No host Python/Elixir installs.

---

## Files to add/change

```
docs/M1_PLAN.md                          # this file
apps/fluxtrader/priv/repo/migrations/
  ..._create_market_data_tables.exs
apps/fluxtrader/lib/fluxtrader/binance/client.ex   # more endpoints
apps/fluxtrader/lib/fluxtrader/market_data/
  collector.ex
  schemas...
apps/fluxtrader/lib/fluxtrader/application.ex      # start collector
docker-compose.yml                       # ml_trainer → postgres network + env
ml/train/
  Dockerfile.train
  requirements.txt
  config.py
  train.py
  eval.py
  data/db.py
  data/features.py
  data/dataset.py
  models/lstm.py
README.md                                # M1 status
```

---

## Success criteria

1. Collectors run without errors for ≥10 minutes  
2. `orderbook_snapshots`, `market_trades`, `candles` have rows for whitelist pairs  
3. `train.py` completes on CPU and writes a checkpoint  
4. Eval prints accuracy (even if low with little data — pipeline works)  

---

## Resume after session loss

1. Read `MODEL.md` + this file  
2. `docker compose up -d`  
3. Check migrations applied  
4. Continue from first unchecked item above  
5. Prefer extending collectors/training over redesigning architecture  

---

*Started: 2026-07-18*
