# Поиск: CHiME-8 Task 3 MMCSG published WER baseline 21.4% — существует ли это число, какой язык и корпус (MMCSG), какие условия (домен, шум, спикеры)

Дата: 2026-11-12
Зачем: План берёт 21.4 % как целевой ориентир; нужно проверить, что число реально опубликовано и что MMCSG вообще сопоставим с русским ASR на FLEURS — если корпус не русскоязычный, сравнение бессмысленно и з

Источник, не измерение. Числа — только после проверки цитаты.

ЗАПРОС: CHiME-8 Task 3 MMCSG published WER baseline 21.4% — существует ли это число, какой язык и корпус (MMCSG), какие условия (домен, шум, спикеры)
1. PowerPoint 演示文稿 — https://chimechallenge.org/workshops/chime2024/papers/19_slides.pdf
   > 1.7
4.2
10.5
1.6
24.4
2.6
7.3
12.3
2.2
0.34
15.0
1.4
3.9
8.4
1.4
21.4
2.2
7.2
10.1
1.8
0.62
14.3
1.3
3.8
7.9
1.3
20.3
2.1
7.1
9.6
1.6
SEUEE
>1.0
12.0
1.4
3.9
6.3
0.4
20.2
3.0
6.5
10.2
0.5
dev
2. GitHub - facebookresearch/MMCSG: This repository contains the baseline system for CHiME-8 MMCSG challenge focusing on transcribing both sides of a conversation where one participant is wearing smart glasses equipped with a microphone array and camera. — https://github.com/facebookresearch/MMCSG
   > | DEL [%] | DEL [%] | ATTR [%] |
| 0.15 | 17.9 | 1.7 | 4.2 | 10.5 | 1.6 | 24.4 | 2.6 | 7.3 | 12.3 | 2.2 |
| 0.34 | 15.0 | 1.4 | 3.9 | 8.4 | 1.4 | 21.4 | 2.2 | 7.2 | 10.1 | 1.8 |
| 0.62 | 14.3 | 1.3
3. When Forgetting Looks Like Improvement: Metric Masking in Streaming Diarizer Adaptation and the Price of Rehearsal — https://arxiv.org/html/2610.08828v1
   > nominal count-FA targets of 2.0%, 2.62%, and 3.5%, Expert has lower gMiss but higher DER on both AMI and EasyCom. The DER increases range from 11.31 to 11.59 pp and from 0.27 to 1.52 pp, respectively.
4. MMCSG/README_from_scratch.md at main · facebookresearch/MMCSG — https://github.com/facebookresearch/MMCSG/blob/main/README_from_scratch.md
   > use any pre-trained model. Instead, here we train a model from scratch based on Librispeech, TEDLIUM speech corpora, DNS noise corpus, and real room impulse responses collected with the Aria
5. MMCSG/README.md at main · facebookresearch/MMCSG — https://github.com/facebookresearch/MMCSG/blob/main/README.md
   > | DEL [%] | DEL [%] | ATTR [%] |
| 0.15 | 17.9 | 1.7 | 4.2 | 10.5 | 1.6 | 24.4 | 2.6 | 7.3 | 12.3 | 2.2 |
| 0.34 | 15.0 | 1.4 | 3.9 | 8.4 | 1.4 | 21.4 | 2.2 | 7.2 | 10.1 | 1.8 |
| 0.62 | 14.3 | 1.3
6. Baseline System — https://chimechallenge.org/challenges/chime8/task3/baseline
   > different baseline systems:
- [Baseline starting from public pre-trained model](https://github.com/facebookresearch/MMCSG/blob/main/README.md), which is fine-tuned on the in-domain MMCSG dataset.
### https://chimechallenge.org/workshops/chime2024/papers/19_slides.pdf
(пусто)
