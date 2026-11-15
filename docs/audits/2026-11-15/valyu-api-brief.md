# Valyu: контракт и границы

15.11.2026. `closes: LG-2026-11-15-01`. По брифу researcher
ses_e2095f6a2ffeKHlkJJuG5Io2lu; исследователь не смог сохранить файл из-за edit permissions.
API: /v1, snapshot документации не сохранён, лицензия документации не проверена.

- POST https://api.valyu.ai/v1/contents, headers Content-Type application/json,
  x-api-key из окружения. `urls`, response_length, extract_effort, summary,
  screenshot, max_age. Использован один URL, short, normal, summary=false,
  screenshot=false, max_age=0. Никаких API answers/deepresearch.
- results[].url/status/content — извлечённый markdown; summary не evidence.
  Exact URL сохраняется. Возможны усечение/преобразования markdown; нет гарантии
  полного текста или идентичности публикации по title.
- Документация заявляет Contents0.2credit/successURL, summary AI0.6credit,
  $10=1600credits: арифметически0.00125USD/обычныйURL. Это тариф источника,
  не измеренный счёт. Клиент резервирует0.01USD/попытку, ошибки не возвращают резерв.
- Search POST /v1/search имеет max_price на весь запрос; единицы неоднозначны,
  хотя reference приводит пример6.25 для10webresults. Search автоматически
  не включён. Автоматический поиск Perplexity/Exa также не добавлен.
- Live Contents в данной сессии вернул top-level total_cost_dollars, а не только
  total_deduction_dollars/cost, ожидаемые по брифу. Все распознаваемые поля
  проверяются; противоречие/невалидный тип блокирует страницу и дальнейшие расходы.
  Отсутствие поля означает неизвестный actual cost, но полный резерв, не бесплатно.
- Локальный cap не абсолютный cap биллинга. Для жёсткого предела нужен лимит
  аккаунта Valyu. Повторное использование ключа другим приложением здесь не учтено.

## Официальные ссылки, обращение15.11

https://docs.valyu.ai/
https://docs.valyu.ai/search/quickstart.md
https://docs.valyu.ai/guides/content-extraction.md
https://docs.valyu.ai/pricing.md
https://docs.valyu.ai/api-reference/endpoint/search.md
https://docs.valyu.ai/search/tips-and-tricks.md

Context7 /valyu-ai/docs не найден по сообщению researcher; SDK не устанавливался.
Точный фактический счёт smoke неизвестен, исходные поля цены в его receipt
не сохранились. Не переносить заявленный тариф в поле measured.
