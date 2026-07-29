<#
.SYNOPSIS
    CSAM Repair one-click test verification script (pre-release)
.DESCRIPTION
    Runs all test layers + coverage, generates JSON intermediate results and
    HTML coverage report. Calls generate_test_report.py to produce TEST_REPORT.md.

    Test layers (markers):
      smoke / regression / gui / export / mock / performance / stress

    Output files:
      test_results.json       - machine-readable results per layer + full suite
      coverage.xml            - coverage XML (CI/Codecov compatible)
      htmlcov/index.html      - coverage HTML report
      TEST_REPORT.md          - human-readable final report

.USAGE
    PS> .\run_all_tests.ps1                # full run + coverage
    PS> .\run_all_tests.ps1 -Quick         # smoke + regression only
    PS> .\run_all_tests.ps1 -SkipInstall   # skip pip install
    PS> .\run_all_tests.ps1 -NoCoverage    # skip coverage (faster)
#>
[CmdletBinding()]
param(
    [switch]$Quick,
    [switch]$SkipInstall,
    [switch]$NoCoverage
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$StartTime = Get-Date
Write-Host "================================================" -ForegroundColor Cyan
Write-Host " CSAM Repair Test Suite" -ForegroundColor Cyan
Write-Host " Project: $ProjectRoot" -ForegroundColor Cyan
Write-Host " Start:   $StartTime" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# ---------------------------------------------------------------
# 0. Environment check + deps install
# ---------------------------------------------------------------
Write-Host ""
Write-Host "[0/4] Environment check..." -ForegroundColor Yellow

python --version
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python not installed or not in PATH" -ForegroundColor Red
    exit 1
}

if (-not $SkipInstall) {
    Write-Host ""
    Write-Host "[0/4] Installing dev dependencies..." -ForegroundColor Yellow
    python -m pip install --upgrade pip -q
    python -m pip install -e ".[dev]" -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARN: dependency install failed, continuing with existing env" -ForegroundColor Yellow
    }
}

python -m pytest --version
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pytest is unavailable; run python -m pip install -e .[dev]" -ForegroundColor Red
    exit 1
}

$env:QT_QPA_PLATFORM = "offscreen"
$env:CSAM_ALGORITHM_ENGINE = "python"
$env:CSAM_HMAC_SECRET = "csam_test_secret_2026"

# ---------------------------------------------------------------
# 1. Run each marker layer separately
# ---------------------------------------------------------------
if ($Quick) {
    $Layers = @("smoke", "regression")
} else {
    $Layers = @("smoke", "regression", "gui", "export", "mock", "performance", "stress")
}

$LayerResults = @{}
$TestPaths = @("repair_app/tests/", "repair_app/bridge/tests/")

Write-Host ""
Write-Host "[1/4] Running marker layers..." -ForegroundColor Yellow
foreach ($layer in $Layers) {
    Write-Host ""
    Write-Host "  --- $layer ---" -ForegroundColor Cyan
    $layerStart = Get-Date

    & python -m pytest -m $layer --tb=short -q --no-header `
        -p no:cacheprovider `
        --junitxml="test_result_$layer.xml" `
        $TestPaths 2>&1

    $exit = $LASTEXITCODE
    $dur = ((Get-Date) - $layerStart).TotalSeconds

    # exit code 5 = no tests collected (e.g. stress marker has no tests), treat as success
    $normalizedExit = if ($exit -eq 5) { 0 } else { $exit }
    $LayerResults[$layer] = @{ exit = $normalizedExit; duration = [math]::Round($dur, 2) }
}

# ---------------------------------------------------------------
# 2. Full test suite + coverage
# ---------------------------------------------------------------
Write-Host ""
Write-Host "[2/4] Running full test suite + coverage..." -ForegroundColor Yellow

$covArgs = @()
if (-not $NoCoverage) {
    $covArgs = @(
        "--cov=repair_app",
        "--cov-report=term-missing",
        "--cov-report=xml:coverage.xml",
        "--cov-report=html:htmlcov",
        "--cov-branch"
    )
}

$fullStart = Get-Date
& python -m pytest --tb=short -q --no-header `
    -p no:cacheprovider `
    --junitxml=test_result_full.xml `
    @covArgs $TestPaths 2>&1

$fullExit = $LASTEXITCODE
$fullDur  = ((Get-Date) - $fullStart).TotalSeconds

$FullStats = @{ exit = $fullExit; duration = [math]::Round($fullDur, 2) }

# ---------------------------------------------------------------
# 3. Summarize JSON (junitxml parsing delegated to Python)
# ---------------------------------------------------------------
Write-Host ""
Write-Host "[3/4] Summarizing results..." -ForegroundColor Yellow

$CoveragePct = $null
if ((-not $NoCoverage) -and (Test-Path "coverage.xml")) {
    [xml]$cov = Get-Content "coverage.xml" -Raw
    $lineRate = $cov.coverage."line-rate"
    if ($lineRate) { $CoveragePct = [math]::Round([double]$lineRate * 100, 2) }
}

$pyVer = (python --version 2>&1) -join " "

$Report = @{
    generated_at   = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    project        = "CSAM Repair"
    python_version = $pyVer
    coverage_pct   = $CoveragePct
    layers         = $LayerResults
    full_suite     = $FullStats
    junitxml_dir   = $ProjectRoot
    layer_names    = $Layers
}

$Report | ConvertTo-Json -Depth 5 | Set-Content -Path "test_results.json" -Encoding utf8
Write-Host "  -> test_results.json"

# ---------------------------------------------------------------
# 4. Generate TEST_REPORT.md (Python parses junitxml + writes report)
# ---------------------------------------------------------------
Write-Host ""
Write-Host "[4/4] Generating TEST_REPORT.md..." -ForegroundColor Yellow
python generate_test_report.py

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
$EndTime = Get-Date
$TotalDur = ((Get-Date) - $StartTime).TotalSeconds

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host " Done" -ForegroundColor Green
Write-Host " Total time: $([math]::Round($TotalDur, 1))s" -ForegroundColor Cyan
$statusColor = if ($fullExit -eq 0) { "Green" } else { "Red" }
$statusText  = if ($fullExit -eq 0) { "PASS" } else { "FAIL" }
Write-Host " Full status: $statusText" -ForegroundColor $statusColor
if ($CoveragePct) {
    $covColor = if ($CoveragePct -ge 60) { "Green" } else { "Red" }
    Write-Host " Coverage: $CoveragePct%" -ForegroundColor $covColor
}
Write-Host " Report: TEST_REPORT.md" -ForegroundColor Cyan
Write-Host " JSON:   test_results.json" -ForegroundColor Cyan
Write-Host " HTML:   htmlcov/index.html" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

if ($fullExit -ne 0) {
    Write-Host ""
    Write-Host "Note: some tests failed. See TEST_REPORT.md section 4." -ForegroundColor Yellow
}

$layerFailed = $false
foreach ($entry in $LayerResults.GetEnumerator()) {
    if ($entry.Value.exit -ne 0) {
        $layerFailed = $true
        break
    }
}
if ($fullExit -ne 0 -or $layerFailed) {
    exit 1
}
exit 0
