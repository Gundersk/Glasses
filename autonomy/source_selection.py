"""Deterministic search-result selection; hints are not evidence of truth."""
import ipaddress
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from autonomy.publication_identity import identity, representation_rank


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


def select_sources(query, items, max_pages, available_urls=None):
    if type(max_pages) is not int or not 1 <= max_pages <= 5:
        raise ValueError('max_pages must be an integer in 1..5')
    candidates, valid, seen = [], [], set()
    query_tokens = _tokens(str(query)[:2048])
    for index, item in enumerate(items[:20]):
        item = item if isinstance(item, dict) else {}
        url = item.get('url')
        canonical = canonical_url(url)
        record = {'index': index, 'url': url[:2048] if isinstance(url, str) else '',
                  'canonical_url': canonical, 'status': 'rejected', 'reason': 'invalid_url',
                  'publication_key': None, 'dedup_basis': 'url', 'mirror_of': None,
                  'selected_group': None, 'versions': [], 'identity_conflicts': []}
        candidates.append(record)
        if not canonical:
            continue
        if canonical in seen:
            record['reason'] = 'duplicate'
        else:
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
        record['_identity'] = identity(item, canonical)
        record['versions'] = record['_identity']['versions']
        valid.append(record)
    def conflicts(a, b):
        result = []
        for field in ('dois', 'arxiv'):
            if a[field] and b[field] and a[field] != b[field]:
                result.append(field)
        if a['arxiv'] and b['arxiv'] and a['version_set'] != b['version_set']:
            result.append('arxiv_version')
        return result

    def absorb(target, source):
        target['records'].extend(source['records'])
        for field in ('ids', 'urls', 'dois', 'arxiv', 'version_set'):
            target[field].update(source[field])

    def mark_conflict(groups_, reasons):
        for component in groups_:
            for r in component['records']:
                r['identity_conflicts'] = sorted(set(r['identity_conflicts']) | set(reasons))

    # Require compatibility across entire components, including potential bridges.
    groups = []
    for record in valid:
        info = record['_identity']
        current = {'records': [record], 'ids': set(info['ids']),
                   'urls': {record['canonical_url']}, 'kind': info['kind'],
                   'dois': set(info['dois']), 'arxiv': set(info['arxiv']),
                   'version_set': set(info['version_set'])}
        matches = [g for g in groups if g['kind'] == current['kind'] and
                   (g['urls'] & current['urls'] or g['ids'] & current['ids'])]
        compatible = []
        for group in matches:
            reasons = conflicts(group, current)
            if reasons:
                mark_conflict([group, current], reasons)
            else:
                compatible.append(group)
        pair_conflicts = set()
        for i, group in enumerate(compatible):
            for other in compatible[i + 1:]:
                pair_conflicts.update(conflicts(group, other))
        if pair_conflicts:
            mark_conflict([current] + compatible, pair_conflicts)
        else:
            for group in compatible:
                absorb(current, group)
                groups.remove(group)
        groups.append(current)
    # A title may attach an ID-less component only when it names at most one
    # explicit component; ambiguous title matches remain separate.
    for group in list(groups):
        if group['ids'] or group not in groups:
            continue
        titles = {r['_identity']['title'] for r in group['records']} - {None}
        matches = [g for g in groups if g is not group and g['kind'] == group['kind']
                   and titles & {r['_identity']['title'] for r in g['records']}]
        strong = [g for g in matches if g['ids']]
        bases = {tuple(sorted(g['arxiv'])) for g in strong}
        if len(bases) == 1 and len(next(iter(bases))) == 1:
            # A known version without a title must still participate in the
            # newest-version decision and DOI ambiguity check.
            base = next(iter(bases))
            strong = [g for g in groups if g['kind'] == group['kind'] and
                      tuple(sorted(g['arxiv'])) == base]
        if len(strong) > 1:
            # Same arXiv base across versions is one title candidate, not proof
            # of version equivalence; attach only to its newest explicit version.
            arxiv_sets = {tuple(sorted(g['arxiv'])) for g in strong}
            doi_sets = {tuple(sorted(g['dois'])) for g in strong if g['dois']}
            explicit = [g for g in strong if len(g['version_set']) == 1 and
                        next(iter(g['version_set'])).startswith('v')]
            if (len(arxiv_sets) != 1 or len(next(iter(arxiv_sets))) != 1 or
                    len(doi_sets) > 1 or not explicit):
                mark_conflict([group], ['ambiguous_title'])
                continue
            newest = max(int(next(iter(g['version_set']))[1:]) for g in explicit)
            strong = [g for g in explicit if int(next(iter(g['version_set']))[1:]) == newest]
            if len(strong) != 1:
                mark_conflict([group], ['ambiguous_title'])
                continue
        targets = strong or [g for g in matches if not g['ids']]
        if targets:
            target = targets[0]
            target['records'].extend(group['records'])
            target['urls'].update(group['urls'])
            target['title_merge'] = True
            groups.remove(group)
    available = {u for u in (available_urls or ()) if canonical_url(u) == u}
    for group in groups:
        records = group['records']
        rep = min(records, key=lambda r: (r['canonical_url'] not in available,
                                         representation_rank(r['canonical_url']), r['index']))
        group['rep'] = rep
        group['score'] = max(r['score'] for r in records)
        group['index'] = min(r['index'] for r in records)
        key = (min(group['ids']) if group['ids'] else
               'title:' + next((r['_identity']['title'] for r in records if r['_identity']['title']), '')
               if group.get('title_merge') else 'url:' + rep['canonical_url'])
        if group['kind'] != 'main':
            key = group['kind'] + ':' + key
        # Same identifier can legitimately occur in different version/conflict groups.
        key += '#group-' + str(group['index'])
        basis = 'title_candidate' if group.get('title_merge') else 'explicit' if group['ids'] else 'url'
        for r in records:
            r.update(publication_key=key, dedup_basis=basis, selected_group=rep['url'])
            if r is not rep:
                r.update(mirror_of=rep['url'], reason=('duplicate' if r['canonical_url'] == rep['canonical_url'] else 'publication_duplicate'))
    selected, used = [], set()
    while groups and len(selected) < max_pages:
        best = min(groups, key=lambda g: (-g['score'], g['rep']['domain'] in used, g['index']))
        groups.remove(best)
        rep = best['rep']
        rep.update(status='selected', reason='relevance_and_domain_diversity')
        selected.append(rep['url'])
        used.add(rep['domain'])
    for r in valid:
        del r['_identity']
    return {'candidates': candidates, 'selected': selected,
            'limitation': 'Publication grouping and representation preferences are heuristics, not verified identity, version equivalence, access, primary status or scientific reliability; title candidates may attach to the newest explicit arXiv version. DNS and redirects are not checked.'}
