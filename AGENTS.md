# Agent notes

## Docker only — no host installs

This project runs **entirely in Docker**. Do **not** install or use host tooling:

- No local Elixir / Erlang / Mix
- No local Postgres / psql client installs
- No local Python venv for app/ML services
- Do not `brew install`, `apt install`, or otherwise provision the host for this repo

### How to run commands

| Task | Command |
|------|---------|
| Ensure model volume | `docker volume create trading_agent_model_weights` (once; external in compose) |
| Start stack | `docker compose up -d postgres ml_inference app` |
| App shell / Mix | `docker compose exec app mix …` |
| App logs | `docker compose logs -f app` |
| DB (psql) — LOCAL DEV ONLY, not real data | `docker compose exec postgres psql -U fluxtrader -d fluxtrader` |
| DB (psql) — REAL data (always-on VM) | `./scripts/gcp_data_collection_stats.sh` or SSH (see "Data lives on the always-on VM") |
| ML train/backfill | `docker compose --profile ml run --rm ml_trainer python …` |
| M3 offline policy analysis | `./scripts/m3.sh -m m3 validate` (torch-free `ml_analysis` image; see `docs/M3_PLAN.md` §0.0) |
| Elixir tests | `docker compose run --rm -e MIX_ENV=test -e POSTGRES_HOST=postgres app mix test` (workers do not start under `MIX_ENV=test`, so a run never touches Binance) |
| Live policy state | `curl -s localhost:4001/api/health \| jq` — signal liveness, the live coverage cut, named skip reasons, both A/B arms (`docs/M3_5_INTEGRATION.md` §2) |
| Inference | `curl http://localhost:8001/…` (or exec into `ml_inference`) |
| Restart after Elixir code change | `docker compose restart app` (code is bind-mounted; `_build` is a volume) |

### Layout reminder

- Elixir/Phoenix: `apps/`, started as service `app` (bind-mount `.:/app`)
- ML: `ml/train/`, services `ml_inference` + profile `ml` → `ml_trainer`, `ml_analysis`
- M3 policy backtester (offline): `ml/train/m3/`, run through `scripts/m3.sh`
- M3 policy, live: `apps/fluxtrader/lib/fluxtrader/trading/` — `policy.ex` is the rule and the
  only place it exists; see `docs/M3_5_INTEGRATION.md`
- DB: service `postgres` user/db `fluxtrader` / password `secret`

If a tool is missing on the host, use the matching container — never install it locally.

## Data lives on the always-on VM — NOT the local DB (permanent)

**All real data (candles, order book, trades, funding/OI, and every backfilled pair)
lives on the always-on GCP collector VM `fluxtrader-1`. The local `docker compose exec
postgres` is a throwaway DEV DB — it does NOT mirror the VM.** This is permanent: data
collection stays on the VM across all project phases. Never reason about what data /
which pairs / how much history exists by querying the local DB.

- **Check VM data:** `./scripts/gcp_data_collection_stats.sh` (SSHes to the VM, runs psql
  there, reports rows/first/last/staleness per table+symbol). This is the ONLY correct way.
- **Ad-hoc VM query:**
  ```sh
  gcloud compute ssh --zone me-central1-b fluxtrader-1 --project fluxtrader -- \
    'cd ~/trading_agent && docker compose exec -T postgres psql -U fluxtrader -d fluxtrader -c "SELECT …"'
  ```
- Training / eval / backfill all run against the VM's DB, not local.
- Lesson (2026-08-16): checking the local DB showed only partial history and led to a
  wrong "these pairs are short/ragged" conclusion. The pairs were fully backfilled on the
  VM. Don't repeat it — always check the VM.

## Token efficiency

Keep token spend low. Apply these by default:

- **Be terse.** Do the work, then give a one-line summary. No preamble ("I'll now…"), no postamble ("Let me know if…"). Expand only when explicitly asked "why" or "explain".
- **Keep important details.** Terse ≠ omitting what's needed to understand a change. State non-obvious decisions, gotchas, and side effects in one line each.
- **Read as much as you need.** This project involves analyzing large logs, docs, and other artifacts — read whole files and long excerpts freely when the task calls for it. Prefer targeted `grep` when hunting for something specific, but don't artificially truncate reads. Just avoid re-reading a file you've already read.
- **Explore via subagents.** Use the Task tool for codebase searches so bulky tool output stays out of the main context.
- **Prefer cheaper models for routine work** (edits, searches, boilerplate); reserve the largest model for hard reasoning.
- **Fresh session per task.** Long sessions resend full history each turn — start a new session when switching tasks.
- **Keep this file and configs lean.** They're sent on every request.
