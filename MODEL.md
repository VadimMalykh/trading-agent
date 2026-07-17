# FluxTrader — Model Architecture

Specification for ML signal + policy design. Complements [docs/PLAN.md](./docs/PLAN.md) (roadmap), `SPEC.md` (system), and `README.md` (status).

**Status:** Design frozen for M1–M3 (discussion 2026-07-18)  
**Version:** 0.1

---

## 1. Goals & Constraints

| Decision | Choice |
|----------|--------|
| Market | Crypto **futures only** (Binance) |
| Trade style | **Few high-confidence** trades |
| V1 horizon | Short / intra-day (minutes–hours) |
| Later | Multi-day positional trades |
| Explainability | Low priority; **accuracy + max drawdown** matter |
| Indicators (RSI/SMA/etc.) | **Not core features** — NN learns transforms from raw/microstructure data |
| Real-time | Batched windows OK (not true HFT) |
| Universe | Majors first; alts with liquidity filter |

### Primary metrics

1. Signal quality: directional accuracy / calibration of confidence  
2. **Max drawdown** (hard constraint + training objective)  
3. Net PnL after fees + funding (truth)  
4. Trade frequency (detect overtrading)

Accuracy alone is insufficient — 52% direction can still lose after costs.

---

## 2. Architecture Overview

Hybrid: **supervised signal model** + **discrete policy layer** + **hard risk manager**.

Not end-to-end RL for price prediction. RL/bandit adapts *actions* (trade / size / hold / exit), not raw price dynamics.

```
Batched market windows
  OHLCV (multi-TF)
  trades / taker flow
  L2 top-20 features
  funding, OI, liquidations
        │
        ▼
┌───────────────────────────────┐
│  Signal model (supervised)    │
│  P(up/down/flat), magnitude,  │
│  confidence / uncertainty     │
│  Horizons: 5m–1h (v1)         │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│  Policy (discrete RL/bandit)  │
│  Actions: flat | long | short │
│           | hold | exit       │
│  (+ optional size buckets)    │
│  Inputs: signal + position +  │
│  unrealized PnL + regime      │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│  Hard risk manager            │
│  max DD, max positions,       │
│  daily loss, leverage caps    │
│  Emergency stop (not learned) │
└───────────────────────────────┘
```

### Why this split

| Layer | Job | Why not the other |
|-------|-----|-------------------|
| Supervised signal | Forecast direction/magnitude | RL is sample-inefficient and unstable for pure price prediction |
| Policy | When to trade, hold, exit, size | Adapts to inventory, fees, regime without relearning price |
| Risk manager | Hard limits | Must never be optimized away |

---

## 3. Data Contract (V1)

### 3.1 Streams

| Stream | Cadence | Role |
|--------|---------|------|
| OHLCV 1m / 5m / 1h | continuous | Price/volume context |
| Aggregate trades / taker buy–sell | batch to 1s–5s | Order flow |
| Order book **top 20** | snapshot **5s** (default) | Imbalance, liquidity |
| Funding rate | as published | Futures carry |
| Open interest | as available | Positioning |
| Liquidations | event → window aggregate | Stress / cascades |

### 3.2 Book features (compressed, not raw 40 levels)

Prefer engineered book features over dumping all levels:

- Bid/ask volume imbalance (near book)  
- Microprice vs mid  
- Spread  
- Near vs far depth slope  
- Wall size / distance (optional)  

Default snapshot interval: **5 seconds**. Top **20** levels.

### 3.3 What we deliberately skip as core inputs

- Hand-crafted TA indicators (RSI, MACD, Bollinger, etc.) as primary features  
- Optional later: indicators only for **baselines / ablations**, not production path  

### 3.4 Feature windows

- Live path: WS/REST → buffer → fixed windows (e.g. 5s / 1m tensors)  
- Model scores on windows, not every tick  
- Storage: TimescaleDB hypertables for candles, trades, book snapshots, funding/OI  

---

## 4. Signal Model (Supervised)

### 4.1 Outputs (per symbol, per horizon)

| Output | Type | Notes |
|--------|------|--------|
| Direction | Classification | up / down / flat |
| Magnitude | Regression | Expected % move |
| Confidence | Calibrated probability | Gate for “few high-confidence” trades |
| Uncertainty | Optional | Ensemble / dropout / quantile |

### 4.2 Horizons

| Phase | Horizons |
|-------|----------|
| **M1 (flagship)** | **15m** (primary); optional 5m aux |
| M2 | 1m, 15m, 1h multi-head |
| M4 | + 4h / 1d for positional |

**V1 focus:** short / intra-day. Multi-day positional deferred.

### 4.3 Labels

- Primary: forward return over horizon + direction  
- Auxiliary (recommended): **triple-barrier** — hit TP / hit SL / timeout  
- Train for **calibrated confidence** so policy can refuse weak trades  

### 4.4 Architecture options (implementation choice)

Any of:

- LSTM / GRU + attention  
- 1D-CNN + temporal stack  
- Transformer encoder  
- Ensemble  

Training stack: **Python + PyTorch**.  
Serving target (later): ONNX → Nx/EXLA or Python inference service.

### 4.5 Majors + alts

- Shared backbone trained on liquid majors first (e.g. BTC, ETH, SOL)  
- Adapters / fine-tunes for liquid alts  
- Liquidity filter: min volume / OI before an alt is tradeable  

