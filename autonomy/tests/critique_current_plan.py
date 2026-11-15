# -*- coding: utf-8 -*-
"""Разовая проверка критика на реальном плане: python autonomy/tests/critique_current_plan.py

Не входит в ночной цикл. Нужен, чтобы увидеть, ловит ли критик дефекты,
которые человек находил руками (12.11.2026: 40 минут на задачу при тике 50 минут).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import yaml

from autonomy import critic, goals, logs, paths, router, state  # noqa: E402


def materials():
    g = goals.load()
    def ctx(p, n):
        fp = paths.resolve(p)
        return fp.read_text(encoding="utf-8", errors="replace")[:n] if fp.exists() else ""
    return (
        "=== РЕЕСТР ЦЕЛЕЙ ===\n" + goals.summary(g, 2800)
        + "\n=== PROJECT.md (фрагмент) ===\n" + ctx("PROJECT.md", 2000)
        + "\n=== STATUS.md ===\n" + ctx("STATUS.md", 4000)
        + "\n=== РЕЕСТР СОПОСТАВИМОСТИ ===\n" + ctx("docs/benchmarks.md", 1800)
    )


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Разовый прогон критика на плане")
    ap.add_argument("--plan", default="autonomy/workspace/night_plan.yaml")
    ap.add_argument("--no-search", action="store_true",
                    help="не давать критику поиск (проверить работу по файлам)")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load((paths.AUTONOMY_DIR / "config.yaml").read_text(encoding="utf-8"))
    log = logs.Logger("critic-live")
    log.log = print
    log.warn = print
    log.error = print
    rt = router.Router(cfg, log)
    st = state.load()
    plan_file = paths.resolve(a.plan)
    tasks = yaml.safe_load(plan_file.read_text(encoding="utf-8"))
    search_fn = None if a.no_search else critic.make_search_fn(cfg, log)
    v = critic.review(rt, st, cfg, log, tasks=tasks, materials=materials(),
                      search_fn=search_fn)
    print("\n--- вердикт ---")
    print(v["verdict"], "|", v["summary"])
    for o in v["objections"]:
        print(f"  [{o['severity']}] {o['task_id']}: {o['issue']} -> {o['fix']}")
    for d in v["defense_value"]:
        print(f"  ценность: {d['task_id']}: {d['verdict']} — {d['why']}")
    if v.get("searches"):
        print("  поиск:", "; ".join(v["searches"]))
    critic.write_note(str(st.get("night_id")), v, 1, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
