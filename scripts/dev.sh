#!/usr/bin/env bash
# Start the RMS dev stack: backend API (:8000), worker (only if app/worker exists), frontend (:5173).
# Local Supabase is started separately with `supabase start` (see docs/SETUP.md).
# Ctrl+C stops everything this script started.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v pnpm >/dev/null 2>&1; then
  echo "dev.sh: 'pnpm' is not on PATH (run 'npm install -g pnpm' or see docs/SETUP.md)" >&2
  exit 1
fi

USE_UV=0
if command -v uv >/dev/null 2>&1; then
  USE_UV=1
elif [[ ! -f "$ROOT/backend/.venv/bin/python" && ! -f "$ROOT/backend/.venv/Scripts/python.exe" ]]; then
  echo "dev.sh: Neither 'uv' nor 'backend/.venv' Python environment found." >&2
  exit 1
fi

pids=()
cleanup() {
  trap - EXIT INT TERM
  echo
  echo "dev.sh: stopping..."
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "dev.sh: backend  -> http://localhost:8000/api/v1/health"
if [[ $USE_UV -eq 1 ]]; then
  (cd "$ROOT/backend" && exec uv run uvicorn app.main:app --reload --port 8000) &
else
  VENV_PY="$ROOT/backend/.venv/bin/python"
  [[ -f "$ROOT/backend/.venv/Scripts/python.exe" ]] && VENV_PY="$ROOT/backend/.venv/Scripts/python.exe"
  (cd "$ROOT/backend" && exec "$VENV_PY" -m uvicorn app.main:app --reload --port 8000) &
fi
pids+=($!)

if [[ -f "$ROOT/backend/app/worker.py" || -f "$ROOT/backend/app/worker/__init__.py" ]]; then
  echo "dev.sh: worker   -> python -m app.worker"
  if [[ $USE_UV -eq 1 ]]; then
    (cd "$ROOT/backend" && exec uv run python -m app.worker) &
  else
    (cd "$ROOT/backend" && exec "$VENV_PY" -m app.worker) &
  fi
  pids+=($!)
else
  echo "dev.sh: worker   -> not present yet (backend/app/worker), skipped"
fi

echo "dev.sh: frontend -> http://localhost:5173"
(cd "$ROOT/frontend" && pnpm dev)
