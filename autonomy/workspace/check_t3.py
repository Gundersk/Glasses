"""T3: сверка experiments/engine_choice.md с metrics.json. Только чтение, без прогонов ASR."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "experiments" / "engine_choice.md"
SHERPA = ROOT / "experiments" / "fleurs_benchmark" / "sherpa_metrics.json"
VOSK = ROOT / "experiments" / "fleurs_benchmark" / "vosk_metrics.json"
OUTBOX = ROOT / "autonomy" / "workspace" / "outbox" / "T3_result.md"


def main() -> int:
    for path in (DOC, SHERPA, VOSK, OUTBOX):
        if not path.is_file() or path.stat().st_size == 0:
            print(f"FAIL: нет непустого файла {path}")
            return 1

    text = DOC.read_text(encoding="utf-8")
    try:
        sherpa = json.loads(SHERPA.read_text(encoding="utf-8"))
        vosk = json.loads(VOSK.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: не читаются metrics.json: {exc}")
        return 1

    checks = []
    checks.append(("num_clips sherpa == 50", sherpa.get("num_clips") == 50))
    checks.append(("num_clips vosk == 50", vosk.get("num_clips") == 50))

    s_wer = round(float(sherpa["wer"]) * 100, 2)
    v_wer = round(float(vosk["wer"]) * 100, 2)
    checks.append((f"sherpa WER {s_wer:.2f}% есть в документе", f"{s_wer:.2f}%" in text))
    checks.append((f"vosk WER {v_wer:.2f}% есть в документе", f"{v_wer:.2f}%" in text))

    for pattern, name in (
        (r"самописн", "ограничение: самописный WER"),
        (r"150 клип", "раздел про 150 клипов"),
        (r"разн\w* семантик", "ограничение: разная семантика задержек"),
    ):
        checks.append((name, re.search(pattern, text) is not None))

    checks.append(
        (
            "нет утверждения о превосходстве по задержке",
            "не означает, что задержка sherpa-onnx ниже" in text,
        )
    )

    ok = True
    for name, passed in checks:
        print(("OK   " if passed else "FAIL ") + name)
        ok = ok and passed

    print(f"sherpa WER = {s_wer:.2f}%, vosk WER = {v_wer:.2f}%, клипов = {sherpa.get('num_clips')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
