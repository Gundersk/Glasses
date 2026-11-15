"""Offline regression tests for partial research outcomes; no live execution."""
import copy
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from autonomy import intake, paths, report, request_research as rr, runner, providers, state
from autonomy.tests import test_intake


class PartialTests(unittest.TestCase):
    def setUp(self):
        test_intake.IntakeTests.setUp(self)
        self.spec['research_policy'] = {'topics': ['models', 'limits'], 'min_sources': 2,
                                        'min_domains': 2, 'max_queries': 3}
        intake.submit(self.spec)
        self.card = intake.load(self.spec['id'])
        self.base = intake.root(self.spec['id'])
        self.folder = intake.output_dir(self.card)
        self.folder.mkdir(parents=True)
        self.url = 'https://a.example/page'
        ev = self.base / 'sources-0.md.json'
        ev.write_text(json.dumps({'sources': [{'url': self.url, 'content': 'Real quote on CPU.'}]}), encoding='utf-8')
        self.claims = [{'id': 'C1', 'claim': 'CPU', 'status': 'supported', 'quote': 'Real quote',
                        'source_url': self.url, 'evidence_file': intake.rel(ev)}]
        self.decision = {'roadmap_change': False, 'report_change': False, 'reason': 'synthetic',
                         'owner_actions': [], 'completion_status': 'partial',
                         'limitations': ['Only one source'],
                         'coverage': [{'topic': 'models', 'claim_ids': ['C1']},
                                      {'topic': 'limits', 'claim_ids': [], 'gap': 'No evidence'}]}
        self.text = 'ЧАСТИЧНЫЙ РЕЗУЛЬТАТ C1 ' + self.url + '\n' + 'Synthetic response. ' * 20
        self.save()

    def save(self):
        (self.folder / 'response.md').write_text(self.text, encoding='utf-8')
        (self.folder / 'claims.json').write_text(json.dumps(self.claims), encoding='utf-8')
        (self.folder / 'decision.json').write_text(json.dumps(self.decision), encoding='utf-8')

    def check(self):
        self.save()
        return intake.check_response(self.spec['id'])

    def test_partial_counts_and_explicit_gaps(self):
        result = self.check()
        self.assertTrue(result['pass'])
        self.assertEqual((result['supported_claims'], result['distinct_sources'], result['distinct_domains']), (1, 1, 1))
        self.assertEqual({g['topic'] for g in result['gaps']}, {'limits', 'min_sources', 'min_domains'})
        self.assertFalse(result['coverage_complete'])

    def test_complete_rejects_insufficient_sources(self):
        self.decision['completion_status'] = 'complete'
        with self.assertRaises(ValueError):
            rr.check_coverage(self.card, self.claims, self.decision)

    def test_complete_rejects_empty_topic_even_with_enough_sources(self):
        claims = self.claims + [dict(self.claims[0], id='C2', source_url='https://b.example/page')]
        self.decision['completion_status'] = 'complete'
        with self.assertRaises(ValueError):
            rr.check_coverage(self.card, claims, self.decision)

    def test_complete_accepts_full_coverage(self):
        claims = self.claims + [dict(self.claims[0], id='C2', source_url='https://b.example/page')]
        self.decision['completion_status'] = 'complete'
        self.decision['coverage'][1]['claim_ids'] = ['C2']
        self.assertTrue(rr.check_coverage(self.card, claims, self.decision)['coverage_complete'])

    def test_partial_missing_gap_rejected(self):
        self.decision['coverage'][1].pop('gap')
        with self.assertRaises(ValueError):
            self.check()

    def test_partial_missing_limitations_rejected(self):
        self.decision['limitations'] = []
        with self.assertRaises(ValueError):
            self.check()

    def test_partial_unknown_claim_rejected(self):
        self.decision['coverage'][0]['claim_ids'] = ['unknown']
        with self.assertRaises(ValueError):
            self.check()

    def test_partial_missing_topic_rejected(self):
        self.decision['coverage'].pop()
        with self.assertRaises(ValueError):
            self.check()

    def test_partial_false_quote_rejected(self):
        self.claims[0]['quote'] = 'Invented quotation'
        with self.assertRaises(ValueError):
            self.check()

    def test_partial_label_required(self):
        self.text = self.text.replace('ЧАСТИЧНЫЙ РЕЗУЛЬТАТ', 'RESULT')
        with self.assertRaises(ValueError):
            self.check()

    def test_legacy_partial_rejected(self):
        legacy = copy.deepcopy(self.card)
        legacy['spec'].pop('research_policy')
        with self.assertRaises(ValueError):
            rr.check_coverage(legacy, self.claims, self.decision)
        with patch.object(intake, 'load', return_value=legacy), self.assertRaises(ValueError):
            self.check()

    def review(self, verdict):
        self.save()
        task = {'id': 'answer-mentor', 'status': 'pending', 'goal': 'synthetic', 'acceptance': []}
        st = {'phase': 'REVIEW', 'tasks': [task], 'task': {'id': task['id'], 'verify': {'pass': True}, 'errors': []},
              'history': [], 'violations': []}
        rt = Mock()
        rt.call.return_value.text = json.dumps({'verdict': verdict, 'reason': 'synthetic'})
        with patch.object(runner, '_ACTIVE_REQUEST', self.card), \
             patch.object(runner, '_require_approval', return_value=True), \
             patch.object(runner, '_verified_result', return_value={'pass': True}), \
             patch.object(runner, '_sync_plan'), patch.object(runner.events, 'emit'), \
             patch('autonomy.shellutil.run_command', side_effect=AssertionError('unexpected command')) as command:
            runner.phase_review({}, st, Mock(), rt)
        rt.call.assert_called_once()
        self.assertEqual(rt.call.call_args.args[0], 'verifier')
        command.assert_not_called()
        return st, task

    def test_review_partial_never_done(self):
        st, task = self.review('PARTIAL')
        self.assertEqual((task['status'], st['request_outcome'], st['phase']), ('partial', 'partial', 'REPORT'))
        self.assertTrue(st['request_gaps'])

    def test_review_pass_cannot_promote_partial(self):
        st, task = self.review('PASS')
        self.assertEqual(st['phase'], 'EXECUTE')
        self.assertNotEqual(task['status'], 'done')

    def test_review_partial_cannot_accept_complete(self):
        self.claims.append(dict(self.claims[0], id='C2', source_url='https://b.example/page', quote='Other quote'))
        ev = self.base / 'sources-0.md.json'
        ev.write_text(json.dumps({'sources': [{'url': self.url, 'content': 'Real quote on CPU.'},
                                               {'url': 'https://b.example/page', 'content': 'Other quote'}]}), encoding='utf-8')
        self.text += ' C2 https://b.example/page'
        self.decision['completion_status'] = 'complete'
        self.decision['coverage'][1]['claim_ids'] = ['C2']
        self.assertEqual(self.check()['completion_status'], 'complete')
        st, task = self.review('PARTIAL')
        self.assertEqual(st['phase'], 'EXECUTE')
        self.assertNotEqual(task['status'], 'done')

    def test_report_and_digest_distinguish_partial(self):
        facts = {'night_id': 'offline', 'request_id': self.spec['id'], 'request_sha256': 'synthetic',
                 'request_outcome': 'partial', 'request_gaps': [{'topic': 'limits', 'reason': 'No evidence'}],
                 'request_limitations': ['Only one source'], 'tasks': []}
        rendered = report.render(facts)
        with patch.object(paths, 'WORKSPACE', self.root), patch.object(paths, 'OUTBOX_DIR', self.root / 'outbox'):
            report.write_digest({'phase': 'REPORT', 'tasks': []}, facts, {}, Mock())
        digest = (self.root / 'digest.md').read_text(encoding='utf-8')
        for text in (rendered, digest):
            self.assertIn('частичный результат', text.lower())
            self.assertIn('No evidence', text)
            self.assertIn('Only one source', text)
            self.assertNotIn('ответ принят REVIEW', text)

    def test_partial_with_corrupt_evidence_rejected(self):
        (self.base / 'sources-0.md.json').write_text('broken JSON')
        with self.assertRaises(ValueError):
            self.check()

    def test_budget_stop_before_review_keeps_draft_blocked(self):
        with intake.runtime(self.spec['id']):
            cfg = runner.load_config()
            cfg['night']['report_interpretation_enabled'] = False
            st = state.default_state()
            st.update(phase='REPORT', tasks=[{'id': 'answer-mentor', 'status': 'pending'}],
                      last_error='verifier: budget exhausted', needs_human='REVIEW unavailable')
            rt = Mock()
            runner.phase_report(cfg, st, Mock(), rt)
            facts = json.loads((paths.OUTBOX_DIR / 'facts.json').read_text(encoding='utf-8'))
            self.assertEqual(facts['request_outcome'], 'blocked')
            self.assertTrue((self.folder / 'response.md').exists())
            rt.call.assert_not_called()

    def test_full_partial_route_with_bound_receipts_and_verdicts(self):
        for name in ('response.md', 'claims.json', 'decision.json'):
            (self.folder / name).unlink()
        (self.base / 'sources-0.md.json').unlink()
        commands, roles = [], []
        with intake.runtime(self.spec['id']) as card:
            cfg = runner.load_config()
            cfg['night']['report_interpretation_enabled'] = False
            st = state.default_state()
            st['phase'] = 'PLAN'
            review_count = [0]
            def model(role, *args, **kwargs):
                roles.append(role)
                if role == 'critic':
                    answer = {'verdict': 'approve', 'summary': 'fixture', 'objections': [],
                              'needs_search': [], 'defense_value': []}
                elif role == 'executor':
                    answer = {'files': {
                        intake.rel(self.folder / 'response.md'): self.text,
                        intake.rel(self.folder / 'claims.json'): json.dumps(self.claims),
                        intake.rel(self.folder / 'decision.json'): json.dumps(self.decision)}, 'commands': []}
                elif role == 'verifier':
                    review_count[0] += 1
                    answer = {'verdict': 'PASS' if review_count[0] == 1 else 'PARTIAL', 'reason': 'fixture'}
                else:
                    self.fail('Unexpected model role: ' + role)
                return providers.Result(json.dumps(answer), 'fixture', 'fixture-' + role, 0, 0, 0, 0)
            def command(cmd, cwd, timeout):
                commands.append(cmd)
                if 'autonomy.research' in cmd:
                    (self.base / 'sources-0.md').write_text('Saved fixture source')
                    (self.base / 'sources-0.md.json').write_text(json.dumps({'sources': [
                        {'url': self.url, 'content': 'Real quote on CPU.'}]}))
                else:
                    self.assertIn('autonomy.intake check', cmd)
                    intake.check_response(self.spec['id'])
                return subprocess.CompletedProcess(cmd, 0, 'fixture', '')
            rt = Mock()
            rt.call.side_effect = model
            with patch('requests.post', side_effect=AssertionError('network forbidden')), \
                 patch('autonomy.shellutil.run_command', side_effect=command), \
                 patch.object(runner, '_DEADLINE', None):
                for _ in range(20):
                    if st['phase'] == 'DONE':
                        break
                    getattr(runner, 'phase_' + st['phase'].lower())(cfg, st, Mock(), rt)
                    state.save(st)
            self.assertEqual(st['phase'], 'DONE')  # process finished, not assignment complete
            self.assertEqual([t['status'] for t in st['tasks']], ['done', 'partial'])
            self.assertEqual(roles, ['critic', 'verifier', 'executor', 'verifier'])
            self.assertEqual(len(commands), 1)  # Response validation is typed/direct, not a subprocess.
            self.assertIn({'mentor_response': self.spec['id']}, st['tasks'][-1]['acceptance'])
            self.assertIsNotNone(runner._verified_result(st['tasks'][0], st['tasks'][0]))
            self.assertIsNotNone(runner._verified_result(st['tasks'][1], st['tasks'][1]))
            facts = json.loads((paths.OUTBOX_DIR / 'facts.json').read_text(encoding='utf-8'))
            self.assertEqual(facts['request_outcome'], 'partial')
            self.assertTrue(facts['request_gaps'])
            self.assertIn('ЧАСТИЧНЫЙ РЕЗУЛЬТАТ', (paths.WORKSPACE / 'digest.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
