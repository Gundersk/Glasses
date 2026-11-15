"""Offline synthetic archive tests; never read the project workspace."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from autonomy import paths, source_archive as archive


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.patcher = patch.object(paths, 'PROJECT_ROOT', self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.base = self.root / 'autonomy/workspace/requests'
        self.base.mkdir(parents=True)
        self.now = datetime.now(timezone.utc)

    def fixture(self, request='r1', source='sources-0.md.json', accessed=None, url='https://arxiv.org/html/1901.01342v2', content='synthetic text'):
        directory = self.base / request
        directory.mkdir(exist_ok=True)
        file = directory / source
        doc = {'accessed': (accessed or self.now.isoformat()), 'sources': [{'url': url, 'content': content}]}
        file.write_text(json.dumps(doc), encoding='utf-8')
        rel = file.relative_to(self.root).as_posix()
        command = f"python -m autonomy.research --query q --out '{rel[:-5]}'"
        rec = {'version': 2, 'mock': False, 'execution': 'approved_commands',
               'outputs_after': [{'path': rel, 'status': 'file', 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                                  'size': file.stat().st_size, 'mtime_ns': file.stat().st_mtime_ns}],
               'commands': [{'command': command, 'command_sha256': hashlib.sha256(command.encode()).hexdigest(),
                             'status': 'completed', 'returncode': 0}]}
        receipt = directory / 'run/evidence/001/receipt.json'
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(rec), encoding='utf-8')
        return file, receipt, doc, rec

    def save(self, file, value):
        file.write_text(json.dumps(value), encoding='utf-8')

    def update_doc(self, file, receipt, doc, rec):
        self.save(file, doc)
        rec['outputs_after'][0].update(sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                                       size=file.stat().st_size, mtime_ns=file.stat().st_mtime_ns)
        self.save(receipt, rec)

    def test_valid_exact_url_and_deepcopy(self):
        self.fixture()
        index = archive.scan_archive()
        self.assertEqual(len(index), 1)
        url = next(iter(index))
        record = archive.reuse_page(index, url)
        self.assertEqual(record['url'], 'https://arxiv.org/html/1901.01342v2')
        self.assertIsNone(archive.reuse_page(index, 'https://arxiv.org/html/1901.01342v1'))
        record['retrieval']['method'] = 'changed'
        self.assertEqual(index[url]['retrieval']['method'], 'archive')

    def test_mock_rejected(self):
        _, receipt, _, rec = self.fixture()
        rec['mock'] = True
        self.save(receipt, rec)
        self.assertEqual(archive.scan_archive(), {})

    def test_fingerprint_mismatch(self):
        _, receipt, _, rec = self.fixture()
        rec['outputs_after'][0]['sha256'] = '0' * 64
        self.save(receipt, rec)
        self.assertEqual(archive.scan_archive(), {})

    def test_source_tamper(self):
        file, _, _, _ = self.fixture()
        index = archive.scan_archive()
        file.write_text('{}', encoding='utf-8')
        self.assertIsNone(archive.reuse_page(index, next(iter(index))))

    def test_receipt_tamper(self):
        _, receipt, _, rec = self.fixture()
        index = archive.scan_archive()
        rec['extra'] = 1
        self.save(receipt, rec)
        self.assertIsNone(archive.reuse_page(index, next(iter(index))))

    def test_old_future_missing_and_naive_dates(self):
        for value in [(self.now - timedelta(days=31)).isoformat(), (self.now + timedelta(minutes=6)).isoformat(), '2026-01-01', '']:
            with self.subTest(value=value):
                file, receipt, doc, rec = self.fixture(accessed=value or self.now.isoformat())
                doc['accessed'] = value
                self.save(file, doc)
                rec['outputs_after'][0].update(sha256=hashlib.sha256(file.read_bytes()).hexdigest(), size=file.stat().st_size, mtime_ns=file.stat().st_mtime_ns)
                self.save(receipt, rec)
                self.assertEqual(archive.scan_archive(), {})

    def test_partial_run(self):
        _, receipt, _, rec = self.fixture()
        rec['commands'].append({'status': 'completed', 'returncode': 1})
        self.save(receipt, rec)
        self.assertEqual(len(archive.scan_archive()), 1)

    def test_command_hash_and_output_required(self):
        _, receipt, _, rec = self.fixture()
        rec['commands'][0]['command_sha256'] = '0' * 64
        self.save(receipt, rec)
        self.assertEqual(archive.scan_archive(), {})

    def test_private_and_loose_cache(self):
        self.fixture(url='http://127.0.0.1/private')
        (self.base / 'page.json').write_text('{}')
        self.assertEqual(archive.scan_archive(), {})
        self.assertIsNone(archive.reuse_page({}, 'file:///secret'))

    def test_symlink_rejected(self):
        file, _, _, _ = self.fixture()
        link = self.base / 'r2'
        try:
            link.symlink_to(file.parent, target_is_directory=True)
        except OSError:
            self.skipTest('symlink creation unavailable')
        self.assertEqual(len(archive.scan_archive()), 1)
        self.assertEqual(archive.scan_archive(exclude_request_id='r1'), {})

    def test_newest_and_exclusion(self):
        self.fixture('a', accessed=(self.now - timedelta(days=1)).isoformat(), content='older')
        self.fixture('b', content='newer')
        self.assertEqual(next(iter(archive.scan_archive().values()))['content'], 'newer')
        self.assertEqual(next(iter(archive.scan_archive(exclude_request_id='b').values()))['content'], 'older')

    def test_directory_bound(self):
        self.fixture('000')
        for i in range(1, 101):
            (self.base / f'{i:03}').mkdir()
        self.assertEqual(archive.scan_archive(), {})

    def test_unavailable_and_invalid_page(self):
        file, receipt, doc, rec = self.fixture(content=' ')
        self.assertEqual(archive.scan_archive(), {})
        doc['collection_status'] = 'unavailable'
        doc['sources'][0]['content'] = 'text'
        self.save(file, doc)
        rec['outputs_after'][0].update(sha256=hashlib.sha256(file.read_bytes()).hexdigest(), size=file.stat().st_size, mtime_ns=file.stat().st_mtime_ns)
        self.save(receipt, rec)
        self.assertEqual(archive.scan_archive(), {})

    def test_revalidation_outside(self):
        self.fixture()
        index = archive.scan_archive()
        key = next(iter(index))
        index[key]['retrieval']['source_path'] = '../secret'
        self.assertIsNone(archive.reuse_page(index, key))

    def test_chain_fresh_header_expired_original(self):
        file, receipt, doc, rec = self.fixture()
        doc['sources'][0]['retrieval'] = {'method': 'archive', 'original_accessed': (self.now - timedelta(days=31)).isoformat()}
        self.update_doc(file, receipt, doc, rec)
        self.assertEqual(archive.scan_archive(), {})

    def test_chain_original_preserved_and_cannot_be_forged(self):
        file, receipt, doc, rec = self.fixture()
        original = (self.now - timedelta(days=2)).isoformat()
        doc['sources'][0]['retrieval'] = {'method': 'archive', 'original_accessed': original}
        self.update_doc(file, receipt, doc, rec)
        index = archive.scan_archive(max_age_days=3)
        key = next(iter(index))
        self.assertEqual(index[key]['retrieval']['original_accessed'], original)
        self.assertEqual(index[key]['retrieval']['captured_accessed'], doc['accessed'])
        self.assertIsNotNone(archive.reuse_page(index, key))
        index[key]['retrieval']['original_accessed'] = doc['accessed']
        self.assertIsNone(archive.reuse_page(index, key))

    def test_ttl_expires_between_scan_and_reuse(self):
        self.fixture(accessed=(self.now - timedelta(days=1)).isoformat())
        index = archive.scan_archive(max_age_days=2)
        key = next(iter(index))
        future = self.now + timedelta(days=2)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return future

        with patch.object(archive, 'datetime', Clock):
            self.assertIsNone(archive.reuse_page(index, key, max_age_days=2))

    def test_reuse_ttl_is_trusted_policy_not_index(self):
        self.fixture(accessed=(self.now - timedelta(days=31)).isoformat())
        index = archive.scan_archive(max_age_days=60)
        key = next(iter(index))
        index[key]['retrieval']['max_age_days'] = 36500
        self.assertIsNone(archive.reuse_page(index, key))
        self.assertIsNotNone(archive.reuse_page(index, key, max_age_days=60))
        for invalid in (True, False, -1, 366, float('nan'), float('inf')):
            with self.subTest(invalid=invalid):
                self.assertIsNone(archive.reuse_page(index, key, max_age_days=invalid))

    def test_bad_pages_rejected_even_with_valid_receipt(self):
        for field, value in [('error', 'blocked'), ('status', 403), ('content', 'Just a moment... captcha')]:
            with self.subTest(field=field):
                file, receipt, doc, rec = self.fixture()
                doc['sources'][0][field] = value
                self.update_doc(file, receipt, doc, rec)
                self.assertEqual(archive.scan_archive(), {})

    def test_reuse_rejects_forged_index_for_bad_page(self):
        file, receipt, doc, rec = self.fixture()
        index = archive.scan_archive()
        key = next(iter(index))
        doc['sources'][0]['error'] = 'blocked'
        self.update_doc(file, receipt, doc, rec)
        index[key]['retrieval']['source_sha256'] = hashlib.sha256(file.read_bytes()).hexdigest()
        index[key]['retrieval']['receipt_sha256'] = hashlib.sha256(receipt.read_bytes()).hexdigest()
        self.assertIsNone(archive.reuse_page(index, key))

    def test_per_page_date_invalid_does_not_hide_valid_page(self):
        file, receipt, doc, rec = self.fixture()
        doc['sources'].insert(0, {'url': 'https://example.com/old', 'content': 'valid text',
                                  'retrieval': {'method': 'archive', 'original_accessed': 'invalid'}})
        self.update_doc(file, receipt, doc, rec)
        self.assertEqual(len(archive.scan_archive()), 1)

    def test_invalid_header_even_with_valid_original(self):
        file, receipt, doc, rec = self.fixture()
        doc['sources'][0]['retrieval'] = {'method': 'archive', 'original_accessed': self.now.isoformat()}
        doc['accessed'] = '2026-11-15'
        self.update_doc(file, receipt, doc, rec)
        self.assertEqual(archive.scan_archive(), {})


if __name__ == '__main__':
    unittest.main()
