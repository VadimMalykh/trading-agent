# FluxTrader — Full Project Plan

Master roadmap for the whole project. Details can change via discussion; this is the **current agreed direction**.

| Doc | Role |
|-----|------|
| **This file** | End-to-end plan, phases, testing, ops |
| [SPEC.md](../SPEC.md) | Original system / infra specification |
| [MODEL.md](../MODEL.md) | ML architecture (signal + policy + risk) |
| [M1_PLAN.md](./M1_PLAN.md) | M1 implementation checklist (session-resilient) |
| [README.md](../README.md) | How to run what exists today |

**Last updated:** 2026-07-18  
**Environment rule:** **Docker only** — no host Elixir/Python/Node installs. Mac needs Docker Desktop.  
**GPU:** Optional later (cloud); M1–M2 designed for **CPU** training.

---

## 1. Product vision

**FluxTrader** is a crypto **futures** trading agent that:

1. Ingests rich market data (not candles alone)  
2. Predicts short-horizon edge with a **supervised** model  
3. Decides actions with a **discrete policy** layer (adapt without full end-to-end RL)  
4. Enforces **hard risk limits** that learning cannot override  
5. Prefers **few high-confidence** trades over high frequency  

**Not goals (near term):** HFT, multi-exchange, explainable-AI-first, pure end-to-end RL price prediction.

---

## 2. Decisions locked (subject to later revision)

| Topic | Decision |
|-------|----------|
| Venue | Binance Futures only |
| Keys for market data | **Not required** (public REST/WS) |
| Keys for trading | Required only for real/manual/auto orders |
| Data style | Batched windows (5s book, etc.), not tick HFT |
| Book | Top 20 levels, compressed features |
| Hand TA indicators | Not core features |
| Signal model | Supervised (direction + magnitude + confidence) |
| Policy | Discrete RL/bandit: flat / long / short / hold / exit |
| Exits | Model-driven hold/exit + hard emergency stops |
| Trade style | Few high-confidence trades |
| Horizons v1 | Short / intra-day (flagship **15m**) |
| Horizons later | Multi-day positional |
| Universe | Majors first; liquid alts later |
| Metrics | Accuracy/calibration + **max drawdown** + net PnL after costs |
| Retrain | Weekly full signal retrain; policy can adapt faster |
| Online weight updates | Avoid full continuous NN updates by default |

Full rationale: [MODEL.md](../MODEL.md).

---

## 3. System architecture (target)

```
┌─────────────────────────────────────────────────────────────┐
│  Phoenix LiveView (dashboard, settings, logs)               │
│  Docker: app                                                │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  Elixir core (fluxtrader)                                   │
│  · Binance adapter (REST + later WS)                        │
│  · MarketData.Collector / stores                            │
│  · Pair selector                                            │
│  · Signal client → ML inference                             │
│  · Policy + RiskManager + Executor                          │
│  Docker: app                                                │
└───────────────────────────┬─────────────────────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
   PostgreSQL/         ML training        ML inference
   TimescaleDB         (PyTorch)          (later: ONNX/Nx
   Docker: postgres    Docker: ml_trainer  or Python serve)
```

**Trading modes** (already partially in code): `simulation` → `signal` → `manual` → `auto`.

**Promotion rule:** no `auto` until backtest + simulation pass accuracy, max DD, and net PnL gates.

---

## 4. Phase map

```
Phase 0  Scaffold          ✅ done (Elixir umbrella, Docker, LiveView, sim executor)
    │
Phase M1 Data + 15m supervised baseline     ✅ pipeline done (improve quality ongoing)
    │
Phase M2 Multi-horizon + confidence gating  ✅ train_m2 / eval_m2 (quality improves with data)
    │
Phase M3 Discrete policy + sim A/B          ⬜ next
    │
Phase M4 Positional + alts                  ⬜
    │
Phase I  Inference serving + live signals   ✅ light (serve.py + SignalEngine + dashboard)
    │
Phase S  Simulation hardening + paper       ⬜
    │
Phase P  Production (manual → auto)         ⬜ gated
```

Legacy SPEC “Phase 1–4” maps roughly as:

| SPEC | This plan |
|------|-----------|
| Phase 1 Dev (data + ML + dashboard) | 0 + M1 + I (partial) |
| Phase 2 Backtesting | M1–M3 eval + dedicated backtest |
| Phase 3 Simulation | S |
| Phase 4 Production | P |

