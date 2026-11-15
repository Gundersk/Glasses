# -*- coding: utf-8 -*-
"""Отчёт и дайджест: факты считает код, модель только объясняет.

Почему так: 11.11.2026 модель написала «T1/T2/T4 провалены», хотя verify.T*.json
говорили pass=true, и этот текст на следующую ночь попал планировщику. Теперь:
- таблицы, статусы, артефакты и стоимость собираются из verify.json и STATE;
- модель пишет только «что это значит», и её числа сверяются с фактами;
- отчёт версионируется по night_id, а не затирается;
- digest.md — короткая выжимка для восстановления контекста.
"""
import json
import re
import time
from pathlib import Path

from . import events, paths, prompts


def _load_verify(task_id, verify_file=None):
    # Старый verify.<id> мог относиться к другой ночи с тем же id.
    if not verify_file:
        return {}
    fp = paths.resolve(verify_file)
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def night_facts(st):
    """Факты ночи без единого слова модели."""
    tasks = []
    for t in st.get("tasks") or []:
        v = _load_verify(t["id"], t.get("verify_file"))
        checks = v.get("checks") or []
        artifacts = []
        for c in checks:
            ch = c.get("check") or {}
            if c.get("ok") and isinstance(ch, dict) and "file_exists" in ch:
                artifacts.append(str(ch["file_exists"]))
        tasks.append({
            "id": t["id"],
            "goal_id": t.get("goal_id"),
            "status": t.get("status"),
            "verify_pass": v.get("pass"),
            "checks_ok": sum(1 for c in checks if c.get("ok")),
            "checks_total": len(checks),
            "artifacts": sorted(set(artifacts)),
            "last_error": (t.get("errors") or [None])[-1],
            "verify_file": t.get("verify_file"),
            "receipt": v.get("receipt"),
            "evidence_level": "command_recorded" if v.get("receipt") else "file_only_or_legacy",
        })
    started = st.get("night_started_ts")
    return {
        "night_id": st.get("night_id"),
        "started": time.strftime("%Y-%m-%d %H:%M", time.localtime(started)) if started else None,
        "finished": time.strftime("%Y-%m-%d %H:%M"),
        "tasks": tasks,
        "budget_usd": round(st.get("budget_used_usd", 0.0), 4),
        "calls_by_provider": st.get("calls_by_provider") or {},
        "attempts_by_provider": st.get("attempts_by_provider") or {},
        "violations": st.get("violations") or [],
        "last_error": st.get("last_error"),
        "needs_human": st.get("needs_human"),
        "lessons": st.get("lessons_admitted") or [],
        "plan_file": "autonomy/workspace/night_plan.yaml",
        "goals_file": "autonomy/goals.yaml",
    }


