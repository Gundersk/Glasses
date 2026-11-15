# Start the night supervisor on demand. No scheduled task is created.
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$loop = Join-Path $PSScriptRoot "run_loop.ps1"
$pidf = Join-Path $root "autonomy\workspace\supervisor.pid"
$lock = Join-Path $root "autonomy\workspace\.lock"

if (Test-Path -LiteralPath $pidf) {
    $old = Get-Content -LiteralPath $pidf -ErrorAction SilentlyContinue
    if ($old -and (Get-Process -Id ([int]$old) -ErrorAction SilentlyContinue)) {
        Write-Host "Already running: supervisor pid $old"
        exit 0
    }
}

if (Test-Path -LiteralPath $lock) {
    $data = Get-Content -LiteralPath $lock -Raw | ConvertFrom-Json
    if ($data.pid -and (Get-Process -Id ([int]$data.pid) -ErrorAction SilentlyContinue)) {
        Write-Host "A tick is already running: pid $($data.pid). Use stop_night.ps1 first."
        exit 1
    }
}

$p = Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$loop`"" `
    -WindowStyle Hidden -PassThru
Write-Host "Started supervisor pid $($p.Id). Log: autonomy\workspace\scheduler.log"
