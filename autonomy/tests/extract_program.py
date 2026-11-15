# -*- coding: utf-8 -*-
"""Извлекает из программы поддержки талантов всё, что относится к отчётности и порталу."""
from pathlib import Path

import pymupdf

PDF = Path("..") / "Программа выявления и поддержки талантливых первокурсников.pdf"
KEYS = ["портал", "отчёт", "отчет", "прикреп", "загруз", "кабинет", "25", "форма"]


def main() -> None:
    doc = pymupdf.open(PDF)
    print("pages:", doc.page_count)
    for i, page in enumerate(doc):
        text = page.get_text()
        low = text.lower()
        if any(k in low for k in KEYS):
            print(f"\n===== PAGE {i + 1}")
            print(text.strip()[:2500])


if __name__ == "__main__":
    main()
