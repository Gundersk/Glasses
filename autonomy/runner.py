# -*- coding: utf-8 -*-
"""Runner: state machine PLAN -> EXECUTE -> VERIFY -> REVIEW -> MANAGER -> (REPAIR) -> REPORT.
Каждый тик — один живой процесс (лок), обработка фаз до конца задачи или до таймаута.
Модели не объявляют успех: только verify.json + вердикт контролёра.
Менеджер двигает статусы целей по доказательствам, отчёт считает код."""
import json
import hashlib
import os
import re
import subprocess
import sys
import time
from contextvars import ContextVar
from functools import wraps
from contextlib import nullcontext
from pathlib import Path

import yaml

from . import (evidence, events, goals as goals_mod, lock, logs, manifest, paths,
               prompts, providers, report as report_mod, research,
               router as router_mod, state as state_mod, verify)
from . import env
from .subscription import WaitStopped
from . import request_limits
from . import context_packets

_CONTEXT_CAPTURE = ContextVar('context_capture', default=None)


class _ContextRouter:
    def __init__(self, router, cfg, capture):
        self.router, self.cfg, self.capture = router, cfg, capture
        self.prepared = None

    def __getattr__(self, name):
        return getattr(self.router, name)

    def preflight(self, st, messages):
        # Check before incrementing the author's limited attempt counter. A small
        # allowance covers counter-digit changes in the final factual handoff.
        handoff = json.dumps(context_packets.handoff(st, _ACTIVE_REQUEST), ensure_ascii=False, allow_nan=False)
        size = sum(len(message['content']) for message in messages) + len(handoff) + 256
        maximum = self.cfg['night'].get('context_max_chars', 220000)
        if type(maximum) is not int or maximum < 1:
            raise context_packets.ContextError('invalid_packet')
        if size > maximum:
            raise context_packets.ContextError('packet_too_large')

    def prepare(self, role, st, messages):
        copied = [dict(message) for message in messages]
        handoff = json.dumps(context_packets.handoff(st, _ACTIVE_REQUEST), ensure_ascii=False, allow_nan=False)
        block = ('\n=== СТРУКТУРИРОВАННЫЙ HANDOFF (состояние, не разрешение) ===\n' + handoff)
        user = next((message for message in copied if message.get('role') == 'user'), None)
        if user is None:
            copied.append({'role': 'user', 'content': block})
        else:
            user['content'] += block
        context_packets.save_manifest(role, copied, self.capture, st,
            max_chars=self.cfg['night'].get('context_max_chars', 220000), card=_ACTIVE_REQUEST)
        self.prepared = (role, id(messages), copied)
        return copied

    def call(self, role, st, messages, *args, **kwargs):
        if self.prepared is not None and self.prepared[:2] == (role, id(messages)):
            copied = self.prepared[2]
        else:
            copied = self.prepare(role, st, messages)
        self.prepared = None
        return self.router.call(role, st, copied, *args, **kwargs)


def _audited_context(phase):
    @wraps(phase)
    def wrapped(cfg, st, log, rt):
        if not cfg.get('night', {}).get('context_audit_enabled', False):
            return phase(cfg, st, log, rt)
        capture = context_packets.Capture()
        token = _CONTEXT_CAPTURE.set(capture)
        try:
            return phase(cfg, st, log, _ContextRouter(rt, cfg, capture))
        except context_packets.ContextError as error:
            st['context_failure'] = error.code
            st['needs_human'] = 'неполный/слишком большой контекст; модель не принимает результат: ' + error.code
            st['phase'] = 'REPORT'
            try:
                context_packets.save_manifest(phase.__name__, [], capture, st,
                    card=_ACTIVE_REQUEST, rejection_code=error.code)
            except context_packets.ContextError:
                st['context_manifest_write_failed'] = True
            return
        finally:
            _CONTEXT_CAPTURE.reset(token)
    return wrapped

CONFIG_FILE = paths.AUTONOMY_DIR / "config.yaml"
PLAN_FILE = paths.WORKSPACE / "night_plan.yaml"
SNAP_FILE = paths.WORKSPACE / "snapshot_before.json"
APPROVAL_FILE = paths.WORKSPACE / "night_plan.approval.json"
APPROVAL_VERSION = 3  # v2 не разделяла mock и настоящий режим
_ACTIVE_REQUEST = None  # только явный autonomy.intake run, не чужой STATE