---

## 5. Policy Layer (Discrete)

### 5.1 Actions (v1)

Discrete only:

| Action | Meaning |
|--------|---------|
| `flat` | No position / stay out |
| `long` | Enter or stay long |
| `short` | Enter or stay short |
| `hold` | Keep current position |
| `exit` | Close position |

Optional later: size buckets (`small` / `med`) as part of action space.

**Skip / flat is first-class** — rare trading is a feature, not a bug.

### 5.2 Policy inputs

- Signal outputs (direction, magnitude, confidence)  
- Open position state (side, size, entry, unrealized PnL)  
- Funding / vol regime features  
- Recent drawdown / daily PnL  

### 5.3 Reward sketch (training)

```
reward =
  realized_pnl
  − fees
  − funding
  − inventory_penalty
  − drawdown_penalty
  − overtrade_penalty
```

### 5.4 Exits

- **Model decides** hold vs exit (not fixed TP/SL only)  
- Hard risk manager still enforces emergency stop / max loss / max DD  
- Soft TP/SL may exist as risk floor, not sole exit logic  

### 5.5 Why not full end-to-end RL

- Sample inefficient on non-stationary crypto  
- Hard to debug; easy to overfit a regime  
- Policy-on-signals still adapts behavior while signal model stays stable  

---

## 6. Adaptation & Retraining

| Layer | Cadence | Notes |
|-------|---------|--------|
| Signal model | **Weekly full retrain** | Rolling window (e.g. 3–6 months), recent data upweighted |
| Signal model | Optional **daily light fine-tune** | Majors only at first |
| Policy | Faster than signal | Bandit thresholds or more frequent retrain |
| Intraday | **No full weight updates** by default | Policy thresholds / confidence gates only |

### Why not continuous online NN updates

- Catastrophic forgetting  
- Silent drift under regime change  
- Hard to audit after a bad day  

Policy-layer adaptation gives “feel adaptive” without unstable weight thrashing.

---

## 7. Risk Integration

Always outside the learned stack:

| Control | Default (from SPEC) |
|---------|---------------------|
| Max concurrent positions | 3 |
| Max position % of margin | 10% |
| Max daily loss | 5% |
| Max drawdown | 10% → pause + alert |
| Leverage cap | configurable (e.g. 5x) |
| Min signal confidence | high bar for “few trades” (e.g. ≥ 0.70–0.75) |

Learned policy **cannot** override hard limits.

---

## 8. Evaluation Protocol

### Offline

1. Walk-forward / purged time-series CV (no random shuffle)  
2. Report: accuracy, Brier/calibration, max DD, net PnL after fees+funding, trade count  
3. Ablations: no-book, no-funding, candle-only baseline  

### Paper / simulation

1. Live data, no real orders (`TRADING_MODE=simulation`)  
2. Compare signal-only vs signal+policy  
3. Promote only if max DD and net PnL pass gates  

### Production

1. Signal / manual approval before auto  
2. Auto only after backtest + simulation validation  

---

## 9. Implementation Phases

### M1 — Data + supervised baseline

- [ ] Ingest trades, top-20 book snapshots (5s), funding, OI, liquidations  
- [ ] Feature windows + TimescaleDB storage  
- [ ] Supervised baseline on **15m** horizon  
- [ ] Confidence output + offline metrics  
- [ ] No RL yet  

### M2 — Multi-horizon + gating

- [ ] Heads: 1m, 15m, 1h  
- [ ] Confidence gating for few high-confidence trades  
- [ ] Uncertainty / calibration improvements  

### M3 — Discrete policy

- [ ] Actions: flat / long / short / hold / exit  
- [ ] DD-aware reward; train offline on historical rollouts  
- [ ] Integrate with existing risk manager  
- [ ] Simulation comparison: signal-only vs policy  

### M4 — Positional + broader universe

- [ ] Longer horizon heads (4h / 1d)  
- [ ] Alt adapters + liquidity filters  
- [ ] Optional continuous size later (if discrete buckets insufficient)  

---

## 10. Relation to Current Codebase

| Component | Today | Target |
|-----------|--------|--------|
| `Binance.Client` | REST klines etc. | + trades, depth, funding, OI |
| Data feed | REST poll 60s | Batched WS/REST windows 5s–1m |
| `FeatureEngineering` | TA indicators | Replace core path with microstructure features |
| `ML.Predict` | Mock RSI stub | Call trained signal model |
| `Trading.Executor` / `RiskManager` | Simulation modes | Policy actions + hard limits |
| `ml/train` | LSTM skeleton | Full supervised pipeline → policy later |

---

## 11. Open Implementation Defaults

Agreed defaults when unspecified:

| Item | Default |
|------|---------|
| M1 flagship horizon | **15m** |
| Book depth | **Top 20** |
| Book snapshot | **5s** |
| Policy action space | Discrete (no continuous size in M3) |
| First pairs | BTCUSDT, ETHUSDT, SOLUSDT |
| Training | Python/PyTorch offline; retrain weekly |

---

## 12. Non-goals (for now)

- Full end-to-end RL price prediction  
- True tick-by-tick HFT  
- Explainable AI / SHAP-first design  
- Hand-indicator-heavy feature store as production path  
- Multi-day positional trading in M1–M3  

---

*Last updated: 2026-07-18*
