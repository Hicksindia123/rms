#!/usr/bin/env bash
# Reset the RMS local database and prepare a clean UAT environment.
# Resets local Supabase DB (runs migrations and reference seeds),
# purges demo transactions, provisions workbook UAT users with
# pre-assigned roles, and optionally imports real products and parties CSVs.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"

PASSWORD="Uat@2026RMS!"
PRODUCTS_CSV=""
PARTIES_CSV=""
CLEAN_DEMO_MASTERS=0
SKIP_DB_RESET=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --password)
      PASSWORD="$2"
      shift 2
      ;;
    --products-csv)
      PRODUCTS_CSV="$2"
      shift 2
      ;;
    --parties-csv)
      PARTIES_CSV="$2"
      shift 2
      ;;
    --clean-demo-masters)
      CLEAN_DEMO_MASTERS=1
      shift
      ;;
    --skip-db-reset)
      SKIP_DB_RESET=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

echo "================================================================="
echo "RMS User Acceptance Testing (UAT) Environment Reset"
echo "================================================================="

if [[ ${SKIP_DB_RESET} -eq 0 ]]; then
  if command -v supabase >/dev/null 2>&1; then
    echo "Resetting Supabase database..."
    (cd "${ROOT_DIR}" && supabase db reset)
    if command -v docker >/dev/null 2>&1; then
      docker exec -i supabase_db_rms psql -U postgres -d postgres -c "alter role rms_api with password 'rms_api_local_pw';" >/dev/null 2>&1 || true
    fi
  else
    echo "WARNING: supabase CLI not found. Skipping db reset." >&2
  fi
fi

PY_ARGS=("scripts/uat_reset.py" "--password" "${PASSWORD}")

if [[ -n "${PRODUCTS_CSV}" ]]; then
  PY_ARGS+=("--products-csv" "${PRODUCTS_CSV}")
fi

if [[ -n "${PARTIES_CSV}" ]]; then
  PY_ARGS+=("--parties-csv" "${PARTIES_CSV}")
fi

if [[ ${CLEAN_DEMO_MASTERS} -eq 1 ]]; then
  PY_ARGS+=("--clean-demo-masters")
fi

echo "Provisioning UAT users and verifying zero-transaction state..."
(cd "${BACKEND_DIR}" && uv run python "${PY_ARGS[@]}")

echo "================================================================="
echo "UAT Reset Completed Successfully!"
echo "All workbook UAT accounts are active with password: ${PASSWORD}"
echo "Start the application with: ./scripts/dev.sh"
echo "================================================================="
