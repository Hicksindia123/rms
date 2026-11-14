# Start the RMS dev stack: backend API (:8000), worker (only if app/worker exists), frontend (:5173).
# Local Supabase is started separately with `supabase start` (see docs/SETUP.md).
# Backend and worker open in their own windows; the frontend runs in this console.
# Ctrl+C (or closing the frontend) stops everything this script started.
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

# Check for pnpm (frontend requirement)
if (-not (Get-Command 'pnpm' -ErrorAction SilentlyContinue)) {
    Write-Error "dev.ps1: 'pnpm' is not on PATH (run 'npm install -g pnpm' or see docs/SETUP.md)"
    exit 1
}

# Determine Python / Uvicorn runner: prefer 'uv', fallback to existing 'backend\.venv'
$useUv = [bool](Get-Command 'uv' -ErrorAction SilentlyContinue)
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'
$venvUvicorn = Join-Path $backend '.venv\Scripts\uvicorn.exe'

if ($useUv) {
    $backendCmd = 'uv run uvicorn app.main:app --reload --port 8000'
    $workerCmd  = 'uv run python -m app.worker'
} elseif (Test-Path $venvPython) {
    $backendCmd = "& '$venvPython' -m uvicorn app.main:app --reload --port 8000"
    $workerCmd  = "& '$venvPython' -m app.worker"
} else {
    Write-Error "dev.ps1: Neither 'uv' nor 'backend\.venv' Python environment was found. Please install uv (powershell -c ""irm https://astral.sh/uv/install.ps1 | iex"") or create backend/.venv."
    exit 1
}

# Ensure rms_api password is set in local Supabase DB if container is active
if (Get-Command 'docker' -ErrorAction SilentlyContinue) {
    try {
        docker exec -i supabase_db_rms psql -U postgres -d postgres -c "alter role rms_api with password 'rms_api_local_pw';" 2>$null | Out-Null
    } catch {
        # ignore if container is not running yet
    }
}

$started = @()
try {
    Write-Host 'dev.ps1: backend  -> http://localhost:8000/api/v1/health' -ForegroundColor Cyan
    $started += Start-Process -PassThru -WorkingDirectory $backend -FilePath 'powershell' `
        -ArgumentList '-NoExit', '-Command', $backendCmd

    $hasWorker = (Test-Path (Join-Path $backend 'app\worker.py')) -or
                 (Test-Path (Join-Path $backend 'app\worker\__init__.py'))
    if ($hasWorker) {
        Write-Host 'dev.ps1: worker   -> python -m app.worker' -ForegroundColor Cyan
        $started += Start-Process -PassThru -WorkingDirectory $backend -FilePath 'powershell' `
            -ArgumentList '-NoExit', '-Command', $workerCmd
    }
    else {
        Write-Host 'dev.ps1: worker   -> not present yet (backend/app/worker), skipped' -ForegroundColor Gray
    }

    Write-Host 'dev.ps1: frontend -> http://localhost:5173' -ForegroundColor Cyan
    Push-Location $frontend
    try {
        pnpm dev
    }
    finally {
        Pop-Location
    }
}
finally {
    Write-Host 'dev.ps1: stopping...' -ForegroundColor Yellow
    foreach ($p in $started) {
        if (-not $p.HasExited) {
            # /T kills the child process tree (uvicorn reloader + workers).
            taskkill /PID $p.Id /T /F | Out-Null
        }
    }
}
