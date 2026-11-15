"""Bounded, receipt-bound reuse of fetched text, not scientific acceptance."""
import copy
import hashlib
import json
import shlex
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import paths
from .research import _valid_page
from .source_selection import canonical_url


def _safe(path, directory=False):
    root = paths.PROJECT_ROOT.resolve()
    path = Path(path)
    try:
        rel = path.relative_to(root)
        if any(p in ('', '.', '..', 'temp') or p.startswith('.env') for p in rel.parts):
            return False
        current = root
        for part in rel.parts:
            current = current / part
            if current.is_symlink() or current.is_junction():
                return False
        return path.resolve() == path and (path.is_dir() if directory else path.is_file())
    except (OSError, ValueError, RuntimeError):
        return False


def _load(path, limit):
    if not _safe(path) or path.stat().st_size > limit:
        raise ValueError('invalid file')
    data = path.read_bytes()
    if len(data) > limit:
        raise ValueError('file too large')
    return json.loads(data), hashlib.sha256(data).hexdigest(), len(data)


def _origin(source, receipt):
    root = paths.PROJECT_ROOT.resolve()
    base = root / 'autonomy' / 'workspace' / 'requests'
    try:
        s = source.relative_to(base)
        r = receipt.relative_to(base)
        return (len(s.parts) == 2 and s.name.startswith('sources-') and
                s.name.endswith('.md.json') and len(r.parts) == 5 and
                r.parts[0] == s.parts[0] and r.parts[1:3] == ('run', 'evidence') and
                r.name == 'receipt.json')
    except ValueError:
        return False


def _command_ok(item, source_rel):
    if not isinstance(item, dict) or item.get('status') != 'completed' or type(item.get('returncode')) is not int or item['returncode'] != 0:
        return False
    cmd = item.get('command')
    if not isinstance(cmd, str) or hashlib.sha256(cmd.encode('utf-8')).hexdigest() != item.get('command_sha256'):
        return False
    try:
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=';&|<>')
        lexer.whitespace_split = True
        tokens = list(lexer)
        return (tokens[:3] == ['python', '-m', 'autonomy.research'] and
                not any(t in (';', '&', '&&', '|', '||', '>', '>>', '<', '<<') or
                        '$(' in t or '`' in t for t in tokens) and
                tokens.count('--out') == 1 and tokens[tokens.index('--out') + 1] == source_rel[:-5])
    except (ValueError, IndexError):
        return False


def _verified(source, receipt):
    if not _origin(source, receipt):
        raise ValueError('invalid origin')
    doc, source_hash, size = _load(source, 500_000)
    rec, receipt_hash, _ = _load(receipt, 2_000_000)
    rel = source.relative_to(paths.PROJECT_ROOT.resolve()).as_posix()
    if (not isinstance(doc, dict) or not isinstance(rec, dict) or
            rec.get('version') != 2 or rec.get('mock') is not False or
            rec.get('execution') != 'approved_commands' or
            doc.get('collection_status', 'available') != 'available' or
            not isinstance(doc.get('sources'), list)):
        raise ValueError('invalid schema')
    outputs = rec.get('outputs_after')
    commands = rec.get('commands')
    if not isinstance(outputs, list) or not isinstance(commands, list):
        raise ValueError('invalid receipt')
    if not any(isinstance(x, dict) and x.get('path') == rel and x.get('status') == 'file' and
               x.get('sha256') == source_hash and type(x.get('size')) is int and x['size'] == size and
               ('mtime_ns' not in x or x['mtime_ns'] == source.stat().st_mtime_ns) for x in outputs):
        raise ValueError('fingerprint mismatch')
    if not any(_command_ok(x, rel) for x in commands):
        raise ValueError('missing command')
    return doc, source_hash, receipt_hash


def _date(value):
    if not isinstance(value, str):
        raise ValueError('missing date')
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None or date.utcoffset() is None:
        raise ValueError('timezone required')
    return date.astimezone(timezone.utc)


def _page_accessed(page, doc):
    retrieval = page.get('retrieval')
    if retrieval is not None and not isinstance(retrieval, dict):
        raise ValueError('invalid retrieval')
    if retrieval and retrieval.get('method') == 'archive':
        return retrieval.get('original_accessed')
    return doc.get('accessed')


