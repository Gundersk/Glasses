"""Offline routing, archive provenance, opt-in and reader-accounting regressions."""
import json
import unittest
from unittest.mock import Mock, patch

import requests

from autonomy import intake, research, retrieval, runner, state, providers, valyu_reader
from autonomy.router import Router
from autonomy.tests import test_intake, test_source_archive


class RouteTests(unittest.TestCase):
    setUp = test_source_archive.ArchiveTests.setUp
    fixture = test_source_archive.ArchiveTests.fixture

    def client(self):
        client = Mock()
        client.search.return_value = {'results': [{'url': 'https://example.org/page', 'title': 'CPU methods paper'}]}
        return client

    def test_archive_copy_selected_and_used_without_reader_network(self):
        url = 'https://arxiv.org/html/1901.01342v2'
        self.fixture(content='AVA Active Speaker original archived text')
        client = self.client()
        client.search.return_value = {'results': [
            {'url': 'https://ieeexplore.ieee.org/document/9053900', 'title': 'Ava Active Speaker: An Audio-Visual Dataset for Active Speaker Detection'},
            {'url': url, 'title': 'AVA-ActiveSpeaker: An Audio-Visual Dataset for Active Speaker Detection'}]}
        with patch.object(valyu_reader, 'read_page') as paid:
            _, manifest, fetched, log = retrieval.acquire(client, 'active speaker dataset', 'fixture',
                max_pages=1, fresh=True, reuse_archive=True, scope_id='new')
        self.assertEqual(manifest['selected'], [url])
        self.assertEqual(fetched['results'][0]['url'], url)
        self.assertEqual(fetched['results'][0]['retrieval']['method'], 'archive')
        self.assertTrue(any(e.get('provider') == 'archive' for e in log))
        client.fetch.assert_not_called()
        paid.assert_not_called()

    def test_search_transport_failure_can_use_authorized_local_candidates(self):
        self.fixture(content='AVA Active Speaker dataset original archived text')
        client = self.client()
        client.search.side_effect = requests.Timeout('PRIVATE backend message')
        _, _, fetched, log = retrieval.acquire(client, 'active speaker dataset', 'fixture', max_pages=1,
                                              fresh=True, reuse_archive=True, scope_id='new')
        self.assertEqual(len(fetched['results']), 1)
        self.assertTrue(any(e.get('operation') == 'local_candidates' for e in log))
        self.assertNotIn('PRIVATE', json.dumps(log))
        client.fetch.assert_not_called()

    def test_funded_fallback_only_reads_exact_attributed_url_once(self):
        url = 'https://example.org/page'
        client = self.client()
        client.fetch.return_value = {'results': [], 'errors': [{'url': url, 'error': 'bot_blocked'}]}
        outcome = {'page': {'url': url, 'content': 'Retrieved source'},
                   'attempt': {'provider': 'valyu', 'requested_url': url, 'reserved_usd': .01}}
        with patch.object(valyu_reader, 'read_page', return_value=outcome) as paid:
            _, _, fetched, _ = retrieval.acquire(client, 'CPU methods', 'fixture', max_pages=1, fresh=True,
                scope_id='new', reader_budget_usd=.02, reader_max_calls=2)
        paid.assert_called_once_with(url, scope_id='new', budget_usd=.02, max_calls=2)
        self.assertEqual(len(fetched['results']), 1)
        self.assertEqual(fetched['errors'], [])

    def test_no_budget_or_unattributed_error_never_calls_paid_reader(self):
        for budget, errors in ((0, [{'error': 'bot_blocked'}]), (.02, [{'error': 'bot_blocked'}])):
            client = self.client()
            client.fetch.return_value = {'results': [], 'errors': errors}
            with patch.object(valyu_reader, 'read_page') as paid:
                _, _, fetched, log = retrieval.acquire(client, 'CPU', 'fixture', max_pages=1, fresh=True,
                    scope_id='new', reader_budget_usd=budget, reader_max_calls=2 if budget else 0)
            paid.assert_not_called()
            self.assertEqual(fetched['results'], [])

    def test_incomplete_failure_attribution_rejected_before_paid_request(self):
        client = self.client()
        client.search.return_value = {'results': [{'url': 'https://one.org/a'}, {'url': 'https://two.org/b'}]}
        client.fetch.return_value = {'results': [], 'errors': [{'url': 'https://one.org/a', 'error': 'bot_blocked'}]}
        with patch.object(valyu_reader, 'read_page') as paid, self.assertRaises(RuntimeError):
            retrieval.acquire(client, 'CPU', 'fixture', max_pages=2, fresh=True, scope_id='new',
                              reader_budget_usd=.02, reader_max_calls=2)
        paid.assert_not_called()

    def test_unknown_schema_never_triggers_paid_fallback(self):
        client = self.client()
        client.fetch.return_value = {'results': [], 'errors': [{'error': 'schema_error'}]}
        with patch.object(valyu_reader, 'read_page') as paid, self.assertRaises(RuntimeError):
            retrieval.acquire(client, 'CPU', 'fixture', max_pages=1, fresh=True, scope_id='new',
                              reader_budget_usd=.02, reader_max_calls=2)
        paid.assert_not_called()

    def test_event_journal_survives_fatal_reader_failure(self):
        client = self.client()
        client.fetch.side_effect = RuntimeError('PRIVATE schema error')
        events = []
        with self.assertRaises(RuntimeError):
            retrieval.acquire(client, 'CPU', 'fixture', max_pages=1, fresh=True, event_sink=events.append)
        self.assertTrue(events)
        self.assertNotIn('PRIVATE', json.dumps(events))

    def test_json_decode_error_never_becomes_transport_fallback(self):
        client = self.client()
        client.fetch.side_effect = requests.exceptions.JSONDecodeError('invalid', '{', 0)
        with patch.object(valyu_reader, 'read_page') as paid, self.assertRaises(RuntimeError):
            retrieval.acquire(client, 'CPU', 'fixture', max_pages=1, fresh=True, scope_id='new',
                              reader_budget_usd=.02, reader_max_calls=2)
        paid.assert_not_called()

    def test_attributed_http503_uses_same_fallback_predicate(self):
        client = self.client()
        url = 'https://example.org/page'
        client.fetch.return_value = {'results': [], 'errors': [{'url': url, 'error': 'http_503'}]}
        with patch.object(valyu_reader, 'read_page', return_value={
                'page': {'url': url, 'content': 'Actual page'}, 'attempt': {'provider': 'valyu'}}) as paid:
            _, _, fetched, _ = retrieval.acquire(client, 'CPU', 'fixture', max_pages=1, fresh=True,
                scope_id='new', reader_budget_usd=.02, reader_max_calls=2)
        paid.assert_called_once()
        self.assertEqual(fetched['errors'], [])

    def test_provider_wide_valyu_denial_not_retried_for_each_url(self):
        client = self.client()
        urls = ['https://one.org/a', 'https://two.org/b']
        client.search.return_value = {'results': [{'url': url} for url in urls]}
        client.fetch.return_value = {'results': [], 'errors': [{'url': url, 'error': 'bot_blocked'} for url in urls]}
        with patch.object(valyu_reader, 'read_page', side_effect=valyu_reader.ValyuUnavailable('missing_key')) as paid:
            _, _, fetched, log = retrieval.acquire(client, 'CPU', 'fixture', max_pages=2, fresh=True,
                scope_id='new', reader_budget_usd=.02, reader_max_calls=2)
        self.assertEqual(paid.call_count, 1)
        self.assertEqual(len(fetched['errors']), 2)


