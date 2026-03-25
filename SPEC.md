# Crypto Trading Agent - Technical Specification

## 1. Project Overview

**Project Name:** FluxTrader  
**Type:** Real-time crypto futures trading agent with ML-driven decision making  
**Core Functionality:** Analyzes Binance market data, predicts price movements using deep learning, and executes trades (with optional auto-trading mode)  
**Target Users:** Individual traders with intermediate to advanced knowledge of crypto futures trading  
**Development Environment:** 100% Docker Compose - no dependencies installed on host PC

---

## 2. Core Principle: Docker-First Development

**All development and execution occurs exclusively within Docker containers.**

| What You Get | What You Need |
|--------------|---------------|
| Complete dev environment | Docker Desktop |
| Pre-configured Elixir + Erlang | VS Code with Dev Containers (optional) |
| Python + PyTorch + CUDA | Any text editor / terminal |
| TimescaleDB with migrations | No host installations |

### Docker Services

```yaml
services:
  app:          # Elixir 1.16+ + Phoenix
  postgres:     # PostgreSQL + TimescaleDB extension
  ml_inference: # Nx + Axon + EXLA (CUDA)
  ml_trainer:   # Python + PyTorch (CUDA, on-demand)
  jupyter:      # JupyterLab for analysis (optional)
```

**Start development:**
```bash
docker compose up
```

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (Phoenix LiveView)                    │
│  • Dashboard: Positions, P&L, Open Orders                                   │
│  • Settings: API keys, Risk parameters, Trading mode                        │
│  • Logs: Trade history, Model signals, System events                         │
│                              [DOCKER: fluxtrader_web]                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          BACKEND (Elixir Application)                       │
│                                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │
│  │   Binance    │  │   Pair      │  │  Trade      │  │   Risk          │   │
│  │   Adapter    │  │   Selector  │  │  Executor   │  │   Manager       │   │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Message Bus (Elixir Processes)                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Data Store (TimescaleDB/Postgres)                 │   │
│  │  • OHLCV candles  • Order book snapshots  • Trades  • Positions       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              [DOCKER: postgres]                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ML SERVICES                                         │
│                                                                             │
│  ┌─────────────────────────┐        ┌─────────────────────────────────────┐│
│  │   Training Pipeline     │        │   Inference Service                 ││
│  │   (Python + PyTorch)   │──────▶│   (Nx/Axon + EXLA)                ││
│  │   RL + Supervised      │        │   Real-time predictions            ││
│  │   [DOCKER: ml_trainer] │        │   [DOCKER: ml_inference]          ││
│  └─────────────────────────┘        └─────────────────────────────────────┘│
│                                                                             │
│  GPU: NVIDIA GPU passthrough to Docker containers                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Technology Stack

| Component | Technology | Docker Image |
|-----------|------------|--------------|
| Backend Core | Elixir 1.16+ | `hexpm/elixir:latest` |
| ML Inference | Nx + Axon + EXLA | Custom Elixir + CUDA |
| ML Training | Python 3.11+ / PyTorch | `pytorch/pytorch:latest-cuda` |
| Database | PostgreSQL + TimescaleDB | `timescale/timescaledb:latest-pg16` |
| WebSocket | Binance WebSocket Streams | Native Elixir |
| Frontend | Phoenix LiveView | Same as Backend |
| Orchestration | Docker Compose | N/A |

---

## 5. Data Pipeline

### 5.1 Data Sources

| Source | Type | Purpose |
|--------|------|---------|
| Binance Spot API | REST | Historical klines, exchange info |
| Binance Futures API | REST + WebSocket | Real-time data, order execution |
| Binance WebSocket Streams | WebSocket | Live trades, klines, depth |
| CoinGecko (optional) | REST | Market-wide metrics |

### 5.2 Data Features (Full Market Data)

**Level 1 - Price Data:**
- OHLCV candles (1m, 5m, 15m, 1h, 4h, 1d)
- VWAP, TWAP indicators

**Level 2 - Order Book:**
- Bid/ask depth (top 20-100 levels)
- Order book imbalance
- Liquidity metrics (bid/ask walls)

