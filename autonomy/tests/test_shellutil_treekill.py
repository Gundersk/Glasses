# -*- coding: utf-8 -*-
"""Тест shellutil: обычный путь + 'таймаут убивает всё дерево' (внук не осиротевает)."""
import subprocess
import sys
import time

sys.path.insert(0, ".")
from autonomy import shellutil

# 1) обычный путь
r = shellutil.run_command('python -c "print(\'normal ok\')"', ".", 30)
print("normal: rc=", r.returncode, "|", (r.stdout or "").strip())

# 2) таймаут с внуком: сын поднимает ping на 60 c и сам спит; убиваем на 6-й секунде
child = ("import subprocess,time;"
         "p=subprocess.Popen(['ping','-n','60','127.0.0.1']);"
         "print('GRANDPID',p.pid,flush=True);"
         "time.sleep(120)")
t0 = time.time()
r = shellutil.run_command('python -c "' + child + '"', ".", 6)
dt = time.time() - t0
gp = [l for l in (r.stdout or "").splitlines() if l.startswith("GRANDPID")]
gpid = gp[0].split()[1] if gp else None
print(f"timeout path: rc={r.returncode} за {dt:.1f}s | grandchild pid={gpid}")
print("stdout tail:", (r.stdout or "").strip()[-120:].replace("\n", " / "))
time.sleep(2)
if gpid:
    cmd = "if (Get-Process -Id " + gpid + " -ErrorAction SilentlyContinue) {'ALIVE'} else {'DEAD'}"
    chk = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True)
    verdict = chk.stdout.decode("cp866", "ignore").strip()
    print("внук после таймаута:", verdict)
    assert verdict == "DEAD", "ВНУК ОСИРОТЕЛ — фикс не работает!"
    print("TREE-KILL OK: дерево процессов умирает по таймауту")
