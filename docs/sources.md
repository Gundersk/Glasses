# Реестр источников

Правило: каждый источник — с датой обращения, версией и лицензией. Если лицензия не проверена, писать «не проверена». Не смешивать источник и собственный результат.

## Шаблон

### Chat2API, 14.11.2026 (частичный бриф researcher)

| ID | Источник | Что подтверждает / проверяем | Дата обращения | Версия | Лицензия | Статус |
|---|---|---|---|---|---|---|
| S074 | https://github.com/lanqian528/chat2api | кандидат ChatGPT Web → OpenAI-compatible; не идентификация локального сервиса | 2026-11-14 | commit не зафиксирован | MIT по брифу researcher; локальная установка неизвестна | по брифу; не аудит локального upstream |
| S075 | https://github.com/xiaoY233/Chat2API | кандидат мультипровайдерного шлюза по набору моделей | 2026-11-14 | не установлена | не проверена | кандидат, идентичность локальному не доказана |
| S076 | https://opencode.ai/docs/providers ; https://opencode.ai/docs/config | V2 provider metadata/settings и проектные overrides | 2026-11-14 | V2, snapshot не сохранён | документация: не проверена | по брифу researcher; конфигурация локально прочитана отдельно |
| S077 | локальный http://127.0.0.1:8080/v1/models | HTTP200 и 23 объявленных ID; не качество/наличие поиска | 2026-11-14 | версия gateway неизвестна | upstream/веса/данные отдельно не установлены | GET выполнен; безопасный snapshot `docs/audits/2026-11-14/chat2api-catalog.json` |
| S078 | https://exa.ai/pricing ; https://exa.ai/products/contents | заявленные назначения/цена Contents, не реальный счёт MCP-проверки | 2026-11-14 | snapshot не сохранён | документация: не проверена | по брифу researcher, `fetch-alternatives.md` |
| S079 | https://openrouter.ai/docs/guides/features/plugins/web-search ; https://openrouter.ai/docs/guides/features/server-tools/web-search | native/Exa web search, citations и дополнительная стоимость; не полный первичный текст | 2026-11-14 | текущие страницы, snapshot не сохранён | документация: не проверена | по брифу researcher; точная цена Perplexity-модели здесь не установлена |
| S080 | https://ieeexplore.ieee.org/document/9053900 ; https://ui.adsabs.harvard.edu/abs/2020spsi.conf..906R/abstract | только доступность reader: TinyFish bot_blocked; Exa без пригодного текста | 2026-11-14 | версии страниц не установлены | права статей/контента не проверены | не прочитанные научные источники; диагностические результаты `source-access-tinyfish.json`, `fetch-alternatives.md` |

Бриф и ограничения: `docs/audits/2026-11-14/chat2api-research.md`.

| ID | Источник | Что подтверждает | Дата обращения | Версия | Лицензия | Статус |
|---|---|---|---|---|---|---|
| S001 | ... | ... | ... | ... | ... | проверено / не проверено |

## Кандидаты из аналитической сводки

