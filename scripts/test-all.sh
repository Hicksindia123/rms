#!/usr/bin/env bash
# Unified test script for RMS (Prompt P4-06)
# Runs in order:
# 1. db reset
# 2. pgTAP (supabase test db)
# 3. backend tests (ruff, mypy, pytest)
# 4. frontend unit (lint, format, typecheck, vitest, build)
# 5. API type generation diff check (fails if types stale)
# 6. E2E (playwright)
# 7. integrity_check.sql
# And outputs a structured summary table.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

SKIP_DB_RESET=false
SKIP_E2E=false

for arg in "$@"; do
  case "$arg" in
    --skip-db-reset) SKIP_DB_RESET=true ;;
    --skip-e2e) SKIP_E2E=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

passed=()
failed=()
skipped=()

step() {
  local name="$1" dir="$2"
  shift 2
  echo
  echo "=== $name"
  if (cd "$dir" && "$@"); then
    passed+=("$name")
  else
    failed+=("$name")
  fi
}

skip() {
  local name="$1" reason="$2"
  skipped+=("$name ($reason)")
}

# 0. Secrets scan
step "secrets scan" "$ROOT" bash scripts/check-secrets.sh

# 1. DB Reset
if ! $SKIP_DB_RESET; then
  if command -v supabase >/dev/null 2>&1; then
    step "supabase db reset" "$ROOT" supabase db reset
  else
    failed+=("supabase db reset (supabase CLI not on PATH)")
  fi
else
  skip "supabase db reset" "flag --skip-db-reset passed"
fi

# 2. pgTAP Tests
if compgen -G "$ROOT/supabase/tests/*.sql" >/dev/null; then
  if command -v supabase >/dev/null 2>&1; then
    step "supabase test db (pgTAP)" "$ROOT" supabase test db
  else
    failed+=("supabase test db (supabase CLI not on PATH)")
  fi
else
  skip "supabase test db" "no sql tests found"
fi

# 3. Backend Tests
step "backend ruff check"   "$BACKEND" uv run ruff check .
step "backend ruff format"  "$BACKEND" uv run ruff format --check .
step "backend mypy"         "$BACKEND" uv run mypy app
step "backend pytest"       "$BACKEND" uv run pytest -q

# 4. Frontend Unit
step "frontend lint"        "$FRONTEND" pnpm lint
step "frontend format"      "$FRONTEND" pnpm format:check
step "frontend typecheck"   "$FRONTEND" pnpm typecheck
step "frontend unit tests"  "$FRONTEND" pnpm test
step "frontend build"       "$FRONTEND" pnpm build

# 5. API Type Generation Diff Check (fails if types stale)
step "api type freshness check" "$FRONTEND" bash -c "pnpm gen:api && git diff --exit-code src/lib/api/schema.d.ts"

# 6. E2E (Playwright)
if ! $SKIP_E2E; then
  step "frontend e2e (playwright)" "$FRONTEND" pnpm e2e
else
  skip "frontend e2e" "flag --skip-e2e passed"
fi

# 7. Database Integrity Check (integrity_check.sql)
step "database integrity check" "$ROOT" bash -c "
  if docker ps -q -f 'name=supabase_db' >/dev/null 2>&1; then
    docker exec -i \$(docker ps -q -f 'name=supabase_db' | head -n1) psql -U postgres -v ON_ERROR_STOP=1 < '$ROOT/scripts/integrity_check.sql'
  elif command -v psql >/dev/null 2>&1; then
    psql 'postgresql://postgres:postgres@127.0.0.1:54322/postgres' -v ON_ERROR_STOP=1 -f '$ROOT/scripts/integrity_check.sql'
  else
    echo 'Neither docker nor psql found' >&2
    exit 1
  fi
"

echo
echo "==================================================="
echo "                TEST SUITE SUMMARY                 "
echo "==================================================="
for s in "${passed[@]}";  do echo "  [PASS]  $s"; done
for s in "${skipped[@]}"; do echo "  [SKIP]  $s"; done
for s in "${failed[@]}";  do echo "  [FAIL]  $s"; done
echo "==================================================="

if [[ ${#failed[@]} -gt 0 ]]; then
  echo "One or more test steps failed."
  exit 1
fi

echo "All tests passed successfully!"
exit 0
