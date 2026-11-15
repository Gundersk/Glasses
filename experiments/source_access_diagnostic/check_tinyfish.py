"""One explicit read-only TinyFish batch, no search and no browser bypass."""
import datetime
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from autonomy import research, runner

URLS = ['https://ieeexplore.ieee.org/document/9053900',
        'https://ui.adsabs.harvard.edu/abs/2020spsi.conf..906R/abstract']


def main():
    if sys.argv[1:] != ['--execute']:
        print(json.dumps({'status': 'dry_run', 'urls': URLS, 'searches': 0}))
        return 0
    cfg = runner.load_config()
    cfg['research']['cache_dir'] = 'experiments/source_access_diagnostic/cache'
    report = {'closes': 'LG-2026-11-14-03', 'created': datetime.datetime.now().astimezone().isoformat(),
              'provider': 'tinyfish', 'requested_urls': URLS, 'searches': 0,
              'limitation': 'Provider outcome, not a diagnosis of site firewall or IP reputation'}
    try:
        result = research.TinyFish(cfg, research._PrintLog()).fetch(URLS, 'diagnose known public URL availability', fresh=True)
        report['pages'] = []
        for url in URLS:
            matches = [p for p in result.get('results', []) if research._valid_page(p, {url})]
            texts = [research._page_text(p) for p in matches]
            report['pages'].append({'url': url, 'content_received': bool(texts),
                'characters': sum(map(len, texts)),
                'sha256': hashlib.sha256('\n'.join(texts).encode('utf-8')).hexdigest() if texts else None})
        report['error_codes'] = research._safe_errors(result.get('errors', []))
    except Exception as error:
        report['status'] = 'transport_failed'
        report['error_type'] = type(error).__name__
    out = Path('docs/audits/2026-11-14/source-access-tinyfish.json')
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
