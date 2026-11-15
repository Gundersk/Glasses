# -*- coding: utf-8 -*-
"""Заменяет длинное тире на короткое в текстовых отчётах (стиль проекта).

Использование:
    python reports/normalize_dashes.py reports/monthly/2026-11-draft.md ...
"""
import sys
from pathlib import Path

EM_DASH = "\u2014"


def normalize(text: str) -> str:
    return text.replace(f" {EM_DASH} ", " - ").replace(EM_DASH, "-")


def main(paths: list[str]) -> None:
    for raw in paths:
        path = Path(raw)
        source = path.read_text(encoding="utf-8")
        result = normalize(source)
        if result != source:
            path.write_text(result, encoding="utf-8")
            print(f"fixed {path}: {source.count(EM_DASH)} em-dashes")
        else:
            print(f"ok {path}: nothing to change")


if __name__ == "__main__":
    main(sys.argv[1:])
