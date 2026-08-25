#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "Virtual environment not found. Run ./scripts/bootstrap.sh first." >&2
  exit 1
fi

cd "$ROOT"
"$PYTHON" -m pip install -e '.[dev]'
"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --onedir \
  --name FlipFillCAD \
  --paths src \
  --collect-all cadquery \
  --collect-all OCP \
  --collect-all vtkmodules \
  --collect-all trimesh \
  --collect-all PIL \
  src/flipfill/ui/launcher.py

echo "Linux application created under dist/FlipFillCAD."