---

## 5. Phase details

### Phase 0 — Scaffold ✅

**Done:** Docker Compose, Elixir umbrella, TimescaleDB, LiveView dashboard/settings, risk/executor stubs, public Binance client, basic candle poll.

---

### Phase M1 — Data + supervised 15m baseline ✅ (pipeline)

**Goal:** Prove ingest → store → features → train → eval on CPU in Docker.

| Area | Status | Notes |
|------|--------|--------|
| Tables: candles, book, trades, funding, OI, liquidations | Done | Liquidations may be empty if endpoint restricted |
| Collector + kline backfill | Done | Public REST, no keys |
| Feature matrix (microstructure + OHLCV) | Done | No hand TA as core |
| LSTM direction model 15m | Done | Checkpoint `/models/m1_15m.pt` |
| Accuracy | Baseline only | Improves with more book/trade history + train time |

**Ops:** see [M1_PLAN.md](./M1_PLAN.md).

**Still useful after M1 (hardening, not blockers):**

- [ ] Longer history / multi-day collection  
- [ ] Walk-forward CV script  
- [ ] Reduce pandas/SQLAlchemy warnings  
- [ ] Optional CPU-only torch image (smaller builds)  
- [ ] WebSocket upgrade (replace heavy REST polling)  
- [ ] Wire trained checkpoint into Elixir `ML.Predict` (starts Phase I)

---

### Phase M2 — Multi-horizon + confidence gating ✅

**Goal:** Multiple horizons and “trade rarely when sure.”

| Work item | Status |
|-----------|--------|
| Shared LSTM encoder + heads 1m / 15m / 1h | ✅ `models/multi_horizon.py` |
| Per-horizon labels | ✅ `build_multi_horizon_arrays` |
| Train | ✅ `train_m2.py` → `/models/m2_multi.pt` |
| Confidence gate + sweep | ✅ `gate.py`, `eval_m2.py` |
| RL policy | ❌ deferred to M3 |

**Exit criteria:** Gated signals produce fewer calls at higher thresholds; per-horizon metrics reported. Still no live trading.

**Commands:** see [M2_PLAN.md](./M2_PLAN.md).

---

### Phase M3 — Discrete policy ⬜

**Goal:** Policy decides flat/long/short/hold/exit on top of signals (not end-to-end price RL).

| Work item | Description |
|-----------|-------------|
| Action space | `flat`, `long`, `short`, `hold`, `exit` (± size buckets later) |
| Reward | PnL − fees − funding − inventory − DD − overtrade penalties |
| Train | Offline rollouts / bandit-style; Docker `ml_trainer` |
| Integrate | Elixir Executor + hard RiskManager always on |
| A/B | Signal-only vs signal+policy in simulation |

**Exit criteria:** Sim shows controlled max DD and non-pathological trade rate; policy never bypasses hard limits.

---

### Phase M4 — Positional + broader universe ⬜

**Goal:** Longer holds and more pairs without breaking short-horizon stack.

| Work item | Description |
|-----------|-------------|
| Horizons | 4h / 1d heads |
| Alts | Liquidity filters + adapters / fine-tunes |
| Retrain | Separate cadence for slow heads if needed |
| Risk | Position duration limits, funding sensitivity |

---

### Phase I — Inference serving ⬜

**Goal:** Live (or near-live) scores inside the trading loop.

| Option | When |
|--------|------|
| A. Python inference sidecar | Fastest to ship |
| B. ONNX → Nx/EXLA in Elixir | Aligns with original SPEC |

Steps: export checkpoint → score feature windows → `ML.Predict` → PubSub/dashboard → executor (still simulation/signal first).

---

### Phase S — Simulation & backtest hardening ⬜

| Work item | Description |
|-----------|-------------|
| Backtest engine | Fees, funding, slippage assumptions |
| Walk-forward | Purged / time-series CV |
| Paper trading | Live data, no real orders, long enough sample |
| Dashboard | Signals, equity curve, DD, trade log |

---

### Phase P — Production ⬜

| Mode | Requirement |
|------|-------------|
| `signal` | Inference stable; notifications only |
| `manual` | User confirms orders; API keys |
| `auto` | Passed backtest + paper gates; kill switch; monitoring |

**Never skip hard risk manager.**

---

## 6. Data plan

