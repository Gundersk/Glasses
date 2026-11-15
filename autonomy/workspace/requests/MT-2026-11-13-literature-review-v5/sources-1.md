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
3. Daily Papers — https://huggingface.co/papers?q=ASR%20evaluation
   > To tackle this issue, we present VibeVoice-ASR-Streaming, one of the first LLM-based end-to-end approaches to streaming speaker-attributed ASR. It interleaves ...
4. Qwen-Audio-3.1-ASR Technical Report — https://arxiv.org/html/2610.28711v1
   > under the
5. (PDF) VIBEVOICE-ASR Technical Report — https://www.researchgate.net/publication/400084025_VIBEVOICE-ASR_Technical_Report
   > [Show full abstract] we present VibeVoice-ASR-Streaming, one of the first LLM-based end-to-end approaches to streaming speaker-attributed ASR.
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
9. How to measure transcription accuracy and evaluate ... — https://www.assemblyai.com/blog/how-to-evaluate-speech-recognition-models
   > The core ASR evaluation metrics are word error rate (WER), semantic WER, missed entity rate (MER), character error rate (CER), and cpWER for ...
10. Evaluating ASR Systems, Part 2: Accuracy and Robustness — https://keenresearch.com/blog/evaluation/evaluating-asr-systems-part-2-accuracy-robustness.html
   > In ASR research, the standard metric for accuracy is Word Error Rate (WER). native-speaker recordings might fail dramatically on children's ...

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

### https://huggingface.co/papers?q=ASR%20evaluation

Get trending papers in your email inbox once a day!

Get trending papers in your email inbox!

Subscribe

### What is lost in Normalization? Exploring Pitfalls in Multilingual ASR Model Evaluations

This paper explores the pitfalls in evaluating multilingual automatic speech recognition (ASR) models, with a particular focus on Indic language scripts. We investigate the text normalization routine employed by leading ASR models, including OpenAI Whisper, Meta's MMS, Seamless, and Assembly AI's Conformer, and their unintended consequences on performance metrics. Our research reveals that current text normalization practices, while aiming to standardize ASR outputs for fair comparison, by removing inconsistencies such as variations in spelling, punctuation, and special characters, are fundamentally flawed when applied to Indic scripts. Through empirical analysis using text similarity scores and in-depth linguistic examination, we demonstrate that these flaws lead to artificially improved performance metrics for Indic languages. We conclude by proposing a shift towards developing text normalization routines that leverage native linguistic expertise, ensuring more robust and accurate evaluations of multilingual ASR models.

### Towards Orthographically-Informed Evaluation of Speech Recognition Systems for Indian Languages

Evaluating ASR systems for Indian languages is challenging due to spelling variations, suffix splitting flexibility, and non-standard spellings in code-mixed wor
