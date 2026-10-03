# SPDX-License-Identifier: FSL-1.1-MIT
# ==============================================================================
# Smoke Test Runner for Archer LDAP Group Migration Toolkit
# NOTE: Run only against DEV / Non-Production databases!
# ==============================================================================
param(
    [string]$Server = ".",
    [string]$Database = "TargetArcherDB",
    [string]$SqlUser,
    [string]$SqlPassword
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BaseDir = Split-Path -Parent $ScriptDir
$ExportScript = Join-Path $BaseDir "scripts/Export-ArcherLdapGroups.py"
$ImportScript = Join-Path $BaseDir "scripts/Import-ArcherLdapGroups.py"
$RollbackScript = Join-Path $BaseDir "scripts/Rollback-ArcherLdapGroups.py"

Write-Host "=== Archer LDAP Group Migration Smoke Test ===" -ForegroundColor Cyan
Write-Host "Target Server   : $Server"
Write-Host "Target Database : $Database"

# Step 1: Verify Python & pyodbc
Write-Host "`n[1/3] Checking environment prerequisites..." -ForegroundColor Yellow
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Error "Python is not installed or not in PATH."
    exit 1
}
python -c "import pyodbc" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "pyodbc is missing. Run: pip install pyodbc"
    exit 1
}
Write-Host "Prerequisites OK." -ForegroundColor Green

# Step 2: Test CLI help flags
Write-Host "`n[2/3] Checking script entry points..." -ForegroundColor Yellow
python $ExportScript --help | Out-Null
python $ImportScript --help | Out-Null
python $RollbackScript --help | Out-Null
Write-Host "All scripts parsed successfully." -ForegroundColor Green

# Step 3: Run verify-only dry run on DEV instance
Write-Host "`n[3/3] Running verify-only dry run against $Database..." -ForegroundColor Yellow
    $sampleExport = Join-Path $BaseDir "examples/example_export.json"
if (Test-Path $sampleExport) {
    $authArgs = @()
    if ($SqlUser) {
        $authArgs += @("--sql-user", $SqlUser, "--sql-password", $SqlPassword)
    }
    python $ImportScript --server $Server --database $Database --input $sampleExport --verify-only @authArgs
} else {
    Write-Host "Example export file not found; skipping dry-run." -ForegroundColor Gray
}

Write-Host "`nSmoke test completed successfully." -ForegroundColor Green
Write-Host "See docs/RUNBOOK.md for the complete production migration sequence." -ForegroundColor Cyan
