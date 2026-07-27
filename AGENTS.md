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

## Token efficiency

Keep token spend low. Apply these by default:

- **Be terse.** Do the work, then give a one-line summary. No preamble ("I'll now…"), no postamble ("Let me know if…"). Expand only when explicitly asked "why" or "explain".
- **Keep important details.** Terse ≠ omitting what's needed to understand a change. State non-obvious decisions, gotchas, and side effects in one line each.
- **Read files sparingly.** Prefer targeted `grep` and offset/limit reads over dumping whole files. Don't re-read a file you've already read.
- **Explore via subagents.** Use the Task tool for codebase searches so bulky tool output stays out of the main context.
- **Prefer cheaper models for routine work** (edits, searches, boilerplate); reserve the largest model for hard reasoning.
- **Fresh session per task.** Long sessions resend full history each turn — start a new session when switching tasks.
- **Keep this file and configs lean.** They're sent on every request.
