import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autonomy import research
from autonomy.source_selection import canonical_url, select_sources


class SelectionTests(unittest.TestCase):
    def test_ava_realistic_group_and_cached_original(self):
        base = 'An Audio-Visual Dataset for Active Speaker Detection'
        items = [
            {'url': 'https://ieeexplore.ieee.org/document/9053900', 'title': 'Ava Active Speaker: ' + base},
            {'url': 'https://ui.adsabs.harvard.edu/abs/2019arXiv190101342R/abstract', 'title': base + ' - ADS'},
            {'url': 'https://export.arxiv.org/abs/1901.01342', 'title': base},
            {'url': 'https://arxiv.org/html/1901.01342v2', 'title': 'AVA-ActiveSpeaker: ' + base},
            {'url': 'https://ieeexplore.ieee.org/document/9021951', 'title': 'Supplementary Material: AVA-ActiveSpeaker: ' + base},
            {'url': 'https://github.com/example/ASDNet', 'title': 'ASDNet another unrelated title'},
            {'url': 'https://arxiv.org/pdf/1901.01342v1.pdf'},
        ]
        result = select_sources('active speaker', items, 5, {items[3]['url']})
        self.assertIn(items[3]['url'], result['selected'])
        self.assertIn(items[4]['url'], result['selected'])
        for record in result['candidates'][:2]:
            self.assertEqual(record['mirror_of'], items[3]['url'])
            self.assertEqual(record['dedup_basis'], 'title_candidate')
        self.assertFalse(items[0]['url'] in result['selected'] and items[1]['url'] in result['selected'])
        self.assertNotEqual(result['candidates'][2]['publication_key'], result['candidates'][3]['publication_key'])
        self.assertEqual(result['candidates'][3]['versions'], ['v2'])
        self.assertEqual(result['candidates'][3]['url'], items[3]['url'])

    def test_strong_alias_and_versions(self):
        items = [{'url': 'https://doi.org/10.48550/arXiv.1901.01342'},
                 {'url': 'https://export.arxiv.org/pdf/1901.01342v1.pdf'},
                 {'url': 'https://arxiv.org/html/1901.01342v2'},
                 {'url': 'https://publisher.org/article', 'doi': '10.1234/abc'},
                 {'url': 'https://doi.org/10.1234/ABC'}]
        result = select_sources('', items, 5)
        self.assertEqual(result['selected'], [items[0]['url'], items[1]['url'], items[2]['url'], items[3]['url']])
        self.assertEqual(result['candidates'][1]['versions'], ['v1'])
        self.assertEqual(result['candidates'][2]['versions'], ['v2'])
        self.assertEqual(result['candidates'][0]['dedup_basis'], 'explicit')

    def test_versions_not_substituted_and_duplicate_v2(self):
        items = [{'url': 'https://arxiv.org/abs/1901.01342v2'},
                 {'url': 'https://arxiv.org/html/1901.01342v1'},
                 {'url': 'https://export.arxiv.org/pdf/1901.01342v2.pdf'},
                 {'url': 'https://doi.org/10.48550/arxiv.1901.01342v2'},
                 {'url': 'https://arxiv.org/abs/1901.01342'}]
        result = select_sources('', items, 5, {items[1]['url']})
        self.assertEqual(set(result['selected']), {items[0]['url'], items[1]['url'], items[4]['url']})
        self.assertEqual(result['candidates'][2]['mirror_of'], items[0]['url'])
        self.assertEqual(result['candidates'][3]['mirror_of'], items[0]['url'])
        self.assertIn('arxiv_version', result['candidates'][0]['identity_conflicts'])

    def test_strong_conflicts_and_bridge(self):
        items = [{'url': 'https://one.org/a', 'doi': '10.1234/a', 'arxiv_id': '1901.01342v2'},
                 {'url': 'https://two.org/b', 'doi': '10.1234/b', 'arxiv_id': '1901.01342v2'},
                 {'url': 'https://arxiv.org/html/1901.01342v2'},
                 {'url': 'https://four.org/d', 'doi': '10.1234/a', 'arxiv_id': '1901.99999v2'}]
        result = select_sources('', items, 5)
        self.assertEqual(len(result['selected']), 4)
        self.assertIn('dois', result['candidates'][2]['identity_conflicts'])
        self.assertIn('arxiv', result['candidates'][3]['identity_conflicts'])
        self.assertTrue(all(r['mirror_of'] is None for r in result['candidates']))

    def test_title_attaches_newest_even_when_newer_has_no_title(self):
        title = 'This is a sufficiently long title about active speaker detection'
        items = [{'url': 'https://publisher.org/article', 'title': title},
                 {'url': 'https://arxiv.org/abs/1901.01342v1', 'title': title},
                 {'url': 'https://arxiv.org/html/1901.01342v2'}]
        result = select_sources('', items, 5, {items[1]['url']})
        self.assertEqual(result['candidates'][0]['mirror_of'], items[2]['url'])
        self.assertIsNone(result['candidates'][1]['mirror_of'])

    def test_only_trusted_identity_url_and_exact_metadata(self):
        items = [{'url': 'https://example.org/compare?paper=https%3A%2F%2Farxiv.org%2Fabs%2F1901.01342v2', 'title': 'short title'},
                 {'url': 'https://arxiv.org/abs/1901.01342v2', 'title': 'short title'},
                 {'url': 'https://example.org/arxiv.org/abs/1901.01342v2', 'arxiv_id': 'https://arxiv.org/abs/1901.01342v2'},
                 {'url': 'https://another.org/x', 'doi': 'prefix 10.1234/abc suffix'},
                 {'url': 'https://doi.org/10.1234/abc'}]
        result = select_sources('', items, 5, {items[1]['url']})
        self.assertEqual(len(result['selected']), 5)
        self.assertTrue(all(r['mirror_of'] is None for r in result['candidates']))

    def test_supplement_correction_retraction_separate(self):
        base = 'A very long title about active speaker detection in the wild'
        titles = [base, 'Supplement to: ' + base, 'Supplementary information: ' + base,
                  'Errata: ' + base, 'Corrigendum: ' + base, 'Retraction: ' + base]
        items = [{'url': f'https://example.org/{i}', 'doi': '10.1234/same', 'title': title}
                 for i, title in enumerate(titles)]
        result = select_sources('', items, 5)
        self.assertEqual(len(result['selected']), 4)
        self.assertEqual(result['candidates'][2]['mirror_of'], items[1]['url'])
        self.assertEqual(result['candidates'][4]['mirror_of'], items[3]['url'])

    def test_conflicts_short_title_and_ambiguity(self):
        title = 'This is a sufficiently long title about active speaker detection'
        items = [{'url': 'https://a.org/1', 'title': title, 'doi': '10.1234/a'},
                 {'url': 'https://b.org/2', 'title': title, 'doi': '10.1234/b'},
                 {'url': 'https://c.org/3', 'title': title},
                 {'url': 'https://d.org/4', 'title': 'Short title'},
                 {'url': 'https://e.org/5', 'title': 'Short title'}]
        self.assertEqual(len(select_sources('', items, 5)['selected']), 5)

    def test_unicode_title_and_available_no_guess(self):
        items = [{'url': 'https://one.org/a', 'title': 'A  STUDY of café and speech in noisy settings today'},
                 {'url': 'https://two.org/b', 'title': 'a study of cafe\u0301 and speech in noisy settings today'}]
        result = select_sources('', items, 5, {'https://arxiv.org/html/1234.56789v2'})
        self.assertEqual(result['selected'], [items[0]['url']])
        self.assertEqual(result, select_sources('', items, 5, {'https://arxiv.org/html/1234.56789v2'}))
        self.assertEqual(select_sources('', [{'url': 'http://127.0.0.1/a'}], 1)['selected'], [])

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
            self.assertEqual([(p['url'], p['content']) for p in payload['sources']], [('https://two.org/b', 'valid')])
            self.assertEqual(payload['sources'][0]['retrieval']['method'], 'fetch')
            self.assertNotIn('must not persist', json.dumps(payload))
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
