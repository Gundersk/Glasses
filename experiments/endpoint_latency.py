# -*- coding: utf-8 -*-
"""Endpointing latency: сколько распознаватель «думает» ПОСЛЕ конца фразы, прежде
чем выдать финальный текст. Это то, что реально добавляется к ожиданию слабослышащего
человека, а не время обработки чанка (его уже даёт asr_benchmark: p50 13 мс).

Метод (честный, измеримый в аудио-времени, не требует real-time pacing):
 1. Собираем paced-клип: 3 русские фразы через 0.8 с тишины + 1.0 с хвост.
    Фиксируем speech_end[i] — момент (сек) конца РЕЧИ i-й фразы (до тишины).
 2. Потоково подаём в Vosk чанками 0.25 с, отслеживаем frames_consumed.
 3. Когда AcceptWaveform вернул финал i-й фразы, endpointing_latency =
    frames_consumed/sr - speech_end[i]  (секунды тишины, сожжённые до решения).
 4. p50/p95 по >=3 финалам. Это нижняя граница «ожидания после конца фразы»
    на нашей машине; сетевой/браузерный транспорт не включён.
"""
import json
import os
import subprocess
import sys
import time

import numpy as np
import soundfile as sf
import vosk

SR = 16000
GAP = 0.8          # тишина между фразами (сек)
TAIL = 1.5         # хвостовая тишина, чтобы последний финал точно вышел
CHUNK = 4000       # кадров на чанк (0.25 с)
MODEL = "models/vosk-model-small-ru-0.22"
OUT = "experiments/benchmarks/endpoint_latency.json"
PACED = "experiments/data/speech_paced.wav"

SENTENCES = [
    "Сегодня мы проверяем систему субтитров для умных очков.",
    "Собеседник говорит про погоду и про встречу в университете.",
    "Задержка распознавания должна быть небольшой чтобы человек успевал читать текст.",
    "Первый говорящий задаёт вопрос о расписании занятий.",
    "Второй собеседник отвечает что лекция начнётся в десять утра.",
    "Затем первый уточняет номер аудитории и этаж корпуса.",
    "В конце они договариваются встретиться у входа в библиотеку.",
    "Такой диалог позволяет проверить качество потокового распознавания русской речи.",
]


def synth(sentence, mp3):
    from gtts import gTTS
    gTTS(text=sentence, lang="ru", tld="com").save(mp3)
    wav = mp3.replace(".mp3", ".wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3,
                    "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", wav], check=True)
    data, sr = sf.read(wav, dtype="float32")
    assert sr == SR
    return data


def build_paced():
    tmp = "experiments/data/_ep_tmp"
    os.makedirs(tmp, exist_ok=True)
    gap = np.zeros(int(GAP * SR), dtype="float32")
    tail = np.zeros(int(TAIL * SR), dtype="float32")
    pieces, speech_end = [], []
    pos = 0.0
    for i, s in enumerate(SENTENCES):
        a = synth(s, os.path.join(tmp, f"s{i}.mp3"))
        pieces.append(a)
        pos += len(a) / SR
        speech_end.append(pos)          # конец речи этой фразы
        pieces.append(gap if i < len(SENTENCES) - 1 else tail)
        pos += len(pieces[-1]) / SR
    audio = np.concatenate(pieces)
    sf.write(PACED, audio, SR, subtype="PCM_16")
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    return speech_end


def measure(speech_end):
    rec_model = vosk.Model(MODEL)
    import wave
    wf = wave.open(PACED, "rb")
    rec = vosk.KaldiRecognizer(rec_model, SR)
    rec.SetWords(True)
    finals = []
    consumed = 0
    idx = 0
    while True:
        data = wf.readframes(CHUNK)
        if not data:
            break
        consumed += len(data) // 2      # int16 -> samples
        if rec.AcceptWaveform(data):
            txt = json.loads(rec.Result()).get("text", "").strip()
            if txt:
                t_final = consumed / SR
                # сопоставляем финал с фразой, чей конец речи ближайший слева
                while idx < len(speech_end) and t_final >= speech_end[idx]:
                    cur_end = speech_end[idx]
                    idx += 1
                lat = max(0.0, t_final - cur_end)
                finals.append({"i": idx - 1, "text": txt,
                               "endpointing_ms": round(lat * 1000, 1)})
    last = json.loads(rec.FinalResult()).get("text", "").strip()
    if last and idx - 1 < len(speech_end):
        t_final = consumed / SR
        finals.append({"i": idx, "text": last,
                       "endpointing_ms": round(max(0.0, t_final - speech_end[idx]) * 1000, 1)})
    wf.close()
    return finals


def pct(vals, p):
    if not vals:
        return None
    v = sorted(vals)
    k = (len(v) - 1) * p
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def main():
    t0 = time.time()
    speech_end = build_paced()
    finals = measure(speech_end)
    lat = [f["endpointing_ms"] for f in finals]
    out = {
        "method": ("Endpointing latency: audio-seconds of silence consumed between "
                   "end-of-speech and Vosk emitting the final segment. Lower bound on "
                   "the wait a user perceives AFTER finishing a sentence. Excludes "
                   "chunk compute time (see asr_benchmark p50=13ms) and network/browser "
                   "transport. Synthetic TTS speech, not live."),
        "n_finals": len(finals),
        "p50_ms": round(pct(lat, 0.5), 1) if lat else None,
        "p95_ms": round(pct(lat, 0.95), 1) if lat else None,
        "finals": finals,
        "speech_end_times_s": [round(x, 3) for x in speech_end],
        "gap_s": GAP, "chunk_frames": CHUNK,
        "audio": PACED, "model": MODEL, "sample_rate": SR,
        "wallclock_s": round(time.time() - t0, 2),
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: out[k] for k in
                      ("n_finals", "p50_ms", "p95_ms", "method")}, ensure_ascii=False))
    return 0 if out["n_finals"] >= 3 else 1


if __name__ == "__main__":
    sys.exit(main())
