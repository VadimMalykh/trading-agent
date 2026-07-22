# Migrate local data → GCP

## What you need to provide

| Variable | Example | Required |
|----------|---------|----------|
| `GCP_INSTANCE` | `fluxtrader-1` | yes |
| `GCP_ZONE` | `europe-west1-b` | yes |
| `GCP_PROJECT` | `my-project-id` | if not default in gcloud |

Also: **gcloud CLI** installed and logged in on the machine that uploads.

```bash
# macOS
brew install --cask google-cloud-sdk
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

VM must already exist with Docker + this repo (see deploy notes).

---

## 1. Export on Mac (local Docker running)

```bash
cd /path/to/trading_agent
chmod +x scripts/*.sh
./scripts/export_local.sh
# → ~/fluxtrader-export/
```

## 2. Upload

```bash
export GCP_INSTANCE=fluxtrader-1
export GCP_ZONE=europe-west1-b
export GCP_PROJECT=your-project-id   # optional if already set

./scripts/upload_to_gcp.sh
```

## 3. Import on the VM

```bash
gcloud compute ssh "$GCP_INSTANCE" --zone="$GCP_ZONE"
cd ~/trading_agent   # or wherever the repo is
git pull             # so scripts/import_on_server.sh exists

export EXPORT_DIR=~/fluxtrader-export
# if scp nested the folder:
# export EXPORT_DIR=~/fluxtrader-export/fluxtrader-export

chmod +x scripts/*.sh
./scripts/import_on_server.sh
```

## 4. Verify & cut over

- Compare counts (script prints local vs remote if `counts_local.txt` present).
- Confirm book `max(ts)` moves forward on GCP.
- **Stop local** `docker compose stop app` (or full stack) so only GCP collects book.

---

## If gcloud is not on Mac

1. Run `./scripts/export_local.sh` locally.
2. Upload `~/fluxtrader-export` any way you like (Console upload, `scp` with SSH key, etc.).
3. On VM run `./scripts/import_on_server.sh`.
