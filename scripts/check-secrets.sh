#!/usr/bin/env bash
# Fails if the Supabase service-role key (or any reference to it) appears under frontend/.
# Master plan §9.5: the service-role key must never reach the browser bundle.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND="$ROOT/frontend"

if [[ ! -d "$FRONTEND" ]]; then
  echo "check-secrets: frontend/ not found at $FRONTEND" >&2
  exit 2
fi

# Generated/third-party output is excluded; .env files ARE scanned.
set +e
matches="$(grep -rnI -E 'service_role|SERVICE_ROLE' "$FRONTEND" \
  --exclude-dir=node_modules --exclude-dir=dist --exclude-dir=coverage \
  --exclude-dir=playwright-report --exclude-dir=test-results)"
status=$?
set -e

if [[ $status -eq 0 ]]; then
  echo "check-secrets: FAIL — service-role reference found under frontend/:" >&2
  echo "$matches" >&2
  exit 1
elif [[ $status -eq 1 ]]; then
  echo "check-secrets: OK — no service-role references under frontend/"
  exit 0
else
  echo "check-secrets: grep failed (exit $status)" >&2
  exit "$status"
fi
