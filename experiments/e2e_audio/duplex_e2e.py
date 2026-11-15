"""Акустический E2E: динамики -> воздух -> микрофон -> потоковый ASR.

Шаги прогона:
  1. Первые N клипов из data/fleurs_ru_test склеиваются через паузу gap_s, нормируются по RMS всей склейки
     в target_dbfs (усиление ограничено пиком -1 dBFS против клиппинга), fade 20 мс на краях каждого клипа. Склейка в 48 кГц - это и есть проигрываемый сигнал.
  2. Один sd.Stream(48000, blocksize=1024, channels=(1,1), float32) одновременно играет склейку и пишет
     микрофон. По каждому callback фиксируются (индекс, adc, dac, currentTime, perf_counter).
  3. Лаг ПЕРЕМЕРЯЕТСЯ кросс-корреляцией записи с проигранным сигналом (константы нет).
  4. Запись (16-bit PCM, 48 кГц) пересэмплируется в 16 кГц и подаётся в streaming_asr в темпе 1.0
     чанками 100 мс (t0 подачи = начало записи, t0_resend_ms = 0).
  5. latency_ms      = t_final_ms - t0_resend_ms - lag_ms - source_end_ms
     endpoint_wait_ms = t_final_ms - t_first_chunk_after_source_end_ms (реальное время подачи чанка)
     Это РАЗНЫЕ величины; source_end_ms берётся из ИСХОДНИКА (последний кадр речи клипа), а не из
     срабатывания детектора. Финалы, оборванные посреди речи (mid_speech) или принудительно на EOF,
     в latency/endpoint_wait не входят.
  6. Если corr_peak < 0.5 или сигнала нет - статус blocked_*, metrics.json НЕ пишется, числа не выдумываются.

Коды выхода: 0 запись и метрики собраны (вердикт - у validate_run/gate), 2 blocked_no_device,
3 blocked_low_correlation, 4 blocked_no_signal, 5 ошибка ASR/подачи.
Веб-страница не поднимается: --port принят для совместимости CLI и не используется.
"""
import argparse
import csv
import datetime
import json
import math
import pathlib
import platform
import subprocess
import sys
import threading
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import streaming_asr  # noqa: E402
import validate_run  # noqa: E402

FLEURS = ROOT / "data" / "fleurs_ru_test"
SR = 48000
FADE_MS = 20.0
# Критерий приёмки записи: медиана корреляции по валидным окнам 4 с, а не глобальный пик.
# Причина: ADC микрофона и DAC динамиков тактируются независимыми генераторами (~55 ppm),
# плюс проскоки буфера; глобальная корреляция записи длиннее ~30 с размывается и падает ниже 0.5.
MIN_CORR_PEAK = validate_run.MIN_CORR_PEAK
MIN_VALID_FRAC = validate_run.CORR_MIN_VALID_FRAC
MAX_DRIFT_PPM = validate_run.DRIFT_LIMIT_PPM
MIN_PEAK_DBFS = -50.0
MAX_LAG_S = 2.5
PEAK_CAP_DBFS = -1.0
EXIT = {"ok": 0, "blocked_no_device": 2, "blocked_low_correlation": 3, "blocked_no_signal": 4, "asr_error": 5}


# ------------------------------------------------------------------ утилиты
def db10(x, eps=1e-12):
    return 10.0 * math.log10(max(float(x), eps))


def rms_dbfs(x):
    x = np.asarray(x, dtype=np.float64)
    return db10(np.mean(x * x)) if len(x) else float("nan")


def pct(values, p):
    return float(np.percentile(values, p)) if len(values) else 0.0


class Log:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")

    def __call__(self, msg):
        line = f"{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]} {msg}"
        self.f.write(line + "\n")
        self.f.flush()
        print(line, flush=True)


