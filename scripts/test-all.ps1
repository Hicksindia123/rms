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

param(
    [switch]$SkipDbReset,
    [switch]$SkipE2E,
    [switch]$E2E
)

if ($E2E) {
    $SkipE2E = $false
}

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

$results = [System.Collections.Generic.List[object]]::new()

function Invoke-Step {
    param([string]$Name, [string]$Dir, [scriptblock]$Command)
    Write-Host ''
    Write-Host "=== $Name" -ForegroundColor Cyan
    Push-Location $Dir
    try {
        & $Command
        $ok = ($LASTEXITCODE -eq 0)
    }
    catch {
        Write-Host $_ -ForegroundColor Red
        $ok = $false
    }
    finally {
        Pop-Location
    }
    $status = if ($ok) { 'PASS' } else { 'FAIL' }
    $results.Add([pscustomobject]@{ Status = $status; Name = $Name })
    if (-not $ok) {
        Write-Host "Step '$Name' failed with exit code $LASTEXITCODE." -ForegroundColor Red
    }
}

function Add-Skip([string]$Name, [string]$Reason = '') {
    $nameWithReason = if ($Reason) { "$Name ($Reason)" } else { $Name }
    $results.Add([pscustomobject]@{ Status = 'SKIP'; Name = $nameWithReason })
}

# 0. Secrets Scan
Invoke-Step 'secrets scan' $root { & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\check-secrets.ps1') }

# 1. DB Reset
if (-not $SkipDbReset) {
    if (Get-Command supabase -ErrorAction SilentlyContinue) {
        Invoke-Step 'supabase db reset' $root { supabase db reset }
    } else {
        $results.Add([pscustomobject]@{ Status = 'FAIL'; Name = 'supabase db reset (supabase CLI not on PATH)' })
    }
} else {
    Add-Skip 'supabase db reset' 'flag -SkipDbReset passed'
}

# 2. pgTAP Tests
if (Get-ChildItem -Path (Join-Path $root 'supabase\tests') -Filter '*.sql' -ErrorAction SilentlyContinue) {
    if (Get-Command supabase -ErrorAction SilentlyContinue) {
        Invoke-Step 'supabase test db (pgTAP)' $root { supabase test db }
    } else {
        $results.Add([pscustomobject]@{ Status = 'FAIL'; Name = 'supabase test db (supabase CLI not on PATH)' })
    }
} else {
    Add-Skip 'supabase test db' 'no sql tests found'
}

$hasUv = [bool](Get-Command uv -ErrorAction SilentlyContinue)

# 3. Backend Tests
Invoke-Step 'backend ruff check'  $backend $(if ($hasUv) { { uv run ruff check . } } else { { .\.venv\Scripts\ruff.exe check . } })
Invoke-Step 'backend ruff format' $backend $(if ($hasUv) { { uv run ruff format --check . } } else { { .\.venv\Scripts\ruff.exe format --check . } })
Invoke-Step 'backend mypy'        $backend $(if ($hasUv) { { uv run mypy app } } else { { .\.venv\Scripts\mypy.exe app } })
Invoke-Step 'backend pytest'      $backend $(if ($hasUv) { { uv run pytest -q } } else { { .\.venv\Scripts\pytest.exe -q } })

# 4. Frontend Unit
Invoke-Step 'frontend lint'       $frontend { pnpm lint }
Invoke-Step 'frontend format'     $frontend { pnpm format:check }
Invoke-Step 'frontend typecheck'  $frontend { pnpm typecheck }
Invoke-Step 'frontend unit tests' $frontend { pnpm test }
Invoke-Step 'frontend build'      $frontend { pnpm build }

# 5. API Type Generation Diff Check (fails if types stale)
Invoke-Step 'api type freshness check' $frontend {
    pnpm gen:api
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    git diff --exit-code src/lib/api/schema.d.ts
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'ERROR: src/lib/api/schema.d.ts is out of date with current backend openapi schema!' -ForegroundColor Red
        exit 1
    }
}

# 6. E2E (Playwright)
if (-not $SkipE2E) {
    Invoke-Step 'frontend e2e (playwright)' $frontend { pnpm e2e }
} else {
    Add-Skip 'frontend e2e' 'flag -SkipE2E passed'
}

# 7. Database Integrity Check (integrity_check.sql)
Invoke-Step 'database integrity check' $root {
    $dbContainer = docker ps -q -f "name=supabase_db"
    if ($dbContainer) {
        Get-Content (Join-Path $root 'scripts\integrity_check.sql') -Raw | docker exec -i $dbContainer psql -U postgres -v ON_ERROR_STOP=1
    } elseif (Get-Command psql -ErrorAction SilentlyContinue) {
        psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f (Join-Path $root 'scripts\integrity_check.sql')
    } else {
        Write-Host "Neither docker nor psql found to run integrity_check.sql" -ForegroundColor Red
        exit 1
    }
}

# Output Summary Table
Write-Host ''
Write-Host '===================================================' -ForegroundColor Cyan
Write-Host '                TEST SUITE SUMMARY                 ' -ForegroundColor Cyan
Write-Host '===================================================' -ForegroundColor Cyan
foreach ($r in $results) {
    $color = switch ($r.Status) { 'PASS' { 'Green' } 'SKIP' { 'Yellow' } default { 'Red' } }
    Write-Host ("  [{0}]  {1}" -f $r.Status, $r.Name) -ForegroundColor $color
}
Write-Host '===================================================' -ForegroundColor Cyan

if ($results | Where-Object Status -eq 'FAIL') {
    Write-Host 'One or more test steps failed.' -ForegroundColor Red
    exit 1
}

Write-Host 'All tests passed successfully!' -ForegroundColor Green
exit 0
