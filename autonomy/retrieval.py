"""Bounded query/reader routing. No URL rewrites, hidden queries or retries."""
import re

import requests

from .source_selection import canonical_url, select_sources


def _service_error(error):
    if isinstance(error, requests.exceptions.JSONDecodeError):
        return None
    if isinstance(error, requests.Timeout):
        return 'transport_timeout'
    if isinstance(error, requests.ConnectionError):
        return 'transport_error'
    if isinstance(error, requests.HTTPError):
        status = getattr(error.response, 'status_code', None)
        return f'http_{status}' if type(status) is int and status in {401, 403, 429, 500, 502, 503, 504} else None
    if isinstance(error, requests.RequestException):
        return None
    match = re.search(r'HTTP (401|403|429|5\d\d)\b', str(error))
    return 'http_' + match.group(1) if match else None


def _fallback_code(code):
    from .source_outcomes import RESOURCE_ERRORS
    return (code in RESOURCE_ERRORS | {'quota_exceeded', 'rate_limited', 'auth', 'network_error',
            'transport_error', 'transport_timeout', 'http_401', 'http_403', 'http_429'}
            or isinstance(code, str) and re.fullmatch(r'http_5\d\d', code) is not None)


def _local_candidates(index, query):
    terms = set(re.findall(r'\w{3,}', query.casefold()))
    rows = []
    for page in index.values():
        text = page['content'][:3000]
        words = set(re.findall(r'\w{3,}', (page['url'] + ' ' + text).casefold()))
        score = len(words & terms)
        if score >= 2:
            rows.append((score, page['url'], {'url': page['url'], 'title': text.splitlines()[0][:300],
                                             'description': text[:500]}))
    return [row[2] for row in sorted(rows, key=lambda row: (-row[0], row[1]))[:20]]


