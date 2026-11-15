from pathlib import Path
import io
import json
import sys
import wave

import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download

REPO_ID = "google/fleurs"
FILENAME = "parquet-data/ru_ru/test-00000-of-00001.parquet"
OUT_DIR = Path("data/fleurs_ru_test")
TARGET_RATE = 16000
TARGET_CHANNELS = 1
TARGET_WIDTH = 2

def get_audio_bytes(row):
    audio = row.get("audio")
    if isinstance(audio, dict):
        return audio.get("bytes")
    return audio

def pcm_to_wav(data, rate=TARGET_RATE, channels=TARGET_CHANNELS, width=TARGET_WIDTH):
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(data.tobytes())
    return out.getvalue()

def normalize_wav_bytes(raw):
    # FLEURS хранит WAV формата 3 (IEEE float32), который wave-модуль НЕ читает.
    # Поэтому читаем через soundfile (понимает float32), приводим к mono 16k PCM16.
    import soundfile as sf
    data, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
    mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    if sr != TARGET_RATE and len(mono) > 0:
        target_len = max(1, int(len(mono) * TARGET_RATE / sr))
        x = np.linspace(0, len(mono) - 1, target_len)
        mono = np.interp(x, np.arange(len(mono)), mono).astype(np.float32)
    samples = (np.clip(mono, -1.0, 1.0) * 32767.0).astype(np.int16)
    return pcm_to_wav(samples)

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = hf_hub_download(repo_id=REPO_ID, filename=FILENAME, repo_type="dataset")
    df = pd.read_parquet(parquet_path)
    if len(df) < 50:
        raise SystemExit(f"Not enough rows in test parquet: {len(df)}")
    manifest = []
    for i in range(50):
        row = df.iloc[i]
        raw = get_audio_bytes(row)
        if raw is None:
            raise SystemExit(f"Missing audio bytes in row {i}")
        if isinstance(raw, memoryview):
            raw = raw.tobytes()
        wav_bytes = normalize_wav_bytes(raw)
        clip_id = f"clip_{i:03d}"
        wav_path = OUT_DIR / f"{clip_id}.wav"
        wav_path.write_bytes(wav_bytes)
        ref = row.get("raw_transcription")
        if ref is None:
            ref = row.get("transcription")
        ref = str(ref).strip()
        if not ref:
            raise SystemExit(f"Empty reference in row {i}")
        manifest.append({"clip_id": clip_id, "wav": str(wav_path), "ref": ref})
    manifest_path = OUT_DIR / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as f:
        for item in manifest:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"prepared {len(manifest)} clips in {OUT_DIR}")

if __name__ == "__main__":
    main()
