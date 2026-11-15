"""Deterministic search-result selection; hints are not evidence of truth."""
import ipaddress
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonical_url(url):
    if not isinstance(url, str) or not url or len(url) > 2048 or any(c.isspace() or ord(c) < 32 for c in url):
        return None
    try:
        p = urlsplit(url)
        host = (p.hostname or '').lower().rstrip('.')
        port = p.port
        if p.scheme.lower() not in ('http', 'https') or not host or p.username is not None or p.password is not None or '\\' in url:
            return None
        host = host.encode('idna').decode('ascii')
        if host == 'localhost' or host.endswith('.localhost') or host.endswith('.local'):
            return None
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', host) or re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*', host):
                return None
        else:
            if not ip.is_global:
                return None
        if host.startswith('www.'):
            host = host[4:]
        netloc = f'[{host}]' if ':' in host else host
        if port and not (p.scheme.lower() == 'http' and port == 80 or p.scheme.lower() == 'https' and port == 443):
            netloc += f':{port}'
        params = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                        if not k.lower().startswith('utm_') and k.lower() not in {'gclid', 'fbclid', 'dclid', 'msclkid', 'ref', 'ref_src'})
        return urlunsplit((p.scheme.lower(), netloc, p.path.rstrip('/') or '/', urlencode(params), ''))
    except (ValueError, UnicodeError):
        return None


def _tokens(text):
    return set(re.findall(r'[^\W_]+', str(text).lower(), flags=re.UNICODE))


def select_sources(query, items, max_pages):
    if type(max_pages) is not int or not 1 <= max_pages <= 5:
        raise ValueError('max_pages must be an integer in 1..5')
    candidates, valid, seen = [], [], set()
    query_tokens = _tokens(str(query)[:2048])
    for index, item in enumerate(items[:20]):
        item = item if isinstance(item, dict) else {}
        url = item.get('url')
        canonical = canonical_url(url)
        record = {'index': index, 'url': url[:2048] if isinstance(url, str) else '',
                  'canonical_url': canonical, 'status': 'rejected', 'reason': 'invalid_url'}
        candidates.append(record)
        if not canonical:
            continue
        if canonical in seen:
            record['reason'] = 'duplicate'
            continue
        seen.add(canonical)
        host = urlsplit(canonical).hostname
        text = ' '.join(str(item.get(k) or '')[:2000] for k in ('title', 'name', 'snippet', 'description'))
        score = len(query_tokens & _tokens(text + ' ' + canonical))
        hints = []
        if host in {'github.com', 'gitlab.com', 'codeberg.org'}:
            hints.append('repository')
        if host.startswith('docs.') or '/docs/' in canonical:
            hints.append('documentation')
        if host in {'arxiv.org', 'doi.org', 'dx.doi.org'}:
            hints.append('arxiv_or_doi')
        if host in {'nature.com', 'science.org', 'springer.com', 'link.springer.com', 'ieee.org', 'dl.acm.org'}:
            hints.append('publisher')
        record.update(score=score, domain=host, primary_source_hints=hints, reason='page_limit')
        valid.append(record)
    selected, used = [], set()
    while valid and len(selected) < max_pages:
        best = min(valid, key=lambda r: (-r['score'], r['domain'] in used, r['index']))
        valid.remove(best)
        best.update(status='selected', reason='relevance_and_domain_diversity')
        selected.append(best['url'])
        used.add(best['domain'])
    return {'candidates': candidates, 'selected': selected,
            'limitation': 'Primary-source hints are heuristics, not verified primary status or scientific reliability; DNS and redirects are not checked.'}
