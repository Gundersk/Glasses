# T1 — расход ресурсов при файловом потоковом ASR

**Статус:** выполнено 11.11.2026. **closes:** roadmap:этап2-шаг3.
**Скрипт:** `experiments/file_stream_eval.py` (режим `resources`), написан заново в этой
сессии: прежняя версия была затёрта заглушкой `PLACEHOLDER_FULL_FILE` при ночном прогоне.

## Условия

- Вход: `data/fleurs_ru_test/clip_001.wav` + 1.0 с тишины в конце, итого 200320 отсчётов
  (`sample_count`), 16 кГц, моно float32.
- Подача: чанки 100 мс, `speed=1.0`, без браузера, динамика и микрофона.
- Модели: sherpa-onnx 2.0.1 (`streaming-zipformer-small-ru-vosk-int8-2025-08-16`, 2 потока,
  greedy, CPU), Vosk 0.3.45 (`vosk-model-small-ru-0.22`).
- Мониторинг: `psutil` по фактическому процессу ASR, интервал 0.05 с, 127 замеров;
  первый `cpu_percent(None)` вызывается заранее для калибровки.

## Команды

```
python experiments\file_stream_eval.py resources --engine sherpa --wav data\fleurs_ru_test\clip_001.wav --metrics experiments\stage2_resources\sherpa_resources.json --result experiments\stage2_resources\sherpa_result.json
python experiments\file_stream_eval.py resources --engine vosk --wav data\fleurs_ru_test\clip_001.wav --metrics experiments\stage2_resources\vosk_resources.json --result experiments\stage2_resources\vosk_result.json
```

Оба прогона: `asr_ok: true`, `simulated: false`, непустые partials и finals, rc=0.

## Результат

| Движок | cpu_avg, % | cpu_max, % | rss_mb_max | wall_s | n_frames | partials | finals |
|---|---:|---:|---:|---:|---:|---:|---:|
| sherpa | 29.87 | 199.5 | 133.051 | 12.5206 | 200320 | 71 | 1 |
| vosk | 8.318 | 58.7 | 246.176 | 12.5535 | 200320 | 71 | 1 |

Артефакты: `experiments/stage2_resources/{sherpa,vosk}_resources.json` и
`{sherpa,vosk}_result.json`.

## Определения и ограничения

- `n_frames` — число поданных **отсчётов** аудио, а не чанков; поэтому оно равно
  `sample_count`. Это записано в JSON полем `n_frames_unit: "audio_samples"`.
- `cpu_percent_max > 100%` означает несколько потоков процесса, а не ошибку.
- CPU-проценты двух движков напрямую не сопоставимы: разные процессы и число потоков.
- Один WAV и один прогон на движок; это не распределение и не оценка всех условий.
- Числа не переносились из документации и не пересчитывались «в пользу результата».
- Старые JSON из этой же папки были получены тем же способом, но утраченным скриптом;
  они перезаписаны текущими значениями, чтобы источник замера был воспроизводим.