def _numbers(obj):
    """Все числа из фактов + их процентные представления для долей 0..1."""
    out = set()

    def norm(x):
        if isinstance(x, int):
            return str(x)
        return f"{float(x):.6f}".rstrip("0").rstrip(".")

    def walk(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            out.add(norm(x))
            if isinstance(x, float) and 0 <= x <= 1:
                out.add(norm(round(x * 100, 4)))
        elif isinstance(x, str):
            for m in re.findall(r"\d+(?:[.,]\d+)?", x):
                out.add(m.replace(",", "."))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return {v for v in out if re.fullmatch(r"-?\d+(?:\.\d+)?", v)}


def bad_numbers(text, facts):
    """Числа в тексте, которых нет в фактах (с допуском на округление)."""
    allowed = [float(x) for x in _numbers(facts)]
    bad = []
    for tok in re.findall(r"\d+(?:[.,]\d+)?", text or ""):
        x = float(tok.replace(",", "."))
        if not any(abs(x - v) <= max(0.01, abs(v) * 0.005) for v in allowed):
            bad.append(tok)
    return bad


def interpret(cfg, st, rt, log, facts, limit=1800):
    """Модель пишет только интерпретацию. Числа проверяются, при выдумке — повтор."""
    if not (cfg.get("night") or {}).get("report_interpretation_enabled", True):
        return "", []
    body = ("=== FACTS (единственный источник чисел и статусов) ===\n"
            + json.dumps(facts, ensure_ascii=False, indent=2))
    try:
        res = rt.call("reporter", st, [
            {"role": "system", "content": prompts.REPORTER},
            {"role": "user", "content": body},
        ], max_tokens=int((cfg.get("role_limits") or {}).get("reporter", {})
                          .get("max_tokens", 16000)), temperature=0.3)
        bad = bad_numbers(res.text, facts)
        if bad:
            log.warn(f"интерпретация содержит числа не из фактов: {bad[:5]}")
            events.emit("report_numbers_rejected", numbers=bad[:10])
            nudge = ("\n\nВ прошлом ответе были числа, которых нет в FACTS: "
                     + ", ".join(bad[:10])
                     + ". Перепиши без них, не добавляй новых чисел.")
            res2 = rt.call("reporter", st, [
                {"role": "system", "content": prompts.REPORTER},
                {"role": "user", "content": body + nudge},
            ], max_tokens=int((cfg.get("role_limits") or {}).get("reporter", {})
                              .get("max_tokens", 16000)), temperature=0.2)
            bad2 = bad_numbers(res2.text, facts)
            if bad2:
                log.warn(f"интерпретация снова с чужими числами: {bad2[:5]} — отброшена")
                return "", bad2
            return res2.text.strip()[:limit], []
        return res.text.strip()[:limit], []
    except Exception as e:  # noqa: BLE001 — отчёт не должен падать из-за модели
        log.warn(f"репортёр недоступен ({e}) — остаётся детерминированная часть")
        return "", []


def _table(rows, headers):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x).replace("|", "/") for x in r) + " |")
    return "\n".join(out)


def _request_outcome(facts):
    labels = {
        "complete": "Полный черновик принят по проверкам и REVIEW (не отправлен)",
        "partial": "ЧАСТИЧНЫЙ РЕЗУЛЬТАТ: проверенный материал сохранён, поручение не выполнено полностью",
        "blocked": "Заблокировано: нет принятого результата; имеющиеся черновики не считать проверенными",
    }
    text = "\n**Исход поручения:** " + labels.get(facts.get("request_outcome"), labels["blocked"]) + ".\n"
    for gap in facts.get("request_gaps", []):
        text += f"- Пробел — {gap['topic']}: {gap['reason']}\n"
    for limitation in facts.get("request_limitations", []):
        text += f"- Ограничение: {limitation}\n"
    limits = facts.get("request_limits")
    if limits:
        text += "\nЛимиты: разрешено / использовано / осталось (не путать used с allowed).\n"
        for key, counter in limits["counts"].items():
            text += f"- {key}: {counter['allowed']} / {counter['used']} / {counter['remaining']}\n"
        for key in ("sources", "answer", "work_total"):
            clock = limits["time"][key]
            text += f"- Время {key}, с: {clock['allowed_seconds']:.1f} / {clock['used_seconds']:.1f} / {clock['remaining_seconds']:.1f}\n"
        text += "Общие часы сохраняются между попытками; ожидание квоты не рабочее время.\n"
    if facts.get("request_limits_error"):
        text += "\nОшибка учёта лимитов: " + facts["request_limits_error"] + ".\n"
    if facts.get("retrieval_usage") is not None:
        usage = facts["retrieval_usage"]
        text += (f"\nValyu reader: попыток {usage['counts']}; консервативно зарезервировано "
                 f"${usage['reserved_usd']:.4f}; сообщено провайдером ${usage['reported_cost_usd']:.4f}; "
                 f"стоимость неизвестна для {usage['unknown_cost_attempts']} попыток. "
                 "Резерв не равен счёту провайдера; отсутствие cost не означает бесплатно.\n")
    return text


