# -*- coding: utf-8 -*-
"""Проверка слияния noise_manifest.json: второй движок не должен терять записи.

Запуск: python autonomy/tests/test_noise_manifest_merge.py
Без запуска ASR: импортируется только функция записи манифеста.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments.file_stream_eval import _write_conditions, _write_noise_manifest  # noqa: E402

SEED = 20261109


def entry(clip, cond, snr):
    return {"clip_id": clip, "condition": cond, "target_snr_db": snr,
            "measured_snr_db": snr, "path": f"audio/{clip}_{cond}.wav"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def case_merge_keeps_old():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "noise_manifest.json"
        _write_noise_manifest(p, [entry("clip_000", "snr20", 20)], SEED, 100, 1.0)
        _write_noise_manifest(p, [entry("clip_000", "snr10", 10)], SEED, 100, 1.0)
        files = read(p)["files"]
        assert [(f["clip_id"], f["condition"]) for f in files] == [
            ("clip_000", "snr10"), ("clip_000", "snr20")], files
        assert read(p)["seed"] == SEED
    return "второй прогон сохраняет записи первого"


def case_same_key_updates():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "noise_manifest.json"
        _write_noise_manifest(p, [entry("clip_000", "snr20", 20)], SEED, 100, 1.0)
        _write_noise_manifest(p, [entry("clip_000", "snr20", 20.034)], SEED, 100, 1.0)
        files = read(p)["files"]
        assert len(files) == 1 and files[0]["measured_snr_db"] == 20.034, files
    return "повтор не дублирует запись"


def case_other_seed_resets():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "noise_manifest.json"
        _write_noise_manifest(p, [entry("clip_000", "snr20", 20)], SEED, 100, 1.0)
        _write_noise_manifest(p, [entry("clip_001", "snr20", 20)], SEED + 1, 100, 1.0)
        data = read(p)
        assert data["seed"] == SEED + 1 and len(data["files"]) == 1, data
    return "другой seed не смешивается со старым"


def case_corrupt_manifest_recovers():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "noise_manifest.json"
        p.write_text("{не json", encoding="utf-8")
        _write_noise_manifest(p, [entry("clip_000", "snr20", 20)], SEED, 100, 1.0)
        assert len(read(p)["files"]) == 1
    return "битый манифест перезаписывается, ночь не падает"


def case_partial_flag():
    class Status:
        version = "test"
        config = {}
        message = "ok"

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sherpa_conditions.json"
        args = (p, "sherpa", SEED, ["clip_000"], 100, 1.0, 1.0, Path("manifest.jsonl"),
                Status(), [{"name": "clean", "wer": 0.1}])
        _write_conditions(*args, partial=True)
        data = read(p)
        assert data["partial"] is True and len(data["conditions"]) == 1, data
        _write_conditions(*args, partial=False)
        assert read(p)["partial"] is False
    return "частичный JSON помечается partial, финальный — нет"


def main():
    cases = [case_merge_keeps_old, case_same_key_updates, case_other_seed_resets,
             case_corrupt_manifest_recovers, case_partial_flag]
    for c in cases:
        print(f"ok: {c()} — {c.__name__}")
    print(f"итог: {len(cases)} проверок пройдено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
