# -*- coding: utf-8 -*-
"""Подготовка РЕАЛЬНОГО тестового аудио с известным эталоном.
Голос = TTS (edge-tts нейронный, фолбэк gTTS). Текст фиксирован => ref честный.
Выход: experiments/data/speech_ru.wav (16k mono) + speech_ru.txt (ровно произнесённый текст).
"""
import os
import subprocess
import sys

DATA = "experiments/data"
TXT = os.path.join(DATA, "speech_ru.txt")
MP3 = os.path.join(DATA, "speech_ru_tts.mp3")
WAV = os.path.join(DATA, "speech_ru.wav")

TEXT = ("Сегодня мы проверяем систему субтитров для умных очков. "
        "Собеседник говорит про погоду и про встречу в университете. "
        "Задержка распознавания должна быть небольшой, чтобы человек успевал читать текст.")


def get_audio():
    # 1) edge-tts (нейрософт, ru-RU-DmitryNeural)
    try:
        import asyncio
        import edge_tts
        async def go():
            await edge_tts.Communicate(TEXT, "ru-RU-DmitryNeural").save(MP3)
        asyncio.run(go())
        if os.path.getsize(MP3) > 1000:
            return "edge-tts"
    except Exception as e:
        print("edge-tts failed:", str(e)[:120])
    # 2) gTTS (Google)
    try:
        from gtts import gTTS
        gTTS(text=TEXT, lang="ru", tld="com").save(MP3)
        if os.path.getsize(MP3) > 1000:
            return "gtts"
    except Exception as e:
        print("gtts failed:", str(e)[:120])
    return None


def main():
    os.makedirs(DATA, exist_ok=True)
    with open(TXT, "w", encoding="utf-8") as f:
        f.write(TEXT)
    src = get_audio()
    if not src:
        print(json_line({"ok": False, "error": "no TTS engine produced audio"}))
        return 1
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", MP3,
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", WAV], check=True)
    import wave
    w = wave.open(WAV)
    dur = w.getnframes() / w.getframerate()
    info = {"ok": True, "engine": src, "wav": WAV, "sr": w.getframerate(),
            "channels": w.getnchannels(), "duration_s": round(dur, 2),
            "text": TEXT}
    w.close()
    json_line(info)
    return 0


def json_line(d):
    import json
    print(json.dumps(d, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
