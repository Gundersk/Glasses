"""Conservative bibliographic grouping hints, not identity verification."""
import re
import unicodedata
from urllib.parse import unquote, urlsplit

_ID = r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7})'
_ARXIV = re.compile(rf'(?i)(?:arxiv:)?({_ID})(v\d+)?')
_DOI = re.compile(r'(?i)10\.\d{4,9}/[^\s"<>?#]+')
_KIND = re.compile(r'(?i)\b(supplementary\s+(?:material|information)|supplement\s+to|errata|erratum|corrigendum|retraction)\b')


def identity(item, url):
    title = str(item.get('title') or item.get('name') or '')[:2000]
    dois, arxiv, versions = set(), set(), set()

    def add_arxiv(value):
        match = _ARXIV.fullmatch(value.strip())
        if match:
            arxiv.add('arxiv:' + match.group(1).lower())
            versions.add((match.group(2) or 'unknown').lower())

    def add_doi(value):
        value = value.strip()
        if value.lower().startswith('doi:'):
            value = value[4:].strip()
        if not _DOI.fullmatch(value):
            return
        value = value.lower()
        if value.startswith('10.48550/arxiv.'):
            add_arxiv(value[len('10.48550/arxiv.'):])
        else:
            dois.add('doi:' + value)

    for key in ('doi', 'DOI'):
        add_doi(str(item.get(key) or '')[:2000])
    for key in ('arxiv', 'arxiv_id', 'arxivId'):
        add_arxiv(str(item.get(key) or '')[:2000])
    parts = urlsplit(url)
    path = unquote(parts.path)
    if parts.hostname in {'arxiv.org', 'export.arxiv.org'}:
        match = re.fullmatch(r'(?i)/(?:abs|html|pdf)/(.+?)(?:\.pdf)?', path)
        if match:
            add_arxiv(match.group(1))
    elif parts.hostname in {'doi.org', 'dx.doi.org'}:
        add_doi(path.lstrip('/'))

    kind_match = _KIND.search(title)
    kind_text = kind_match.group(1).lower() if kind_match else ''
    kind = ('supplement' if kind_text.startswith('supplement') else
            'correction' if kind_text in {'errata', 'erratum', 'corrigendum'} else
            'retraction' if kind_text else 'main')
    title = unicodedata.normalize('NFKC', title).casefold()
    title = re.sub(r'\s+-\s+ads\s*$', '', title)
    title = re.sub(r'^\s*ava[\s-]*active[\s-]*speaker\s*:\s*', '', title)
    words = re.findall(r'[^\W_]+', title, flags=re.UNICODE)
    normalized = ' '.join(words) if len(words) >= 8 else None
    return {'ids': dois | arxiv, 'dois': dois, 'arxiv': arxiv,
            'version_set': versions, 'versions': sorted(versions - {'unknown'}),
            'title': normalized, 'kind': kind}


def representation_rank(url):
    parts = urlsplit(url)
    host, path = parts.hostname, parts.path.lower()
    if host in {'arxiv.org', 'export.arxiv.org'}:
        for rank, prefix in enumerate(('/html/', '/abs/', '/pdf/')):
            if path.startswith(prefix):
                return rank
    if host in {'github.com', 'gitlab.com', 'codeberg.org'}:
        return 3
    return 4
