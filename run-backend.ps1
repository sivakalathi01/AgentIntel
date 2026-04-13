$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Backend venv Python not found at $python"
}

Push-Location $backend
try {
    & $python -m uvicorn --app-dir $backend app.main:app --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