def _page_valid(page):
    if not isinstance(page, dict):
        return False
    url, content = page.get('url'), page.get('content')
    if not canonical_url(url) or not isinstance(content, str) or not content.strip() or len(content) > 30000:
        return False
    # Also check content itself when an older record has a competing text field.
    content_page = {k: v for k, v in page.items() if k not in ('text', 'markdown')}
    return _valid_page(page, {url}) and _valid_page(content_page, {url})


def _age(value, now, max_age_days):
    if type(max_age_days) not in (int, float) or not 0 <= max_age_days <= 365:
        raise ValueError('invalid TTL')
    age = now - _date(value)
    if age > timedelta(days=max_age_days) or age < -timedelta(minutes=5):
        raise ValueError('expired or future page')
    return age


def scan_archive(exclude_request_id=None, max_age_days=30):
    now = datetime.now(timezone.utc)
    root = paths.PROJECT_ROOT.resolve()
    base = root / 'autonomy' / 'workspace' / 'requests'
    result, ranks = {}, {}
    try:
        if not _safe(base, True) or type(max_age_days) not in (int, float) or not 0 <= max_age_days <= 365:
            return {}
        dirs = sorted((p for p in base.iterdir() if _safe(p, True)), reverse=True)[:100]
        for request in dirs:
            if request.name == exclude_request_id:
                continue
            try:
                sources = sorted((p for p in request.glob('sources-*.md.json') if _safe(p)), reverse=True)[:20]
                evidence = request / 'run' / 'evidence'
                if not _safe(evidence, True):
                    continue
                runs = sorted((p for p in evidence.iterdir() if _safe(p, True)), reverse=True)[:20]
                receipts = [p / 'receipt.json' for p in runs if _safe(p / 'receipt.json')]
                for source in sources:
                    for receipt in receipts:
                        try:
                            doc, source_hash, receipt_hash = _verified(source, receipt)
                            _date(doc.get('accessed'))
                            for page in doc['sources']:
                                if not _page_valid(page):
                                    continue
                                url, content = page.get('url'), page.get('content')
                                key = canonical_url(url)
                                try:
                                    effective = _page_accessed(page, doc)
                                    age = _age(effective, now, max_age_days)
                                    accessed = _date(effective)
                                except (ValueError, TypeError, OverflowError):
                                    continue
                                rank = (accessed, source.as_posix(), receipt.as_posix())
                                if key in ranks and rank <= ranks[key]:
                                    continue
                                ranks[key] = rank
                                result[key] = {'url': url, 'content': content, 'retrieval': {
                                    'method': 'archive', 'source_path': source.relative_to(root).as_posix(),
                                    'source_sha256': source_hash, 'receipt_path': receipt.relative_to(root).as_posix(),
                                    'receipt_sha256': receipt_hash, 'original_accessed': effective,
                                    'captured_accessed': doc['accessed'], 'max_age_days': max_age_days,
                                    'verified_at': now.isoformat().replace('+00:00', 'Z'),
                                    'age_days': age.total_seconds() / 86400,
                                    'limitation': 'Archived fetched text; no scientific acceptance inherited'}}
                        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
                            continue
            except (OSError, ValueError, RuntimeError):
                continue
    except (OSError, ValueError, RuntimeError):
        return result
    return result


def reuse_page(index, url, *, max_age_days=30):
    try:
        key = canonical_url(url)
        if not key or not isinstance(index, dict):
            return None
        record = index[key]
        retrieval = record['retrieval']
        root = paths.PROJECT_ROOT.resolve()
        source = root / retrieval['source_path']
        receipt = root / retrieval['receipt_path']
        doc, source_hash, receipt_hash = _verified(source, receipt)
        _date(doc.get('accessed'))
        if (source_hash != retrieval['source_sha256'] or receipt_hash != retrieval['receipt_sha256'] or
                retrieval.get('method') != 'archive' or canonical_url(record['url']) != key):
            return None
        matching = [p for p in doc['sources'] if _page_valid(p) and p.get('url') == record['url'] and
                    p.get('content') == record['content'] and
                    _page_accessed(p, doc) == retrieval['original_accessed']]
        if not matching:
            return None
        _age(_page_accessed(matching[0], doc), datetime.now(timezone.utc), max_age_days)
        return copy.deepcopy(record)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, OverflowError):
        return None
