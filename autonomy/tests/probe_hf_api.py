# -*- coding: utf-8 -*-
"""Быстрая проверка: публичные русские ASR-данные через HF API (не datasets-server)."""
import requests

CANDS = ["google/fleurs", "bond005/sberdevices_golos_100h_opus", "bond005/golos"]

for repo in CANDS:
    print("\n=====", repo)
    r = requests.get(f"https://huggingface.co/api/datasets/{repo}", timeout=20)
    print("status:", r.status_code)
    if r.status_code == 200:
        d = r.json()
        print("downloads:", d.get("downloads"), "| gated:", d.get("gated"))
        files = [s["rfilename"] for s in d.get("siblings", []) if "ru" in s["rfilename"].lower() or "parquet" in s["rfilename"].lower()]
        print("relevant files:", files[:8])
