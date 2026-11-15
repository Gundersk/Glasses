# Поиск: Russian streaming ASR speaker attributed WER cpWER DER latency evaluation protocol datasets

Дата: 2026-11-14
Зачем: найти внешний ориентир для метрики проекта

Это источник, не измерение. Числа переносить в `docs/benchmarks.md`
только после проверки цитаты функцией `quote_in_page`.
Подсказки первоисточника — эвристика, не подтверждение первичности или достоверности.

## Найденные ссылки
1. VibeVoice-ASR-Streaming Technical Report — https://arxiv.org/html/2609.02812v1
   > | 22.76 | 28.70 | +2.89 | +6.67 |
| AliMeeting | Chinese | 32.15 | 34.12 | 33.83 | 39.80 | +1.68 | +5.68 |
| AMI-IHM | English | 19.08 | 20.98 | 19.83 | 27.48 | +0.75 | +6.50 |
| AMI-SDM | English
2. Streaming evaluation — asr_eval 0.4.0 documentation — https://sibnn.github.io/asr_eval/guide_streaming_evaluation.html
   > Streaming speech recognition system can be evaluated by a variety of parameters:
1. Final WER/CER.
2. Latency induced by calculations.
3. Latency induced by accumulating context, where the model
3. Paper page - VibeVoice-ASR-Streaming Technical Report — https://huggingface.co/papers/2609.02812
   > diarization stage. For transcription accuracy, our 7B model achieves the lowest average [WER/CER](/papers?q=WER%2FCER) across five evaluation sets. For speaker attribution, it achieves the best
4. evaluation and adaptation of open-source models for speaker ... — https://dspace.vut.cz/bitstreams/8860ec91-65c1-45bc-9d10-13ab89a83a6a/download
   > LibriMix [13] is an open-source dataset designed specifically for speech separation and multi-speaker ASR evaluation in controlled environments.
5. Qwen-Audio-3.1-ASR Technical Report — https://arxiv.org/html/2610.28711v1
   > under the
6. asr_eval: Algorithms and tools for multi-reference and streaming speech recognition evaluation — https://arxiv.org/pdf/2601.20992
   > as a source (a "YODAS2"
version with full audios) and use correction based on
multiple alignments, as described in Section 5.1.
2. A multi-reference re-annotation of 500 samples from
Sova-RuDevices
7. mlx-community/VibeVoice-ASR-Streaming-7B-bf16 · Hugging Face — https://huggingface.co/mlx-community/VibeVoice-ASR-Streaming-7B-bf16
   > |
|---|---|---|---|---|---|---|
| PyTorch reference | 31.76 % | 21.25 % | 15 / 16 | — | — | 0.696 |
| MLX bf16 | 31.68 % | 21.17 % | 15 / 16 | 16.66 GB | 21.45 GB | 0.916 |
| **MLX 4-bit** | **31.95
8. mlx-community/VibeVoice-ASR-Streaming-7B-4bit · Hugging Face — https://huggingface.co/mlx-community/VibeVoice-ASR-Streaming-7B-4bit?library=mlx
   > |
|---|---|---|---|---|---|---|
| PyTorch reference | 31.76 % | 21.25 % | 15 / 16 | — | — | 0.696 |
| MLX bf16 | 31.68 % | 21.17 % | 15 / 16 | 16.66 GB | 21.45 GB | 0.916 |
| **MLX 4-bit** |
9. Building Accurate Low Latency ASR for Streaming Voice ... — https://aclanthology.org/2023.acl-industry.26.pdf
   > by A Goyal · 2023 · Cited by 3 — Our model achieves a word error rate (WER) of 3.69% without EOS and 4.78% with EOS while also reducing the search latency by approximately ∼ ...
10. huggingface.co/mlx-community/VibeVoice-ASR-Streaming-7B-4bit/raw/main/README.md — https://huggingface.co/mlx-community/VibeVoice-ASR-Streaming-7B-4bit/raw/main/README.md
   > |
|---|---|---|---|---|---|---|
| PyTorch reference | 31.76 % | 21.25 % | 15 / 16 | — | — | 0.696 |
| MLX bf16 | 31.68 % | 21.17 % | 15 / 16 | 16.66 GB | 21.45 GB | 0.916 |
| **MLX 4-bit** | **31.95

## Фрагменты страниц

### https://sibnn.github.io/asr_eval/guide_streaming_evaluation.html

# Streaming evaluation¶

Streaming speech recognition system can be evaluated by a variety of parameters:

1. Final WER/CER.
2. Latency induced by calculations.
3. Latency induced by accumulating context, where the model refuses to emit a word until accumulates enough audio frames, even with infinite compute speed.
4. The dependency between average WER and time delta, if the system is able to correct previous transcription as more audio context comes.
5. Distributions, spikes and edge cases of the parameters described above.

In view of the diversity of all the streaming characteristics, we believe that diagramming is a good way to analyze a streaming system.

## StreamingASR interface¶

First, to unify evaluation,
we define a general input-output interface: the system accepts audio chunks labeled
by recording ID via input buffer, and emits strings labeled by recording ID and part
ID. When a new string is emitted, if the part ID matches that for one of the previous
parts, it replaces that part, otherwise the new string appended to the end of the
text. This allows a system to correct previously emitted words or sentences, if needed.
For the described interface, we develop a wrapper

```
StreamingASR
```

with input and output buffers, which
makes it easy to wrap any streaming ASR into our interface.

## Time remapping¶

To simulate real-time CPU/GPU loading (and thus a realistic latency) we need to send audio in real time. However, this leads to time spans when both the sender

### https://huggingface.co/papers/2609.02812

Papers

arxiv:2609.02812

# VibeVoice-ASR-Streaming Technical Report

Published on Sep 2

·  Submitted by  zhiliang  on Sep 3

 

·  Microsoft

Upvote

16

Authors: 

,

,

,

Li Dong  ,

,

,

,

,

,

,

,

,

## Abstract

A streaming, LLM-based end-to-end model unifies speaker-attributed speech recognition and diarization for low-latency real-time applications.

Generated by thinkingmachines/Inkling-Small

Traditional speaker-attributed ASR systems treated ASR and speaker diarization as two separate tasks. Recently, end-to-end models such as VibeVoice-ASR have unified the two tasks within a single model. However, existing unified models still mainly support offline recognition, making it difficult to meet the low-latency requirements of real-time voice assistants and agents. To tackle this issue, we present VibeVoice-ASR-Streaming, one of the first LLM-based end-to-end approaches to streaming speaker-attributed ASR. It interleaves fixed-size audio chunks, a small amount of lookahead audio and previous text. This allows the model to produce ''who said what'' as speech arrives, without a separate diarization stage. For transcription accuracy, our 7B model achieves the lowest average WER/CER across five evaluation sets. For speaker attribution, it achieves the best or tied-best on 12 of 13 evaluation settings. We release the 1.5B and 7B model weights together with inference code.

View arXiv page View PDF     Add to collection

    

### Community

zzliang

   Paper submitter
