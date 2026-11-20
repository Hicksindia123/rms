<#
.SYNOPSIS
    One-command rebuild of the LOCAL RMS database with all reference and master data.
.DESCRIPTION
    1. Preflight: docker, supabase CLI, backend Python, APP_ENV=local (refuses anything else).
    2. Backup of the current DB to backups\ (skip with -SkipBackup).
    3. supabase db reset:
         migrations  -> schema, guards, roles/permissions, all-India states & stations
         seed.sql    -> reference config (option sets, forms, workflow, categories incl. GENERAL)
         seed_stations.sql -> stations added for the party import (DEC-37)
         seed_parties.sql / seed_products.sql -> party and item masters (config.toml [db.seed])
    4. rms_api role password, taken from backend\.env DATABASE_URL.
    5. backend\scripts\uat_reset.py: removes DEMO placeholder masters and provisions the 16
       workbook users with their roles (admin@rms.local is Super Admin).
    6. Verification: counts every master against its seed file; exits non-zero on any mismatch.
.PARAMETER Password
    Password for all provisioned users (default: Uat@2026RMS!, as in RMS_USER_CREDENTIALS.txt).
.PARAMETER SkipBackup
    Do not dump the current database before resetting.
.PARAMETER KeepDemo
    Keep the DEMO-* placeholder party/products/transporter from seed.sql.
.EXAMPLE
    .\scripts\reset-db.ps1
.EXAMPLE
    .\scripts\reset-db.ps1 -Password 'S0me-Other!Pw' -SkipBackup
#>
[CmdletBinding()]
param(
    [string]$Password = 'Uat@2026RMS!',
    [switch]$SkipBackup,
    [switch]$KeepDemo
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$dbContainer = 'supabase_db_rms'   # supabase/config.toml project_id = "rms"

function Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Fail([string]$msg) { Write-Host "reset-db: $msg" -ForegroundColor Red; exit 1 }
function Check-Exit([string]$what) { if ($LASTEXITCODE -ne 0) { Fail "$what failed (exit $LASTEXITCODE)" } }
# Native tools (supabase, docker, python) write progress to stderr. Windows PowerShell 5.1 turns
# that into a terminating error under 'Stop' when output is redirected, so native calls run under
# 'Continue' and are judged by their exit code only.
function Invoke-Native([string]$what, [scriptblock]$block) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $block } finally { $ErrorActionPreference = $prev }
    Check-Exit $what
}
function Psql([string]$sql) {
    return Invoke-Native "psql: $sql" { docker exec -i $dbContainer psql -U postgres -d postgres -At -v ON_ERROR_STOP=1 -c $sql }
}

# --- 1. preflight -------------------------------------------------------------------------------
Step 'Preflight'
foreach ($cmd in 'docker', 'supabase') {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { Fail "'$cmd' is not on PATH (see docs/SETUP.md)" }
}
$envFile = Join-Path $backend '.env'
if (-not (Test-Path $envFile)) { Fail 'backend\.env not found (copy backend\.env.example, see docs/SETUP.md)' }
$envText = Get-Content $envFile -Raw
if ($envText -notmatch '(?m)^APP_ENV=local\s*$') { Fail 'APP_ENV in backend\.env is not "local"; this script only resets the local database' }
if ($envText -notmatch '(?m)^DATABASE_URL=[^\r\n]*://rms_api:([^@\r\n]+)@') { Fail 'DATABASE_URL in backend\.env does not use the rms_api role' }
$rmsApiPassword = [uri]::UnescapeDataString($Matches[1])

if (Get-Command 'uv' -ErrorAction SilentlyContinue) {
    $python = @('uv', 'run', 'python')
} elseif (Test-Path (Join-Path $backend '.venv\Scripts\python.exe')) {
    $python = @((Join-Path $backend '.venv\Scripts\python.exe'))
} else {
    Fail "neither 'uv' nor backend\.venv was found"
}

$running = Invoke-Native 'docker ps' { docker ps --filter "name=^$dbContainer$" --format '{{.Names}}' }
if ($running -ne $dbContainer) {
    Write-Host 'Local Supabase is not running; starting it...'
    Push-Location $root
    try { Invoke-Native 'supabase start' { supabase start } } finally { Pop-Location }
}

