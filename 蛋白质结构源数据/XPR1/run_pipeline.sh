#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$TASK_DIR/.venv/bin/python" ]]; then
  exec "$TASK_DIR/.venv/bin/python" "$TASK_DIR/run_pipeline.py" "$@"
else
  exec python "$TASK_DIR/run_pipeline.py" "$@"
fi
