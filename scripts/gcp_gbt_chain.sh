#!/usr/bin/env bash
# Drive a SERIAL chain of gcp_gbt.sh runs: wait for the run in flight (if any) to finish,
# fetch its log to logs/<name>.log, launch the next, repeat. One GBT VM at a time — the
# launcher's status marker (status/gbt_latest.json) is the only state read.
#
#   ./scripts/gcp_gbt_chain.sh <queue-file> [first-run-name]
#
# queue-file: one run per line — `<log-name> <FEATURE_GROUPS> <seed> [extra env K=V …]`,
# e.g. `X17_legacy_s2 legacy 2`. Lines starting with # are skipped. The launcher env
# (CANDLE_INTERVAL, GBT_*, ARCHIVE_*, …) is the caller's — export it before running.
# `first-run-name` names the run ALREADY in flight when the chain starts, whose log is
# fetched under that name before the first queued launch.
#
# Written 2026-10-22 for NEXT_TRAINING_PLAN §2 X17 (six runs, two arms × three seeds).
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source scripts/gcp_common.sh
QUEUE="${1:?queue file}"; INFLIGHT="${2:-}"
POLL="${GBT_CHAIN_POLL_S:-300}"

marker() { gcloud storage cat "$GCS_BUCKET/status/gbt_latest.json" 2>/dev/null || echo ""; }
field() { printf '%s' "$1" | sed -n "s/.*\"$2\":\"\([^\"]*\)\".*/\1/p"; }

wait_done() {   # $1 = run id to wait for; prints DONE|FAILED
  while true; do
    local m; m="$(marker)"
    local run; run="$(field "$m" run)"; local st; st="$(field "$m" status)"
    if [[ "$run" == "$1" && ( "$st" == "DONE" || "$st" == "FAILED" ) ]]; then echo "$st"; return 0; fi
    echo "    $(date -u +%H:%M:%S) waiting on $1 (status=${st:-?} run=${run:-?})" >&2
    sleep "$POLL"
  done
}

fetch_log() {   # $1 = run id, $2 = log name
  ./scripts/gcp_gbt.sh --log "$1" > "logs/$2.log"
  echo "==> fetched $1 -> logs/$2.log ($(wc -l < "logs/$2.log") lines)"
}

if [[ -n "$INFLIGHT" ]]; then
  run="$(field "$(marker)" run)"
  echo "==> waiting for the run in flight: $run (log name $INFLIGHT)"
  st="$(wait_done "$run")"; fetch_log "$run" "$INFLIGHT"
  [[ "$st" == "DONE" ]] || { echo "ERROR: $run $st — chain stopped"; exit 1; }
fi

while read -r name groups seed extra; do
  [[ -z "$name" || "$name" == \#* ]] && continue
  echo ""; echo "==> launching $name (FEATURE_GROUPS=$groups --seed $seed ${extra:-})"
  prev="$(field "$(marker)" run)"
  # the previous VM deletes itself after DONE; a launch that finds it STOPPING tries to start
  # it and fails (seen 2026-10-22). Wait until it is gone.
  for i in $(seq 1 60); do
    st_vm="$(gcloud compute instances describe "${GCP_GBT_INSTANCE:-fluxtrader-gbt}" \
      --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='get(status)' 2>/dev/null || true)"
    [[ -z "$st_vm" ]] && break
    echo "    previous VM still $st_vm — waiting" >&2; sleep 10
  done
  # stdin from /dev/null: the launcher's ssh calls would otherwise swallow the rest of the
  # queue (found 2026-10-22 — the first chain stopped after two of six runs, exit 0).
  if ! env ${extra:-} FEATURE_GROUPS="$groups" ./scripts/gcp_gbt.sh --seed "$seed" > "logs/${name}.launch.log" 2>&1 < /dev/null; then
    echo "ERROR: launcher failed for $name — see logs/${name}.launch.log"; exit 1
  fi
  # the new marker appears once the remote job starts (a minute or two after launch)
  for i in $(seq 1 60); do
    run="$(field "$(marker)" run)"
    [[ -n "$run" && "$run" != "$prev" ]] && break
    sleep 10
  done
  [[ -n "$run" && "$run" != "$prev" ]] || { echo "ERROR: no new run marker after launching $name"; exit 1; }
  echo "    run=$run"
  st="$(wait_done "$run")"; fetch_log "$run" "$name"
  [[ "$st" == "DONE" ]] || { echo "ERROR: $run $st — chain stopped after $name"; exit 1; }
done < "$QUEUE"
echo ""; echo "==> chain complete"
