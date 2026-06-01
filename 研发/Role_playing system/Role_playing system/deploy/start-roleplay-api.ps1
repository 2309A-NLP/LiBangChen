$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$logsDir = Join-Path $projectRoot "logs"
$pidFile = Join-Path $projectRoot ".roleplay-api.pid"
$stdoutLog = Join-Path $logsDir "roleplay-api.out.log"
$stderrLog = Join-Path $logsDir "roleplay-api.err.log"
$defaultPython = "D:\Anaconda\envs\python_3_10\python.exe"

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

function Test-ApiHealthy([int]$Port) {
    try {
        $response = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $Port) -TimeoutSec 3
        return $response.status -eq "healthy"
    } catch {
        return $false
    }
}

function Get-ListeningPid([int]$Port) {
    $match = netstat -ano | Select-String (":{0}" -f $Port) | Select-Object -First 1
    if (-not $match) {
        return $null
    }

    $parts = ($match.Line -split "\s+") | Where-Object { $_ }
    if ($parts.Count -lt 5) {
        return $null
    }

    return $parts[-1]
}

function Get-ActiveProcessFromPidFile {
    if (-not (Test-Path -LiteralPath $pidFile)) {
        return $null
    }

    $rawPidLine = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $rawPidLine) {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    $rawPid = $rawPidLine.ToString().Trim()
    $pidValue = 0
    if (-not [int]::TryParse($rawPid, [ref]$pidValue)) {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if (-not $process) {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    return $process
}

if (-not (Test-Path -LiteralPath $projectRoot)) {
    throw "Project root not found: $projectRoot"
}

if (-not (Test-Path -LiteralPath $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

$pythonPath = $env:ROLEPLAY_PYTHON
if ([string]::IsNullOrWhiteSpace($pythonPath)) {
    if (Test-Path -LiteralPath $defaultPython) {
        $pythonPath = $defaultPython
    } else {
        $pythonPath = "python"
    }
}

$appPort = Get-AppPort
$existingProcess = Get-ActiveProcessFromPidFile
if ($existingProcess) {
    if (Test-ApiHealthy -Port $appPort) {
        Write-Host "Roleplay API is already running."
        Write-Host ("PID: {0}" -f $existingProcess.Id)
        Write-Host ("Local URL: http://127.0.0.1:{0}/" -f $appPort)
        Write-Host ("Logs: {0}" -f $stdoutLog)
        exit 0
    }

    Write-Host "Found stale API process. Stopping it first..."
    Stop-Process -Id $existingProcess.Id -Force
    Start-Sleep -Seconds 1
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $stdoutLog) {
    Remove-Item -LiteralPath $stdoutLog -Force
}
if (Test-Path -LiteralPath $stderrLog) {
    Remove-Item -LiteralPath $stderrLog -Force
}

Write-Host "Starting Roleplay API in background..."
$process = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList @(".\run.py") `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

Set-Content -LiteralPath $pidFile -Value $process.Id

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1

    if ($process.HasExited) {
        break
    }

    if (Test-ApiHealthy -Port $appPort) {
        $listeningPid = Get-ListeningPid -Port $appPort
        if ($listeningPid) {
            Set-Content -LiteralPath $pidFile -Value $listeningPid
        }
        $ready = $true
        break
    }
}

if (-not $ready) {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue

    Write-Host "Roleplay API failed to become ready."
    if (Test-Path -LiteralPath $stderrLog) {
        Write-Host ""
        Write-Host "Last stderr lines:"
        Get-Content -LiteralPath $stderrLog -Tail 30
    }
    exit 1
}

Write-Host "Roleplay API started."
Write-Host ("PID: {0}" -f ((Get-Content -LiteralPath $pidFile | Select-Object -First 1)))
Write-Host ("Local URL: http://127.0.0.1:{0}/" -f $appPort)
Write-Host ("Health: http://127.0.0.1:{0}/health" -f $appPort)
Write-Host ("Logs: {0}" -f $stdoutLog)
