"""Диагностика blocked-прогона: распознаёт ли ASR записанный WAV, несмотря на corr_peak < 0.5.

Подаёт <run>/artifacts/recording.wav в streaming_asr в темпе 1.0 (чанки 100 мс, как duplex_e2e) и пишет
<run>/diag_asr.json: partials/finals и число финалов. Это ДИАГНОСТИКА причины блокировки, а НЕ метрика прогона:
metrics.json не создаётся, latency не считается (лаг при corr < 0.5 недостоверен).

CLI: python diag_asr.py --run runs/<id> [--engine sherpa]
"""
import argparse
import json
import pathlib
import sys
import time

import numpy as np
import soundfile as sf

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import streaming_asr  # noqa: E402
from duplex_e2e import feed_asr  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--engine", default="sherpa")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    run = pathlib.Path(a.run)
    rec, sr = sf.read(str(run / "artifacts" / "recording.wav"), dtype="float32")
    x16 = streaming_asr.resample_to_16k(rec, sr)
    asr, status = streaming_asr.create_asr(a.engine)
    if asr is None:
        raise SystemExit(f"ASR не создан: {status.message}")
    lines = []
    partials, finals, _, wall = feed_asr(asr, x16, 100, lambda m: (lines.append(m), print(m, flush=True)))
    out = {"note": "ДИАГНОСТИКА blocked-прогона, не метрика; latency не считается",
           "engine": a.engine, "recording_s": len(x16) / 16000.0, "feed_wall_s": wall,
           "partial_count": len(partials), "final_count": len(finals),
           "final_count_endpoint": sum(1 for f in finals if f["reason"] == "endpoint"),
           "finals": finals, "n_partials_unique": len({p["text"] for p in partials})}
    (run / "diag_asr.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "finals"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
