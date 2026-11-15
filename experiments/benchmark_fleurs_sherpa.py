import json, math, re, sys, time, wave
from pathlib import Path
import numpy as np
import sherpa_onnx

MODEL_DIR = Path("models/sherpa-onnx-streaming-zipformer-small-ru-vosk-int8-2025-08-16")
MANIFEST = Path("data/fleurs_ru_test/manifest.jsonl")
OUT = Path("experiments/fleurs_benchmark/sherpa_metrics.json")
SR = 16000
CHUNK_SEC = 0.2

def norm(text):
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^а-яёa-z0-9]+", " ", text)
    return text.split()

def edit_counts(ref, hyp):
    # Возвращает (S, D, I) — substitutions, deletions, insertions.
    m, n = len(ref), len(hyp)
    dp = [[None] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = (0, 0, 0, 0)  # (cost, S, D, I)
    for i in range(1, m + 1):
        c, s, d, ins = dp[i - 1][0]
        dp[i][0] = (c + 1, s, d + 1, ins)          # deletion
    for j in range(1, n + 1):
        c, s, d, ins = dp[0][j - 1]
        dp[0][j] = (c + 1, s, d, ins + 1)          # insertion
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            c, s, d, ins = dp[i - 1][j]
            best = (c + 1, s, d + 1, ins)          # deletion
            c, s, d, ins = dp[i][j - 1]
            cand = (c + 1, s, d, ins + 1)          # insertion
            if cand[0] < best[0]:
                best = cand
            c, s, d, ins = dp[i - 1][j - 1]
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            cand = (c + cost, s + cost, d, ins)    # match / substitution
            if cand[0] < best[0]:
                best = cand
            dp[i][j] = best
    c, s, d, ins = dp[m][n]
    return s, d, ins

def load_wav(path):
    with wave.open(str(path), "rb") as wf:
        ch = wf.getnchannels()
        sr = wf.getframerate()
        width = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
    if width != 2:
        raise ValueError("expected 16-bit PCM")
    samples = np.frombuffer(frames, dtype=np.int16)
    if ch > 1:
        samples = samples[::ch]
    samples = samples.astype(np.float32) / 32768.0
    if sr != SR:
        target = int(len(samples) * SR / sr)
        x = np.linspace(0, len(samples) - 1, target, dtype=np.float32)
        samples = np.interp(x, np.arange(len(samples), dtype=np.float32), samples).astype(np.float32)
    return samples

def build_recognizer():
    for f in ["tokens.txt", "encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx"]:
        if not (MODEL_DIR / f).exists():
            raise FileNotFoundError(f"missing {MODEL_DIR / f}")
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(MODEL_DIR / "tokens.txt"),
        encoder=str(MODEL_DIR / "encoder.int8.onnx"),
        decoder=str(MODEL_DIR / "decoder.onnx"),
        joiner=str(MODEL_DIR / "joiner.int8.onnx"),
        num_threads=2,
        sample_rate=SR,
        feature_dim=80,
        enable_endpoint_detection=True,
        rule1_min_trailing_silence=2.4,
        rule2_min_trailing_silence=1.2,
        rule3_min_utterance_length=20.0,
        decoding_method="greedy_search",
        provider="cpu",
    )

def main():
    if not MANIFEST.exists():
        raise FileNotFoundError(MANIFEST)
    clips = []
    with MANIFEST.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                clips.append(json.loads(line))
    if not clips:
        raise RuntimeError("empty manifest")
    rec = build_recognizer()
    chunk = max(1, int(CHUNK_SEC * SR))
    tail = np.zeros(int(0.5 * SR), dtype=np.float32)
    total_ref = 0
    total_s = total_d = total_i = 0
    lat = []
    errors = []
    for idx, clip in enumerate(clips):
        wav = Path(str(clip["wav"]).replace("\\", "/"))
        if not wav.exists():
            wav = Path("data/fleurs_ru_test") / Path(wav).name
        if not wav.exists():
            raise FileNotFoundError(wav)
        samples = load_wav(wav)
        stream = rec.create_stream()
        t0 = time.perf_counter()
        for start in range(0, len(samples), chunk):
            block = samples[start:start + chunk]
            stream.accept_waveform(SR, block)
            while rec.is_ready(stream):
                rec.decode_stream(stream)
        stream.accept_waveform(SR, tail)
        stream.input_finished()
        while rec.is_ready(stream):
            rec.decode_stream(stream)
        decode_s = time.perf_counter() - t0
        lat.append(decode_s)
        hyp = rec.get_result(stream)
        ref = clip.get("ref", "")
        rt = norm(ref)
        ht = norm(hyp)
        s, d, i = edit_counts(rt, ht)
        total_ref += len(rt)
        total_s += s
        total_d += d
        total_i += i
        clip_wer = (s + d + i) / max(1, len(rt))
        if clip_wer > 0 and len(errors) < 10:
            errors.append({"clip_id": clip.get("clip_id", f"clip_{idx:03d}"), "ref": ref, "hyp": hyp})
    if not errors:
        c = clips[0]
        errors.append({"clip_id": c.get("clip_id", "clip_000"), "ref": c.get("ref", ""), "hyp": ""})
    wer = (total_s + total_d + total_i) / max(1, total_ref)
    lat_sorted = sorted(lat)
    def pct(p):
        if not lat_sorted:
            return 0.0
        k = (len(lat_sorted) - 1) * p
        f = int(math.floor(k))
        c = min(len(lat_sorted) - 1, f + 1)
        return lat_sorted[f] + (lat_sorted[c] - lat_sorted[f]) * (k - f)
    metrics = {
        "engine": "sherpa-onnx",
        "num_clips": len(clips),
        "total_ref_words": total_ref,
        "wer": round(wer, 6),
        "latency_p50": round(pct(0.5), 6),
        "latency_p95": round(pct(0.95), 6),
        "error_examples": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False))

if __name__ == "__main__":
    main()
