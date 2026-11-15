# Поиск: streaming speaker attributed ASR end to end online offline diarization latency

Дата: 2026-11-14
Зачем: найти внешний ориентир для метрики проекта

Это источник, не измерение. Числа переносить в `docs/benchmarks.md`
только после проверки цитаты функцией `quote_in_page`.
Подсказки первоисточника — эвристика, не подтверждение первичности или достоверности.

## Найденные ссылки
1. VibeVoice-ASR-Streaming Technical Report - Yujie Tu — https://alextyj.github.io/publication/2026-09-03-vibevoice-asr-streaming
   > VibeVoice-ASR-Streaming is one of the first LLM-based end-to-end approaches to streaming speaker-attributed ASR. By interleaving fixed-size audio chunks, a small amount of lookahead audio, and previous text, it produces “who said what” as speech arrives, with no separate diarization stage.
2. VibeVoice-ASR-Streaming Technical Report - Microsoft Research — https://www.microsoft.com/en-us/research/publication/vibevoice-asr-streaming-technical-report/
   > To tackle this issue, we present VibeVoice-ASR-Streaming, one of the first LLM-based end-to-end approaches to streaming speaker-attributed ASR. It interleaves fixed-size audio chunks, a small amount of lookahead audio and previous text.
3. VibeVoice-ASR-Streaming: Who Spoke What in Real Time — https://openreview.net/forum?id=r6QZahgnJY
   > Meanwhile, streaming LLM-based ASR has mainly focused on single-speaker transcription and generally lacks speaker-attribution capability. To address this gap, we present VibeVoice-ASR-Streaming, an end-to-end framework for streaming speaker-attributed ASR.
4. [2609.02812] VibeVoice-ASR-Streaming Technical Report — https://arxiv.org/abs/2609.02812
   > Traditional speaker-attributed ASR systems treated ASR and speaker diarization as two separate tasks. Recently, end-to-end models such as VibeVoice-ASR have unified the two tasks within a single model. However, existing unified models still mainly support offline recognition, making it difficult to 
5. Streaming Speaker-Attributed ASR for Enterprise Voice AI — https://vector-labs.ai/insights/streaming-speaker-attributed-asr-what-enterprise-voice-ai-teams-need-to-evaluate-before-committing-to-a-production-architecture
   > Traditional speaker-attributed ASR pipelines run ASR and speaker diarization as sequential stages: transcribe first, then assign speakers to transcript segments. This separation is operationally
6. Paper page - VibeVoice-ASR-Streaming Technical Report — https://huggingface.co/papers/2609.02812
   > A streaming, LLM-based end-to-end model unifies speaker-attributed speech recognition and diarization for low-latency real-time applications.
7. Streaming ASR Unifies Transcription and Speaker Attribution — https://www.sotapapers.com/article/2026/09/streaming-asr-unifies-transcription-and-speaker-attribution-2609-02812
   > Recently, end-to-end models such as VibeVoice-ASR have unified the two tasks within a single model. However, existing unified models still mainly support offline recognition, making it difficult to meet the low-latency requirements of real-time voice assistants and agents.
8. VibeVoice-ASR-Streaming Technical Report — https://doi.org/10.48550/arxiv.2609.02812
   > the audio span covered by emitted result $j$ and the time its speaker label settles, $n_{j}$ and $d_{j}$ are its word count and duration, and $d_{j}/2$ is the expected position of a word inside it.
9. VibeVoice-ASR-Streaming Technical Report — https://arxiv.org/html/2609.02812v1
   > For the cloud services we report a measured wall-clock delay:
| | ℓ̄=(∑_jn_j(ℓ_j+d_j/2))/(∑_jn_j), | | (4) |
|---|---|---|---|
where ℓ_j is the delay between the end of the audio span
10. FASTDIAR: Frame-level speaker encoder for Streaming Diarization — https://doi.org/10.48550/arxiv.2610.02941
   > | RAMC |
| --- | --- | --- | --- | --- |
|ReDimNet2-B6-S | 12.3M | 4.85 | 14.79 | 27.97 |
|Small | 2.7M | 0.05 | 16.49 | 31.59 |
|Medium | 4.6M | 0.09 | 14.06 | 24.21 |
|Large (FASTDIAR) |

## Фрагменты страниц

### https://arxiv.org/abs/2609.02812

# Electrical Engineering and Systems Science > Audio and Speech Processing

[Submitted on 2 Sep 2026 (v1), last revised 10 Sep 2026 (this version, v2)]

# Title:VibeVoice-ASR-Streaming Technical Report

View a PDF of the paper titled VibeVoice-ASR-Streaming Technical Report, by Yujie Tu and 13 other authors

View PDF
HTML (experimental)
> Abstract:Traditional speaker-attributed ASR systems treated ASR and speaker diarization as two separate tasks. Recently, end-to-end models such as VibeVoice-ASR have unified the two tasks within a single model. However, existing unified models still mainly support offline recognition, making it difficult to meet the low-latency requirements of real-time voice assistants and agents. To tackle this issue, we present VibeVoice-ASR-Streaming, one of the first LLM-based end-to-end approaches to streaming speaker-attributed ASR. It interleaves fixed-size audio chunks, a small amount of lookahead audio and previous text. This allows the model to produce ''who said what'' as speech arrives, without a separate diarization stage. For transcription accuracy, our 7B model achieves the lowest average WER/CER across five evaluation sets. For speaker attribution, it achieves the best or tied-best on 12 of 13 evaluation settings. We release the 1.5B and 7B model weights together with inference code.

|  |  |
| --- | --- |
| Subjects: | Audio and Speech Processing (eess.AS) |
| Cite as: | arXiv:2609.02812 [eess.AS] |
|  | (or  arXiv:2609.02812v2 [eess.AS] fo

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
