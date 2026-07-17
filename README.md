# FluxTrader

Real-time cryptocurrency futures trading agent with ML-driven decision making.

## Status

**M1 — Market data + supervised 15m baseline** (in progress)

See **[docs/M1_PLAN.md](./docs/M1_PLAN.md)** for the full implementation checklist (session-resilient).

What's working:
- Elixir umbrella project running in Docker (no host installs)
- PostgreSQL/TimescaleDB migrations (candles, positions, trades, book, market trades, funding, OI, liquidations)
- Binance Futures **public** REST (no API keys for market data)
- `MarketData.Collector`: book top-20 @ 5s, trades, funding, OI, liquidations, candle backfill + poll
- LiveView dashboard + settings + positions API
- Trading executor (simulation) + risk manager
- ML train/eval in `ml_trainer` (PyTorch LSTM, CPU, Docker)

Docs:
- **[docs/PLAN.md](./docs/PLAN.md)** — full project roadmap (all phases)
- [MODEL.md](./MODEL.md) — ML architecture
- [docs/M1_PLAN.md](./docs/M1_PLAN.md) — M1 checklist
- [SPEC.md](./SPEC.md) — original system spec

## Quick Start

Requires only Docker. No local installs needed.

```bash
cp .env.example .env
docker compose up
```

Dashboard: http://localhost:4000
API: http://localhost:4000/api/positions

### Services

| Service | Description | Port |
|---------|-------------|------|
| `app` | Elixir/Phoenix backend + web UI | 4000 |
| `postgres` | PostgreSQL + TimescaleDB | 5432 |
| `ml_trainer` | Python/PyTorch (on-demand) | — |

### Commands

```bash
docker compose up -d postgres app    # App + DB + collectors
docker compose logs -f app           # Watch app / collector logs
docker compose exec postgres psql -U fluxtrader -d fluxtrader -c "\dt"

# M1 train (CPU, no GPU, no API keys)
docker compose --profile ml run --rm ml_trainer \
  python train.py --device cpu --epochs 5 --horizon 15

docker compose --profile ml run --rm ml_trainer \
  python eval.py --checkpoint /models/m1_15m.pt

docker compose down
```

## Project Structure

```
trading_agent/
├── docker-compose.yml          # Service orchestration
├── Dockerfile.app              # Elixir container
├── .env.example                # Environment variables
├── mix.exs                     # Umbrella root
├── config/                     # Elixir config
│   ├── config.exs
│   ├── dev.exs
│   └── runtime.exs
├── apps/
│   ├── fluxtrader/             # Core business logic
│   │   ├── lib/fluxtrader/
│   │   │   ├── binance/        # Binance REST client + data feed
│   │   │   ├── data/           # Candle store, feature engineering
│   │   │   ├── pairs/          # Pair whitelist selector
│   │   │   ├── trading/        # Executor, risk manager
│   │   │   └── ml/             # ML prediction interface
│   │   └── priv/repo/migrations/
│   └── fluxtrader_web/         # Phoenix LiveView UI
│       ├── lib/fluxtrader_web/
│       │   ├── live/           # DashboardLive, SettingsLive
│       │   └── components/     # Layouts, CoreComponents
│       └── priv/static/
├── ml/
│   └── train/                  # Python ML training scaffold
│       ├── Dockerfile.train
│       ├── requirements.txt
│       └── train.py
└── SPEC.md                     # Full technical specification
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Elixir 1.16 / OTP 26 |
| Web | Phoenix 1.7 / LiveView 0.20 |
| HTTP Client | Finch (Mint-based) |
| Database | PostgreSQL 16 + TimescaleDB |
| ML Training | Python 3.11 / PyTorch |
| Infrastructure | Docker Compose |

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Default | Description |
|----------|---------|-------------|
| `BINANCE_API_KEY` | — | Binance API key (read-only for data) |
| `BINANCE_API_SECRET` | — | Binance API secret |
| `TRADING_MODE` | `simulation` | `simulation`, `signal`, `manual`, `auto` |
| `MAX_POSITIONS` | `3` | Max concurrent positions |
| `STOP_LOSS_PCT` | `0.02` | Stop loss percentage |
| `TAKE_PROFIT_RATIO` | `2.0` | Risk:reward ratio |
| `LEVERAGE` | `5` | Leverage multiplier |
| `WHITELIST_PAIRS` | `BTCUSDT,ETHUSDT,SOLUSDT` | Pairs to analyze |

## Model Design

See **[MODEL.md](./MODEL.md)** for the frozen ML architecture:

- Supervised signal model (microstructure + OHLCV + funding/OI; no hand TA as core)
- Discrete policy layer (flat/long/short/hold/exit) — not end-to-end RL
- Hard risk manager always on
- Phases M1–M4 (data → multi-horizon → policy → positional)

## What's Next

### Near term (M1 — data + supervised baseline)

- [ ] Trades + top-20 book (5s) + funding/OI/liquidations ingestion
- [ ] Feature windows + TimescaleDB storage for new streams
- [ ] Supervised 15m baseline (Python/PyTorch) + offline walk-forward eval
- [ ] Replace indicator-centric `FeatureEngineering` as production path

### Then (M2–M3)

- [ ] Multi-horizon heads (1m, 15m, 1h) + confidence gating
- [ ] Discrete policy (hold/exit/size) with DD-aware reward
- [ ] Simulation A/B: signal-only vs signal+policy

### Later

- [ ] Binance WebSocket (upgrade from REST polling)
- [ ] ML inference serving (ONNX / Nx)
- [ ] Position persistence, backtesting UI
- [ ] Multi-day positional head (M4)
