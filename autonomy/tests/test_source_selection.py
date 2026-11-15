import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autonomy import research
from autonomy.source_selection import canonical_url, select_sources


class SelectionTests(unittest.TestCase):
    def test_tracking_fragment_dedup(self):
        items = [{'url': 'https://www.example.org/a/?utm_source=x#part'},
                 {'url': 'https://example.org/a'}]
        result = select_sources('', items, 2)
        self.assertEqual(len(result['selected']), 1)
        self.assertEqual(result['candidates'][1]['reason'], 'duplicate')

    def test_hint_is_not_fact(self):
        result = select_sources('', [{'url': 'https://arxiv.org/abs/123'}], 1)
        self.assertIn('arxiv_or_doi', result['candidates'][0]['primary_source_hints'])
        self.assertIn('not verified', result['limitation'])
        self.assertNotIn('verdict', result['candidates'][0])

    def test_relevance(self):
        items = [{'url': 'https://example.org/a', 'title': 'unrelated'},
                 {'url': 'https://example.net/b', 'title': 'Russian speech recognition'}]
        self.assertEqual(select_sources('Russian speech', items, 1)['selected'], [items[1]['url']])

    def test_diversity_only_on_tie(self):
        items = [{'url': f'https://{host}/{path}', 'title': title} for host, path, title in
                 [('a.org', '1', 'speech'), ('a.org', '2', 'speech'), ('b.org', '3', 'speech')]]
        self.assertEqual(select_sources('speech', items, 2)['selected'], [items[0]['url'], items[2]['url']])
        items[1]['title'] = 'speech audio'
        self.assertEqual(select_sources('speech audio', items, 2)['selected'], [items[1]['url'], items[2]['url']])

    def test_bad_urls(self):
        for url in ['file:///etc/passwd', 'http://u:p@example.org/', 'http://localhost/',
                    'http://x.localhost/', 'http://127.0.0.1/', 'http://192.168.1.1/',
                    'http://[::1]/', 'http://169.254.169.254/', 'http://127.1/', 'https://bad host/']:
            with self.subTest(url=url):
                self.assertIsNone(canonical_url(url))

    def test_bounds(self):
        items = [{'url': f'https://example.org/{i}'} for i in range(100)]
        result = select_sources('', items, 5)
        self.assertEqual(len(result['candidates']), 20)
        self.assertEqual(len(result['selected']), 5)
        for value in [0, 6, -1, True, 1.5]:
            with self.assertRaises(ValueError):
                select_sources('', items, value)
            with self.assertRaises(ValueError):
                research.refresh('q', 'p', value, dry_run=True)

    def test_refresh_mock_no_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(research.paths, 'inside_project', return_value=True), patch.object(research, 'TinyFish') as cls:
            client = cls.return_value
            client.search.return_value = {'results': [{'url': 'https://one.org/a', 'title': 'no'},
                                                        {'url': 'https://two.org/b', 'title': 'speech'}]}
            client.fetch.return_value = {'results': [
                {'url': 'https://two.org/b', 'content': 'valid'},
                {'url': 'https://evil.org/', 'content': 'must not persist'},
                {'url': 'https://two.org/b', 'content': ' ', 'error': 'failed'}]}
            out = Path(tmp) / 'note.md'
            research.refresh('speech', 'test', max_pages=1, out=str(out), fresh=True)
            client.fetch.assert_called_once_with(['https://two.org/b'], purpose='test', fresh=True)
            payload = json.loads(Path(str(out) + '.json').read_text(encoding='utf-8'))
            self.assertEqual(payload['sources'], [{'url': 'https://two.org/b', 'content': 'valid'}])
            self.assertEqual(payload['selection_manifest']['selected'], ['https://two.org/b'])
            self.assertNotIn('must not persist', out.read_text(encoding='utf-8'))

    def test_empty_or_error_refuses(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(research.paths, 'inside_project', return_value=True), patch.object(research, 'TinyFish') as cls:
            cls.return_value.search.return_value = {'results': [{'url': 'https://one.org/a'}]}
            cls.return_value.fetch.return_value = {'results': [{'url': 'https://one.org/a', 'content': 'error', 'error': 'failed'}]}
            with self.assertRaises(RuntimeError):
                research.refresh('q', 'p', out=str(Path(tmp) / 'x.md'))

    def test_fetch_never_caches_unrequested_or_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tf = research.TinyFish.__new__(research.TinyFish)
            tf.cache_dir = Path(tmp)
            with patch.object(tf, '_tool', return_value={'results': [
                {'url': 'https://other.org/', 'content': 'bad'},
                {'url': 'https://one.org/', 'content': 'error', 'error': 'bad'},
                {'url': 'https://one.org/', 'content': 'good'}]}):
                result = tf.fetch(['https://one.org/'], 'test')
            self.assertEqual(len(result['results']), 1)
            self.assertEqual(len(list(Path(tmp).glob('*.json'))), 1)
            self.assertEqual(json.loads(next(Path(tmp).glob('*.json')).read_text(encoding='utf-8'))['content'], 'good')


if __name__ == '__main__':
    unittest.main()