| ID | Источник | Что проверяем | Дата | Версия | Лицензия | Статус |
|---|---|---|---|---|---|---|
| S001 | https://github.com/k2-fsa/sherpa-onnx | потоковый ASR, мобильные платформы | 2026-11-06 | v2.0.1 (2026-10-26) | Apache-2.0 по метаданным GitHub; проверить LICENSE | частично проверено |
| S002 | https://github.com/QuentinFuxa/WhisperLiveKit | локальный потоковый ASR-сервер, WebSocket, диаризация | — | — | Apache-2.0; модели отдельно | не проверено |
| S003 | https://github.com/SYSTRAN/faster-whisper | оптимизированный Whisper, CPU int8 | — | — | MIT | не проверено |
| S004 | https://github.com/ggml-org/whisper.cpp | локальный Whisper, on-device | — | — | MIT | не проверено |
| S005 | https://github.com/m-bain/whisperX | выравнивание и диаризация записей | — | — | BSD-2-Clause | не проверено |
| S006 | https://github.com/pyannote/pyannote-audio | диаризация | — | — | MIT (библиотека); веса CC BY 4.0 | не проверено |
| S007 | https://huggingface.co/pyannote/speaker-diarization-community-1 | веса диаризации | — | — | CC BY 4.0; доступ по условиям | не проверено |
| S008 | https://github.com/Junhua-Liao/Light-ASD | ASD | — | — | исследовательская лицензия | не проверено |
| S009 | https://github.com/Junhua-Liao/LR-ASD | ASD | — | — | исследовательская лицензия | не проверено |
| S010 | https://github.com/google-ai-edge/mediapipe | лица и видеопризнаки | — | — | Apache-2.0 | не проверено |
| S011 | https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb | голосовые embeddings | — | — | проверять веса | не проверено |
| S012 | https://github.com/brilliantlabsAR/brilliant_sdk | SDK очков, эмулятор | — | — | BSD-3-Clause | не проверено |
| S013 | https://github.com/Mentra-Community/MentraOS | открытая платформа очков | — | — | Apache-2.0 на 25.10.2026 (проверять) | не проверено |
| S014 | https://sites.research.google/gr/ava/download/ | датасет ASD | — | — | условия оригинальных видео | не проверено |
| S015 | https://github.com/joonson/voxconverse | диаризация, RTTM | — | — | проверять | не проверено |
| S016 | https://github.com/QwenLM/Qwen3-TTS | синтетический TTS | — | — | Apache-2.0 | не проверено |
| S017 | Служебный бриф researcher, передан в запросе 06.11.2026; первичные URL не переданы | предварительные сведения об аналогах, ASR, диаризации и ASD; не первоисточник | 2026-11-06 — дата получения брифа, не дата обращения к первоисточникам | не указана | не установлена | требует восстановления точных ссылок и проверки перед внешним цитированием |
| S018 | https://huggingface.co/datasets/google/fleurs | живой русский ASR test-корпус (ru_ru/test), аудио+эталон; использован для baseline WER/задержки 09.11 | 2026-11-09 | parquet-data/ru_ru/test-00000-of-00001.parquet (snapshot 70bb2e84) | CC-BY 4.0 (FLEURS); проверить карточку | проверено: доступ без gate, 50 клипов скачаны |

### Аналоги автономных систем (12.11.2026)

Проверены по GitHub API; устанавливался и запускался только Argus. Звёзды —
на дату обращения, это не оценка качества.

| ID | Источник | Что рассматривали | Дата | Версия | Лицензия | Статус |
|---|---|---|---|---|---|---|
| S019 | https://github.com/microsoft/ArgusAgent | роли Manager/Planner/Engineer/Reviewer, Skills/Wiki, bounded-миссии | 2026-11-12 | 0.1.8 из main (README заявляет 0.1.6) | MIT | локальный пилот: OpenCode Reviewer несовместим, ограниченная миссия на Pi прошла; пилот закрыт владельцем, см. `../ArgusPilot/PILOT_NOTES.md` |
| S020 | https://github.com/langchain-ai/deepagents | субагенты, файловая память, оркестрация | 2026-11-12 | не устанавливалась | MIT | не проверено |
| S021 | https://github.com/All-Hands-AI/OpenHands | автономный coding agent, песочница | 2026-11-12 | не устанавливалась | MIT | не проверено |
| S022 | https://github.com/SakanaAI/AI-Scientist-v2 и https://raw.githubusercontent.com/SakanaAI/AI-Scientist-v2/main/LICENSE | автономный ML-исследовательский цикл; README: Linux/NVIDIA/CUDA/PyTorch | 2026-11-12 | main; LICENSE v1.0 December 2025 | собственная AI Scientist Source Code License с ограничениями, не MIT | README проверен researcher; LICENSE сохранён с хэшем в `docs/audits/2026-11-12/`; не устанавливалась/не запускалась |
| S023 | https://github.com/temporalio/temporal | durable workflow, восстановление после сбоев | 2026-11-12 | не устанавливалась | MIT | не проверено |
| S024 | soothe (URL не зафиксирован в брифе) | лёгкий автономный цикл | 2026-11-12 | не устанавливалась | MIT по брифу | не проверено: ссылку восстановить перед цитированием |


