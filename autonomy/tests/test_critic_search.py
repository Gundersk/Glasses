# -*- coding: utf-8 -*-
"""Оффлайн-проверка цикла поиска у критика: без сети и без модели.

Запуск: python autonomy/tests/test_critic_search.py
Проверяет, что критик получает право спросить внешний факт, но не может
превратить критику в исследование и не может уронить ночь сбоем поиска.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from autonomy import critic  # noqa: E402


class FakeRouter:
    """Отдаёт заранее заданные ответы и запоминает запросы."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.seen = []

    def call(self, role, st, messages, max_tokens=4096, temperature=0.3):
        self.seen.append(messages[-1]["content"])

        class Out:
            text = self.answers.pop(0) if self.answers else "{}"

        return Out()


class Log:
    def __init__(self):
        self.lines = []

    def log(self, m):
        self.lines.append(("log", m))

    def warn(self, m):
        self.lines.append(("warn", m))

    def error(self, m):
        self.lines.append(("error", m))


def verdict(needs=()):
    return json.dumps({
        "verdict": "approve",
        "summary": "проверено",
        "objections": [],
        "defense_value": [],
        "needs_search": [{"query": q, "why": "проверить ориентир"} for q in needs],
    }, ensure_ascii=False)


def run(answers, search_fn=None):
    log = Log()
    rt = FakeRouter(answers)
    v = critic.review(rt, {}, {}, log, tasks=[{"id": "T1"}], materials="ctx",
                      search_fn=search_fn)
    return v, log, rt


def case_search_then_verdict():
    calls = []

    def search(q, why):
        calls.append(q)
        return f"ЗАПРОС: {q}\n1. Пример — https://example.org/x\n   > сниппет"

    v, log, rt = run([verdict(["есть ли бенчмарк X"]), verdict()], search)
    assert calls == ["есть ли бенчмарк X"], calls
    assert v["verdict"] == "approve" and v["raw_ok"]
    assert v["searches"] == ["есть ли бенчмарк X"], v["searches"]
    assert len(rt.seen) == 2 and "РЕЗУЛЬТАТЫ ПОИСКА" in rt.seen[1]
    assert any("поиск ок" in m for _, m in log.lines)
    return "поиск -> повторный вердикт"


def case_limit_three():
    calls = []

    def search(q, why):
        calls.append(q)
        return "ok"

    v, _, _ = run([verdict([f"q{i}" for i in range(5)]), verdict()], search)
    assert not calls, calls
    assert v["verdict"] == "block"
    return "больше MAX_SEARCHES — разделить план, не пропускать непроверенные вопросы"


def case_search_fails():
    def search(q, why):
        raise RuntimeError("нет ключа")

    v, log, rt = run([verdict(["q1"]), verdict()], search)
    assert v["verdict"] == "block" and not v["raw_ok"], v
    assert any(k == "warn" and "поиск не удался" in m for k, m in log.lines)
    assert len(rt.seen) == 1
    return "сбой запрошенного поиска блокирует выполнение"


def case_no_search_fn():
    v, log, rt = run([verdict(["q1"])], None)
    assert len(rt.seen) == 1, "без search_fn второго вызова быть не должно"
    assert v["searches"] == []
    assert v["verdict"] == "block"
    assert any("поиск не подключён" in m for k, m in log.lines if k == "warn")
    return "запрошенный, но не подключённый поиск не даёт одобрения"


def case_second_search_refused():
    calls = []

    def search(q, why):
        calls.append(q)
        return "ok"

    v, log, rt = run([verdict(["q1"]), verdict(["q2"])], search)
    assert calls == ["q1"], calls
    assert any("второй раунд поиска не даю" in m for k, m in log.lines)
    assert v["searches"] == ["q1"]
    assert v["verdict"] == "block"
    return "второй раунд поиска не даётся"


def case_invalid_after_search_keeps_first():
    v, log, rt = run([verdict(["q1"]), "не json"], lambda q, why: "ok")
    assert v["verdict"] == "block" and not v["raw_ok"]
    assert any("выполнение не разрешено" in m for k, m in log.lines)
    return "мусор после поиска не превращается в одобрение"


def case_bad_json_retry_no_search():
    v, log, rt = run(["мусор", verdict()])
    assert v["verdict"] == "approve" and v["raw_ok"]
    assert len(rt.seen) == 2 and "ТОЛЬКО JSON" in rt.seen[1]
    return "невалидный JSON -> один строгий повтор"


def main():
    cases = [case_search_then_verdict, case_limit_three, case_search_fails,
             case_no_search_fn, case_second_search_refused,
             case_invalid_after_search_keeps_first, case_bad_json_retry_no_search]
    for c in cases:
        print(f"ok: {c()} — {c.__name__}")
    print(f"итог: {len(cases)} проверок пройдено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
