<#
.SYNOPSIS
    Resets the RMS local database and prepares a clean UAT environment.
.DESCRIPTION
    Resets local Supabase DB (runs migrations and baseline reference seed),
    purges all demo transactions, provisions workbook UAT users with
    pre-assigned roles, and optionally imports real products and parties CSVs.
.PARAMETER Password
    Password for all UAT users (default: 'Uat@2026RMS!').
.PARAMETER ProductsCsv
    Optional path to real products CSV file.
.PARAMETER PartiesCsv
    Optional path to real parties CSV file.
.PARAMETER CleanDemoMasters
    Switch to purge placeholder DEMO-* products, parties, and transporters.
.PARAMETER SkipDbReset
    Skip the full `supabase db reset` if already fresh.
#>
[CmdletBinding()]
param(
    [string]$Password = 'Uat@2026RMS!',
    [string]$ProductsCsv,
    [string]$PartiesCsv,
    [switch]$CleanDemoMasters,
    [switch]$SkipDbReset
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "RMS User Acceptance Testing (UAT) Environment Reset" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# Step 1: Check Supabase CLI and reset database if requested
if (-not $SkipDbReset) {
    if (Get-Command 'supabase' -ErrorAction SilentlyContinue) {
        Write-Host "Resetting Supabase database (migrations + reference seeds)..." -ForegroundColor Yellow
        Push-Location $root
        try {
            supabase db reset
            # Set the rms_api role password (required after db reset per docs/SETUP.md line 44)
            if (Get-Command 'docker' -ErrorAction SilentlyContinue) {
                Write-Host "Configuring rms_api database role password..." -ForegroundColor Gray
                docker exec -i supabase_db_rms psql -U postgres -d postgres -c "alter role rms_api with password 'rms_api_local_pw';" | Out-Null
            }
        } finally {
            Pop-Location
        }
    } else {
        Write-Warning "supabase CLI not found on PATH. Skipping 'supabase db reset'. Using existing DB schema."
    }
}

# Step 2: Run Python UAT reset and provisioner script
$pyArgs = @("scripts/uat_reset.py", "--password", $Password)

if ($ProductsCsv) {
    $pyArgs += @("--products-csv", (Resolve-Path $ProductsCsv).Path)
}

if ($PartiesCsv) {
    $pyArgs += @("--parties-csv", (Resolve-Path $PartiesCsv).Path)
}

if ($CleanDemoMasters) {
    $pyArgs += "--clean-demo-masters"
}

Write-Host "Provisioning UAT users and verifying zero-transaction state..." -ForegroundColor Yellow
Push-Location $backend
try {
    if (Get-Command 'uv' -ErrorAction SilentlyContinue) {
        uv run python @pyArgs
    } else {
        python @pyArgs
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Green
Write-Host "UAT Reset Completed Successfully!" -ForegroundColor Green
Write-Host "All workbook UAT accounts are active with password: $Password" -ForegroundColor Green
Write-Host "Start the application with: .\scripts\dev.ps1" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Green
