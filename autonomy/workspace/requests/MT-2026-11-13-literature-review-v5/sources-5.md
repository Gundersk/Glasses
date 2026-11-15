# Поиск: WhisperLive pyannote.audio Vosk GigaAM streaming diarization license MIT hardware GPU requirements real-time factor

Дата: 2026-11-14
Зачем: найти внешний ориентир для метрики проекта

Это источник, не измерение. Числа переносить в `docs/benchmarks.md`
только после проверки цитаты функцией `quote_in_page`.
Подсказки первоисточника — эвристика, не подтверждение первичности или достоверности.

## Найденные ссылки
1. collabora/WhisperLive: A nearly-live implementation of ... — https://github.com/collabora/WhisperLive
   > This project is a real-time transcription application that uses the OpenAI Whisper model. Diarization Real-time speaker identification using pyannote.audio. ...
2. WhisperLive/README.md at main · collabora/WhisperLive — https://github.com/collabora/whisper-live/blob/main/README.md
   > using pyannote.audio embeddings (optional dependency):
```
pip install pyannote.audio
```
```
client = TranscriptionClient(
"localhost", 9090,
enable_diarization=True,
max_speakers=4,
)
3. GitHub - collabora/WhisperLive: A nearly-live implementation of OpenAI's Whisper. — https://github.com/collabora/WhisperLive?tab=readme-ov-file
   > using pyannote.audio embeddings (optional dependency):
```
pip install pyannote.audio
```
```
client = TranscriptionClient(
"localhost", 9090,
enable_diarization=True,
max_speakers=4,
)
4. WhisperLive: Near-real-time Whisper transcription server over WebSocket — https://archestack.com/best-of-ai/projects/whisperlive
   > are faster-whisper (CPU, CUDA, ROCm), TensorRT-LLM and OpenVINO; extras include word timestamps, hotwords, pyannote diarization and translation. For teams embedding live captions or dictation.
5. Document all new features in README by boxerab · Pull Request #491 · collabora/WhisperLive — https://github.com/collabora/WhisperLive/pull/491/files
   > #### Speaker Diarization
Real-time speaker identification using pyannote.audio embeddings (optional dependency):
```bash
pip install pyannote.audio
```
```python
client =
6. WhisperLive - Learn AI — https://ai.miraheze.org/wiki/WhisperLive
   > capable of running the selected inference backend. For the Faster-Whisper and TensorRT backends, this typically means an Nvidia GPU with sufficient memory to hold the model weights and process
7. From Batch to Streaming: 12 years building diarization — https://www.pyannote.ai/blog/introducing-live-1-streaming-diarization
   > pyannoteAI launches Streaming Diarization after 12 years of research. Real-time speaker attribution with sub-300ms latency for production voice AI.
8. Why I built my own GPU-Accelerated Audio Transcription ... — https://renan-costaalencar.medium.com/why-i-built-my-own-gpu-accelerated-audio-transcription-system-and-you-should-too-1445109de696
   > The Real Requirements: Time and Patience. Initial setup time: 4–6 hours for first-time installation. Plan for 1–2 hours of version compatibility
9. Speaker Diarization API Comparison 2026: Price & DER — https://www.forasoft.com/blog/article/speaker-diarization-api-comparison
   > Per audio-hour of diarized transcript, managed APIs run from about $0.17 to $0.96 and self-hosted pyannote runs about $0.08–$0.16 in raw GPU.
10. Top 7 Speaker Diarization APIs and Models (2026) — https://pyannote.ai/blog/top-7-speaker-diarization-apis-and-models-in-2026
   > WeSpeaker embeddings, and VBx clustering into one pretrained pipeline, works in any language, and has no ceiling on how many speakers it can track. Its published results give a sense of the

## Фрагменты страниц

### https://github.com/collabora/WhisperLive

BranchesTags

## Repository files navigation

# WhisperLive

## A nearly-live implementation of OpenAI's Whisper.

This project is a real-time transcription application that uses the OpenAI Whisper model
to convert speech input into text output. It can be used to transcribe both live audio
input from microphone and pre-recorded audio files.

## Installation

* Install PortAudio (required system dependency for microphone input via PyAudio)

```
 bash scripts/setup.sh
```

On Debian/Ubuntu this installs `portaudio19-dev`, on Fedora `portaudio-devel`, on macOS it uses Homebrew (`portaudio`).

* Install 3.12 venv (on Fedora `sudo dnf install -y python3.12 python3.12-pip`)

```
python3.12 -m venv whisper_env
source whisper_env/bin/activate
```

* Install whisper-live from pip

```
 pip install whisper-live
```

### OpenAI REST interface

#### Server

```
python3 run_server.py --port 9090 --backend faster_whisper --max_clients 4 --max_connection_time 600 --enable_rest --cors-origins="http://localhost:8080,http://127.0.0.1:8080"
```

#### Client

```
python3 client_openai.py $AUDIO_FILE
```

### Setting up NVIDIA/TensorRT-LLM for TensorRT backend

* Please follow TensorRT\_whisper readme for setup of NVIDIA/TensorRT-LLM and for building Whisper-TensorRT engine.

## Getting Started

The server supports 3 backends `faster_whisper`, `tensorrt` and `openvino`. If running `tensorrt` backend follow TensorRT\_whisper readme

### Running the Server

* Faster Whisper backend

```
python3 run

### https://github.com/collabora/WhisperLive/pull/491/files

# Document all new features in README #491

New issue


**Have a question about this project?** Sign up for a free GitHub account to open an issue and contact its maintainers and the community.

Sign up for GitHub

By clicking “Sign up for GitHub”, you agree to our terms of service and
privacy statement. We’ll occasionally send you account related emails.

Already on GitHub?
Sign in
to your account

Merged

boxerab
merged 1 commit into
collabora:main
from
boxerab:readme-features


May 15, 2026

### Uh oh!

There was an error while loading. Please reload this page.



Merged

Changes from **all commits**



**File filter**

Clear filters

**Conversations**
 


Failed to load comments.

Loading

### Uh oh!

There was an error while loading. Please reload this page.

 **Jump to**
 

Jump to file

Failed to load files.

Loading

### Uh oh!

There was an error while loading. Please reload this page.

 

##### Diff view

##### Diff view



## There are no files selected for viewing

102 changes: 102 additions & 0 deletions

README.md

Show comments
View file

Open in desktop

This file contains hidden or bidirectional Unicode text that may be interpreted or compiled differently than what appears below. To review, open the file in an editor that reveals hidden Unicode characters.
Learn more about bidirectional Unicode characters

Show hidden characters







| Original file line number | Diff line number | Diff line change |
| --- | --- | --- |

| Expand Up | | @@ -17,6 +17,15 @@ i