class AccountingPolicyTests(unittest.TestCase):
    setUp = test_intake.IntakeTests.setUp

    def enable(self):
        self.spec['research_policy'] = {'topics': ['methods'], 'max_queries': 3,
            'reuse_sources': True, 'retrieval_budget_usd': .02, 'max_reader_calls': 2}

    def test_opt_in_plan_flags_and_legacy_fields_not_inserted(self):
        plain = {'topics': ['methods']}
        from autonomy.request_research import validate_policy
        old = validate_policy(plain, self.spec['research_queries'])
        self.assertNotIn('reuse_sources', old)
        self.assertNotIn('retrieval_budget_usd', old)
        self.enable()
        intake.submit(self.spec)
        card = intake.load(self.spec['id'])
        command = intake.build_plan(card)[0]['commands'][0]
        self.assertIn('--reuse-archive', command)
        self.assertIn('--reader-budget-usd 0.02', command)
        self.assertIn('--reader-max-calls 2', command)
        self.assertEqual(intake.load(self.spec['id'])['sha256'], card['sha256'])

    def test_reader_subbudget_not_larger_than_whole_request(self):
        self.enable()
        self.spec['budget_usd'] = .01
        with self.assertRaises(ValueError):
            intake.validate(self.spec)

    def test_reader_usage_charged_once_and_pending_reserve_protects_model_budget(self):
        self.enable()
        intake.submit(self.spec)
        card = intake.load(self.spec['id'])
        with intake.runtime(self.spec['id']), patch.object(state, 'save'):
            cfg = runner.load_config()
            st = state.default_state()
            usage = dict(counts=1, reserved_usd=.01, reported_cost_usd=0, unknown_cost_attempts=1, charge_usd=.01)
            with patch.object(valyu_reader, 'usage', return_value=usage):
                runner._sync_reader_usage(cfg, st)
                runner._sync_reader_usage(cfg, st)
            self.assertEqual(st['budget_used_usd'], .01)
            self.assertAlmostEqual(Router(cfg, Mock())._budget_left(st), .48)

    def test_mixed_cost_overrun_sets_terminal_block_before_any_new_call(self):
        self.enable()
        intake.submit(self.spec)
        card = intake.load(self.spec['id'])
        with intake.runtime(self.spec['id']), patch.object(state, 'save'):
            cfg = runner.load_config()
            st = state.default_state()
            usage = dict(counts=2, reserved_usd=.02, reported_cost_usd=.015, unknown_cost_attempts=1, charge_usd=.025)
            with patch.object(valyu_reader, 'usage', return_value=usage), self.assertRaises(ValueError):
                runner._sync_reader_usage(cfg, st)
            self.assertEqual(st['budget_used_usd'], .025)
            self.assertTrue(st['paid_work_blocked'])
            with patch.object(providers, 'chat') as chat, self.assertRaises(providers.ProviderError):
                Router(cfg, Mock()).call('planner', st, [])
            chat.assert_not_called()
            rt = Mock()
            runner.phase_execute(cfg, st, Mock(), rt)
            self.assertEqual(st['phase'], 'REPORT')
            rt.call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
