# -*- coding: utf-8 -*-
"""Человекочитаемая лента событий из events.jsonl: кто вызывался, чем заменён,
какие вердикты, сколько токенов/денег, где передачи ролей и затыки.

    python -m autonomy.history            # лента за сегодня
    python -m autonomy.history --all      # всё
    python -m autonomy.history --role planner
    python -m autonomy.history --cost     # сводка затрат по провайдерам
"""
import json
import sys
import time
from collections import defaultdict

from . import paths


def load_events():
    fp = paths.WORKSPACE / "events.jsonl"
    if not fp.exists():
        return []
    out = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


ICON = {
    "model_call": "→", "model_fail": "✗", "model_skip": "∅",
    "task_start": "▶", "task_end": "■", "verdict": "⚖", "mentor_action": "🧠",
    "phase_change": "·", "violation": "⚠", "night_report": "📄",
}


def timeline(events, day=None, role=None):
    lines = []
    for e in events:
        if day and not e.get("ts", "").startswith(day):
            continue
        t = e.get("type", "?")
        if role and e.get("role") != role:
            continue
        ic = ICON.get(t, "•")
        if t == "model_call":
            lines.append(f"{e['ts']} {ic} {e['role']:9}→{e['provider']:16} "
                         f"in={e['in_tok']} out={e['out_tok']} ${e['cost_usd']:.4f} "
                         f"{e['latency']}s finish={e.get('finish')}")
        elif t in ("model_fail", "model_skip"):
            lines.append(f"{e['ts']} {ic} {e.get('role','')}: {e['provider']} — {e.get('reason') or e.get('error','')[:80]}")
        elif t == "task_start":
            lines.append(f"{e['ts']} {ic} задача {e['task_id']}: {e.get('goal','')[:70]}")
        elif t == "task_end":
            lines.append(f"{e['ts']} {ic} задача {e['task_id']} → {e['status']} ({e.get('reason','')})")
        elif t == "verdict":
            vp = "verify:PASS" if e.get("verify_pass") else "verify:FAIL"
            lines.append(f"{e['ts']} {ic} {e['task_id']}: {e['verdict']} [{vp}] — {e.get('reason','')[:60]}")
        elif t == "mentor_action":
            lines.append(f"{e['ts']} {ic} ментор: {e['action']} — {e.get('notes','')[:70]}")
        elif t == "violation":
            lines.append(f"{e['ts']} {ic} {e.get('task','')}: {e.get('kind')} {e.get('path') or e.get('cmd','')}")
        else:
            lines.append(f"{e['ts']} {ic} {t}: " + json.dumps({k: v for k, v in e.items()
                         if k not in ("ts", "t", "type")}, ensure_ascii=False)[:120])
    return lines


def cost_summary(events):
    by_prov = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "usd": 0.0})
    by_role = defaultdict(int)
    for e in events:
        if e.get("type") == "model_call":
            p = by_prov[e["provider"]]
            p["calls"] += 1
            p["in"] += e.get("in_tok", 0)
            p["out"] += e.get("out_tok", 0)
            p["usd"] += e.get("cost_usd", 0.0)
            by_role[e["role"]] += 1
    print("По провайдерам:")
    for name, p in sorted(by_prov.items(), key=lambda kv: -kv[1]["usd"]):
        print(f"  {name:16} calls={p['calls']:3} in={p['in']:8} out={p['out']:7} ${p['usd']:.4f}")
    print("По ролям:")
    for name, n in sorted(by_role.items(), key=lambda kv: -kv[1]):
        print(f"  {name:12} вызовов={n}")


def main(argv):
    events = load_events()
    if not events:
        print("событий пока нет (events.jsonl пуст)")
        return 0
    if "--cost" in argv:
        cost_summary(events)
        return 0
    day = None if "--all" in argv else time.strftime("%Y-%m-%d")
    role = None
    if "--role" in argv:
        role = argv[argv.index("--role") + 1]
    for line in timeline(events, day=day, role=role):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
