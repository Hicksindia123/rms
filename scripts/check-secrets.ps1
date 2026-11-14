# Fails if the Supabase service-role key (or any reference to it) appears under frontend/.
# Master plan §9.5: the service-role key must never reach the browser bundle.
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root 'frontend'

if (-not (Test-Path $frontend)) {
    Write-Error "check-secrets: frontend/ not found at $frontend"
    exit 2
}

# Generated/third-party output is excluded; .env files ARE scanned.
$excluded = @('node_modules', 'dist', 'coverage', 'playwright-report', 'test-results')
# Excluded top-level folders are skipped BEFORE recursing: node_modules holds paths longer than the
# Windows 260-character limit (e.g. @reduxjs/toolkit via recharts), which Get-ChildItem cannot read.
$files = Get-ChildItem -Path $frontend -Force | Where-Object { $excluded -notcontains $_.Name } |
    ForEach-Object {
        if ($_.PSIsContainer) { Get-ChildItem -Path $_.FullName -Recurse -File -Force } else { $_ }
    } | Where-Object {
        $rel = $_.FullName.Substring($frontend.Length + 1)
        $rel -notmatch '[\\/]node_modules[\\/]'
    }

$found = $files | Select-String -Pattern 'service_role|SERVICE_ROLE' -CaseSensitive

if ($found) {
    Write-Host 'check-secrets: FAIL - service-role reference found under frontend/:' -ForegroundColor Red
    $found | ForEach-Object { Write-Host ("  {0}:{1}: {2}" -f $_.Path, $_.LineNumber, $_.Line.Trim()) }
    exit 1
}

Write-Host 'check-secrets: OK - no service-role references under frontend/' -ForegroundColor Green
exit 0
