# -*- coding: utf-8 -*-
"""Безопасный запуск команд: python-команды идут списком аргументов (без cmd.exe —
в пути проекта пробелы и кириллица), прочее — через shell с venv в PATH.

По таймауту убивается ВСЁ дерево процессов (taskkill /T /F на Windows), а не только
прямой потомок — иначе дочерний сервер, поднятый скриптом, осиротел бы и держал
порт/память. Это оркестраторский код, не команда модели: deny-список песочницы его
не касается.
"""
import os
import re
import shlex
import subprocess
import sys


def _kill_tree(pid):
    """Убить процесс и всех его потомков. Windows: taskkill /T /F. Иначе: kill."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=15)
        else:
            import signal
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        try:
            proc = _last_proc
            proc.kill()
        except Exception:
            pass


_last_proc = None


def _split_args(rest):
    """Разбор аргументов python-команды.

    POSIX-режим shlex на Windows съедает обратные слэши как escape, и путь
    `experiments\\file_stream_eval.py` превращается в `experimentsfile_stream_eval.py`
    (а `\\w` в regex — в `w`). Поэтому на Windows берём posix=False и снимаем
    внешние кавычки вручную.
    """
    if os.name != "nt":
        return shlex.split(rest)
    toks = shlex.split(rest, posix=False)
    argv = []
    for t in toks:
        if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
            t = t[1:-1].replace('\\"', '"')
        argv.append(t)
    return argv


def run_command(cmd, cwd, timeout=900):
    env = os.environ.copy()
    venv_bin = os.path.join(cwd, ".venv", "Scripts")
    if os.path.isdir(venv_bin):
        env["PATH"] = venv_bin + os.pathsep + env["PATH"]
    # Windows Python defaults stdout to cp1251. A child that prints Cyrillic or
    # an emoji dies with "'charmap' codec can't encode", and the task fails even
    # though the command is correct. Force UTF-8 on both sides.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    m = re.match(r"^\s*python(?:\d[\.\d]*)?\s+(.*)", cmd, flags=re.IGNORECASE)
    # stdin=DEVNULL: ни одна команда не сможет зависнуть на интерактивном
    # вопросе ("Y/n?", "Overwrite?") — она мгновенно упадёт с ошибкой,
    # и исполнитель повторит её с правильным неинтерактивным флагом.
    if m and not re.search(r"[|&<>^]", cmd):
        try:
            argv = _split_args(m.group(1))
            return _run([sys.executable] + argv, cwd, env, timeout, shell=False)
        except ValueError:
            pass  # неразбираемые кавычки — падаем в shell-ветку
    return _run(cmd, cwd, env, timeout, shell=True)


def _run(args, cwd, env, timeout, shell):
    global _last_proc
    proc = subprocess.Popen(args, cwd=cwd, env=env, shell=shell,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace",
                            stdin=subprocess.DEVNULL)
    _last_proc = proc
    try:
        out, err = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args, proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)          # гасим всё дерево, не только прямого сына
        try:
            out, err = proc.communicate(timeout=15)
        except Exception:
            out, err = "", ""
        return subprocess.CompletedProcess(
            args, -1, (out or "") + f"\n[TIMEOUT {timeout}s — дерево убито]",
            (err or "") + f"\n[timeout kill tree pid={proc.pid}]")
