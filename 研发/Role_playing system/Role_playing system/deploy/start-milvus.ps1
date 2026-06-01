$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $projectRoot "docker-compose.milvus.yml"
$projectName = "roleplay_milvus"

if (-not (Test-Path -LiteralPath $composeFile)) {
    throw "Compose file not found: $composeFile"
}

Write-Host "Checking Docker daemon..."
$null = docker.exe version 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Docker daemon is unavailable. Start Docker Desktop first, then rerun this script."
}

Write-Host "Starting Milvus stack..."
docker.exe compose -p $projectName -f $composeFile up -d
if ($LASTEXITCODE -ne 0) {
    throw "Failed to start Milvus stack."
}

Write-Host ""
Write-Host "Milvus services:"
docker.exe compose -p $projectName -f $composeFile ps

Write-Host ""
Write-Host "Endpoints:"
Write-Host "Milvus gRPC: localhost:19530"
Write-Host "Milvus health: http://localhost:9091/healthz"
Write-Host "MinIO console: http://localhost:9001"
Write-Host "Attu UI: http://localhost:8001"