### Литературный обзор (12.11.2026)

Собрано по запросу ментора для `docs/literature-review-2026-11.md`. Дата обращения
у всех — 2026-11-12. «Не проверено» в столбце статуса означает: страница/карточка
прочитана, но лицензия или число не сверены по первоисточнику.

Бенчмарк и метрики

| ID | Источник | Что подтверждает | Версия | Лицензия | Статус |
|---|---|---|---|---|---|
| S025 | https://www.chimechallenge.org/challenges/chime8/task3/index | CHiME-8 Task 3 MMCSG: разговор двух человек на очках Aria, speaker-attributed транскрипция потоково | CHiME-8 (2024) | материалы сайта | проверено лично |
| S026 | https://www.chimechallenge.org/challenges/chime8/task3/rules | multitalker WER с SELF/OTHER, категории задержки 150/350/1000 мс, задержка = алгоритмическая и emission, а не wall-clock; `facebookresearch/MMCSG` | CHiME-8 (2024) | материалы сайта | проверено лично |
| S027 | https://www.chimechallenge.org/challenges/chime8/task2/index | CHiME-8 Task 2 NOTSOFAR: ранжирование по tcpWER (MeetEval) как стандарт speaker-attributed оценки | CHiME-8 (2024) | материалы сайта | проверено лично |
| S028 | Žmolíková et al., «The CHiME-8 MMCSG Challenge», CHiME Workshop 2024, isca-archive.org/chime_2024/zmolikova24_chime.pdf | baseline-числа multitalker WER для MMCSG (eval: 0.62 с → SELF 14.1, OTHER 21.7, ATTR 2.3/2.1) | 2024 | открытый PDF | прочитан по пересказу, число не перепроверял |
| S029 | Kanda et al., «Streaming Speaker-Attributed ASR with Token-Level Speaker Embeddings», Interspeech 2022, arXiv:2203.16685 | потоковый SA-ASR (t-SOT + t-vector), низкая задержка | 2022 | arXiv | прочитан по пересказу |
| S030 | «VibeVoice-ASR-Streaming Technical Report», Microsoft Research, arXiv:2609.02812 | end-to-end потоковый SA-ASR одной моделью; заявленная задержка атрибуции 2.00 с; сравнение с Azure 8.21 с и Google STT 9.12 с | 2026 | arXiv, не рецензирован | заявлено авторами |
| S049 | Raj et al., «On Speaker Attribution with SURT», arXiv:2401.15676 | потоковая атрибуция без инвентаря говорящих, AMI | 2024 | arXiv | прочитан по пересказу |
| S031 | https://arxiv.org/html/2611.12246v1 | Table 1, DH3: Nemotron-3 DER **12.73 / 13.18 / 13.55 %** при 30.4 / 1.04 / 0.32 с; Sortformer-v2.1 **19.09 / 19.60 / 19.85 %** — другая строка; DH3 collar 0 с, overlap scored | v1 Table 1; обращение 13.11.2026 | веса Nemotron-3 OpenMDW-1.1 по статье, не лицензия всех зависимостей | researcher сверил таблицу; исправляет смешение моделей; наши прогоны отсутствуют |
| S032 | https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1 | ≤4 говорящих; карточка DH3 full **19.49 / 20.21 %** при 30.4 / 1.04 с, не числа Table 1 S031; причина расхождения DH3 не установлена | v2.1, обращение 13.11.2026 | `nvidia-open-model-license` для весов; код/зависимости отдельно | researcher; CPU-RTF на нашем ПК не измерялся |
| S033 | https://huggingface.co/pyannote/speaker-diarization-3.1 | офлайн-DER: AMI IHM 18.8, VoxConverse 11.3, DIHARD3 21.7 | 3.1 | MIT, веса gated | не проверено |
| S034 | https://github.com/juanmc2005/diart | онлайн-диаризация на pyannote: RTF 0.33, шаг 250–500 мс, 20-ядерный Xeon | — | MIT | не проверено |
| S035 | Liang, Shao, Li, 2023, arXiv:2309.13916 | FS-EEND: DER 5.1/11.1/15.8 %, RTF 0.026 при латентности 1 с | 2023 | не проверено | прочитан по пересказу |

