# Поиск: audiovisual active speaker detection talking face audio video research captions accessibility

Дата: 2026-11-14
Зачем: найти внешний ориентир для метрики проекта

Это источник, не измерение. Числа переносить в `docs/benchmarks.md`
только после проверки цитаты функцией `quote_in_page`.
Подсказки первоисточника — эвристика, не подтверждение первичности или достоверности.

## Найденные ссылки
1. Audio-Visual Active Speaker Detection on Embedded Devices — https://www.youtube.com/watch?v=cu4WQVSyH4M
   > The audio and visual embeddings are finally combined within the “fusion” block that outputs the probability of an individual speaking. This ...
2. Active Speaker Detection Using Audio, Visual, and Depth ... — https://www.researchgate.net/publication/382204735_Active_Speaker_Detection_using_Audio_Visual_and_Depth_Modalities_A_Survey
   > Audio-visual active speaker detection (AV-ASD) aims to identify which visible face is speaking in a scene with one or more persons. Most ...
3. Face-Voice Association for Audiovisual Active Speaker ... — https://eusipco2025.org/wp-content/uploads/pdfs/0000066.pdf
   > Audiovisual active speaker detection (ASD) refers to the task of identifying the video-framewise speaking activity of a candidate speaker through the joint ...
4. AS-Net: active speaker detection using deep audio-visual ... — https://link.springer.com/article/10.1007/s11042-024-18457-9
   > by A Radman · 2024 · Cited by 7 — Active Speaker Detection (ASD) aims at identifying the active speaker among multiple speakers in a video scene.
5. AVA-ActiveSpeaker: An Audio-Visual Dataset for Active Speaker Detection — https://arxiv.org/html/1901.01342v2
   > The dataset contains temporally labeled face tracks in video, where each face instance is labeled as speaking or not, and whether the speech is audible. This dataset contains about 3.65
6. arxiv.org/pdf/2410.11068 — https://arxiv.org/pdf/2410.11068
   > on two fronts: first, we show that audio-visual syn-
chronisation can be used to pick out the talking face amongst others
present in a video clip, and assign an identity to the
7. arxiv.org/pdf/1901.01342v2.pdf — https://arxiv.org/pdf/1901.01342v2.pdf
   > AVA-ActiveSpeaker: An Audio-Visual Dataset for Active Speaker Detection
Joseph Roth, Sourish Chaudhuri, Ondrej Klejch, Radhika Marvin, Andrew Gallagher, Liat Kaver,
8. Active speaker detection on video that's 90% faster — https://www.reddit.com/r/computervision/comments/1b2awl7/active_speaker_detection_on_video_thats_90_faster/
   > This is particularly built for visual active speaker detection where we can associated a specific person in the video to be speaking.
9. An Efficient and Streaming Audio Visual Active Speaker ... — https://machinelearning.apple.com/research/efficient-streaming-audio-visual
   > This paper delves into the challenging task of Active Speaker Detection (ASD), where the system needs to determine in real-time whether a person is speaking ...
10. A Lightweight Audio-Visual Speaker Detection System for Assistive Video Captioning — https://researchportal.ip-paris.fr/en/publications/a-lightweight-audio-visual-speaker-detection-system-for-assistive
   > In this paper we introduce a novel dynamic subtitling system aimed at improving media accessibility for individuals with hearing impairments. The system is built upon an end-to-end active speaker

## Фрагменты страниц

### https://eusipco2025.org/wp-content/uploads/pdfs/0000066.pdf

Face-V oice Association for Audiovisual Active
Speaker Detection in Egocentric Recordings
Jason Clarke 1, Yoshihiko Gotoh 1, and Stefan Goetze 1,2
1Speech and Hearing (SPandH) group, School of Computer Science, The University of Sheffield, Sheffield, United Kingdom
2South Westphalia University of Applied Sciences, Iserlohn, Germany
{jclarke8, y.gotoh, s.goetze }@sheffield.ac.uk, goetze.stefan@fh-swf.de
Abstract—Audiovisual active speaker detection (ASD) is con-
ventionally performed by modelling the temporal synchronisa-
tion of acoustic and visual speech cues. In egocentric record-
ings, however, the efficacy of synchronisation-based methods is
compromised by occlusions, motion blur, and adverse acoustic
conditions. In this work, a novel framework is proposed that
exclusively leverages cross-modal face-voice associations to deter-
mine speaker activity. An existing face-voice association model
is integrated with a transformer-based encoder that aggregates
facial identity information by dynamically weighting each frame
based on its visual quality. This system is then coupled with
a front-end utterance segmentation method, producing a com-
plete ASD system. This work demonstrates that the proposed
system, Self-Lifting for audiovisual active speaker detection
(SL-ASD), achieves performance comparable to, and in certain
cases exceeding, that of parameter-intensive synchronisation-
based approaches with significantly fewer learnable parameters,
thereby validating the feasibility 

### https://arxiv.org/html/1901.01342v2

# AVA-ActiveSpeaker: An Audio-Visual Dataset for Active Speaker Detection

###### Abstract

Active speaker detection is an important component in video analysis algorithms for applications such as speaker diarization, video re-targeting for meetings, speech enhancement, and human-robot interaction. The absence of a large, carefully labeled audio-visual dataset for this task has constrained algorithm evaluations with respect to data diversity, environments, and accuracy. This has made comparisons and improvements difficult. In this paper, we present the AVA Active Speaker detection dataset (AVA-ActiveSpeaker) that will be released publicly to facilitate algorithm development and enable comparisons. The dataset contains temporally labeled face tracks in video, where each face instance is labeled as speaking or not, and whether the speech is audible. This dataset contains about 3.65 million human labeled frames or about 38.5 hours of face tracks, and the corresponding audio. We also present a new audio-visual approach for active speaker detection, and analyze its performance, demonstrating both its strength and the contributions of the dataset.

### 1 Introduction

Conversational content in videos has received significant attention in the literature, with audio-only, visual-only, and joint audiovisual modeling approaches applied to applications such as human-robot interactions, speech recognition and analysis, and video re-targeting. Active speaker detection— detecting which (if
