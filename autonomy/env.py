# -*- coding: utf-8 -*-
"""Загрузка .env без внешних зависимостей. Секреты только из окружения (правило №9)."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_loaded = False


def load_env():
    """Минималистичный .env-парсер: KEY=VALUE, # — комментарий. Не перекрывает уже заданное env."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k and k not in os.environ:
            os.environ[k] = v


def get(name, default=None, required=False):
    load_env()
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Переменная окружения {name} не задана (см. .env.example)")
    return val