Русский ASR и данные

| ID | Источник | Что подтверждает | Версия | Лицензия | Статус |
|---|---|---|---|---|---|
| S036 | https://github.com/salute-developers/GigaAM/blob/main/evaluation.md ; https://github.com/k2-fsa/sherpa-onnx/issues/2852 | WER-таблицы — прежний пересказ; точная таблица для «среднее 8.3 по 10 наборам» не установлена. Мейнтейнер 03.03.2026: «it is a non-streaming model. You should use an offline recognizer, not online.» о v3_e2e_rnnt; simulated streaming не native streaming | issue #2852, обращение 13.11.2026 | MIT по прежней записи; новые зависимости отдельно | streaming-статус проверен researcher; средние/версии WER требуют перепроверки, не сопоставимы с нашими |
| S037 | https://huggingface.co/t-tech/T-one ; https://raw.githubusercontent.com/voicekit-team/T-one/main/LICENSE ; https://huggingface.co/t-tech/T-one/raw/main/vocab.json | T-one ~71M CTC, чанки 300 мс; 33 кириллические буквы + пробел + pad/blank, без латиницы/цифр/пунктуации. WER CV19 5.32 / call-center 8.63 / OpenSTT 20.27 остаётся пересказом | HF sha prefix 106f3b0b; обращение 13.11.2026 | код Apache-2.0 по LICENSE; веса apache-2.0 по metadata HF; отдельные bundled artifacts не проверены | лицензия/алфавит проверены researcher; WER и CPU у нас не измерены; сторонние CPU-числа — S067 |
| S038 | https://huggingface.co/alphacep/vosk-model-streaming-ru → https://alphacephei.com/vosk/models | Vosk streaming ru 0.56: WER 11.3 на Common Voice ru | 0.56 | Apache-2.0 по общей странице моделей | частично проверено |
| S039 | https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-small-ru-vosk-2025-08-16 | наша модель — конвертация Vosk streaming ru (WER 11.3 унаследован) | 2025-08-16 | наследует Vosk | не проверено |
| S018 | https://huggingface.co/datasets/google/fleurs | FLEURS ru: 50 клипов для нашего baseline | snapshot 70bb2e84 | CC-BY 4.0 | проверено ранее |

Нормативы и восприятие

| ID | Источник | Что подтверждает | Лицензия | Статус |
|---|---|---|---|---|
| S041 | Kafle, Huenerfauth, ASSETS 2017, doi:10.1145/3132525.3132542 | WER слабо предсказывает понятность субтитров для DHH; предложена метрика ACE | ACM, платный (абстракт) | прочитан абстракт |
| S042 | https://www.w3.org/TR/saur/ | цели синхронизации живых субтитров: разброс 3–10 с, рекомендация 5 с | W3C Doc License | прочитан по пересказу |
| S043 | https://www.ecfr.gov/current/title-47/chapter-I/subchapter-C/part-79/subpart-A/section-79.1 и https://www.w3.org/WAI/WCAG22/Understanding/captions-live.html | FCC и WCAG требуют живые субтитры, но числовых порогов не задают | гос. документ / W3C | прочитан по пересказу |

Рынок очков с субтитрами

| ID | Источник | Что подтверждает | Статус |
|---|---|---|---|
| S044 | https://xrai.glass/ar2/ и https://knowledge.xrai.glass/speaker-identifcation | XRAI AR2: метки говорящих в облачном движке, имя через «Hey XRAI, my name is…»; русского в офлайн-модели нет | проверено по сайту вендора |
| S045 | https://aircaps.com/ | AirCaps: заявлено 300 мс и «speaker identification» без методики | заявление вендора |
| S046 | https://www.evenrealities.com/translation-glasses и https://support.evenrealities.com/hc/en-us/articles/13755354799247-Language-Support | Even G2: русский в Translate/Conversate, нужен интернет, меток говорящих в документации нет | проверено по сайту вендора |
| S047 | https://www.meta.com/help/ai-glasses/23879220601763496/ | Meta Ray-Ban Display: субтитры только на английском | проверено по сайту вендора |
| S048 | https://brilliant.xyz/products/halo | Brilliant Labs Halo: ассистент и перевод, диаризации нет | проверено по сайту вендора |
| S050 | https://charly.sensor-tech.ru/ | «Чарли» (Сенсор-Тех): стационарное устройство речь→текст, не очки; ПО 210 000 ₽ | проверено по сайту вендора |

