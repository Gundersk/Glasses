# -*- coding: utf-8 -*-
"""events.jsonl — структурированная история всей работы: кто вызывался, кем заменён,
какие вердикты, сколько токенов и денег, когда передавалась роль.
Append-only: каждая строка — отдельное событие. Основа для отчётов и разбора на защите."""
import json
import time

from . import paths


def emit(event_type, **fields):
    ev = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "t": round(time.time(), 3)}
    ev["type"] = event_type
    ev.update(fields)
    paths.ensure_dirs()
    with open(paths.WORKSPACE / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev
