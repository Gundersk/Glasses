"""Offline regression for real TinyFish MCP response schemas."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autonomy import research


class ContractTests(unittest.TestCase):
    def test_text_field_accepted_and_legacy_accepted(self):
        for key in ('text', 'content', 'markdown'):
            self.assertTrue(research._valid_page({'url': 'https://x.org', key: 'valid'}, {'https://x.org'}))

    def test_failed_or_unrequested_never_accepted(self):
        for item in ({'url': 'https://other.org', 'text': 'valid'},
                     {'url': 'https://x.org', 'text': 'valid', 'status': 403},
                     {'url': 'https://x.org', 'text': 'valid', 'isError': True},
                     {'url': 'https://x.org', 'text': {'tree': 'not markdown'}},
                     {'url': 'https://x.org', 'text': '  '}):
            self.assertFalse(research._valid_page(item, {'https://x.org'}))

    def test_both_status_fields_must_be_successful(self):
        for code in (401, 429, 500):
            for fields in ({'status': 'ok', 'status_code': code},
                           {'status': code, 'status_code': 200}):
                self.assertFalse(research._valid_page({'url': 'https://x.org', 'content': 'nonempty', **fields}, {'https://x.org'}))

    def client(self, directory):
        tf = research.TinyFish.__new__(research.TinyFish)
        tf.cache_dir = Path(directory)
        return tf

    def test_fetch_text_caches_and_returns_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tf = self.client(tmp)
            with patch.object(tf, '_tool', return_value={'results': [
                    {'url': 'https://x.org', 'text': 'original exact quotation'}], 'errors': []}):
                response = tf.fetch(['https://x.org'], 'test', fresh=True)
            self.assertEqual(response['results'][0]['text'], 'original exact quotation')
            self.assertEqual(len(list(Path(tmp).glob('page-*.json'))), 1)

    def test_mcp_iserror_cannot_be_accepted(self):
        tf = self.client('.')
        with patch.object(tf, '_ensure_init'), patch.object(tf, '_rpc', return_value={
            'result': {'isError': True, 'content': [{'type': 'text', 'text': '{"results": []}'}]}}):
            with self.assertRaisesRegex(RuntimeError, 'tool error'):
                tf._tool('fetch_content', {})

    def test_structured_content_and_non_json_failure(self):
        tf = self.client('.')
        with patch.object(tf, '_ensure_init'), patch.object(tf, '_rpc', return_value={
            'result': {'structuredContent': {'results': [], 'errors': []}}}):
            self.assertEqual(tf._tool('fetch_content', {})['results'], [])
        with patch.object(tf, '_ensure_init'), patch.object(tf, '_rpc', return_value={
            'result': {'content': [{'type': 'text', 'text': 'SECRET unexpected response'}]}}):
            with self.assertRaises(RuntimeError) as exc:
                tf._tool('fetch_content', {})
            self.assertNotIn('SECRET', str(exc.exception))

    def test_refresh_saves_text_as_canonical_content(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(research.paths, 'inside_project', return_value=True), \
             patch.object(research, 'TinyFish') as cls:
            cls.return_value.search.return_value = {'results': [{'url': 'https://x.org', 'title': 'test'}]}
            cls.return_value.fetch.return_value = {'results': [{'url': 'https://x.org', 'text': 'Exact original quote'}], 'errors': []}
            output = Path(tmp) / 'source.md'
            research.refresh('test', 'test', out=str(output), fresh=True)
            stored = json.loads(Path(str(output) + '.json').read_text(encoding='utf-8'))
            self.assertEqual(stored['sources'][0]['content'], 'Exact original quote')
            self.assertIn('Exact original quote', output.read_text(encoding='utf-8'))

    def test_safe_error_code_without_sensitive_values(self):
        errors = [{'error': 'bot_blocked', 'url': 'https://sensitive.org/key'},
                  {'error': 'secret API key: abc'}, {'error': {'message': 'secret'}}]
        self.assertEqual(research._safe_errors(errors), ['bot_blocked', 'unclassified_error', 'unclassified_error'])

    def test_empty_results_reports_specific_code_without_raw_details(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(research.paths, 'inside_project', return_value=True), \
             patch.object(research, 'TinyFish') as cls:
            cls.return_value.search.return_value = {'results': [{'url': 'https://x.org'}]}
            cls.return_value.fetch.return_value = {'results': [], 'errors': [{'error': 'bot_blocked', 'url': 'SECRET'}]}
            with self.assertRaises(RuntimeError) as exc:
                research.refresh('test', 'test', out=str(Path(tmp) / 'source.md'))
            self.assertIn('bot_blocked', str(exc.exception))
            self.assertNotIn('SECRET', str(exc.exception))

    def test_malformed_response_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tf = self.client(tmp)
            with patch.object(tf, '_tool', return_value={'raw': 'SECRET'}):
                with self.assertRaisesRegex(RuntimeError, 'invalid results/errors schema'):
                    tf.fetch(['https://x.org'], 'test', fresh=True)


if __name__ == '__main__':
    unittest.main()
