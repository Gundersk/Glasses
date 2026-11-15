# Регрессия полноты и восстановления контекста

15.11.2026. `closes: LG-2026-11-15-02`. Seed не применим.

## Гипотеза

Обязательный structured handoff, полный REVIEW JSON и pre-call manifest
исключают локальное молчаливое отбрасывание критических данных в тестовых сценариях.
Это не гипотеза качества суммаризации живой LLM.

## Данные и конфигурация

Синтетические STATE/task/card и временные файлы: длинные STATUS/history,
claims/decision с tail после24k, большой diff, packet после добавления handoff,
ошибка записи manifest, missing/denied paths. Модели/команды прототипа замоканы;
ни внешняя компактизация, ни новая карточка, ни ночь не запускались.
Windows/рабочая .venv. SHA кода/команды/логи — в test receipt.

## Команды и критерии

`python -m unittest discover -s autonomy/tests -p 'test_*.py' -v` и четыре
standalone сценария из `docs/audits/2026-11-15/context-preservation-tests.json`.
Критерии: полный обязательный tail доступен REVIEW; превышение cap/ошибка
manifest дают ноль model calls и не списывают author quota; DONE/blocked
сохраняются после STATE JSON roundtrip; source/hash/omissions отражены явно;
manifest существует уже внутри underlying call; approved_commands не создаёт
fake call manifest. Тест вклада handoff изолирован от фиксированного allowance256.

## Результат и ограничения

Число/исход финального полного прогона — в receipt; scoped reviewer PASS после
исправлений. Symlink ветки без Windows-привилегий пропущены, не выданы за PASS.
Read-only чтение текущих файлов проведено отдельно: `context-current-files.json`,
локальный диагностический manifest в artifacts/context. Его hashes относятся
к моменту диагностики, позднее STATUS/инструкции обновлялись; он не текущий baseline.

Инфраструктурная проверка не доказывает удержание решений конкретной моделью,
экономию квоты или принятие старого обзора. Внешние compaction параметры
оставлены неизменными. Старые run/вердикты не редактировались.
