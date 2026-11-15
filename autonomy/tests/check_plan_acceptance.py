# -*- coding: utf-8 -*-
"""Проверка синтаксиса acceptance-команд в night_plan*.yaml без их выполнения.

Зачем: длинные python -c в YAML ломаются незаметно, и ночь падает на проверке,
которая сама неверна. compile() ловит это за секунды и ничего не запускает.

Запуск: python autonomy/tests/check_plan_acceptance.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

PLANS = ["autonomy/workspace/night_plan.yaml",
         "autonomy/workspace/night_plan.next.yaml"]


def inner_python(cmd):
    c = cmd.strip()
    if not c.startswith("python -c"):
        return None
    body = c[len("python -c"):].strip()
    if body.startswith('"') and body.endswith('"'):
        body = body[1:-1]
    return body


def main():
    bad = 0
    for rel in PLANS:
        fp = ROOT / rel
        if not fp.exists():
            print(f"нет файла {rel}")
            continue
        tasks = yaml.safe_load(fp.read_text(encoding="utf-8")) or []
        for t in tasks:
            for i, a in enumerate(t.get("acceptance") or []):
                if not isinstance(a, dict) or "command" not in a:
                    continue
                body = inner_python(a["command"])
                if body is None:
                    continue
                try:
                    compile(body, f"{rel}:{t['id']}:acc{i}", "exec")
                except SyntaxError as e:
                    bad += 1
                    print(f"СИНТАКСИС: {rel} / {t['id']} / проверка {i}: {e}")
                else:
                    print(f"ok: {t['id']} проверка {i}")
    print("итог:", "всё компилируется" if not bad else f"ошибок {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
