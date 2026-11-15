"""Literal claim/evidence checks; this does not establish semantic support."""
import json

from . import paths, request_research


class ClaimValidationError(ValueError):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__()

    def __str__(self):
        return json.dumps(self.diagnostics, ensure_ascii=False)


def _metadata(value, limit):
    if not isinstance(value, str):
        return None, value is not None
    # Control characters would expand up to sixfold when serialized as JSON.
    safe = ''.join(c if ord(c) >= 32 and c not in '\\"' else ' ' for c in value)
    return safe[:limit], len(value) > limit or safe != value


def validate_claims(card, claims, response_text):
    from . import intake

    queries = (request_research.read_plan(card)['queries'] if request_research.policy(card)
               else card['spec']['research_queries'])
    base = intake.root(card['spec']['id'])
    allowed = {intake.rel(base / f'sources-{i}.md.json') for i in range(len(queries))}
    cache, seen, errors, supported = {}, set(), [], 0
    if not isinstance(claims, list) or len(claims) > 30:
        raise ClaimValidationError({'schema_version': 1, 'errors': [
            {'claim_id': None, 'codes': ['invalid_claims_list']}], 'claims_checked': 0,
            'limitation': 'literal evidence only, not semantic support'})
    for claim in claims:
        codes = []
        def add(code):
            if code not in codes:
                codes.append(code)

        if not isinstance(claim, dict):
            claim = {}
            add('invalid_claim')
        cid, url, filename = claim.get('id'), claim.get('source_url'), claim.get('evidence_file')
        if not isinstance(cid, str) or not cid.strip() or len(cid) > 40:
            add('invalid_claim')
        else:
            cid = cid.strip()
            if cid in seen:
                add('duplicate_id')
            seen.add(cid)
            if not isinstance(response_text, str) or cid not in response_text:
                add('id_missing_in_response')
        content = claim.get('claim')
        if not isinstance(content, str) or not content.strip() or len(content) > 12000:
            add('invalid_claim')
        status = claim.get('status')
        if status != 'supported' and status != 'unverified':
            add('invalid_status')
        if status == 'supported':
            quote = claim.get('quote')
            if not isinstance(quote, str) or not quote.strip() or len(quote) > 12000:
                add('missing_quote')
            if isinstance(quote, str) and len(quote) > 4000:
                add('quote_too_large')
            if not isinstance(url, str) or not url.strip() or len(url) > 12000:
                add('invalid_claim')
            elif not isinstance(response_text, str) or url.strip() not in response_text:
                add('url_missing_in_response')
            if not isinstance(filename, str) or filename not in allowed:
                add('evidence_outside_allowed_set')
            else:
                if filename not in cache:
                    try:
                        path = paths.resolve(filename)
                        path.relative_to(paths.PROJECT_ROOT.resolve())
                        if path != paths.PROJECT_ROOT.resolve() / filename:
                            raise ValueError('redirected evidence path')
                        raw = path.read_text(encoding='utf-8')
                    except (OSError, ValueError, UnicodeError, RuntimeError):
                        cache[filename] = ('evidence_unreadable', None)
                    else:
                        try:
                            evidence = json.loads(raw)
                        except (ValueError, RecursionError):
                            cache[filename] = ('evidence_invalid_json', None)
                        else:
                            sources = evidence.get('sources') if isinstance(evidence, dict) else None
                            if (not isinstance(sources, list) or any(
                                    not isinstance(p, dict) or not isinstance(p.get('url'), str)
                                    or not isinstance(p.get('content'), str) for p in sources)):
                                cache[filename] = ('evidence_invalid_schema', None)
                            else:
                                cache[filename] = (None, sources)
                problem, sources = cache[filename]
                if problem:
                    add(problem)
                elif isinstance(url, str) and url.strip():
                    matching = [p for p in sources if p['url'] == url.strip()]
                    if not matching:
                        add('url_missing_in_evidence')
                    elif isinstance(quote, str) and quote.strip() and not any(
                            ' '.join(quote.strip().split()) in ' '.join(p['content'].split()) for p in matching):
                        add('quote_missing')
        if codes:
            claim_id, t1 = _metadata(cid, 256)
            source_url, t2 = _metadata(url, 256)
            evidence_file, t3 = _metadata(filename, 500)
            errors.append({'claim_id': claim_id, 'codes': codes, 'source_url': source_url,
                           'evidence_file': evidence_file, 'metadata_truncated': t1 or t2 or t3})
        elif status == 'supported':
            supported += 1
    if errors:
        raise ClaimValidationError({'schema_version': 1, 'errors': errors, 'claims_checked': len(claims),
                                    'limitation': 'literal evidence only, not semantic support'})
    return {'supported_claims': supported}
