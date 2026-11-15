# Поиск: streaming ASR diarization tools official documentation hardware requirements code model weights data licenses

Дата: 2026-11-14
Зачем: найти внешний ориентир для метрики проекта

Это источник, не измерение. Числа переносить в `docs/benchmarks.md`
только после проверки цитаты функцией `quote_in_page`.
Подсказки первоисточника — эвристика, не подтверждение первичности или достоверности.

## Найденные ссылки
1. Build Real-Time, Multi-Speaker AI with NVIDIA Nemotron 3 ... — https://huggingface.co/blog/nvidia/nemotron-diarization
   > Below we will show a few quick start guides on how to combine diarization with ASR models, streaming ASR, diarization only and offline ASR with ...
2. Top 8 speaker diarization libraries and APIs in 2026 — https://www.assemblyai.com/blog/top-speaker-diarization-libraries-and-apis
   > Compare the 8 best speaker diarization APIs and open-source libraries on DER, cpWER, streaming support and price, with Nov 2026 benchmarks.
3. streaming-self-hosting-stack/README.md at main · AssemblyAI/streaming-self-hosting-stack — https://github.com/AssemblyAI/streaming-self-hosting-stack/blob/main/README.md
   > |
| **Diarization** | [`diarization/`](/AssemblyAI/streaming-self-hosting-stack/blob/main/diarization) | Synchronous HTTP, full-file | Speaker diarization | NVIDIA T4 or newer, 16 GB+ VRAM |
4. What Is NVIDIA Nemotron 3.5 ASR? The Streaming ... — https://www.mindstudio.ai/blog/what-is-nvidia-nemotron-3-5-asr
   > NVIDIA Nemotron 3.5 ASR is a 600M streaming model supporting 40 languages with cache-aware architecture. Learn how it works and when to use ...
5. ASR_INTEGRATION_GUIDE.md · nvidia/Nemotron-3-Diarization at main — https://huggingface.co/nvidia/Nemotron-3-Diarization/blob/main/ASR_INTEGRATION_GUIDE.md
   > - **A model cannot be downloaded:** Accept any required model terms and verify that `HF_TOKEN` can read both repositories.
6. GitHub - AssemblyAI/streaming-self-hosting-stack: AssemblyAI streaming self-hosting resources and examples. — https://github.com/AssemblyAI/streaming-self-hosting-stack
   > |
| **Diarization** | [`diarization/`](/AssemblyAI/streaming-self-hosting-stack/blob/main/diarization) | Synchronous HTTP, full-file | Speaker diarization | NVIDIA T4 or newer, 16 GB+ VRAM |
7. diarist/docs/04-model-guide.md at main · ebt55/diarist — https://github.com/ebt55/diarist/blob/main/docs/04-model-guide.md
   > or mixed meetings: 40+ locales with automatic detection, 30 percent less VRAM | 742 MB | OpenMDW-1.1 |
| Parakeet TDT 0.6B v3, q8_0 | Experimental only, off by default: better punctuation but drops
8. ASR_INTEGRATION_GUIDE.md · nvidia/Nemotron-3-Diarization at 5c7c103 — https://huggingface.co/nvidia/Nemotron-3-Diarization/blob/5c7c10355591fa1762ae0d30491cd39b19376b3b/ASR_INTEGRATION_GUIDE.md
   > - **A model cannot be downloaded:** Accept any required model terms and verify that `HF_TOKEN` can read both repositories.
9. Nemotron 3 Diarization API - Demo — https://deepinfra.com/nvidia/Nemotron-3-Diarization
   > Nemotron 3 Diarization is an open-weight streaming Sortformer model, engineered for low-latency speaker diarization across up to 8 speakers, ...
10. Speaker Diarization — NVIDIA NeMo Framework User Guide — https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/speaker_diarization/intro.html
   > Speaker diarization is the process of segmenting audio recordings by speaker labels and aims to answer the question “who spoke when?”.

## Фрагменты страниц

### https://huggingface.co/blog/nvidia/nemotron-diarization

Back to Articles

# **Know Who Spoke When: Build Real-Time, Multi-Speaker AI with NVIDIA Nemotron 3 Diarization**

Community Article

Published
September 23, 2026

Upvote

73

 

## *Turn overlapping conversations into speaker-aware data with one open-weight, 100M-parameter model - ranked #1 in VoiceArena's Diarization leaderboard with a 14.72% Diarization Error Rate (DER).*

### **Why speaker diarization matters**

Every conversation carries two layers of information: *what was said* and *who said it*. Speech recognition captures and transcribes the words. Speaker diarization classifies **who spoke when**, helping applications connect what was said to the right participant.

Consider a transcript from a meeting, customer call, or podcast in which every sentence is correct but none is attributed to a speaker. You can read the words, but you cannot reliably tell who made a commitment, who raised an objection, or which participant interrupted. Search, summaries, action items, conversation analytics, and voice-agent memory all become less useful.

Speaker diarization identifies the time intervals during which each speaker is active, including intervals where people talk over one another. Those speaker timestamps can then be combined with automatic speech recognition (ASR) to create a speaker-attributed transcript.

NVIDIA Nemotron 3 Diarization is an open-weight, 100M-parameter model that ranks #1 on VoiceArena's Diarization-Bench leaderboard with a 14.72% Diarization Error Rate

### https://www.mindstudio.ai/blog/what-is-nvidia-nemotron-3-5-asr

# What Is NVIDIA Nemotron 3.5 ASR? The Streaming Speech-to-Text Model Explained

NVIDIA Nemotron 3.5 ASR is a 600M streaming model supporting 40 languages with cache-aware architecture. Learn how it works and when to use it.

## A New Generation of Real-Time Transcription

Speech recognition has been around for decades, but getting it right in real-world conditions — multiple languages, low latency, production reliability — has always been harder than it looks. NVIDIA Nemotron 3.5 ASR is a 600M parameter streaming automatic speech recognition model that attempts to solve all three problems at once.

If you’re building voice-enabled AI applications, call center automation, live captioning tools, or multilingual transcription workflows, this model deserves a close look. This article explains what NVIDIA Nemotron 3.5 ASR is, how its cache-aware streaming architecture works, what makes it different from other ASR models, and how to evaluate whether it fits your use case.

## What NVIDIA Nemotron 3.5 ASR Actually Is

NVIDIA Nemotron 3.5 ASR is an automatic speech recognition model released by NVIDIA as part of their NeMo framework ecosystem. It’s designed to convert spoken audio into text — both in real-time streaming mode and in standard offline batch processing.

The “3.5” refers to its generation within the Nemotron model family, and “ASR” stands for Automatic Speech Recognition. With 600 million parameters, it sits in a middle tier: large enough to handle nuanced speech patter
