import json
import os
import wave
import numpy as np
from itertools import permutations

WAV_PATH = "experiments/data/two_speaker.wav"
REF_PATH = "experiments/data/two_speaker_ref.json"
OUT_PATH = "experiments/diarization/diar_baseline_metrics.json"


def read_wav_mono(path):
    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        channels = wf.getnchannels()
        sw = wf.getsampwidth()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)
    if sw != 2:
        raise ValueError("Only 16-bit PCM supported")
    data = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels)
        data = data.mean(axis=1)
    else:
        data = data.reshape(-1)
    return data.astype(np.float64) / 32768.0, sr


def make_windows(x, sr, frame_ms=25, step_ms=10):
    frame_len = int(round(sr * frame_ms / 1000.0))
    step_len = int(round(sr * step_ms / 1000.0))
    if frame_len <= 0:
        frame_len = 1
    if step_len <= 0:
        step_len = 1
    starts = np.arange(0, max(0, len(x) - frame_len + 1), step_len, dtype=np.int64)
    windows = []
    times = []
    for s in starts:
        w = x[s:s + frame_len]
        if len(w) < frame_len:
            w = np.pad(w, (0, frame_len - len(w)), mode="constant")
        windows.append(w)
        times.append((s + frame_len / 2.0) / sr)
    return np.array(windows, dtype=np.float64), np.array(times, dtype=np.float64)


def fft_log_bands(windows, sr, n_bands=24):
    if windows.size == 0:
        return np.zeros((0, n_bands), dtype=np.float64)
    frame_len = windows.shape[1]
    fft = np.fft.rfft(windows, axis=1)
    mag = np.abs(fft)
    freqs = np.fft.rfftfreq(frame_len, d=1.0 / sr)
    edges = np.linspace(0.0, sr / 2.0, n_bands + 1)
    feats = np.zeros((windows.shape[0], n_bands), dtype=np.float64)
    for b in range(n_bands):
        lo = edges[b]
        hi = edges[b + 1]
        mask = (freqs >= lo) & (freqs < hi)
        if b == n_bands - 1:
            mask = (freqs >= lo) & (freqs <= hi)
        if mask.any():
            feats[:, b] = np.log1p(mag[:, mask].sum(axis=1))
    return feats


def normalize_features(feats):
    if feats.size == 0:
        return feats
    mean = feats.mean(axis=0)
    std = feats.std(axis=0)
    std[std < 1e-12] = 1.0
    return (feats - mean) / std


def kmeans2(feats, seed=0, iters=2):
    n = feats.shape[0]
    if n == 0:
        return np.array([], dtype=int)
    if n == 1:
        return np.array([0], dtype=int)
    rng = np.random.default_rng(seed)
    centers = feats[rng.choice(n, 2, replace=False)].copy()
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        d0 = ((feats - centers[0]) ** 2).sum(axis=1)
        d1 = ((feats - centers[1]) ** 2).sum(axis=1)
        labels = np.where(d0 <= d1, 0, 1)
        for k in (0, 1):
            mask = labels == k
            if mask.any():
                centers[k] = feats[mask].mean(axis=0)
    return labels


def true_speaker_for_times(times, segments):
    true = []
    if not segments:
        return np.array([], dtype=str)
    for t in times:
        chosen = None
        for seg in segments:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
            if start <= t < end:
                chosen = str(seg.get("speaker", "A"))
                break
        if chosen is None:
            best = None
            best_dist = None
            for seg in segments:
                start = float(seg.get("start", 0.0))
                end = float(seg.get("end", 0.0))
                mid = (start + end) / 2.0
                dist = abs(t - mid)
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = str(seg.get("speaker", "A"))
            chosen = best
        true.append(chosen)
    return np.array(true, dtype=str)


def frame_accuracy(labels, true_labels):
    if len(labels) == 0:
        return 0.0
    clusters = sorted(set(int(x) for x in labels))
    speakers = sorted(set(true_labels.tolist()))
    if not speakers:
        return 0.0
    if len(clusters) == 0:
        return 0.0
    best = 0.0
    if len(clusters) > len(speakers):
        speakers = speakers + [speakers[0]] * (len(clusters) - len(speakers))
    for perm in permutations(speakers, len(clusters)):
        mapping = dict(zip(clusters, perm))
        pred = np.array([mapping[int(l)] for l in labels], dtype=str)
        acc = float(np.mean(pred == true_labels))
        if acc > best:
            best = acc
    return best


def main():
    if not os.path.exists(WAV_PATH):
        raise SystemExit(f"Missing WAV: {WAV_PATH}")
    if not os.path.exists(REF_PATH):
        raise SystemExit(f"Missing REF: {REF_PATH}")
    with open(REF_PATH, "r", encoding="utf-8") as f:
        ref = json.load(f)
    x, sr = read_wav_mono(WAV_PATH)
    windows, times = make_windows(x, sr)
    feats = fft_log_bands(windows, sr, 24)
    feats = normalize_features(feats)
    labels = kmeans2(feats, seed=0, iters=2)
    num_windows = int(len(labels))
    num_detected = int(len(set(labels.tolist()))) if num_windows else 0
    num_change_points = int(np.sum(labels[1:] != labels[:-1])) if num_windows > 1 else 0
    true_labels = true_speaker_for_times(times, ref.get("segments", []))
    acc = frame_accuracy(labels, true_labels)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    metrics = {
        "method": "numpy_fft_24band_2means_baseline",
        "synthetic": True,
        "num_detected_speakers": num_detected,
        "num_change_points": num_change_points,
        "frame_accuracy": acc,
        "num_windows": num_windows,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