Восприятие задержки субтитров

| ID | Источник | Что подтверждает | Статус |
|---|---|---|---|
| S051 | Burnham et al., «Why Captions Have To Be On Time», AVSP 1998, isca-archive.org/avsp_1998/burnham98c_avsp.pdf | задержка 1–4 с снижает понятность; n=2 | малая выборка, прочитан по пересказу |
| S052 | Maruyama et al., Eurospeech 1999, doi:10.21437/Eurospeech.1999-148 | допустимый сдвиг субтитров ~1 с для новостей | малая выборка, прочитан по пересказу |

### Отклонённые источники данных (09.11.2026)
- `bond005/sberdevices_golos_100h_opus`, `bond005/golos` — HF API вернул **401** (gated/недоступно без токена).
- `mozilla-foundation/common_voice_13_0` — datasets-server вернул **500 / empty dataset**; доступ без токена не подтверждён.
  Оба варианта не использованы; для baseline взят публичный FLEURS (S018). Если появится токен HF, вопрос можно пересмотреть.


## Аудит автономности и инструментов (12.11.2026, LG-2026-11-12-01)

Внешние источники ниже не являются результатами наших экспериментов. Для страниц,
проверенных researcher, это библиографическая проверка; локальный запуск не заявлен.
Копии нескольких первичных документов и даты/хэши — `docs/audits/2026-11-12/`.

