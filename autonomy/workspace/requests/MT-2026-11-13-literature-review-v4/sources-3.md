# Поиск: audio-visual speaker diarization active speaker detection face voice association benchmark AVSD

Дата: 2026-11-14
Зачем: найти внешний ориентир для метрики проекта

Это источник, не измерение. Числа переносить в `docs/benchmarks.md`
только после проверки цитаты функцией `quote_in_page`.
Подсказки первоисточника — эвристика, не подтверждение первичности или достоверности.

## Найденные ссылки
1. Cross-attention and Self-attention for Audio-visual Speaker ... — https://arxiv.org/html/2506.02621v1
   > Audio-visual speaker diarization (AVSD) is a technology that integrates both audio and visual signals to determine “who spoke when” [1] in ...
2. Active Speaker Detection Using Audio, Visual, and Depth ... — https://www.researchgate.net/publication/382204735_Active_Speaker_Detection_using_Audio_Visual_and_Depth_Modalities_A_Survey
   > Audio-visual active speaker detection (AV-ASD) aims to identify which visible face is speaking in a scene with one or more persons. Most ...
3. AVA-AVD: Audio-visual Speaker Diarization in the Wild — https://www.semanticscholar.org/paper/AVA-AVD%3A-Audio-visual-Speaker-Diarization-in-the-Xu-Song/e7b68d0ec4889837442581feac324ab8af982d89
   > The AVA Audio-Visual Relation Network (AVR-Net) is designed which introduces a simple yet effective modality mask to capture discriminative information ...
4. Assessing active speaker detection algorithms through the ... — https://project.inria.fr/wicedxcinemotions2023/files/2023/06/WICED_x_Cinemotions_2023_paper_13.pdf
   > We set up and evaluate three different classes of ASD algorithms for active speaker detection in the OSD. We employ an off-the- shelf audio-visual algorithm and ...
5. Ensembling Synchronisation-based and Face-Voice Association Paradigms for Robust Active Speaker Detection in Egocentric Recordings — https://arxiv.org/html/2508.10580
   > Empirical validation on Ego4D-AVD: the ensemble achieves $70.2$% and $66.7$% mAP for two synchronisation-based components (TalkNet and Light-ASD), marking a new state-of-the-art in the domain of
6. Audio-visual Speaker Diarization: Improved Voice Activity ... — https://repository.kaust.edu.sa/bitstreams/20d9e30f-d81d-4608-89fb-92ebfb179ff9/download
   > by K Fanaras · 2022 · Cited by 7 — This paper presents a deep learning architecture to implement an AV speaker diarization system emphasizing Voice Activity. Detection (VAD). Traditional AV ...
7. AVA-ActiveSpeaker: An Audio-Visual Dataset for Active ... — https://www.alphaxiv.org/abs/1901.01342
   > Active speaker detection is an important component in video analysis algorithms for applications such as speaker diarization, video re-targeting for ...
8. Decoupled Dual-Stream Temporal-Speaker Interaction for Audio-Visual Speaker Detection — https://arxiv.org/html/2512.19130v1
   > - [13] (2020) Ava active speaker: an audio-visual dataset for active speaker detection.
9. THE WHU-ALIBABA AUDIO-VISUAL SPEAKER ... — https://mispchallenge.github.io/mispchallenge2022/papers/task1/Track1_WHU-ALIBABA.pdf
   > by M Cheng · Cited by 11 — Speaker diarization is the process of detecting speakers' voice activ- ities in conversational data. Many classical methods are proposed, including clustering- ...
10. Beyond Visible Speakers: Context-Aware Active Speaker Detection with Speaker Registration — https://doi.org/10.48550/arxiv.2610.33127
   > representations with fine-grained localized visual cues, such as mouth information, and fuses audio, face, and mouth streams through flexible joint self-attention with modality-dropout training. This

## Фрагменты страниц

### https://arxiv.org/html/2508.10580

# Ensembling Synchronisation-Based and Face–Voice Association Paradigms for Robust Active Speaker Detection in Egocentric Recordings

###### Abstract

ASD (ASD) in egocentric recordings is challenged by frequent occlusions, motion blur, and audio interference, which undermine the discernability of temporal synchrony between lip movement and speech. Traditional synchronisation-based systems perform well under clean conditions but degrade sharply in first-person recordings. Conversely, FVA (FVA)-based methods forgo synchronisation modelling in favour of cross-modal biometric matching, exhibiting robustness to transient visual corruption but suffering when overlapping speech or front-end segmentation errors occur. In this paper, a simple yet effective ensemble approach is proposed to fuse synchronisation-dependent and synchronisation-agnostic model outputs via weighted averaging, thereby harnessing complementary cues without introducing complex fusion architectures. A refined preprocessing pipeline for the FVA-based component is also introduced to optimise ensemble integration. Experiments on the Ego4D-AVD validation set demonstrate that the ensemble attains % and % mAP (mAP) with TalkNet and Light-ASD backbones, respectively. A qualitative analysis stratified by face image quality and utterance masking prevalence further substantiates the complementary strengths of each component.

###### Keywords:

Face-voice association, Audiovisual active speaker detection, egocentric record
