# Поиск: Russian streaming speech recognition models datasets benchmarks primary publication

Дата: 2026-11-14
Зачем: найти внешний ориентир для метрики проекта

Это источник, не измерение. Числа переносить в `docs/benchmarks.md`
только после проверки цитаты функцией `quote_in_page`.
Подсказки первоисточника — эвристика, не подтверждение первичности или достоверности.

## Найденные ссылки
1. nur-dev/realtime-streaming-asr-kk-ru-en · Hugging Face — https://huggingface.co/nur-dev/realtime-streaming-asr-kk-ru-en
   > 16.39 | 12.89 | **15.08** | ~0.015 |
| Streaming `[70,6]` | ~480 ms | 14.34 | 16.20 | 17.34 | 13.75 | 15.96 | ~0.016 |
| Streaming `[70,1]` | ~80 ms | 15.89 | 18.73 | 20.03 | 15.71 | 18.22 | ~0.037 |
2. t-tech/T-one · Hugging Face — https://huggingface.co/t-tech/T-one
   > | 17.65 | 17.87 |
| CommonVoice 19 (test split) | 5.32 | **2.68** | 3.14 | 6.22 | 11.3 | 5.78 |
| OpenSTT asr_calls_2_val original | 20.27 | **20.07** | 21.24 | 22.64 | 29.45 | 29.02 |
| OpenSTT
3. huggingface.co/t-tech/T-one/raw/main/README.md — https://huggingface.co/t-tech/T-one/raw/main/README.md
   > **🚀 T-one is a high-performance streaming ASR pipeline for Russian, specialized for the telephony domain.**
4. 1Introduction — https://arxiv.org/html/2601.20992v1
   > In our experiments, we use a human-labeled Sova-RuDevices (Zubarev & Moskalets, 2019) Russian dataset, originally crowdsourced from voice messages,
5. Balalaika: Data-Centric, Prosody-Aware Annotation ... — https://arxiv.org/pdf/2507.13563
   > by K Borodin · 2025 · Cited by 4 — Our annotation framework produces higher-quality Russian speech datasets than existing methods in perceptual quality and text–audio consistency,
6. README.md · t-tech/T-one at main — https://huggingface.co/t-tech/T-one/blob/main/README.md
   > hours of Russian speech. A significant portion (up to 64%) was pseudo-labeled using a robust ROVER model ensemble.
| Domain | Hours | Source |
|---|---|---|
| Telephony | 57.9k | internal |
|
7. GigaAM: Efficient Self-Supervised Learner for Speech Recognition — https://arxiv.org/html/2506.01192v1
   > Russian MCV-19 | Russian LibriSpeech |
|---|---|---|---|
| XLS-R [14] finetuned | 15.7 | 8.0 | 16.1 |
| Whisper-large-v3 | 16.6 | 5.5 | 9.5 |
| FastConformer-RNNT | 6.6 | 5.7 | 11.3 |
| Ours (CTC) |
8. asr_eval: Algorithms and tools for multi-reference and streaming speech recognition evaluation — https://arcxiv.org/abs/2601.20992
   > word formation, to label cluttered or longform speech. Secondly, we collect a novel test set DiverseSpeech-Ru of longform in-the-wild Russian speech with careful multi-reference labeling. We also
9. Russian Speech Recognition Dataset - 338 Hours — https://www.kaggle.com/datasets/unidpro/russian-speech-recognition-dataset/data
   > Dataset comprises 338 hours of telephone dialogues in Russian, collected from 460 native speakers across various topics and domains, with an impressive 98% Word ...
10. Speech-to-text benchmark - Picovoice — https://github.com/Picovoice/speech-to-text-benchmark
   > This repo is a minimalist and extensible framework for benchmarking different speech-to-text engines.

## Фрагменты страниц

### https://arcxiv.org/abs/2601.20992

# asreval: Algorithms and tools for multi-reference and streaming speech recognition evaluation

Oleg Sedukhin, Andrey Kostin

## Abstract

We propose several improvements to the speech recognition evaluation. First, we propose a string alignment algorithm that supports both multi-reference labeling, arbitrary-length insertions and better word alignment. This is especially useful for non-Latin languages, those with rich word formation, to label cluttered or longform speech. Secondly, we collect a novel test set DiverseSpeech-Ru of longform in-the-wild Russian speech with careful multi-reference labeling. We also perform multi-reference relabeling of popular Russian tests set and study fine-tuning dynamics on its corresponding train set. We demonstrate that the model often adopts to dataset-specific labeling, causing an illusion of metric improvement. Based on the improved word alignment, we develop tools to evaluate streaming speech recognition and to align multiple transcriptions to compare them visually. Additionally, we provide uniform wrappers for many offline and streaming speech recognition models. Our code will be made publicly available.

## Create a lesson

## Related papers

* ArchSpace: Recording, Reviewing, and Referencing LLM Architecture Research

  Jie Wang, Tong Zhu, JiaHao Kuang et al.
* Learning When Diffusion Language Models Should Regenerate

  Minhae Oh, Jeonghye Kim, Jinwoo Koo et al.
* Goal Encoding in LLMs

  Arnab Sen Sharma, Eric Todd, Sheridan Feuch

### https://www.kaggle.com/datasets/unidpro/russian-speech-recognition-dataset/data

Kaggle uses cookies from Google to deliver and enhance the quality of its services and to analyze traffic.

Learn more

OK, Got it.

###### Something went wrong and this page crashed!

If the issue persists, it's likely a problem on our side.

```
Loading CSS chunk 7815 failed.\n(https://www.kaggle.com/static/assets/7815.e94de944d22d175f.css)

Error: Loading CSS chunk 7815 failed.\n(https://www.kaggle.com/static/assets/7815.e94de944d22d175f.css)
    at n.onerror.n.onload (https://www.kaggle.com/static/assets/runtime.js?v=826e134bc4dfe45c:1:13161)
```
