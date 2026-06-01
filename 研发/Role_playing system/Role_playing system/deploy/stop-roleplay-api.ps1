$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot ".roleplay-api.pid"

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host "Roleplay API is not running."
    exit 0
}

$rawPidLine = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $rawPidLine) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host "Removed empty PID file."
    exit 0
}

$rawPid = $rawPidLine.ToString().Trim()
$pidValue = 0
if (-not [int]::TryParse($rawPid, [ref]$pidValue)) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host "Removed invalid PID file."
    exit 0
}

$process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
if (-not $process) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host "Roleplay API process was already stopped."
    exit 0
}

Stop-Process -Id $pidValue -Force
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue

Write-Host ("Stopped Roleplay API (PID: {0})." -f $pidValue)
