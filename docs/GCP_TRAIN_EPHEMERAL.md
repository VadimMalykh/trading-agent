# GCP: always-on collector + ephemeral CPU training

## Architecture

```text
┌─────────────────────────────┐     dump DB      ┌──────────────────────────────┐
│  Always-on (small)          │ ───────────────► │  Train VM (medium/standard)  │
│  fluxtrader-1               │                  │  fluxtrader-train (temp)     │
│  postgres + app             │ ◄─────────────── │  restore → train_m2 → eval   │
│  (+ ml_inference optional)  │   m2_multi.pt    │  then DELETE                 │
└─────────────────────────────┘                  └──────────────────────────────┘
```

| Role | Instance (default) | Size | 24/7? |
|------|-------------------|------|-------|
| Collect + UI + inference | `fluxtrader-1` | e2-small (2 GB) OK | **Yes** |
| Train only | `fluxtrader-train` | e2-standard-2 (8 GB) or e2-medium | **No** — create → train → delete |

Training does **not** need GPU yet. Same pattern later with a Spot GPU VM.

---

## One-time setup on your Mac

```bash
# gcloud installed + logged in
gcloud auth login
gcloud config set project fluxtrader

cd /path/to/trading_agent
cp scripts/gcp_env.example scripts/gcp_env
# edit scripts/gcp_env if names/zone differ
chmod +x scripts/gcp_*.sh scripts/gcp_common.sh
```

Defaults in `scripts/gcp_env.example`:

- `GCP_PROJECT=fluxtrader`
- `GCP_ZONE=me-central1-b`
- `GCP_ALWAYS_ON=fluxtrader-1`
- `GCP_TRAIN_INSTANCE=fluxtrader-train`
- `GCP_TRAIN_MACHINE=e2-standard-2`

---

## Full pipeline (recommended)

From your **Mac** (not on the small VM):

```bash
cd /path/to/trading_agent
source scripts/gcp_env   # if you created it

# dump always-on → create train VM → train → promote ckpt → delete train VM
./scripts/gcp_train_pipeline.sh --epochs 40 --seq-len 64

# keep train VM for debugging:
./scripts/gcp_train_pipeline.sh --epochs 40 --seq-len 64 --keep-vm

# majors only (less RAM):
TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT ./scripts/gcp_train_pipeline.sh --epochs 40
```

This will:

1. `pg_dump` from always-on → `~/fluxtrader-train-export/fluxtrader.dump`
2. Create/start `fluxtrader-train` with Docker
3. Restore dump, run `train_m2.py` + `eval_m2.py`
4. Download `m2_multi.pt` locally
5. Install it on always-on model volume + restart `ml_inference` if running
6. Delete train VM (unless `--keep-vm`)

**Duration:** dump/transfer minutes; train can be **many hours** on CPU — leave Mac awake or run pipeline inside `tmux` on a machine that stays online (the train itself runs on GCP; Mac only needs to stay connected for the SSH session driving `gcp_run_train.sh`).

Tip: for long trains, either:

- run `./scripts/gcp_run_train.sh` from Mac in `tmux`, or  
- SSH to train VM and run train in `tmux` there after setup.

---

## Step-by-step (manual / debug)

```bash
source scripts/gcp_env

./scripts/gcp_dump_always_on.sh
./scripts/gcp_create_train_vm.sh
./scripts/gcp_run_train.sh 40 64
./scripts/gcp_promote_checkpoint.sh
./scripts/gcp_delete_train_vm.sh
```

### On always-on after promote

```bash
gcloud compute ssh fluxtrader-1 --zone=me-central1-b --project=fluxtrader
cd ~/trading_agent
curl -s http://127.0.0.1:8001/health
curl -s http://127.0.0.1:4000/api/signals | head -c 500
```

---

## Scripts reference

| Script | What it does |
|--------|----------------|
| `gcp_env.example` | Config template → copy to `gcp_env` |
| `gcp_common.sh` | Shared vars / SSH helpers |
| `gcp_dump_always_on.sh` | Dump Postgres from always-on to Mac |
| `gcp_create_train_vm.sh` | Create/start train VM + Docker |
| `gcp_run_train.sh` | Upload dump, restore, train, eval, fetch ckpt |
| `gcp_promote_checkpoint.sh` | Install `m2_multi.pt` on always-on |
| `gcp_delete_train_vm.sh` | Delete train VM |
| `gcp_train_pipeline.sh` | All of the above |

Also still useful:

- `export_local.sh` / `upload_to_gcp.sh` / `import_on_server.sh` — Mac↔always-on bulk migrate  
- `docs/TRAINING.md` — epochs, backfill, eval interpretation  
- `docs/GCP_MIGRATE.md` — first-time data move  

---

## What stays on the small always-on box

```bash
docker compose up -d postgres app
# optional live signals:
docker compose up -d ml_inference
```

Do **not** run heavy `train_m2` with 180d history on 2 GB RAM.

Optional historic klines (lighter than full train) can still run on always-on:

```bash
docker compose --profile ml run --rm ml_trainer \
  python backfill_history.py --days 180 --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --intervals 1m,15m,1h
```

If backfill OOMs, run it on the train VM once (after restore) before `train_m2`, or backfill in chunks (`--days 30` repeatedly).

---

## Cost notes

| Resource | When you pay |
|----------|----------------|
| Always-on e2-small | Every hour it exists |
| Train e2-standard-2 | Only while VM exists — **delete after train** |
| Disk snapshots / dumps on Mac | Negligible at current size |

Leaving `fluxtrader-train` running overnight after training wastes money — use `gcp_delete_train_vm.sh`.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Train OOM | `e2-standard-2` or `TRAIN_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT` / `--seq-len 32` |
| Docker not ready on new VM | Wait 2–3 min; re-run `gcp_create_train_vm.sh` |
| Dump huge / slow | Normal after 180d backfill; be patient |
| Promote but UI old model | `docker compose restart ml_inference` on always-on |
| Volume name warning | Harmless if data is correct; scripts grep `model_weights` |
| SSH from Mac drops mid-train | Use `tmux` on Mac around `gcp_run_train.sh`, or train in tmux on train VM |

---

## Recommended first serious train

1. Always-on collecting (book growing).  
2. Optional: backfill 90–180d klines on always-on or train VM.  
3. From Mac:
   ```bash
   ./scripts/gcp_train_pipeline.sh --epochs 40 --seq-len 64
   ```
4. Read eval output (15m gate table).  
5. Confirm live signals pick up new weights after promote.

---

*Last updated: 2026-07-21*
