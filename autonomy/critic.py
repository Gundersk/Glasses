# -*- coding: utf-8 -*-
"""Критик: ворота перед выполнением.

Зачем: verify.json проверяет «файл есть и число в диапазоне», но не проверяет
«задача вообще стоит того и даст ли она результат для защиты». Такие ошибки
поймал человек 12.11.2026 (наши числа сравнивали с чужими без условий).

Правила, которые критик обязан проверять кодом, а не «на вкус»:
- каждая задача ссылается на открытую цель;
- acceptance измерим (файл/метрика/команда), а не «улучшить»;
- у метрики есть условия сравнения;
- сумма задач влезает в тик (phase_timeout_minutes);
- задача не требует человека;
- артефакт пригоден для отчёта/демонстрации/сравнения.

Критик НЕ правит файлы и НЕ выполняет работу. Возвращает вердикт:
approve | revise | block. Жёсткий предел раундов — 2, иначе ночь может
зациклиться на вкусовых правках.
"""

import json
import re
import time

from . import paths

VERDICTS = ("approve", "revise", "block")
MAX_ROUNDS = 2
# Больше трёх запросов на план — это уже исследование, а не критика.
MAX_SEARCHES = 3
SEVERITIES = ("high", "low")
MAX_PLAN_CHARS = 24000