def acquire(tf, query, purpose, *, max_pages, fresh, reuse_archive=False,
            scope_id=None, reader_budget_usd=0, reader_max_calls=0, strict=True, event_sink=None):
    from . import research, source_archive, source_outcomes, valyu_reader
    index = source_archive.scan_archive(exclude_request_id=scope_id) if reuse_archive else {}
    log = []
    def emit(event):
        log.append(event)
        if event_sink is not None:
            event_sink(event)
    if reuse_archive:
        emit({'provider': 'archive', 'operation': 'scan', 'outcome': 'complete',
              'eligible_urls': len(index), 'max_age_days': 30})
    emit({'provider': 'tinyfish', 'operation': 'search', 'outcome': 'started'})
    try:
        found = tf.search(query, purpose=purpose, max_age_days=0 if fresh else None)
        emit({'provider': 'tinyfish', 'operation': 'search', 'outcome': 'response_received'})
    except (requests.RequestException, RuntimeError) as error:
        code = _service_error(error)
        emit({'provider': 'tinyfish', 'operation': 'search', 'outcome': 'unavailable',
              'error_code': code or 'search_protocol_failure'})
        candidates = _local_candidates(index, query) if code and reuse_archive else []
        if not candidates:
            raise RuntimeError('search unavailable; no authorized local alternative') from None
        found = {'results': candidates}
        emit({'provider': 'archive', 'operation': 'local_candidates', 'outcome': 'success',
              'limitation': 'Not a fresh web search'})
    if not isinstance(found, dict) or not isinstance(found.get('results', found.get('items')), list):
        emit({'provider': 'tinyfish', 'operation': 'search', 'outcome': 'fatal', 'error_code': 'invalid_schema'})
        raise RuntimeError('search: invalid results schema')
    items = found.get('results', found.get('items'))
    manifest = select_sources(query, items, max_pages, available_urls=set(index))
    urls = manifest['selected']
    results, live = [], []
    for url in urls:
        page = source_archive.reuse_page(index, url) if reuse_archive else None
        if page is not None:
            results.append(page)
            emit({'provider': 'archive', 'operation': 'read', 'requested_url': url, 'outcome': 'success',
                        'source_path': page['retrieval']['source_path'],
                        'source_sha256': page['retrieval']['source_sha256']})
        else:
            if reuse_archive:
                emit({'provider': 'archive', 'operation': 'read', 'requested_url': url, 'outcome': 'miss',
                      'error_code': 'origin_changed_or_expired' if canonical_url(url) in index else 'no_bound_origin'})
            live.append(url)
    fetched = {'results': [], 'errors': []}
    service_failure = False
    if live:
        emit({'provider': 'tinyfish', 'operation': 'read', 'outcome': 'started', 'requested_urls': live})
        try:
            fetched = tf.fetch(live, purpose=purpose, fresh=fresh)
        except (requests.RequestException, RuntimeError) as error:
            code = _service_error(error)
            emit({'provider': 'tinyfish', 'operation': 'read', 'outcome': 'unavailable',
                  'requested_urls': live, 'error_code': code or 'reader_protocol_failure'})
            if not code or not reader_budget_usd:
                raise RuntimeError('primary reader transport or schema unavailable') from None
            fetched = {'results': [], 'errors': [{'error': code} for _ in live]}
            service_failure = True
        if (not isinstance(fetched, dict) or not isinstance(fetched.get('results'), list)
                or not isinstance(fetched.get('errors', []), list)):
            raise RuntimeError('primary reader invalid results schema')
        if strict and (fetched.get('invalid_results', 0) != 0
                       or any(not research._valid_page(page, set(live)) for page in fetched['results'])):
            raise RuntimeError('primary reader invalid results schema')
        fetched['results'] = [page for page in fetched['results'] if research._valid_page(page, set(live))]
        results.extend(fetched['results'])
    errors = fetched.get('errors', [])
    missing = [url for url in live if url not in {page['url'] for page in results}]
    codes = research._safe_errors(errors)
    if live:
        emit({'provider': 'tinyfish', 'operation': 'read', 'requested_urls': live,
                    'outcome': 'available' if not missing else 'incomplete', 'error_codes': codes})
    # Unknown/schema failures are not converted into resource failures. Only an
    # explicitly funded alternative may repair a known primary transport failure.
    if reader_budget_usd and missing:
        if not codes or any(not _fallback_code(code) for code in codes):
            raise RuntimeError('unclassified primary failure; paid alternative not called')
        if not service_failure and len(codes) != len(missing):
            raise RuntimeError('unexplained missing page; paid alternative not called')
        if not scope_id or not reader_max_calls:
            raise ValueError('reader scope and call cap required')
        for url in missing:
            attributed = any(isinstance(error, dict) and error.get('url') == url
                             and _fallback_code(error.get('error'))
                             for error in errors)
            if not service_failure and not attributed:
                emit({'provider': 'valyu', 'operation': 'read', 'requested_url': url,
                      'outcome': 'not_called', 'error_code': 'unattributed_primary_failure', 'reserved_usd': 0})
                continue
            emit({'provider': 'valyu', 'operation': 'read', 'requested_url': url, 'outcome': 'started'})
            try:
                outcome = valyu_reader.read_page(url, scope_id=scope_id,
                    budget_usd=reader_budget_usd, max_calls=reader_max_calls)
                emit(outcome['attempt'])
                page = outcome['page']
                if page is not None:
                    if not research._valid_page(page, {url}):
                        raise RuntimeError('alternative reader invalid page')
                    results.append(page)
            except valyu_reader.ValyuUnavailable as error:
                emit({'provider': 'valyu', 'operation': 'read', 'requested_url': url,
                             'outcome': 'not_called', 'error_code': error.code, 'reserved_usd': 0})
                if error.code in {'missing_key', 'circuit_disabled', 'inflight', 'cooldown',
                                  'scope_quota', 'daily_quota', 'budget_denied'}:
                    break  # A provider-wide denial is not retried for every missing URL.
        remaining = [url for url in live if url not in {page['url'] for page in results}]
        if not remaining:
            errors = []
        elif service_failure:
            raise RuntimeError('primary service failure unresolved by authorized reader')
        elif not service_failure and codes and all(code in source_outcomes.RESOURCE_ERRORS for code in codes):
            errors = [{'error': 'resource_unavailable'} for _ in remaining]
        # Otherwise preserve a primary service failure as fatal in refresh.
    return items, manifest, {'results': results, 'errors': errors}, log
