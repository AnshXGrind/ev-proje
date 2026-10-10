$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$MainPath = Join-Path $Root "app\main.py"
$IndexPath = Join-Path $Root "app\static\index.html"
$RouteApi = Join-Path $Root "app\route_api.py"
$RouteHtml = Join-Path $Root "app\static\route_planner.html"

foreach ($path in @($MainPath, $IndexPath, $RouteApi, $RouteHtml)) {
    if (!(Test-Path $path)) { throw "Required file not found: $path. Extract the patch ZIP into C:\EV\ev proje first." }
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (!(Test-Path $Python)) { throw "Project virtual environment not found at $Python. Create .venv before applying this patch." }

Write-Host "Checking route-planner dependencies..." -ForegroundColor Cyan
& $Python -c "import requests, pyproj, shapely, fastapi, pydantic, numpy"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing route-planner runtime dependencies..." -ForegroundColor Yellow
    & $Python -m pip install -r (Join-Path $Root "requirements-route.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependencies could not be installed. Check the pip/network error." }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item $MainPath "$MainPath.backup-$stamp" -Force
Copy-Item $IndexPath "$IndexPath.backup-$stamp" -Force

$mainText = [System.IO.File]::ReadAllText($MainPath)
if ($mainText -notmatch 'app\.include_router\(route_planner_router\)') {
    $marker = 'if __name__ == "__main__":'
    if (!$mainText.Contains($marker)) { throw "Could not find the main guard in app\main.py; backup made, but no code was changed." }
    $insert = "from app.route_api import router as route_planner_router`r`napp.include_router(route_planner_router)`r`n`r`n"
    $mainText = $mainText.Replace($marker, $insert + $marker)
    [System.IO.File]::WriteAllText($MainPath, $mainText, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Registered route API endpoints in app\main.py" -ForegroundColor Green
} else {
    Write-Host "Route API is already registered in app\main.py" -ForegroundColor DarkGray
}

$indexText = [System.IO.File]::ReadAllText($IndexPath)
if ($indexText -notmatch 'href="/route-planner"') {
    $stationButton = '<button class="navbtn" data-page="stations"><span class="ico">⌖</span><span>Station explorer</span></button>'
    if (!$indexText.Contains($stationButton)) {
        throw "Could not locate the Station Explorer navigation item in app\static\index.html. Backups exist; no navigation change made."
    }
    $routeLink = '<a href="/route-planner" style="display:flex;align-items:center;gap:11px;padding:12px 13px;border-radius:10px;background:#edf2ff;color:#2856ca;text-decoration:none;font-weight:700;width:100%;box-sizing:border-box"><span style="width:20px;text-align:center;font-size:16px">⇢</span><span>Route Planner</span></a>'
    $indexText = $indexText.Replace($stationButton, $stationButton + "`r`n    " + $routeLink)
    [System.IO.File]::WriteAllText($IndexPath, $indexText, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Added Route Planner navigation link to dashboard" -ForegroundColor Green
} else {
    Write-Host "Route Planner navigation link already exists" -ForegroundColor DarkGray
}

Write-Host "Compiling route API..." -ForegroundColor Cyan
& $Python -m py_compile (Join-Path $Root "app\route_api.py")
if ($LASTEXITCODE -ne 0) { throw "Route API syntax check failed. Restore backups if necessary." }

Write-Host "Running fast route-model unit tests..." -ForegroundColor Cyan
& $Python -m pytest tests\test_route_planner_model.py -q
if ($LASTEXITCODE -ne 0) { throw "Route-model tests failed. Check the failure output before restarting the server." }

Write-Host "`nRoute planner patch installed successfully." -ForegroundColor Green
Write-Host "Important: stop the currently running Uvicorn process with Ctrl+C, then restart it." -ForegroundColor Yellow
Write-Host 'Start command: .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000' -ForegroundColor Cyan
Write-Host 'Dashboard:    http://127.0.0.1:8000' -ForegroundColor Cyan
Write-Host 'Route Planner: http://127.0.0.1:8000/route-planner' -ForegroundColor Cyan
Write-Host 'API docs:     http://127.0.0.1:8000/docs' -ForegroundColor Cyan
