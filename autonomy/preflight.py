# -*- coding: utf-8 -*-
"""Preflight ночного цикла: подготовка состояния, плана и провайдеров.

Делает то, из-за чего ночь 11.11.2026 запускалась впустую:
- сбрасывает состояние прошлой ночи, если она уже DONE/FAILED (иначе tick
  завершается за 0.0 с и ничего не делает);
- не восстанавливает план из резерва, если в нём нет задач к работе;
- пробует каждый провайдер из лестниц одним коротким запросом и отключает
  мёртвые (регион, квота, пустой ответ) до утра;
- проверяет, что разбор команд не съедает обратные слэши Windows.

Запуск: python -m autonomy.preflight
"""
import shutil
import sys
import time

import yaml

from . import goals, paths, providers, shellutil
from . import state as state_mod

CONFIG_FILE = paths.AUTONOMY_DIR / "config.yaml"
PLAN_FILE = paths.WORKSPACE / "night_plan.yaml"
BACKUP_FILE = paths.WORKSPACE / "night_plan.backup.yaml"


def _selftest_split():
    """Путь и regex должны пережить разбор без изменений."""
    argv = shellutil._split_args(
        r"experiments\file_stream_eval.py resources --wav data\fleurs_ru_test\clip_001.wav")
    assert argv[0] == r"experiments\file_stream_eval.py", f"путь испорчен: {argv[0]!r}"
    assert argv[3] == r"data\fleurs_ru_test\clip_001.wav", f"аргумент испорчен: {argv[3]!r}"
    code = shellutil._split_args(
        r"""-c "import re; re.search(r'разн\w* семантик', 'x')" """.strip())[1]
    assert r"\w" in code, f"regex испорчен: {code!r}"


def _probe(cfg, name):
    pcfg = dict(cfg["providers"][name])
    if pcfg.get("skip_probe"):
        return {"ok": True, "unverified": True, "model": pcfg.get("model"), "latency_s": 0}
    pcfg["timeout_s"] = int(cfg["night"].get("probe_timeout_s", 45))
    pcfg["retries"] = 0
    budget = int(cfg["night"].get("probe_max_tokens", 1024))
    try:
        res = providers.chat(name, pcfg,
                             [{"role": "user", "content": "Ответь одним словом: ok"}],
                             max_tokens=budget, temperature=0)
        return {"ok": True, "model": res.model, "latency_s": round(res.latency, 1)}
    except Exception as e:  # noqa: BLE001 — проба не должна ронять preflight
        kind = getattr(e, "kind", "?")
        # Проба проверяет ДОСТУПНОСТЬ, а не качество: если эндпоинт ответил, но
        # модель ушла в reasoning — она жива, пустоту поймает обычная проверка.
        alive = kind in ("empty", "empty_reasoning", "truncated", "truncated_reasoning")
        return {"ok": alive, "degraded": alive, "kind": kind, "error": str(e)[:200]}


def _tasks(path):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except (OSError, yaml.YAMLError):
        return []
    return data if isinstance(data, list) else []


def _pending(tasks):
    return [t for t in tasks if isinstance(t, dict) and t.get("status", "pending") == "pending"]


def main():
    paths.ensure_dirs()
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))

    print("[preflight] самопроверка разбора команд")
    try:
        _selftest_split()
    except AssertionError as e:
        print(f"FAIL: разбор команд ломает пути/регэкспы: {e}")
        return 1

    print("[preflight] состояние прошлой ночи")
    st = state_mod.load()
    if st.get("phase") in ("DONE", "FAILED"):
        paths.STATE_FILE.unlink(missing_ok=True)
        st = state_mod.load()
        print("  прошлая ночь завершена — состояние сброшено")
    else:
        print(f"  незавершённая ночь: phase={st.get('phase')} — продолжаю её")

    print("[preflight] план")
    tasks = _tasks(PLAN_FILE)
    if _pending(tasks):
        print(f"  беру night_plan.yaml: {len(_pending(tasks))} задач к работе из {len(tasks)}")
    else:
        backup = _tasks(BACKUP_FILE) if BACKUP_FILE.exists() else []
        if _pending(backup):
            shutil.copy2(BACKUP_FILE, PLAN_FILE)
            tasks = backup
            print(f"  восстановлен из резерва: {len(_pending(tasks))} задач к работе")
        else:
            print("  незавершённых задач нет — план не восстанавливаю (planner построит новый)")

    print("[preflight] реестр целей")
    try:
        g = goals.load()
    except goals.GoalsError as e:
        print(f"FAIL: {e}")
        return 1
    open_goals = goals.open_targets(g)
    print(f"  глобальная цель: {(g.get('global') or {}).get('statement')}")
    print(f"  этап: {(g.get('stage') or {}).get('id')} до "
          f"{(g.get('stage') or {}).get('deadline')}, открытых целей: {len(open_goals)}")
    for t in open_goals:
        bm = str(t.get("benchmark") or "").strip()
        mark = f" | ориентир: {bm}" if bm else ""
        print(f"    {t['id']}: {t.get('text')[:100]}{mark}")
    missing = []
    for t in goals.targets(g):
        for p in t.get("evidence") or []:
            if not paths.resolve(p).exists():
                missing.append(f"{t['id']}: {p}")
    if missing:
        print("FAIL: доказательства целей указывают на отсутствующие файлы:")
        for m in missing[:10]:
            print(f"  {m}")
        return 1
    if not paths.resolve("docs/benchmarks.md").exists():
        print("FAIL: нет docs/benchmarks.md — сравнивать наши числа с чужими не по чему")
        return 1
    print("  реестр сопоставимости: docs/benchmarks.md на месте")
    bm_file = paths.resolve("docs/benchmarks.md")
    bm_age_days = (time.time() - bm_file.stat().st_mtime) / 86400
    if bm_age_days > 45:
        print(f"  ВНИМАНИЕ: реестр не обновлялся {bm_age_days:.0f} дней — "
              f"обнови внешний ориентир: python -m autonomy.research \"<запрос>\"")
    else:
        print(f"  реестр обновлён {bm_age_days:.0f} дн. назад")
    if not open_goals:
        print("  ВНИМАНИЕ: открытых целей нет — ночь остановится и попросит решение")

    print("[preflight] проба провайдеров")
    names = []
    for ladder in cfg["roles"].values():
        for n in ladder:
            if n not in names:
                names.append(n)
    results, disabled = {}, {}
    for name in names:
        r = _probe(cfg, name)
        results[name] = r
        if r.get("unverified"):
            print(f"  {name}: генерация-проба пропущена ради квоты; доступность НЕ проверена")
        elif r["ok"] and r.get("degraded"):
            print(f"  {name}: отвечает, но ответ пустой/обрезан ({r['kind']}) — оставляю в лестнице")
        elif r["ok"]:
            print(f"  {name}: ok, модель {r['model']}, {r['latency_s']} c")
        else:
            disabled[name] = r["error"]
            print(f"  {name}: НЕ ОТВЕЧАЕТ ({r.get('kind')}): {r['error'][:120]}")

    st["provider_probe"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
    st["disabled_providers"] = disabled
    st["provider_fails"] = {}
    state_mod.save(st)

    alive_roles = [role for role, ladder in cfg["roles"].items()
                   if any(n not in disabled for n in ladder)]
    if not alive_roles:
        print("FAIL: ни одна роль не имеет живого провайдера")
        return 1
    dead_roles = [role for role in cfg["roles"] if role not in alive_roles]
    if dead_roles:
        print(f"ВНИМАНИЕ: роли без живых провайдеров: {dead_roles}")
    print(f"[preflight] ok: отключено {len(disabled)} из {len(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
