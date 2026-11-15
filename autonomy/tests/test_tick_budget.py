# -*- coding: utf-8 -*-
"""Проверка бюджета тика: задача не стартует, если не влезает.

Запуск: python autonomy/tests/test_tick_budget.py
Без модели и без запуска команд: проверяется решение, а не исполнение.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from autonomy import runner  # noqa: E402


def task(minutes):
    return {"id": "T1", "time_limit_minutes": minutes}


def case_fits():
    now = 1000.0
    assert runner._fits_tick(task(20), deadline=now + 28 * 60, now=now)
    return "28 мин на 20-минутную задачу — влезает"


def case_not_fits():
    now = 1000.0
    assert not runner._fits_tick(task(20), deadline=now + 21 * 60, now=now)
    return "21 мин на 20-минутную — не влезает (нужен запас на фазы)"


def case_no_limit():
    assert runner._fits_tick({"id": "T1"}, deadline=time.time() + 60)
    return "без time_limit_minutes задача не откладывается"


def case_no_deadline():
    now = 1000.0
    assert runner._fits_tick(task(60), deadline=None, now=now)
    return "вне тика (нет дедлайна) задача не откладывается"


def case_defer_marks_and_returns():
    st = {"tasks": [{"id": "T1", "time_limit_minutes": 20, "status": "pending"}],
          "task": None, "phase": "EXECUTE"}
    drafted = []
    old_emit, old_sync = runner.events.emit, runner._sync_plan
    runner.events.emit = lambda *a, **k: drafted.append(k.get("task_id"))
    runner._sync_plan = lambda s: None
    try:
        runner._defer_task(st, st["tasks"][0], "тест", _Log())
    finally:
        runner.events.emit, runner._sync_plan = old_emit, old_sync
    assert st["tasks"][0]["status"] == "deferred"
    assert st["tasks"][0]["deferred_reason"] == "тест"
    assert st["phase"] == "EXECUTE" and st["task"] is None
    assert st["deferred"] == ["T1"] and drafted == ["T1"]
    return "откладывание пишет статус, причину и событие"


class _Log:
    def warn(self, m):
        pass

    def log(self, m):
        pass

    def error(self, m):
        pass


def main():
    cases = [case_fits, case_not_fits, case_no_limit, case_no_deadline,
             case_defer_marks_and_returns]
    for c in cases:
        print(f"ok: {c()} — {c.__name__}")
    print(f"итог: {len(cases)} проверок пройдено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