def fade_edges(x, n):
    n = min(n, len(x) // 2)
    if n > 0:
        r = np.linspace(0.0, 1.0, n, dtype=np.float32)
        x[:n] *= r
        x[-n:] *= r[::-1]
    return x


def speech_bounds(x16, frame=320, rel_db=-30.0):
    """Первый/последний кадр речи клипа (20 мс; порог = p95 энергии кадров -30 дБ). Возвращает отсчёты 16 кГц."""
    nf = len(x16) // frame
    e = np.mean(x16[: nf * frame].reshape(nf, frame).astype(np.float64) ** 2, axis=1)
    thr = float(np.percentile(e, 95)) * 10 ** (rel_db / 10.0)
    idx = np.where(e > thr)[0]
    if len(idx) == 0:
        return 0, len(x16)
    return int(idx[0] * frame), int((idx[-1] + 1) * frame)


# ------------------------------------------------------------------ источник
def build_source(n_clips, gap_s, target_dbfs, clips_dir):
    import soundfile as sf
    from scipy.signal import resample_poly
    files = sorted(clips_dir.glob("clip_*.wav"))[:n_clips]
    if len(files) < n_clips:
        raise FileNotFoundError(f"нужно {n_clips} клипов, найдено {len(files)} в {clips_dir}")
    parts, clips, pos16 = [], [], 0
    gap16 = int(round(gap_s * 16000))
    fade16 = int(FADE_MS * 16)
    for k, f in enumerate(files):
        x, sr = sf.read(str(f), dtype="float32", always_2d=False)
        if x.ndim == 2:
            x = x.mean(axis=1).astype(np.float32)
        x = streaming_asr.resample_to_16k(x, sr)
        s0, s1 = speech_bounds(x)
        x = fade_edges(x.copy(), fade16)
        clips.append({"file": f.name, "start_ms": pos16 / 16.0, "end_ms": (pos16 + len(x)) / 16.0,
                      "speech_start_ms": (pos16 + s0) / 16.0, "speech_end_ms": (pos16 + s1) / 16.0,
                      "orig_sr": int(sr), "duration_s": len(x) / 16000.0})
        parts.append(x)
        pos16 += len(x)
        if k < len(files) - 1:
            parts.append(np.zeros(gap16, dtype=np.float32))
            pos16 += gap16
    cat16 = np.concatenate(parts)
    play = resample_poly(cat16.astype(np.float64), 3, 1).astype(np.float32)  # 16 -> 48 кГц, ровно x3
    rms0 = rms_dbfs(play)
    gain = 10 ** ((target_dbfs - rms0) / 20.0)
    # crest-фактор FLEURS ~19-22 дБ: RMS -20 dBFS по всей склейке дал бы пик > 0 dBFS (клиппинг).
    # Поэтому усиление ограничивается пиком PEAK_CAP_DBFS; фактический RMS пишется в метрики.
    peak0 = float(np.max(np.abs(play)))
    cap_gain = 10 ** (PEAK_CAP_DBFS / 20.0) / peak0
    limited = gain > cap_gain
    if limited:
        gain = cap_gain
    play = (play * gain).astype(np.float32)
    play = fade_edges(play, int(FADE_MS * SR / 1000))
    peak = float(np.max(np.abs(play)))
    info = {"rms_before_dbfs": rms0, "gain_db": 20 * math.log10(gain), "rms_after_dbfs": rms_dbfs(play),
            "target_rms_dbfs": target_dbfs, "limited_by_peak": bool(limited), "peak_cap_dbfs": PEAK_CAP_DBFS,
            "peak_dbfs": 20 * math.log10(peak) if peak > 0 else -240.0, "n_samples": int(len(play)),
            "duration_s": len(play) / SR, "gap_s": gap_s, "fade_ms": FADE_MS}
    return play, clips, info


# ------------------------------------------------------------------ запись
def play_and_record(play, tail_s, blocksize, log):
    import sounddevice as sd
    din, dout = sd.default.device
    if din is None or dout is None or din < 0 or dout < 0:
        raise RuntimeError("нет устройства по умолчанию")
    di, do = sd.query_devices(din), sd.query_devices(dout)
    if di["max_input_channels"] < 1 or do["max_output_channels"] < 1:
        raise RuntimeError("у устройства по умолчанию нет каналов")
    sd.check_input_settings(device=din, samplerate=SR, channels=1, dtype="float32")
    sd.check_output_settings(device=dout, samplerate=SR, channels=1, dtype="float32")
    devs = {"input": {"index": int(din), "name": di["name"], "hostapi": sd.query_hostapis(di["hostapi"])["name"]},
            "output": {"index": int(dout), "name": do["name"], "hostapi": sd.query_hostapis(do["hostapi"])["name"]}}
    total = len(play) + int(tail_s * SR)
    play_pad = np.concatenate([play, np.zeros(total - len(play), np.float32)])
    rec = np.zeros(total + blocksize, np.float32)
    pos = [0]
    times, flags = [], []
    done = threading.Event()
    t_start = [None]

    def cb(indata, outdata, frames, time_info, status):
        i = pos[0]
        if i == 0:
            t_start[0] = time.perf_counter()
        if status:
            flags.append((i, str(status)))
        outdata[:] = 0
        n = min(frames, total - i)
        if n > 0:
            outdata[:n, 0] = play_pad[i:i + n]
            rec[i:i + n] = indata[:n, 0]
        times.append((i, float(time_info.inputBufferAdcTime), float(time_info.outputBufferDacTime),
                      float(time_info.currentTime), time.perf_counter()))
        pos[0] = i + frames
        if i + frames >= total:
            raise sd.CallbackStop

    st = sd.Stream(device=(din, dout), samplerate=SR, blocksize=blocksize, channels=(1, 1), dtype="float32",
                   callback=cb, finished_callback=done.set)
    lat = st.latency
    lat_in, lat_out = (float(lat[0]), float(lat[1])) if hasattr(lat, "__iter__") else (float(lat), float(lat))
    log(f"устройства: in=[{din}] {di['name']} ({devs['input']['hostapi']}), out=[{dout}] {do['name']} "
        f"({devs['output']['hostapi']}); stream.latency in={lat_in * 1000:.1f} ms out={lat_out * 1000:.1f} ms")
    log(f"ВОСПРОИЗВЕДЕНИЕ НАЧАЛОСЬ: {len(play) / SR:.1f} с + хвост {tail_s:.1f} с, RMS {rms_dbfs(play):.1f} dBFS")
    with st:
        if not done.wait(timeout=total / SR + 15):
            raise RuntimeError("таймаут: stream не завершился")
    log(f"запись завершена: {len(times)} callback-ов, status-флагов: {len(flags)}")
    return rec[:total].copy(), {"devices": devs, "latency_in_s": lat_in, "latency_out_s": lat_out,
                                "times": times, "flags": flags, "blocksize": blocksize}


# ------------------------------------------------------------------ лаг / корреляция
def xcorr_lag(ref, rec, sr, max_lag_s=MAX_LAG_S):
    """Нормированная кросс-корреляция ref (проигранный сигнал) и rec. Лаг 0..max_lag_s. -> (corr_peak, lag_samples)."""
    import scipy.signal as sig
    r = np.asarray(ref, np.float64)
    pad = int(max_lag_s * sr)
    xp = np.concatenate([np.asarray(rec, np.float64), np.zeros(len(r) + pad)])
    corr = sig.correlate(xp, r, mode="valid", method="fft")
    cs = np.concatenate([[0.0], np.cumsum(xp * xp)])
    ex = cs[len(r):] - cs[:-len(r)]
    nc = np.abs(corr) / (np.sqrt(np.maximum(ex, 0) * float(np.sum(r * r))) + 1e-12)
    nc = nc[: pad + 1]
    k = int(np.argmax(nc))
    return float(nc[k]), k


# ------------------------------------------------------------------ окна речь/пауза
def windows_snr(rec, sr, lag_ms, clips, rec_len_s):
    """Окна в записи: речь = [speech_start, speech_end] каждого клипа + лаг (с запасом 50 мс);
    пауза = лаг-преамбула, промежутки между клипами (запас 250 мс после речи, 100 мс до речи), хвост."""
    lag = lag_ms / 1000.0
    sp, pa = [], []
    for c in clips:
        a, b = c["speech_start_ms"] / 1000 + lag + 0.05, c["speech_end_ms"] / 1000 + lag - 0.05
        if b > a:
            sp.append((a, b))
    if lag > 0.15:
        pa.append((0.05, lag - 0.05))
    for c, nx in zip(clips, clips[1:]):
        a, b = c["speech_end_ms"] / 1000 + lag + 0.25, nx["speech_start_ms"] / 1000 + lag - 0.10
        if b - a >= 0.1:
            pa.append((a, b))
    a = clips[-1]["speech_end_ms"] / 1000 + lag + 0.25
    if rec_len_s - 0.05 - a >= 0.1:
        pa.append((a, rec_len_s - 0.05))

    def cat(ws):
        segs = [rec[int(a * sr):int(b * sr)] for a, b in ws]
        return np.concatenate(segs) if segs else np.zeros(0)

    s, p = cat(sp), cat(pa)
    if len(s) == 0 or len(p) == 0:
        raise ValueError("не удалось выделить окна речи/паузы")
    return {"speech_rms_dbfs": rms_dbfs(s), "pause_rms_dbfs": rms_dbfs(p),
            "snr_db": rms_dbfs(s) - rms_dbfs(p), "speech_s": len(s) / sr, "pause_s": len(p) / sr,
            "n_speech_windows": len(sp), "n_pause_windows": len(pa),
            "per_clip_speech_rms_dbfs": [rms_dbfs(rec[int(a * sr):int(b * sr)]) for a, b in sp],
            "windows_speech_s": [[round(a, 3), round(b, 3)] for a, b in sp],
            "windows_pause_s": [[round(a, 3), round(b, 3)] for a, b in pa]}


# ------------------------------------------------------------------ подача в ASR
def feed_asr(asr, x16, chunk_ms, log):
    sr = streaming_asr.TARGET_SR
    chunk = int(chunk_ms * sr / 1000)
    n = len(x16)
    partials, finals, chunk_t = [], [], []
    last_partial = ""
    t0 = time.perf_counter()
    for start in range(0, n, chunk):
        end = min(start + chunk, n)
        sched = end / sr
        while True:
            rem = sched - (time.perf_counter() - t0)
            if rem <= 0:
                break
            time.sleep(rem - 0.002 if rem > 0.004 else 0)
        t_feed = (time.perf_counter() - t0) * 1000.0
        chunk_t.append((end * 1000.0 / sr, t_feed))
        partial = asr.accept(x16[start:end], sr)
        if not asr.status.ok:
            raise RuntimeError(asr.status.message)
        pos_ms = end * 1000.0 / sr
        if asr.is_endpoint():
            final = asr.finalize()
            t_ev = (time.perf_counter() - t0) * 1000.0
            asr.reset()
            if final:
                finals.append({"text": final, "t_ms": round(t_ev, 3), "chunk_end_pos_ms": round(pos_ms, 3),
                               "reason": "endpoint"})
                log(f"FINAL(endpoint) t={t_ev:8.1f} ms pos={pos_ms:8.1f}: {final}")
            last_partial = ""
        elif partial and partial != last_partial:
            t_ev = (time.perf_counter() - t0) * 1000.0
            partials.append({"text": partial, "t_ms": round(t_ev, 3), "chunk_end_pos_ms": round(pos_ms, 3)})
            last_partial = partial
            log(f"partial t={t_ev:8.1f} ms pos={pos_ms:8.1f}: {partial}")
    final = asr.finalize()
    t_ev = (time.perf_counter() - t0) * 1000.0
    if final:
        finals.append({"text": final, "t_ms": round(t_ev, 3), "chunk_end_pos_ms": round(n * 1000.0 / sr, 3),
                       "reason": "eof"})
        log(f"FINAL(eof)      t={t_ev:8.1f} ms pos={n * 1000.0 / sr:8.1f}: {final}")
    return partials, finals, chunk_t, (time.perf_counter() - t0)


def annotate_finals(finals, clips, lag_ms, chunk_t, t0_resend_ms):
    """Сопоставляет финалы с концами фраз ИСХОДНИКА и считает latency_ms / endpoint_wait_ms.

    post_gap   - финал сработал после конца клипа c и до начала речи следующего: валиден;
    mid_speech - финал оборвал речь внутри клипа (напр. rule3 по длине): latency/endpoint_wait = None;
    eof        - принудительный сброс в конце входа: latency/endpoint_wait = None.
    """
    out, prev_se = [], 0.0
    for f in finals:
        p = f["chunk_end_pos_ms"]
        done = [i for i, c in enumerate(clips) if c["speech_end_ms"] + lag_ms <= p]
        c = done[-1] if done else -1
        last = len(clips) - 1
        g = dict(f)
        if f["reason"] == "eof":
            kind, se = "eof", clips[last]["speech_end_ms"]
        elif c >= 0 and (c == last or p < clips[c + 1]["speech_start_ms"] + lag_ms):
            kind, se = "post_gap", clips[c]["speech_end_ms"]
        else:
            kind, se = "mid_speech", p - lag_ms
        se = max(se, prev_se)
        prev_se = se
        g.update({"source_end_ms": round(se, 3), "kind": kind, "clip_index": c if kind == "post_gap" else None,
                  "latency_ms": None, "endpoint_wait_ms": None, "t_first_chunk_after_source_end_ms": None})
        if kind == "post_gap":
            g["latency_ms"] = round(f["t_ms"] - t0_resend_ms - lag_ms - se, 3)
            g["latency_vs_clip_end_ms"] = round(f["t_ms"] - t0_resend_ms - lag_ms - clips[c]["end_ms"], 3)
            nxt = [tf for pos_ms, tf in chunk_t if pos_ms > se + lag_ms]
            if nxt:
                g["t_first_chunk_after_source_end_ms"] = round(nxt[0], 3)
                g["endpoint_wait_ms"] = round(f["t_ms"] - nxt[0], 3)
        out.append(g)
    return out


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Акустический E2E: динамики -> микрофон -> потоковый ASR")
    ap.add_argument("--clips", type=int, default=3)
    ap.add_argument("--engine", default="sherpa", choices=sorted(streaming_asr.ENGINES))
    ap.add_argument("--target-dbfs", type=float, default=-20.0)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--gap-s", type=float, default=0.7)
    ap.add_argument("--port", type=int, default=0, help="не используется: страница не поднимается")
    ap.add_argument("--clips-dir", default=str(FLEURS))
    ap.add_argument("--chunk-ms", type=int, default=100)
    ap.add_argument("--blocksize", type=int, default=1024)
    ap.add_argument("--tail-s", type=float, default=2.5, help="запись после конца проигрывания")
    ap.add_argument("--countdown-s", type=float, default=2.0)
    ap.add_argument("--min-snr", type=float, default=10.0)
    ap.add_argument("--post-checks", action="store_true",
                    help="после прогона: validate_run + gate --allow-missing-dom --allow-missing-vision")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    import scipy
    import soundfile as sf
    import sounddevice as sd

    run_dir = pathlib.Path(a.run_dir)
    art = run_dir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    run_id = run_dir.name
    for n in ("metrics.json", "verdict.json", "run_verdict.json", "blocked.json"):
        (run_dir / n).unlink(missing_ok=True)
    for n in ("gate_stdout.txt", "validate_stdout.txt", "summary_table.txt"):
        (art / n).unlink(missing_ok=True)
    log = Log(run_dir / "log.txt")
    command = " ".join(sys.argv)
    log(f"run_id={run_id} команда: {command}")

    def blocked(status, reason, extra=None):
        d = {"status": status, "run_id": run_id, "reason": reason, "created": datetime.datetime.now().astimezone().isoformat(),
             **(extra or {})}
        (run_dir / "blocked.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"СТАТУС {status}: {reason}")
        return EXIT[status]

    # 1. источник
    play, clips, ninfo = build_source(a.clips, a.gap_s, a.target_dbfs, pathlib.Path(a.clips_dir))
    log(f"источник: {a.clips} клипов, {ninfo['duration_s']:.2f} с, RMS {ninfo['rms_after_dbfs']:.2f} dBFS, "
        f"peak {ninfo['peak_dbfs']:.2f} dBFS, gain {ninfo['gain_db']:+.2f} дБ")
    for k, c in enumerate(clips):
        log(f"  клип {k}: {c['file']} {c['duration_s']:.2f} с, речь {c['speech_start_ms']:.0f}..{c['speech_end_ms']:.0f} мс "
            f"(клип {c['start_ms']:.0f}..{c['end_ms']:.0f})")
    if ninfo["duration_s"] + a.tail_s > 45.0:
        return blocked("blocked_no_device", f"склейка {ninfo['duration_s']:.1f} с + хвост > 45 с: уменьшите --clips")
    if ninfo["limited_by_peak"]:
        log(f"ВНИМАНИЕ: RMS {a.target_dbfs:.1f} dBFS дал бы клиппинг; усиление ограничено пиком {PEAK_CAP_DBFS} dBFS, "
            f"фактический RMS {ninfo['rms_after_dbfs']:.2f} dBFS")
    sf.write(str(art / "source_played.wav"), play, SR, subtype="PCM_16")
    (run_dir / "source_info.json").write_text(json.dumps(ninfo | {"clips": clips}, ensure_ascii=False, indent=2),
                                              encoding="utf-8")

    # 2. запись
    log(f"через {a.countdown_s:.0f} с начнётся ТИХОЕ воспроизведение (~{ninfo['duration_s']:.0f} с, {a.target_dbfs:.0f} dBFS)")
    time.sleep(a.countdown_s)
    try:
        rec, meta = play_and_record(play, a.tail_s, a.blocksize, log)
    except Exception as e:  # noqa: BLE001
        return blocked("blocked_no_device", f"{type(e).__name__}: {str(e)[:300]}")
    sf.write(str(art / "recording.wav"), rec, SR, subtype="PCM_16")
    rec_rb, sr_rb = sf.read(str(art / "recording.wav"), dtype="float32")  # то, что видит валидатор
    assert sr_rb == SR
    with open(art / "chunk_times.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sample_index", "input_adc_time_s", "output_dac_time_s", "current_time_s", "perf_counter_s"])
        w.writerows(meta["times"])
    # dac-adc из PortAudio на MME берутся из РАЗНЫХ часов (вход и выход разных устройств) - разность бессмысленна
    # (в r1/r2 дала ~6.8e7 мс), поэтому в лог и метрики не идёт; лаг только из кросс-корреляции.
    pa_lag_ms = None

    # 3. лаг и корреляция: окна 4 с / шаг 2 с, медиана корреляции, линейная модель лага
    res = validate_run.recompute_corr_lag_windowed(play, SR, rec_rb, SR)
    corr_global = res["corr_global"]
    corr_peak = res["corr_peak"] if res["corr_peak"] is not None else 0.0
    lag_ms = res["lag_ms"] if res["lag_ms"] is not None else res["lag_global_ms"]
    drift_ppm = res["drift_ppm"]
    valid_frac = res["valid_window_fraction"]
    lag_samples = int(round(lag_ms * SR / 1000.0))
    peak_dbfs = 20 * math.log10(max(float(np.max(np.abs(rec_rb))), 1e-12))
    log(f"запись: {len(rec_rb) / SR:.2f} с, peak {peak_dbfs:.1f} dBFS, RMS {rms_dbfs(rec_rb):.1f} dBFS; "
        f"corr_global={corr_global:.4f} (справочно, лаг {res['lag_global_ms']:.1f} мс); "
        f"corr_peak={corr_peak:.4f} (медиана {res['n_valid']}/{res['n_windows']} валидных окон 4 с), "
        f"lag={lag_ms:.1f} мс (медиана локальных), drift="
        f"{'не определён' if drift_ppm is None else f'{drift_ppm:+.1f} ppm'}, "
        f"доля валидных окон={valid_frac:.2f}")
    diag = {"corr_peak": corr_peak, "corr_global": corr_global, "lag_ms": lag_ms,
            "lag_global_ms": res["lag_global_ms"], "drift_ppm": drift_ppm,
            "valid_window_fraction": valid_frac, "n_windows": res["n_windows"], "n_valid": res["n_valid"],
            "peak_dbfs": peak_dbfs, "rms_dbfs": rms_dbfs(rec_rb),
            "devices": meta["devices"], "recording_path": "artifacts/recording.wav",
            "corr_windows": res["windows"]}
    if peak_dbfs <= MIN_PEAK_DBFS:
        return blocked("blocked_no_signal", f"пик записи {peak_dbfs:.1f} dBFS <= {MIN_PEAK_DBFS}", diag | {"causes": [
            "микрофон отключён/muted или не тот вход по умолчанию", "приватность Windows блокирует микрофон",
            "динамики выключены или звук ушёл на другое устройство (Bluetooth/HDMI)"]})
    failed = []
    if corr_peak < MIN_CORR_PEAK:
        failed.append(f"corr_peak {corr_peak:.3f} < {MIN_CORR_PEAK}")
    if valid_frac < MIN_VALID_FRAC:
        failed.append(f"доля валидных окон {valid_frac:.2f} < {MIN_VALID_FRAC}")
    if drift_ppm is None:
        failed.append("drift_ppm не определён (меньше 2 валидных окон)")
    elif abs(drift_ppm) >= MAX_DRIFT_PPM:
        failed.append(f"|drift {drift_ppm:+.1f} ppm| >= {MAX_DRIFT_PPM}")
    if failed:
        return blocked("blocked_low_correlation", "; ".join(failed), diag | {"causes": [
            "микрофон ловит комнатный шум/голос, а не динамики (слишком тихо при -20 dBFS или далеко)",
            "включены AGC/шумоподавление микрофона и подавляют речь из динамиков",
            "звук идёт на другое устройство, не на Realtek-динамики",
            "дрейф/проскоки буфера делают лаг нестабильным (см. corr_windows)",
            "эхоподавление драйвера (AEC) вычитает воспроизводимый сигнал"]})

    # 4. SNR двумя способами + санити
    ws = windows_snr(rec_rb, SR, lag_ms, clips, len(rec_rb) / SR)
    snr_re, nfr, noise_db, sig_db = validate_run.recompute_snr(rec_rb.astype(np.float64), SR)
    log(f"SNR окна речь/пауза: {ws['snr_db']:.2f} дБ (речь {ws['speech_rms_dbfs']:.1f}, пауза {ws['pause_rms_dbfs']:.1f} dBFS); "
        f"SNR p90/p10 кадров 30 мс: {snr_re:.2f} дБ")

    # 5. ASR
    x16 = streaming_asr.resample_to_16k(rec_rb, SR)
    asr, status = streaming_asr.create_asr(a.engine)
    if asr is None:
        return blocked("asr_error", f"ASR не создан: {status.message}", diag)
    log(f"ASR {a.engine}: {status.version}; подача {len(x16) / 16000:.1f} с в темпе 1.0, чанки {a.chunk_ms} мс")
    t0_resend_ms = 0.0
    try:
        partials, finals_raw, chunk_t, wall = feed_asr(asr, x16, a.chunk_ms, log)
    except Exception as e:  # noqa: BLE001
        return blocked("asr_error", f"{type(e).__name__}: {str(e)[:300]}", diag)
    finals = annotate_finals(finals_raw, clips, lag_ms, chunk_t, t0_resend_ms)
    valid = [f for f in finals if f["latency_ms"] is not None]
    lat = [f["latency_ms"] for f in valid]
    epw = [f["endpoint_wait_ms"] for f in valid if f["endpoint_wait_ms"] is not None]
    for f in finals:
        log(f"  final kind={f['kind']} reason={f['reason']} source_end={f['source_end_ms']:.0f} мс "
            f"latency={f['latency_ms']} endpoint_wait={f['endpoint_wait_ms']}")

    metrics = {
        "kind": "e2e", "run_id": run_id, "created": datetime.datetime.now().astimezone().isoformat(),
        "simulated": False, "engine": a.engine,
        "source": {"type": "loopback", "path": "artifacts/source_played.wav", "duration_s": round(len(play) / SR, 3),
                   "n_clips": a.clips, "clips": clips, "gap_s": a.gap_s, "target_dbfs": a.target_dbfs,
                   "dataset": "data/fleurs_ru_test", "sample_rate": SR},
        "partial_count": len(partials), "final_count": len(finals),
        "first_partial_ms": min((p["t_ms"] for p in partials), default=0.0),
        "finals": finals, "partials": partials,
        "audio": {"recording_path": "artifacts/recording.wav",
                  "snr_db": round(ws["snr_db"], 3), "snr_db_recomputed": round(snr_re, 3),
                  "snr_method": "snr_db: RMS окон речи / RMS окон пауз (по позициям исходника + лаг); "
                                "snr_db_recomputed: p90/p10 энергий кадров 30 мс записи (как в validate_run)",
                  "corr_peak": round(corr_peak, 5), "lag_ms": round(lag_ms, 3), "lag_samples": int(lag_samples),
                  "corr_global": round(corr_global, 5), "lag_global_ms": round(res["lag_global_ms"], 3),
                  "drift_ppm": drift_ppm, "valid_window_fraction": round(valid_frac, 5),
                  "corr_windows": {"win_s": res["win_s"], "step_s": res["step_s"],
                                   "min_win_corr": res["min_win_corr"], "n_windows": res["n_windows"],
                                   "n_valid": res["n_valid"], "n_fit": res["n_fit"],
                                   "dropped_as_outliers": res["dropped_as_outliers"],
                                   "windows": res["windows"]},
                  "corr_method": "окна 4 с / шаг 2 с: в каждом окне лаг по кросс-корреляции; окна с corr<0.3 "
                                 "отброшены; corr_peak = медиана корреляции валидных окон; лаг - линейная модель "
                                 "по времени (Theil-Sen + отброс выбросов), drift_ppm = наклон; lag_ms = медиана "
                                 "локальных лагов. corr_global - справочное поле глобального пика, критерием не является",
                  "stream_latency_in": meta["latency_in_s"], "stream_latency_out": meta["latency_out_s"],
                  "stream_latency_unit": "s",
                  "lag_minus_stream_latency_ms": round(lag_ms - 1000.0 * (meta["latency_in_s"] + meta["latency_out_s"]), 3),
                  "sample_rate": SR, "blocksize": meta["blocksize"], "dtype": "float32",
                  "input_device": meta["devices"]["input"], "output_device": meta["devices"]["output"],
                  "recording_peak_dbfs": round(peak_dbfs, 2), "recording_rms_dbfs": round(rms_dbfs(rec_rb), 2),
                  "sanity": {k2: ws[k2] for k2 in ("speech_rms_dbfs", "pause_rms_dbfs", "per_clip_speech_rms_dbfs",
                                                   "speech_s", "pause_s", "n_speech_windows", "n_pause_windows")},
                  "callback_status_flags": len(meta["flags"]), "callback_status_first": meta["flags"][:3]},
        "timing": {"p50_ms": round(pct(lat, 50), 3), "p95_ms": round(pct(lat, 95), 3), "n": len(lat),
                   "basis": "latency_ms = t_final_ms - t0_resend_ms - lag_ms - source_end_ms (только post_gap endpoint-финалы)",
                   "t0_resend_ms": t0_resend_ms,
                   "endpoint_wait_p50_ms": round(pct(epw, 50), 3), "endpoint_wait_p95_ms": round(pct(epw, 95), 3),
                   "endpoint_wait_n": len(epw),
                   "endpoint_wait_basis": "t_final_ms - t_first_chunk_after_source_end_ms (реальное время подачи чанка)",
                   "excluded_finals": [{"kind": f["kind"], "reason": f["reason"], "text": f["text"][:60]}
                                       for f in finals if f["latency_ms"] is None]},
        "feed": {"speed": 1.0, "chunk_ms": a.chunk_ms, "feed_wall_s": round(wall, 3), "chunks": len(chunk_t),
                 "feed_lag_ms_max": round(max((tf - pos for pos, tf in chunk_t), default=0.0), 3)},
        "asr": status.as_dict(),
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(), "numpy": np.__version__,
                        "scipy": scipy.__version__, "sounddevice": sd.__version__, "soundfile": sf.__version__},
        "command": command,
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "config.json").write_text(json.dumps({
        "args": vars(a), "seed": None, "seed_note": "случайности нет: источник и ASR детерминированы; запись по воздуху недетерминирована",
        "asr": status.as_dict(), "command": command, "clips": clips, "normalization": ninfo,
        "devices": meta["devices"], "sample_rate": SR, "blocksize": a.blocksize,
        "windows": {"speech_s": ws["windows_speech_s"], "pause_s": ws["windows_pause_s"]},
        "environment": metrics["environment"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"metrics.json записан: partials={len(partials)} finals={len(finals)} valid_latency_n={len(lat)}")

    gate_line = "не запускалось"
    if a.post_checks:
        env = {**__import__("os").environ, "PYTHONUTF8": "1"}

        def run(cmd, out):
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=300)
            (art / out).write_text((p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr.strip() else ""), encoding="utf-8")
            return p.returncode, p.stdout
        rc_v, _ = run([sys.executable, str(HERE / "validate_run.py"), "--run", str(run_dir), "--kind", "e2e",
                       "--min-snr", str(a.min_snr)], "validate_stdout.txt")
        rc_g, so_g = run([sys.executable, str(HERE / "gate.py"), "--run", str(run_dir), "--min-snr", str(a.min_snr),
                          "--allow-missing-dom", "--allow-missing-vision"], "gate_stdout.txt")
        gate_line = ("PASS" if rc_g == 0 else "FAIL") + f" (validate rc={rc_v}, gate rc={rc_g}): " + (so_g.strip().splitlines() or [""])[-1][:300]
        log(f"validate_run rc={rc_v}; gate rc={rc_g}: {gate_line}")

    rows = [("engine", a.engine), ("n_clips", a.clips), ("duration_s", round(len(play) / SR, 2)),
            ("snr_db (окна)", round(ws["snr_db"], 2)), ("snr_db_recomputed (p90/p10)", round(snr_re, 2)),
            ("corr_peak (медиана окон)", round(corr_peak, 4)), ("corr_global (справочно)", round(corr_global, 4)),
            ("drift_ppm", drift_ppm), ("valid_window_fraction", round(valid_frac, 3)),
            ("lag_ms (медиана локальных)", round(lag_ms, 1)),
            ("partial_count", len(partials)), ("final_count", len(finals)),
            ("latency p50/p95 мс (n=%d)" % len(lat), f"{pct(lat, 50):.0f} / {pct(lat, 95):.0f}" if lat else "не измерено"),
            ("endpoint_wait p50/p95 мс (n=%d)" % len(epw), f"{pct(epw, 50):.0f} / {pct(epw, 95):.0f}" if epw else "не измерено"),
            ("gate", gate_line), ("run_dir", str(run_dir)), ("recording", str(art / "recording.wav"))]
    table = "\n".join(f"{k:<34} | {v}" for k, v in rows)
    (art / "summary_table.txt").write_text(table + "\n", encoding="utf-8")
    print("\n" + table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
