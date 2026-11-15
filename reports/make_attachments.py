# -*- coding: utf-8 -*-
"""Собирает ZIP-пакеты вложений для портала (имена внутри - ASCII)."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "attachments"

OCTOBER = [
    (ROOT.parent / "Дорожная карта — Антропов Юрий Андреевич (v2).pdf", "roadmap_v2.pdf"),
]

NOVEMBER = [
    (ROOT / "reports" / "analytics-note-2026-11.pdf", "analytics_note_2026-11.pdf"),
    (ROOT / "reports" / "monthly" / "2026-11-draft.pdf", "monthly_report_2026-11.pdf"),
    (ROOT / "experiments" / "web_demo" / "asr_ui.png", "asr_browser_output.png"),
    (ROOT / "experiments" / "fleurs_benchmark" / "vosk_metrics.json", "vosk_metrics.json"),
    (ROOT / "experiments" / "fleurs_benchmark" / "sherpa_metrics.json", "sherpa_metrics.json"),
]


def build(name: str, items: list[tuple[Path, str]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / name
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for source, arcname in items:
            if not source.exists():
                raise FileNotFoundError(source)
            archive.write(source, arcname)
    print(f"{target}  {target.stat().st_size} bytes")
    with ZipFile(target) as archive:
        for info in archive.infolist():
            print(f"  {info.file_size:>9}  {info.filename}")


if __name__ == "__main__":
    build("2026-10-attachments.zip", OCTOBER)
    build("2026-11-attachments.zip", NOVEMBER)
