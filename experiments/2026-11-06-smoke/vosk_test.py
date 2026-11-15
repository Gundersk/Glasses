"""Smoke test: streaming Russian ASR with Vosk.

Usage:
  python vosk_test.py models/vosk-model-small-ru-0.22 models/.../test_wavs/0.wav

Smoke test only: no WER, no calibrated latency.
"""

from __future__ import annotations

import argparse
import json
import time
import wave

from vosk import KaldiRecognizer, Model, SetLogLevel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_dir")
    parser.add_argument("wav")
    parser.add_argument("--chunk-seconds", type=float, default=0.2)
    args = parser.parse_args()

    SetLogLevel(-1)

    with wave.open(args.wav, "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        if channels != 1 or width != 2:
            raise ValueError("expected mono 16-bit PCM wav")
        frames = wf.readframes(wf.getnframes())

    model = Model(args.model_dir)
    rec = KaldiRecognizer(model, rate)
    rec.SetWords(False)

    chunk = max(1, int(args.chunk_seconds * rate) * 2)  # bytes
    started = time.perf_counter()
    first_partial_at = None
    last_text = ""
    partial_count = 0

    for start in range(0, len(frames), chunk):
        block = frames[start : start + chunk]
        audio_time = start / 2 / rate
        target = started + audio_time
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)

        if rec.AcceptWaveform(block):
            text = json.loads(rec.Result()).get("text", "")
            if text and text != last_text:
                if first_partial_at is None:
                    first_partial_at = time.perf_counter() - started
                partial_count += 1
                print(f"[{audio_time:6.2f}s audio] FINAL {text}", flush=True)
                last_text = text
        else:
            text = json.loads(rec.PartialResult()).get("partial", "")
            if text and text != last_text:
                if first_partial_at is None:
                    first_partial_at = time.perf_counter() - started
                partial_count += 1
                print(f"[{audio_time:6.2f}s audio] {text}", flush=True)
                last_text = text

    # Feed a short silence tail, then finalize. Without it Vosk can return
    # an empty FinalResult even though the last partial had text.
    tail = b"\x00\x00" * int(rate * 0.5)
    ended = rec.AcceptWaveform(tail)
    final_raw = json.loads(rec.Result() if ended else rec.FinalResult()).get("text", "")
    final = final_raw or last_text
    total_wall = time.perf_counter() - started
    duration = len(frames) / 2 / rate

    print("\n=== RESULT ===")
    print(json.dumps({
        "model": "vosk-small-ru-0.22",
        "wav": args.wav,
        "sample_rate": rate,
        "duration_sec": round(duration, 3),
        "first_partial_sec": round(first_partial_at, 3) if first_partial_at else None,
        "partial_updates": partial_count,
        "final_text": final,
        "final_source": "result" if final_raw else "last_partial",
        "total_wall_sec": round(total_wall, 3),
        "realtime_feed": True,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
