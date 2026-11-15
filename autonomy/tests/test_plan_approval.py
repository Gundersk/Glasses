# -*- coding: utf-8 -*-
"""Одобрение критика привязано к содержимому плана, а не к факту запуска.

Запуск: python autonomy/tests/test_plan_approval.py
Смысл: план с диска выполняется без повторной критики только тогда, когда критик
одобрил ровно эти задачи. Правка задачи руками одобрение снимает, смена статуса —
нет (иначе каждая ночь платила бы за повторную критику).
"""
import json
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from autonomy import runner  # noqa: E402


def task(tid="T1", minutes=20, **kw):
    d = {"id": tid, "goal": "проверить что-то", "time_limit_minutes": minutes}
    d.update(kw)
    return d


def setup(d, tasks):
    plan = Path(d) / "night_plan.yaml"
    approval = Path(d) / "night_plan.approval.json"
    plan.write_text(yaml.safe_dump(tasks, allow_unicode=True, sort_keys=False), encoding="utf-8")
    runner.PLAN_FILE, runner.APPROVAL_FILE = plan, approval
    return plan, approval


def case_no_approval():
    with tempfile.TemporaryDirectory() as d:
        setup(d, [task()])
        assert runner._approval_ok() is False
    return "без файла одобрения план не выполняется"


def case_approved():
    with tempfile.TemporaryDirectory() as d:
        setup(d, [task()])
        runner._save_approval({"verdict": "approve", "raw_ok": True, "searches": []}, 1)
        assert runner._approval_ok() is True
    return "одобренный план принимается"


def case_revise_not_ok():
    with tempfile.TemporaryDirectory() as d:
        setup(d, [task()])
        runner._save_approval({"verdict": "revise", "searches": []}, 2)
        assert runner._approval_ok() is False
    return "revise не даёт выполнять план"


def case_edit_invalidates():
    with tempfile.TemporaryDirectory() as d:
        plan, _ = setup(d, [task()])
        runner._save_approval({"verdict": "approve", "raw_ok": True, "searches": []}, 1)
        assert runner._approval_ok() is True
        plan.write_text(yaml.safe_dump([task(minutes=45)], allow_unicode=True,
                                       sort_keys=False), encoding="utf-8")
        assert runner._approval_ok() is False
    return "правка задачи руками снимает одобрение"


def case_status_change_keeps():
    with tempfile.TemporaryDirectory() as d:
        plan, _ = setup(d, [task()])
        runner._save_approval({"verdict": "approve", "raw_ok": True, "searches": []}, 1)
        plan.write_text(yaml.safe_dump([task(status="done")], allow_unicode=True,
                                       sort_keys=False), encoding="utf-8")
        assert runner._approval_ok() is True
    return "смена статуса одобрение не снимает"


def case_broken_approval_file():
    with tempfile.TemporaryDirectory() as d:
        _, approval = setup(d, [task()])
        approval.write_text("{не json", encoding="utf-8")
        assert runner._approval_ok() is False
    return "битый файл одобрения не считается одобрением"


def main():
    cases = [case_no_approval, case_approved, case_revise_not_ok, case_edit_invalidates,
             case_status_change_keeps, case_broken_approval_file]
    for c in cases:
        print(f"ok: {c()} — {c.__name__}")
    print(f"итог: {len(cases)} проверок пройдено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