def render(facts):
    tasks = facts.get("tasks") or []
    done = sum(1 for t in tasks if t["status"] == "done")
    failed = sum(1 for t in tasks if t["status"] == "failed")
    partial = sum(1 for t in tasks if t["status"] == "partial")
    head = (f"# Отчёт за ночь {facts.get('night_id')}\n\n"
            f"**Итог (посчитано кодом по verify.json):** задач {len(tasks)}, "
            f"done {done}, partial {partial}, failed {failed}. Бюджет ${facts.get('budget_usd', 0)}.\n")
    if facts.get("needs_human"):
        head += f"\n**Нужно решение владельца:** {facts['needs_human']}\n"
    if facts.get("request_id"):
        head += (f"\nЗадание: `{facts['request_id']}`, SHA-256 `{facts['request_sha256']}`. "
                  "Это черновик ответа, не отправка ментору и не закрытие этапа.\n")
        head += _request_outcome(facts)

    rows = []
    for t in tasks:
        rows.append([t["id"], t.get("goal_id") or "—", t.get("status"),
                     t.get("verify_pass"), f"{t.get('checks_ok')}/{t.get('checks_total')}",
                     ", ".join(t.get("artifacts") or []) or "—"])
    body = "\n## Задачи\n\n" + _table(
        rows, ["Задача", "Цель", "Статус", "verify", "чеков", "Артефакты"]) + "\n"

    g = facts.get("goals") or {}
    grows = []
    for t in g.get("targets") or []:
        grows.append([t.get("id"), t.get("kind"), t.get("status"),
                      len(t.get("evidence") or []), t.get("nights_without_progress"),
                      t.get("text")])
    if grows:
        body += "\n## Цели\n\n" + _table(
            grows, ["Цель", "Тип", "Статус", "Доказательств", "Ночей без прогресса", "Формулировка"]) + "\n"

    blockers = []
    if facts.get("last_error"):
        blockers.append(f"- последняя ошибка: {facts['last_error']}")
    for v in facts.get("violations") or []:
        blockers.append(f"- нарушение: {v}")
    for t in tasks:
        if t.get("last_error"):
            blockers.append(f"- {t['id']}: {t['last_error']}")
    if blockers:
        body += "\n## Блокеры и ошибки\n\n" + "\n".join(blockers[:10]) + "\n"

    calls = facts.get("calls_by_provider") or {}
    if calls:
        body += "\n## Вызовы моделей\n\n" + ", ".join(
            f"{k}: {v}" for k, v in sorted(calls.items())) + "\n"
    body += (f"\n## Источники фактов\n\n"
             f"- план: `{facts.get('plan_file')}`\n"
             f"- цели: `{facts.get('goals_file')}`\n"
             f"- текущие вердикты и протоколы:\n")
    for t in tasks:
        body += f"  - {t['id']}: `{t.get('verify_file')}`; команды: `{t.get('receipt')}`\n"
    attempts = facts.get("attempts_by_provider") or {}
    if attempts:
        body += "\nФизические попытки (включая неудачные): " + ", ".join(
            f"{k}: {v}" for k, v in sorted(attempts.items())) + ".\n"
    return head + body


