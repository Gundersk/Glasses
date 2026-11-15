# Как устроена среда OpenCode

## Файлы

- `.opencode/opencode.json` — модель по умолчанию, права, MCP, компакция.
- `.opencode/agents/*.md` — роли и системные промпты.
- `.opencode/skills/*/SKILL.md` — подгружаемые инструкции (не занимают контекст, пока не нужны).
- `.opencode/commands/*.md` — слэш-команды.
- `AGENTS.md` — короткие правила, загружаются всегда.
- `PROJECT.md`, `ROADMAP.md`, `STATUS.md` — читаются по необходимости, не автоматически.

## Модели

| Агент | Модель | Роль |
|---|---|---|
| `assistant` | `deepseek/deepseek-v4.1-flash-1017#high` | дешёвый интерфейс по умолчанию |
| `mentor` | `openai/gpt-6.1-terra#high` | старший ментор, `mode: all` |
| `researcher` | `deepseek/deepseek-v4.1-flash-1017#high` | поиск |
| `digester` | `z-ai/glm-5.3-flash#low` | сжатие |
| `reviewer` | `openai/gpt-6.1-sol#high` | проверка |
| `implementer` | `anthropic/claude-sonnet-5.5#high` | код |
| `vision` | `google/gemini-3.6-flash#high` | видео/изображения |

Менять модель конкретного агента — в его Markdown-файле. Модель по умолчанию — в `.opencode/opencode.json`.

## Два режима работы

- **`assistant` (по умолчанию)** — дешёвая модель. Для вопросов, напоминаний, статуса, простого поиска. Может позвать `mentor` как субагента.
- **`mentor`** — старший ментор. Для архитектуры, кода, проверки, важных текстов. Может вызывать остальных субагентов.

Переключение:

- `/mentor <задача>` — перейти в режим ментора.
- `/assistant` — вернуться в дешёвый режим.
- `/models` — вручную выбрать модель для текущей сессии (обычно не нужно).

## Как менять модель вручную

- `/models` — выбрать модель для текущей сессии. Обычно не нужно.
- `.opencode/agents/<agent>.md`, поле `model` — постоянная модель конкретного агента.
- `.opencode/opencode.json`, поле `default_agent` — агент по умолчанию.
- Изменение конфига не переключает уже начатую сессию; для новых сессий оно применяется автоматически.

## Команды

- `/status` — обновить `STATUS.md`.
- `/research <вопрос>` — исследовательский бриф.
- `/experiment <название>` — план эксперимента.
- `/report <месяц>` — месячный отчёт.
- `/review <файл>` — критическая проверка.
- `/vision <файл>` — анализ изображения/кадров/видео.
- `/mentor <задача>` — переключиться на старшего ментора.
- `/assistant` — вернуться в дешёвый режим.
- `/roadmap-change <идея>` — предложить изменение дорожной карты.

## MCP

- `context7` — документация библиотек. Подключён, проверен.
- `arxiv` — можно добавить локально через `uvx arxiv-mcp-server`, если понадобятся статьи. Сейчас не подключён, чтобы не тратить контекст на лишние инструменты.
- `tavily` — можно добавить как второй поисковик, нужен ключ. По умолчанию не подключён: Exa уже работает.

Добавить MCP:

```powershell
opencode mcp add <name> --url <url>
opencode mcp add <name> -- npx -y <package>
opencode mcp list
```

## Права

- `mentor` может читать, писать, запускать shell, искать в интернете и вызывать субагентов.
- `researcher` не может редактировать файлы и запускать shell.
- `reviewer` не может редактировать файлы и запускать shell.
- `implementer` может редактировать и запускать команды, но не может вызывать субагентов.
- `vision` только читает изображения/видео.

## Экономия

- `subagent_depth: 1` — субагенты не плодят субагентов.
- `compaction.keep.tokens: 20000`, `buffer: 12%`.
- `tool_output.max_lines: 1200`, `max_bytes: 48000`.
- `AGENTS.md` короткий; подробности — в отдельных файлах.
- `websearch` — Exa; сырые страницы остаются в контексте дешёвого `researcher`.

## Проверка

В этом окружении CLI лежит по пути `%LOCALAPPDATA%\Programs\ai.opencode.desktop\resources\opencode-cli.exe`. Если команда `opencode` не находится в PATH, используйте полный путь или добавьте папку в PATH.

```powershell
opencode mcp list
opencode debug agents
opencode debug config
opencode auth list
```

Ожидаемо: `context7 connected`, агенты `mentor`, `researcher`, `digester`, `reviewer`, `implementer`, `vision`, OpenRouter `stored`.

## Если что-то не работает

1. `opencode mcp list` — подключён ли Context7.
2. `opencode debug config` — видит ли проектный конфиг.
3. `opencode debug agents` — загрузились ли агенты.
4. `opencode auth list` — есть ли OpenRouter.
5. Логи: `~/.local/share/opencode/log/opencode.log`.
6. Перезагрузка конфигурации: `/reload` в OpenCode.
