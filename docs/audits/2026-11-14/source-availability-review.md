# Ограниченное ревью устойчивого сбора

14.11.2026. `closes: LG-2026-11-14-03`.

Два read-only reviewer, без запуска тестов/сети. Независимость по семействам
моделей не гарантируется; научную достоверность страниц они не проверяли.

1. `ses_e2515715fffe2bhkleHxMNNOFR`: intake/rebuild/runner. PASS в проверенных
   участках: file-check slicing сохраняет typed collection check; прежние
   источники связаны inputs followup, новый модуль включён в approval hash,
   невалидная/пустая коллекция не вызывает автора/semantic LLM.
2. `ses_e2515a2d3ffeF5jjJxoUmwC5jt`: research/source_outcomes/author_evidence.
   Первый вердикт — HIGH: status='ok' скрывал status_code429. MEDIUM: author
   самостоятельно не проверял query/selected-cap до unavailable-ветки.
   Оба исправлены и покрыты негативными тестами. Повторный вердикт PASS,
   остаточных HIGH/MEDIUM нет в проверенных исправлениях.

Полный тестовый прогон также выявил регрессию TinyFish.fetch: возвращались
невалидные/невыбранные страницы. Восстановлен контракт valid results only,
отклонённые страницы учитываются отдельно как invalid_results; opt-in сбор
такие schema/challenge-аномалии не принимает. Повторный общий прогон PASS.

Протокол основной сессии: `source-availability-tests.json`, 304 unittest +23
standalone проверки. Реальные сравнения readers — отдельно `fetch-alternatives.md`.
