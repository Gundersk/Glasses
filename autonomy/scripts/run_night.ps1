# Night tick for the autonomous system (ASCII-only: PS 5.1 reads UTF-8 w/o BOM as ANSI).
# Safe to run often: a live process -> silent exit; dead lock -> taken over.
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
# Same reason as in shellutil.py: cp1251 console kills a child that prints Cyrillic.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$logf = Join-Path $root "autonomy\workspace\scheduler.log"
& $py -m autonomy.runner tick 2>&1 | Out-File -Append -Encoding utf8 $logf
exit $LASTEXITCODE
