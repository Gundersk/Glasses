# -*- coding: utf-8 -*-
"""Файловый потоковый ASR-замер этапа 2: ресурсы (T1) и условия с шумом (T2).

Единый потоковый цикл: WAV подаётся чанками chunk_ms в темпе speed=1.0, в конце
добавляется тишина tail_s. Без браузера, динамика и микрофона.

    python experiments/file_stream_eval.py resources --engine sherpa \
        --wav data/fleurs_ru_test/clip_001.wav \
        --metrics experiments/stage2_resources/sherpa_resources.json \
        --result experiments/stage2_resources/sherpa_result.json

    python experiments/file_stream_eval.py conditions --engine sherpa \
        --manifest data/fleurs_ru_test/manifest.jsonl \
        --clips clip_000,clip_001,clip_002,clip_003,clip_004 --snr 20,10,5 \
        --seed 20261109 --noise-dir experiments/stage2_conditions/audio \
        --out experiments/stage2_conditions/sherpa_conditions.json

Задержка события = время события минус позиция конца последнего поданного чанка
в аудио. Значения из старых offline-бенчмарков сюда не переносятся.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import platform
import re
import sys
import time

import numpy as np
import soundfile as sf

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "e2e_audio"))
import streaming_asr  # noqa: E402

TARGET_SR = 16000
CONDITIONS = [("clean", None), ("snr20", 20), ("snr10", 10), ("snr5", 5)]


# ---------------------------------------------------------------- ввод/вывод
def load_wav(path: pathlib.Path) -> np.ndarray:
    x, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if x.ndim == 2:
        x = x.mean(axis=1)
    x = np.asarray(x, dtype=np.float32)
    if int(sr) != TARGET_SR:
        x = streaming_asr.resample_to_16k(x, sr)
    return x


def norm(text: str) -> list[str]:
    text = (text or "").lower().replace("ё", "е")
    text = re.sub(r"[^а-яa-z0-9]+", " ", text)
    return text.split()


def edit_counts(ref: list[str], hyp: list[str]) -> tuple[int, int, int]:
    """Возвращает (S, D, I) для пары эталон/гипотеза."""
    m, n = len(ref), len(hyp)
    dp = [[(0, 0, 0, 0)] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        c, s, d, ins = dp[i - 1][0]
        dp[i][0] = (c + 1, s, d + 1, ins)
    for j in range(1, n + 1):
        c, s, d, ins = dp[0][j - 1]
        dp[0][j] = (c + 1, s, d, ins + 1)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            c, s, d, ins = dp[i - 1][j]
            best = (c + 1, s, d + 1, ins)
            c, s, d, ins = dp[i][j - 1]
            cand = (c + 1, s, d, ins + 1)
            if cand[0] < best[0]:
                best = cand
            c, s, d, ins = dp[i - 1][j - 1]
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            cand = (c + cost, s + cost, d, ins)
            if cand[0] < best[0]:
                best = cand
            dp[i][j] = best
    _c, s, d, ins = dp[m][n]
    return s, d, ins


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    k = (len(xs) - 1) * p
    lo = int(math.floor(k))
    hi = min(len(xs) - 1, lo + 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


# ---------------------------------------------------------------- поток
def stream_file(asr, samples: np.ndarray, chunk: int, speed: float = 1.0,
                monitor=None) -> dict:
    """Единый потоковый цикл. n_frames считается в отсчётах аудио, не в чанках."""
    total = int(samples.shape[0])
    t0 = time.perf_counter()
    next_tick = t0
    pos = 0
    n_frames = 0
    last_ref_ms = 0.0
    partials: list[dict] = []
    finals: list[dict] = []
    last_partial = ""
    while pos < total:
        piece = samples[pos:pos + chunk]
        pos += int(piece.shape[0])
        n_frames += int(piece.shape[0])
        text = asr.accept(piece, sample_rate=TARGET_SR)
        now = time.perf_counter()
        wall_ms = (now - t0) * 1000.0
        source_ms = pos / TARGET_SR * 1000.0
        # Момент, когда поданный чанк фактически ушёл в движок: чанк подаётся сразу,
        # а темп держится сном, поэтому конец чанка доступен на (pos - chunk).
        ref_ms = (pos - int(piece.shape[0])) / TARGET_SR * 1000.0
        last_ref_ms = ref_ms
        if text and text != last_partial:
            last_partial = text
            partials.append({"t_ms": round(wall_ms, 1),
                             "source_pos_ms": round(source_ms, 1),
                             "latency_ms": round(wall_ms - ref_ms, 1),
                             "text": text})
        if asr.is_endpoint():
            fin = asr.finalize()
            if fin:
                now2 = time.perf_counter()
                wall2 = (now2 - t0) * 1000.0
                item = {"t_ms": round(wall2, 1),
                        "source_pos_ms": round(source_ms, 1),
                        "latency_ms": round(wall2 - ref_ms, 1),
                        "text": fin}
                finals.append(item)
            asr.reset()
            last_partial = ""
        if monitor is not None:
            monitor()
        next_tick += (piece.shape[0] / TARGET_SR) / speed
        delay = next_tick - time.perf_counter()
        if delay > 0:
            time.sleep(delay)

    fin = asr.finalize()
    if fin:
        now = time.perf_counter()
        wall_ms = (now - t0) * 1000.0
        source_ms = total / TARGET_SR * 1000.0
        finals.append({"t_ms": round(wall_ms, 1),
                       "source_pos_ms": round(source_ms, 1),
                       "latency_ms": round(wall_ms - last_ref_ms, 1),
                       "text": fin})
    return {"partials": partials, "finals": finals,
            "n_frames": n_frames, "wall_s": time.perf_counter() - t0}


def _init_engine(engine: str):
    asr, status = streaming_asr.create_asr(engine)
    if asr is None or status is None or not status.ok:
        message = status.message if status is not None else "create_asr вернул None"
        print(f"FAIL init {engine}: {message}", file=sys.stderr)
    return asr, status


# ---------------------------------------------------------------- resources
def run_resources(engine: str, wav: pathlib.Path, metrics_path: pathlib.Path,
                  result_path: pathlib.Path, chunk_ms: int = 100, speed: float = 1.0,
                  tail_s: float = 1.0, cpu_interval_s: float = 0.05) -> int:
    import psutil

    audio = load_wav(wav)
    tail = np.zeros(int(round(tail_s * TARGET_SR)), dtype=np.float32)
    stream = np.concatenate([audio, tail]).astype(np.float32)
    sample_count = int(stream.shape[0])
    chunk = max(1, int(round(chunk_ms / 1000.0 * TARGET_SR)))

    asr, status = _init_engine(engine)
    if asr is None:
        return 2

    proc = psutil.Process()
    proc.cpu_percent(None)          # калибровка: первый вызов всегда 0.0
    time.sleep(cpu_interval_s)

    cpu_samples: list[float] = []
    rss_mb_max = 0.0

    def monitor():
        nonlocal rss_mb_max
        cpu_samples.append(float(proc.cpu_percent(None)))
        rss_mb_max = max(rss_mb_max, proc.memory_info().rss / (1024.0 * 1024.0))

    res = stream_file(asr, stream, chunk, speed=speed, monitor=monitor)
    rss_mb_max = max(rss_mb_max, proc.memory_info().rss / (1024.0 * 1024.0))

    finals = res["finals"]
    asr_ok = bool(status.ok and asr.status.ok and finals
                  and all(f["text"].strip() for f in finals))
    cpu_avg = float(sum(cpu_samples) / len(cpu_samples)) if cpu_samples else 0.0

    metrics = {
        "engine": engine,
        "wav": str(wav).replace("\\", "/"),
        "chunk_ms": chunk_ms,
        "speed": speed,
        "tail_s": tail_s,
        "sample_rate": TARGET_SR,
        "sample_count": sample_count,
        "n_frames": res["n_frames"],
        "cpu_percent_avg": round(cpu_avg, 3),
        "cpu_percent_max": round(max(cpu_samples), 3) if cpu_samples else 0.0,
        "rss_mb_max": round(rss_mb_max, 3),
        "wall_s": round(res["wall_s"], 4),
        "cpu_interval_s": cpu_interval_s,
        "cpu_samples_n": len(cpu_samples),
        "command": " ".join([pathlib.Path(sys.executable).name,
                             "experiments/file_stream_eval.py", "resources",
                             "--engine", engine, "--wav", str(wav),
                             "--metrics", str(metrics_path),
                             "--result", str(result_path)]),
        "model_version": status.version,
        "asr_config": status.config,
        "n_frames_unit": "audio_samples",
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    result = {
        "engine": engine,
        "wav": str(wav).replace("\\", "/"),
        "simulated": False,
        "asr_ok": asr_ok,
        "partials": res["partials"],
        "finals": finals,
        "events": {
            "n_partials": len(res["partials"]),
            "n_finals": len(finals),
            "partials_per_s": round(len(res["partials"]) / max(res["wall_s"], 1e-9), 3),
        },
        "n_frames": res["n_frames"],
        "sample_count": sample_count,
        "wall_s": round(res["wall_s"], 4),
        "status_message": status.message,
    }

    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: metrics[k] for k in ("engine", "cpu_percent_avg", "cpu_percent_max",
                                              "rss_mb_max", "wall_s", "n_frames")}
                     | {"asr_ok": asr_ok}, ensure_ascii=False))
    return 0 if asr_ok else 1


# ---------------------------------------------------------------- conditions
def _noise_wav(clean: np.ndarray, snr_db: float, seed: int, out_path: pathlib.Path) -> dict:
    """Белый гауссов шум по заданному SNR. Пишет float32 WAV и возвращает паспорт."""
    rng = np.random.default_rng(seed)
    p_sig = float(np.mean(np.square(clean))) or 1e-12
    sigma = math.sqrt(p_sig / (10.0 ** (snr_db / 10.0)))
    noise = rng.normal(0.0, sigma, size=clean.shape).astype(np.float32)
    noisy = (np.asarray(clean, dtype=np.float32) + noise).astype(np.float32)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), noisy, TARGET_SR, subtype="FLOAT")
    measured_noise = np.asarray(noisy, dtype=np.float32) - np.asarray(clean, dtype=np.float32)
    p_noise = float(np.mean(np.square(measured_noise))) or 1e-12
    measured_snr = round(10.0 * math.log10(float(np.mean(np.square(clean))) / p_noise), 3)
    return {"path": str(out_path).replace("\\", "/"),
            "target_snr_db": snr_db, "measured_snr_db": measured_snr,
            "seed": seed, "sigma": round(sigma, 6),
            "sample_count": int(clean.shape[0])}


def _write_noise_manifest(path: pathlib.Path, new_files: list[dict], seed: int,
                          chunk_ms: int, tail_s: float) -> None:
    """Слить паспорта шумных WAV с прежними, а не перезаписать текущим прогоном.

    Второй движок переиспользует готовые WAV и новых не создаёт, поэтому
    манифест, записанный только текущим прогоном, терял бы чужие записи.
    Другой seed не смешиваем: тогда прежние записи отбрасываются, иначе
    в одном файле окажутся разные условия.
    """
    merged: dict[tuple[str, str], dict] = {}
    if path.is_file():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("seed") == seed:
                for f in old.get("files") or []:
                    merged[(f["clip_id"], f["condition"])] = f
        except (json.JSONDecodeError, KeyError, TypeError):
            merged = {}
    for f in new_files:
        merged[(f["clip_id"], f["condition"])] = f
    files_out = sorted(merged.values(), key=lambda f: (f["clip_id"], f["condition"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"seed": seed, "sample_rate": TARGET_SR, "chunk_ms": chunk_ms,
         "tail_s": tail_s, "files": files_out},
        ensure_ascii=False, indent=2), encoding="utf-8")


def run_conditions(engine: str, manifest: pathlib.Path, clips: list[str], snrs: list[float],
                   seed: int, noise_dir: pathlib.Path, out: pathlib.Path,
                   chunk_ms: int = 100, speed: float = 1.0, tail_s: float = 1.0) -> int:
    refs = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        refs[item["clip_id"]] = item

    missing = [c for c in clips if c not in refs]
    if missing:
        print(f"FAIL: нет клипов в манифесте: {missing}", file=sys.stderr)
        return 2

    chunk = max(1, int(round(chunk_ms / 1000.0 * TARGET_SR)))
    tail = np.zeros(int(round(tail_s * TARGET_SR)), dtype=np.float32)

    # Готовим шумные WAV один раз и переиспользуем их для обоих движков.
    noise_manifest_path = noise_dir.parent / "noise_manifest.json"
    noise_files: list[dict] = []
    wav_by_condition: dict[str, dict[str, pathlib.Path]] = {}
    for cond_name, snr_db in CONDITIONS:
        wav_by_condition[cond_name] = {}
        for i, clip_id in enumerate(clips):
            src = pathlib.Path(str(refs[clip_id]["wav"]).replace("\\", "/"))
            if not src.is_file():
                print(f"FAIL: нет WAV {src}", file=sys.stderr)
                return 2
            if snr_db is None:
                wav_by_condition[cond_name][clip_id] = src
                continue
            dst = noise_dir / f"{clip_id}_{cond_name}.wav"
            if dst.is_file():
                wav_by_condition[cond_name][clip_id] = dst
                continue
            clean = load_wav(src)
            info = _noise_wav(clean, float(snr_db), seed + i, dst)
            info.update({"clip_id": clip_id, "source_wav": str(src).replace("\\", "/"),
                         "condition": cond_name})
            noise_files.append(info)
            wav_by_condition[cond_name][clip_id] = dst

    asr, status = _init_engine(engine)
    if asr is None:
        return 2

    conditions_out = []
    for cond_name, snr_db in CONDITIONS:
        results = []
        total_ref = total_s = total_d = total_i = 0
        final_lat: list[float] = []
        partial_lat: list[float] = []
        for clip_id in clips:
            wav = wav_by_condition[cond_name][clip_id]
            samples = np.concatenate([load_wav(wav), tail]).astype(np.float32)
            asr.reset()
            res = stream_file(asr, samples, chunk, speed=speed)
            hyp = " ".join(f["text"] for f in res["finals"]).strip()
            ref = str(refs[clip_id].get("ref", ""))
            rt, ht = norm(ref), norm(hyp)
            s, d, i = edit_counts(rt, ht)
            total_ref += len(rt)
            total_s += s
            total_d += d
            total_i += i
            final_lat.extend(float(f["latency_ms"]) for f in res["finals"])
            partial_lat.extend(float(p["latency_ms"]) for p in res["partials"])
            results.append({
                "clip_id": clip_id,
                "wav": str(wav).replace("\\", "/"),
                "ref": ref,
                "hyp": hyp,
                "s": s, "d": d, "i": i, "ref_words": len(rt),
                "partials": res["partials"],
                "finals": res["finals"],
                "n_frames": res["n_frames"],
                "wall_s": round(res["wall_s"], 4),
            })
        wer = (total_s + total_d + total_i) / max(1, total_ref)
        conditions_out.append({
            "name": cond_name,
            "snr_db": snr_db,
            "wer": round(wer, 6),
            "s": total_s, "d": total_d, "i": total_i,
            "ref_words": total_ref,
            "final_latency_p50_ms": pct(final_lat, 0.5),
            "final_latency_p95_ms": pct(final_lat, 0.95),
            "final_latency_n": len(final_lat),
            "partial_latency_p50_ms": pct(partial_lat, 0.5),
            "partial_latency_p95_ms": pct(partial_lat, 0.95),
            "partial_latency_n": len(partial_lat),
            "results": results,
        })
        print(f"{engine} {cond_name}: WER {wer:.4f} finals {len(final_lat)} "
              f"partials {len(partial_lat)}", file=sys.stderr)
        # Пишем JSON после каждого условия: иначе обрыв по таймауту теряет и
        # готовые условия, а утро получает «ничего не было» вместо «clean готов,
        # snr20 нет». partial=true явно говорит, что набор условий неполный,
        # и приёмка такой файл как результат не принимает.
        _write_conditions(out, engine, seed, clips, chunk_ms, speed, tail_s, manifest,
                          status, conditions_out, partial=True)

    if not noise_files and noise_manifest_path.is_file():
        noise_files = json.loads(noise_manifest_path.read_text(encoding="utf-8"))["files"]
    elif noise_files:
        _write_noise_manifest(noise_manifest_path, noise_files, seed, chunk_ms, tail_s)

    _write_conditions(out, engine, seed, clips, chunk_ms, speed, tail_s, manifest,
                      status, conditions_out, partial=False)
    print(json.dumps({c["name"]: c["wer"] for c in conditions_out}, ensure_ascii=False))
    return 0


def _write_conditions(out: pathlib.Path, engine: str, seed: int, clips: list[str],
                      chunk_ms: int, speed: float, tail_s: float,
                      manifest: pathlib.Path, status, conditions_out: list[dict],
                      partial: bool) -> None:
    """Записать JSON условий (в том числе частичный набор при обрыве)."""
    payload = {
        "engine": engine,
        "seed": seed,
        "n_clips": len(clips),
        "clips": clips,
        "chunk_ms": chunk_ms,
        "speed": speed,
        "tail_s": tail_s,
        "sample_rate": TARGET_SR,
        "manifest": str(manifest).replace("\\", "/"),
        "model_version": status.version,
        "asr_config": status.config,
        "status_message": status.message,
        "partial": partial,
        "conditions": conditions_out,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- CLI
def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)

    r = sub.add_parser("resources")
    r.add_argument("--engine", required=True, choices=["sherpa", "vosk"])
    r.add_argument("--wav", required=True)
    r.add_argument("--metrics", required=True)
    r.add_argument("--result", required=True)
    r.add_argument("--chunk-ms", type=int, default=100)
    r.add_argument("--speed", type=float, default=1.0)
    r.add_argument("--tail-s", type=float, default=1.0)

    c = sub.add_parser("conditions")
    c.add_argument("--engine", required=True, choices=["sherpa", "vosk"])
    c.add_argument("--manifest", required=True)
    c.add_argument("--clips", required=True)
    c.add_argument("--snr", default="20,10,5")
    c.add_argument("--seed", type=int, default=20261109)
    c.add_argument("--noise-dir", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--chunk-ms", type=int, default=100)
    c.add_argument("--speed", type=float, default=1.0)
    c.add_argument("--tail-s", type=float, default=1.0)

    args = ap.parse_args()
    if args.mode == "resources":
        wav = pathlib.Path(args.wav)
        if not wav.is_file():
            print(f"нет файла: {wav}", file=sys.stderr)
            return 2
        return run_resources(args.engine, wav, pathlib.Path(args.metrics),
                             pathlib.Path(args.result), chunk_ms=args.chunk_ms,
                             speed=args.speed, tail_s=args.tail_s)

    clips = [x.strip() for x in args.clips.split(",") if x.strip()]
    snrs = [float(x) for x in args.snr.split(",") if x.strip()]
    if snrs != [20.0, 10.0, 5.0]:
        print(f"FAIL: план фиксирует SNR 20,10,5, получено {snrs}", file=sys.stderr)
        return 2
    return run_conditions(args.engine, pathlib.Path(args.manifest), clips, snrs,
                          args.seed, pathlib.Path(args.noise_dir),
                          pathlib.Path(args.out), chunk_ms=args.chunk_ms,
                          speed=args.speed, tail_s=args.tail_s)


if __name__ == "__main__":
    raise SystemExit(main())
