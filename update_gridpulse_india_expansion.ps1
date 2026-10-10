[CmdletBinding()]
param(
    [Parameter()]
    [string]$ProjectRoot = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
$Branch = "feature/india-wide-coverage-validation"
$Files = @(
    "app/main.py",
    "app/route_api.py",
    "app/geo_boundaries.py",
    "app/static/index.html",
    "scripts/prepare_india_inventory.py",
    "tests/test_india_boundary_validation.py",
    "tests/test_mvp.py",
    "tests/test_central_support.py",
    "tests/test_northeast_support.py",
    "INSTALL_GRIDPULSE_INDIA.md",
    "readme.md",
    "README_MVP.md",
    "README_ROUTE_PLANNER.md"
)

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Could not find the project virtual environment at '$Python'. Set ProjectRoot to C:\EV\ev proje."
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $ProjectRoot ".backup-india-expansion-$Stamp"
$StageRoot = Join-Path $env:TEMP ("gridpulse-india-expansion-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $StageRoot -Force | Out-Null

Write-Host "GRIDPULSE India-wide update"
Write-Host "Project: $ProjectRoot"
Write-Host "A backup of existing code files will be kept at: $BackupRoot"
Write-Host ""

try {
    # Stage all downloads first; no project file is overwritten until every
    # source file has downloaded successfully.
    foreach ($RelativePath in $Files) {
        $UrlPath = $RelativePath.Replace("\", "/")
        $StagePath = Join-Path $StageRoot $RelativePath
        $StageDirectory = Split-Path -Parent $StagePath
        New-Item -ItemType Directory -Path $StageDirectory -Force | Out-Null
        $Url = "https://raw.githubusercontent.com/AnshXGrind/ev-proje/$Branch/$UrlPath"
        Write-Host "Downloading $RelativePath"
        Invoke-WebRequest -Uri $Url -OutFile $StagePath -UseBasicParsing -TimeoutSec 60
        if (-not (Test-Path -LiteralPath $StagePath) -or (Get-Item -LiteralPath $StagePath).Length -lt 20) {
            throw "Downloaded file is missing or unexpectedly small: $RelativePath"
        }
    }

    foreach ($RelativePath in $Files) {
        $Destination = Join-Path $ProjectRoot $RelativePath
        if (Test-Path -LiteralPath $Destination) {
            $BackupPath = Join-Path $BackupRoot $RelativePath
            New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
            Copy-Item -LiteralPath $Destination -Destination $BackupPath -Force
        }
    }

    foreach ($RelativePath in $Files) {
        $Destination = Join-Path $ProjectRoot $RelativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $StageRoot $RelativePath) -Destination $Destination -Force
    }

    $CompileFiles = @(
        (Join-Path $ProjectRoot "app\main.py"),
        (Join-Path $ProjectRoot "app\route_api.py"),
        (Join-Path $ProjectRoot "app\geo_boundaries.py"),
        (Join-Path $ProjectRoot "scripts\prepare_india_inventory.py")
    )
    Write-Host ""
    Write-Host "Checking Python syntax..."
    & $Python -m py_compile @CompileFiles
    if ($LASTEXITCODE -ne 0) {
        throw "Python syntax check failed. Existing files are backed up at '$BackupRoot'."
    }

    $RawInventory = Join-Path $ProjectRoot "data\raw\india_ev_chargers_raw.geojson"
    if (-not (Test-Path -LiteralPath $RawInventory)) {
        throw "The India source inventory was not found at '$RawInventory'. Re-extract the bundle at the project root."
    }

    Write-Host ""
    Write-Host "Running official India state/UT polygon validation. This may take a few minutes."
    & $Python (Join-Path $ProjectRoot "scripts\prepare_india_inventory.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "The boundary-validation pipeline did not complete."
        Write-Host "Official boundary download URL:"
        Write-Host "https://nwdp.nwic.gov.in/dataset/dd960900-34cc-4486-a95c-83200d2f2c7b/resource/f039e721-132c-4a24-9e5e-07af03064b4d/download/state_NWIC_GeoJSON.zip"
        Write-Host "If automatic download failed, save that ZIP as:"
        Write-Host (Join-Path $ProjectRoot "data\raw\state_NWIC_GeoJSON.zip")
        Write-Host "Then rerun this same installer command."
        throw "National inventory is not yet validated. Do not start the app in nationwide mode until this step succeeds."
    }

    Write-Host ""
    Write-Host "Running focused regression tests..."
    $TestFiles = @(
        (Join-Path $ProjectRoot "tests\test_india_boundary_validation.py"),
        (Join-Path $ProjectRoot "tests\test_northeast_support.py"),
        (Join-Path $ProjectRoot "tests\test_central_support.py"),
        (Join-Path $ProjectRoot "tests\test_mvp.py")
    )
    & $Python -m pytest $TestFiles -q
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed. Check the error output above; the prior code files are backed up at '$BackupRoot'."
    }

    Write-Host ""
    Write-Host "SUCCESS: India-wide source inventory prepared and boundary audit completed."
    Write-Host "Validated map: $(Join-Path $ProjectRoot 'data\processed\india_ev_chargers_map.geojson')"
    Write-Host "Full audit: $(Join-Path $ProjectRoot 'data\reports\india_ev_chargers_boundary_audit.csv')"
    Write-Host "State/UT summary: $(Join-Path $ProjectRoot 'data\reports\india_ev_chargers_boundary_summary.csv')"
    Write-Host "Backup: $BackupRoot"
    Write-Host "Restart Uvicorn, then verify http://127.0.0.1:8000/api/health."
}
catch {
    Write-Error $_
    Write-Host "Existing code backups (if replacement began): $BackupRoot"
    exit 1
}
finally {
    if (Test-Path -LiteralPath $StageRoot) {
        Remove-Item -LiteralPath $StageRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
