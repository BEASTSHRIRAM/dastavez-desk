# Starts the API (port 8000) and the web app (port 3000), each in its own window.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

foreach ($port in 8000, 3000) {
  $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if ($busy) {
    $p = Get-Process -Id $busy[0].OwningProcess -ErrorAction SilentlyContinue
    Write-Host "Port $port is already in use by $($p.ProcessName) (PID $($busy[0].OwningProcess))." -ForegroundColor Red
    Write-Host "Stop it first, for example: Stop-Process -Id $($busy[0].OwningProcess)" -ForegroundColor Yellow
    exit 1
  }
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; .\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"

Write-Host "API:  http://localhost:8000/docs" -ForegroundColor Green
Write-Host "App:  http://localhost:3000" -ForegroundColor Green
Write-Host "Demo login: operator@demo.test / demo-pass"
