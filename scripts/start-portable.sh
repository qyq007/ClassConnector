#!/usr/bin/env bash
# ClassConnector PORTABLE launcher (Linux / macOS)
# No autostart, no systemd, no user-profile or system site-packages writes.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export CLASSCONNECTOR_HOME="$ROOT/data"
export CLASSCONNECTOR_CONFIG="$ROOT/data/config.json"
mkdir -p "$ROOT/data"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if command -v python3 >/dev/null 2>&1; then PY="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then PY="$(command -v python)"
  else echo "[ERROR] Python 3.8+ not found"; exit 1; fi
fi

if ! "$PY" -c "import fastapi, uvicorn, multipart, PIL" >/dev/null 2>&1; then
  echo "First run: creating ./runtime/venv (stays inside this folder) ..."
  mkdir -p "$ROOT/runtime"
  if [ ! -x "$ROOT/runtime/venv/bin/python" ]; then "$PY" -m venv "$ROOT/runtime/venv"; fi
  "$ROOT/runtime/venv/bin/python" -m pip install --disable-pip-version-check -q -r "$ROOT/requirements-portable.txt"
  PY="$ROOT/runtime/venv/bin/python"
fi

echo "Data folder: $CLASSCONNECTOR_HOME"
"$PY" -m agent.portable "$@"
