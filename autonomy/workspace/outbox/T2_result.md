# T2 — короткие русские фразы в разных цифровых условиях

**Статус:** выполнено 11.11.2026. **closes:** roadmap:этап2-шаг3.
**Скрипт:** `experiments/file_stream_eval.py` (режим `conditions`).

## Условия

- Клипы: `clip_000`–`clip_004` из `data/fleurs_ru_test/manifest.jsonl` (5 клипов, 88 слов эталона).
- Потоковый цикл: чанки 100 мс, `speed=1.0`, `tail_s=1.0`, 16 кГц, моно.
- Условия: `clean`, `snr20`, `snr10`, `snr5`; seed `20261109`.
- Шум: белый гауссов, подмешан к отсчётам WAV по заданному SNR, без динамика и микрофона.
- 15 шумных WAV: `experiments/stage2_conditions/audio/`,
  паспорт `experiments/stage2_conditions/noise_manifest.json`
  (фактический SNR отличается от целевого не более чем на 0.1 дБ).
- Оба движка читают одни и те же сохранённые WAV.

## Команды

```
python experiments\file_stream_eval.py conditions --engine sherpa --manifest data\fleurs_ru_test\manifest.jsonl --clips clip_000,clip_001,clip_002,clip_003,clip_004 --snr 20,10,5 --seed 20261109 --noise-dir experiments\stage2_conditions\audio --out experiments\stage2_conditions\sherpa_conditions.json
python experiments\file_stream_eval.py conditions --engine vosk --manifest data\fleurs_ru_test\manifest.jsonl --clips clip_000,clip_001,clip_002,clip_003,clip_004 --snr 20,10,5 --seed 20261109 --noise-dir experiments\stage2_conditions\audio --out experiments\stage2_conditions\vosk_conditions.json
```

## WER (корпусной, по 5 клипам, N = 88)

| Движок | clean | snr20 | snr10 | snr5 |
|---|---:|---:|---:|---:|
| sherpa-onnx | **2.27%** (2/0/0) | 3.41% (3/0/0) | 20.45% (12/6/0) | 35.23% (24/6/1) |
| Vosk | **14.77%** (11/1/1) | 14.77% (10/2/1) | 37.50% (20/12/1) | 59.09% (28/24/0) |

В скобках: S / D / I.

## Задержка

| Движок | Условие | final p50, мс | final p95, мс | n | partial p50, мс | partial p95, мс | n |
|---|---|---:|---:|---:|---:|---:|---:|
| sherpa | clean | 15.7 | 17.7 | 7 | 17.5 | 19.5 | 75 |
| sherpa | snr20 | 13.6 | 17.9 | 7 | 17.4 | 21.0 | 75 |
| sherpa | snr10 | 18.1 | 19.7 | 7 | 17.4 | 19.6 | 74 |
| sherpa | snr5 | 17.8 | 18.4 | 8 | 17.9 | 21.2 | 74 |
| vosk | clean | 8.2 | 9.9 | 6 | 17.7 | 48.2 | 97 |
| vosk | snr20 | 10.1 | 12.6 | 6 | 17.6 | 48.6 | 96 |
| vosk | snr10 | 11.3 | 38.3 | 7 | 22.6 | 71.7 | 90 |
| vosk | snr5 | 19.6 | 27.4 | 9 | 28.3 | 78.5 | 83 |

Артефакты: `experiments/stage2_conditions/{sherpa,vosk}_conditions.json` — там же
поклиповые `ref`, `hyp`, S/D/I, события partial и final с временами и задержками.

## Определение задержки

Задержка события = время события минус момент, когда последний поданный чанк ушёл в
движок. Это задержка выдачи текста внутри файлового тракта. В неё **не** входят: время
до конца фразы, endpointing, сеть и вывод в браузер. Значения квантованы шагом чанка
100 мс и с замерами из §2.4–2.6 отчёта напрямую не сравнимы.

## Ограничения

- Пять клипов на условие — предварительная проверка, не статистика; p95 при n = 6–9
  устойчивой оценкой не является.
- Шум цифровой и одинаковый для всех клипов условия; реверберация, дальний микрофон и
  улица не моделируются.
- Совпадение WER Vosk на clean и snr20 не доказывает устойчивости к шуму: на пяти клипах
  это эффект малой выборки.
- Один и тот же seed и одни и те же WAV у обоих движков; подбора шума ради лучшего WER
  не было.
