param(
    [switch]$SkipMilvus,
    [switch]$SkipApi
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$milvusScript = Join-Path $PSScriptRoot "start-milvus.ps1"
$apiScript = Join-Path $PSScriptRoot "start-roleplay-api.ps1"

function Get-AppPort {
    $envFile = Join-Path $projectRoot ".env"
    if (-not (Test-Path -LiteralPath $envFile)) {
        return 8000
    }

    $line = Get-Content -LiteralPath $envFile |
        Where-Object { $_ -match '^\s*APP_PORT\s*=' } |
        Select-Object -First 1

    if (-not $line) {
        return 8000
    }

    $value = (($line -split "=", 2)[1]).Trim()
    $port = 0
    if ([int]::TryParse($value, [ref]$port) -and $port -gt 0) {
        return $port
    }

    return 8000
}

function Test-Health([int]$Port) {
    try {
        $response = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $Port) -TimeoutSec 3
        return $response.status -eq "healthy"
    } catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $projectRoot)) {
    throw "Project root not found: $projectRoot"
}

Write-Host "Deploying roleplay system..."

if (-not $SkipMilvus) {
    if (-not (Test-Path -LiteralPath $milvusScript)) {
        throw "Milvus start script not found: $milvusScript"
    }

    Write-Host "Starting Milvus stack..."
    & $milvusScript
}

if (-not $SkipApi) {
    if (-not (Test-Path -LiteralPath $apiScript)) {
        throw "API start script not found: $apiScript"
    }

    Write-Host "Starting API service..."
    & $apiScript
}

$port = Get-AppPort
if (Test-Health -Port $port) {
    Write-Host ""
    Write-Host "Deployment completed."
    Write-Host ("API: http://127.0.0.1:{0}/" -f $port)
    Write-Host ("Health: http://127.0.0.1:{0}/health" -f $port)
} elseif (-not $SkipApi) {
    Write-Host ""
    Write-Host "API health check did not pass yet."
    Write-Host ("Check logs under: {0}" -f (Join-Path $projectRoot "logs"))
}
