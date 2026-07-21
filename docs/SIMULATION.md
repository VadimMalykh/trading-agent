# Signal Simulation Guide (Phase I light)

How to run **paper signal simulation** with the wired M2 model on **CPU + small data**.  
No API keys. No real orders.

For **historic backfill, more epochs, overfitting, `eval_m2`**: see **[TRAINING.md](./TRAINING.md)**.

---

## What “simulation” means here

| Does | Does not |
|------|----------|
| Load `m2_multi.pt` in `ml_inference` | Place Binance orders |
| Score BTC/ETH/SOL every ~30s | Guarantee profitable edge |
| Show signals on dashboard + `/api/signals` | Replace offline `eval_m2.py` |
| Log `[SIM_SIGNAL]` and optional sim positions | Full backtest with fees/funding (later) |

Treat results as **pipeline + behaviour check**, not a green light to trade real money.

---

## Prerequisites

1. Docker Desktop running  
2. Model checkpoint exists (train once if needed):

```bash
docker compose up -d postgres app
# wait for collector backfill / data

docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 8
```

Checkpoint path inside Docker: `/models/m2_multi.pt` (volume `model_weights`).

---

## Start the full stack (this is how you launch simulation)

You do **not** need `eval_m2.py` to run live sim. Offline eval is only for metrics.

```bash
# 0) Once: train model if /models/m2_multi.pt missing
docker compose up -d postgres
docker compose --profile ml run --rm ml_trainer python train_m2.py --device cpu --epochs 8

# 1) Live paper simulation stack
docker compose up -d postgres ml_inference app
```

Wait ~30–60s for SignalEngine’s first cycle. Then open the dashboard.

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:4000 |
| Signals API | http://localhost:4000/api/positions |
| Signals API | http://localhost:4000/api/signals |
| Inference health | http://localhost:8001/health |
| Single predict | http://localhost:8001/predict?symbol=BTCUSDT |

Optional gate (default `0.40` — lower than research 0.65 because small models are flat-heavy):

```bash
ML_GATE_THRESHOLD=0.35 docker compose up -d ml_inference app
```

---

## What you should see

### 1. Inference healthy
```bash
curl -s http://localhost:8001/health | jq .
```
Expect `"ok": true`. If model missing → train M2 first.

### 2. Raw model output
```bash
curl -s 'http://localhost:8001/predict?symbol=BTCUSDT' | jq .
```
Fields:
- `trade` — passed directional confidence gate  
- `side` — `BUY` / `SELL` / `FLAT`  
- `confidence` — `max(p_up, p_down)` on primary horizon (15m)  
- `horizons` — per 1m / 15m / 60m detail  

### 3. App-facing signals
```bash
curl -s http://localhost:4000/api/signals | jq .
```

### 4. Dashboard
Open http://localhost:4000  
- **ML: online**  
- **M2 Signals** cards (SKIP vs TRADE)  
- Candles still updating  

### 5. Logs (paper intents)
```bash
docker compose logs -f app | grep SIM_SIGNAL
```
Example:
```text
[SIM_SIGNAL] BUY BTCUSDT conf=0.412 price=65000.0 h=15m gate=0.4
```

---

## How to interpret results (small data / CPU)

### Healthy pipeline (pass)
- `ml_inference` ok, app ML online  
- `/api/signals` returns 3 symbols without hard errors  
- Most of the time **SKIP / FLAT** (expected with weak model + gate)  
- Occasional **TRADE** when conf ≥ gate  
- No crash loops  

### Model quality (do **not** over-read)
| Observation | Meaning |
|-------------|---------|
| Almost always SKIP | Gate strict or model uncertain — **OK** for “few high-confidence” |
| Always BUY or always SELL | Collapse / bias — retrain, check labels, more data |
| High conf + random sides | Overfit or leak risk — use offline `eval_m2` gate sweep |
| conf never above ~0.4 | Softmax mass on flat — lower gate only for plumbing tests |

### Offline numbers still matter more for accuracy
```bash
docker compose --profile ml run --rm ml_trainer \
  python eval_m2.py --checkpoint /models/m2_multi.pt --gate 0.35,0.4,0.5,0.6
```
Look at:
- **coverage** — how often we would trade  
- **gated_acc / dir_acc** — when we trade, hit rate  
- Compare after you retrain with more data or GPU  

Live sim and offline eval can disagree slightly (online z-score vs train z-score, newest bars only).

---

## Suggested simulation session (30–60 min)

1. `docker compose up -d postgres ml_inference app`  
2. Confirm health + dashboard ML online  
3. Leave running; every few minutes:
   - `curl -s localhost:4000/api/signals | jq .`
   - skim `SIM_SIGNAL` logs  
4. Count roughly: signals fired vs skips  
5. Run `eval_m2.py` and note gate table  
6. Write down: gate threshold used, fire rate, anything weird  

After a **better train** (more history / GPU / more epochs), repeat 1–6 and compare fire rate + offline gated_acc.

---

## Retrain then re-sim

```bash
docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 15

docker compose restart ml_inference   # reload weights
# watch dashboard / logs again
```

No need to rebuild app image if only the model file changed.

---

## Tuning knobs

| Env | Default | Effect |
|-----|---------|--------|
| `ML_GATE_THRESHOLD` | `0.40` | Higher → fewer TRADE signals |
| `PRIMARY_HORIZON` | `15` | Horizon used for trade decision |
| `TRADING_MODE` | `simulation` | Keep simulation for paper |

---

## What not to conclude yet

- “Ready for auto trading”  
- “X% live accuracy” from a short UI session  
- That sim positions = realistic PnL (sizing/fees/funding not fully modeled)  

Next steps later: richer paper ledger, walk-forward backtest, then M3 policy.

---

*Phase I light — 2026-07-19*