**Level 3 - Market Metrics:**
- Funding rate (futures)
- Open interest
- Long/short ratio
- Recent liquidations
- Taker buy/sell volume

**Level 4 - Cross-Asset Signals (optional):**
- BTC dominance
- Fear & Greed index

### 5.3 Data Storage

```
Database: TimescaleDB (PostgreSQL extension)
├── candles_1m, candles_5m, candles_1h (hypertables)
├── orderbook_snapshots (compressed)
├── trades, funding_rates, liquidations (hypertables)
└── positions (regular table)
```

---

## 6. Pair Selection System

### 6.1 Selection Layers

```
LAYER 1: Manual Whitelist (user-configured, always analyzed)
    ↓
LAYER 2: 3rd Party Screener Signals (optional integration)
    ↓
LAYER 3: ML-Based Scoring (future phase)
    ↓
FINAL: Top N pairs by combined score → max_concurrent_positions
```

### 6.2 3rd Party Integrations (Optional)

| Service | Purpose |
|---------|---------|
| CoinGecko API | Market-wide sentiment |
| Whale Alert | Large transaction tracking |
| Fear & Greed Index | Market sentiment |

---

## 7. ML Architecture

### 7.1 Model Objectives

| Task | Type | Output |
|------|------|--------|
| Price Direction | Classification | Probability of up/down/sideways |
| Price Magnitude | Regression | Expected % change |
| Trade Signal | Combined | Entry confidence + direction + size |

### 7.2 Hybrid Approach

| Phase | Technology | Docker Service |
|-------|------------|----------------|
| **Training** | Python + PyTorch | `ml_trainer` |
| **Serving** | Nx + Axon + EXLA | `ml_inference` |

**Rationale:** Python required for RL training (Stable-Baselines3, RLlib); Nx/Axon sufficient for real-time inference.

### 7.3 Model Architecture Options

```
Input Features (per pair, per timestep):
├── Price: [close, open, high, low, volume] × timeframes
├── Order Book: [bid_volumes, ask_volumes, imbalance]
├── Market: [funding, oi, liq_vol, long_short_ratio]
└── Temporal: hour, day_of_week

Architecture Options:
├── LSTM/GRU + Attention (time series focus)
├── 1D-CNN + LSTM (pattern recognition)
├── Transformer Encoder (self-attention)
└── Ensemble of above
```

### 7.4 RL Considerations

If RL is needed for trade execution optimization:
- **Training:** Python with Stable-Baselines3 or RLlib
- **Serving:** Export to ONNX, serve via Nx/EXLA
- **Alternative:** Behavioral Cloning (train supervised, deploy as policy)

---

## 8. Trading Logic

### 8.1 Trade Decision Flow

```
Market Data → Feature Engineering → ML Inference
                                           ↓
        [Direction: BULL (78%), Size: 0.5%]
                                           ↓
Signal Strength > threshold?
├── Yes → Calculate position size → Check risk limits → Execute/Alert
└── No  → Hold / monitor
```

### 8.2 Order Parameters

| Parameter | Calculation |
|-----------|-------------|
| Direction | Long / Short / Flat from ML signal |
| Entry Price | Market or limit (configurable) |
| Position Size | Kelly criterion or fixed % of margin |
| Stop Loss | ATR-based or fixed % |
| Take Profit | Risk:Reward ratio (e.g., 1:2) |
| Leverage | Risk-based (1x-10x, configurable) |

### 8.3 Risk Management

| Parameter | Default | Description |
|-----------|---------|-------------|
| Signal threshold | 0.65 | Min confidence to act |
| Min confidence | 0.70 | Minimum model confidence |
| Max position size | 10% | Of margin per position |
| Max concurrent positions | 3 | Active positions limit |
| Max daily loss | 5% | Stops trading if hit |
| Max drawdown | 10% | Pause and alert |
| Stop loss | 2% | ATR-based or fixed |
| Take profit ratio | 1:2 | Risk:reward |
| Leverage | 5x | Configurable 1x-10x |

---

## 9. Trading Modes

