# -*- coding: utf-8 -*-
"""STATE.json — единственная правда о том, где мы. Атомарная запись.
Цикл-детектор: хэш (task_id, action, result_digest); 3 повтора подряд = STUCK."""
import hashlib
import json
import time

from . import paths

PHASES = ["IDLE", "PLAN", "EXECUTE", "VERIFY", "REVIEW", "MANAGER", "REPAIR", "REPORT", "DONE", "FAILED"]


def default_state():
    return {
        "night_id": time.strftime("%Y%m%d"),
        "phase": "IDLE",
        "task": None,
        "tasks": [],
        "iter": 0,
        "budget_used_usd": 0.0,
        "calls_by_provider": {},   # вызовов модели по провайдеру за ночь
        "history": [],          # [{h, n}] — хэш действия и сколько раз подряд
        "violations": [],       # попытки выйти за песочницу
        "last_error": None,
        "manager_context": None,  # завершённая задача для фазы MANAGER
        "goal_bump_night": None,  # ночь, за которую уже сдвинут счётчик прогресса
        "needs_human": None,      # причина остановки на решение владельца
        "lessons_admitted": [],   # уроки, принятые менеджером за ночь
        "updated": time.time(),
    }


def load():
    paths.ensure_dirs()
    if not paths.STATE_FILE.exists():
        return default_state()
    try:
        st = json.loads(paths.STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        st = default_state()
    base = default_state()
    for k, v in base.items():
        st.setdefault(k, v)
    # Новая ночь = новый календарный день И прошлая ночь завершена.
    # Незавершённая ночь продолжается, даже если дата сменилась в процессе.
    today = time.strftime("%Y%m%d")
    if st.get("night_id") != today:
        if st.get("phase") in ("DONE", "FAILED"):
            fresh = default_state()
            fresh["night_id"] = today
            return fresh
        # Незавершённый запуск остаётся тем же запуском после полуночи.
        # Ожидание квоты не должно обнулять деньги/попытки/лимиты Kimi.
    return st


def save(st):
    st["updated"] = time.time()
    tmp = paths.STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(paths.STATE_FILE)


def record_action(st, task_id, action, result_digest):
    """Возвращает True, если это уже застой (STUCK)."""
    h = hashlib.sha1(f"{task_id}|{action}|{result_digest}".encode("utf-8")).hexdigest()[:12]
    hist = st["history"]
    if hist and hist[-1]["h"] == h:
        hist[-1]["n"] += 1
    else:
        hist.append({"h": h, "n": 1})
    hist[:] = hist[-20:]  # не раздуваем
    stuck = hist[-1]["n"] >= 3
    return stuck
