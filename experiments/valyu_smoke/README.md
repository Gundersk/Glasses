# Диагностика Valyu Contents и повторного использования

15.11.2026. `closes: LG-2026-11-15-01`. Seed не применим.

## Гипотезы

Существующий receipt-bound текст AVA может быть использован без повторного
чтения; Valyu Contents может дать текст точного URL после отказа основного reader.
Не гипотеза качества ASR, полноты обзора или научной новизны.

## Данные/конфигурация

Точная открытая копия https://arxiv.org/html/1901.01342v2 и
https://ieeexplore.ieee.org/document/9053900. Два URL, не случайная выборка сайтов.
Windows/рабочая .venv. POST/v1/contents,1URL/вызов,short,normal,summary=false,
screenshot=false,max_age0,deadline40с. Секрет передан только env/pipe в runtime;
не ключ в argv/log/коде. Консервативный budget0.02USD,maxcalls2, без ретраев.

`python experiments/valyu_smoke/check.py --execute` — вызван один раз;
по умолчанию скрипт dry-run. Valyu Search/AI Summary/DeepResearch не вызывались.

## Получено

Оба Contents-вызова HTTP200. arXiv принятый клиентом текст30000символов,
IEEE4895символов. Сохранены только голова/размер/SHA, не полный corpus.
Это транспортная/схемная приёмка, не проверка полного текста: IEEE может содержать
abstract/metadata/navigation, их не выдавать за всю статью. URL не переписывался.

Цена в исходном smoke записана unknown: response содержит total_cost_dollars,
который не распознавал тогдашний parser. Фактическое значение поля не сохранили;
ledger резерв0.02USD, не заявленный счёт. Поле добавлено и покрыто оффлайн-тестом,
ещё live-вызовов ради cost не делали. Тариф источника0.2credits/URL — не наше измерение.

Read-only реального архива:27eligibleURLs, выбор на старой выдаче v6 теперь
arXivv2+отдельныйSupplement,99файловv3/v6 неизменны. Loose cache52kнеиспользован,
взят matchingreceipt source30k; original_accessed14.11 сохранён. Старый runнепринят.

## Протоколы и ограничения

`docs/audits/2026-11-15/valyu-smoke-20261115T190309.json`,
`archive-selection-diagnostic.json`, `retrieval-tests.json`, `retrieval-review.md`.
374 unittest(373PASS/1skip)+23standalone. APIконтракт и unit hashes в протоколе.
Новый обзор/поисковая модель/ночь не запускались. Смена ChatGPTаккаунта не повод
сбрасывать quota. Для постоянной Valyu работы ещё нужен envVALYU_API_KEY;
глобальный JSON/постоянное окружение не менялись. Пара Contentsуспехов не
доказывает общую надёжность, дешёвизну, полноту и автономное завершение обзора.
