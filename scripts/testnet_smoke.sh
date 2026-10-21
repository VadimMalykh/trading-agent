#!/usr/bin/env bash
# Run `mix flux.testnet_smoke` with the TESTNET keys kept in .env.testnet (owner-only, git-ignored;
# on fluxtrader-1 since 2026-10-21). The app's own .env holds the PRODUCTION key and is not touched.
#
#   ./scripts/testnet_smoke.sh                       # the taker path (REAL_MONEY_TRACK §6)
#   ./scripts/testnet_smoke.sh --maker --wait-seconds 60 --hold-seconds 30   # M2's maker path (§6.4)
#
# Uses `docker compose exec` when the app container is running (compile first: a task that compiles
# on the way in runs the old beam), else `docker compose run --rm --no-deps`.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env.testnet ]] || { echo "no .env.testnet here (BINANCE_TESTNET_API_KEY / _SECRET)" >&2; exit 2; }
KEY=$(grep -E '^BINANCE_TESTNET_API_KEY=' .env.testnet | cut -d= -f2-)
SECRET=$(grep -E '^BINANCE_TESTNET_API_SECRET=' .env.testnet | cut -d= -f2-)
[[ -n "$KEY" && -n "$SECRET" ]] || { echo ".env.testnet is missing a key" >&2; exit 2; }
if docker compose ps --status running app 2>/dev/null | grep -q app; then
  docker compose exec app mix compile >/dev/null
  exec docker compose exec -e BINANCE_TESTNET=true -e BINANCE_API_KEY="$KEY" -e BINANCE_API_SECRET="$SECRET" \
    app mix flux.testnet_smoke "$@"
else
  exec docker compose run --rm --no-deps -e BINANCE_TESTNET=true -e BINANCE_API_KEY="$KEY" -e BINANCE_API_SECRET="$SECRET" \
    app mix flux.testnet_smoke "$@"
fi
