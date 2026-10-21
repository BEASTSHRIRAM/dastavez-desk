# One-time setup for Windows PowerShell. Safe to run again.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "Backend: virtual environment and dependencies" -ForegroundColor Cyan
Set-Location "$root\backend"
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python -m pip install --upgrade pip --quiet
& .\.venv\Scripts\python -m pip install -r requirements-dev.txt --quiet
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Created backend\.env from the example. Edit it to add a database URL or API keys (optional)." -ForegroundColor Yellow
}

Write-Host "Frontend: dependencies" -ForegroundColor Cyan
Set-Location "$root\frontend"
npm install --no-audit --no-fund
if (-not (Test-Path ".env.local")) { Copy-Item ".env.example" ".env.local" }

Set-Location $root
Write-Host "`nDone. Start everything with: .\scripts\dev.ps1" -ForegroundColor Green
