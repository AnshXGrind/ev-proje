param(
    [string]$ProjectRoot = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path $ProjectRoot).Path

if (!(Test-Path (Join-Path $ProjectRoot "app\main.py"))) {
    throw "ProjectRoot does not look like GRIDPULSE: app\main.py was not found at $ProjectRoot"
}

$baseUrl = "https://raw.githubusercontent.com/AnshXGrind/ev-proje/main"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$staging = Join-Path $env:TEMP "gridpulse-central-update-$timestamp"
$backupRoot = Join-Path $ProjectRoot ".backup-central-update-$timestamp"

$files = @(
    "app/main.py",
    "app/route_api.py",
    "app/static/index.html",
    "configs/regions.yaml",
    "tests/test_mvp.py",
    "tests/test_northeast_support.py",
    "tests/test_central_support.py",
    "readme.md",
    "README_MVP.md",
    "README_ROUTE_PLANNER.md",
    "MVP_BUILD_NOTES.md"
)

New-Item -ItemType Directory -Force -Path $staging | Out-Null

Write-Host ""
Write-Host "Downloading updated GRIDPULSE code..." -ForegroundColor Cyan
foreach ($file in $files) {
    $relative = $file.Replace("/", "\")
    $target = Join-Path $staging $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    $url = "$baseUrl/$file"
    Invoke-WebRequest -Uri $url -OutFile $target -UseBasicParsing

    if (!(Test-Path $target) -or (Get-Item $target).Length -lt 100) {
        throw "Download validation failed for $file. No project files were changed."
    }

    Write-Host "Downloaded $file" -ForegroundColor Green
}

Write-Host ""
Write-Host "Backing up current code..." -ForegroundColor Cyan
foreach ($file in $files) {
    $relative = $file.Replace("/", "\")
    $source = Join-Path $ProjectRoot $relative
    $backup = Join-Path $backupRoot $relative

    if (Test-Path $source) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
        Copy-Item -LiteralPath $source -Destination $backup -Force
    }
}

Write-Host ""
Write-Host "Installing update..." -ForegroundColor Cyan
foreach ($file in $files) {
    $relative = $file.Replace("/", "\")
    $source = Join-Path $staging $relative
    $destination = Join-Path $ProjectRoot $relative

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
    Write-Host "Updated $file" -ForegroundColor Green
}

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $python) {
    Write-Host ""
    Write-Host "Checking Python syntax..." -ForegroundColor Cyan
    & $python -m py_compile (Join-Path $ProjectRoot "app\main.py") (Join-Path $ProjectRoot "app\route_api.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Python syntax check failed. Previous files are available in $backupRoot"
    }
}

Write-Host ""
Write-Host "Code update complete." -ForegroundColor Green
Write-Host "Backup: $backupRoot"
Write-Host "The data file is separate. Extract central_states_ev_chargers_bundle.zip into $ProjectRoot."
Write-Host "Required new data path: data\processed\central_states_ev_chargers_map.geojson"
Write-Host "Next: restart Uvicorn, then check /api/health."
