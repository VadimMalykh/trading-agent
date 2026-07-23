# Training & Evaluation Guide

Session-resilient guide: **more data → better M2 train → evaluate quality / overfitting → optional live peek**.

Related docs:

| Doc | Role |
|-----|------|
| [GCP_TRAIN_EPHEMERAL.md](./GCP_TRAIN_EPHEMERAL.md) | **GCP train: 3 steps (train → status → promote), self-cleaning VM** |
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
docker volume create trading_agent_model_weights 2>/dev/null || true
docker compose up -d postgres

docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 40 \
  --pairs BTCUSDT,ETHUSDT,SOLUSDT
```

Writes best checkpoint (by **primary gated dir_acc** @ gate 0.40, with early stop on val loss) to:

- `/models/m2_multi.pt` (Docker volume `model_weights`)  
- `/workspace/train/output/m2_multi.pt` + `history_m2.json`

**Defaults (Phase 1+2):** horizons `5,30,60`, primary **30m**, `seq_len=64`, train-only per-pair z-score (stored in checkpoint; serve uses the same), global time val split.

### Useful knobs

| Flag / env | Default | Suggestions |
|------------|---------|-------------|
| `--epochs` | 40 | early-stops on val loss (`--patience`, default 5) |
| `--seq-len` | 64 | 64 default; try 96 for slower horizons |
| `--horizons` | `5,30,60` | drop 1m; optional `15,60,240` experiment |
| `--primary` | 30 | product / checkpoint horizon |
| `--ckpt-gate` | 0.40 | gate used when ranking checkpoints |
| `--batch-size` | 32 | 32–64 |
| `--pairs` | **DB UI whitelist** (auto) | prefer majors: `BTCUSDT,ETHUSDT,SOLUSDT` |
| `--device` | `cpu` | `cuda` if GPU available in container |
| `LR` / `--lr` | `5e-4` | |
| `WEIGHT_DECAY` | `1e-4` | |
| `BATCH_SIZE` env | 32 | same as flag |

Examples:

```bash
# GPU
docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cuda --epochs 40 \
  --pairs BTCUSDT,ETHUSDT,SOLUSDT

# Custom pairs / horizons (override DB whitelist)
docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 40 \
  --pairs BTCUSDT,ETHUSDT,SOLUSDT --horizons 5,30,60 --primary 30
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

Focus on **primary 30m** (and its gate table) for product decisions. Compare **before vs after** more data/epochs using the same `--gate` list. Look at **edge = dir_acc − 0.5** at the serve gate (`*`).

---

## 5. Evaluate the **training process** (overfitting)

### During training

Each epoch logs train/val loss, per-horizon val acc, and **gate@0.40** coverage / dir_acc / score.  
Checkpoint saves when **primary gated score** improves. Training **early-stops** when val loss stops improving (`patience`, default 5).

| Pattern | Meaning | Action |
|---------|---------|--------|
| train loss ↓ and val loss ↓ | Healthy learning | Continue / more data |
| train ↓ , val ↑ or flat | **Overfitting** | Trust **best** ckpt (early stop should help) |
| Both stuck high | Underfit / hard task | More data, more capacity/epochs, check labels |
| Best gate score early, then worse | Classic overfit | Use saved best `m2_multi.pt` |
| High 3-class acc, tiny gate cov | Flat-dominated / unconfident | Prefer gate **dir_acc** + coverage over raw acc |

### After training

1. Inspect `ml/train/output/history_m2.json` (epoch curves).  
2. Run `eval_m2.py` (section 4).  
3. Optional live peek (section 6) — behaviour only.

### What to write down each run

| Field | Example |
|-------|---------|
| Date | 2026-07-23 |
| Backfill | 180d 1m (+ funding optional) |
| Samples (train log) | ~50000 |
| Horizons / primary | 5,30,60 / 30 |
| Epochs (stopped) | 12 (early stop) |
| seq_len | 64 |
| Best primary gate score | 0.56 |
| eval 30m @ gate 0.4 coverage | 0.15 |
| eval 30m @ gate 0.4 dir_acc | 0.56 |
| Notes | global split + train-only norm |

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
- Live serve uses **checkpoint train-only norm_stats** (same as eval) when present; health shows `norm=ckpt`.  
- This is **not** full P&L paper trading.

---

## 7. Recommended loop (no weeks of waiting)

```text
1. backfill_history.py --days 90 or 180 (optional if DB already full)
2. train_m2.py --epochs 40 (early-stops; defaults 5/30/60 primary 30)
3. Watch train vs val + gate score each epoch
4. eval_m2.py — save gate table (focus 30m PRIMARY)
5. restart ml_inference (or GCP step 5), glance UI
6. If overfit / weak edge → more data / label tuning; not more blind epochs
7. Repeat; only then consider M3 or full paper P&L
```

**GCP:** use [GCP_TRAIN_EPHEMERAL.md](./GCP_TRAIN_EPHEMERAL.md) — 3 steps
(`gcp_train.sh` → `gcp_status.sh` → `gcp_promote.sh`); the train VM self-cleans.

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
| GCP train fails / OOM | See [GCP_TRAIN_EPHEMERAL.md § Run FAILED — inspect](./GCP_TRAIN_EPHEMERAL.md#run-failed--inspect) — VM self-stops; log in bucket + `~/train_m2.log` |

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
  python train_m2.py --device cpu --epochs 40 \
  --pairs BTCUSDT,ETHUSDT,SOLUSDT

# Eval signals (offline)
docker compose --profile ml run --rm ml_trainer \
  python eval_m2.py --checkpoint /models/m2_multi.pt \
  --gate 0.35,0.4,0.45,0.5,0.55,0.6

# Live paper signals
docker compose up -d postgres ml_inference app
docker compose up -d --force-recreate ml_inference   # after retrain
```

---

*Last updated: 2026-07-23*
