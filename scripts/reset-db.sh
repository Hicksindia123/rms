#!/usr/bin/env bash
# One-command rebuild of the LOCAL RMS database with all reference and master data.
# Bash twin of scripts/reset-db.ps1 (see that file for the full description).
#
#   scripts/reset-db.sh [--password <pw>] [--skip-backup] [--keep-demo]
#
# 1. preflight (docker, supabase, backend Python, APP_ENV=local)   2. backup to backups/
# 3. supabase db reset: migrations + seed.sql + seed_stations.sql + seed_parties.sql + seed_products.sql
# 4. rms_api password from backend/.env   5. uat_reset.py: DEMO cleanup + 12 workbook users
# 6. verification against the seed files (non-zero exit on mismatch)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
DB_CONTAINER="supabase_db_rms" # supabase/config.toml project_id = "rms"
PASSWORD='Uat@2026RMS!'
SKIP_BACKUP=0
KEEP_DEMO=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --password) PASSWORD="$2"; shift 2 ;;
    --skip-backup) SKIP_BACKUP=1; shift ;;
    --keep-demo) KEEP_DEMO=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

step() { printf '\n==> %s\n' "$1"; }
fail() { echo "reset-db: $1" >&2; exit 1; }
psql_q() { docker exec -i "$DB_CONTAINER" psql -U postgres -d postgres -At -v ON_ERROR_STOP=1 -c "$1"; }

# --- 1. preflight -------------------------------------------------------------------------------
step "Preflight"
for cmd in docker supabase; do
  command -v "$cmd" >/dev/null 2>&1 || fail "'$cmd' is not on PATH (see docs/SETUP.md)"
done
ENV_FILE="$BACKEND/.env"
[[ -f "$ENV_FILE" ]] || fail "backend/.env not found (copy backend/.env.example, see docs/SETUP.md)"
grep -qE '^APP_ENV=local[[:space:]]*$' "$ENV_FILE" \
  || fail 'APP_ENV in backend/.env is not "local"; this script only resets the local database'
RMS_API_PASSWORD="$(sed -nE 's#^DATABASE_URL=[^\r]*://rms_api:([^@]+)@.*#\1#p' "$ENV_FILE" | tr -d '\r')"
[[ -n "$RMS_API_PASSWORD" ]] || fail "DATABASE_URL in backend/.env does not use the rms_api role"
RMS_API_PASSWORD="$(printf '%b' "${RMS_API_PASSWORD//%/\\x}")" # URL-decode

if command -v uv >/dev/null 2>&1; then
  PYTHON=(uv run python)
elif [[ -x "$BACKEND/.venv/bin/python" ]]; then
  PYTHON=("$BACKEND/.venv/bin/python")
elif [[ -x "$BACKEND/.venv/Scripts/python.exe" ]]; then
  PYTHON=("$BACKEND/.venv/Scripts/python.exe")
else
  fail "neither 'uv' nor backend/.venv was found"
fi

if [[ "$(docker ps --filter "name=^${DB_CONTAINER}\$" --format '{{.Names}}')" != "$DB_CONTAINER" ]]; then
  echo "Local Supabase is not running; starting it..."
  (cd "$ROOT" && supabase start)
fi

# --- 2. backup ----------------------------------------------------------------------------------
if [[ $SKIP_BACKUP -eq 0 ]]; then
  step "Backing up the current database"
  mkdir -p "$ROOT/backups"
  NAME="rms-$(date +%Y%m%d-%H%M%S).dump"
  MSYS_NO_PATHCONV=1 docker exec "$DB_CONTAINER" pg_dump -U postgres -d postgres -Fc -f "/tmp/$NAME"
  MSYS_NO_PATHCONV=1 docker cp "$DB_CONTAINER:/tmp/$NAME" "$ROOT/backups/$NAME"
  MSYS_NO_PATHCONV=1 docker exec "$DB_CONTAINER" rm -f "/tmp/$NAME"
  echo "Saved backups/$NAME (restore: pg_restore --clean --if-exists -d postgres)"
fi

# --- 3. reset -----------------------------------------------------------------------------------
step "supabase db reset (migrations + seed.sql + seed_stations.sql + seed_parties.sql + seed_products.sql)"
(cd "$ROOT" && supabase db reset)

# --- 4. rms_api password ------------------------------------------------------------------------
step "Setting the rms_api role password from backend/.env"
echo "alter role rms_api with password :'pw';" |
  docker exec -i "$DB_CONTAINER" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -v pw="$RMS_API_PASSWORD"

# --- 5. demo cleanup + users --------------------------------------------------------------------
step "Provisioning users (and removing DEMO masters)"
PY_ARGS=(scripts/uat_reset.py --password "$PASSWORD")
[[ $KEEP_DEMO -eq 1 ]] || PY_ARGS+=(--clean-demo-masters)
(cd "$BACKEND" && "${PYTHON[@]}" "${PY_ARGS[@]}")

# --- 6. verification ----------------------------------------------------------------------------
step "Verifying"
seed_rows() {
  head -1 "$ROOT/supabase/$1" | sed -nE 's/.*\(([0-9]+) rows\).*/\1/p' | grep . \
    || fail "cannot read the row count from supabase/$1"
}
EXPECT_STATIONS="$((845 + $(seed_rows seed_stations.sql)))"
EXPECT_PARTIES="$(seed_rows seed_parties.sql)"
EXPECT_PRODUCTS="$(seed_rows seed_products.sql)"
FAILED=0
check() { # name, op (eq|ge), expected, sql
  local n ok
  n="$(psql_q "$4" | tr -d '\r')"
  if [[ "$2" == eq ]]; then [[ "$n" -eq "$3" ]] && ok=1 || ok=0; else [[ "$n" -ge "$3" ]] && ok=1 || ok=0; fi
  printf '  [%s] %-22s %6s   (expected %s %s)\n' "$([[ $ok -eq 1 ]] && echo 'OK  ' || echo FAIL)" "$1" "$n" \
    "$([[ "$2" == eq ]] && echo '=' || echo '>=')" "$3"
  [[ $ok -eq 1 ]] || FAILED=1
}
check "States" ge 36 "select count(*) from public.states"
check "Stations" ge "$EXPECT_STATIONS" "select count(*) from public.stations"
check "Product categories" eq 4 "select count(*) from public.product_categories where code in ('DMT','PRISMATIC','ENCLOSED_OVAL','GENERAL')"
check "Parties (PTY-)" eq "$EXPECT_PARTIES" "select count(*) from public.parties where code like 'PTY-%'"
check "Products (ITM-)" eq "$EXPECT_PRODUCTS" "select count(*) from public.products where code like 'ITM-%'"
check "Roles" ge 13 "select count(*) from public.roles"
check "Users (active)" ge 12 "select count(*) from public.profiles where is_active"
check "Super Admins" ge 1 "select count(*) from public.profiles where is_super_admin and is_active"
check "Users without a role" eq 0 "select count(*) from public.profiles p where p.is_active and not exists (select 1 from public.user_roles ur where ur.user_id = p.id)"
if [[ $KEEP_DEMO -eq 0 ]]; then
  check "DEMO masters left" eq 0 "select (select count(*) from public.parties where code like 'DEMO-%') + (select count(*) from public.products where code like 'DEMO-%') + (select count(*) from public.transporters where name like '%(DEMO)%')"
fi
[[ $FAILED -eq 0 ]] || fail "verification failed (see above)"

printf '\nDatabase reset complete. Users log in with password: %s\nStart the app with: scripts/dev.sh\n' "$PASSWORD"