def write(st, facts, interpretation, log):
    night = str(facts.get("night_id") or st.get("night_id") or "night")
    body = render(facts)
    if interpretation:
        body += ("\n## Что это значит\n\n"
                 + interpretation.strip()
                 + "\n\n_Интерпретация модели; числа сверены с фактами._\n")
    else:
        body += ("\n## Что это значит\n\n"
                  "Интерпретация отключена, недоступна или отклонена. Выше — "
                  "автоматическая сводка; PASS и наличие файла не заменяют проверку "
                  "происхождения результатов и научной методики.\n")
    rdir = paths.OUTBOX_DIR / "reports"
    rdir.mkdir(parents=True, exist_ok=True)
    versioned = rdir / f"{night}.md"
    versioned.write_text(body, encoding="utf-8")
    (paths.OUTBOX_DIR / "report.md").write_text(body, encoding="utf-8")
    (paths.OUTBOX_DIR / "facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    (rdir / f"{night}.facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    log.ok(f"отчёт: {versioned.relative_to(paths.PROJECT_ROOT)} (и report.md)")
    return versioned


def write_digest(st, facts, g, log):
    """Короткая выжимка: что сделали, где доказательства, что дальше, как продолжить."""
    tasks = facts.get("tasks") or []
    lines = [
        f"# Ночной дайджест {facts.get('night_id')}",
        "",
        f"Обновлён: {facts.get('finished')}. Фаза: {st.get('phase')}.",
        "",
    ]
    if facts.get("needs_human"):
        lines += [f"**Нужно решение владельца:** {facts['needs_human']}", ""]
    if facts.get("request_id"):
        lines += [_request_outcome(facts), ""]
    rows = [[t["id"], t.get("goal_id") or "—", t.get("status"), t.get("verify_pass"),
             ", ".join(t.get("artifacts") or []) or "—"] for t in tasks]
    if rows:
        lines += ["## Задачи", "", _table(rows, ["Задача", "Цель", "Статус", "verify", "Артефакты"]), ""]

    factsg = (facts.get("goals") or {}).get("targets") or []
    if factsg:
        lines += ["## Цели", ""]
        for t in factsg:
            ev = t.get("evidence") or []
            lines.append(f"- {t.get('id')} [{t.get('status')}]: {t.get('text')} "
                         f"(доказательств {len(ev)}, ночей без прогресса "
                         f"{t.get('nights_without_progress')})")
        lines.append("")

    pending = [t for t in st.get("tasks") or []
               if t.get("status") in ("pending", "deferred")]
    lines += ["## Следующие задачи", ""]
    if pending:
        for t in pending[:5]:
            mark = " (отложена: не влезла в тик)" if t.get("status") == "deferred" else ""
            lines.append(f"- {t['id']} (цель {t.get('goal_id')}){mark}: "
                         f"{str(t.get('goal'))[:160]}")
    else:
        for t in factsg:
            if t.get("status") == "open":
                lines.append(f"- цель {t.get('id')}: {t.get('text')}")
    lines.append("")

    if facts.get("last_error"):
        lines += ["## Последняя ошибка", "", f"- {facts['last_error']}", ""]
    if facts.get("violations"):
        lines += ["## Нарушения", ""] + [f"- {v}" for v in facts["violations"][-5:]] + [""]

    if facts.get("request_id"):
        lines += ["## Как продолжить", "",
                  "Повторный запуск этого id запрещён. Проверить ответ/decision и причины остановки; "
                  "при необходимости согласовать новую карточку с новым id. Не запускать обычную ночь вместо задания.", "",
                  f"- план: `{facts.get('plan_file')}`", f"- цели: `{facts.get('goals_file')}`",
                  f"- отчёт: `{paths.OUTBOX_DIR.relative_to(paths.PROJECT_ROOT).as_posix()}/report.md`",
                  "- инструкция: `docs/mentor-requests.md`", ""]
        fp = paths.WORKSPACE / "digest.md"
        fp.write_text("\n".join(lines), encoding="utf-8")
        return fp
    lines += [
        "## Как продолжить",
        "",
        "```powershell",
        ".venv\\Scripts\\python.exe -m autonomy.runner status",
        ".venv\\Scripts\\python.exe -m autonomy.preflight",
        ".venv\\Scripts\\python.exe -m autonomy.runner tick",
        "```",
        "",
        "## Где смотреть",
        "",
        f"- план: `{facts.get('plan_file')}`",
        f"- цели: `{facts.get('goals_file')}`",
        f"- отчёт ночи: `autonomy/workspace/outbox/reports/{facts.get('night_id')}.md`",
        "- уроки: `autonomy/workspace/lessons.md`",
        "- события: `autonomy/workspace/events.jsonl`",
    ]
    fp = paths.WORKSPACE / "digest.md"
    fp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.ok(f"дайджест: {fp.relative_to(paths.PROJECT_ROOT)}")
    return fp
