# Stop the manual night supervisor. Without -Force it asks the loop to stop
# after the current tick. With -Force it kills the tick tree immediately.
param([switch]$Force)
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ws = Join-Path $root "autonomy\workspace"
$pidf = Join-Path $ws "supervisor.pid"
$lock = Join-Path $ws ".lock"
$stopf = Join-Path $ws "STOP"

New-Item -ItemType Directory -Force -Path $ws | Out-Null
New-Item -ItemType File -Force -Path $stopf | Out-Null

$targets = @()
if (Test-Path -LiteralPath $pidf) {
    $v = Get-Content -LiteralPath $pidf -ErrorAction SilentlyContinue
    if ($v) { $targets += [int]$v }
}
if (Test-Path -LiteralPath $lock) {
    $d = Get-Content -LiteralPath $lock -Raw | ConvertFrom-Json
    if ($d.pid) { $targets += [int]$d.pid }
}
$targets = $targets | Select-Object -Unique
$alive = @($targets | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })

if (-not $alive) {
    Remove-Item -LiteralPath $stopf -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $pidf -ErrorAction SilentlyContinue
    Write-Host "Nothing is running."
    exit 0
}
$targets = $alive

if ($Force) {
    foreach ($id in $targets) {
        if (Get-Process -Id $id -ErrorAction SilentlyContinue) {
            & taskkill /PID $id /T /F | Out-Null
            Write-Host "Killed pid $id and its children."
        }
    }
    Remove-Item -LiteralPath $pidf -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stopf -ErrorAction SilentlyContinue
    exit 0
}

for ($i = 0; $i -lt 20; $i++) {
    $alive = $false
    foreach ($id in $targets) { if (Get-Process -Id $id -ErrorAction SilentlyContinue) { $alive = $true } }
    if (-not $alive) { break }
    Start-Sleep -Seconds 1
}

if (Get-Process -Id $targets[0] -ErrorAction SilentlyContinue) {
    Write-Host "Stop requested. The current tick can take several minutes; use -Force to stop now."
} else {
    Remove-Item -LiteralPath $pidf -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stopf -ErrorAction SilentlyContinue
    Write-Host "Stopped."
}
