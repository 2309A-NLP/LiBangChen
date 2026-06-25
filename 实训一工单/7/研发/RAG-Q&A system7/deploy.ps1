param(
    [ValidateSet("deploy", "start", "stop", "status", "restart")]
    [string]$Action = "deploy",
    [string]$PythonExe = "python",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8010,
    [int]$AppStartupTimeoutSec = 120,
    [int]$MilvusStartupTimeoutSec = 90,
    [switch]$SkipMilvus,
    [switch]$InstallDependencies,
    [switch]$StopMilvus
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $RepoRoot ".env"
$EnvExampleFile = Join-Path $RepoRoot ".env.example"
$LogsDir = Join-Path $RepoRoot "logs"
$StdoutLog = Join-Path $LogsDir "rag-api.out.log"
$StderrLog = Join-Path $LogsDir "rag-api.err.log"
$PidFile = Join-Path $RepoRoot ".rag-api.pid"
$ComposeFile = Join-Path $RepoRoot "milvus\docker-compose.milvus.v2.6.17.yml"

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-WarnLine {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Ensure-Command {
    param([string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Required command not found: $Name"
    }
    return $command.Source
}

function Ensure-EnvFile {
    if (Test-Path -LiteralPath $EnvFile) {
        return
    }
    if (-not (Test-Path -LiteralPath $EnvExampleFile)) {
        throw "Missing .env and .env.example."
    }
    Copy-Item -LiteralPath $EnvExampleFile -Destination $EnvFile
    Write-WarnLine "'.env' was missing and has been created from '.env.example'. Review model paths and API keys before production use."
}

function Test-TcpPortOpen {
    param(
        [string]$HostName,
        [int]$PortNumber,
        [int]$TimeoutMs = 1500
    )
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $asyncResult = $client.BeginConnect($HostName, $PortNumber, $null, $null)
        if (-not $asyncResult.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            return $false
        }
        $client.EndConnect($asyncResult)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Get-TrackedProcess {
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
    }
    catch {
        Write-WarnLine "PID file is invalid. Removing stale file."
        Remove-Item -LiteralPath $PidFile -Force
        return $null
    }
}

function Remove-TrackedProcessFile {
    if (Test-Path -LiteralPath $PidFile) {
        Remove-Item -LiteralPath $PidFile -Force
    }
}

function Test-ProcessRunning {
    param([int]$Pid)
    return $null -ne (Get-Process -Id $Pid -ErrorAction SilentlyContinue)
}

function Resolve-PythonPath {
    $pythonCommand = Get-Command $PythonExe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python executable not found: $PythonExe"
    }
    return $pythonCommand.Source
}

function Install-ProjectDependencies {
    param([string]$ResolvedPythonExe)
    Write-Info "Installing Python dependencies with $ResolvedPythonExe"
    & $ResolvedPythonExe -m pip install -r (Join-Path $RepoRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }
}

function Start-MilvusStack {
    if ($SkipMilvus) {
        Write-Info "Skipping Milvus startup."
        return
    }
    if (-not (Test-Path -LiteralPath $ComposeFile)) {
        throw "Milvus compose file not found: $ComposeFile"
    }
    Ensure-Command "docker" | Out-Null
    Write-Info "Starting Milvus stack from $ComposeFile"
    & docker compose -f $ComposeFile up -d
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start Milvus with docker compose."
    }
    $deadline = (Get-Date).AddSeconds($MilvusStartupTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPortOpen -HostName "127.0.0.1" -PortNumber 19530) {
            Write-Info "Milvus is reachable on 127.0.0.1:19530"
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Milvus did not become reachable within $MilvusStartupTimeoutSec seconds."
}

function Stop-MilvusStack {
    if (-not $StopMilvus) {
        return
    }
    if (-not (Test-Path -LiteralPath $ComposeFile)) {
        Write-WarnLine "Milvus compose file not found, skip docker compose down."
        return
    }
    Ensure-Command "docker" | Out-Null
    Write-Info "Stopping Milvus stack"
    & docker compose -f $ComposeFile down
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stop Milvus with docker compose."
    }
}

function Get-HealthUrl {
    param(
        [string]$HostName = $BindHost,
        [int]$PortNumber = $Port
    )
    return "http://${HostName}:$PortNumber/api/health"
}

function Wait-ForAppHealth {
    param([int]$ProcessId)
    $deadline = (Get-Date).AddSeconds($AppStartupTimeoutSec)
    $healthUrl = Get-HealthUrl
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-ProcessRunning -Pid $ProcessId)) {
            throw "Application process exited unexpectedly. Check $StdoutLog and $StderrLog"
        }
        try {
            $response = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 5
            if ($response.status -eq "ok") {
                Write-Info "Application is healthy at $healthUrl"
                return
            }
        }
        catch {
        }
        Start-Sleep -Seconds 2
    }
    throw "Application did not pass health check within $AppStartupTimeoutSec seconds. Check $StdoutLog and $StderrLog"
}

