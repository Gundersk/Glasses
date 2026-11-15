# Ночной дайджест 20261111

Обновлён: 2026-11-12 11:14. Фаза: DONE.

## Задачи

| Задача | Цель | Статус | verify | Артефакты |
|---|---|---|---|---|
| T1 | — | done | True | autonomy/workspace/outbox/T1_result.md, experiments/file_stream_eval.py, experiments/stage2_resources/sherpa_resources.json, experiments/stage2_resources/sherpa_result.json, experiments/stage2_resources/vosk_resources.json, experiments/stage2_resources/vosk_result.json |
| T2 | — | done | True | autonomy/workspace/outbox/T2_result.md, experiments/stage2_conditions/noise_manifest.json, experiments/stage2_conditions/sherpa_conditions.json, experiments/stage2_conditions/vosk_conditions.json |
| T3 | — | done | True | autonomy/workspace/outbox/T3_result.md, experiments/engine_choice.md |
| T4 | — | done | True | reports/monthly/2026-11-draft.md |
| E23-20clips | E2.3 | pending | None | — |
| E23-errors | E2.3 | pending | None | — |
| E24-demo-prep | E2.4 | pending | None | — |

## Цели

- E2.1 [done]: Одна streaming-ASR модель на русском запущена; зафиксированы задержка и ошибки (доказательств 4, ночей без прогресса 0)
- E2.2 [done]: Частичный и финальный текст выводятся в браузер/на экран и проверены на тестовом аудио (доказательств 3, ночей без прогресса 0)
- E2.3 [open]: Статистика задержки и WER: медиана/p95 и примеры ошибок; для WER выборка не менее 20 клипов (доказательств 2, ночей без прогресса 0)
- E2.4 [open]: Демонстрация и отчёт к 24.11.2026 подготовлены (доказательств 0, ночей без прогресса 0)

## Следующие задачи

- E23-20clips (цель E2.3): Перезапустить файловый потоковый замер на 20 клипах FLEURS для sherpa-onnx и Vosk в условиях clean, snr20, snr10, snr5 и получить медиану/p95 задержки и WER с n
- E23-errors (цель E2.3): Выписать из 20-клиповых результатов примеры замен, вставок и пропусков и собрать сводку медианы/p95 и WER с ограничениями.
- E24-demo-prep (цель E2.4): Подготовить воспроизводимый сценарий демонстрации браузерных субтитров и чеклист, не заявляя запись живого голоса или видеодемонстрацию выполненными.

## Как продолжить

```powershell
.venv\Scripts\python.exe -m autonomy.runner status
.venv\Scripts\python.exe -m autonomy.preflight
.venv\Scripts\python.exe -m autonomy.runner tick
```

## Где смотреть

- план: `autonomy/workspace/night_plan.yaml`
- цели: `autonomy/goals.yaml`
- отчёт ночи: `autonomy/workspace/outbox/reports/20261111.md`
- уроки: `autonomy/workspace/lessons.md`
- события: `autonomy/workspace/events.jsonl`
