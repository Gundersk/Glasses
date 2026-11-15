# Manual night supervisor. Started only by the user, never by Task Scheduler.
# Runs runner ticks back to back until DONE, STOP file, or MaxTicks.
param([int]$IntervalSec = 15, [int]$MaxTicks = 200)
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
# Same reason as in shellutil.py: cp1251 console kills a child that prints Cyrillic.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$ws = Join-Path $root "autonomy\workspace"
$logf = Join-Path $ws "scheduler.log"
$pidf = Join-Path $ws "supervisor.pid"
$stopf = Join-Path $ws "STOP"

New-Item -ItemType Directory -Force -Path $ws | Out-Null
Set-Content -LiteralPath $pidf -Value $PID -Encoding ascii
Remove-Item -LiteralPath $stopf -ErrorAction SilentlyContinue
"[$(Get-Date -Format s)] supervisor start pid=$PID" | Out-File -Append -Encoding utf8 $logf

$fail = 0
for ($i = 1; $i -le $MaxTicks; $i++) {
    if (Test-Path -LiteralPath $stopf) {
        "[$(Get-Date -Format s)] stop requested before tick $i" | Out-File -Append -Encoding utf8 $logf
        break
    }
    & $py -m autonomy.runner tick 2>&1 | Out-File -Append -Encoding utf8 $logf
    $code = $LASTEXITCODE
    $status = (& $py -m autonomy.runner status 2>&1 | Out-String)
    "[$(Get-Date -Format s)] tick $i exit=$code" | Out-File -Append -Encoding utf8 $logf
    if ($status -match '"phase"\s*:\s*"DONE"') {
        "[$(Get-Date -Format s)] phase DONE" | Out-File -Append -Encoding utf8 $logf
        break
    }
    if ($code -ne 0) {
        $fail++
        if ($fail -ge 3) {
            "[$(Get-Date -Format s)] three failed ticks, stop" | Out-File -Append -Encoding utf8 $logf
            break
        }
    } else {
        $fail = 0
    }
    Start-Sleep -Seconds $IntervalSec
}

Remove-Item -LiteralPath $pidf -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stopf -ErrorAction SilentlyContinue
"[$(Get-Date -Format s)] supervisor exit" | Out-File -Append -Encoding utf8 $logf
