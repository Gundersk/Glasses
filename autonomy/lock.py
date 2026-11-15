# -*- coding: utf-8 -*-
"""Лок + heartbeat. Если процесс жив — новый тик тихо выходит.
Лок снимается, если heartbeat старый (процесс умер) или PID не существует."""
import json
import os
import time

from . import paths


def _write_lock(handle):
    handle.write(json.dumps({
        "pid": os.getpid(),
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
    }))
    handle.flush()


def try_acquire(cfg):
    """Возвращает открытый handle лока, либо None, если кто-то живой держит."""
    paths.ensure_dirs()
    stale_min = cfg["night"].get("stale_lock_minutes", 20)

    # Проверка существующего лока до захвата.
    if paths.LOCK_FILE.exists():
        try:
            data = json.loads(paths.LOCK_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        age_min = (time.time() - data.get("ts", 0)) / 60
        pid_alive = _pid_alive(data.get("pid"))
        if pid_alive and age_min < stale_min:
            return None  # живой процесс идёт — не мешаем
        # лок мёртвый или устаревший — снимаем
        try:
            paths.LOCK_FILE.unlink()
        except OSError:
            pass

    # Эксклюзивное создание: O_EXCL даёт атомарность на одной машине.
    try:
        fd = os.open(str(paths.LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    handle = os.fdopen(fd, "w", encoding="utf-8")
    _write_lock(handle)
    return handle


def heartbeat(handle):
    try:
        handle.seek(0)
        handle.truncate(0)
        _write_lock(handle)
    except Exception:
        pass


def release(handle):
    try:
        handle.close()
    except Exception:
        pass
    try:
        paths.LOCK_FILE.unlink()
    except OSError:
        pass


def _pid_alive(pid):
    if not pid:
        return False
    # Windows: проверяем существование процесса по PID.
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        kernel32.CloseHandle(h)
        return bool(ok) and code.value == still_active
    except Exception:
        return True  # не смогли проверить — считаем живым (консервативно)