# --- 2. backup ----------------------------------------------------------------------------------
if (-not $SkipBackup) {
    Step 'Backing up the current database'
    $backupDir = Join-Path $root 'backups'
    New-Item -ItemType Directory -Force $backupDir | Out-Null
    $name = 'rms-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.dump'
    Invoke-Native 'pg_dump' { docker exec $dbContainer pg_dump -U postgres -d postgres -Fc -f "/tmp/$name" }
    Invoke-Native 'docker cp' { docker cp "${dbContainer}:/tmp/$name" (Join-Path $backupDir $name) }
    Invoke-Native 'cleanup' { docker exec $dbContainer rm -f "/tmp/$name" | Out-Null }
    Write-Host "Saved backups\$name (restore: pg_restore --clean --if-exists -d postgres)"
}

# --- 3. reset -----------------------------------------------------------------------------------
Step 'supabase db reset (migrations + seed.sql + seed_stations.sql + seed_parties.sql + seed_products.sql)'
Push-Location $root
try { Invoke-Native 'supabase db reset' { supabase db reset } } finally { Pop-Location }

# --- 4. rms_api password ------------------------------------------------------------------------
Step 'Setting the rms_api role password from backend\.env'
Invoke-Native 'alter role rms_api' {
    "alter role rms_api with password :'pw';" |
        docker exec -i $dbContainer psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -v pw="$rmsApiPassword"
}

# --- 5. demo cleanup + users --------------------------------------------------------------------
Step 'Provisioning users (and removing DEMO masters)'
$pyArgs = @('scripts/uat_reset.py', '--password', $Password)
if (-not $KeepDemo) { $pyArgs += '--clean-demo-masters' }
Push-Location $backend
try {
    $exe = $python[0]
    $pre = @($python | Select-Object -Skip 1)
    Invoke-Native 'uat_reset.py' { & $exe @pre @pyArgs }
} finally { Pop-Location }

# --- 6. verification ----------------------------------------------------------------------------
Step 'Verifying'
function Seed-Rows([string]$file) {
    $header = Get-Content (Join-Path $root "supabase\$file") -TotalCount 1
    if ($header -notmatch '\((\d+) rows\)') { Fail "cannot read the row count from supabase\$file" }
    return [int]$Matches[1]
}
$expectStations = 845 + (Seed-Rows 'seed_stations.sql')
$expectParties = Seed-Rows 'seed_parties.sql'
$expectProducts = Seed-Rows 'seed_products.sql'
$checks = @(
    @{ Name = 'States';               Sql = "select count(*) from public.states";                                 Min = 36 },
    @{ Name = 'Stations';             Sql = "select count(*) from public.stations";                               Min = $expectStations },
    @{ Name = 'Product categories';   Sql = "select count(*) from public.product_categories where code in ('DMT','PRISMATIC','ENCLOSED_OVAL','GENERAL')"; Exact = 4 },
    @{ Name = 'Parties (PTY-)';       Sql = "select count(*) from public.parties where code like 'PTY-%'";      Exact = $expectParties },
    @{ Name = 'Products (ITM-)';      Sql = "select count(*) from public.products where code like 'ITM-%'";     Exact = $expectProducts },
    @{ Name = 'Roles';                Sql = "select count(*) from public.roles";                                  Min = 13 },
    @{ Name = 'Users (active)';       Sql = "select count(*) from public.profiles where is_active";              Min = 12 },
    @{ Name = 'Super Admins';         Sql = "select count(*) from public.profiles where is_super_admin and is_active"; Min = 1 },
    @{ Name = 'Users without a role'; Sql = "select count(*) from public.profiles p where p.is_active and not exists (select 1 from public.user_roles ur where ur.user_id = p.id)"; Exact = 0 }
)
if (-not $KeepDemo) {
    $checks += @{ Name = 'DEMO masters left'; Sql = "select (select count(*) from public.parties where code like 'DEMO-%') + (select count(*) from public.products where code like 'DEMO-%') + (select count(*) from public.transporters where name like '%(DEMO)%')"; Exact = 0 }
}
$failed = $false
foreach ($c in $checks) {
    $n = [int](Psql $c.Sql)
    if ($c.ContainsKey('Exact')) { $ok = ($n -eq $c.Exact); $want = "= $($c.Exact)" } else { $ok = ($n -ge $c.Min); $want = ">= $($c.Min)" }
    $mark = if ($ok) { 'OK  ' } else { 'FAIL' }
    $color = if ($ok) { 'Green' } else { 'Red' }
    Write-Host ("  [{0}] {1,-22} {2,6}   (expected {3})" -f $mark, $c.Name, $n, $want) -ForegroundColor $color
    if (-not $ok) { $failed = $true }
}
if ($failed) { Fail 'verification failed (see above)' }

Write-Host "`nDatabase reset complete. Users log in with password: $Password" -ForegroundColor Green
Write-Host 'Start the app with: .\scripts\dev.ps1' -ForegroundColor Green
