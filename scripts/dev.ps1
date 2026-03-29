# NetScope — Development Startup Script
# Starts Redis, Daemon, Engine, and Gateway with auto-restart on crash.
# Run from the project root: powershell -ExecutionPolicy Bypass -File scripts\dev.ps1

param(
    [switch]$NoOllama
)

$Root     = Split-Path $PSScriptRoot -Parent
$Vendor   = Join-Path $Root "vendor"
$Redis    = Join-Path $Vendor "redis\redis-server.exe"
$RedisCli = Join-Path $Vendor "redis\redis-cli.exe"
$Python   = "python"

$Env:PYTHONPATH = "$Root;$Root\backend"
$Env:PYTHONUNBUFFERED = "1"

function Write-Step($msg) { Write-Host "[dev] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[dev] $msg" -ForegroundColor Green }
function Write-Err($msg)  { Write-Host "[dev] $msg" -ForegroundColor Red }

# ── Redis ─────────────────────────────────────────────────────────────────────
Write-Step "Starting Redis..."
$redisPing = & $RedisCli -p 6379 PING 2>$null
if ($redisPing -eq "PONG") {
    Write-Ok "Redis already running."
} else {
    Start-Process -FilePath $Redis -ArgumentList "--port 6379" `
        -WindowStyle Hidden -PassThru | Out-Null
    Start-Sleep 2
    Write-Ok "Redis started."
}

# ── Helper: run a process and auto-restart on crash ──────────────────────────
function Start-WithRestart {
    param($Name, $WorkDir, [string[]]$Args, $LogFile)
    $job = Start-Job -ScriptBlock {
        param($py, $wd, $a, $log, $env)
        $Env:PYTHONPATH    = $env.PYTHONPATH
        $Env:PYTHONUNBUFFERED = "1"
        while ($true) {
            $p = Start-Process -FilePath $py -ArgumentList $a `
                -WorkingDirectory $wd -NoNewWindow -PassThru `
                -RedirectStandardOutput $log -RedirectStandardError $log
            Write-Output "[$using:Name] started PID $($p.Id)"
            $p.WaitForExit()
            $code = $p.ExitCode
            Write-Output "[$using:Name] exited ($code) — restarting in 2s..."
            Start-Sleep 2
        }
    } -ArgumentList $Python, $WorkDir, $Args, $LogFile, @{PYTHONPATH=$Env:PYTHONPATH}
    return $job
}

# ── Daemon ────────────────────────────────────────────────────────────────────
Write-Step "Starting Daemon..."
$daemonLog = Join-Path $Root "daemon.log"
$daemonJob = Start-WithRestart "daemon" `
    (Join-Path $Root "daemon") `
    @((Join-Path $Root "daemon\main.py")) `
    $daemonLog
Start-Sleep 2
Write-Ok "Daemon started (auto-restart enabled)."

# ── Engine ────────────────────────────────────────────────────────────────────
Write-Step "Starting Engine..."
$engineLog = Join-Path $Root "engine.log"
$engineJob = Start-WithRestart "engine" `
    (Join-Path $Root "engine") `
    @((Join-Path $Root "engine\main.py")) `
    $engineLog
Start-Sleep 2
Write-Ok "Engine started (auto-restart enabled)."

# ── Gateway ───────────────────────────────────────────────────────────────────
Write-Step "Starting Gateway on port 8000..."
$gatewayLog = Join-Path $Root "gateway.log"
$gatewayJob = Start-WithRestart "gateway" `
    (Join-Path $Root "gateway") `
    @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000") `
    $gatewayLog

# Wait for gateway health
Write-Step "Waiting for gateway..."
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 1
        if ($r.StatusCode -eq 200) { break }
    } catch {}
    Start-Sleep 1
}
Write-Ok "Gateway ready at http://127.0.0.1:8000"

Write-Host ""
Write-Ok "All processes running. Ctrl+C to stop."
Write-Host "  Gateway : http://127.0.0.1:8000" -ForegroundColor Yellow
Write-Host "  Frontend: cd frontend && npm run dev" -ForegroundColor Yellow
Write-Host ""

# Keep script alive, relay job output
try {
    while ($true) {
        foreach ($job in @($daemonJob, $engineJob, $gatewayJob)) {
            Receive-Job $job -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
        }
        Start-Sleep 2
    }
} finally {
    Write-Step "Shutting down..."
    # Signal daemon to stop via Redis pub/sub
    try { & $RedisCli -p 6379 PUBLISH "ns:daemon.shutdown" "1" | Out-Null } catch {}
    Stop-Job $daemonJob, $engineJob, $gatewayJob -ErrorAction SilentlyContinue
    Remove-Job $daemonJob, $engineJob, $gatewayJob -Force -ErrorAction SilentlyContinue
    Write-Ok "Done."
}
