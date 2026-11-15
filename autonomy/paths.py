# -*- coding: utf-8 -*-
"""Пути и песочница. Вне allowed_write_paths — только чтение."""
import fnmatch
import os
from pathlib import Path

from . import env

PROJECT_ROOT = env.PROJECT_ROOT
AUTONOMY_DIR = PROJECT_ROOT / "autonomy"
WORKSPACE = AUTONOMY_DIR / "workspace"
STATE_FILE = WORKSPACE / "STATE.json"
LOCK_FILE = WORKSPACE / ".lock"
NIGHT_LOG = WORKSPACE / "NIGHT_LOG.md"
RUNS_DIR = WORKSPACE / "runs"
TASKS_DIR = WORKSPACE / "tasks"
OUTBOX_DIR = WORKSPACE / "outbox"
CACHE_DIR = WORKSPACE / "cache"


def ensure_dirs():
    for d in (WORKSPACE, RUNS_DIR, TASKS_DIR, OUTBOX_DIR, CACHE_DIR,
              CACHE_DIR / "web"):
        d.mkdir(parents=True, exist_ok=True)


def resolve(p):
    return (PROJECT_ROOT / p).resolve() if not os.path.isabs(p) else Path(p).resolve()


def inside_project(p):
    try:
        resolve(p).relative_to(PROJECT_ROOT)
        return True
    except ValueError:
        return False


def writable(p, cfg):
    """Разрешена ли запись в путь по sandbox.allowed_write_paths."""
    if not inside_project(p):
        return False
    try:
        rel = str(resolve(p).relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return False
    for pat in cfg["sandbox"]["allowed_write_paths"]:
        if fnmatch.fnmatch(rel, pat) or rel == pat.rstrip("/*"):
            return True
    return False


def command_allowed(cmd, cfg):
    """True если команда не совпадает с denied-паттернами."""
    import re
    for pat in cfg["sandbox"]["denied_command_patterns"]:
        if re.search(pat, cmd, flags=re.IGNORECASE):
            return False
    return True