| Mode | Behavior | Docker Config |
|------|----------|---------------|
| **Simulation** | Paper trades, no real orders | `SIMULATION_MODE=1` |
| **Signal Only** | ML predictions → notification only | `TRADING_MODE=signal` |
| **Manual Approval** | Signal → review → user confirms | `TRADING_MODE=manual` |
| **Auto Trading** | Full automation after backtest | `TRADING_MODE=auto` |

---

## 10. Go-Live Workflow

```
PHASE 1: Development → Data pipeline + ML inference + Dashboard
    ↓
PHASE 2: Backtesting → Train model + Validate performance
    ↓
PHASE 3: Simulation → Paper trading with live data
    ↓
PHASE 4: Production → Auto-trading (after backtest validation)
```

---

## 11. Infrastructure

### 11.1 Docker Compose Services

```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile.app
    environment:
      DATABASE_URL: postgresql://fluxtrader:secret@postgres:5432/fluxtrader
      BINANCE_API_KEY: ${BINANCE_API_KEY}
      BINANCE_API_SECRET: ${BINANCE_API_SECRET}
      TRADING_MODE: ${TRADING_MODE:-signal}
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - app_data:/app
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  postgres:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_USER: fluxtrader
      POSTGRES_PASSWORD: secret
      POSTGRES_DB: fluxtrader
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U fluxtrader"]
      interval: 5s
      timeout: 5s
      retries: 5

  ml_inference:
    build:
      context: ./ml/inference
      dockerfile: Dockerfile.inference
    environment:
      MODEL_PATH: /models/latest
      EXLA_BACKEND: cuda
    volumes:
      - model_weights:/models
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  ml_trainer:
    build:
      context: ./ml/train
      dockerfile: Dockerfile.train
    environment:
      CUDA_VISIBLE_DEVICES: "0"
    volumes:
      - model_weights:/models
      - ./ml:/workspace
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  jupyter:
    image: jupyter/pytorch-notebook:latest-cuda
    ports:
      - "8888:8888"
    volumes:
      - ./ml:/home/jovyan/work
    environment:
      JUPYTER_TOKEN: localdev

volumes:
  app_data:
  postgres_data:
  model_weights:
```

### 11.2 GPU Configuration

> **TODO:** Specify NVIDIA GPU model/VRAM to complete GPU configuration.

Docker Desktop (Mac/Windows):
```bash
# Enable GPU in Docker Desktop settings first
docker run --gpus all nvidia/cuda:12.1-base nvidia-smi
```

Linux:
```bash
# Ensure nvidia-container-toolkit is installed
nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### 11.3 Local Development Commands

```bash
# Start all services
docker compose up

# Run migrations
docker compose exec app mix ecto.migrate

# Open iex shell
docker compose exec app iex -S mix

# View logs
docker compose logs -f app

# Train model (on-demand)
docker compose run --rm ml_trainer python train.py --epochs 100