def _extract_json(text):
    """Модель иногда оборачивает JSON в текст или ```json — достаём объект."""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = fence.group(1) if fence else None
    if raw is None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        raw = text[start:end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def normalize(data):
    """Привести ответ к безопасному виду. Невалидный ответ — None."""
    if not isinstance(data, dict):
        return None
    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        return None
    for key in ("objections", "defense_value", "needs_search"):
        if not isinstance(data.get(key, []), list):
            return None
    objections = []
    for o in data.get("objections") or []:
        if not isinstance(o, dict):
            continue
        issue = str(o.get("issue") or "").strip()
        if not issue:
            continue
        objections.append({
            "task_id": str(o.get("task_id") or "").strip(),
            "severity": str(o.get("severity") or "low").strip().lower()
            if str(o.get("severity") or "low").strip().lower() in SEVERITIES else "low",
            "issue": issue[:400],
            "fix": str(o.get("fix") or "").strip()[:400],
        })
    value = []
    for v in data.get("defense_value") or []:
        if isinstance(v, dict) and str(v.get("task_id") or "").strip():
            value.append({
                "task_id": str(v["task_id"]).strip(),
                "verdict": str(v.get("verdict") or "weak").strip()[:20],
                "why": str(v.get("why") or "").strip()[:300],
            })
    # Противоречивое «approve + high» не является одобрением.
    if verdict == "approve" and any(o["severity"] == "high" for o in objections):
        verdict = "revise"
    return {
        "verdict": verdict,
        "summary": str(data.get("summary") or "").strip()[:600],
        "objections": objections,
        "defense_value": value,
        "needs_search": [{"query": str(s.get("query") or "").strip()[:200],
                          "why": str(s.get("why") or "").strip()[:200]}
                         for s in (data.get("needs_search") or [])
                         if isinstance(s, dict) and str(s.get("query") or "").strip()],
        "raw_ok": True,
    }


def _fallback(reason):
    return {"verdict": "block", "summary": reason, "objections": [],
            "defense_value": [], "needs_search": [], "searches": [],
            "raw_ok": False}


def objections_text(verdict):
    """Текст замечаний для планировщика: что именно исправить."""
    lines = []
    for o in verdict.get("objections") or []:
        where = o.get("task_id") or "план"
        lines.append(f"- [{o['severity']}] {where}: {o['issue']}")
        if o.get("fix"):
            lines.append(f"  как исправить: {o['fix']}")
    return "\n".join(lines) or "(замечаний нет)"


def _ask(rt, st, cfg, log, role, content, strict=False):
    """Один вызов критика. Невалидный JSON — один строгий повтор."""
    from . import prompts

    out = rt.call(role, st, [
        {"role": "system", "content": prompts.CRITIC},
        {"role": "user", "content": content
         + ("\n\nВерни ТОЛЬКО JSON по схеме." if strict else "")},
    ], max_tokens=_role_max(cfg, role, 12000),
        temperature=0.0 if strict else 0.1)
    verdict = normalize(_extract_json(out.text))
    if verdict is None and not strict:
        log.warn("критик вернул невалидный ответ — повторю один раз")
        return _ask(rt, st, cfg, log, role, content, strict=True)
    return verdict


def make_search_fn(cfg, log):
    """Поиск для критика: ссылки + короткие выдержки, а не простыни страниц.

    Критик не должен сам решать, что «нагуглил». Выжимка уходит ему как
    источник, а числа из неё попадают в реестр только после проверки цитаты.
    """
    def _search(query, why=""):
        from . import research
        return research.brief(
            query, max_pages=1, chars=600,
            purpose=(why or "проверка внешнего факта для ночного плана")[:200])
    return _search


def review(rt, st, cfg, log, *, tasks, materials, role="critic", round_no=1,
           search_fn=None):
    """Один проход критика. Возвращает разобранный вердикт.

    Если критику нужен внешний факт, он просит поиск (`needs_search`), получает
    выжимку и отвечает повторно уже с ней. Ровно один раунд поиска и не больше
    MAX_SEARCHES запросов: иначе критика превращается в исследование и съедает
    тик. Поиск необязателен — без него критик работает по файлам проекта.
    """
    plan_txt = json.dumps(tasks, ensure_ascii=False, indent=1)
    if len(plan_txt) > MAX_PLAN_CHARS:
        return _fallback("план превышает лимит полного просмотра; сократить или разделить")
    content = (
        "=== ПЛАН НОЧИ (YAML) ===\n" + plan_txt
        + "\n\n=== КОНТЕКСТ ПРОЕКТА ===\n" + materials
        + f"\n\nРаунд критики: {round_no} из {MAX_ROUNDS}."
    )
    try:
        verdict = _ask(rt, st, cfg, log, role, content)
    except Exception as e:
        log.error(f"критик недоступен: {type(e).__name__}")
        return _fallback("критик недоступен; выполнение не разрешено")
    if verdict is None:
        log.error("критик дважды не дал валидный ответ")
        return _fallback("критик не дал валидный вердикт; выполнение не разрешено")

    if len(verdict.get("needs_search") or []) > MAX_SEARCHES:
        return _fallback("запрошено больше внешних проверок, чем допускает бюджет; разделить план")
    queries = (verdict.get("needs_search") or [])[:MAX_SEARCHES]
    verdict["searches"] = []
    if queries and search_fn:
        log.log(f"критик просит поиск: {len(queries)} запрос(ов)")
        found = []
        failed_queries = []
        for q in queries:
            t0 = time.time()
            try:
                text = search_fn(q["query"], q.get("why") or "")
            except Exception as e:
                log.warn(f"поиск не удался «{q['query'][:60]}»: {e}")
                found.append(f"ЗАПРОС: {q['query']}\n(поиск не удался: {e})")
                failed_queries.append(q["query"])
                continue
            if not isinstance(text, str) or not text.strip():
                failed_queries.append(q["query"])
                continue
            log.log(f"поиск ок: «{q['query'][:60]}» {time.time() - t0:.1f} c, "
                    f"{len(text)} симв.")
            found.append(text)
        block = ("\n\n=== РЕЗУЛЬТАТЫ ПОИСКА (внешний источник, не измерение) ===\n"
                 + "\n\n".join(found)[:9000])
        if failed_queries:
            blocked = _fallback("запрошенные внешние факты не проверены: сбой поиска")
            blocked["searches"] = [q["query"] for q in queries]
            return blocked
        try:
            second = _ask(rt, st, cfg, log, role, content + block
                          + "\n\nУчти результаты поиска. Если они не подтверждают внешний"
                            " ориентир — считай ориентир неподтверждённым, не выдумывай"
                            " числа. Ответь тем же JSON.")
        except Exception:
            second = None
        if second is None:
            log.warn("критик не ответил после поиска — выполнение не разрешено")
            verdict = _fallback("нет финального вердикта после поиска")
            verdict["searches"] = [q["query"] for q in queries]
        else:
            if second.get("needs_search"):
                log.warn("критик снова просит поиск — второй раунд поиска не даю")
                second = _fallback("внешние вопросы остались после единственного раунда поиска")
            second["searches"] = [q["query"] for q in queries]
            verdict = second
    elif queries:
        log.warn("критик просит поиск, но поиск не подключён — вердикт без проверки")
        verdict = _fallback("запрошен поиск, но он не подключён; выполнение не разрешено")
    if len(verdict.get("needs_search") or []) > MAX_SEARCHES:
        verdict = _fallback("запрошено больше внешних проверок, чем допускает бюджет; разделить план")
    return verdict


def _role_max(cfg, role, default):
    try:
        return int(((cfg.get("role_limits") or {}).get(role) or {}).get("max_tokens", default))
    except (TypeError, ValueError):
        return default


def write_note(night_id, verdict, round_no, log):
    """Заметка для утра: что критик сказал и что с этим сделали."""
    out = paths.WORKSPACE / "outbox" / "critique.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Критика плана {night_id} (раунд {round_no})",
        "",
        f"Вердикт: **{verdict['verdict']}**",
        f"Время: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Резюме",
        verdict.get("summary") or "(пусто)",
        "",
        "## Замечания",
    ]
    objections = verdict.get("objections") or []
    if not objections:
        lines.append("(нет)")
    for o in objections:
        lines.append(f"- [{o['severity']}] {o.get('task_id') or 'план'}: {o['issue']}")
        if o.get("fix"):
            lines.append(f"  - правка: {o['fix']}")
    lines += ["", "## Ценность для защиты"]
    value = verdict.get("defense_value") or []
    if not value:
        lines.append("(критик не оценил)")
    for v in value:
        lines.append(f"- {v['task_id']}: {v['verdict']} — {v['why']}")
    searches = verdict.get("searches") or []
    if searches:
        lines += ["", "## Что критик проверял поиском"]
        lines += [f"- {q}" for q in searches]
        lines.append("")
        lines.append("Выжимки и ссылки — в `docs/research/notes/`. Это источник,"
                     " а не измерение: числа из поиска в реестр без проверки цитаты"
                     " не попадают.")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if log:
        log.log(f"критика записана: {out.relative_to(paths.PROJECT_ROOT)}")
    return out
