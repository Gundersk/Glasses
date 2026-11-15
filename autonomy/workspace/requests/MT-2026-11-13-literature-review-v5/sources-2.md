# Поиск: streaming speaker attributed ASR end to end online diarization latency

Дата: 2026-11-14
Зачем: найти внешний ориентир для метрики проекта

Это источник, не измерение. Числа переносить в `docs/benchmarks.md`
только после проверки цитаты функцией `quote_in_page`.
Подсказки первоисточника — эвристика, не подтверждение первичности или достоверности.

## Найденные ссылки
1. Real-Time Diarization + Streaming ASR | pyannoteAI — https://pyannote.ai/blog/real-time-diarization-transcription
   > 
```
{"type":"diarization_speaker_start",
"data":{"timestamp":0.42,"speaker":"SPEAKER_00"}}
{"type":"diarization_speaker_end",
"data":{"timestamp":1.86,"speaker":"SPEAKER_00"}}
```
2. DongKeon/Awesome-Speaker-Diarization — https://github.com/DongKeon/Awesome-Speaker-Diarization
   > "Online Streaming End-to-End Neural Diarization Handling Overlapping Speech and Flexible Numbers of Speakers", in Proc. End-to-End Speaker-Attributed ASR,"
3. Streaming ASR Unifies Transcription and Speaker Attribution — https://www.sotapapers.com/article/2026/09/streaming-asr-unifies-transcription-and-speaker-attribution-2609-02812
   > End-to-end streaming ASR can jointly emit transcript text and speaker attribution · Interleaving audio, lookahead, and prior text supports ...
4. VibeVoice-ASR-Streaming Technical Report — https://arxiv.org/html/2609.02812v1
   > being spoken and its speaker-attributed transcription settling: an *expected algorithmic* delay C/2+T_(lookahead) for VibeVoice-ASR-Streaming, with C the chunk duration, giving 2.00 s at 22 frames
5. When Forgetting Looks Like Improvement: Metric Masking in Streaming Diarizer Adaptation and the Price of Rehearsal — https://arxiv.org/html/2610.08828
   > diarization must detect speaker activity and maintain consistent identities as audio arrives [12]. When combining with a Streaming Sortformer it addresses online identity tracking through a speaker
6. Streaming Speaker-Attributed ASR with Token-Level ... — https://www.microsoft.com/en-us/research/publication/streaming-speaker-attributed-asr-with-token-level-speaker-embeddings/
   > This paper presents a streaming speaker-attributed automatic speech recognition (SA-ASR) model that can recognize “who spoke what” with low ...
7. Online Streaming End-to-End Neural DiarizationHandling Overlapping Speech and Flexible Numbers of Speakers — https://arxiv.org/html/2101.08473v2
   > To solve the overlapping issue, an end-to-end neural diarization model (EEND) was proposed [27]. EEND directly minimizes the diarization error by mapping the multi-speaker mixture recording to joint
8. VibeVoice-ASR-Streaming Technical Report — https://doi.org/10.48550/arxiv.2609.02812
   > delay $C/2+T_{\mathrm{lookahead}}$ for VibeVoice-ASR-Streaming, with $C$ the chunk duration, giving 2.00 s at 22 frames and 1.53 s at 15, and a __measured wall-clock__ mean for the cloud services.
9. Streaming speaker diarization: How to identify who's speaking in real time | AssemblyAI — https://assemblyai.com/blog/streaming-speaker-diarization
   > while people are still talking. This creates a fundamental constraint: once the system assigns a speaker label to audio, that decision becomes permanent with no ability to revise it later.
10. Streaming Sortformer: Speaker Cache-Based Online ... — https://www.researchgate.net/publication/396813275_Streaming_Sortformer_Speaker_Cache-Based_Online_Speaker_Diarization_with_Arrival-Time_Ordering
   > This paper introduces an online speaker diarization system that can handle long-time audio with low latency. First, a new variant of agglomerative hierarchy ...

## Фрагменты страниц

### https://github.com/DongKeon/Awesome-Speaker-Diarization

BranchesTags

## Latest commit

## History

146 Commits

## Folders and files

| Name | | Name | Last commit message | Last commit date |
| --- | --- | --- | --- | --- |
| README.md | | README.md |  |  |
|  | | |

## Repository files navigation

# 🎤 Awesome Speaker Diarization

📄 Paper · 💻 Code · 📝 Review · 🎬 Video/Demo · 📊 Slides · 🔗 Other

---

**🧠 Core Methods**

**🔌 Extensions**

**🌐 Cross-Modal**

**🔗 Related**

**📦 Resources**

---

## 📖 Overview — 1 paper

**2020 (1 paper)**

* **DIHARD Keynote Session:** The yellow brick road of diarization, challenges and other neural paths 📊 🎬


---

## 📝 Reviews — 3 papers

**🔥 2023-2024 (3 papers)**

* "Overview of Speaker Modeling and Its Applications: From the Lens of Deep Speaker Representation Learning," in *Submitted to IEEE/ACM TASLP*, 2024. 📄
* “A review of speaker diarization: Recent advances with deep learning”, in *Computer Speech & Language, Volume 72,* 2023. (USC) 📄
* "An Experimental Review of Speaker Diarization methods with application to Two-Speaker Conversational Telephone Speech recordings", in *Computer Speech & Language,* 2023. 📄


---

## 📚 EEND (End-to-End Neural Diarization)-based — 50 papers

**🔥 2025 (7 papers)**

* "Mamba-based Segmentation Model for Speaker Diarization," *Proc. ICASSP,* 2025. (NTT) 📄 💻
* "Pushing the Limits of End-to-End Diarization," in *Proc. Interspeech,* 2025. 📄
* **VBx-EEND-VC**: "VBx for End-to-End Neural and Clustering-based Diarization," in *arXiv:2510.19572,* 2025. (BUT) 📄
* "Im

### https://arxiv.org/html/2101.08473v2

# Online Streaming End-to-End Neural Diarization Handling Overlapping Speech and Flexible Numbers of Speakers

###### Abstract

We propose a streaming diarization method based on an end-to-end neural diarization (EEND) model, which handles flexible numbers of speakers and overlapping speech. In our previous study, the speaker-tracing buffer (STB) mechanism was proposed to achieve a chunk-wise streaming diarization using a pre-trained EEND model. STB traces the speaker information in previous chunks to map the speakers in a new chunk. However, it only worked with two-speaker recordings. In this paper, we propose an extended STB for flexible numbers of speakers, FLEX-STB. The proposed method uses a zero-padding followed by speaker-tracing, which alleviates the difference in the number of speakers between a buffer and a current chunk. We also examine buffer update strategies to select important frames for tracing multiple speakers. Experiments on CALLHOME and DIHARD II datasets show that the proposed method achieves comparable performance to the offline EEND method with 1-second latency. The results also show that our proposed method outperforms recently proposed chunk-wise diarization methods based on EEND (BW-EDA-EEND).

2 Language Technologies Institute, Carnegie Mellon University, USA

3 Center for Language and Speech Processing, Johns Hopkins University, USA††email: yawen.xue.wn@hitachi.com

Index Terms: online speaker diarization, EEND, overlapping speech, flexible numbers
