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
| DB (psql) | `docker compose exec postgres psql -U fluxtrader -d fluxtrader` |
| ML train/backfill | `docker compose --profile ml run --rm ml_trainer python …` |
| Inference | `curl http://localhost:8001/…` (or exec into `ml_inference`) |
| Restart after Elixir code change | `docker compose restart app` (code is bind-mounted; `_build` is a volume) |

### Layout reminder

- Elixir/Phoenix: `apps/`, started as service `app` (bind-mount `.:/app`)
- ML: `ml/train/`, services `ml_inference` + profile `ml` → `ml_trainer`
- DB: service `postgres` user/db `fluxtrader` / password `secret`

If a tool is missing on the host, use the matching container — never install it locally.
