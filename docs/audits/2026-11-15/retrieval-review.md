# Ограниченные ревью маршрута

`closes: LG-2026-11-15-01`. 15.11.2026. Статические проверки, без исполнения тестов
самими reviewer. Независимость по семействам моделей не гарантируется.

## Архив/дедупликация

Reviewer ses_e20873116ffeqhNj8NL46j4oU7: source_archive/publication_identity/source_selection.
Пять MEDIUM: доверие TTL из индекса; смешение явных версий; конфликт сильных ID;
неполные supplement/errata категории; извлечение ID из произвольного URL.
Исправлены, добавлены негативные тесты. Повторный вердикт PASS в этих границах.
Title-группировка по-прежнему эвристика, научная идентичность не установлена.

## Valyu/расходы/переключение

Reviewer ses_e20876599ffeDS9AkyCOQZxSKy: valyu_reader/retrieval/reader accounting runner.
HIGH: max(сумм) вместо суммы консервативных per-attempt charges; ошибка бюджета
не блокировала дальнейшую работу; socket timeout не ограничивал весь запрос.
MEDIUM: отсутствие точной URL-атрибуции. Исправлены SUM(max) на попытку,
persistent paid_work_blocked до новых вызовов, отдельный завершаемый HTTP-worker,
exact URL error attribution (с исключением известного whole-service отказа).
Повторно: JSONDecodeError мог разрешить платный fallback; конфликт cost-полей
игнорировался; http503 predicate расходился. Исправлено, последнее ревью PASS.

Последующие небольшие правки основной сессии: observed total_cost_dollars,
credential-echo rejection, provider-wide denial без обхода всех URL; покрыты
тестами, не выдаются за новое полное статическое ревью системы.

Протокол: retrieval-tests.json. Из374 unittest один symlink-case пропущен
из-за прав Windows; остальные373 прошли, плюс23 standalone. Local subprocess
kill не гарантирует отмены работы провайдера; неизвестный запрос оставляет резерв
и circuit disabled. Качество живого обзора не проверялось, нового run не было.
