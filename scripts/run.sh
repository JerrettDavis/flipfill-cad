#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "Virtual environment not found. Run ./scripts/bootstrap.sh first." >&2
  exit 1
fi

cd "$ROOT"
if [[ $# -gt 0 ]]; then
  exec "$PYTHON" -m flipfill gui "$1"
else
  exec "$PYTHON" -m flipfill gui
fi
