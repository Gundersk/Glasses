# Поиск: audio visual active speaker detection speech transcription captions speaker attribution research paper TalkNet

Дата: 2026-11-14
Зачем: найти внешний ориентир для метрики проекта

Это источник, не измерение. Числа переносить в `docs/benchmarks.md`
только после проверки цитаты функцией `quote_in_page`.
Подсказки первоисточника — эвристика, не подтверждение первичности или достоверности.

## Найденные ссылки
1. TaoRuijie/TalkNet-ASD: ACM MM 2021: 'Is Someone ... — https://github.com/TaoRuijie/TalkNet-ASD
   > TalkNet: Audio-visual active speaker detection Model. This repository contains the code for our ACM MM 2021 paper (oral), TalkNet, an active speaker detection ...
2. GitHub - TaoRuijie/TalkNet-ASD: ACM MM 2021: 'Is Someone Speaking? Exploring Long-term Temporal Features for Audio-visual Active Speaker Detection' — https://github.com/TaoRuijie/TalkNet-ASD/tree/main
   > paper (oral), TalkNet, an active speaker detection model to detect 'whether the face in the screen is speaking or not?'. [[Paper](https://arxiv.org/pdf/2107.06592.pdf)]
3. GitHub - DongKeon/TalkNet-ASD: ACM MM 2021: 'Is Someone Speaking? Exploring Long-term Temporal Features for Audio-visual Active Speaker Detection' — https://github.com/DongKeon/TalkNet-ASD
   > model to detect 'whether the face in the screen is speaking or not?'. [[Paper](https://arxiv.org/pdf/2107.06592.pdf)] [[Video_English](https://youtu.be/C6bpAgI9zxE)]
4. Is Someone Speaking?: Exploring Long-term Temporal Features for Audio-visual Active Speaker Detection — https://arxiv.org/pdf/2107.06592
   > where systems make decision instantaneously using short-term features, we propose a novel framework, named TalkNet, that makes decision by taking both short-term and long-term features into
5. Is Someone Speaking? Exploring Long-term Temporal Features for Audio-visual Active Speaker Detection — https://arcxiv.org/abs/2107.06592
   > where systems make decision instantaneously using short-term features, we propose a novel framework, named TalkNet, that makes decision by taking both short-term and long-term features into
6. Is Someone Speaking? Exploring Long-term Temporal Features for Audio-visual Active Speaker Detection — https://ui.adsabs.harvard.edu/abs/arXiv:2107.06592
   > where systems make decision instantaneously using short-term features, we propose a novel framework, named TalkNet, that makes decision by taking both short-term and long-term features into
7. Is Someone Speaking? Exploring Long-term Temporal Features for Audio-visual Active Speaker Detection — https://arxiv.org/abs/2107.06592
   > where systems make decision instantaneously using short-term features, we propose a novel framework, named TalkNet, that makes decision by taking both short-term and long-term features into
8. Improving audiovisual active speaker detection in egocentric recordings with the data-efficient image transformer — https://eprints.whiterose.ac.uk/id/eprint/204202/1/ASRU_AV-ASD_DeiT_cr.pdf
   > conditioning mechanism is proposed. The module is evaluated in
conjunction with TalkNet, an existing ASD architecture, on two
audiovisual datasets: Ego4D (egocentric) and AVA-ActiveSpeaker
9. Submitted to INTERSPEECH — https://arxiv.org/pdf/2305.12831v1
   > The recent work,
TalkNet [21], incorporated long-term temporal information and
demonstrated strong performance on the ASD task.
10. Target Active Speaker Detection with Audio-visual Cues — https://arxiv.org/html/2305.12831v3
   > In this paper, we propose the Target Speaker TalkNet (TS-TalkNet) for active speaker detection by incorporating target speaker embeddings.

## Фрагменты страниц

### https://github.com/TaoRuijie/TalkNet-ASD

BranchesTags

## Latest commit

## History

45 Commits

## Folders and files

| Name | | Name | Last commit message | Last commit date |
| --- | --- | --- | --- | --- |

## Repository files navigation

## Is someone talking? TalkNet: Audio-visual active speaker detection Model

This repository contains the code for our ACM MM 2021 paper (oral), TalkNet, an active speaker detection model to detect 'whether the face in the screen is speaking or not?'. [Paper] [Video\_English] [Video\_Chinese].

### Updates:

A new demo page. Thanks the contribution from mvoodarla !

* **Awesome ASD**: Papers about active speaker detection in last years.
* **TalkNet in AVA-Activespeaker dataset**: The code to preprocess the AVA-ActiveSpeaker dataset, train TalkNet in AVA train set and evaluate it in AVA val/test set.
* **TalkNet in TalkSet and Columbia ASD dataset**: The code to generate TalkSet, an ASD dataset in the wild, based on VoxCeleb2 and LRS3, train TalkNet in TalkSet and evaluate it in Columnbia ASD dataset.
* **An ASD Demo with pretrained TalkNet model**: An end-to-end script to detect and mark the speaking face by the pretrained TalkNet model.

---

### Dependencies

Start from building the environment

```
conda create -n TalkNet python=3.7.9 anaconda
conda activate TalkNet
pip install -r requirement.txt
```

Start from the existing environment

```
pip install -r requirement.txt
```

---

## TalkNet in AVA-Activespeaker dataset

#### Data preparation

The following script can be us

### https://arxiv.org/html/2305.12831v3

1National University of Singapore, Singapore
  
2Shenzhen Research Institute of Big Data, School of Data Science,
  
The Chinese University of Hong Kong, Shenzhen, China

# Target Active Speaker Detection with Audio-visual Cues

###### Abstract

In active speaker detection (ASD), we would like to detect whether an on-screen person is speaking based on audio-visual cues. Previous studies have primarily focused on modeling audio-visual synchronization cue, which depends on the video quality of the lip region of a speaker. In real-world applications, it is possible that we can also have the reference speech of the on-screen speaker. To benefit from both facial cue and reference speech, we propose the Target Speaker TalkNet (TS-TalkNet), which leverages a pre-enrolled speaker embedding to complement the audio-visual synchronization cue in detecting whether the target speaker is speaking. Our framework outperforms the popular model, TalkNet on two datasets, achieving absolute improvements of 1.6% in mAP on the AVA-ActiveSpeaker validation set, and 0.8%, 0.4%, and 0.8% in terms of AP, AUC and EER on the ASW test set, respectively. Code is available at https://github.com/Jiang-Yidi/TS-TalkNet/.

Index Terms: Active speaker detection, target speaker, audio-visual, speaker recognition

## 1 Introduction

The study of active speaker detection (ASD) is to determine whether an on-screen person is speaking in each video frame of an audio-visual scene [1]. It plays a critical frontend role