# Access Jupyter
# http://localhost:8888 (token: localdev)
```

---

## 12. File Structure

```
crypto_trader/
├── docker-compose.yml
├── Dockerfile.app
├── .env.example
│
├── apps/
│   ├── fluxtrader/              # Core business logic
│   │   ├── lib/
│   │   │   ├── binance/         # Binance API adapter
│   │   │   │   ├── client.ex
│   │   │   │   ├── websocket.ex
│   │   │   │   └── adapter.ex
│   │   │   ├── data/            # Data stores
│   │   │   │   ├── candle_store.ex
│   │   │   │   ├── orderbook_store.ex
│   │   │   │   └── feature_engineering.ex
│   │   │   ├── pairs/          # Pair selector
│   │   │   │   ├── selector.ex
│   │   │   │   └── whitelist.ex
│   │   │   ├── trading/        # Trading logic
│   │   │   │   ├── executor.ex
│   │   │   │   ├── position_manager.ex
│   │   │   │   └── risk_manager.ex
│   │   │   └── ml/             # ML integration
│   │   │       ├── model_loader.ex
│   │   │       └── predict.ex
│   │   └── test/
│   │
│   └── fluxtrader_web/         # Phoenix LiveView UI
│       ├── lib/
│       │   ├── fluxtrader_web/
│       │   │   ├── endpoint.ex
│       │   │   ├── router.ex
│       │   │   └── live/
│       │   │       ├── dashboard_live.ex
│       │   │       └── settings_live.ex
│       │   └── fluxtrader_web.ex
│       └── test/
│
├── ml/
│   ├── train/                   # Python training
│   │   ├── Dockerfile.train
│   │   ├── requirements.txt
│   │   ├── train.py
│   │   ├── data/
│   │   │   ├── dataset.py
│   │   │   └── preprocessor.py
│   │   ├── models/
│   │   │   ├── lstm.py
│   │   │   ├── transformer.py
│   │   │   └── ensemble.py
│   │   └── rl/
│   │       ├── ppo_agent.py
│   │       └── replay_buffer.py
│   │
│   ├── inference/
│   │   ├── Dockerfile.inference
│   │   └── (Elixir-based, no separate Dockerfile needed)
│   │
│   └── notebooks/
│       └── analysis.ipynb
│
├── config/
│   ├── config.exs
│   ├── runtime.exs
│   └── prod.exs
│
├── priv/
│   └── postgres/
│       └── migrations/
│
└── SPEC.md
```

---

## 13. API Integrations

### 13.1 Binance Futures API Endpoints

| Endpoint | Usage |
|----------|-------|
| `GET /fapi/v1/exchangeInfo` | Trading rules, pair list |
| `GET /fapi/v1/klines` | Historical candles |
| `GET /fapi/v1/depth` | Order book snapshot |
| `GET /fapi/v1/premiumIndex` | Funding rates |
| `GET /fapi/v1/openInterest` | Open interest |
| `GET /fapi/v1/positions` | Current positions |
| `POST /fapi/v1/order` | Place order |
| `WS streams` | Real-time trades, klines, depth |

### 13.2 Optional 3rd Party Integrations

| Service | Purpose | API Required |
|---------|---------|--------------|
| CoinGecko | Market-wide sentiment | Free tier |
| Whale Alert | Large transaction tracking | Free tier |
| Fear & Greed Index | Market sentiment | Free tier |
| Glassnode | Advanced on-chain | Paid |

---

## 14. Configuration Parameters

### 14.1 Environment Variables (.env.example)

```bash
# Database
DATABASE_URL=postgresql://fluxtrader:secret@postgres:5432/fluxtrader

# Binance
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here

# Trading Mode: simulation, signal, manual, auto
TRADING_MODE=signal

# ML
MODEL_PATH=/models/latest
EXLA_BACKEND=cuda

# Risk
MAX_POSITIONS=3
MAX_POSITION_PCT=0.10
STOP_LOSS_PCT=0.02
TAKE_PROFIT_RATIO=2.0
LEVERAGE=5

# Whitelist pairs (comma-separated)
WHITELIST_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT
```

---

## 15. Open Questions

| Question | Status |
|----------|--------|
| NVIDIA GPU model/VRAM? | **TODO: Specify** |
| Is RL essential? | Supervised baseline first, RL if needed |
| Historical data available? | Start with 6-12 months Binance data |
| Auto-trading approval? | Backtest validation required first |

---

## 16. Risks & Disclaimers

> **WARNING**: Cryptocurrency trading, especially futures, involves substantial risk of loss. This software is provided for educational and research purposes. The developers are not responsible for any financial losses incurred through its use.

### Known Risks

- Market volatility and unpredictable price movements
- Model prediction errors and overfitting
- API rate limits and connection failures
- Slippage and liquidity issues
- Funding rate changes in futures trading
- Regulatory changes in cryptocurrency markets

---

## 17. Success Metrics (Phase 1)

| Metric | Target |
|--------|--------|
| Data latency | < 100ms |
| Inference latency | < 50ms |
| Backtesting coverage | 6+ months |
| Model accuracy | > 52% (baseline: random) |
| Dashboard uptime | 99%+ |

---

*Specification Version: 0.2*  
*Last Updated: 2026-03-25*  
*Environment: Docker Compose Only*
