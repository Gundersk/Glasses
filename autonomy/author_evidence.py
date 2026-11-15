"""Read-only, bounded and explicitly partial author evidence packet."""
import hashlib
import json
import re
from pathlib import Path

from . import paths


class AuthorEvidenceError(ValueError):
    """Evidence is unavailable, unauthorized, malformed, or cannot fit."""


def _tokens(values):
    result = set()
    for value in values:
        if isinstance(value, str):
            result.update(t.casefold() for t in re.findall(r"\w{3,}", value, re.UNICODE))
    return set(sorted(result)[:128])


def _excerpts(text, budget, tokens, quotes, claim_tokens):
    if len(text) <= budget:
        return [(0, len(text))]
    prefix = min(1000, max(1, budget // 3))
    # A preferred quote straddling the initial prefix must remain one excerpt.
    # If prefix+quote cannot fit, shrink the prefix rather than split the quote.
    for quote in quotes:
        pos = text.find(quote)
        end = pos + len(quote)
        if pos >= 0 and len(quote) <= budget and pos < prefix < end:
            prefix = end if end <= budget else min(pos, budget - len(quote))
            break
    remaining = budget - prefix
    candidates = []
    for quote in quotes:
        pos = text.find(quote)
        if pos >= 0 and len(quote) <= remaining:
            candidates.append((0, pos, len(quote)))
    for match in re.finditer(r"\w{3,}", text, re.UNICODE):
        token = match.group().casefold()
        if token in claim_tokens or token in tokens:
            candidates.append((1 if token in claim_tokens else 2, match.start(), len(match.group())))
    candidates.sort()
    intervals = [(0, prefix)]
    for rank, pos, size in candidates:
        if len(intervals) >= 3 or remaining <= 0:
            break
        if any(start <= pos < end for start, end in intervals):
            continue
        amount = remaining if len(intervals) == 2 else max(remaining // 2, size)
        amount = min(remaining, max(amount, size))
        start = max(prefix, min(pos - max(0, (amount - size) // 2), len(text) - amount))
        end = start + amount
        if any(start < b and end > a for a, b in intervals):
            continue
        intervals.append((start, end))
        remaining -= amount
    if remaining:
        # Always use the budget, without overlapping another excerpt.
        for start, end in zip([0] + [b for a, b in sorted(intervals)],
                              [a for a, b in sorted(intervals)] + [len(text)]):
            if remaining and end > start and len(intervals) < 3:
                take = min(remaining, end - start)
                intervals.append((start, start + take))
                remaining -= take
    return sorted(intervals)


def author_bundle(card, input_paths, claims=None, max_chars=60000):
    from . import intake, request_research
    from .source_outcomes import inspect_document

    if type(max_chars) is not int or not 8000 <= max_chars <= 60000:
        raise AuthorEvidenceError("max_chars must be an integer in 8000..60000")
    try:
        spec = card["spec"]
        policy = request_research.policy(card)
        queries = request_research.read_plan(card)["queries"] if policy else spec["research_queries"]
        if not isinstance(queries, list) or len(queries) > (6 if policy else 3):
            raise ValueError("invalid queries")
        base = intake.root(spec["id"])
        allowed = [intake.rel(base / f"sources-{i}.md.json") for i in range(len(queries))]
        query_by_file = dict(zip(allowed, queries))
        if not isinstance(input_paths, (list, tuple)):
            raise ValueError("invalid inputs")
        selected = set()
        for name in input_paths:
            if not isinstance(name, str):
                raise ValueError("invalid input path")
            if name in allowed:
                selected.add(name)
            elif re.match(r"^sources-.*\.json$", Path(name.replace('\\', '/')).name, re.I):
                raise ValueError("unknown source input")
        if claims is None:
            claims = []
        if not isinstance(claims, list) or len(claims) > 30 or any(not isinstance(c, dict) for c in claims):
            raise ValueError("invalid claims")
        tokens = _tokens(spec.get("requirements", []) + (policy or {}).get("topics", []) + queries)
        pages, unavailable = [], []
        for name in allowed:
            if name not in selected:
                continue
            fp = paths.PROJECT_ROOT / name
            resolved = fp.resolve(strict=True)
            if (not resolved.is_relative_to(paths.PROJECT_ROOT.resolve())
                    or resolved != paths.PROJECT_ROOT.resolve() / name):
                raise ValueError("source outside project")
            raw = fp.read_bytes()
            document = json.loads(raw.decode("utf-8"))
            outcome = inspect_document(document)
            page_cap = policy.get("pages_per_query", 3) if policy else 2
            if (len(document['sources']) > page_cap
                    or document.get('schema_version') == 2 and
                    (document['query'] != query_by_file[name]
                     or len(document['selection_manifest']['selected']) > page_cap)):
                raise ValueError("source query or selected-page cap mismatch")
            if outcome["collection_status"] == "unavailable":
                unavailable.append({"evidence_file": name, "source_sha256": hashlib.sha256(raw).hexdigest(),
                                    "unavailable_urls": outcome["unavailable_urls"],
                                    "error_codes": outcome["error_codes"], "read_pages": 0,
                                    "limitation": "No fetched page; cannot support a claim"})
                continue
            source_pages = document.get("sources") if isinstance(document, dict) else None
            if not isinstance(source_pages, list) or not source_pages:
                raise ValueError("empty or invalid source pages")
            if len(source_pages) > (policy.get("pages_per_query", 3) if policy else 2):
                raise ValueError("too many pages per source")
            sha = hashlib.sha256(raw).hexdigest()
            for page in source_pages:
                if (not isinstance(page, dict) or not isinstance(page.get("url"), str)
                        or not page["url"].strip() or len(page["url"]) > 2000
                        or not isinstance(page.get("content"), str)):
                    raise ValueError("invalid page url/content")
                text = " ".join(page["content"].split())
                if not text:
                    raise ValueError("empty page content")
                related = [c for c in claims if c.get("evidence_file") == name and c.get("source_url") == page["url"]]
                quotes = [" ".join(c["quote"].split()) for c in related
                          if isinstance(c.get("quote"), str) and c["quote"].strip() and len(c["quote"]) <= 4000]
                pages.append((name, sha, page["url"], text, quotes, _tokens([c.get("claim") for c in related])))
        if not pages or len(pages) > (18 if policy else 6):
            raise ValueError("no selected source pages or page limit exceeded")

        def render(per_page):
            result = []
            for name, sha, url, text, quotes, claim_tokens in pages:
                spans = _excerpts(text, per_page, tokens, quotes, claim_tokens)
                excerpts = [{"start": a, "end": b, "text": text[a:b]} for a, b in spans]
                visible = sum(b - a for a, b in spans)
                result.append({"evidence_file": name, "source_sha256": sha, "url": url,
                               "source_characters": len(text), "visible_characters": visible,
                               "omitted_characters": len(text) - visible, "full_source": visible == len(text),
                               "excerpts": excerpts})
            packet = {"schema_version": 1, "untrusted_source_data": True,
                      "limitation": "Visible excerpts of saved pages only (not necessarily full publications); exact quote from a single excerpt is not proof of an entire claim.",
                      "sources": result, "unavailable_sources": unavailable,
                      "omitted_characters": sum(p["omitted_characters"] for p in result)}
            return json.dumps(packet, ensure_ascii=False, separators=(",", ":"))

        low, high = 300, max(len(p[3]) for p in pages)
        packed = render(low)
        if len(packed) > max_chars:
            raise ValueError("metadata and minimum excerpts exceed budget")
        while low < high:
            mid = (low + high + 1) // 2
            candidate = render(mid)
            if len(candidate) <= max_chars:
                low, packed = mid, candidate
            else:
                high = mid - 1
        return packed
    except AuthorEvidenceError:
        raise
    except (ValueError, TypeError, KeyError, OSError, UnicodeError) as exc:
        raise AuthorEvidenceError(str(exc)) from exc
