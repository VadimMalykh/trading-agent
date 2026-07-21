# Training & Evaluation Guide

Session-resilient guide: **more data → better M2 train → evaluate quality / overfitting → optional live peek**.

Related docs:

| Doc | Role |
|-----|------|
| [SIMULATION.md](./SIMULATION.md) | Live paper **signals** (UI / API, no real orders) |
| [M2_PLAN.md](./M2_PLAN.md) | M2 multi-horizon design |
| [PLAN.md](./PLAN.md) | Full roadmap |
| [MODEL.md](../MODEL.md) | ML architecture |
| [README.md](../README.md) | Quick start |

**Rules:** Docker only. No host Python. Market data needs **no API keys**. GPU optional.

---

## 1. Goals (before M3)

Improve **signal quality** of the current M2 model (`m2_multi.pt`):

1. More **historic** candles (and optional funding/OI) from Binance  
2. Longer / better **training**  
3. Judge with **train/val curves** + **`eval_m2.py`**  
4. Optionally glance at live UI signals (not a substitute for eval)

**Not yet:** full paper P&L backtest, M3 policy, real trading.

---

## 2. What data you can collect

### Binance Futures public API (no keys)

| Data | Historic bulk? | Notes |
|------|----------------|--------|
| **Klines OHLCV** | **Yes** | Up to 1500 bars/request; paginate with `startTime`/`endTime` |
| **Funding history** | **Yes** | `/fapi/v1/fundingRate` |
| **Open interest hist** | **Yes** | Futures data endpoints |
| **Agg trades** | Limited | Heavy to backfill long ranges |
| **Order book L2** | **No history** | Only live snapshots (our 5s collector) |

### What the app already does

On start, `MarketData.Collector` backfills **~500** candles per interval (1m/5m/15m/1h) per pair — only hours of 1m data, not months.

### What to run for “more data without waiting weeks”

```bash
docker compose up -d postgres

# Example: 180 days of 1m (+ 15m, 1h) for majors → candles table
docker compose --profile ml run --rm ml_trainer \
  python backfill_history.py \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --intervals 1m,15m,1h \
  --days 180
```

Optional funding backfill:

```bash
docker compose --profile ml run --rm ml_trainer \
  python backfill_history.py --symbols BTCUSDT,ETHUSDT,SOLUSDT --funding --days 180
```

Keep the app running if you also want **live book/trades** to accumulate:

```bash
docker compose up -d postgres app
```

**Book features** only improve with **live** collection time; price model can still improve a lot from kline history alone.

---

## 3. Training (M2)

### Prerequisites

- Postgres up, preferably after backfill  
- Docker image has deps (`sqlalchemy` included); if import errors:

```bash
docker compose build --no-cache ml_trainer ml_inference
```

### Basic retrain (CPU)

```bash
docker compose up -d postgres

docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 30
```

Writes best checkpoint (by **15m** val acc) to:

- `/models/m2_multi.pt` (Docker volume `model_weights`)  
- `/workspace/train/output/m2_multi.pt` + `history_m2.json`

### Useful knobs

| Flag / env | Default | Suggestions |
|------------|---------|-------------|
| `--epochs` | 10 | **20–50**; stop when val stops improving |
| `--seq-len` | 32 | 32 or **64** with more data |
| `--horizons` | `1,15,60` | keep unless experimenting |
| `--primary` | 15 | keep 15m as product horizon |
| `--batch-size` | 32 | 32–64 |
| `--pairs` | **DB UI whitelist** (auto) | omit flag to use Settings pairs; or pass e.g. `BTCUSDT,DOGEUSDT` |
| `--device` | `cpu` | `cuda` only if GPU available in container |
| `LR` env | `1e-3` | try `5e-4` if unstable |
| `BATCH_SIZE` env | 32 | same as flag |

Examples:

```bash
# Longer context
docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 40 --seq-len 64

# Custom pairs / horizons (override DB whitelist)
docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 30 \
  --pairs BTCUSDT,ETHUSDT,DOGEUSDT --horizons 1,15,60 --primary 15
```

**Pairs source:** By default `train_m2` / `eval_m2` load the **Settings UI whitelist** from Postgres (`app_settings`).  
You do **not** edit the train script when you add DOGE in the UI — just collect data for that pair, then re-run train.  
Override only if needed: `--pairs BTCUSDT,DOGEUSDT`.

### After train: reload live inference (optional)

```bash
docker compose restart ml_inference
# or full stack:
docker compose up -d postgres ml_inference app
```

---

## 4. Evaluate signal quality (`eval_m2`)

**Does not** start the UI. Offline report card on **time-ordered** validation split.

