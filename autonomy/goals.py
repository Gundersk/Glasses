# -*- coding: utf-8 -*-
"""Реестр целей: машинная проекция ROADMAP и локальных целей.

Зачем: планировщик раньше видел только обрезанный ROADMAP и прошлый отчёт,
а `docs/local-goals.md` и `docs/roadmap-changes.md` не читал вообще. Теперь
цель — сущность с id, статусом и доказательствами, и задача без цели не
ставится.

Инварианты:
- доказательства добавляет код по verify.json, а не модель;
- `done` нельзя поставить без существующих файлов-доказательств;
- счётчик ночей без прогресса хранится здесь и переживает перезапуск.
"""
import time
from pathlib import Path

import yaml

from . import paths

GOALS_FILE = paths.AUTONOMY_DIR / "goals.yaml"
STATUSES = ("open", "done", "blocked")
TERMINAL = ("done",)
# Цель, которая меряет качество, обязана назвать внешний ориентир: иначе ночь
# закроет её честным, но несопоставимым числом (поймано 12.11.2026 на WER).
METRIC_HINTS = ("wer", "der", "задержк", "латентн", "точность")


class GoalsError(Exception):
    pass


def load(path=None):
    fp = Path(path) if path else GOALS_FILE
    if not fp.exists():
        raise GoalsError(f"нет файла целей {fp} — планировать не по чему")
    try:
        data = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise GoalsError(f"{fp.name}: некорректный YAML: {e}")
    errors = validate(data)
    if errors:
        raise GoalsError("; ".join(errors))
    return data


