# e2e_audio: приёмка результатов экспериментов

Цель: сделать ложный PASS дорогим. Все скрипты по умолчанию отвечают FAIL; PASS - только при явных доказательствах.
Запуск из корня проекта, Python: `.venv\Scripts\python.exe` (переменная `PYTHONUTF8=1`).

## Слои

| Слой | Скрипт | Что доказывает |
|---|---|---|
| 1 | `validate_run.py` | структура и согласованность `metrics.json`, артефакты, пересчёт WAV и корреляции |
| 2 | `check_dom.py`, `check_screenshot.py` | страница реально отдаёт меняющийся русский текст; скриншот не пустой |
| 3 | vision-review (делает агент `vision`, файл `vision_review.json`) | человекочитаемая оценка скриншота |
| - | `gate.py` | сводит слои в `run_verdict.json`, код 0 = PASS |

## Команды

```powershell
$env:PYTHONUTF8="1"
$py = ".venv\Scripts\python.exe"
$run = "experiments\e2e_audio\runs\<run_id>"

# слой 1
& $py experiments\e2e_audio\validate_run.py --run $run [--kind auto|streaming|e2e] [--min-snr 10] [--allow-missing-vision] [--allow-unverified-source]

# слой 2 (сервер должен быть запущен!)
& $py experiments\e2e_audio\check_dom.py --url http://127.0.0.1:8765/ --samples 8 --interval 0.5 --out $run\dom_checks.json
& $py experiments\e2e_audio\check_screenshot.py --path $run\artifacts\screenshot.png --out $run\screenshot_checks.json

# сводный вердикт
& $py experiments\e2e_audio\gate.py --run $run --dom $run\dom_checks.json --vision-review $run\vision_review.json

# самотест приёмки (34 кейса, ~25 с на этой машине)
& $py experiments\e2e_audio\selftest_validator.py
```

## Контракт прогона

Каждый прогон: `experiments/e2e_audio/runs/<run_id>/` с файлами `metrics.json`, `artifacts/`, `log.txt`;
`verdict.json` создаёт валидатор, `run_verdict.json` - gate. `metrics.run_id` обязан совпадать с именем папки.

```json
{
  "kind": "streaming" | "e2e",
  "run_id": "...", "created": "ISO8601", "simulated": false,
  "engine": "sherpa" | "vosk" | "...",
  "source": {"type": "file" | "loopback", "path": "...", "duration_s": 0.0},
  "partial_count": 0, "final_count": 0, "first_partial_ms": 0.0,
  "finals":   [{"text": "...", "t_ms": 0.0, "source_end_ms": 0.0}],
  "partials": [{"text": "...", "t_ms": 0.0}],
  "audio": {"recording_path": "...", "snr_db": 0.0, "corr_peak": 0.0, "lag_ms": 0.0},
  "timing": {"p50_ms": 0.0, "p95_ms": 0.0}
}
```

- `audio.*` обязателен для `kind=e2e`; для `kind=streaming` обязательны `artifacts/screenshot.png` и `artifacts/page.html`.
- `recording_path` и `source.path`: абсолютные или относительные (ищутся в `run/`, `run/artifacts/`, cwd, папке скрипта, корне проекта).
- Договорённости, на которые опирается валидатор: счётчики равны длинам списков; `first_partial_ms` равен `min(partials.t_ms)` (допуск 5 мс); `t_ms` в одной шкале времени прогона, не больше `duration_s*1000 + 30000`; `source_end_ms` не больше `duration_s*1000 + 1000`.
- Числа должны быть конечными (NaN/inf = ошибка типа); bool не считается числом.

## Правила слоя 1 (кратко)

`simulated` строго `false`; `partial_count > 0`, `final_count >= 1`; финалы непустые, с кириллицей, различны
(при `final_count >= 2` уникальных >= `max(2, final_count-1)`; при `final_count == 1` достаточно `unique == 1`), суммарно >= 10 символов; partial-ов с разным текстом >= 2;
заглушки (`lorem`, `ipsum`, `test`, `example`, `todo`, `placeholder` как отдельные латинские слова, и `...`) запрещены;
тайминги неубывают и правдоподобны; для e2e пересчитываются пик (> -50 dBFS), длительность записи (> 5 с),
нормированная корреляция и лаг по `source.path` (расхождение с заявленным: > 0.15 или > 50 мс = FAIL); скриншот проверяется `check_screenshot`;
`log.txt` непустой и без `Traceback`.

## Как читать verdict.json

`{"layer":1, "run_id":..., "kind":..., "pass":bool, "checks":[{"name","ok","expected","actual","detail"}], ...}`.
`pass=true` только если **все** `checks[].ok == true`. Для диагноза ищите проверки с `ok:false`; имя проверки - причина
(`missing_field:<поле>`, `bad_type:<поле>`, `simulated_is_false`, `partial_count_gt_0`, `snr_db_min`, ...).
`run_verdict.json` (gate): `layers.<имя>.status` = `pass|fail|missing|unreadable`, `failed_layers` - список проваленных слоёв.

Gate: слой 1 пересчитывается заново (старому `verdict.json` не доверяем). Для `kind=streaming` автоматически требуются DOM,
скриншот и vision-review (отключается `--allow-missing-dom` / `--allow-missing-vision`); для любого kind - `--require-dom/-screenshot/-vision`.
`vision_review.json` принимается только при `"pass": true`; если есть `run_id` или `screenshot_sha256`, они сверяются.

## Что делать при FAIL

1. Откройте `verdict.json` / `run_verdict.json`, найдите первую проваленную проверку и прочитайте `detail`.
2. Не правьте `metrics.json` вручную, чтобы пройти проверку. Исправьте причину (скрипт записи, формат WAV, устройство, движок) и повторите прогон с новым `run_id`.
3. `missing_field:*` / `bad_type:*` - ошибка скрипта, пишущего метрики. `partial_count_gt_0` с пустыми финалами - см. историю с float32-WAV: проверьте формат входа (soundfile/ffmpeg) и что движок получил звук.
4. `snr_db_min` / `corr_*` / `recording_peak_dbfs` - проблема акустики: громкость, устройство по умолчанию, шумоподавление/AGC; сначала `selftest_loopback.py`.
5. `connection_refused` в DOM-слое - сервер не запущен на момент проверки.
6. Если проверка кажется ошибочной - не отключайте её; опишите случай в `docs/roadmap-changes.md` или ADR и согласуйте с ментором.

## Чего приёмка НЕ проверяет

См. раздел в ответе исполнителя и ниже; коротко: правильность распознанного текста (WER), заявленный `snr_db`,
подлинность исходного аудио, то, что движок реально использован, JS-рендеринг страницы (DOM-слой читает серверный HTML),
содержательность vision-review, а также умышленную подделку со стороны того, кто может править и валидатор.
Фикстуры в `fixtures/_generated/` синтетические и никогда не являются результатами экспериментов.
