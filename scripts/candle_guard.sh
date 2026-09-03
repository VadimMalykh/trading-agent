#!/usr/bin/env bash
# Daily candle integrity guard. Runs ON fluxtrader-1, fired by the systemd timer that
# scripts/install_candle_guard.sh installs. Compares yesterday's stored candles against
# Binance's own closed klines and shouts on Telegram if they disagree.
#
# This is the check whose absence let the candle-poll defect run for six weeks
# (docs/CANDLE_POLL_DEFECT.md). The checks that existed all compared one derived number
# to another derived number -- live confidence against the offline split's confidence,
# for instance -- and both sides were computed from the same corrupt candles, so they
# agreed perfectly while being uniformly wrong. Only a comparison against something
# OUTSIDE the system can catch a bad input, which is what this is.
#
# Run it by hand exactly as the timer does:
#   ~/trading_agent/scripts/candle_guard.sh
#
# Quiet on success by design -- a guard that messages every day is a guard people mute.
# It writes a status file either way, so "did it run?" is answerable without Telegram.

set -uo pipefail

REPO="${CANDLE_GUARD_REPO:-$HOME/trading_agent}"
INTERVALS="${CANDLE_GUARD_INTERVALS:-5m,1m}"
# Empty means "every symbol in `candles`", which is what a guard should watch. Set it
# only to narrow the check when testing.
SYMBOLS="${CANDLE_GUARD_SYMBOLS:-}"
LOG="${CANDLE_GUARD_LOG:-$HOME/candle_guard.log}"
STATUS="${CANDLE_GUARD_STATUS:-/var/tmp/candle_guard_status.json}"

cd "$REPO" || { echo "candle_guard: no repo at $REPO" >&2; exit 2; }

# Telegram credentials live in the same .env the app reads, so the guard alerts through
# the channel that already exists rather than inventing a second one.
if [[ -f "$REPO/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO/.env"
  set +a
fi

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Positional params rather than an array: "$@" with nothing set is safe under `set -u`
# on every bash, while "${arr[@]}" on an empty array aborts on bash 3.2. The empty case
# is the production default here, so it must be the one that cannot break.
set --
[[ -n "$SYMBOLS" ]] && set -- --symbols "$SYMBOLS"
out="$(docker compose --profile ml run --rm -T ml_trainer \
        python verify_candles.py --since-yesterday --intervals "$INTERVALS" "$@" 2>&1)"
rc=$?
finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

{
  echo "=== candle guard $started -> $finished (exit $rc) ==="
  echo "$out"
} >> "$LOG"

# Keep the log from growing without bound; a year of daily runs is plenty of history.
if [[ -f "$LOG" ]] && [[ "$(wc -l < "$LOG")" -gt 20000 ]]; then
  tail -n 10000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

summary="$(echo "$out" | grep -E '^[0-9]+/[0-9]+ checks passed' | tail -1)"
failed="$(echo "$out" | grep -cE ': FAIL|: ERROR')"

# `ok` is exit-code 0 AND a summary line we could actually parse. A run that died before
# printing its summary is not a pass, and must not be recorded as one.
ok=false
if [[ $rc -eq 0 && -n "$summary" ]]; then ok=true; fi

cat > "$STATUS" <<JSON
{
  "started_utc": "$started",
  "finished_utc": "$finished",
  "exit_code": $rc,
  "ok": $ok,
  "failed_checks": ${failed:-0},
  "summary": "${summary:-no summary line -- the check did not finish}",
  "intervals": "$INTERVALS",
  "log": "$LOG"
}
JSON

if [[ "$ok" == true ]]; then
  echo "candle guard OK: $summary"
  exit 0
fi

echo "candle guard FAILED (exit $rc): ${summary:-no summary}" >&2

if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  # Only the failing lines, capped: Telegram rejects messages over ~4096 chars, and the
  # detail that matters is which pair/interval/day disagreed and by how much.
  detail="$(echo "$out" | grep -E ': FAIL|: ERROR' | head -20)"
  text="$(printf '%s\n\n%s\n\n%s\n\n%s' \
    "🔴 CANDLE GUARD FAILED on $(hostname)" \
    "${summary:-the check did not finish (exit $rc)}" \
    "${detail:-no per-check detail; see $LOG}" \
    "Stored candles disagree with Binance. This is the candle-poll defect's signature (docs/CANDLE_POLL_DEFECT.md). The model is reading bad input until it is fixed.")"
  curl -sS --max-time 30 -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${text}" \
    -o /dev/null || echo "candle guard: Telegram send failed" >&2
else
  echo "candle guard: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset — no alert sent" >&2
fi

exit 1
