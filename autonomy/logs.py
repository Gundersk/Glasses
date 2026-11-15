# -*- coding: utf-8 -*-
"""Подробное логирование: NIGHT_LOG.md (человекочитаемый) + runs/<ts>.log (сырой)."""
import time

from . import paths


class Logger:
    def __init__(self, run_name=None):
        paths.ensure_dirs()
        self.run_name = run_name or time.strftime("%Y%m%d-%H%M%S")
        self.raw = paths.RUNS_DIR / f"{self.run_name}.log"
        self.t0 = time.time()

    def _line(self, level, msg):
        el = time.time() - self.t0
        return f"{time.strftime('%H:%M:%S')} [+{el:6.1f}s] {level:5} {msg}"

    def log(self, msg, level="INFO"):
        line = self._line(level, msg)
        with open(self.raw, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._md(msg, level)
        print(line, flush=True)

    def _md(self, msg, level):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        prefix = {"INFO": "", "WARN": "⚠ ", "ERROR": "✖ ", "OK": "✔ ", "STEP": "**"}.get(level, "")
        suffix = "**" if level == "STEP" else ""
        with open(paths.NIGHT_LOG, "a", encoding="utf-8") as f:
            f.write(f"- `{stamp}` {prefix}{msg}{suffix}\n")

    def step(self, msg):
        self.log(msg, "STEP")

    def ok(self, msg):
        self.log(msg, "OK")

    def warn(self, msg):
        self.log(msg, "WARN")

    def error(self, msg):
        self.log(msg, "ERROR")
