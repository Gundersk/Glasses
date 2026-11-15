import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "experiments" / "data"
TMP_DIR = DATA_DIR / "tmp"
OUT_WAV = DATA_DIR / "two_speaker.wav"
OUT_REF = DATA_DIR / "two_speaker_ref.json"

TEXT_A = "Привет, это первый говорящий."
TEXT_B = "Второй голос говорит другую фразу."


def run(cmd):
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def ffprobe_duration(path):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    out = run(cmd).stdout.decode().strip()
    return float(out)


def make_mp3(text, mp3_path):
    try:
        from gtts import gTTS
    except ImportError as exc:
        raise RuntimeError("gTTS is not installed. Run: uv pip install --python .venv\\Scripts\\python.exe gTTS") from exc
    tts = gTTS(text=text, lang="ru")
    tts.save(str(mp3_path))


def convert_to_wav(mp3_path, wav_path):
    run([
        "ffmpeg", "-y", "-i", str(mp3_path),
        "-ac", "1", "-ar", "16000", str(wav_path),
    ])


def pitch_shift_wav(in_wav, out_wav):
    run([
        "ffmpeg", "-y", "-i", str(in_wav),
        "-af", "asetrate=16000*1.25,aresample=16000",
        "-ac", "1", "-ar", "16000", str(out_wav),
    ])


def concat_wav(parts, out_wav):
    inputs = []
    for p in parts:
        inputs.extend(["-i", str(p)])
    filter_complex = "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]"
    run([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ac", "1", "-ar", "16000", str(out_wav),
    ])


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    a_mp3 = TMP_DIR / "speaker_a.mp3"
    b_mp3 = TMP_DIR / "speaker_b.mp3"
    a_wav = TMP_DIR / "speaker_a.wav"
    b_orig_wav = TMP_DIR / "speaker_b_orig.wav"
    b_wav = TMP_DIR / "speaker_b.wav"

    make_mp3(TEXT_A, a_mp3)
    make_mp3(TEXT_B, b_mp3)

    convert_to_wav(a_mp3, a_wav)
    convert_to_wav(b_mp3, b_orig_wav)
    pitch_shift_wav(b_orig_wav, b_wav)

    concat_wav([a_wav, b_wav, a_wav], OUT_WAV)

    dur_a = ffprobe_duration(a_wav)
    dur_b = ffprobe_duration(b_wav)
    total = ffprobe_duration(OUT_WAV)

    segments = [
        {"speaker": "A", "start": 0.0, "end": dur_a, "text": TEXT_A},
        {"speaker": "B", "start": dur_a, "end": dur_a + dur_b, "text": TEXT_B},
        {"speaker": "A", "start": dur_a + dur_b, "end": total, "text": TEXT_A},
    ]

    ref = {
        "synthetic": True,
        "num_speakers": 2,
        "num_segments": 3,
        "segments": segments,
    }

    OUT_REF.write_text(json.dumps(ref, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"Command failed: {exc.cmd}\n")
        sys.stderr.write(exc.stderr.decode() if exc.stderr else "")
        sys.exit(1)
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(1)
