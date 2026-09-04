# FluxTrader

Real-time cryptocurrency futures trading agent with ML-driven decision making.

## Status

**M3 — the trading policy is live in paper.** A pre-registered rules policy (top 2% of bars by
model confidence, held four hours, sized by BTC's daily move) is wired to a crossing executor on
the always-on VM and paper-trading forward. M2 is frozen as a research object; every M3 build
item is complete. Nothing trades real money: the `auto` order path is unsigned by design.

👉 **[docs/BACKLOG.md](./docs/BACKLOG.md) is the entry point** — the single index of every open,
parked and closed item, with the revival trigger for each. Start there.

| for | read |
|---|---|
| what runs live, and how to read `/api/health` | [docs/M3_5_INTEGRATION.md](./docs/M3_5_INTEGRATION.md) |
| the rules that govern a promotion | [docs/M3_PROTOCOL.md](./docs/M3_PROTOCOL.md) |
| the policy milestone and what each step established | [docs/M3_PLAN.md](./docs/M3_PLAN.md) |
| training: what M2 measured, and the standing rules | [docs/NEXT_TRAINING_PLAN.md](./docs/NEXT_TRAINING_PLAN.md) |
| how to train, locally or on GCP | [docs/TRAINING.md](./docs/TRAINING.md) |

## Quick Start

Requires only Docker. No local installs needed.

```bash
cp .env.example .env
# once per machine (model volume is external — silences compose WARN)
docker volume create trading_agent_model_weights
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
docker volume create trading_agent_model_weights 2>/dev/null || true

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
- **What runs live, and how to read it:** [docs/M3_5_INTEGRATION.md](./docs/M3_5_INTEGRATION.md)

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
└── docs/                       # BACKLOG.md is the entry point
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

The architecture note is archived at [docs/archive/MODEL.md](./docs/archive/MODEL.md); it is the
design as frozen in 2026-07, not as measured. For what the model measures, see
[docs/NEXT_TRAINING_PLAN.md](./docs/NEXT_TRAINING_PLAN.md) §1.

- Supervised signal model (microstructure + OHLCV + funding/OI; no hand TA as core)
- Discrete policy layer (flat/long/short/hold/exit) — not end-to-end RL
- Hard risk manager always on
- Phases M1–M4 (data → multi-horizon → policy → positional)

## What's Next

Everything open, parked or closed — with the trigger that would revive each parked item — is in
**[docs/BACKLOG.md](./docs/BACKLOG.md)**. In short: the walk-forward folds are the next
investment, the forward paper test needs calendar time rather than work, and real money is
blocked on an unverified fee tier and an unsigned order path.
