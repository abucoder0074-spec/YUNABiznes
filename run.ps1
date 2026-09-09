[CmdletBinding()]
param(
    [ValidateSet("Start", "Stop", "Restart")]
    [string]$Action = "Start",
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root "backend"
$EnvFile = Join-Path $Root ".env"
$VenvDir = Join-Path $Root ".venv"
$Python = Join-Path $VenvDir "Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
$StartupLog = Join-Path $LogDir "startup.log"
$BackendPidFile = Join-Path $LogDir "backend.pid"
$FrontendPidFile = Join-Path $LogDir "frontend.pid"
$BackendUrl = "http://127.0.0.1:8000"
$FrontendUrl = "http://127.0.0.1:5173"

function Write-StartupLog {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $StartupLog -Value $line
    Write-Host $Message
}

function Redact-Output {
    param([object[]]$Lines)
    $text = ($Lines | Out-String)
    return [regex]::Replace(
        $text,
        "postgresql\+asyncpg://([^:]+):([^@]+)@",
        'postgresql+asyncpg://$1:***@'
    )
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$FailureMessage
    )
    $output = & $FilePath @Arguments 2>&1
    $safeOutput = Redact-Output $output
    if ($safeOutput.Trim()) {
        Add-Content -LiteralPath $StartupLog -Value $safeOutput
    }
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
    return $output
}

function Test-ProcessOwned {
    param([int]$ProcessId, [string]$ExpectedPath)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }
    $commandLine = [string]$process.CommandLine
    return (
        $commandLine.IndexOf($ExpectedPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
        $commandLine.IndexOf("uvicorn app.main:app", [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
        $commandLine.IndexOf("npm run dev", [StringComparison]::OrdinalIgnoreCase) -ge 0
    )
}

function Get-ProcessTree {
    param([int]$ParentId)
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentId" -ErrorAction SilentlyContinue)
    $ids = @()
    foreach ($child in $children) {
        $ids += Get-ProcessTree -ParentId ([int]$child.ProcessId)
        $ids += [int]$child.ProcessId
    }
    return $ids
}

function Stop-OwnedProcess {
    param(
        [string]$PidFile,
        [string]$ExpectedPath,
        [string]$Label
    )
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return
    }
    $rawPid = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    $processId = 0
    if (-not [int]::TryParse($rawPid, [ref]$processId) -or $processId -le 0) {
        Write-StartupLog "Ignoring invalid $Label PID file."
        return
    }
    if (-not (Test-ProcessOwned -ProcessId $processId -ExpectedPath $ExpectedPath)) {
        Write-StartupLog "Skipped stale or unrelated $Label PID $processId."
        return
    }
    $tree = @(Get-ProcessTree -ParentId $processId)
    $tree += $processId
    foreach ($id in ($tree | Sort-Object -Descending -Unique)) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
    Write-StartupLog "Stopped YUNABiznes $Label process tree."
}

function Stop-Services {
    Stop-OwnedProcess -PidFile $FrontendPidFile -ExpectedPath (Join-Path $Root "frontend") -Label "frontend"
    Stop-OwnedProcess -PidFile $BackendPidFile -ExpectedPath $BackendDir -Label "backend"
}

function Assert-Prerequisites {
    if (-not (Test-Path -LiteralPath $BackendDir -PathType Container)) {
        throw "Backend directory not found: $BackendDir"
    }
    if (-not (Test-Path -LiteralPath $VenvDir -PathType Container) -or
        -not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "Python virtual environment not found at $VenvDir. Create it with: python -m venv .venv"
    }
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
        throw "Required .env file not found at $EnvFile. Copy .env.example and configure it."
    }
    $envText = Get-Content -LiteralPath $EnvFile -Raw
    $databaseLine = [regex]::Match($envText, "(?m)^\s*DATABASE_URL\s*=\s*(\S+)\s*$")
    if (-not $databaseLine.Success) {
        throw "DATABASE_URL is missing from $EnvFile."
    }
    $databaseUrl = $databaseLine.Groups[1].Value.Trim("'`"")
    if ($databaseUrl -notmatch "^postgresql\+asyncpg://[^:]+:[^@]+@localhost:5432/[^/?#\s]+$") {
        throw "DATABASE_URL must be a PostgreSQL asyncpg URL using localhost:5432."
    }
    if ($databaseUrl -match "change-me|your-password|password-here") {
        throw "DATABASE_URL still contains a placeholder password."
    }
    Write-StartupLog "Python virtual environment, .env, and DATABASE_URL format verified."
}

function Assert-Postgres {
    $portTest = Test-NetConnection -ComputerName "localhost" -Port 5432 -InformationLevel Quiet -WarningAction SilentlyContinue
    if (-not $portTest) {
        throw "PostgreSQL is not reachable at localhost:5432."
    }
    Write-StartupLog "PostgreSQL TCP availability verified at localhost:5432."

    Push-Location $BackendDir
    try {
        $pythonCode = @'
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import get_settings

async def main():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()

asyncio.run(main())
'@
        $output = & $Python -c $pythonCode 2>&1
        if ($LASTEXITCODE -ne 0) {
            $safeOutput = Redact-Output $output
            if ($safeOutput.Trim()) {
                Add-Content -LiteralPath $StartupLog -Value $safeOutput
            }
            throw "Database connectivity check failed. Verify PostgreSQL credentials and .env without sharing the password."
        }
    } finally {
        Pop-Location
    }
    Write-StartupLog "Database connectivity verified without exposing credentials."
}

function Invoke-Migrations {
    Push-Location $BackendDir
    try {
        Invoke-Checked -FilePath $Python -Arguments @("-m", "alembic", "upgrade", "head") -WorkingDirectory $BackendDir -FailureMessage "Alembic migrations failed. See logs\startup.log."
    } finally {
        Pop-Location
    }
    Write-StartupLog "Alembic migrations completed."
}

function Start-Backend {
    $stdout = Join-Path $LogDir "backend.log"
    $stderr = Join-Path $LogDir "backend.error.log"
    $process = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $BackendDir -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Set-Content -LiteralPath $BackendPidFile -Value $process.Id
    Write-StartupLog "Backend started with PID $($process.Id)."
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-WebRequest -Uri "$BackendUrl/health" -UseBasicParsing -TimeoutSec 2
            if ($health.StatusCode -eq 200) {
                return
            }
        } catch {
            if ($process.HasExited) {
                throw "Backend exited during startup. See logs\backend.error.log."
            }
        }
    }
    throw "Backend did not become healthy within 30 seconds. See logs\backend.error.log."
}