| ID | URL | Что подтверждает / ограничение | Версия и лицензия / условия | Проверка |
|---|---|---|---|---|
| S053 | https://docs.langchain.com/oss/python/langgraph/checkpointers ; https://docs.langchain.com/oss/python/langgraph/interrupts ; https://github.com/langchain-ai/langgraph | persistence, pending writes, human interrupts; не гарантируют истинность измерений или идемпотентность произвольной команды | документация на 12.11.2026; LangGraph MIT; не устанавливался | прочитано researcher; стоимость миграции/Windows-прогон не измерялись |
| S054 | https://openrouter.ai/api/v1/models | текущие model IDs, prices, output caps; есть тарифные overrides | снимок `openrouter-models.json` с UTC/хэшем; API/модели по условиям провайдера, не лицензия весов | GET выполнен, сохранены 4 используемых модели; это не рейтинг качества |
| S055 | https://openrouter.ai/docs/guides/best-practices/reasoning-tokens | max_tokens включает reasoning; пустой final content не отменяет оплату | текущая документация, 12.11.2026 | Context7 `/websites/openrouter_ai`, не замер моделей |
| S056 | https://openrouter.ai/docs/api_reference/streaming | SSE final usage chunk, finish_reason, DONE | текущая документация, 12.11.2026 | Context7; наш клиент проверялся моками |
| S057 | https://opencode.ai/docs/config ; https://opencode.ai/docs/agents | V2: конфиги/приоритет, agents model#variant, steps/permissions | онлайн-документация на 12.11.2026 | страницы открыты; Context7 V2; root JSON и локальные профили проверены; итоговые запросы всех ролей не запускались |
| S058 | https://huggingface.co/datasets/mexus/ru-book-mix-10h ; https://huggingface.co/datasets/mexus/ru-book-mix-10h/raw/main/README.md ; https://huggingface.co/api/datasets/its5Q/biggest-ru-book | русский синтетический audiobook RTTM; схема flac/rttm/json без транскриптов, RTTM ortho `<NA>`: WER не посчитать как есть. Рекомендация карточки не обучать связана с утечкой 53 голосов, не общим запретом CC-BY | main, lastModified 16.05.2026; CC-BY-4.0 по карточке; у upstream its5Q/biggest-ru-book license не указана, права звука/шума не решены | проверка researcher 13.11 + GET карточки 12.11; шарды не скачивались, вывод по схеме, не аудит всех файлов |
| S059 | https://huggingface.co/datasets/davidai-labs/DAI-ASR-I18N | по карточке researcher: естественные двухспикерные записи, русский входит, поканальная атрибуция; наличие готового RTTM не подтверждено | license other/DUA по карточке; scoring code MIT отдельно | researcher прочитал; независимый raw GET в этой сессии вернул 401, доступ/права не считать решёнными |
| S060 | https://huggingface.co/datasets/artem-tish/veche-bench | карточка существует, видна текстовая схема summaries/action_items; пригодность для ASR/диаризации не подтверждена | версия/лицензия не установлены | частично проверено researcher; не кандидат в замер без дальнейшей проверки |
| S061 | https://www.crossref.org/documentation/retrieve-metadata/rest-api/ | DOI/метаданные по HTTP без отдельного MCP; метаданные не заменяют полный текст/прочтение статьи | REST API; условия контента/абстрактов отдельно | официальная документация прочитана researcher; интеграция не реализована |
| S062 | https://www.zotero.org/support/dev/web_api/v3/local_api | локальная библиотека по API, чтение без аутентификации; не выставлять порт наружу | API v3; условия приложения/плагинов отдельно | документация прочитана researcher; наличие Zotero/настройка на ПК не проверялись |
| S063 | https://github.com/github/github-mcp-server | официальный MCP для репозиториев/issues/PR; есть write-инструменты, нужен read-only/minimal scope | main; MIT по репозиторию | прочитано researcher; не установлен, новых токенов не выдавали |
| S064 | https://github.com/oraios/serena ; https://raw.githubusercontent.com/oraios/serena/main/LICENSE | LSP/символьная навигация; лицензии по компонентам | Serena v2 GPL-3.0-or-later; SolidLSP MIT; общий LICENSE — overview, не «неизвестная лицензия» | прямой LICENSE сохранён; исправляет неполный бриф с ярлыком GitHub «Other»; не установлена |
| S065 | https://github.com/microsoft/playwright-mcp ; https://raw.githubusercontent.com/microsoft/playwright-mcp/main/LICENSE | UI MCP как альтернатива, частично дублирует имеющийся browser/screenshot | main; Apache-2.0 по сохранённому LICENSE | README researcher + прямой LICENSE; новый сервер не устанавливался |

Дата обращения ко всем S053–S065: **12.11.2026**. Версия `main` не является
закреплённым релизом; перед установкой фиксировать commit/version и зависимости.
OpenAlex (редирект), Semantic Scholar и arXiv API в этом проходе полноценно не
проверены; это не основание объявлять их непригодными или несуществующими.

Решения/границы — `docs/autonomy-audit-2026-11.md`. Локальные тесты протоколов
команд — `docs/audits/2026-11-12/offline-tests.json`: это проверка нашей реализации
по мокам и синтетическому subprocess, а не подтверждение внешних заявлений
провайдеров, качества моделей или новых научных измерений.

## Сверка двух новых ревью (13.11.2026, LG-2026-11-13-01)

Сводные записи с происхождением: `docs/audits/2026-11-13/{asr-amd,diarization}-sources.json`.
Это брифы проверок, не полный архив первичных страниц и не наши измерения.

