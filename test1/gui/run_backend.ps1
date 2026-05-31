# Launch the GUI backend on the spike venv interpreter (the one with altium_monkey).
# ALWAYS start the backend with this script — a bare `python app.py` on system
# Python can't import altium_monkey and every build silently fails (A2).
#
#   pwsh test1/gui/run_backend.ps1
#
$ErrorActionPreference = "Stop"
$venv = "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $here "backend"

if (-not (Test-Path $venv)) {
    Write-Error "venv python not found at $venv — adjust the path in run_backend.ps1"
    exit 1
}

# Stop any backend already bound to :8765 so we never run two (the duplicate-bind
# bug where a stale system-Python instance keeps the port).
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*app.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800

Write-Host "Starting backend on $venv ..."
& $venv (Join-Path $backend "app.py")
