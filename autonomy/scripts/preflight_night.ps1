# Preflight before the night: compile, config sanity, state/plan/providers. Then start.
# ASCII-only: PS 5.1 reads UTF-8 without BOM as ANSI and garbles Cyrillic.
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path -LiteralPath $py)) { Write-Host "FAIL: venv python not found"; exit 1 }

Write-Host "[1/5] compile"
& $py -m py_compile .\autonomy\router.py .\autonomy\state.py .\autonomy\runner.py .\autonomy\providers.py .\autonomy\preflight.py
if ($LASTEXITCODE -ne 0) { Write-Host "FAIL: compile"; exit 1 }

Write-Host "[2/5] config and ladders"
& $py -c "import yaml,sys;c=yaml.safe_load(open('autonomy/config.yaml',encoding='utf-8'));r=c['roles'];p=c['providers'];m=[x for l in r.values() for x in l if x not in p];print('missing providers:',m);print('kimi cap:',c['night'].get('max_calls_per_provider'));print('executor:',r.get('executor'));print('role limits:',c.get('role_limits'));sys.exit(1 if m else 0)"
if ($LASTEXITCODE -ne 0) { Write-Host "FAIL: config references unknown provider"; exit 1 }

Write-Host "[3/5] preflight: state, plan, providers"
& $py -m autonomy.preflight
if ($LASTEXITCODE -ne 0) { Write-Host "FAIL: preflight (state/plan/providers)"; exit 1 }

Write-Host "[4/5] plan tasks and closes"
& $py -c "import yaml,sys;from pathlib import Path;p=Path('autonomy/workspace/night_plan.yaml');d=yaml.safe_load(p.read_text(encoding='utf-8')) if p.exists() else [];d=d or [];print('tasks:',[(t.get('id'),t.get('closes')) for t in d]);print('pending:',[t.get('id') for t in d if t.get('status')=='pending']);sys.exit(0)"
if ($LASTEXITCODE -ne 0) { Write-Host "FAIL: plan not readable"; exit 1 }

Write-Host "[5/5] state"
& $py -m autonomy.runner status

Write-Host "preflight ok, starting supervisor"
& (Join-Path $PSScriptRoot "start_night.ps1")
