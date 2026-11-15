"""Smoke test: streaming Russian ASR with sherpa-onnx.

Usage:
  python stream_test.py --model zipformer --wav models/.../test_wavs/0.wav
  python stream_test.py --model tone --wav models/.../0.wav

This is a smoke test, not a benchmark. It feeds audio in real time (1x)
and prints partial/final results. No WER and no calibrated latency.
"""

from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path

import numpy as np
import sherpa_onnx


MODELS = {
    "zipformer": {
        "dir": "models/sherpa-onnx-streaming-zipformer-small-ru-vosk-int8-2025-08-16",
        "sample_rate": 16000,
    },
    "tone": {
        "dir": "models/sherpa-onnx-streaming-t-one-russian-2025-09-08",
        "sample_rate": 8000,
    },
}


def load_wav(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as wf:
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        width = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())

    if channels != 1:
        raise ValueError(f"expected mono, got {channels} channels")
    if width != 2:
        raise ValueError(f"expected 16-bit PCM, got sample width {width}")

    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, sample_rate


def build_recognizer(kind: str) -> tuple[sherpa_onnx.OnlineRecognizer, int]:
    cfg = MODELS[kind]
    model_dir = Path(cfg["dir"])
    tokens = str(model_dir / "tokens.txt")
    sample_rate = cfg["sample_rate"]

    if kind == "zipformer":
        recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=tokens,
            encoder=str(model_dir / "encoder.int8.onnx"),
            decoder=str(model_dir / "decoder.onnx"),
            joiner=str(model_dir / "joiner.int8.onnx"),
            num_threads=2,
            sample_rate=sample_rate,
            feature_dim=80,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=1.2,
            rule3_min_utterance_length=20.0,
            decoding_method="greedy_search",
            provider="cpu",
        )
    elif kind == "tone":
        recognizer = sherpa_onnx.OnlineRecognizer.from_t_one_ctc(
            tokens=tokens,
            model=str(model_dir / "model.onnx"),
            num_threads=2,
            sample_rate=sample_rate,
            feature_dim=80,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=1.2,
            rule3_min_utterance_length=20.0,
            decoding_method="greedy_search",
            provider="cpu",
        )
    else:
        raise ValueError(f"unknown model kind: {kind}")

    return recognizer, sample_rate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=sorted(MODELS), required=True)
    parser.add_argument("--wav", required=True)
    parser.add_argument("--chunk-seconds", type=float, default=0.2)
    parser.add_argument("--no-realtime", action="store_true")
    args = parser.parse_args()

    samples, wav_rate = load_wav(args.wav)
    recognizer, model_rate = build_recognizer(args.model)

    if wav_rate != model_rate:
        raise ValueError(
            f"{args.model} expects {model_rate} Hz, got {wav_rate} Hz. "
            "Resample with ffmpeg first."
        )

    stream = recognizer.create_stream()
    chunk = max(1, int(args.chunk_seconds * model_rate))
    started = time.perf_counter()
    audio_time = 0.0
    first_partial_at = None
    last_text = ""
    partial_count = 0
    decode_seconds = 0.0

    for start in range(0, len(samples), chunk):
        block = samples[start : start + chunk]
        audio_time = start / model_rate

        if not args.no_realtime:
            target = started + audio_time
            delay = target - time.perf_counter()
            if delay > 0:
                time.sleep(delay)

        t0 = time.perf_counter()
        stream.accept_waveform(model_rate, block)
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        decode_seconds += time.perf_counter() - t0

        text = recognizer.get_result(stream)
        if text and text != last_text:
            if first_partial_at is None:
                first_partial_at = time.perf_counter() - started
            partial_count += 1
            print(f"[{audio_time:6.2f}s audio] {text}", flush=True)
            last_text = text

    # tail padding, then finalize
    tail = np.zeros(int(0.5 * model_rate), dtype=np.float32)
    t0 = time.perf_counter()
    stream.accept_waveform(model_rate, tail)
    stream.input_finished()
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    decode_seconds += time.perf_counter() - t0

    final_text = recognizer.get_result(stream)
    total_wall = time.perf_counter() - started
    duration = len(samples) / model_rate

    print("\n=== RESULT ===")
    print(json.dumps({
        "model": args.model,
        "wav": args.wav,
        "sample_rate": model_rate,
        "duration_sec": round(duration, 3),
        "first_partial_sec": round(first_partial_at, 3) if first_partial_at else None,
        "partial_updates": partial_count,
        "final_text": final_text,
        "total_wall_sec": round(total_wall, 3),
        "decode_sec": round(decode_seconds, 3),
        "rtf_decode": round(decode_seconds / duration, 3) if duration else None,
        "realtime_feed": not args.no_realtime,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
