# -*- coding: utf-8 -*-
"""Диагностика: что реально в audio у FLEURS parquet, и почему движки молчат."""
import io
import wave
import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download

p = hf_hub_download(repo_id="google/fleurs",
                    filename="parquet-data/ru_ru/test-00000-of-00001.parquet",
                    repo_type="dataset")
df = pd.read_parquet(p)
print("columns:", list(df.columns))
row = df.iloc[0]
audio = row["audio"]
print("audio type:", type(audio))
if isinstance(audio, dict):
    print("audio keys:", list(audio.keys()))
    for k, v in audio.items():
        if isinstance(v, (bytes, memoryview)):
            print(f"  {k}: bytes len={len(v)} head={bytes(v[:16])!r}")
        elif isinstance(v, np.ndarray):
            print(f"  {k}: ndarray shape={v.shape} dtype={v.dtype} rms={np.sqrt(np.mean(v**2)):.4f}")
        else:
            print(f"  {k}: {type(v)} = {str(v)[:80]}")

raw = audio.get("bytes") if isinstance(audio, dict) else audio
if raw is not None:
    raw = bytes(raw)
    print("raw len:", len(raw), "head:", raw[:16])
    try:
        w = wave.open(io.BytesIO(raw), "rb")
        print("wave opens: sr", w.getframerate(), "ch", w.getnchannels(), "width", w.getsampwidth(), "frames", w.getnframes())
        frames = w.readframes(w.getnframes())
        a = np.frombuffer(frames, dtype=np.int16)
        print("PCM rms:", float(np.sqrt(np.mean(a.astype(float)**2))), "max:", int(np.abs(a).max()))
        # спектральный центроид: речь vs шум
        spec = np.abs(np.fft.rfft(a[:16000].astype(float)))
        freqs = np.fft.rfftfreq(16000, 1/16000)
        centroid = float(np.sum(freqs*spec)/np.sum(spec))
        zcr = float(np.mean(np.abs(np.diff(np.sign(a))))/2)
        print("spectral centroid Hz:", round(centroid,1), "| ZCR:", round(zcr,3))
    except Exception as e:
        print("wave FAIL:", type(e).__name__, str(e)[:120])