```bash
docker compose --profile ml run --rm ml_trainer \
  python eval_m2.py \
  --checkpoint /models/m2_multi.pt \
  --device cpu \
  --gate 0.35,0.4,0.45,0.5,0.55,0.6
```

Output also in `ml/train/output/eval_m2.json`.

### How to read it

| Field | Meaning |
|-------|---------|
| **Ungated accuracy** | 3-class argmax (down/flat/up). Can look high if everything is “flat”. |
| **Confusion matrix** | Rows = truth, cols = pred. Flat column heavy ⇒ shy model. |
| **gate** | Directional conf threshold `max(p_up, p_down)`. |
| **coverage** | Fraction of bars that would **trade**. Falls as gate rises. |
| **n_gated** | Absolute trade count. `0` ⇒ gate too high. |
| **gated_acc** | Hit rate among gated trades (true flat = miss if we forced a side). |
| **dir_acc** | Hit rate among gated trades where truth was up/down. |
| **mean_conf** | Avg conf on gated samples. |

Focus on **15m** for product decisions. Compare **before vs after** more data/epochs using the same `--gate` list.

---

## 5. Evaluate the **training process** (overfitting)

### During training

Each epoch logs train/val loss and per-horizon val acc. Checkpoint saves when **primary 15m** val acc improves (not necessarily last epoch).

| Pattern | Meaning | Action |
|---------|---------|--------|
| train loss ↓ and val loss ↓ | Healthy learning | Continue / more data |
| train ↓ , val ↑ or flat | **Overfitting** | Fewer epochs, more data, lower LR; trust **best** ckpt |
| Both stuck high | Underfit / hard task | More data, more capacity/epochs, check labels |
| Best 15m val early, then worse | Classic overfit | Use saved best `m2_multi.pt` |
| 1m acc high but all-flat confusion | Flat-dominated score | Prefer gate **dir_acc** over raw acc |

### After training

1. Inspect `ml/train/output/history_m2.json` (epoch curves).  
2. Run `eval_m2.py` (section 4).  
3. Optional live peek (section 6) — behaviour only.

### What to write down each run

| Field | Example |
|-------|---------|
| Date | 2026-07-20 |
| Backfill | 180d 1m/15m/1h |
| Samples (train log) | ~50000 |
| Epochs | 30 |
| seq_len | 64 |
| Best 15m val acc | 0.55 |
| eval 15m @ gate 0.4 coverage | 0.05 |
| eval 15m @ gate 0.4 dir_acc | 0.52 |
| Notes | less flat collapse |

---

## 6. Live signals (optional, not the main grade)

See [SIMULATION.md](./SIMULATION.md).

```bash
docker compose up -d postgres ml_inference app
curl -s http://localhost:8001/health
curl -s http://localhost:4000/api/signals
# Dashboard http://localhost:4000
```

- **FLAT / SKIP** most of the time can be normal (gate + weak model).  
- Live conf uses a slightly different online z-score than train — don’t expect identical stats to `eval_m2`.  
- This is **not** full P&L paper trading.

---

## 7. Recommended loop (no weeks of waiting)

```text
1. backfill_history.py --days 90 or 180
2. train_m2.py --epochs 30 (or 40–50)
3. Watch train vs val each epoch
4. eval_m2.py — save gate table (focus 15m)
5. Optional: restart ml_inference, glance UI
6. If overfit → more data / fewer epochs / lower LR
7. Repeat; only then consider M3 or full paper P&L
```

---

## 8. GPU note

- **CPU is enough** to iterate if jobs finish in reasonable time.  
- GPU only speeds training; it does not replace history or good eval.  
- Use `--device cuda` only when the container has GPU access (not typical default Mac Docker).

---

## 9. Troubleshooting

| Problem | Fix |
|---------|-----|
| `No module named 'sqlalchemy'` | `docker compose build --no-cache ml_trainer ml_inference` |
| `Not enough samples` | Run `backfill_history.py`; ensure postgres has candles |
| `model not found` on inference | Run `train_m2.py` first; check volume `model_weights` |
| eval `n_gated=0` all gates | Model never directionally confident; more data/train or lower gates for plumbing only |
| Binance rate limits on backfill | Script retries/sleeps; reduce `--symbols` parallelism / increase sleep |

---

## 10. Command cheat sheet

```bash
# Data
docker compose up -d postgres
docker compose --profile ml run --rm ml_trainer \
  python backfill_history.py --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --intervals 1m,15m,1h --days 180

# Train
docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 30

# Eval signals (offline)
docker compose --profile ml run --rm ml_trainer \
  python eval_m2.py --checkpoint /models/m2_multi.pt \
  --gate 0.35,0.4,0.45,0.5,0.55,0.6

# Live paper signals
docker compose up -d postgres ml_inference app
docker compose restart ml_inference   # after retrain
```

---

*Last updated: 2026-07-20*
