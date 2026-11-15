"""Offline tests: synthetic pages only; no provider or request runs."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autonomy import intake, paths, research, source_outcomes as so

A, B = 'https://a.example/page', 'https://b.example/page'


def document(selected=None, pages=None, errors=None, query='query'):
    selected = [A] if selected is None else selected
    pages = [] if pages is None else pages
    return {'schema_version': 2, 'query': query, 'accessed': '2026-11-14T00:00:00Z',
            'fresh_requested': True, 'selection_manifest': {'selected': selected},
            'search_results_count': len(selected), 'fetch_attempted': bool(selected),
            'sources': pages, 'collection_status': 'available' if pages else 'unavailable',
            'unavailable_urls': [u for u in selected if u not in [p['url'] for p in pages]],
            'error_codes': errors or []}


class OutcomesTests(unittest.TestCase):
    def run_refresh(self, found, fetched, allow=True):
        with tempfile.TemporaryDirectory() as tmp, patch.object(research.paths, 'inside_project', return_value=True), \
             patch.object(research, 'TinyFish') as cls:
            cls.return_value.search.return_value = found
            cls.return_value.fetch.return_value = fetched
            out = Path(tmp) / 'source.md'
            research.refresh('query', 'test', out=str(out), fresh=True, allow_unavailable=allow)
            return out.read_text(encoding='utf-8'), json.loads(Path(str(out) + '.json').read_text(encoding='utf-8'))

    def test_blocked_opt_in(self):
        text, doc = self.run_refresh({'results': [{'url': A}]},
                                     {'results': [], 'errors': [{'error': 'bot_blocked', 'url': 'SECRET'}]})
        self.assertIn('SOURCE UNAVAILABLE - not evidence', text)
        self.assertEqual(so.inspect_document(doc)['unavailable_urls'], [A])
        self.assertNotIn('SECRET', json.dumps(doc))

    def test_blocked_legacy(self):
        with self.assertRaisesRegex(RuntimeError, 'bot_blocked'):
            self.run_refresh({'results': [{'url': A}]}, {'results': [], 'errors': [{'error': 'bot_blocked'}]}, False)

    def test_partial(self):
        _, doc = self.run_refresh({'results': [{'url': A}, {'url': B}]},
                                  {'results': [{'url': A, 'text': 'real text'}], 'errors': [{'error': 'bot_blocked'}]})
        self.assertEqual(so.inspect_document(doc)['read_pages'], 1)
        self.assertEqual(doc['unavailable_urls'], [B])

    def test_fatal_errors_even_with_page(self):
        for code in ('quota_exceeded', 'rate_limited', 'auth', 'network_error', 'unknown', 'schema_error'):
            with self.subTest(code=code), self.assertRaises(RuntimeError):
                self.run_refresh({'results': [{'url': A}, {'url': B}]},
                                 {'results': [{'url': A, 'text': 'page'}], 'errors': [{'error': code}]})

    def test_search_schema_fatal(self):
        for found in ({}, {'results': {}}, [], {'results': None}):
            with self.subTest(found=found), self.assertRaises(RuntimeError):
                self.run_refresh(found, {})

    def test_fetch_schema_fatal(self):
        with self.assertRaises(RuntimeError):
            self.run_refresh({'results': [{'url': A}]}, {'results': 'invalid'})

    def test_no_results(self):
        _, doc = self.run_refresh({'results': []}, {})
        self.assertEqual(doc['error_codes'], ['no_results'])
        self.assertEqual(so.inspect_document(doc)['read_pages'], 0)

    def test_no_valid_selection_not_no_results(self):
        with self.assertRaises(RuntimeError):
            self.run_refresh({'results': [{'url': 'http://localhost/'}]}, {})

    def test_invalid_empty_legacy(self):
        with self.assertRaises(ValueError):
            so.inspect_document({'sources': []})

    def test_legacy_page(self):
        self.assertEqual(so.inspect_document({'sources': [{'url': A, 'content': 'text'}]})['read_pages'], 1)

    def test_injected_unavailable(self):
        d = document(errors=['bot_blocked'])
        d['unavailable_urls'] = [B]
        with self.assertRaises(ValueError):
            so.inspect_document(d)

    def test_missing_selected(self):
        d = document(errors=['bot_blocked'])
        del d['selection_manifest']['selected']
        with self.assertRaises(ValueError):
            so.inspect_document(d)

    def test_unrequested_page(self):
        d = document(pages=[{'url': B, 'content': 'page'}], errors=['bot_blocked'])
        with self.assertRaises(ValueError):
            so.inspect_document(d)

    def test_challenge(self):
        with self.assertRaises(RuntimeError):
            self.run_refresh({'results': [{'url': A}]}, {'results': [{'url': A, 'text': 'cf-please-wait CAPTCHA'}]})
        with self.assertRaises(ValueError):
            so.inspect_document({'sources': [{'url': A, 'content': 'cf-please-wait'}]})

    def test_public_url_and_version(self):
        for url in ('http://127.0.0.1/', 'https://user:pass@example.org/', 'file:///etc/passwd'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                so.inspect_document(document(selected=[url], errors=['bot_blocked']))
        d = document(errors=['bot_blocked']); d['schema_version'] = True
        with self.assertRaises(ValueError):
            so.inspect_document(d)

    def test_collection_and_path_guard(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(paths, 'PROJECT_ROOT', Path(tmp)):
            card = {'spec': {'id': 'MT-2026-11-14-test', 'research_queries': ['query', 'second']}}
            base = intake.root(card['spec']['id']); base.mkdir(parents=True)
            one = document(pages=[{'url': A, 'content': 'real page'}])
            two = document(errors=['bot_blocked'], query='second')
            for i, d in enumerate((one, two)):
                (base / f'sources-{i}.md.json').write_text(json.dumps(d), encoding='utf-8')
            result = so.validate_collection(card)
            self.assertEqual((result['pass'], result['read_pages'], result['unavailable_queries']), (True, 1, 1))
            one = document(errors=['bot_blocked'])
            (base / 'sources-0.md.json').write_text(json.dumps(one), encoding='utf-8')
            self.assertFalse(so.validate_collection(card)['pass'])
            # Redirected request directory is forbidden, even when destination is inside project.
            other = Path(tmp) / 'other'; other.mkdir()
            with patch.object(intake, 'root', return_value=other / '..' / 'other'):
                with self.assertRaises(ValueError):
                    so.validate_collection(card)

    def test_unexplained_missing(self):
        with self.assertRaises(RuntimeError):
            self.run_refresh({'results': [{'url': A}]}, {'results': [], 'errors': []})


if __name__ == '__main__':
    unittest.main()
