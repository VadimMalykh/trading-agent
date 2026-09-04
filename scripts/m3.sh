#!/usr/bin/env bash
# Run an M3 offline-analysis command inside Docker.
#
# WHY: every part of this project — local development, analysis and tests included — runs
# in a container; nothing is installed on the host. M3 is offline work over the
# eval_preds.parquet dumps (docs/M3_PLAN.md §0.3), so it uses the small torch-free
# `ml_analysis` image rather than the 5.6GB trainer one.
#
# The repo's ml/train is bind-mounted at /workspace/train, so edits on the host take
# effect immediately with no rebuild, and anything written to
# ml/train/output/ lands back in the working copy.
#
# Usage:
#   ./scripts/m3.sh reaggregate_preds.py <parquet> --validate
#   ./scripts/m3.sh policy_backtest.py --help
#   ./scripts/m3.sh --shell                 # interactive poke-around
#
# Paths passed to the script are container paths. The dumps live at
#   /workspace/train/output/eval_dumps/eval_preds_<run_id>.parquet
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="trading_agent-ml_analysis:latest"

# Build on first use, and whenever the image is missing. Rebuilding is ~10s and only
# needed when requirements.analysis.txt changes.
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "→ building $IMAGE (first run)…" >&2
  docker build -q -f "$REPO_ROOT/ml/train/Dockerfile.analysis" -t "$IMAGE" "$REPO_ROOT/ml/train" >/dev/null
fi

# M3_EXPORT_DIR lets `bookprep` point at an alternative export directory (a smoke-test
# slice, say) without editing the module. Only forwarded when set, so the container keeps
# its own default otherwise.
# M3_ERA selects which scoring of the three banked checkpoints to read — `prerepair` (the
# default, and what every published M3 number was measured on) or `repaired`. See
# m3/dumps.py:RUNS_BY_ERA.
ENV_ARGS=()
[[ -n "${M3_EXPORT_DIR:-}" ]] && ENV_ARGS+=(-e "M3_EXPORT_DIR=$M3_EXPORT_DIR")
[[ -n "${M3_ERA:-}" ]] && ENV_ARGS+=(-e "M3_ERA=$M3_ERA")

DOCKER_ARGS=(--rm "${ENV_ARGS[@]+"${ENV_ARGS[@]}"}" -v "$REPO_ROOT/ml/train:/workspace/train" -w /workspace/train "$IMAGE")

if [[ "${1:-}" == "--shell" ]]; then
  exec docker run -it "${DOCKER_ARGS[@]}" /bin/bash
fi

exec docker run "${DOCKER_ARGS[@]}" python "$@"