def save(g, path=None):
    fp = Path(path) if path else GOALS_FILE
    tmp = fp.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(g, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(fp)
    return fp


def validate(g):
    errs = []
    if not isinstance(g, dict):
        return ["верхний уровень должен быть словарём"]
    glob = g.get("global") or {}
    if not str(glob.get("statement") or "").strip():
        errs.append("global.statement пуст")
    if not str(glob.get("deadline") or "").strip():
        errs.append("global.deadline пуст")
    stage = g.get("stage") or {}
    for key in ("id", "title", "deadline", "status"):
        if not str(stage.get(key) or "").strip():
            errs.append(f"stage.{key} пуст")
    targets = (stage.get("exit_criteria") or []) + (g.get("local_goals") or [])
    if not targets:
        errs.append("нет ни одного критерия этапа и ни одной локальной цели")
    seen = set()
    for t in targets:
        tid = str(t.get("id") or "").strip()
        if not tid:
            errs.append("цель без id")
            continue
        if tid in seen:
            errs.append(f"повтор id цели: {tid}")
        seen.add(tid)
        if not str(t.get("text") or "").strip():
            errs.append(f"{tid}: пустой text")
        if t.get("status") not in STATUSES:
            errs.append(f"{tid}: status={t.get('status')!r}, ждём {STATUSES}")
        ev = t.get("evidence") or []
        if not isinstance(ev, list):
            errs.append(f"{tid}: evidence должен быть списком")
        errs.extend(_benchmark_errors(t, tid))
    policy = g.get("policy") or {}
    if not isinstance(policy, dict):
        errs.append("policy должен быть словарём")
    return errs


def _benchmark_errors(t, tid):
    """Цель про качество/задержку должна назвать внешний ориентир или его отсутствие."""
    text = str(t.get("text") or "").lower()
    if not any(h in text for h in METRIC_HINTS):
        return []
    bm = str(t.get("benchmark") or "").strip()
    if not bm:
        return [f"{tid}: цель про качество/задержку без benchmark — укажи ссылку "
                f"на docs/benchmarks.md или 'none' с benchmark_reason"]
    if bm.lower() == "none":
        if not str(t.get("benchmark_reason") or "").strip():
            return [f"{tid}: benchmark: none требует непустой benchmark_reason"]
        return []
    rel = bm.split("#")[0].strip()
    try:
        exists = paths.resolve(rel).exists()
    except OSError:
        exists = False
    if not exists:
        return [f"{tid}: benchmark ссылается на отсутствующий файл {rel}"]
    return []


def _raw_targets(g):
    """Ссылки на сами словари целей (для изменения статусов и доказательств)."""
    return (list((g.get("stage") or {}).get("exit_criteria") or [])
            + list(g.get("local_goals") or []))


def targets(g):
    """Все цели этапа и локальные — плоским списком копий (для чтения)."""
    out = []
    for t in (g.get("stage") or {}).get("exit_criteria") or []:
        x = dict(t)
        x["kind"] = "stage"
        out.append(x)
    for t in g.get("local_goals") or []:
        x = dict(t)
        x["kind"] = "local"
        out.append(x)
    return out


def target(g, goal_id):
    """Исходный словарь цели, чтобы изменения сохранялись, а не терялись в копии."""
    for t in _raw_targets(g):
        if t.get("id") == goal_id:
            return t
    return None


def open_targets(g):
    return [t for t in targets(g) if t.get("status") == "open"]


def goal_ids(g):
    return {t["id"] for t in targets(g)}


def max_no_progress(g):
    return int((g.get("policy") or {}).get("max_nights_without_progress", 3))


def summary(g, limit=2800):
    """Текст для планировщика: глобальная цель, этап и открытые цели."""
    glob = g.get("global") or {}
    stage = g.get("stage") or {}
    lines = [
        f"ГЛОБАЛЬНАЯ ЦЕЛЬ: {glob.get('statement')} (до {glob.get('deadline')})",
        f"ЭТАП: {stage.get('id')} — {stage.get('title')} (до {stage.get('deadline')})",
        "ОТКРЫТЫЕ ЦЕЛИ (задача обязана ссылаться на goal_id одной из них):",
    ]
    for t in targets(g):
        if t.get("status") != "open":
            continue
        ev = t.get("evidence") or []
        misses = int(t.get("nights_without_progress", 0) or 0)
        lines.append(f"- {t['id']} [{t.get('kind')}]: {t.get('text')} "
                     f"(доказательств: {len(ev)}; ночей без прогресса: {misses})")
        if t.get("blocked_reason"):
            lines.append(f"  блокер: {t['blocked_reason']}")
        bm = str(t.get("benchmark") or "").strip()
        if bm:
            mark = f"  ориентир: {bm}"
            if bm.lower() == "none":
                mark += f" (нет ориентира: {t.get('benchmark_reason')})"
            lines.append(mark)
    if len(lines) == 3:
        lines.append("- открытых целей нет")
    txt = "\n".join(lines)
    return txt[:limit]


def evidence_from_task(task, verdict):
    """Какие артефакты задача реально предъявила. Только при verify=pass."""
    if not verdict or not verdict.get("pass"):
        return []
    out = []
    for c in task.get("acceptance") or []:
        if isinstance(c, dict) and "file_exists" in c:
            p = str(c["file_exists"])
            try:
                if paths.resolve(p).exists():
                    out.append(p)
            except OSError:
                continue
    return out


def record_evidence(g, goal_id, evidence, night_id):
    """Добавить доказательства цели. Возвращает число новых путей."""
    t = target(g, goal_id)
    if t is None:
        return 0
    have = list(t.get("evidence") or [])
    new = [p for p in evidence if p not in have]
    if new:
        t["evidence"] = have + new
        t["last_evidence_night"] = night_id
        t["nights_without_progress"] = 0
    return len(new)


def apply_updates(g, updates):
    """Применить предложения менеджера. Код проверяет инварианты.

    Возвращает (applied, rejected) — списки словарей для лога.
    """
    applied, rejected = [], []
    for u in updates or []:
        if not isinstance(u, dict):
            rejected.append({"update": u, "reason": "не словарь"})
            continue
        tid = str(u.get("id") or "")
        t = target(g, tid)
        if t is None:
            rejected.append({"update": u, "reason": "неизвестная цель"})
            continue
        status = str(u.get("status") or "").strip()
        if status and status not in STATUSES:
            rejected.append({"update": u, "reason": f"недопустимый статус {status!r}"})
            continue
        if status in TERMINAL:
            # Пока у целей нет исполнимой полной приёмки, существование любого
            # файла не даёт модели права закрыть целый критерий этапа. Это редкие
            # контрольные точки владельца, не ручное принятие каждой задачи.
            rejected.append({"update": u, "reason": "закрытие цели требует подтверждения владельца; "
                             "LLM не заменяет полную приёмку критерия этапа"})
            continue
        if status == "blocked":
            reason = str(u.get("reason") or "").strip()
            if not reason:
                rejected.append({"update": u, "reason": "blocked без причины"})
                continue
            t["status"] = "blocked"
            t["blocked_reason"] = reason[:300]
        elif status == "open":
            t["status"] = "open"
            t.pop("blocked_reason", None)
        applied.append({"id": tid, "status": t.get("status"),
                        "reason": str(u.get("reason") or "")[:200]})
    return applied, rejected


def bump_no_progress(g, night_id):
    """Раз в ночь: у кого не появилось доказательств — +1 ночь. Вернуть зависших."""
    hits = []
    cap = max_no_progress(g)
    for t in _raw_targets(g):
        if t.get("status") != "open":
            continue
        if t.get("last_evidence_night") == night_id:
            t["nights_without_progress"] = 0
            continue
        n = int(t.get("nights_without_progress", 0) or 0) + 1
        t["nights_without_progress"] = n
        if n >= cap:
            hits.append({"id": t["id"], "nights": n, "text": t.get("text")})
    return hits


def stage_is_closed(g):
    crit = (g.get("stage") or {}).get("exit_criteria") or []
    return bool(crit) and all(c.get("status") == "done" for c in crit)


def facts(g):
    """Компактные факты о целях для отчёта и дайджеста."""
    stage = g.get("stage") or {}
    return {
        "global": (g.get("global") or {}).get("statement"),
        "stage": stage.get("id"),
        "stage_deadline": stage.get("deadline"),
        "stage_closed": stage_is_closed(g),
        "targets": [{
            "id": t.get("id"),
            "kind": t.get("kind"),
            "text": t.get("text"),
            "status": t.get("status"),
            "evidence": list(t.get("evidence") or []),
            "nights_without_progress": int(t.get("nights_without_progress", 0) or 0),
            "blocked_reason": t.get("blocked_reason"),
        } for t in targets(g)],
    }