| ID | URL | Что подтверждает / ограничение | Версия, лицензия и дата обращения | Статус |
|---|---|---|---|---|
| S066 | https://voicelab.ai/evaluating-nemotron-3-diarization-on-spokesbiz-and-diabiz | SpokesBiz, польский: Nemotron-3 DER 22.5 %, WDER 4.8 %, match слова ≥50 % overlap. Разность метрик не доказывает, что DER — границы/тишина | пост 12.10.2026, обращение 13.11; лицензия поста/корпусов, collar и точное подмножество не подтверждены | researcher открыл оригинал; не прямое сравнение с русским чтением |
| S067 | https://dev.to/meshoklv/benchmarking-russian-speech-recognition-on-cpu-t-one-gigaam-v3-and-cloud-models-3cgo | T-one 99–123 мс на 300-мс чанк; p95 104–175; лаг фразы 1.05–1.09 с при пороге тишины 0.6 с. Это сторонний замер, не вендор | 23.10.2026, замеры 09.2026; 8 vCPU Xeon E5-2695 v2, ORT 1 поток, 8 кГц, 4 клипа 53–285 с; обращение 13.11; права статьи не проверены | researcher; не наш CPU, не микрофон→экран |
| S068 | https://raw.githubusercontent.com/fgnt/meeteval/main/README.md ; https://raw.githubusercontent.com/fgnt/meeteval/main/LICENSE | greedy_dicpwer — жадное приближение DI-cpWER; DER через md-eval с явным collar. WDER не подтверждён как готовый scorer; pooling/дефолты не проверены в этом проходе | main, commit не закреплён, обращение 13.11; **MIT** кода по прямому LICENSE, внешние scorers/данные отдельно | README researcher; LICENSE открыт основным агентом, исправляет ошибочное Apache-2.0 в брифе |
| S069 | https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-6.4.4/docs/compatibility/compatibilityrad/windows/windows_compatibility.html ; https://www.amd.com/en/resources/support-articles/release-notes/RN-AMDGPU-LINUX-ROCM-6-4-4.html | RX 7700 XT есть в Linux 6.4.4; Windows PyTorch matrix 6.4.4 даёт gfx1201/gfx1200/gfx1100, не gfx1101. Это не подтверждение Windows preview для нашего GPU | ROCm 6.4.4, Windows PyTorch 2.8/Python 3.12; обращение 13.11; SDK/компоненты по отдельным условиям AMD | researcher; более поздняя матрица требует отдельной проверки, реальный GPU-инференс не запускался |
| S070 | https://opencode.ai/docs/commands | `.opencode/commands/*.md`, frontmatter agent/subagent, `$ARGUMENTS`; subagent false — текущая сессия | V2, обращение 13.11; документация, не лицензия моделей | прямая страница + Context7 V2 в предыдущей части сессии; команда добавлена, UI-вызов не проверен |
| S071 | https://opencode.ai/docs/providers ; https://opencode.ai/docs/models | ChatGPT-вход у openai, подписочная цена; context-caps input 500k для 6.1+, 272k ранее; варианты и body overrides | V2, обращение 13.11.2026; документация/тариф, не лицензия модели | открыто напрямую; локальный каталог 2.2.7 подтверждает метаданные, не предельную генерацию |
| S072 | https://opencode.ai/docs/compaction ; https://opencode.ai/docs/config ; https://opencode.ai/docs/instructions | auto/keep.tokens/процентный buffer, summary/native, warming, durable instruction entries | V2 на дату 13.11.2026; права документации отдельно, код не заимствован | прямые страницы; Context7 вернул более старые дефолты V2, применены текущая страница и локальный конфиг |
| S073 | https://opencode.ai/docs/api ; локальный opencode api get /openapi.json | session.create/generate, instruction entries, ProviderRequestError/retryAfterMs; usage/limits — Go/Console, не Plus | OpenCode 2.2.7, обращение 13.11.2026; экспериментальный контракт, условия подписки отдельно | каталог и CRUD сессии/инструкций без generate/prompt проверены; настоящий quota/error shape ещё не проверен |

Balalaika, ASD-числа/CAST-ASD, детали pyannote 4.x и дефолты MeetEval из ревью
**не приняты как проверенные факты**: требуют отдельного ограниченного прохода
перед выбором данных/стека. Ни исходное ревью, ни его самопроверка не являются
первоисточником. Отсутствие проверки не означает отсутствия технологии.

## Что фиксировать для каждого

- точный URL и, если есть, DOI/arXiv;
- дата обращения;
- версия/коммит/релиз;
- лицензия кода, весов и данных — отдельно;
- что именно подтверждает источник;
- где он противоречит другому источнику.

## Запрещено

- Указывать источник, который не открывался.
- Писать «по данным исследования» без ссылки.
- Переносить числа из статьи в свой отчёт как «наш результат».
- Скрывать некоммерческие ограничения лицензии.
