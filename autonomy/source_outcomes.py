"""Fail-closed validation of collected pages; availability is not scientific acceptance."""
import json
from pathlib import Path

from .source_selection import canonical_url

RESOURCE_ERRORS = frozenset({'bot_blocked', 'robots_denied', 'access_denied',
                             'not_found', 'http_403', 'http_404', 'http_410', 'gone', 'resource_unavailable'})


def inspect_document(doc):
    from .research import _valid_page
    if not isinstance(doc, dict) or not isinstance(doc.get('sources'), list) or len(doc['sources']) > 5:
        raise ValueError('invalid sources schema')
    pages = doc['sources']
    urls = []
    for page in pages:
        if (not isinstance(page, dict) or not canonical_url(page.get('url'))
                or not isinstance(page.get('content'), str)
                or len(page['content']) > (30000 if doc.get('schema_version') == 2 else 500000)
                or not _valid_page(page, {page.get('url')})):
            raise ValueError('invalid source page')
        urls.append(page['url'])
    if len(set(urls)) != len(urls):
        raise ValueError('duplicate source page')
    if 'schema_version' not in doc:
        if not pages or any(k in doc for k in ('collection_status', 'unavailable_urls', 'error_codes')):
            raise ValueError('invalid legacy collection')
        return {'collection_status': 'available', 'read_pages': len(pages),
                'unavailable_urls': [], 'error_codes': []}
    manifest = doc.get('selection_manifest')
    if (type(doc['schema_version']) is not int or doc['schema_version'] != 2
            or not isinstance(manifest, dict) or not isinstance(manifest.get('selected'), list)
            or not isinstance(doc.get('query'), str) or not 1 <= len(doc['query']) <= 500
            or not isinstance(doc.get('accessed'), str) or not 1 <= len(doc['accessed']) <= 40
            or type(doc.get('fresh_requested')) is not bool
            or type(doc.get('search_results_count')) is not int
            or not 0 <= doc['search_results_count'] <= 10000
            or type(doc.get('fetch_attempted')) is not bool):
        raise ValueError('invalid collection metadata')
    selected = manifest['selected']
    missing = doc.get('unavailable_urls')
    codes = doc.get('error_codes')
    if (len(selected) > 5 or any(not canonical_url(u) for u in selected)
            or len(set(selected)) != len(selected)
            or len({canonical_url(u) for u in selected}) != len(selected)
            or doc['search_results_count'] < len(selected)
            or doc['fetch_attempted'] != bool(selected)
            or not isinstance(missing, list) or not isinstance(codes, list)
            or len(codes) > 10 or any(not isinstance(c, str) for c in codes)
            or any(u not in selected for u in urls)
            or missing != [u for u in selected if u not in urls]
            or doc.get('collection_status') != ('available' if pages else 'unavailable')):
        raise ValueError('invalid collection manifest')
    if not selected:
        if pages or missing or codes != ['no_results'] or doc['search_results_count'] != 0:
            raise ValueError('invalid empty search manifest')
    elif any(c not in RESOURCE_ERRORS for c in codes) or len(codes) != len(missing):
        raise ValueError('fatal or unexplained source error')
    return {'collection_status': doc['collection_status'], 'read_pages': len(pages),
            'unavailable_urls': missing, 'error_codes': codes}


def validate_collection(card):
    from . import intake, paths, request_research as rr
    plan = rr.read_plan(card)
    policy = rr.policy(card)
    cap = policy['pages_per_query'] if policy else 2
    if type(cap) is not int or not 1 <= cap <= 3:
        raise ValueError('invalid page cap')
    queries = plan['queries']
    if not isinstance(queries, list) or not 1 <= len(queries) <= 6:
        raise ValueError('invalid authorized queries')
    base = intake.root(card['spec']['id'])
    root = paths.PROJECT_ROOT.resolve()
    total, unavailable, urls = 0, 0, []
    for i, query in enumerate(queries):
        fp = base / f'sources-{i}.md.json'
        expected = root / fp.relative_to(paths.PROJECT_ROOT)
        if fp.resolve() != expected or not fp.resolve().is_relative_to(root):
            raise ValueError('source path redirected')
        try:
            if fp.stat().st_size > 500000:
                raise ValueError('source document too large')
            doc = json.loads(fp.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('cannot read source document') from exc
        result = inspect_document(doc)
        if len(doc['sources']) > cap or (doc.get('schema_version') == 2 and
                (len(doc['selection_manifest']['selected']) > cap or doc['query'] != query)):
            raise ValueError('source query or page cap mismatch')
        total += result['read_pages']
        unavailable += result['collection_status'] == 'unavailable'
        urls.extend(result['unavailable_urls'])
    return {'pass': total > 0, 'read_pages': total, 'unavailable_queries': unavailable,
            'unavailable_urls': urls, 'limitation': 'collection not full scientific coverage'}
