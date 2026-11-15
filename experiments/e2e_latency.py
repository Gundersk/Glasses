import json
import os
import sys
import time
import wave

import numpy as np


def resample_linear(samples, sr, target_sr):
    if sr == target_sr:
        return samples
    if len(samples) == 0:
        return samples
    target_len = int(round(len(samples) * target_sr / sr))
    if target_len <= 0:
        return np.array([], dtype=np.int16)
    x_old = np.arange(len(samples), dtype=np.float64)
    x_new = np.linspace(0, len(samples) - 1, target_len, dtype=np.float64)
    return np.interp(x_new, x_old, samples.astype(np.float64)).astype(np.int16)


def main():
    audio = sys.argv[1] if len(sys.argv) > 1 else "experiments/data/speech_ru.wav"
    model = sys.argv[2] if len(sys.argv) > 2 else "models/vosk-model-small-ru-0.22"
    out = sys.argv[3] if len(sys.argv) > 3 else "experiments/benchmarks/e2e_latency.json"
    chunk_frames = 4000
    target_sr = 16000
    latencies_ms = []
    meta = {}
    vosk_version = "unavailable"

    try:
        import vosk
        vosk_version = getattr(vosk, "__version__", "unknown")
    except Exception as e:
        meta["error"] = f"vosk import failed: {e}"

    try:
        wf = wave.open(audio, "rb")
        sr = wf.getframerate()
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)
        wf.close()

        if sampwidth != 2:
            raise ValueError("expected 16-bit PCM audio")

        samples = np.frombuffer(raw, dtype=np.int16)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
        samples = resample_linear(samples, sr, target_sr)

        if not os.path.isdir(model):
            raise FileNotFoundError(f"model directory not found: {model}")

        vosk_model = vosk.Model(model)
        rec = vosk.KaldiRecognizer(vosk_model, target_sr)

        last_fully_submitted = None
        for i in range(0, len(samples), chunk_frames):
            chunk = samples[i:i + chunk_frames]
            if len(chunk) == 0:
                continue
            accepted = rec.AcceptWaveform(chunk.tobytes())
            fully_submitted = time.perf_counter()
            last_fully_submitted = fully_submitted
            if accepted:
                result = json.loads(rec.Result())
                text = result.get("text", "")
                final_time = time.perf_counter()
                if text:
                    latencies_ms.append((final_time - fully_submitted) * 1000.0)

        if last_fully_submitted is not None:
            final = json.loads(rec.FinalResult())
            final_time = time.perf_counter()
            text = final.get("text", "")
            latencies_ms.append((final_time - last_fully_submitted) * 1000.0)
            if text:
                meta["final_text"] = text

        meta["audio_frames"] = int(nframes)
        meta["audio_sample_rate"] = int(sr)
        meta["audio_channels"] = int(channels)
        meta["processed_samples"] = int(len(samples))
    except Exception as e:
        meta["error"] = str(e)

    if latencies_ms:
        p50 = float(np.percentile(latencies_ms, 50))
        p95 = float(np.percentile(latencies_ms, 95))
        n_finals = len(latencies_ms)
    else:
        p50 = 0.0
        p95 = 0.0
        n_finals = 0

    out_data = {
        "method": "Algorithmic streaming ASR finalize latency: wall-clock time from AcceptWaveform returning True (last chunk of segment fully submitted) to Result() returning non-empty text; includes stream FinalResult after last chunk. Not network/browser latency.",
        "p50_ms": p50,
        "p95_ms": p95,
        "n_finals": n_finals,
        "audio": audio,
        "model": model,
        "sample_rate": target_sr,
        "vosk_version": vosk_version,
        "python": sys.version,
        "chunk_frames": chunk_frames,
        "meta": meta,
    }

    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)
    print(json.dumps(out_data, ensure_ascii=False))


if __name__ == "__main__":
    main()
