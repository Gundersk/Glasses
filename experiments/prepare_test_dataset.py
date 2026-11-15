import json, math, os, struct, sys, wave

AUDIO = "experiments/data/test_16k.wav"
REF = "experiments/data/test_ref.json"
SR = 16000
DURATION = 2.0
SEED = 0

def main():
    try:
        os.makedirs(os.path.dirname(AUDIO), exist_ok=True)
        nframes = int(SR * DURATION)
        amp = int(0.3 * 32767)
        with wave.open(AUDIO, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            frames = bytearray()
            for i in range(nframes):
                sample = int(amp * math.sin(2 * math.pi * 440.0 * i / SR))
                frames.extend(struct.pack("<h", sample))
            wf.writeframes(bytes(frames))
        ref = {
            "reference_text": "привет мир это тестовый аудиофайл для бенчмарка распознавания речи",
            "audio": AUDIO,
            "sample_rate": SR,
            "duration_sec": DURATION,
            "seed": SEED,
        }
        with open(REF, "w", encoding="utf-8") as f:
            json.dump(ref, f, ensure_ascii=False, indent=2)
        print(json.dumps({"ok": True, "audio": AUDIO, "ref": REF, "sample_rate": SR, "frames": nframes}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)

if __name__ == "__main__":
    main()
