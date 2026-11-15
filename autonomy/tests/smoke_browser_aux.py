"""Explicit two-call smoke. Run as a UTF-8 file, never via PowerShell stdin.

Default is offline; --execute requires owner permission. Stops on first error.
"""
import argparse
import datetime
import json
from pathlib import Path
import re
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from autonomy import assist, paths

CHECKS = [
    ('digest', 'Тестовые вымышленные данные, не результаты проекта. Источник: документ сообщает 7. План: проверить два файла. Измерено в вымышленном примере: обработаны 3 строки. Сожми без новых фактов, сохрани числа и статусы.'),
    ('scout', 'Найди официальную страницу лицензии sherpa-onnx на GitHub. Укажи URL, тип лицензии и короткую дословную цитату. Явно сообщи, выполнялся ли поиск; если поиска нет, сообщи об этом.'),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    assert all(any('\u0400' <= c <= '\u04ff' for c in text) and '?' not in text for _, text in CHECKS)
    if not args.execute:
        print(json.dumps({'status': 'dry_run', 'cyrillic_fixture_valid': True,
                          'max_calls': 2, 'browser_only': True}))
        return 0
    stamp = datetime.datetime.now().strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:6]
    out = paths.PROJECT_ROOT / 'docs/audits/2026-11-14' / f'chat2api-utf8-smoke-{stamp}.json'
    report = {'closes': 'LG-2026-11-14-01', 'browser_only': True,
              'created': datetime.datetime.now().astimezone().isoformat(), 'attempts': []}
    for mode, text in CHECKS:
        row = {'mode': mode, 'input': text}
        started = time.monotonic()
        try:
            row.update(status='response_received_unverified',
                       result=assist.run(mode, text, budget=0, browser_only=True, wait_seconds=60))
        except assist.providers.ProviderError as error:
            code = re.search(r'browser_gateway:(http_\d{3}|[a-z_]+)', str(error))
            row.update(status='blocked', error_kind=error.kind,
                       error_code=code.group(1) if code else 'unavailable')
        row['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report['attempts'].append(row)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(row, ensure_ascii=True), flush=True)
        if row['status'] == 'blocked':
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
