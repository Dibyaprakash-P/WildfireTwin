# Start MongoDB, the backend API and the frontend dev server as independent processes.
# Usage (from anywhere):  powershell -ExecutionPolicy Bypass -File C:\WildFireTwin\scripts\start_all.ps1
# Already-running services (port in use) are left alone. Logs: data\mongo\mongod.log, data\backend.log, data\frontend.log
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function PortUp($port) { [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }

if (-not (PortUp 27017)) {
    New-Item -ItemType Directory -Force data\mongo | Out-Null
    Start-Process -WindowStyle Hidden -FilePath "$root\tools\mongodb\bin\mongod.exe" `
        -ArgumentList "--dbpath", "$root\data\mongo", "--bind_ip", "127.0.0.1", "--port", "27017", "--logpath", "$root\data\mongo\mongod.log"
    Write-Host "MongoDB started"
} else { Write-Host "MongoDB already running" }

if (-not (PortUp 8000)) {
    Start-Process -WindowStyle Hidden -FilePath "$root\.venv\Scripts\python.exe" -WorkingDirectory $root `
        -ArgumentList "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -RedirectStandardOutput "$root\data\backend.log" -RedirectStandardError "$root\data\backend.err.log"
    Write-Host "Backend started  -> http://127.0.0.1:8000/docs"
} else { Write-Host "Backend already running" }

if (-not (PortUp 5173)) {
    Start-Process -WindowStyle Hidden -FilePath "cmd.exe" -WorkingDirectory "$root\frontend" `
        -ArgumentList "/c", "npx vite --host 127.0.0.1 --port 5173 > ..\data\frontend.log 2>&1"
    Write-Host "Frontend started -> http://127.0.0.1:5173"
} else { Write-Host "Frontend already running" }
