"""Explicit <=2 Contents calls. Key only from environment, never printed."""
import datetime
import hashlib
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from autonomy import valyu_reader

URLS = ['https://arxiv.org/html/1901.01342v2', 'https://ieeexplore.ieee.org/document/9053900']


def main():
    if sys.argv[1:] != ['--execute']:
        print(json.dumps({'status': 'dry_run', 'urls': URLS, 'max_calls': 2, 'reserve_usd': .02}))
        return 0
    stamp = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    scope = 'LG-2026-11-15-01-smoke-' + stamp + '-' + uuid.uuid4().hex[:6]
    report = {'closes': 'LG-2026-11-15-01', 'created': datetime.datetime.now().astimezone().isoformat(),
              'scope_id': scope, 'reserve_budget_usd': .02, 'max_calls': 2, 'attempts': [],
              'limitation': 'Technical diagnostic, not accepted literature evidence; reserve is not invoice'}
    out = Path('docs/audits/2026-11-15/valyu-smoke-' + stamp + '.json')
    for url in URLS:
        try:
            result = valyu_reader.read_page(url, scope_id=scope, budget_usd=.02, max_calls=2, timeout_s=40)
        except valyu_reader.ValyuUnavailable as error:
            report['attempts'].append({'url': url, 'status': 'not_called', 'error_code': error.code})
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            break
        row = dict(result['attempt'])
        page = result['page']
        if page:
            row.update(characters=len(page['content']), content_sha256=hashlib.sha256(page['content'].encode('utf-8')).hexdigest(),
                       head=page['content'][:400])
        report['attempts'].append(row)
        report['usage'] = valyu_reader.usage(scope)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(row, ensure_ascii=True), flush=True)
        if row.get('http_status') in (401, 402, 403, 429) or row.get('error_code') in ('transport_timeout', 'billing_conflict', 'unknown_cost'):
            break
    print('ARTIFACT', out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
