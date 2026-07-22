# FluxTrader

Real-time cryptocurrency futures trading agent with ML-driven decision making.

## Status

**Phase I light — M2 signals wired into the app** (current)

See **[docs/SIMULATION.md](./docs/SIMULATION.md)** for how to run paper signal simulation.

What's working:
- Elixir + Docker (no host installs); public Binance data (no keys)
- M1/M2 train/eval in `ml_trainer`
- **`ml_inference`** serves `m2_multi.pt` (`serve.py`)
- **SignalEngine** polls scores → dashboard + `/api/signals` + `[SIM_SIGNAL]` logs
- Simulation mode only (no real orders)

Docs: [TRAINING.md](./docs/TRAINING.md) · [GCP_TRAIN_EPHEMERAL.md](./docs/GCP_TRAIN_EPHEMERAL.md) · [SIMULATION.md](./docs/SIMULATION.md) · [PLAN.md](./docs/PLAN.md) · [MODEL.md](./MODEL.md) · [M1](./docs/M1_PLAN.md) · [M2](./docs/M2_PLAN.md) · [SPEC.md](./SPEC.md)

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
# Full stack: DB + inference + app (needs m2_multi.pt — train first if missing)
docker compose up -d postgres ml_inference app
# Dashboard http://localhost:4000  ·  Signals http://localhost:4000/api/signals
# Inference http://localhost:8001/health

docker compose logs -f app | grep -E 'SIM_SIGNAL|SignalEngine'

# Historic data (months of klines — no waiting weeks)
docker compose --profile ml run --rm ml_trainer \
  python backfill_history.py --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --intervals 1m,15m,1h --days 180

# Train / eval M2 (CPU)
docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 30
docker compose --profile ml run --rm ml_trainer \
  python eval_m2.py --checkpoint /models/m2_multi.pt --gate 0.35,0.4,0.5,0.6
docker compose restart ml_inference   # reload weights after retrain

docker compose down
```

- **Train / backfill / eval / overfit:** [docs/TRAINING.md](./docs/TRAINING.md)  
- **Live paper signals:** [docs/SIMULATION.md](./docs/SIMULATION.md)

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

### Done

- [x] M1 data + 15m baseline
- [x] M2 multi-horizon (1m/15m/1h) + confidence gating

### Next (M3+)

- [ ] Discrete policy (flat/long/short/hold/exit) with DD-aware reward
- [ ] Simulation A/B: signal-only vs signal+policy
- [ ] Wire checkpoint into Elixir `ML.Predict` (Phase I light)

### Later

- [ ] Binance WebSocket (upgrade from REST polling)
- [ ] ML inference serving (ONNX / Nx)
- [ ] Position persistence, backtesting UI
- [ ] Multi-day positional head (M4)
