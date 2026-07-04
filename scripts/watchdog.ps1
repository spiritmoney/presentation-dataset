# Watchdog for Windows — restarts supervisor if it crashes before goal is reached.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/watchdog.ps1

$ErrorActionPreference = "Continue"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectDir

$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$CheckInterval = if ($env:CHECK_INTERVAL) { [int]$env:CHECK_INTERVAL } else { 30 }
$MaxRestartsPerHour = if ($env:MAX_RESTARTS_PER_HOUR) { [int]$env:MAX_RESTARTS_PER_HOUR } else { 120 }

$LogDir = "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$restarts = 0
$hourStart = Get-Date

function Log($msg) {
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    Write-Host "[$ts] $msg"
}

function Test-GoalReached {
    & $Python -c @"
from pathlib import Path
from src.supervisor.state import StateManager, RunStatus
from src.config import Settings
s = Settings()
m = StateManager(s.data_dir / 'state' / 'pipeline_state.json')
state = m.load()
if state and state.status.value == 'goal_reached':
    exit(0)
from src.supervisor.progress import count_qualified_files
count = count_qualified_files(s.data_dir / 'qualified')
target = state.target_count if state else 500000
exit(0 if count >= target else 1)
"@ 2>$null
    return $LASTEXITCODE -eq 0
}

while ($true) {
    if (Test-GoalReached) {
        Log "Goal reached — watchdog exiting."
        exit 0
    }

    if (((Get-Date) - $hourStart).TotalHours -ge 1) {
        $restarts = 0
        $hourStart = Get-Date
    }

    if ($restarts -ge $MaxRestartsPerHour) {
        Log "ERROR: Too many restarts ($restarts/hour). Waiting 5 minutes."
        Start-Sleep -Seconds 300
        $restarts = 0
        $hourStart = Get-Date
        continue
    }

    Log "Starting pipeline (restart #$restarts)..."
    & $Python -m scripts.run_pipeline run 2>&1 | Tee-Object -FilePath "$LogDir\supervisor.log" -Append
    if ($LASTEXITCODE -eq 0 -and (Test-GoalReached)) {
        Log "Goal reached after supervisor exit."
        exit 0
    }

    $restarts++
    Log "Supervisor exited before goal. Restarting in ${CheckInterval}s..."
    Start-Sleep -Seconds $CheckInterval
}
