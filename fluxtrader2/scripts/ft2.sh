#!/usr/bin/env bash
# Run a fluxtrader2 command inside Docker. The repo rule is that nothing runs on the host.
#
#   ./fluxtrader2/scripts/ft2.sh smoke            # python -m ft2 smoke
#   ./fluxtrader2/scripts/ft2.sh <subcommand> …   # any `python -m ft2 …` subcommand
#   ./fluxtrader2/scripts/ft2.sh --shell          # interactive shell
#   FT2_REBUILD=1 ./fluxtrader2/scripts/ft2.sh smoke   # force an image rebuild
#
# fluxtrader2/ is bind-mounted at /workspace/ft2, so code edits need no rebuild and
# anything written under output/ or data/ lands in the working copy.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$ROOT/fluxtrader2"
IMAGE="fluxtrader2-analysis:latest"

if [[ "${FT2_REBUILD:-0}" == "1" ]] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "→ building ${IMAGE}..." >&2
  docker build -q -f "$DIR/Dockerfile" -t "$IMAGE" "$DIR" >/dev/null
fi

ARGS=(--rm -v "$DIR:/workspace/ft2" -w /workspace/ft2 "$IMAGE")
if [[ "${1:-}" == "--shell" ]]; then
  exec docker run -it "${ARGS[@]}" /bin/bash
fi
exec docker run "${ARGS[@]}" python -m ft2 "$@"
