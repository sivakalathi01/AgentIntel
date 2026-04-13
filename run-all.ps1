$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

try {
    $npmCmd = (Get-Command npm.cmd -ErrorAction Stop).Source
}
catch {
    throw "npm not found in PATH. Please install Node.js or add npm to PATH."
}

if (-not (Test-Path $python)) {
    throw "Backend venv Python not found at $python"
}

Write-Host "Starting backend on http://127.0.0.1:8000 ..."
$backendProc = $null
$backendPortUsed = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($backendPortUsed) {
    Write-Host "Backend port 8000 already in use; skipping backend start."
}
else {
    $backendProc = Start-Process -FilePath $python -ArgumentList @("-m", "uvicorn", "--app-dir", $backend, "app.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $backend -PassThru -NoNewWindow
}

Write-Host "Starting frontend on http://127.0.0.1:3000 ..."
$frontendProc = $null
$frontendPortUsed = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
if ($frontendPortUsed) {
    Write-Host "Frontend port 3000 already in use; skipping frontend start."
}
else {
    $frontendProc = Start-Process -FilePath $npmCmd -ArgumentList @("run", "dev", "--", "--port", "3000") -WorkingDirectory $frontend -PassThru -NoNewWindow
}

Start-Sleep -Seconds 3

if ($backendProc) {
    Write-Host "Backend PID: $($backendProc.Id)"
}
if ($frontendProc) {
    Write-Host "Frontend PID: $($frontendProc.Id)"
}

Write-Host ""
Write-Host "Health checks:"

$backendReady = $false
$frontendReady = $false
$maxRetries = 5
$retryCount = 0

while (($backendReady -eq $false -or $frontendReady -eq $false) -and $retryCount -lt $maxRetries) {
    if (-not $backendReady) {
        try {
            $backendHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method Get -TimeoutSec 3
            Write-Host "  Backend: OK ($($backendHealth.status))"
            $backendReady = $true
        }
        catch {
            Write-Host "  Backend: checking... ($($retryCount+1)/$maxRetries)"
        }
    }
    
    if (-not $frontendReady) {
        try {
            $frontendResp = Invoke-WebRequest -Uri "http://127.0.0.1:3000" -Method Get -TimeoutSec 3 -UseBasicParsing
            Write-Host "  Frontend: OK (HTTP $($frontendResp.StatusCode))"
            $frontendReady = $true
        }
        catch {
            Write-Host "  Frontend: checking... ($($retryCount+1)/$maxRetries)"
        }
    }
    
    if (-not $backendReady -or -not $frontendReady) {
        Start-Sleep -Seconds 2
        $retryCount++
    }
}

if (-not $backendReady) {
    Write-Host "  Backend: not ready after retries (may still be starting)"
}
if (-not $frontendReady) {
    Write-Host "  Frontend: not ready after retries (may still be starting)"
}

Write-Host ""
Write-Host "Services running on:"
Write-Host "  Frontend: http://127.0.0.1:3000"
Write-Host "  Backend:  http://127.0.0.1:8000"
Write-Host "  API docs: http://127.0.0.1:8000/docs"
Write-Host ""
Write-Host "To stop processes using the app ports:"
Write-Host '  Get-NetTCPConnection -LocalPort 8000,3000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique | ForEach-Object { Stop-Process -Id $_ }'
