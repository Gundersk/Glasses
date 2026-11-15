# -*- coding: utf-8 -*-
"""Манифест-дифф без git: снимок sha256 по allowed-корням, сравнение до/после.
Ловит выход за песочницу (кто тронул не то) и пустые прогоны (ничего не изменилось)."""
import hashlib
import os
from pathlib import Path

from . import paths

SKIP_DIRS = {".venv", "__pycache__", ".git", "cache", "runs", "node_modules", ".cache"}
SKIP_EXT = {".wav", ".mp3", ".flac", ".mp4", ".mkv", ".mov", ".onnx", ".bin",
            ".pt", ".pth", ".ckpt", ".safetensors", ".gguf"}


def _roots(cfg):
    # Помимо рабочих корней следим за договором/конфигом, иначе изменение
    # AGENTS.md командой было бы невидимо для проверки выхода за scope.
    roots = {"AGENTS.md", "ROADMAP.md", "PROJECT.md", "opencode.json", ".opencode"}
    for pat in cfg["sandbox"]["allowed_write_paths"]:
        top = pat.split("/")[0].rstrip("*")
        if top:
            roots.add(top)
    return roots


def snapshot(cfg):
    """{relpath: (sha256, size, mtime)} по allowed-корням."""
    files = {}
    for root in _roots(cfg):
        base = paths.PROJECT_ROOT / root
        if not base.exists():
            continue
        if base.is_file():
            st = base.stat()
            files[root] = (hashlib.sha256(base.read_bytes()).hexdigest(),
                           st.st_size, round(st.st_mtime, 3))
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                # The orchestrator updates this exact heartbeat independently of executor output.
                if Path(dirpath) / fn == paths.PROJECT_ROOT / "autonomy" / "workspace" / ".lock":
                    continue
                # Account quota bookkeeping is orchestration, not executor output.
                if (Path(dirpath) == paths.AUTONOMY_DIR / "workspace"
                        and fn in {"subscription.sqlite3", "subscription.sqlite3-journal",
                                   "subscription.sqlite3-wal", "subscription.sqlite3-shm"}):
                    continue
                if Path(fn).suffix.lower() in SKIP_EXT:
                    continue
                full = Path(dirpath) / fn
                try:
                    st = full.stat()
                    if st.st_size > 8 * 1024 * 1024:
                        h = "big"
                    else:
                        h = hashlib.sha256(full.read_bytes()).hexdigest()
                    rel = str(full.relative_to(paths.PROJECT_ROOT)).replace("\\", "/")
                    files[rel] = (h, st.st_size, round(st.st_mtime, 3))
                except OSError:
                    continue
    return files


def diff(before, after):
    added = sorted(k for k in after if k not in before)
    deleted = sorted(k for k in before if k not in after)
    modified = sorted(k for k in after if k in before and after[k][0] != before[k][0])
    return {"added": added, "modified": modified, "deleted": deleted}


def any_change(d):
    return bool(d["added"] or d["modified"] or d["deleted"])


def summary(d, limit=40):
    parts = []
    for kind in ("added", "modified", "deleted"):
        items = d[kind]
        if items:
            shown = items[:limit]
            parts.append(f"{kind}: {len(items)} — " + ", ".join(shown))
    return "\n".join(parts) if parts else "(без изменений)"
