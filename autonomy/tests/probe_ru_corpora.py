# -*- coding: utf-8 -*-
"""Проверка доступности публичных русских ASR-корпусов через HF datasets-server.
Цель: набор аудио+эталон без скачивания всего корпуса (assets endpoint)."""
import json
import requests

CANDS = [
    "bond005/sberdevices_golos_100h_opus",
    "mozilla-foundation/common_voice_13_0",
    "bond005/golos",
]

DS = "https://datasets-server.huggingface.co"


def probe(repo):
    print("\n=====", repo)
    try:
        r = requests.get(DS + "/splits", params={"dataset": repo}, timeout=25)
        if r.status_code != 200:
            print("splits:", r.status_code, r.text[:160])
            return
        data = r.json()
        splits = [(s["config"], s["split"]) for s in data.get("splits", [])]
        print("splits:", splits[:8])
        # первая строка: есть ли аудио-ссылка и текст
        cfg, sp = splits[0]
        r2 = requests.get(DS + "/rows", params={"dataset": repo, "config": cfg,
                                               "split": sp, "offset": 0, "length": 1},
                          timeout=25)
        print("rows:", r2.status_code)
        if r2.status_code == 200:
            rows = r2.json().get("rows", [])
            if rows:
                row = rows[0]["row"]
                keys = {k: (str(v)[:160]) for k, v in row.items()}
                print(json.dumps(keys, ensure_ascii=False, indent=1)[:1200])
        else:
            print(r2.text[:200])
    except Exception as e:
        print("ERR", type(e).__name__, str(e)[:200])


for c in CANDS:
    probe(c)
