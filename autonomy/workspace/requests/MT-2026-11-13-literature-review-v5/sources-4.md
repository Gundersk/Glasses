# Поиск: speaker-attributed ASR cpWER ORC-WER AS-WER evaluation protocol SA-ASR paper AMI CALLHOME

Дата: 2026-11-14
Зачем: найти внешний ориентир для метрики проекта

Это источник, не измерение. Числа переносить в `docs/benchmarks.md`
только после проверки цитаты функцией `quote_in_page`.
Подсказки первоисточника — эвристика, не подтверждение первичности или достоверности.

## Найденные ссылки
1. SPEAKER ATTRIBUTED AUTOMATIC SPEECH ... — https://arxiv.org/pdf/2604.11269
   > by H Aronowitz · 2026 · Cited by 4 — Regarding ASR accuracy (not reported in the Table), WER decreased slightly on Fisher and CallHome, and decreased by 14% and 21% for AMI-SDM and GALE ...
2. A Comparative Study of Modular and Joint Approaches for Speaker-Attributed ASR on Monaural Long-Form Audio — https://doi.org/10.48550/arxiv.2107.02852
   > In the evaluation, we used the concatenated minimum-permutation word error rate (cpWER) [5] as a primary metric. The cpWER is computed as follows: (i) concatenate all reference transcriptions in
3. Speaker-Attributed Training for Multi-Speaker Speech ... — https://www.mdpi.com/2076-3417/14/18/8138
   > by M Kim · 2024 · Cited by 12 — This paper proposes a multi-speaker ASR method that incorporates speaker embedding information as an additional input. in the word error rate ( ...
4. arxiv.org/pdf/2309.13573 — https://arxiv.org/pdf/2309.13573
   > Multi-party Meet-
ing Transcription challenge (M2MeT), the second M2MeT
challenge (M2MeT 2.0) held in ASRU2023 particularly aims
to tackle the complex task of speaker-attributed ASR (SA-
ASR),
5. Transcribe-to-Diarize: Neural Speaker Diarization for Unlimited Number of Speakers using End-to-End Speaker-Attributed ASR — https://arxiv.org/html/2110.03151v2
   > In our experiment using the LibriCSS [24] and AMI [25] corpora, we show that the proposed method achieves the SOTA performance in both diarization error rate (DER) and the concatenated
6. THE SECOND MULTI-CHANNEL MULTI-PARTY MEETING TRANSCRIPTION CHALLENGE (M2MeT 2.0): A BENCHMARK FOR SPEAKER-ATTRIBUTED ASR — https://arxiv.org/html/2309.13573v1
   > order. This produces a single transcription within one session. Next, the character error rate (CER) is calculated between the concatenated reference and hypothesis transcriptions, and this process
7. Improving Speaker Assignment in Speaker-Attributed ASRfor Real Meeting Applications — https://arxiv.org/html/2403.06570v1
   > [31], the output is the concatenation of all speakers’ sentences in first-in-first-out order, where each token is associated with one speaker ID and distinct speakers are separated by an <sc>
8. From WER and RIL to MER and WIL — https://www.isca-archive.org/interspeech_2004/morris04_interspeech.pdf
   > by AC Morris · 2004 · Cited by 632 — The word error rate (WER), commonly used in ASR assess- ment, measures the cost of restoring the output word se- quence to the original input sequence ...
9. DNCASR: End-to-End Training for Speaker-Attributed ASR — https://www.semanticscholar.org/paper/DNCASR%3A-End-to-End-Training-for-Speaker-Attributed-Zheng-Zhang/098e8acb21934fa66e38aab607f5208c831f8a2e
   > This paper introduces a novel approach to speaker-attributed ASR transcription using a neural clustering method that does not require an extra non-neural ...
10. Speaker-attributed meeting transcription refinement with constrained open-weight language models — https://sciencedirect.com/science/article/pii/S0167739X26002827
   > analysis using standard metrics, including Diarization Error Rate (DER), Jaccard Error Rate (JER), Word Error Rate (WER), and concatenated minimum-permutation Word Error Rate (cpWER). The

## Фрагменты страниц

### https://arxiv.org/pdf/2604.11269

SPEAKER ATTRIBUTED AUTOMATIC SPEECH RECOGNITION 
USING SPEECH AWARE LLMS 
 
Hagai Aronowitz*, Zvi Kons*, Avihu Dekel, George Saon, Ron Hoory 
 
IBM Research 
 
 
 Core contributors 
ABSTRACT 
 
Speaker-Attributed Automatic Speech Recognition (SAA) 
enhances traditional ASR systems by incorporating relative 
speaker identity tags directly into the transcript  (e.g., [Speaker 1]:, 
[Speaker 2]:). In this work, we extend the capabilities of Granite-
speech, a state -of-the-art speech-aware Large Language Model 
(LLM) originally trained for transcription and translation . We 
demonstrate that it can be  effectively adapted for SAA with only 
minimal architectural changes. Our core contribution is the 
introduction of speaker cluster identification tags  (e.g., [Speaker 1 
cluster 42]:) which are  jointly train ed with SAA to significantly 
improve accuracy. To address limitations in training data,  we 
propose a data augmentation method that uses artificially 
concatenated multi -speaker conversations . Our approach is 
evaluated across multiple benchmark s and shows superior 
performance compared to conventional pipelines that sequentially 
perform speaker diarization followed by ASR. 
 
Index Terms — SAA, s peaker attributed ASR, speaker 
diarization, speech-aware LLM, Granite Speech 
 
1. INTRODUCTION 
 
Automatic Speech Recognition (ASR) has  witnessed remarkable 
advancements in recent years, driven by large-scale pretraining and 
powerful neural sequence model s. Despite t

### https://doi.org/10.48550/arxiv.2107.02852

# Electrical Engineering and Systems Science > Audio and Speech Processing

[Submitted on 6 Jul 2021 (v1), last revised 17 Sep 2021 (this version, v2)]

# Title:A Comparative Study of Modular and Joint Approaches for Speaker-Attributed ASR on Monaural Long-Form Audio

View a PDF of the paper titled A Comparative Study of Modular and Joint Approaches for Speaker-Attributed ASR on Monaural Long-Form Audio, by Naoyuki Kanda and 8 other authors

View PDF
HTML (experimental)
> Abstract:Speaker-attributed automatic speech recognition (SA-ASR) is a task to recognize "who spoke what" from multi-talker recordings. An SA-ASR system usually consists of multiple modules such as speech separation, speaker diarization and ASR. On the other hand, considering the joint optimization, an end-to-end (E2E) SA-ASR model has recently been proposed with promising results on simulation data. In this paper, we present our recent study on the comparison of such modular and joint approaches towards SA-ASR on real monaural recordings. We develop state-of-the-art SA-ASR systems for both modular and joint approaches by leveraging large-scale training data, including 75 thousand hours of ASR training data and the VoxCeleb corpus for speaker representation learning. We also propose a new pipeline that performs the E2E SA-ASR model after speaker clustering. Our evaluation on the AMI meeting corpus reveals that after fine-tuning with a small real data, the joint system performs 8.9--29.9% better in accuracy c
