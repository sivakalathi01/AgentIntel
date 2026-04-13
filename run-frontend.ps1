$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontend = Join-Path $root "frontend"

Push-Location $frontend
try {
    npm run dev -- --port 3000
}
finally {
    Pop-Location
}