def _plan_sha256(data=None):
    """Хэш содержимого плана без служебных статусов.

    Нужен, чтобы одобрение критика относилось к самим задачам: правка задачи
    ломает одобрение, а смена статуса (done/deferred) — нет.
    """
    if data is None:
        try:
            data = yaml.safe_load(PLAN_FILE.read_text(encoding="utf-8")) or []
        except (OSError, yaml.YAMLError):
            return ""
    items = [t for t in (data if isinstance(data, list) else []) if isinstance(t, dict)]
    served = [{k: v for k, v in t.items()
               if k not in ("status", "note", "deferred_reason", "verify_file", "receipt",
                            "verify_fingerprint")} for t in items]
    raw = json.dumps(served, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _approval_context_sha256():
    """Смена ограничений/политики критика также снимает прежнее одобрение."""
    h = hashlib.sha256()
    for rel in ("docs/agent-context.md", "docs/scope.md", "AGENTS.md",
                "autonomy/config.yaml", "autonomy/prompts.py", "autonomy/critic.py",
                "autonomy/intake.py", "autonomy/runner.py", "autonomy/evidence.py", "autonomy/verify.py",
                "autonomy/research.py", "autonomy/shellutil.py", "autonomy/router.py",
                "autonomy/providers.py", "autonomy/opencode_provider.py",
                "autonomy/subscription.py", "autonomy/state.py", "opencode.json",
                "autonomy/request_research.py", "autonomy/source_selection.py", "autonomy/request_limits.py",
                "autonomy/claim_validation.py", "autonomy/author_evidence.py", "autonomy/source_outcomes.py",
                "autonomy/source_archive.py", "autonomy/publication_identity.py", "autonomy/retrieval.py",
                "autonomy/valyu_reader.py", "autonomy/manifest.py", "autonomy/context_packets.py"):
        fp = paths.PROJECT_ROOT / rel
        h.update(rel.encode("utf-8"))
        h.update(fp.read_bytes() if fp.exists() else b"MISSING")
    if _ACTIVE_REQUEST:
        h.update(_ACTIVE_REQUEST["sha256"].encode("ascii"))
        from . import request_research
        h.update(str(request_research.read_plan(_ACTIVE_REQUEST)["sha256"]).encode("ascii"))
    return h.hexdigest()


def _approval_ok():
    """План с диска выполняется без повторной критики, только если критик
    одобрил ровно это содержимое. Иначе ворота работают и для правок руками."""
    if not (PLAN_FILE.exists() and APPROVAL_FILE.exists()):
        return False
    try:
        a = json.loads(APPROVAL_FILE.read_text(encoding="utf-8"))
        if _ACTIVE_REQUEST:
            from . import intake
            from . import request_research
            if request_research.pending_update(_ACTIVE_REQUEST).exists():
                return False
            if intake.load(_ACTIVE_REQUEST["spec"]["id"]) != _ACTIVE_REQUEST:
                return False
    except (OSError, ValueError):
        return False
    return (a.get("version") == APPROVAL_VERSION and a.get("raw_ok") is True
            and a.get("mock") is bool(env.get("AUTONOMY_MOCK"))
            and a.get("verdict") == "approve" and a.get("sha256") == _plan_sha256()
            and a.get("context_sha256") == _approval_context_sha256())


def _save_approval(verdict, round_no):
    APPROVAL_FILE.write_text(json.dumps({
        "version": APPROVAL_VERSION,
        "mock": bool(env.get("AUTONOMY_MOCK")),
        "raw_ok": verdict.get("raw_ok", False),
        "context_sha256": _approval_context_sha256(),
        "verdict": verdict.get("verdict"),
        "sha256": _plan_sha256(),
        "rounds": round_no,
        "searches": verdict.get("searches") or [],
        "ts": time.time(),
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def load_config():
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    if _ACTIVE_REQUEST:
        from . import intake
        spec = _ACTIVE_REQUEST["spec"]
        cfg["request_id"] = spec["id"]
        cfg["night"]["retrieval_budget_usd"] = spec.get("research_policy", {}).get("retrieval_budget_usd", 0)
        cfg["night"]["budget_usd_per_night"] = min(cfg["night"]["budget_usd_per_night"], spec["budget_usd"])
        cfg["night"]["input_chars_per_file"] = 24000
        cfg["roles"]["verifier"] = list(cfg["roles"]["critic"])
        cfg["role_limits"]["verifier"]["max_tokens"] = 24000
        cfg["research"]["cache_dir"] = intake.rel(paths.CACHE_DIR / "web")
        cfg["sandbox"]["allowed_write_paths"] = [intake.rel(paths.WORKSPACE) + "/**",
            intake.rel(intake.output_dir(_ACTIVE_REQUEST)) + "/**",
            intake.rel(intake.root(spec["id"])) + "/sources-*"]
    return cfg


# ---------------------------------------------------------------- utilities
def extract_json(text):
    """Достаёт первый JSON-объект из ответа модели (терпимо к markdown/пояснениям)."""
    if not text:
        raise ValueError("пустой ответ")
    t = text.strip()
    # снять ```-обёртку
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if m:
        t = m.group(1)
    start = t.find("{")
    if start < 0:
        raise ValueError("нет { в ответе")
    obj, _ = json.JSONDecoder().raw_decode(t, start)
    return obj


def _read_ctx(path, limit=8000, *, required=False, mode='prefix'):
    capture = _CONTEXT_CAPTURE.get()
    if capture is not None:
        if str(path).replace('\\', '/') == 'docs/agent-context.md':
            required, limit = True, 16000
        elif str(path).replace('\\', '/') == 'docs/scope.md':
            required, limit = True, 30000
        return capture.read(path, limit, required=required, mode=mode)
    if required or mode != 'prefix':
        return context_packets.Capture().read(path, limit, required=required, mode=mode)
    p = paths.resolve(path)
    if (not paths.inside_project(path) or p.name.startswith(".env")
            or "temp" in p.relative_to(paths.PROJECT_ROOT).parts):
        return "(закрытый путь: не передавать секреты и временные credentials модели)"
    if not p.exists():
        return f"(нет файла {path})"
    if p.is_dir():
        # каталог вместо файла: список содержимого, не чтение
        try:
            entries = sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())[:40]
        except OSError as e:
            return f"(каталог {path}: ошибка чтения {e})"
        return f"(каталог {path}, {len(entries)} записей)\n" + "\n".join(entries)
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(не удалось прочитать {path}: {e})"
    return txt if len(txt) <= limit else txt[:limit] + "\n...(обрезано)"


def _request_author_inputs(task, cfg, iteration):
    """Source JSON is selected by page, never sent as an arbitrary prefix."""
    from . import intake, request_research, author_evidence
    source_paths = set()
    if _ACTIVE_REQUEST["spec"]["kind"] == "research":
        queries = (request_research.read_plan(_ACTIVE_REQUEST)["queries"]
                   if request_research.policy(_ACTIVE_REQUEST)
                   else _ACTIVE_REQUEST["spec"]["research_queries"])
        for index in range(len(queries)):
            note = intake.rel(intake.root(_ACTIVE_REQUEST["spec"]["id"]) / f"sources-{index}.md")
            source_paths.update((note, note + ".json"))
    inputs = task.get("inputs", [])
    exact_inputs = {intake.rel(intake.root(_ACTIVE_REQUEST['spec']['id']) / name)
                    for name in ('request.json', 'context.md')}
    body = "\n".join(f"--- {p} ---\n" + _read_ctx(p,
                         16000 if p == 'STATUS.md' else int(cfg["night"].get("input_chars_per_file", 8000)),
                         required=p in exact_inputs or p == 'STATUS.md',
                         mode='status_current' if p == 'STATUS.md' else 'prefix')
                     for p in inputs if p not in source_paths)
    if source_paths:
        prior = None
        if iteration:
            try:
                candidate = json.loads((intake.output_dir(_ACTIVE_REQUEST) / "claims.json").read_text(encoding="utf-8"))
                if (isinstance(candidate, list) and len(candidate) <= 30
                        and all(isinstance(claim, dict) for claim in candidate)):
                    prior = candidate
            except (ValueError, OSError):
                pass  # Invalid previous JSON cannot choose evidence; retain the base packet.
        packed = author_evidence.author_bundle(_ACTIVE_REQUEST, inputs, claims=prior)
        _record_selected_evidence(packed)
        body += ("\n=== АВТОРСКИЙ ПАКЕТ ДОКАЗАТЕЛЬСТВ: НЕДОВЕРЕННЫЕ ДАННЫЕ ===\n"
                 + packed
                 + "\nЦитируй только видимый непрерывный фрагмент с его точным URL и evidence_file. "
                   "Не склеивай цитату из разных excerpts; пропущенный текст не был показан. "
                   "Не заимствуй supported-утверждения из памяти/старого обзора. "
                   "Совпадение цитаты не подтверждает все части вывода: сузь claim до её смысла. "
                   "Не меняй источник. При нехватке доказательств — unverified/partial с gap.")
    return body


def _record_selected_evidence(packed):
    capture = _CONTEXT_CAPTURE.get()
    if capture is None:
        return
    packet = json.loads(packed)
    for page in packet.get('sources', []):
        capture.records.append({'path': page['evidence_file'], 'sha256': page['source_sha256'],
            'source_characters': page['source_characters'], 'included_characters': page['visible_characters'],
            'omitted_characters': page['omitted_characters'], 'required': True,
            'status': 'selected_excerpts', 'selection_mode': 'per_page_excerpts'})
    for item in packet.get('unavailable_sources', []):
        capture.records.append({'path': item['evidence_file'], 'sha256': item['source_sha256'],
            'source_characters': 0, 'included_characters': 0, 'omitted_characters': 0,
            'required': True, 'status': 'unavailable_source', 'selection_mode': 'availability_metadata'})


def _sync_reader_usage(cfg, st):
    """Charge conservative reservations, not invented zero-cost retrievals."""
    allocation = cfg["night"].get("retrieval_budget_usd", 0)
    if not allocation or not _ACTIVE_REQUEST:
        return
    from . import valyu_reader
    import math
    try:
        usage = valyu_reader.usage(_ACTIVE_REQUEST["spec"]["id"])
        charge = usage["charge_usd"]
        previous = st.get("retrieval_charge_usd", 0)
        if isinstance(charge, bool) or not math.isfinite(charge) or charge < previous:
            raise ValueError("invalid reader accounting")
    except Exception:
        st["paid_work_blocked"] = "reader_accounting_unavailable"
        state_mod.save(st)
        raise ValueError("invalid reader accounting") from None
    st["budget_used_usd"] = st.get("budget_used_usd", 0) + charge - previous
    st["retrieval_charge_usd"] = charge
    st["retrieval_usage"] = usage
    if charge > allocation + 1e-9:
        st["paid_work_blocked"] = "retrieval_allocation_exceeded"
        state_mod.save(st)
        raise ValueError("reported retrieval cost exceeds allocation; further paid work forbidden")
    state_mod.save(st)


STUB_MARKERS = [
    "не запуска", "не выполня", "не измер", "не проводил", "не реально",
    "заглушка", "placeholder", "todo", "fixme", "not launched", "not executed",
    "not measured", "asr_launched\": false", '"asr_launched": false',
]

# Маркеры заглушки внутри содержимого файла, который пишет исполнитель.
STUB_CONTENT = ("placeholder", "заглушка", "todo:", "fixme", "not implemented")


def _role_max(cfg, role, default):
    """Потолок вывода на роль из config.yaml (role_limits.<role>.max_tokens)."""
    limits = cfg.get("role_limits") or {}
    return int((limits.get(role) or {}).get("max_tokens", default))


def _content_stub_reason(rel, content):
    """Почему содержимое файла нельзя записывать (None — можно)."""
    t = (content or "").strip()
    if not t:
        return "пустое содержимое"
    if t in ("...", "…", "TODO", "TBD"):
        return "заглушка вместо файла"
    low = t.lower()
    for m in STUB_CONTENT:
        if m in low:
            return f"маркер заглушки «{m}»"
    if rel.endswith(".py") and len(t) < 200:
        return f"подозрительно короткий .py ({len(t)} символов)"
    return None


def _backup_before_write(rel, fp):
    """Копия текущей версии файла перед перезаписью. Заглушка не должна
    уничтожать рабочий результат: 11.11.2026 так был потерян рабочий скрипт."""
    if not fp.exists() or not fp.is_file():
        return None
    try:
        if fp.stat().st_size > 4 * 1024 * 1024:
            return None
        bdir = paths.WORKSPACE / "backups" / time.strftime("%Y%m%d-%H%M%S")
        dst = bdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(fp, dst)
        return dst
    except OSError:
        return None


def _stub_scan(paths_list):
    """Ищет в МАШИННЫХ артефактах (json/csv) признания, что работа не выполнялась.
    .md-файлы не сканим: честное «не измерено» в STATUS/notes — норма проекта."""
    hits = []
    for rel in paths_list:
        if not rel.endswith((".json", ".csv")):
            continue
        # Служебные файлы раннера (state.json, events.jsonl) содержат тексты задач
        # с честными «не измерялось» и не являются артефактами задачи.
        if rel.replace("\\", "/").startswith("autonomy/workspace/"):
            continue
        try:
            txt = paths.resolve(rel).read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        for m in STUB_MARKERS:
            if m.lower() in txt:
                hits.append(f"{rel}: «{m.strip()}»")
    return hits


# ---------------------------------------------------------------- phases
def _request_limits_context(cfg, st):
    if not _ACTIVE_REQUEST or not _ACTIVE_REQUEST["spec"].get("research_policy"):
        return ""
    from . import request_research
    return ("\n=== МАШИННЫЙ КОНТРАКТ ЛИМИТОВ (текущий, не исторический STATUS) ===\n"
            + json.dumps(request_limits.snapshot(_ACTIVE_REQUEST, st,
                coordinator_minutes=cfg.get("night", {}).get("phase_timeout_minutes", 50)), ensure_ascii=False)
            + "\n=== ТЕКУЩИЕ ЗАПРОСЫ ===\n"
            + json.dumps(request_research.read_plan(_ACTIVE_REQUEST)["queries"], ensure_ascii=False)
            + "\nПоля used — израсходовано, НЕ разрешено. remaining — доступный остаток; "
              "нулевой used followup не запрещает разрешённый followup. "
              "sources/answer — общие часы всех задач/попыток одной полосы; "
              "time_limit_minutes карточки — общий бюджет ответа, не всего поручения. "
              "Повторение задачи не добавляет времени. Coordinator — отдельное окно ворот. "
              "intake check проверяет цитаты, coverage, разные URL/домены и partial; "
              "REVIEW проверяет смысл. Оцени охват с учётом имеющихся context_files и "
              "разрешённого резерва, не требуй отдельного запроса с дословными словами для каждой темы.")


@_audited_context
def phase_plan(cfg, st, log, rt):
    log.step("PLAN")
    st.setdefault("night_started_ts", time.time())  # не сбрасывать начало при bounded replan
    try:
        g = goals_mod.load()
    except goals_mod.GoalsError as e:
        log.error(f"реестр целей: {e}")
        st["needs_human"] = f"реестр целей: {e}"
        st["phase"] = "REPORT"
        return
    open_ids = [t["id"] for t in goals_mod.open_targets(g)]
    if not open_ids:
        log.warn("открытых целей нет — планировать нечего, нужно решение о следующем этапе")
        st["needs_human"] = "все цели этапа закрыты; нужно решение о переходе"
        st["phase"] = "REPORT"
        return

    preloaded = False
    if _ACTIVE_REQUEST:
        from . import intake
        intake.load(_ACTIVE_REQUEST["spec"]["id"])
        tasks = _validate_tasks(st["tasks"] if st.pop("request_replan_pending", False)
                                else intake.build_plan(_ACTIVE_REQUEST), g)
        preloaded = True
    elif PLAN_FILE.exists():
        age_h = (time.time() - PLAN_FILE.stat().st_mtime) / 3600
        if age_h < 12:
            try:
                tasks = _validate_tasks(yaml.safe_load(PLAN_FILE.read_text(encoding="utf-8")), g)
            except Exception as e:
                log.warn(f"план-файл повреждён ({e}) — перестраиваю с нуля")
                tasks = []
            # План из одних done не переиспользуем: иначе ночь заканчивается
            # за секунду и ничего не делает (было 11.11.2026). Отложенные
            # (не влезли в тик) возвращаем в pending, иначе работа теряется.
            for t in tasks:
                if t.get("status") == "deferred":
                    t["status"] = "pending"
                    t["note"] = "возвращена после откладывания: не влезла в прошлый тик"
            if tasks and any(t.get("status") == "pending" for t in tasks):
                if _approval_ok():
                    st["tasks"] = tasks
                    st["phase"] = "EXECUTE"
                    log.ok(f"план загружен из {PLAN_FILE.name}: {len(st['tasks'])} задач"
                           " (одобрен критиком, файл не менялся)")
                    return
                # План с диска без подтверждения: его мог править человек или
                # прошлая ночь упасть до критики. Такой план тоже идёт ворота.
                log.warn("план с диска не подтверждён критиком — проверяю перед выполнением")
                preloaded = True

    materials = (
        "=== АКТУАЛЬНЫЕ ОГРАНИЧЕНИЯ И ПРИОРИТЕТ ДОКУМЕНТОВ ===\n"
        + _read_ctx("docs/agent-context.md", 16000, required=True)
        + "\n=== РЕЕСТР ЦЕЛЕЙ ===\n" + goals_mod.summary(g, 2800)
        + "\n=== PROJECT.md (фрагмент) ===\n" + _read_ctx("PROJECT.md", 2000)
        + "\n=== STATUS.md: АКТУАЛЬНЫЕ РАЗДЕЛЫ ===\n" + _read_ctx("STATUS.md", 16000, required=True, mode='status_current')
        + "\n=== ФАКТЫ ПРОШЛОЙ НОЧИ (digest) ===\n"
        + _read_ctx("autonomy/workspace/digest.md", 2500)
        + "\n=== ПОСЛЕДНИЕ СОГЛАСОВАННЫЕ ИЗМЕНЕНИЯ ПЛАНА (RC) ===\n" + _rc_tail(1500)
        + "\n=== РЕЕСТР СОПОСТАВИМОСТИ (docs/benchmarks.md) ===\n"
        + _read_ctx("docs/benchmarks.md", 1800)
        + "\n=== ОБЯЗАТЕЛЬНЫЕ АРТЕФАКТЫ ЭТАПА (из scope, не метрики вместо них) ===\n"
        + _stage_scope(g)
    )
    if _ACTIVE_REQUEST:
        materials += "\n=== ЗАДАНИЕ ВЛАДЕЛЬЦА/МЕНТОРА ===\n" + json.dumps(_ACTIVE_REQUEST, ensure_ascii=False)
        from . import request_research
        if request_research.policy(_ACTIVE_REQUEST):
            materials += ("\nПроверь явно покрытие всех research_policy.topics, соответствие closes "
                          "без объявления шага завершённым, разнообразие предшествующих работ и "
                          "достаточность поискового плана, не только выбранный стек. "
                          "Исходное поручение/requirements/бюджеты неизменяемы.\n")
            # All literature searches must be approved collection commands; a
            # hidden critic search would evade the source-page/query caps.
    if preloaded:
        log.log("план с диска: перегенерация не нужна, проверяю критиком")
    else:
        res = rt.call("planner", st, [
            {"role": "system", "content": prompts.PLANNER},
            {"role": "user", "content": materials + _request_limits_context(cfg, st)},
        ], max_tokens=_role_max(cfg, "planner", 32000), temperature=0.2)
        tasks = _validate_tasks(_parse_yaml_list(res.text), g)
        st["plan_author_model"] = res.model
    if not tasks:
        log.warn("планировщик не нашёл задач под открытые цели")
        st["needs_human"] = "планировщик не нашёл задач; открытые цели: " + ", ".join(open_ids)
        st["phase"] = "REPORT"
        return

    # --- критик: ворота перед выполнением ---------------------------------
    # План, который «выполним и измерим», ещё не значит «нужен». Критик ищет
    # именно это, но получает жёсткий предел раундов: иначе ночь зацикливается
    # на вкусовых правках и не выполняет работу.
    from . import critic as critic_mod
    night_id = str(st.get("night_id") or time.strftime("%Y%m%d"))
    round_no = 1
    # Поиск нужен только для внешних фактов (ориентир существует? условия
    # сопоставимы? лицензия/модель не устарела?). Файлы проекта уже в контексте.
    search_fn = critic_mod.make_search_fn(cfg, log)
    if _ACTIVE_REQUEST and request_research.policy(_ACTIVE_REQUEST):
        search_fn = None
    verdict = critic_mod.review(rt, st, cfg, log, tasks=tasks, materials=materials + _request_limits_context(cfg, st),
                               role="critic", round_no=round_no, search_fn=search_fn)
    while verdict["verdict"] == "revise" and round_no < critic_mod.MAX_ROUNDS:
        if _ACTIVE_REQUEST:
            if not request_research.policy(_ACTIVE_REQUEST) or any(t.get("status") == "done" for t in tasks):
                break
            if request_research.read_plan(_ACTIVE_REQUEST)["plan_revisions"] >= request_research.policy(_ACTIVE_REQUEST)["max_plan_revisions"]:
                break  # do not spend a planner call on a forbidden revision
            try:
                proposal = rt.call("planner", st, [
                    {"role": "system", "content": request_research.PLANNER},
                    {"role": "user", "content": materials + _request_limits_context(cfg, st) + "\n" + critic_mod.objections_text(verdict)},
                ], max_tokens=_role_max(cfg, "planner", 32000), temperature=0.1)
                typed = json.loads(proposal.text)
                request_research.begin_update(_ACTIVE_REQUEST)
                request_research.propose(_ACTIVE_REQUEST, typed, proposal.model, "plan")
                st["plan_author_model"] = proposal.model
                tasks = _validate_tasks(intake.build_plan(_ACTIVE_REQUEST), g)
                st["tasks"] = tasks
                _sync_plan(st, strict=True)
                request_research.commit_update(_ACTIVE_REQUEST, st)
            except (ValueError, providers.ProviderError, OSError) as e:
                st["needs_human"] = "ограниченная доработка research-плана отклонена: " + str(e)[:200]
                st["phase"] = "REPORT"
                return
            round_no += 1
            verdict = critic_mod.review(rt, st, cfg, log, tasks=tasks, materials=materials + _request_limits_context(cfg, st),
                                        role="critic", round_no=round_no, search_fn=None)
            continue
        round_no += 1
        log.warn(f"критик требует правок (раунд {round_no})")
        fix_materials = (
            materials
            + "\n\n=== ТЕКУЩИЙ ПЛАН (исправь его, а не пиши заново) ===\n"
            + yaml.safe_dump(tasks, allow_unicode=True, sort_keys=False)
            + "\n\n=== ЗАМЕЧАНИЯ КРИТИКА (исправь план) ===\n"
            + critic_mod.objections_text(verdict)
            + "\nВерни исправленный YAML-список задач по тем же правилам."
        )
        res2 = rt.call("planner", st, [
            {"role": "system", "content": prompts.PLANNER},
            {"role": "user", "content": fix_materials},
        ], max_tokens=_role_max(cfg, "planner", 32000), temperature=0.2)
        fixed = _validate_tasks(_parse_yaml_list(res2.text), g)
        st["plan_author_model"] = res2.model
        if not fixed:
            log.warn("планировщик не дал исправленный план — оставляю прежний")
        else:
            tasks = fixed
        verdict = critic_mod.review(rt, st, cfg, log, tasks=tasks, materials=materials,
                                    role="critic", round_no=round_no,
                                    search_fn=search_fn)
    critic_mod.write_note(night_id, verdict, round_no, log)
    st["critique"] = {
        "verdict": verdict["verdict"],
        "summary": verdict.get("summary") or "",
        "objections": verdict.get("objections") or [],
        "defense_value": verdict.get("defense_value") or [],
        "searches": verdict.get("searches") or [],
        "rounds": round_no,
        "model_answered": bool(verdict.get("raw_ok", True)),
    }
    if verdict["verdict"] != "approve" or not verdict.get("raw_ok"):
        log.error("план не получил валидное одобрение критика")
        APPROVAL_FILE.unlink(missing_ok=True)
        st["needs_human"] = ("план не одобрен критиком: "
                             + (verdict.get("summary") or "без объяснения"))
        st["phase"] = "REPORT"
        return
    log.log(f"критик: {verdict['verdict']} (раундов {round_no}, "
            f"замечаний {len(verdict.get('objections') or [])})")

    PLAN_FILE.write_text(yaml.safe_dump(tasks, allow_unicode=True, sort_keys=False),
                         encoding="utf-8")
    _save_approval(verdict, round_no)
    st["tasks"] = tasks
    st["phase"] = "EXECUTE"
    log.ok(f"план построен: {len(tasks)} задач: "
           + ", ".join(f"{t['id']}->{t.get('goal_id')}" for t in tasks))


def _rc_tail(limit=1500):
    """Последние согласованные изменения плана, а не весь журнал."""
    p = paths.PROJECT_ROOT / "docs" / "roadmap-changes.md"
    if not p.exists():
        return "(журнала RC нет)"
    txt = p.read_text(encoding="utf-8", errors="replace")
    parts = re.split(r"(?=^### RC-)", txt, flags=re.M)
    accepted = [p for p in parts if re.search(
        r"^[-* ]*\*\*Статус:\*\*\s*принято\b", p, flags=re.M | re.I)]
    tail = "\n".join(accepted[-2:]).strip() or "(принятых RC нет)"
    return tail[-limit:] if len(tail) > limit else tail


def _stage_scope(g):
    text = _read_ctx("docs/scope.md", 30000)
    match = re.fullmatch(r"этап([1-6])", str((g.get("stage") or {}).get("id", "")))
    if not match:
        return (_ACTIVE_REQUEST or {}).get("scope_quote", "см. docs/scope.md")
    section = re.search(rf"^### Этап {match[1]}\. .*?(?=^### Этап |\Z)", text, re.M | re.S)
    return section[0] if section else "нормативный раздел не найден; этап нельзя закрыть"


def _parse_yaml_list(text):
    t = text.strip()
    m = re.search(r"```(?:ya?ml)?\s*(.*?)\s*```", t, re.S)
    if m:
        t = m.group(1)
    data = yaml.safe_load(t)
    return data if isinstance(data, list) else data.get("tasks", [])


def _validate_tasks(data, g=None):
    out = []
    seen = set()
    open_ids = [t["id"] for t in goals_mod.open_targets(g)] if g else []
    for t in data or []:
        if not isinstance(t, dict) or "id" not in t or "goal" not in t:
            raise ValueError("задача должна содержать id и goal")
        if not isinstance(t["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", t["id"]):
            raise ValueError("небезопасный id задачи")
        if t["id"] in seen:
            raise ValueError(f"повтор id задачи {t['id']}")
        seen.add(t["id"])
        closes = t.get("closes")
        if closes is None:
            raise ValueError(
                f"задача {t['id']}: отсутствует обязательное поле closes; "
                "ожидается roadmap:этапN-шагM или LG-YYYY-MM-DD-NN")
        if not isinstance(closes, str) or not re.fullmatch(
                r"(?:roadmap:этап\d+-шаг\d+|LG-\d{4}-\d{2}-\d{2}-\d{2})", closes):
            raise ValueError(
                f"задача {t['id']}: неверный формат closes={closes!r}; "
                "ожидается roadmap:этапN-шагM или LG-YYYY-MM-DD-NN")
        if g is not None:
            goal_id = str(t.get("goal_id") or "").strip()
            known = goals_mod.target(g, goal_id) if goal_id else None
            if known is None or (known.get("status") != "open" and t.get("status") != "done"):
                raise ValueError(f"задача {t['id']}: goal_id должен ссылаться на открытую цель")
            t["goal_id"] = goal_id
        if not isinstance(t.get("acceptance"), list) or not t["acceptance"]:
            raise ValueError(f"задача {t['id']}: пустой acceptance запрещён")
        if t.get("kind") == "measurement" and t.get("execution") != "approved_commands":
            raise ValueError(f"задача {t['id']}: измерение требует approved_commands")
        if t.get("execution") == "approved_commands":
            commands = t.get("commands")
            if not isinstance(commands, list) or not commands or not all(
                    isinstance(c, str) and c.strip() for c in commands):
                raise ValueError(f"задача {t['id']}: отсутствуют утверждаемые команды")
        t.setdefault("max_iter", 2)
        t.setdefault("inputs", [])
        t.setdefault("hint", "")
        t.setdefault("status", "pending")
        out.append(t)
    return out


def _current_task(st):
    for t in st["tasks"]:
        if t.get("status") == "pending":
            return t
    return None


def _sync_plan(st, *, strict=False):
    """Держать night_plan.yaml в согласии со STATE: иначе done-задачи
    остаются pending и следующая ночь запускает их заново."""
    try:
        tmp = PLAN_FILE.with_suffix(".tmp")
        tmp.write_text(yaml.safe_dump(st.get("tasks") or [], allow_unicode=True,
                                     sort_keys=False), encoding="utf-8")
        tmp.replace(PLAN_FILE)
    except OSError:
        if strict:
            raise


def _finish_task(st, task, status, reason=None):
    """Завершить задачу и передать её менеджеру, а не сразу в следующую."""
    task["status"] = status
    for key in ("verify_file", "receipt", "verify_fingerprint"):
        if (st.get("task") or {}).get(key):
            task[key] = st["task"][key]
    st["task"] = None
    _sync_plan(st)
    st["manager_context"] = {
        "task_id": task["id"],
        "goal_id": task.get("goal_id"),
        "status": status,
        "reason": reason,
        "verify_pass": (task.get("verify") or {}).get("pass"),
    }
    st["phase"] = "MANAGER"


def _fits_tick(task, deadline=None, now=None):
    """Влезает ли задача в остаток тика с запасом на PLAN/VERIFY/REPORT.

    time_limit_minutes без этой проверки было пожеланием: команда могла
    стартовать за минуту до конца тика, и утро оставалось без отчёта.
    """
    limit_min = float(task.get("time_limit_minutes") or 0)
    if not limit_min or not deadline:
        return True
    left_min = (deadline - (now if now is not None else time.time())) / 60
    return left_min >= limit_min + 2


def _defer_task(st, task, reason, log):
    """Задача не влезает в остаток тика: не начинать её в последние минуты.

    Иначе команда стартует за минуту до дедлайна, тик заканчивается посреди
    работы, и утро получает ночь без отчёта. Отложенная задача вернётся
    в pending при переиспользовании плана, а не потеряется.
    """
    task["status"] = "deferred"
    task["deferred_reason"] = reason[:300]
    st["task"] = None
    _sync_plan(st)
    st["deferred"] = (st.get("deferred") or [])[-4:] + [task["id"]]
    events.emit("task_deferred", task_id=task["id"], reason=reason[:200])
    log.warn(f"{task['id']}: отложена — {reason}")
    st["phase"] = "EXECUTE"


def _require_approval(st, log, *, return_to_plan=False):
    if _approval_ok() and _plan_sha256(st.get("tasks")) == _plan_sha256():
        return True
    log.warn("одобрение плана отсутствует/устарело — выполнение запрещено")
    st["phase"] = "PLAN" if return_to_plan and not _ACTIVE_REQUEST else "REPORT"
    if st["phase"] == "REPORT":
        st["needs_human"] = "STATE без действующего одобрения; требуется проверка перед новым запуском"
    return False


def _guard_recovered_state(st):
    """Не повторять побочные эффекты после обрыва: произвольный resume не поддержан."""
    from . import request_research
    pending = bool(_ACTIVE_REQUEST and request_research.pending_update(_ACTIVE_REQUEST).exists())
    if (pending or st.get("phase") in ("VERIFY", "REVIEW", "MANAGER", "REPAIR")
            or (st.get("phase") == "EXECUTE" and st.get("task"))):
        st["needs_human"] = ("найден незавершённый STATE; автоматическое восстановление "
                             "запрещено, сохранить артефакты и проверить вручную")
        st["phase"] = "REPORT"


def _verified_result(task, current):
    """Вердикт должен относиться к этой задаче, режиму и неизменным артефактам."""
    try:
        fp = paths.resolve(current["verify_file"])
        fp.relative_to(paths.WORKSPACE / "verdicts")
        if current.get("verify_fingerprint") != evidence.fingerprint(current["verify_file"]):
            return None
        verdict = json.loads(fp.read_text(encoding="utf-8"))
        if (verdict.get("task_id") != task["id"]
                or verdict.get("task_sha256") != _plan_sha256([task])
                or verdict.get("mock") is not bool(env.get("AUTONOMY_MOCK"))
                or verdict.get("receipt") != current.get("receipt")):
            return None
        if "verify" in current and current["verify"] != verdict:
            return None
        if verdict.get("artifacts") != [evidence.fingerprint(p) for p in evidence.outputs(task)]:
            return None
        if _ACTIVE_REQUEST and verdict.get("input_artifacts") != [
                evidence.fingerprint(p) for p in task.get("inputs", [])]:
            return None
        if task.get("execution") == "approved_commands" and not evidence.validate(
                current.get("receipt"), task, _plan_sha256([task]))[0]:
            return None
        return verdict
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


@_audited_context
def phase_execute(cfg, st, log, rt):
    if st.get("paid_work_blocked"):
        st["needs_human"] = "платная работа заблокирована ошибкой учёта; требуется ручная проверка"
        st["phase"] = "REPORT"
        return
    if not _require_approval(st, log, return_to_plan=True):
        st["task"] = None
        return
    task = _current_task(st)
    if task is None:
        st["phase"] = "REPORT"
        return
    if _ACTIVE_REQUEST:
        statuses = {t["id"]: t.get("status") for t in st["tasks"]}
        dependencies = [t for t in st["tasks"] if t["id"] in task.get("depends_on", [])]
        if (any(statuses.get(tid) != "done" for tid in task.get("depends_on", []))
                or any(_verified_result(t, t) is None for t in dependencies)):
            st["needs_human"] = "ответ не создаётся: сбор источников не принят"
            st["phase"] = "REPORT"
            return
    adaptive = bool(_ACTIVE_REQUEST and _ACTIVE_REQUEST["spec"].get("research_policy"))
    lane = "sources" if task.get("execution") == "approved_commands" else "answer"
    fitting_task = task
    if adaptive:
        left = request_limits.remaining(_ACTIVE_REQUEST, st, lane)
        if left <= 0:
            st["needs_human"] = f"общий бюджет времени {lane} исчерпан; новый вызов не разрешён"
            st["phase"] = "REPORT"
            return
        fitting_task = dict(task, time_limit_minutes=min(float(task.get("time_limit_minutes", left / 60)), left / 60))
    if st.get("task") is None or st["task"]["id"] != task["id"]:
        if not _fits_tick(fitting_task, _DEADLINE):
            left_min = (_DEADLINE - time.time()) / 60
            _defer_task(st, task,
                        f"до конца тика {left_min:.0f} мин, задаче нужно "
                        f"{float(task.get('time_limit_minutes') or 0):.0f} мин + фазы", log)
            return
        st["task"] = {"id": task["id"], "iter": 0, "errors": [], "mentor_note": None,
                      "started_ts": time.time()}
        st["snapshot"] = "before"
        SNAP_FILE.write_text(json.dumps(manifest.snapshot(cfg)), encoding="utf-8")
        events.emit("task_start", task_id=task["id"], goal=str(task.get("goal", ""))[:200])
        log.step(f"EXECUTE задача={task['id']}")

    it = st["task"]["iter"]
    max_it = task.get("max_iter", 2)
    if it >= max_it:
        log.warn(f"{task['id']}: исчерпаны итерации ({max_it})")
        events.emit("task_end", task_id=task["id"], status="failed",
                    reason="итерации исчерпаны", iter=it)
        _finish_task(st, task, "failed", "итерации исчерпаны")
        return

    try:
        input_context = (_request_author_inputs(task, cfg, it)
                         if _ACTIVE_REQUEST and task.get("execution") == "document_only"
                         else "\n".join(f"--- {p} ---\n" + _read_ctx(p, int(cfg["night"].get("input_chars_per_file", 8000)))
                                        for p in task.get("inputs", [])))
    except (ValueError, OSError, TypeError, KeyError) as error:
        if isinstance(error, context_packets.ContextError):
            raise
        st["needs_human"] = f"авторский пакет доказательств отклонён: {type(error).__name__}; модель не вызвана"
        st["phase"] = "REPORT"
        return
    context = (
        "=== АКТУАЛЬНЫЕ ОГРАНИЧЕНИЯ ===\n" + _read_ctx("docs/agent-context.md", 16000, required=True)
        + "\n=== ЗАДАЧА ===\n" + yaml.safe_dump(task, allow_unicode=True, sort_keys=False)
        + "\n=== РАЗРЕШЁННЫЕ ПУТИ ДЛЯ ЗАПИСИ ===\n"
        + "\n".join(cfg["sandbox"]["allowed_write_paths"])
        + "\n=== ВХОДНЫЕ ФАЙЛЫ ===\n"
        + input_context
    )
    if st["task"].get("mentor_note"):
        context += f"\n=== УКАЗАНИЕ МЕНТОРА (учесть!) ===\n{st['task']['mentor_note']}\n"
    if (_ACTIVE_REQUEST and task.get("execution") == "document_only"
            and task.get("id") == "answer-mentor" and st.get("request_force_partial")):
        context += ("\n=== ОБЯЗАТЕЛЬНЫЙ ЧАСТИЧНЫЙ РЕЗУЛЬТАТ ===\n"
                    "Дополнительный поиск запрещён: лимит followup исчерпан. "
                    "Напиши ЧАСТИЧНЫЙ РЕЗУЛЬТАТ; в decision.json укажи "
                    "decision.completion_status=partial, limitations и gap для непокрытых тем "
                    "из-за запрета дополнительного поиска. Не утверждай полноту. Причина REVIEW: "
                    + str(st["request_force_partial"].get("reason", "")) + "\n")
    if st["task"]["errors"]:
        context += ("\n=== ОШИБКИ ПРОШЛЫХ ИТЕРАЦИЙ (не повторяй их) ===\n"
                     + "\n\n".join(st["task"]["errors"][-3:]))
    if st["task"].get("validation_feedback"):
        context += ("\n=== ПОЛНАЯ АДРЕСНАЯ ДИАГНОСТИКА ПРЕДЫДУЩЕГО ОТВЕТА ===\n"
                    + json.dumps(st["task"]["validation_feedback"], ensure_ascii=False)
                    + "\nИсправь все перечисленные claims и согласуй response/claims/coverage. "
                      "Не заменяй source URL или цитату на несохранённую страницу ради прохождения проверки.")

    messages = [{"role": "system", "content": prompts.EXECUTOR},
                {"role": "user", "content": context}]
    # Grace-период: Strata грузит модель ~20 мин и в это время gateway даёт 502.
    # Ждём восстановления вместо трёх дорогих провалов.
    try:
        if task.get("execution") == "approved_commands":
            # Известный измерительный протокол не переписывается моделью.
            # Исполняются ровно команды, которые видел критик; ноль LLM-вызовов.
            plan = {"files": {}, "commands": task["commands"],
                    "summary": "утверждённый протокол без LLM"}
            res = None
        else:
            if isinstance(rt, _ContextRouter):
                rt.preflight(st, messages)
            if _ACTIVE_REQUEST and task.get("execution") == "document_only":
                from . import request_research
                policy = request_research.policy(_ACTIVE_REQUEST)
                if policy:
                    used = st.get("request_answer_attempts", 0)
                    if used >= policy["answer_attempts"]:
                        st["needs_human"] = "исчерпан общий лимит попыток ответа по поручению"
                        st["phase"] = "REPORT"
                        return
                    st["request_answer_attempts"] = used + 1
                    if isinstance(rt, _ContextRouter):
                        try:
                            rt.prepare('executor', st, messages)
                        except context_packets.ContextError:
                            if used:
                                st['request_answer_attempts'] = used
                            else:
                                st.pop('request_answer_attempts', None)
                            raise
                    state_mod.save(st)
            try:
                scope = request_limits.account(_ACTIVE_REQUEST, st, "answer", save=state_mod.save) if adaptive else nullcontext()
                with scope:
                    res = rt.call("executor", st, messages, max_tokens=_role_max(cfg, "executor", 48000), temperature=0.2)
            except request_limits.TimeBudgetExceeded as e:
                st["needs_human"] = "исчерпан общий бюджет ответа: " + str(e)[:150]
                st["phase"] = "REPORT"
                return
    except providers.ProviderError as e:
        if adaptive and e.kind == "time_budget":
            st["needs_human"] = "авторский вызов остановлен по общему дедлайну; поздний ответ не принят"
            st["phase"] = "REPORT"
            return
        if "local" not in str(e) or st["task"].get("grace_used"):
            raise
        grace_min = cfg["night"].get("local_load_grace_min", 25)
        st["task"]["grace_used"] = True
        log.warn(f"local недоступен — жду до {grace_min} мин (возможно, грузится модель)")
        events.emit("local_grace_wait", task_id=task["id"], grace_min=grace_min,
                    reason=str(e)[:150])
        deadline = time.time() + grace_min * 60
        revived = False
        while time.time() < deadline:
            lock.heartbeat(_H)
            time.sleep(60)
            if providers.health("local", cfg["providers"]["local"]):
                revived = True
                break
        if not revived:
            raise providers.ProviderError(
                f"local не ожил за {grace_min} мин (502/health fail) — "
                f"нужно вручную загрузить модель в Strata", "provider")
        log.ok("local ожил — повторяю вызов исполнителя")
        res = rt.call("executor", st, messages, max_tokens=_role_max(cfg, "executor", 48000), temperature=0.2)
    st["task"]["iter"] += 1

    if res is not None and res.finish == "length":
        _note_error(st, "ответ исполнителя обрезан по лимиту токенов (finish_reason=length). "
                       "В следующий раз: пиши один файл за итерацию, код компактно, без длинных "
                       "комментариев; остаток — следующей итерацией.")
        return

    try:
        if res is not None:
            plan = extract_json(res.text)
    except ValueError as e:
        _note_error(st, f"не разобран JSON ответа исполнителя: {e}. "
                        f"Верни СТРОГО один JSON-объект, без текста до и после.")
        return

    # --- scope guard: файлы и команды ---
    bad = []
    if task.get("execution") == "document_only" and plan.get("commands"):
        bad.append("документное задание не разрешает команды/установки от executor")
    if _ACTIVE_REQUEST and task.get("execution") == "document_only":
        from . import intake
        permitted = {intake.output_dir(_ACTIVE_REQUEST) / n
                     for n in ("response.md", "claims.json", "decision.json")}
        if any(paths.resolve(p) not in permitted for p in plan.get("files", {})):
            bad.append("executor может писать только три файла ответа, не источники/STATE/approval")
    for rel in plan.get("files", {}):
        if not paths.writable(rel, cfg):
            bad.append(f"файл вне песочницы: {rel}")
            st["violations"].append({"task": task["id"], "kind": "write_scope", "path": rel})
    receipt_dir, receipt = evidence.begin(task, _plan_sha256([task]),
                                          mock=bool(env.get("AUTONOMY_MOCK")))
    for cmd in plan.get("commands", []):
        if not paths.command_allowed(cmd, cfg):
            bad.append(f"запрещённая команда: {cmd}")
            st["violations"].append({"task": task["id"], "kind": "command", "cmd": cmd})
    if bad:
        for b in bad:
            events.emit("violation", task_id=task["id"], detail=b[:150])
        _note_error(st, "нарушение границ:\n" + "\n".join(bad))
        return

    # --- запись файлов ---
    write_errors = []
    try:
        scope = request_limits.account(_ACTIVE_REQUEST, st, "answer", save=state_mod.save) if adaptive and plan.get("files") else nullcontext()
        with scope:
            for rel, content in plan.get("files", {}).items():
                fp = paths.resolve(rel)
                if fp.is_dir():
                    write_errors.append(f"файл не может быть директорией: {rel}")
                    continue
                stub = _content_stub_reason(rel, content)
                if stub:
                    write_errors.append(f"{rel}: {stub} — файл НЕ записан, верни полное содержимое")
                    events.emit("stub_blocked", task_id=task["id"], path=rel, reason=stub)
                    log.warn(f"заглушка отклонена: {rel} ({stub})")
                    continue
                try:
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    saved = _backup_before_write(rel, fp)
                    fp.write_text(content, encoding="utf-8")
                    log.log(f"записан {rel} ({len(content)} симв.)"
                            + (f", копия прежней версии: {saved.relative_to(paths.PROJECT_ROOT)}"
                               if saved else ""))
                except OSError as e:
                    write_errors.append(f"не удалось записать {rel}: {e}")
    except request_limits.TimeBudgetExceeded:
        st["needs_human"] = "общий бюджет ответа исчерпан при записи; черновики не приняты"
        st["phase"] = "REPORT"
        return
    if write_errors:
        _note_error(st, "ошибки записи файлов:\n" + "\n".join(write_errors)
                    + "\nУказывай ПОЛНЫЙ путь к файлу с именем и расширением, не к директории.")
        return
    if plan.get("summary"):
        log.log(f"summary: {plan['summary'][:300]}")

    # --- запуск команд ---
    failed = []
    last_output = ""
    from . import shellutil
    import shutil
    free_gb = shutil.disk_usage(str(paths.PROJECT_ROOT)).free / 1e9
    if free_gb < 10:
        _note_error(st, f"на диске осталось {free_gb:.1f} ГБ — скачивание запрещено, "
                        f"работай только с существующими файлами")
        return
    for cmd in plan.get("commands", []):
        lock.heartbeat(_H)
        # Бюджет задачи из плана (time_limit_minutes) — реальный, а не пожелание:
        # без него команда могла идти 30 минут при плане 20 и выбить тик.
        limit_min = task.get("time_limit_minutes")
        remaining = None
        if limit_min:
            spent = time.time() - float(st["task"].get("started_ts") or time.time())
            remaining = float(limit_min) * 60 - spent
            if remaining <= 15:
                failed.append(f"команда `{cmd}` не запущена: бюджет задачи "
                              f"{limit_min} мин исчерпан ({spent / 60:.1f} мин)")
                log.warn(f"бюджет задачи {limit_min} мин исчерпан — команда не запущена")
                break
        if adaptive:
            shared_left = request_limits.remaining(_ACTIVE_REQUEST, st, "sources")
            remaining = min(remaining, shared_left) if remaining is not None else shared_left
            if remaining <= 0:
                failed.append("общий бюджет сбора источников исчерпан; следующая команда не запущена")
                break
            if st.get("request_sources_attempted", 0) >= _ACTIVE_REQUEST["spec"]["research_policy"]["max_queries"]:
                failed.append("общий лимит запросов поручения исчерпан")
                break
        log.log(f"$ {cmd}")
        command_started_ns = time.time_ns()
        try:
            timeout = 1800 if remaining is None else max(30, int(min(1800, remaining)))
            scope = request_limits.account(_ACTIVE_REQUEST, st, "sources", save=state_mod.save) if adaptive else nullcontext()
            with scope as shared_seconds:
                if adaptive:
                    timeout = min(float(timeout), shared_seconds)
                    st["request_sources_attempted"] = st.get("request_sources_attempted", 0) + 1
                    state_mod.save(st)
                try:
                    r = shellutil.run_command(cmd, str(paths.PROJECT_ROOT), timeout=timeout)
                finally:
                    _sync_reader_usage(cfg, st)
            evidence.record_command(receipt_dir, receipt, cmd, r, command_started_ns)
            tail_out = (r.stdout or "")[-2000:]
            tail_err = (r.stderr or "")[-2000:]
            if r.returncode != 0:
                failed.append(f"команда `{cmd}` rc={r.returncode}\nSTDERR: {tail_err}")
                last_output = tail_err
                log.error(f"rc={r.returncode}: {tail_err[:200]}")
                if _ACTIVE_REQUEST and task.get("execution") == "approved_commands":
                    log.warn("сбор поручения остановлен на первой ошибке; остальные запросы не расходуются")
                    break
            else:
                last_output = tail_out
                log.ok(f"rc=0: {tail_out[-200:]}")
        except request_limits.TimeBudgetExceeded:
            evidence.record_command(receipt_dir, receipt, cmd,
                                    subprocess.CompletedProcess(cmd, -1, "", "shared request time budget exhausted"),
                                    command_started_ns, status="timeout")
            failed.append("общий бюджет сбора источников исчерпан; результат не принят")
            last_output = "TIME_BUDGET"
            break
        except subprocess.TimeoutExpired as exc:
            evidence.record_command(receipt_dir, receipt, cmd,
                                    subprocess.CompletedProcess(cmd, -1, exc.stdout, exc.stderr),
                                    command_started_ns, status="timeout")
            failed.append(f"команда `{cmd}`: таймаут {timeout}s")
            last_output = "TIMEOUT"
            break
        except ValueError:
            evidence.record_command(receipt_dir, receipt, cmd,
                                    subprocess.CompletedProcess(cmd, -1, "", "reader accounting rejected"),
                                    command_started_ns, status="budget_error")
            failed.append("учёт reader-бюджета отклонён; дальнейшие команды запрещены")
            last_output = "READER_BUDGET_ERROR"
            break
        except OSError as exc:
            evidence.record_command(receipt_dir, receipt, cmd,
                                    subprocess.CompletedProcess(cmd, -1, "", str(exc)),
                                    command_started_ns, status="launch_error")
            failed.append(f"команда `{cmd}`: ошибка запуска {type(exc).__name__}")
            last_output = "LAUNCH_ERROR"
            break
    st["task"]["receipt"] = evidence.finish(receipt_dir, receipt, task)
    st["task"]["last_output"] = evidence.redact(last_output[-1500:])
    if failed:
        _note_error(st, "\n".join(failed))
    else:
        st["phase"] = "VERIFY"


def _note_error(st, msg):
    st["task"]["errors"].append(msg[:3000])
    stuck = state_mod.record_action(st, st["task"]["id"], "execute", msg[:200])
    if stuck:
        st["phase"] = "REPAIR"
        st["last_error"] = "STUCK: цикл исполнителя"
    # фаза остаётся EXECUTE — следующая итерация с фидбеком


def phase_verify(cfg, st, log, rt):
    if not _require_approval(st, log):
        return
    task = next(t for t in st["tasks"] if t["id"] == st["task"]["id"])
    log.step(f"VERIFY задача={task['id']}")
    verdict = verify.run_checks(task, cfg)
    if task.get("execution") == "approved_commands":
        ok, detail = evidence.validate(st["task"].get("receipt"), task, _plan_sha256([task]))
        verdict["checks"].append({"check": {"execution_receipt": True}, "ok": ok, "detail": detail})
        verdict["pass"] = verdict["pass"] and ok
    verdict["receipt"] = st["task"].get("receipt")
    verdict["task_sha256"] = _plan_sha256([task])
    verdict["mock"] = bool(env.get("AUTONOMY_MOCK"))
    verdict["artifacts"] = [evidence.fingerprint(p) for p in evidence.outputs(task)]
    if _ACTIVE_REQUEST:
        verdict["input_artifacts"] = [evidence.fingerprint(p) for p in task.get("inputs", [])]

    before = json.loads(SNAP_FILE.read_text(encoding="utf-8")) if SNAP_FILE.exists() else {}
    d = manifest.diff(before, manifest.snapshot(cfg))
    # out-of-scope изменения, которые сделал не runner (страховка)
    violations = []
    for f in d["added"] + d["modified"] + d["deleted"]:
        if not paths.writable(f, cfg):
            st["violations"].append({"task": task["id"], "kind": "changed_out_of_scope", "path": f})
            violations.append(f)
    if violations:
        verdict["pass"] = False
        verdict["checks"].append({"check": {"write_scope": True}, "ok": False,
                                  "detail": ", ".join(violations)})
    verdict["diff"] = {k: v for k, v in d.items()}
    verdict["changed_anything"] = manifest.any_change(d)
    if not verdict["changed_anything"] and task.get("acceptance"):
        verdict["pass"] = False
        verdict["checks"].append({"check": {"no_changes": True}, "ok": False,
                                  "detail": "модель ничего не изменила — заявка без работы"})
    # Анти-заглушка: артефакт сам признаёт, что работа не выполнялась.
    # Честное unverified/не измерялось в claim/decision — не фиктивный замер.
    stub_hits = [] if task.get("execution") == "document_only" else _stub_scan(
        d.get("added", []) + d.get("modified", []))
    if stub_hits:
        verdict["pass"] = False
        verdict["checks"].append({"check": {"stub_markers": True}, "ok": False,
                                  "detail": "в артефактах признание незавершенности: "
                                            + "; ".join(stub_hits[:5])})
        log.warn(f"stub-маркеры: {stub_hits[:3]}")
    fp = verify.write_result(task["id"], verdict)
    st["task"]["verify_file"] = str(fp.relative_to(paths.PROJECT_ROOT)).replace("\\", "/")
    st["task"]["verify_fingerprint"] = evidence.fingerprint(st["task"]["verify_file"])
    st["task"]["verify"] = verdict
    log.log(f"verify: pass={verdict['pass']} ({fp.name})")
    state_mod.record_action(st, task["id"], "verify", json.dumps(verdict.get("checks", []))[:200])
    if violations:
        st["needs_human"] = "обнаружены изменения вне разрешённых путей; требуется проверка владельца"
        st["phase"] = "REPORT"
    else:
        st["phase"] = "REVIEW"


def _request_followup(st, full_task, out, model, log):
    """Only typed queries; original card, completed receipts and caps stay fixed."""
    from . import intake, request_research
    if not request_research.policy(_ACTIVE_REQUEST):
        return False
    try:
        policy = request_research.policy(_ACTIVE_REQUEST)
        if st.get("request_answer_attempts", 0) >= policy["answer_attempts"]:
            raise ValueError("answer attempt budget exhausted; do not spend more searches")
        if request_limits.remaining(_ACTIVE_REQUEST, st, "answer") <= 0:
            raise ValueError("shared research work time exhausted")
        if _DEADLINE and time.time() + 2 * 60 > _DEADLINE:
            raise ValueError("not enough tick time for followup and answer")
        if (set(out) - {"verdict", "reason", "research_queries"} or st.get("violations")
                or not ((full_task["id"] == "answer-mentor" and full_task.get("execution") == "document_only")
                        or (full_task["id"].startswith("collect-sources")
                            and full_task.get("execution") == "approved_commands"))):
            raise ValueError("invalid followup request or sandbox violation")
        for task in st["tasks"]:
            if task["id"].startswith("collect-sources") and task.get("status") == "done":
                v = _verified_result(task, task)
                if not v or not v.get("pass"):
                    raise ValueError("previous source evidence changed")
        current = _verified_result(full_task, st["task"])
        if not current or full_task["id"].startswith("collect-sources") and not current.get("pass"):
            raise ValueError("current collection has no valid receipt")
        research_plan = request_research.read_plan(_ACTIVE_REQUEST)
        if research_plan["followup_rounds"] >= policy["max_followup_rounds"]:
            if full_task["id"] == "answer-mentor" and st["task"].get("iter", 0) >= full_task.get("max_iter", 2):
                raise ValueError("answer iteration budget exhausted")
            st["request_force_partial"] = {"reason": out["reason"], "task_id": full_task["id"]}
            if full_task["id"].startswith("collect-sources"):
                _finish_task(st, full_task, "done", "verified collection; followup cap requires partial answer")
            else:
                st["phase"] = "EXECUTE"
            return True
        if request_limits.remaining(_ACTIVE_REQUEST, st, "sources") <= 0:
            raise ValueError("shared research work time exhausted")
        done = [dict(t) for t in st["tasks"] if t.get("status") == "done"]
        if full_task["id"].startswith("collect-sources"):
            accepted = dict(full_task, status="done")
            for key in ("verify_file", "receipt", "verify_fingerprint"):
                if key in st["task"]:
                    accepted[key] = st["task"][key]
            done.append(accepted)
        request_research.begin_update(_ACTIVE_REQUEST)
        request_research.propose(_ACTIVE_REQUEST,
                                 {"queries": out.get("research_queries"), "reason": out.get("reason")},
                                 model, "followup")
        revised = _validate_tasks(request_research.rebuild(_ACTIVE_REQUEST, done), goals_mod.load())
        st["tasks"], st["task"] = revised, None
        st["plan_author_model"] = model
        st["request_replan_pending"] = True
        st["phase"] = "PLAN"
        APPROVAL_FILE.unlink(missing_ok=True)
        _sync_plan(st, strict=True)
        request_research.commit_update(_ACTIVE_REQUEST, st)
        events.emit("request_followup", request_id=_ACTIVE_REQUEST["spec"]["id"],
                    queries=len(out["research_queries"]), author_model=model)
        log.log("дополнительные запросы в пределах поручения; нужен новый независимый critic")
    except (ValueError, TypeError, KeyError, OSError) as e:
        st["needs_human"] = "дополнительный поиск отклонён: " + str(e)[:200]
        st["phase"] = "REPORT"
    return True


@_audited_context
def phase_review(cfg, st, log, rt):
    if not _require_approval(st, log):
        return
    task = st["task"]
    full_task = next(t for t in st["tasks"] if t["id"] == task["id"])
    if _verified_result(full_task, task) is None:
        st["needs_human"] = "вердикт проверки не привязан к задаче или артефакты изменились"
        st["phase"] = "REPORT"
        return
    log.step(f"REVIEW задача={task['id']}")
    v = task.get("verify", {})
    if (_ACTIVE_REQUEST and full_task.get("execution") == "approved_commands"
            and not v.get("pass")
            and any("research_collection" in check for check in full_task.get("acceptance", []))):
        st["needs_human"] = "сбор не содержит принятых страниц либо manifest некорректен; ответ не создаётся"
        _finish_task(st, full_task, "failed", "collection validation failed; no author or semantic call")
        st["phase"] = "REPORT"
        return
    if _ACTIVE_REQUEST and full_task["id"] == "answer-mentor" and not v.get("pass"):
        # Do not spend a semantic-review call on deterministically invalid output.
        task["validation_feedback"] = {"schema_version": 1, "failed_checks": [
            {"check": row.get("check"), "detail": row.get("detail")}
            for row in v.get("checks", []) if not row.get("ok")]}
        _note_error(st, "Детерминированная приёмка ответа не пройдена; исправь полный validation_feedback.")
        st["phase"] = "EXECUTE"
        return
    context = json.dumps({
        "task_goal": full_task.get("goal"),
        "task_hint": full_task.get("hint"),
        "task_acceptance": v.get("checks", []),
        "verify_pass": v.get("pass"),
        "diff": v.get("diff"),
        "last_output_tail": (task.get("last_output") or "")[-1500:],
        "errors": task.get("errors", [])[-2:],
    }, ensure_ascii=False, allow_nan=False)
    if _ACTIVE_REQUEST:
        from . import request_research
        context += "\n=== ПЕРЕДАННОЕ ЗАДАНИЕ ===\n" + json.dumps(_ACTIVE_REQUEST, ensure_ascii=False)
        if full_task["id"] == "answer-mentor":
            from . import intake
            for name in ("response.md", "claims.json", "decision.json"):
                fp = intake.output_dir(_ACTIVE_REQUEST) / name
                limit = 24000 if name == 'response.md' else 160000 if name == 'claims.json' else 60000
                context += f"\n=== {name} (ПОЛНОСТЬ ОБЯЗАТЕЛЬНА) ===\n" + _read_ctx(str(fp), limit, required=True)
            if request_research.policy(_ACTIVE_REQUEST):
                try:
                    context += "\n=== КОНТЕКСТ ВСЕХ ИСПОЛЬЗОВАННЫХ ЦИТАТ ===\n" + request_research.evidence_bundle(_ACTIVE_REQUEST)
                except (ValueError, KeyError, TypeError, OSError) as e:
                    task["validation_feedback"] = getattr(e, "diagnostics", {
                        "schema_version": 1, "errors": [{"claim_id": None,
                        "codes": ["review_evidence_unavailable"]}],
                        "limitation": "Current REVIEW evidence could not be built; prior feedback replaced"})
                    _note_error(st, "неполный пакет доказательств для REVIEW; см. validation_feedback: " + str(e)[:200])
                    st["phase"] = "EXECUTE"
                    return  # bounded author repair; never PASS unseen quote context
        # REVIEW collection must see the pages, not merely successful stdout.
        names = list(full_task.get("inputs", [])) + evidence.outputs(full_task)
        if (any(name.endswith('.md.json') and '/sources-' in name for name in names)
                and not (full_task['id'] == 'answer-mentor' and request_research.policy(_ACTIVE_REQUEST))):
            from . import author_evidence
            try:
                packed = author_evidence.author_bundle(_ACTIVE_REQUEST, list(dict.fromkeys(names)))
            except (ValueError, OSError, TypeError, KeyError):
                raise context_packets.ContextError('collection_review_evidence_unavailable') from None
            _record_selected_evidence(packed)
            context += ('\n=== ПРОЧИТАННЫЕ СТРАНИЦЫ: ЯВНЫЕ ВЫДЕРЖКИ И ПРОПУСКИ ===\n' + packed
                        + '\nЭто обзор доступности/покрытия, не научная приёмка непоказанных частей источника.')
        if full_task["id"] == "answer-mentor":
            context += ("\nПроверь все requirements, контекст русского CPU-проекта, смысл цитат, "
                        "переносимость измерений, отсутствие безусловных первых/единственных. "
                        "Наличие цитаты не доказывает вывод. Карта меняется только предложением; "
                         "PASS не означает отправку или закрытие этапа. При сомнении ESCALATE.")
        if request_research.policy(_ACTIVE_REQUEST):
            context += (
                "\nОцени покрытие ВСЕХ research_policy.topics, смысл цитат и соответствие closes. "
                "Количество страниц/доменов не доказывает независимость исследований. "
                "Если нужны новые источники, верни ровно JSON "
                '{"verdict":"SEARCH","reason":"какой пробел и почему",'
                '"research_queries":["новый запрос"]}. Это предложение, не выполнение поиска. '
                "Не повторяй уже выполненные запросы. Исправимые ошибки текста при достаточных "
                "источниках — FAIL с конкретными правками; опасные действия/выход за бюджет — ESCALATE. "
                "Если все требования и проверки выполнены — PASS. Остаток поискового плана:\n"
                + _request_limits_context(cfg, st))
            if full_task["id"] == "answer-mentor":
                context += (
                    "\nЧастичный материал — не PASS: если decision.completion_status=partial, "
                    "проверь все имеющиеся цитаты, честность ограничений и пробелов; "
                    "верни PARTIAL только для корректного частичного материала. "
                    "Если дополнительный поиск ещё полезен и разрешён — SEARCH, "
                    "если некорректны цитаты/ограничения — FAIL/ESCALATE. "
                    "PARTIAL не закрывает поручение и не требует ослаблять полные критерии.")
    res = rt.call("verifier", st, [
        {"role": "system", "content": prompts.VERIFIER},
        {"role": "user", "content": context},
    ], max_tokens=_role_max(cfg, "verifier", 8000), temperature=0.1)
    try:
        from . import request_research
        adaptive = bool(_ACTIVE_REQUEST and request_research.policy(_ACTIVE_REQUEST))
        raw = json.loads(res.text) if adaptive else extract_json(res.text)
        out = request_research.review_output(raw, adaptive)
        verdict = out["verdict"]
    except (ValueError, KeyError, TypeError, AttributeError):
        verdict, out = "ESCALATE", {"reason": "контролёр вернул невалидную схему JSON"}
    log.log(f"вердикт контролёра: {verdict} — {out.get('reason', '')[:200]}")
    if _verified_result(full_task, task) is None:
        st["needs_human"] = "артефакты/вердикт изменились во время REVIEW; приёмка запрещена"
        st["phase"] = "REPORT"
        return
    if _ACTIVE_REQUEST and verdict == "SEARCH":
        if _request_followup(st, full_task, out, res.model, log):
            return
        verdict = "ESCALATE"  # legacy card did not authorize adaptive research
    if _ACTIVE_REQUEST and verdict in ("PASS", "PARTIAL"):
        from . import intake, request_research
        if full_task["id"] == "answer-mentor" and request_research.policy(_ACTIVE_REQUEST):
            try:
                checked = intake.check_response(_ACTIVE_REQUEST["spec"]["id"])
                completion = checked["completion_status"]
            except (ValueError, KeyError, TypeError, OSError) as e:
                _note_error(st, "проверка исхода: " + str(e)[:200])
                st["phase"] = "EXECUTE"
                return
            if verdict == "PARTIAL" and completion == "partial" and v.get("pass"):
                st["request_outcome"] = "partial"
                st["request_gaps"] = checked["gaps"]
                st["request_limitations"] = checked["limitations"]
                st["needs_human"] = "Сохранён проверенный частичный материал; поручение не выполнено полностью"
                events.emit("task_end", task_id=task["id"], status="partial", iter=task.get("iter"))
                _finish_task(st, full_task, "partial", "verified partial material; not task completion")
                st["phase"] = "REPORT"
                return
            if completion == "partial" or verdict == "PARTIAL" or st.get("request_force_partial"):
                _note_error(st, "исход автора и REVIEW не согласован: partial нельзя принять как PASS")
                st["phase"] = "EXECUTE"
                return
        elif verdict == "PARTIAL":
            verdict = "ESCALATE"  # never a partial collection or legacy task
    events.emit("verdict", task_id=task["id"], verdict=verdict,
                reason=str(out.get("reason", ""))[:200], verify_pass=v.get("pass"))

    full_task = next(t for t in st["tasks"] if t["id"] == task["id"])
    if verdict == "PASS" and v.get("pass"):
        events.emit("task_end", task_id=task["id"], status="done", iter=task.get("iter"))
        _finish_task(st, full_task, "done", "verify+review PASS")
    elif verdict == "PASS" and not v.get("pass"):
        # контролёр optimistic, а детерминированные проверки — нет: верим проверкам
        log.warn("PASS контролёра при verify fail — возврат на исправление")
        _note_error(st, "verify.json не прошёл, см. checks")
        st["phase"] = "EXECUTE"
    elif verdict == "FAIL":
        _note_error(st, f"контролёр: FAIL — {out.get('reason', '')}")
        st["phase"] = "EXECUTE"
    else:
        st["phase"] = "REPAIR"
        st["last_error"] = f"ESCALATE: {out.get('reason', '')}"


def _admit_lessons(st, lessons, log):
    """Уроки хранятся файлом и переживают ночь. Дубликаты не плодим."""
    fp = paths.WORKSPACE / "lessons.md"
    have = fp.read_text(encoding="utf-8") if fp.exists() else "# Уроки ночей\n"
    added = []
    for item in lessons or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text or text in have:
            continue
        scope = str(item.get("scope") or "project")
        have += (f"\n- [{scope}] {time.strftime('%Y-%m-%d')} "
                 f"(ночь {st.get('night_id')}): {text}\n")
        added.append(text)
    if added:
        fp.write_text(have, encoding="utf-8")
        st["lessons_admitted"] = (st.get("lessons_admitted") or []) + added
        events.emit("lesson_admitted", count=len(added))
        log.log(f"принято уроков: {len(added)}")
    return added


def phase_manager(cfg, st, log, rt):
    if not _require_approval(st, log):
        return
    if _ACTIVE_REQUEST:
        st["manager_context"] = None
        st["phase"] = "REPORT" if _current_task(st) is None else "EXECUTE"
        return  # не менять статусы канонических целей по отдельному заданию
    ctx = st.get("manager_context") or {}
    log.step(f"MANAGER задача={ctx.get('task_id')}")
    try:
        g = goals_mod.load()
    except goals_mod.GoalsError as e:
        log.warn(f"менеджер без реестра целей: {e}")
        st["manager_context"] = None
        st["phase"] = "REPORT" if st.get("stop_after_manager") else "EXECUTE"
        return

    task = next((t for t in st["tasks"] if t["id"] == ctx.get("task_id")), None)
    verdict = {}
    if task and ctx.get("status") == "done":
        verdict = _verified_result(task, task)
        if verdict is None or not verdict.get("pass"):
            st["needs_human"] = "менеджеру передан done без действующей привязки к проверке"
            st["phase"] = "REPORT"
            return
    # Доказательства добавляет код, а не модель: только acceptance file_exists,
    # которые реально существуют и прошли verify.
    new_ev = 0
    if task and ctx.get("status") == "done" and verdict.get("pass"):
        ev = goals_mod.evidence_from_task(task, verdict)
        if task.get("goal_id") and task["goal_id"] != "UNASSIGNED":
            new_ev = goals_mod.record_evidence(g, task["goal_id"], ev, st["night_id"])
            log.log(f"доказательства {task['goal_id']}: +{new_ev} из {len(ev)}")

    context = json.dumps({
        "night": st.get("night_id"),
        "finished_task": ctx,
        "new_evidence": new_ev,
        "goals": goals_mod.facts(g),
        "last_error": st.get("last_error"),
    }, ensure_ascii=False)[:14000]
    out = {}
    try:
        res = rt.call("manager", st, [
            {"role": "system", "content": prompts.MANAGER},
            {"role": "user", "content": context},
        ], max_tokens=_role_max(cfg, "manager", 16000), temperature=0.1)
        try:
            out = extract_json(res.text)
        except ValueError:
            log.warn("менеджер вернул не JSON — статусы целей не меняю")
    except providers.ProviderError as e:
        log.warn(f"менеджер недоступен ({e}) — продолжаю без смены целей")

    applied, rejected = goals_mod.apply_updates(g, out.get("goal_updates") or [])
    for a in applied:
        events.emit("goal_updated", goal_id=a["id"], status=a["status"],
                    reason=a["reason"][:150])
        log.log(f"цель {a['id']} -> {a['status']}: {a['reason'][:100]}")
    for r in rejected:
        log.warn(f"обновление цели отклонено: {r['reason']}")
        events.emit("goal_update_rejected", reason=r["reason"][:150])
    _admit_lessons(st, out.get("lessons") or [], log)
    goals_mod.save(g)

    if out.get("decision_needed"):
        note = str(out.get("notes") or "менеджер просит решение владельца")
        st["needs_human"] = note[:300]
        st["stop_after_manager"] = True
        events.emit("needs_human", reason=note[:200])
    if goals_mod.stage_is_closed(g):
        st["needs_human"] = "этап закрыт: все критерии с доказательствами; нужно решение о переходе"
        st["stop_after_manager"] = True
        events.emit("stage_closed", stage=(g.get("stage") or {}).get("id"))

    st["manager_context"] = None
    if st.get("stop_after_manager"):
        st["phase"] = "REPORT"
    else:
        st["phase"] = "EXECUTE"


def _mentor_json(cfg, st, rt, log, context, res):
    """Разбор ответа ментора: терпимо к markdown, один повтор, потом деградация.
    Один не-JSON ответ не должен останавливать ночь (11.11.2026 было именно так)."""
    try:
        return extract_json(res.text)
    except ValueError as e:
        log.warn(f"ментор вернул не JSON ({e}) — прошу повторить строго в JSON")
    nudge = ("\n\nВерни ОТВЕТ СТРОГО одним JSON-объектом, без текста до и после: "
             '{"action": "continue|replan|halt", "notes": "...", "tasks": []}')
    try:
        res2 = rt.call("mentor", st, [
            {"role": "system", "content": prompts.MENTOR},
            {"role": "user", "content": context + nudge},
        ], max_tokens=_role_max(cfg, "mentor", 32000), temperature=0.2)
        return extract_json(res2.text)
    except (ValueError, providers.ProviderError) as e:
        log.warn(f"ментор снова без JSON ({e}) — продолжаю задачу без его указаний")
        return {"action": "continue",
                "notes": "ментор ответил не-JSON; продолжай и исправь ошибки итерации"}


def phase_repair(cfg, st, log, rt):
    if _ACTIVE_REQUEST:
        st["needs_human"] = "задание остановлено на ошибке/сомнении REVIEW; auto-replan отключён"
        st["phase"] = "REPORT"
        return
    task_id = (st.get("task") or {}).get("id")
    # Потолок вмешательств ментора на задачу: дальше — фиксим статус и идём дальше,
    # ночь не должна сгореть на одной задаче.
    if st.get("task") is not None:
        st["task"]["repairs"] = st["task"].get("repairs", 0) + 1
        if st["task"]["repairs"] > 2:
            log.warn(f"{task_id}: ментор помог 2 раза и не помог — задача failed, дальше")
            _finish_task(st, next(t for t in st["tasks"] if t["id"] == task_id),
                         "failed", "ментор не помог за 2 вмешательства")
            return
    log.step(f"REPAIR задача={task_id}")
    context = json.dumps({
        "phase": st["phase"], "task": st.get("task"), "last_error": st.get("last_error"),
        "history_tail": st.get("history", [])[-6:],
        "violations": st.get("violations", [])[-5:],
    }, ensure_ascii=False)[:15000]
    res = rt.call("mentor", st, [
        {"role": "system", "content": prompts.MENTOR},
        {"role": "user", "content": context},
    ], max_tokens=_role_max(cfg, "mentor", 32000), temperature=0.2)
    out = _mentor_json(cfg, st, rt, log, context, res)
    action = out.get("action", "halt")
    log.log(f"ментор: action={action} notes={str(out.get('notes', ''))[:200]}")
    events.emit("mentor_action", task_id=task_id, action=action,
                notes=str(out.get("notes", ""))[:300])

    if action == "continue" and st.get("task"):
        st["task"]["mentor_note"] = out.get("notes", "")
        st["task"]["iter"] = max(0, st["task"]["iter"] - 1)  # дать шанс
        st["phase"] = "EXECUTE"
    elif action == "replan":
        try:
            new_tasks = _validate_tasks(out.get("tasks") or [], goals_mod.load())
        except (ValueError, goals_mod.GoalsError) as e:
            st["needs_human"] = f"replan отклонён: {e}"
            st["phase"] = "REPORT"
            return
        if not new_tasks:
            # пустой replan — не выжидаем план, а продолжаем с оставшимися задачами
            log.warn("replan без tasks: текущая задача помечена failed, план не тронут")
            cur = st.get("task")
            if cur:
                _finish_task(st, next(t for t in st["tasks"] if t["id"] == cur["id"]),
                             "failed", "replan без задач")
            else:
                st["phase"] = "EXECUTE"
            return
        done = [t for t in st["tasks"] if t.get("status") == "done"]
        st["tasks"] = done + new_tasks
        st["plan_author_model"] = res.model
        PLAN_FILE.write_text(yaml.safe_dump(st["tasks"], allow_unicode=True, sort_keys=False),
                             encoding="utf-8")
        st["task"] = None
        APPROVAL_FILE.unlink(missing_ok=True)
        st["phase"] = "PLAN"
    else:  # halt
        if st.get("task"):
            _finish_task(st, next(t for t in st["tasks"] if t["id"] == st["task"]["id"]),
                         "failed", f"halt: {out.get('notes', '')}")
            st["stop_after_manager"] = True
        else:
            st["phase"] = "REPORT"
        st["last_error"] = f"halt от ментора: {out.get('notes', '')}"


def phase_report(cfg, st, log, rt):
    log.step("REPORT")
    try:
        g = goals_mod.load()
    except goals_mod.GoalsError as e:
        log.warn(f"реестр целей недоступен при отчёте: {e}")
        g = {"global": {}, "stage": {}, "local_goals": [], "policy": {}}

    # Счётчик «ночей без прогресса» двигаем ровно раз за ночь.
    if st.get("goal_bump_night") != st.get("night_id"):
        hits = goals_mod.bump_no_progress(g, st.get("night_id"))
        st["goal_bump_night"] = st.get("night_id")
        if hits:
            msg = ("нет прогресса " + str(goals_mod.max_no_progress(g))
                   + "+ ночи: " + ", ".join(f"{h['id']} ({h['nights']})" for h in hits))
            st["needs_human"] = msg
            events.emit("no_progress", goals=hits)
            log.warn(msg)
        goals_mod.save(g)

    facts = report_mod.night_facts(st)
    if _ACTIVE_REQUEST:
        facts["request_id"] = _ACTIVE_REQUEST["spec"]["id"]
        facts["request_sha256"] = _ACTIVE_REQUEST["sha256"]
        answer = next((t for t in st.get("tasks", []) if t["id"] == "answer-mentor"), {})
        facts["request_outcome"] = st.get("request_outcome") or (
            "complete" if answer.get("status") == "done" else "blocked")
        facts["request_gaps"] = st.get("request_gaps", [])
        facts["request_limitations"] = st.get("request_limitations", [])
        if st.get("retrieval_usage") is not None:
            facts["retrieval_usage"] = st["retrieval_usage"]
            facts["retrieval_charge_usd"] = st.get("retrieval_charge_usd", 0)
        if _ACTIVE_REQUEST["spec"].get("research_policy"):
            try:
                facts["request_limits"] = request_limits.snapshot(_ACTIVE_REQUEST, st,
                    coordinator_minutes=cfg["night"].get("phase_timeout_minutes", 50))
            except ValueError:
                facts["request_outcome"] = "blocked"
                facts["request_limits_error"] = "некорректное состояние счётчиков; расход не считается нулевым"
        from . import intake
        facts["plan_file"] = intake.rel(PLAN_FILE)
        facts["goals_file"] = intake.rel(goals_mod.GOALS_FILE)
    facts["goals"] = goals_mod.facts(g)
    interp, _bad = report_mod.interpret(
        cfg, st, rt, log, facts,
        int(cfg["night"].get("report_interpretation_chars", 1800)))
    report_mod.write(st, facts, interp, log)
    report_mod.write_digest(st, facts, g, log)
    events.emit("night_report", budget_usd=facts["budget_usd"],
                tasks={t["id"]: t.get("status") for t in st["tasks"]},
                needs_human=st.get("needs_human"))
    st["phase"] = "DONE"


# ---------------------------------------------------------------- tick
_H = None
_DEADLINE = None  # конец тика: по нему решается, влезает ли задача


def tick():
    global _H, _DEADLINE
    cfg = load_config()
    paths.ensure_dirs()
    _H = lock.try_acquire(cfg)
    if _H is None:
        print("tick: процесс уже идёт — выхожу тихо")
        return 0
    log = logs.Logger("tick-" + time.strftime("%Y%m%d-%H%M%S"))
    st = state_mod.load()
    _guard_recovered_state(st)
    rt = _make_router(cfg, log)
    try:
        deadline = time.time() + cfg["night"].get("phase_timeout_minutes", 50) * 60
        _DEADLINE = deadline
        guard = 0
        while st["phase"] not in ("DONE", "FAILED") and time.time() < _DEADLINE and guard < 200:
            guard += 1
            lock.heartbeat(_H)
            phase = st["phase"]
            try:
                {"IDLE": lambda *a: st.update(phase="PLAN"),
                 "PLAN": phase_plan, "EXECUTE": phase_execute, "VERIFY": phase_verify,
                 "REVIEW": phase_review, "MANAGER": phase_manager,
                 "REPAIR": phase_repair, "REPORT": phase_report,
                 }[phase](cfg, st, log, rt)
            except Exception as e:
                log.error(f"фаза {phase}: {e}")
                st["last_error"] = f"{phase}: {e}"
                events.emit("phase_error", phase=phase, error=str(e)[:200])
                if phase == "EXECUTE" and st.get("task"):
                    _note_error(st, f"исключение: {e}")
                elif phase == "MANAGER":
                    st["phase"] = "REPORT" if st.get("stop_after_manager") else "EXECUTE"
                elif phase == "REPORT":
                    st["phase"] = "FAILED"
                elif phase == "PLAN":
                    st["needs_human"] = f"ошибка ворот планирования: {type(e).__name__}; выполнение не разрешено"
                    st["phase"] = "REPORT"
                else:
                    st["phase"] = "REPAIR" if phase != "REPAIR" else "FAILED"
            if st["phase"] != phase:
                events.emit("phase_change", frm=phase, to=st["phase"])
            state_mod.save(st)
        if st["phase"] == "DONE":
            log.ok(f"ночь завершена: бюджет ${st.get('budget_used_usd', 0):.3f}, "
                   f"задачи: " + ", ".join(f"{t['id']}={t.get('status')}" for t in st["tasks"]))
    except WaitStopped:
        log.warn("ожидание квоты остановлено владельцем; продолжение только вручную")
    finally:
        state_mod.save(st)
        lock.release(_H)
    return 0


def _make_router(cfg, log):
    if env.get("AUTONOMY_MOCK"):
        return MockRouter(cfg, log)
    def wait_hook(st, elapsed):
        global _DEADLINE
        if (paths.WORKSPACE / "STOP").exists():
            st["needs_human"] = "владелец остановил ожидание подписки; автоматического старта нет"
            st["subscription_blocked"] = st.pop("subscription_wait", {})
            st["phase"] = "REPORT"
            state_mod.save(st)
            raise WaitStopped("владелец остановил ожидание подписки")
        lock.heartbeat(_H)
        if _DEADLINE is not None:
            _DEADLINE += elapsed  # ожидание квоты не время выполнения задачи
        state_mod.save(st)
    return router_mod.Router(cfg, log, wait_hook=wait_hook)


class MockRouter:
    """Тестовый роутер: прогоняет весь пайплайн без моделей."""
    def __init__(self, cfg, log):
        self.log = log

    def call(self, role, st, messages, max_tokens=4096, temperature=0.3):
        from . import providers
        events.emit("model_call", role=role, provider="mock", model="mock",
                    in_tok=0, out_tok=0, cost_usd=0.0, latency=0.0, finish="stop")
        if role == "planner":
            text = ("- id: mock-wer\n  goal: тестовая задача\n"
                    "  goal_id: E2.3\n"
                    "  closes: roadmap:этап2-шаг3\n"
                    "  acceptance:\n"
                    "    - file_exists: autonomy/workspace/outbox/mock_result.json\n"
                    "    - number_range: [autonomy/workspace/outbox/mock_result.json, wer, 0, 0.5]\n")
        elif role == "executor":
            text = json.dumps({
                "summary": "mock: записываю результат",
                "files": {"autonomy/workspace/outbox/mock_result.json":
                          json.dumps({"wer": 0.123, "n": 100})},
                "commands": ["python -c \"print('mock ok')\""],
                "notes": "мок",
            })
        elif role == "verifier":
            text = json.dumps({"verdict": "PASS", "reason": "mock"})
        elif role == "manager":
            text = json.dumps({"goal_updates": [], "lessons": [],
                               "decision_needed": False, "notes": "mock"})
        elif role == "mentor":
            text = json.dumps({"action": "halt", "notes": "mock halt"})
        elif role == "critic":
            text = json.dumps({"verdict": "approve", "summary": "mock, не научная проверка",
                               "objections": [], "defense_value": [], "needs_search": []})
        else:
            text = "Ночь прошла по плану; артефакты проверены."
        return providers.Result(text, "mock", "mock", 0, 0, 0.0, 0.0)


# ---------------------------------------------------------------- CLI
def main(argv):
    cmd = argv[1] if len(argv) > 1 else "tick"
    if cmd == "tick":
        return tick()
    if cmd == "status":
        st = state_mod.load()
        print(json.dumps({k: st.get(k) for k in
                          ("phase", "night_id", "budget_used_usd", "last_error",
                           "subscription_wait", "subscription_blocked")},
                         ensure_ascii=False, indent=2))
        for t in st["tasks"]:
            print(f"  task {t['id']}: {t.get('status')}")
        return 0
    if cmd == "reset":
        paths.STATE_FILE.unlink(missing_ok=True)
        PLAN_FILE.unlink(missing_ok=True)
        print("STATE и план сброшены")
        return 0
    print("использование: python -m autonomy.runner [tick|status|reset]")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