function Start-Frontend {
    $frontendDirs = @((Join-Path $Root "frontend"), $Root)
    $frontendDir = $null
    foreach ($candidate in $frontendDirs) {
        if (Test-Path -LiteralPath (Join-Path $candidate "package.json") -PathType Leaf) {
            $frontendDir = $candidate
            break
        }
    }
    if ($null -eq $frontendDir) {
        Write-StartupLog "No frontend package.json found; backend-only startup selected."
        return $false
    }
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $npm) {
        throw "Frontend exists but npm.cmd was not found on PATH."
    }
    $stdout = Join-Path $LogDir "frontend.log"
    $stderr = Join-Path $LogDir "frontend.error.log"
    $process = Start-Process -FilePath $npm.Source -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1") `
        -WorkingDirectory $frontendDir -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Set-Content -LiteralPath $FrontendPidFile -Value $process.Id
    Write-StartupLog "Frontend started with PID $($process.Id)."
    return $true
}

try {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    if (-not (Test-Path -LiteralPath $StartupLog)) {
        New-Item -ItemType File -Path $StartupLog -Force | Out-Null
    }
    Write-StartupLog "YUNABiznes $Action requested."

    if ($Action -eq "Stop") {
        Stop-Services
        Write-StartupLog "YUNABiznes services stopped."
        exit 0
    }
    if ($Action -eq "Restart") {
        Stop-Services
    }

    Assert-Prerequisites
    Assert-Postgres
    Invoke-Migrations
    $hasFrontend = Start-Frontend
    Start-Backend
    if (-not $NoBrowser) {
        $url = if ($hasFrontend) { $FrontendUrl } else { "$BackendUrl/docs" }
        Start-Process $url
        Write-StartupLog "Opened $url."
    }
    Write-StartupLog "YUNABiznes is running."
    exit 0
} catch {
    $message = $_.Exception.Message
    Write-StartupLog "ERROR: $message"
    exit 1
}
