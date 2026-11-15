# -*- coding: utf-8 -*-
"""FLEURS ru_ru + контрольный публичный датасет: доступность через datasets-server."""
import json
import requests

DS = "https://datasets-server.huggingface.co"


def probe(repo, config=None):
    print("\n=====", repo, config or "")
    r = requests.get(DS + "/splits", params={"dataset": repo}, timeout=25)
    print("splits:", r.status_code)
    if r.status_code != 200:
        print(r.text[:200])
        return
    splits = [(s["config"], s["split"]) for s in r.json().get("splits", [])]
    print("configs/splits sample:", splits[:12])
    ru = [s for s in splits if "ru" in s[0]] or splits
    if config:
        ru = [s for s in splits if s[0] == config]
    if not ru:
        print("нет нужного конфига")
        return
    cfg, sp = ru[0]
    r2 = requests.get(DS + "/rows", params={"dataset": repo, "config": cfg,
                                           "split": sp, "offset": 0, "length": 2},
                      timeout=30)
    print("rows:", r2.status_code, f"({cfg}/{sp})")
    if r2.status_code == 200:
        rows = r2.json().get("rows", [])
        if rows:
            row = rows[0]["row"]
            out = {}
            for k, v in row.items():
                if isinstance(v, dict) and "src" in v:
                    out[k] = {"src": v["src"][:120], "bytes": v.get("bytes")}
                else:
                    out[k] = str(v)[:120]
            print(json.dumps(out, ensure_ascii=False, indent=1)[:1500])
    else:
        print(r2.text[:200])


probe("PolyAI/minds14")           # контроль: публичный, должен работать
probe("google/fleurs", "ru_ru")   # цель: живой русский с эталоном, CC-BY
