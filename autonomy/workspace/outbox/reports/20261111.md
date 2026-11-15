# Отчёт за ночь 20261111


**Перегенерировано 2026-11-12:** статусы и артефакты взяты из актуальных `verify.T*.json`. Ночной прогон 11.11 завершился вручную; этот файл заменяет ошибочный отчёт, где T1, T2 и T4 были названы проваленными.

**Итог (посчитано кодом по verify.json):** задач 4, done 4, failed 0. Бюджет $0.0053.

## Задачи

| Задача | Цель | Статус | verify | чеков | Артефакты |
|---|---|---|---|---|---|
| T1 | — | done | True | 23/23 | autonomy/workspace/outbox/T1_result.md, experiments/file_stream_eval.py, experiments/stage2_resources/sherpa_resources.json, experiments/stage2_resources/sherpa_result.json, experiments/stage2_resources/vosk_resources.json, experiments/stage2_resources/vosk_result.json |
| T2 | — | done | True | 27/27 | autonomy/workspace/outbox/T2_result.md, experiments/stage2_conditions/noise_manifest.json, experiments/stage2_conditions/sherpa_conditions.json, experiments/stage2_conditions/vosk_conditions.json |
| T3 | — | done | True | 7/7 | autonomy/workspace/outbox/T3_result.md, experiments/engine_choice.md |
| T4 | — | done | True | 10/10 | reports/monthly/2026-11-draft.md |

## Цели

| Цель | Тип | Статус | Доказательств | Ночей без прогресса | Формулировка |
|---|---|---|---|---|---|
| E2.1 | stage | done | 4 | 0 | Одна streaming-ASR модель на русском запущена; зафиксированы задержка и ошибки |
| E2.2 | stage | done | 3 | 0 | Частичный и финальный текст выводятся в браузер/на экран и проверены на тестовом аудио |
| E2.3 | stage | open | 2 | 0 | Статистика задержки и WER: медиана/p95 и примеры ошибок; для WER выборка не менее 20 клипов |
| E2.4 | stage | open | 0 | 0 | Демонстрация и отчёт к 24.11.2026 подготовлены |

## Источники фактов

- план: `autonomy/workspace/night_plan.yaml`
- цели: `autonomy/goals.yaml`
- вердикты: `autonomy/workspace/verify.<id>.json`

## Что это значит

Интерпретация модели не добавлена: отчёт собран кодом по проверенным вердиктам. Числа WER и задержек смотрите в артефактах задач; отчёт не заявляет новых измерений.