function Start-AppProcess {
    param([string]$ResolvedPythonExe)
    $tracked = Get-TrackedProcess
    if ($tracked -and (Test-ProcessRunning -Pid ([int]$tracked.pid))) {
        throw "Application is already running with PID $($tracked.pid). Use -Action status or -Action restart."
    }
    if ($tracked) {
        Remove-TrackedProcessFile
    }
    if (Test-TcpPortOpen -HostName $BindHost -PortNumber $Port) {
        throw "Port $Port on $BindHost is already in use."
    }

    Ensure-Directory $LogsDir
    Ensure-Directory (Join-Path $RepoRoot "data")
    Ensure-Directory (Join-Path $RepoRoot "data\source")
    Ensure-Directory (Join-Path $RepoRoot "data\processed")

    $previousHost = [Environment]::GetEnvironmentVariable("HOST", "Process")
    $previousPort = [Environment]::GetEnvironmentVariable("PORT", "Process")
    $previousReload = [Environment]::GetEnvironmentVariable("RELOAD", "Process")

    try {
        [Environment]::SetEnvironmentVariable("HOST", $BindHost, "Process")
        [Environment]::SetEnvironmentVariable("PORT", [string]$Port, "Process")
        [Environment]::SetEnvironmentVariable("RELOAD", "false", "Process")

        Write-Info "Starting API service on http://${BindHost}:$Port"
        $process = Start-Process `
            -FilePath $ResolvedPythonExe `
            -ArgumentList "run.py" `
            -WorkingDirectory $RepoRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $StdoutLog `
            -RedirectStandardError $StderrLog `
            -PassThru
    }
    finally {
        [Environment]::SetEnvironmentVariable("HOST", $previousHost, "Process")
        [Environment]::SetEnvironmentVariable("PORT", $previousPort, "Process")
        [Environment]::SetEnvironmentVariable("RELOAD", $previousReload, "Process")
    }

    @{
        pid = $process.Id
        host = $BindHost
        port = $Port
        python = $ResolvedPythonExe
        started_at = (Get-Date).ToString("s")
    } | ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding utf8

    Wait-ForAppHealth -ProcessId $process.Id
}

function Stop-AppProcess {
    $tracked = Get-TrackedProcess
    if (-not $tracked) {
        Write-Info "Application is not tracked as running."
        return
    }

    $pid = [int]$tracked.pid
    if (Test-ProcessRunning -Pid $pid) {
        Write-Info "Stopping application PID $pid"
        Stop-Process -Id $pid -Force
    }
    else {
        Write-WarnLine "Tracked PID $pid is not running."
    }

    Remove-TrackedProcessFile
}

function Show-Status {
    $tracked = Get-TrackedProcess
    $milvusUp = Test-TcpPortOpen -HostName "127.0.0.1" -PortNumber 19530
    $statusHost = $BindHost
    $statusPort = $Port
    if ($tracked) {
        if ($tracked.host) {
            $statusHost = [string]$tracked.host
        }
        if ($tracked.port) {
            $statusPort = [int]$tracked.port
        }
    }
    $healthUrl = Get-HealthUrl -HostName $statusHost -PortNumber $statusPort
    $appHealth = $null

    try {
        $appHealth = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 5
    }
    catch {
    }

    if ($tracked) {
        $isRunning = Test-ProcessRunning -Pid ([int]$tracked.pid)
        Write-Host "Tracked PID : $($tracked.pid)"
        Write-Host "Process Up  : $isRunning"
        Write-Host "App URL     : http://${statusHost}:$statusPort/"
    }
    else {
        Write-Host "Tracked PID : none"
        Write-Host "Process Up  : False"
        Write-Host "App URL     : http://${statusHost}:$statusPort/"
    }

    Write-Host "Health URL  : $healthUrl"
    Write-Host "Health OK   : $([bool]($appHealth -and $appHealth.status -eq 'ok'))"
    Write-Host "Milvus Up   : $milvusUp"
    Write-Host "Stdout Log  : $StdoutLog"
    Write-Host "Stderr Log  : $StderrLog"
}

Ensure-Directory $LogsDir

switch ($Action) {
    "deploy" {
        Ensure-EnvFile
        $resolvedPython = Resolve-PythonPath
        Install-ProjectDependencies -ResolvedPythonExe $resolvedPython
        Start-MilvusStack
        Start-AppProcess -ResolvedPythonExe $resolvedPython
        Show-Status
    }
    "start" {
        Ensure-EnvFile
        $resolvedPython = Resolve-PythonPath
        if ($InstallDependencies) {
            Install-ProjectDependencies -ResolvedPythonExe $resolvedPython
        }
        Start-MilvusStack
        Start-AppProcess -ResolvedPythonExe $resolvedPython
        Show-Status
    }
    "stop" {
        Stop-AppProcess
        Stop-MilvusStack
        Show-Status
    }
    "status" {
        Show-Status
    }
    "restart" {
        Stop-AppProcess
        $resolvedPython = Resolve-PythonPath
        if ($InstallDependencies) {
            Install-ProjectDependencies -ResolvedPythonExe $resolvedPython
        }
        Start-MilvusStack
        Start-AppProcess -ResolvedPythonExe $resolvedPython
        Show-Status
    }
}
