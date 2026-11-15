"""Offline integration of machine limits, clocks and real temporary receipts."""
import copy
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from autonomy import intake, paths, providers, request_limits, runner, state
from autonomy.tests import test_intake


class LimitIntegrationTests(unittest.TestCase):
    def setUp(self):
        test_intake.IntakeTests.setUp(self)
        self.spec['research_policy'] = {'topics': ['methods', 'metrics'], 'min_sources': 2,
                                        'min_domains': 2, 'max_queries': 3}
        intake.submit(self.spec)

    @staticmethod
    def result(data, model='fixture-reviewer'):
        return providers.Result(json.dumps(data), 'fixture', model, 0, 0, 0, 0)

    def approve(self):
        return self.result({'verdict': 'approve', 'summary': 'fixture', 'objections': [],
                            'needs_search': [], 'defense_value': []})

    @staticmethod
    def contract(text):
        marker = '=== МАШИННЫЙ КОНТРАКТ ЛИМИТОВ (текущий, не исторический STATUS) ==='
        return json.JSONDecoder().raw_decode(text.split(marker, 1)[1].lstrip())[0]

    def test_critic_gets_one_fresh_contract_before_and_after_revision(self):
        with intake.runtime(self.spec['id']) as card:
            original = copy.deepcopy(card)
            cfg, st, rt = runner.load_config(), state.default_state(), Mock()
            st['phase'] = 'PLAN'
            rt.call.side_effect = [
                self.result({'verdict': 'revise', 'summary': 'improve coverage',
                    'objections': [{'task_id': 'collect-sources', 'severity': 'high',
                                    'issue': 'gap', 'fix': 'broaden query'}], 'needs_search': [], 'defense_value': []}),
                self.result({'queries': ['broader research methods', 'metric evaluation definitions'],
                             'reason': 'cover both topics'}, 'fixture-author'),
                self.approve(),
            ]
            runner.phase_plan(cfg, st, Mock(), rt)
            self.assertEqual(st['phase'], 'EXECUTE')
            critic_messages = [c.args[2][1]['content'] for c in rt.call.call_args_list if c.args[0] == 'critic']
            self.assertEqual(len(critic_messages), 2)
            for index, message in enumerate(critic_messages):
                self.assertEqual(message.count('=== МАШИННЫЙ КОНТРАКТ ЛИМИТОВ'), 1)
                limits = self.contract(message)
                self.assertEqual(limits['counts']['followup_rounds'], {'allowed': 1, 'used': 0, 'remaining': 1})
                self.assertEqual(limits['counts']['plan_revisions']['used'], index)
                self.assertEqual(limits['counts']['plan_revisions']['remaining'], 1 - index)
                self.assertEqual(limits['time']['work_total']['allowed_seconds'], 1500)
                self.assertEqual(limits['time']['coordinator']['allowed_seconds'], 3000)
            self.assertEqual(card, original)
            self.assertEqual(intake.load(self.spec['id']), original)

    def test_followup_uses_shared_remainder_without_replaying_accepted_collection(self):
        with intake.runtime(self.spec['id']) as card:
            cfg, st, rt = runner.load_config(), state.default_state(), Mock()
            st['phase'] = 'PLAN'
            rt.call.return_value = self.approve()
            runner.phase_plan(cfg, st, Mock(), rt)
            calls = []
            def command(cmd, cwd, timeout):
                calls.append((cmd, timeout))
                number = 0 if 'sources-0.md' in cmd else 1
                base = intake.root(self.spec['id'])
                (base / f'sources-{number}.md').write_text('Saved fixture source')
                (base / f'sources-{number}.md.json').write_text(json.dumps({'sources': [
                    {'url': f'https://example.org/paper{number}', 'content': 'A source for the methods.'}]}))
                return subprocess.CompletedProcess(cmd, 0, 'fixture', '')
            with patch('requests.post', side_effect=AssertionError('network forbidden')), \
                 patch('autonomy.shellutil.run_command', side_effect=command), \
                 patch.object(runner, '_DEADLINE', None):
                with patch.object(request_limits.time, 'monotonic', side_effect=[100., 500.]):
                    runner.phase_execute(cfg, st, Mock(), rt)
                runner.phase_verify(cfg, st, Mock(), rt)
                rt.call.return_value = self.result({'verdict': 'SEARCH', 'reason': 'metrics gap',
                                                    'research_queries': ['metric dataset evaluation']})
                runner.phase_review(cfg, st, Mock(), rt)
                self.assertEqual(st['phase'], 'PLAN')
                accepted = copy.deepcopy(st['tasks'][0])
                self.assertIsNotNone(runner._verified_result(accepted, accepted))
                rt.call.return_value = self.approve()
                runner.phase_plan(cfg, st, Mock(), rt)
                self.assertEqual(request_limits.remaining(card, st, 'sources'), 200.)
                with patch.object(request_limits.time, 'monotonic', side_effect=[1000., 1050.]):
                    runner.phase_execute(cfg, st, Mock(), rt)
                self.assertEqual(st['phase'], 'VERIFY')
                self.assertEqual(st['tasks'][0], accepted)
                self.assertIsNotNone(runner._verified_result(accepted, accepted))
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(calls[0][0], calls[1][0])
            self.assertLessEqual(calls[1][1], 200.)
            self.assertEqual(st['request_work_seconds']['sources'], 450.)
            self.assertEqual(st['request_sources_attempted'], 2)
            snapshot = request_limits.snapshot(card, st)
            self.assertEqual(snapshot['counts']['queries']['used'], 2)
            self.assertEqual(snapshot['time']['sources']['remaining_seconds'], 150.)

    def test_exhausted_answer_clock_starts_no_model_or_write(self):
        with intake.runtime(self.spec['id']) as card:
            task = intake.build_plan(card)[-1]
            task['depends_on'] = []
            st, rt = state.default_state(), Mock()
            st.update(phase='EXECUTE', tasks=[task], request_answer_attempts=1,
                      request_work_seconds={'sources': 0., 'answer': 900.})
            with patch.object(runner, '_require_approval', return_value=True):
                runner.phase_execute(runner.load_config(), st, Mock(), rt)
            self.assertEqual(st['phase'], 'REPORT')
            self.assertEqual(st['request_answer_attempts'], 1)
            rt.call.assert_not_called()
            self.assertFalse(intake.output_dir(card).exists())

    def test_exhausted_source_clock_starts_no_command(self):
        with intake.runtime(self.spec['id']) as card:
            task = intake.build_plan(card)[0]
            st, rt = state.default_state(), Mock()
            st.update(phase='EXECUTE', tasks=[task], request_work_seconds={'sources': 600., 'answer': 0.})
            with patch.object(runner, '_require_approval', return_value=True), \
                 patch('autonomy.shellutil.run_command') as command:
                runner.phase_execute(runner.load_config(), st, Mock(), rt)
            self.assertEqual(st['phase'], 'REPORT')
            command.assert_not_called()
            rt.call.assert_not_called()
            self.assertNotIn('request_sources_attempted', st)

    def test_planned_queries_are_not_spent_queries(self):
        with intake.runtime(self.spec['id']) as card:
            snap = request_limits.snapshot(card, state.default_state())
            self.assertEqual(snap['counts']['queries'], {
                'allowed': 3, 'used': 0, 'remaining': 3, 'planned': 1, 'unplanned_capacity': 2})
            tasks = intake.build_plan(card)
            self.assertEqual(tasks[0]['time_budget']['scope'], 'shared_request_lane')
            self.assertEqual(tasks[1]['time_budget']['allowed_seconds'], 900.)

    def test_report_and_digest_surface_same_machine_contract(self):
        with intake.runtime(self.spec['id']):
            cfg, st, rt = runner.load_config(), state.default_state(), Mock()
            cfg['night']['report_interpretation_enabled'] = False
            st.update(phase='REPORT', request_work_seconds={'sources': 400., 'answer': 200.})
            runner.phase_report(cfg, st, Mock(), rt)
            facts = json.loads((paths.OUTBOX_DIR / 'facts.json').read_text(encoding='utf-8'))
            self.assertEqual(facts['request_limits']['time']['work_total']['used_seconds'], 600.)
            for path in (paths.OUTBOX_DIR / 'report.md', paths.WORKSPACE / 'digest.md'):
                text = path.read_text(encoding='utf-8')
                self.assertIn('followup_rounds: 1 / 0 / 1', text)
                self.assertIn('Время sources, с: 600.0 / 400.0 / 200.0', text)
            rt.call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
