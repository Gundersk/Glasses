# Доступность источников и восстановление сбора

14.11.2026. `closes: LG-2026-11-14-03`. Seed не применим.

## Гипотезы

1. Другой reader может получить содержательный текст двух URL, заблокированных
   TinyFish в v6. 2. Ресурсная недоступность не должна отменять оставшиеся уже
   разрешённые команды; приёмка не должна превращать пустые manifests в источники.

## Данные/конфигурация/команды

IEEE9053900 и ADS2020spsi.conf..906R из сохранённого cache v6, без нового поиска.
Windows, рабочая .venv; TinyFish direct client, fresh=True, один batch двух URL.
`python experiments/source_access_diagnostic/check_tinyfish.py --execute`.
Без --execute скрипт offline. Ключи из env, cache исключён из git.

Exa web_fetch_exa: по researcher-брифу, один read каждого URL, maxCharacters5000.
Сырые Exa outputs не сохранены; повторная проверка основной сессией не выполнялась.
Поисковые inference-модели OpenRouter/Perplexity не вызывались; автоматический
платный fallback не включён. Проверка не обходила CAPTCHA/логин/robots-защиту.

Оффлайн-ветка: синтетические query manifests/страницы и mocked роли,
`python -m unittest discover -s autonomy/tests -p 'test_*.py' -v` и четыре
standalone-скрипта из `source-availability-tests.json`.

## Получено

TinyFish: оба URL bot_blocked, 0 символов содержимого.
Exa по брифу: IEEE1016 символов заголовка/навигации без abstract/статьи;
ADS timeout, содержимого нет. Преимущество Exa на этом n=2 не показано;
не сравнивать с качеством reader вообще или стоимостью полного обзора.
Конкретная причина firewall/HTTP-статус сайта/индекс против live неизвестны.

304 unittest и23 standalone PASS. Сквозные сценарии:
- три разрешённые команды available/blocked/available выполняются ровно по разу;
  реальные страницы и причины отказа раздельны, final mocked REVIEW=PARTIAL;
- все unavailable: коллекция failed, автор/semantic reviewer не вызываются;
- неисправность второго вызова: третий не выполняется;
- неверные статусы, чужой query/ID, превышение cap и невыбранные страницы отклоняются.

Артефакты: `docs/audits/2026-11-14/source-access-tinyfish.json`,
`fetch-alternatives.md`, `source-availability-tests.json`, `source-availability-review.md`.
Новый обзор/ночь/v7 не запускались, v6 остаётся blocked.

## Ограничения/следующий шаг

Оффлайн PASS не доказывает успешность живого обзора. Нужно либо отдельно
использовать сохранённый материал с ревью, либо согласовать новый ограниченный
run. Для альтернативного provider необходимы цена/лимит attempts/учёт; для копии
статьи — чтение и проверка соответствия, не подмена исходного URL.