| Stream | Cadence (target) | M1 | Later |
|--------|------------------|----|--------|
| OHLCV multi-TF | 1m+ | ✅ REST + backfill | WS klines |
| L2 top 20 features | 5s | ✅ REST | WS depth |
| Agg trades / flow | 5s windows | ✅ REST | WS aggTrade |
| Funding / premium | ~60s | ✅ | history jobs |
| Open interest | ~60s | ✅ | hist API |
| Liquidations | event/poll | partial | WS forceOrder |

Storage: Postgres/TimescaleDB. Training reads via `DATABASE_URL` from `ml_trainer`.

---

## 7. Model plan (summary)

```
Features (batched)
    → Signal model (supervised, multi-horizon over time)
    → Policy (discrete actions, DD-aware)
    → Hard risk manager
    → Executor (simulation → signal → manual → auto)
```

- **Train:** Python/PyTorch in Docker (`ml_trainer`)  
- **Retrain:** weekly signal (default); policy faster  
- **GPU:** optional cloud when CPU retrain is too slow  

Details: [MODEL.md](../MODEL.md).

---

## 8. Testing strategy (all phases)

| Level | What | Where |
|-------|------|--------|
| Smoke | Containers up, migrations, HTTP 200 | Docker |
| Data | Table counts, null rates, pair coverage | SQL + logs |
| Unit | Feature shapes, label alignment, no leakage | `ml_trainer` / Elixir tests later |
| Model | Time-ordered val accuracy, confusion, calibration | `train.py` / `eval.py` |
| Sim | PnL after costs, max DD, trade count | Executor simulation |
| Paper | Live data, no orders, multi-day | `TRADING_MODE=simulation` / signal |
| Prod gate | Written checklist before auto | Human + metrics |

**No random shuffle of time series.** Walk-forward preferred.

---

## 9. Infrastructure & ops

### Services

| Service | Role | Profile |
|---------|------|---------|
| `app` | Elixir + Phoenix + collectors | default |
| `postgres` | TimescaleDB | default |
| `ml_trainer` | Train/eval PyTorch | `--profile ml` |

### Principles

1. Everything in Docker  
2. Secrets only in `.env` (never commit)  
3. Models on volume `/models`  
4. API keys only when leaving pure market-data/sim path  

### Optional later

- Cloud GPU for heavy retrain  
- Jupyter profile for analysis  
- Separate `ml_inference` service  

---

## 10. Suggested order of work (from today)

1. **More data + better M2 train** — see [TRAINING.md](./TRAINING.md) (`backfill_history.py`, epochs, `eval_m2`)  
2. **Judge signal quality** — train/val curves + gate table (before M3)  
3. **Live paper signals** — [SIMULATION.md](./SIMULATION.md) (optional peek)  
4. **M3** — discrete policy + sim A/B  
5. **S** — full paper P&L / backtest  
6. **M4 / P** — positional, alts, production  

Training runbook: **[TRAINING.md](./TRAINING.md)**.

---

## 11. Success criteria by stage

| Stage | Success looks like |
|-------|-------------------|
| M1 | Pipeline runs; checkpoint saved; metrics reported |
| M2 | Gated signals rarer and better calibrated than always-on |
| M3 | Policy improves DD or net PnL vs signal-only in sim |
| S | Multi-day paper without risk-limit breaches |
| P | Manual then auto with kill switch and monitoring |

---

## 12. Risks & non-goals

**Risks:** non-stationary markets, overfitting, API limits, silent data gaps, RL instability if overused.

**Non-goals for now:** full end-to-end RL prediction, HFT, multi-venue, indicator-heavy production features, requiring local GPU.

---

## 13. Resume after session loss

1. Read **this file** → [MODEL.md](../MODEL.md) → [M1_PLAN.md](./M1_PLAN.md) → [README.md](../README.md)  
2. `docker compose up -d postgres app`  
3. Check data: SQL counts; train: `ml_trainer` commands in README  
4. Continue from **§10 Suggested order** at first incomplete phase  

---

## 14. Changelog (plan-level)

| Date | Note |
|------|------|
| 2026-07-18 | Initial full plan; M0+M1 pipeline documented; M2–P sketched from model discussion |
| 2026-07-19 | M2 implemented (shared encoder, 1m/15m/1h, confidence gate) |

---

*This plan is living documentation. Prefer amending this file when architecture discussions change direction.*
