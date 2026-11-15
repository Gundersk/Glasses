# Поиск: WhisperX pyannote.audio NeMo streaming speaker diarization license hardware requirements GPU

Дата: 2026-11-14
Зачем: найти внешний ориентир для метрики проекта

Это источник, не измерение. Числа переносить в `docs/benchmarks.md`
только после проверки цитаты функцией `quote_in_page`.
Подсказки первоисточника — эвристика, не подтверждение первичности или достоверности.

## Найденные ссылки
1. whisperX/README.md at main · m-bain/whisperX — https://github.com/m-bain/WhisperX/blob/main/README.md
   > **Speaker Diarization** is the process of partitioning an audio stream containing human speech into homogeneous segments according to the identity of each speaker.
2. whisperX/README.md at main · SesameAILabs/whisperX — https://github.com/SesameAILabs/whisperX/blob/main/README.md
   > GPU execution requires the NVIDIA libraries cuBLAS 11.x and cuDNN 8.x to be installed on the system. Please refer to the [CTranslate2 documentation](https://opennmt.net/CTranslate2/installation.html).
3. GitHub - a180285/whisperX: WhisperX: Automatic Speech Recognition with Word-level Timestamps (& Diarization) — https://github.com/a180285/whisperX
   > **Speaker Diarization** is the process of partitioning an audio stream containing human speech into homogeneous segments according to the identity of each speaker.
4. whisperx-asr-service/README.md at main · murtaza-nasir/whisperx-asr-service — https://github.com/murtaza-nasir/whisperx-asr-service/blob/main/README.md
   > A simple ASR API service powered by WhisperX for transcription with speaker diarization. Built for self-hosters running [Speakr](https://github.com/murtaza-nasir/speakr) or similar applications.
5. GitHub - m-bain/whisperX: WhisperX: Automatic Speech Recognition with Word-level Timestamps (& Diarization) — https://github.com/m-bain/whisperX?tab=readme-ov-file
   > ```
To run on CPU instead of GPU (and for running on Mac OS X):
```
whisperx path/to/audio.wav --compute_type int8 --device cpu
```
6. Looking for diarization model better than Pyannote — https://www.reddit.com/r/LocalLLaMA/comments/1m48v53/looking_for_diarization_model_better_than_pyannote/
   > I tested this last week: WhisperX with pyannote against NVIDIA's Nemotron-3-Diarization, on seven scripted two-person recordings in English.
7. GitHub - AndrewPaglusch/whisperx-asr-service — https://github.com/AndrewPaglusch/whisperx-asr-service
   > | Suitable GPUs |
|---|---|---|
| tiny, base | ~4-5GB | RTX 3060 8GB, RTX 2060, GTX 1660 Ti |
| small | ~6GB | RTX 3060, RTX 2070, RTX 2080 |
| medium | ~10GB | RTX 3080, RTX 3060 12GB, RTX
8. GitHub - manuel-llop/whisperx: WhisperX: Automatic Speech Recognition with Word-level Timestamps (& Diarization) — https://github.com/manuel-llop/whisperx
   > **Speaker Diarization** is the process of partitioning an audio stream containing human speech into homogeneous segments according to the identity of each speaker.
9. Pyannote is 10 times slower than WhisperX with GPU ... — https://github.com/pyannote/pyannote-audio/issues/1652
   > It uses the GPU during diarization, but with a low utilization. When doing the diarization with whisperx , though, it takes just a minute, and ...
10. NeMo Open Source Speaker Diarization System — https://www.isca-archive.org/interspeech_2022/park22e_interspeech.pdf
   > by TJ Park · 2022 · Cited by 6 — The speaker diarization system consists of a VAD model based on MarbleNet [2] that generates times- tamps of the input audio stream where speech-active regions.

## Фрагменты страниц

### https://github.com/pyannote/pyannote-audio/issues/1652

# Pyannote is 10 times slower than WhisperX with GPU utilization 10%: expected behavior or misconfiguration? #1652

New issue

New issue

Closed

Labels

cannot\_reproducewontfix

## Description

chubin

opened on Feb 19, 2024

### Tested versions

```
pyannote.audio==3.1.1
pyannote.core==5.0.0
pyannote.database==5.0.1
pyannote.metrics==3.2.1
pyannote.pipeline==3.0.1
```

### System information

Ubuntu 22.04, NVIDIA RTX A6000

### Issue description

I am not sure if it is a bug, so please feel free to close it if it is expected behavior.

I am trying to diarize a large recording (approximately 60 minutes), and the  
diarization process takes 8.5 minutes:

```
real    8m40,982s
user    8m12,687s
sys     1m21,703s
```

Here is my code:

```
import torch
from pyannote.audio import Pipeline

pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1", use_auth_token=hf_token
    )

pipeline.to(torch.device("cuda"))

diarization = pipeline("audio.wav")
```

It uses the GPU during diarization, but with a low utilization level (~10%),  
and it uses 1 core of the CPU (100%) all the time.

When doing the diarization with `whisperx`, though, it takes just a minute,  
and GPU utilization is at full capacity.

However, the quality of diarization is slightly worse in this case (approximately 5% of text  
is attributed to wrong/non-existent speakers).

```
           duration   GPU-usage
pyannote   520.5s     10%
whisperx    75.0s     100%
```

Pyannote diarization quality 

### https://www.isca-archive.org/interspeech_2022/park22e_interspeech.pdf

NeMo Open Source Speaker Diarization System
Tae Jin Park, Nithin Rao Koluguri, Fei Jia, Jagadeesh Balam and Boris Ginsburg
NVIDIA
{taejinp, nkoluguri, fjia, jbalam, bginsburg }@nvidia.com
Abstract
We introduce an open-source speaker diarization system which
is part of the NeMo conversational AI toolkit. During the Show
and Tell session, we will present an interactive system which
demonstrates both online and offline speaker diarization. The
audience would be able to test the speaker diarization system
by recording their voice. We believe that our demo session
would be an excellent opportunity to learn and experience how
a speaker diarization system can be implemented for real-life
applications using an open source toolkit.
Index Terms: Speaker diarization, NeMo Toolkit, Automatic
Speech Recognition
1. Introduction
In recent years, a rapid technological progress in automatic
speech recognition (ASR) and natural language processing
(NLP) has been made owing to the improvements in machine
learning models, increased computational resources and avail-
able public datasets. When it comes to conversational AI, every
component in the pipeline from ASR modules to natural lan-
guage understanding (NLU) should perform seamlessly to un-
derstand or react to the free-form speech input. In a speech
understanding system, the basic components include voice ac-
tivity detection (V AD), speaker diarization, core ASR module,
inverse text-normalization and punctuation module. Especially,
when it
