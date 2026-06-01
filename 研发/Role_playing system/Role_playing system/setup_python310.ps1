$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envName = "python_3_10"
$envFile = Join-Path $projectRoot "environment.yml"

if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Environment file not found: $envFile"
}

Write-Host "Creating or updating Conda environment: $envName"
conda env update --name $envName --file $envFile --prune
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create or update Conda environment: $envName"
}

Write-Host ""
Write-Host "Environment ready."
Write-Host "Activate with:"
Write-Host "conda activate $envName"
Write-Host ""
Write-Host "Run the API with:"
Write-Host "python run.py serve"
