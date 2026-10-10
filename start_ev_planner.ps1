$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (!(Test-Path $Python)) {
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        py -3 -m venv (Join-Path $Root ".venv")
    } else {
        $PyCmd = Get-Command python -ErrorAction SilentlyContinue
        if (!$PyCmd) { throw "Python was not found. Install Python 3.12 or 3.13 and reopen PowerShell." }
        python -m venv (Join-Path $Root ".venv")
    }
}
if (!(Test-Path $Python)) { throw "Virtual environment creation failed: $Python" }

$DataPath = Join-Path $Root "data\processed\north_india_ev_chargers_map.geojson"
if (!(Test-Path $DataPath)) {
    throw "North India GeoJSON missing at $DataPath. Extract this MVP pack into the project root first."
}

Write-Host "Installing/verifying app runtime dependencies..." -ForegroundColor Cyan
& $Python -m pip install -r (Join-Path $Root "requirements-mvp.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Check network/pip output." }

Write-Host "Starting GRIDPULSE API + frontend at http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Keep this terminal open. Press Ctrl+C to stop the server." -ForegroundColor Yellow
Start-Job -ScriptBlock { Start-Sleep -Seconds 3; Start-Process "http://127.0.0.1:8000" } | Out-Null
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
