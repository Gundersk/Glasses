"""Context completeness, handoff recovery and pre-call manifests, offline only."""
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from autonomy import context_packets, intake, paths, providers, runner, state
from autonomy.tests import test_intake


class ContextPipelineTests(unittest.TestCase):
    setUp = test_intake.IntakeTests.setUp
    submit = test_intake.IntakeTests.submit
    answer = test_intake.IntakeTests.answer

    def review_state(self):
        folder, claims = self.answer()
        card = intake.load(self.spec['id'])
        task = intake.build_plan(card)[-1]
        verdict = {'pass': True, 'checks': [], 'diff': {'added': [], 'modified': [], 'deleted': []}}
        st = state.default_state()
        st.update(phase='REVIEW', tasks=[task], task={'id': task['id'], 'iter': 1,
                  'errors': [], 'verify': verdict})
        return card, folder, task, verdict, st

    def review(self, card, verdict, st, *, max_chars=220000, on_call=None):
        cfg = {'night': {'context_audit_enabled': True, 'context_max_chars': max_chars}, 'role_limits': {}}
        rt = Mock()
        rt.call.return_value = providers.Result(json.dumps({'verdict': 'PASS', 'reason': 'fixture'}),
                                              'fixture', 'fixture-reviewer', 0, 0, 0, 0)
        if on_call is not None:
            rt.call.side_effect = on_call
        with patch.object(runner, '_ACTIVE_REQUEST', card), \
             patch.object(paths, 'WORKSPACE', self.root / 'run'), \
             patch.object(runner, '_require_approval', return_value=True), \
             patch.object(runner, '_verified_result', return_value=verdict), \
             patch.object(runner, '_sync_plan'), patch.object(runner.events, 'emit'):
            runner.phase_review(cfg, st, Mock(), rt)
        return rt

    def test_review_receives_tail_of_complete_claims_and_decision(self):
        card, folder, task, verdict, st = self.review_state()
        # Direct phase regression: JSON completeness, not semantic fixture validity.
        for name in ('claims.json', 'decision.json'):
            (folder / name).write_text(json.dumps({'padding': 'x' * 26000, 'tail': 'CRITICAL_TAIL'}), encoding='utf-8')
        rt = self.review(card, verdict, st)
        self.assertEqual(rt.call.call_count, 1)
        sent = rt.call.call_args.args[2][1]['content']
        self.assertEqual(sent.count('CRITICAL_TAIL'), 2)
        self.assertIn('СТРУКТУРИРОВАННЫЙ HANDOFF', sent)
        manifest = json.loads(paths.resolve(st['last_context_manifest']).read_text(encoding='utf-8'))
        mandatory = [row for row in manifest['files'] if row['path'].endswith(('claims.json', 'decision.json'))]
        self.assertEqual(len(mandatory), 2)
        self.assertTrue(all(row['required'] and row['omitted_characters'] == 0 for row in mandatory))

    def test_oversized_mandatory_output_blocks_before_semantic_model(self):
        card, folder, task, verdict, st = self.review_state()
        (folder / 'decision.json').write_text(json.dumps({'padding': 'x' * 65000}), encoding='utf-8')
        rt = self.review(card, verdict, st)
        rt.call.assert_not_called()
        self.assertEqual(st['phase'], 'REPORT')
        self.assertIn('context_failure', st)
        manifests = list((self.root / 'run/context').glob('*.json'))
        self.assertTrue(manifests)
        self.assertTrue(any(json.loads(fp.read_text(encoding='utf-8'))['status'] == 'rejected' for fp in manifests))

    def test_large_diff_is_not_sliced_mid_json_and_blocks_at_packet_cap(self):
        card, folder, task, verdict, st = self.review_state()
        verdict['diff']['modified'] = ['path/' + 'x' * 100] * 1200
        rt = self.review(card, verdict, st, max_chars=100000)
        rt.call.assert_not_called()
        self.assertEqual(st['phase'], 'REPORT')
        self.assertEqual(st['context_failure'], 'packet_too_large')

    def test_short_old_tail_and_open_task_survive_state_roundtrip_handoff(self):
        st = state.default_state()
        st.update(phase='DONE', request_outcome='blocked', needs_human='needs source check',
                  tasks=[{'id': 'answer-mentor', 'status': 'failed', 'closes': 'roadmap:этап1-шаг2'}],
                  request_answer_attempts=2, request_sources_attempted=6)
        before = context_packets.handoff(st)
        after = context_packets.handoff(json.loads(json.dumps(st)))
        self.assertEqual(before, after)
        packed = json.dumps(after)
        self.assertIn('blocked', packed)
        self.assertIn('failed', packed)
        self.assertIn('2', packed)

    def test_regular_night_handoff_joins_current_task_goal_and_closes(self):
        st = state.default_state()
        st.update(phase='EXECUTE', task={'id': 'T1', 'iter': 1}, tasks=[{
            'id': 'T1', 'goal': 'Preserve this goal', 'closes': 'roadmap:этап1-шаг2',
            'acceptance': [{'file_exists': 'docs/result.md'}], 'status': 'pending'}])
        handoff = context_packets.handoff(st)
        self.assertEqual(handoff['purpose']['goal'], 'Preserve this goal')
        self.assertEqual(handoff['purpose']['closes'], 'roadmap:этап1-шаг2')
        self.assertEqual(handoff['run']['iter'], 1)

    def test_manifest_written_before_underlying_call_and_absent_on_no_model_work(self):
        card, folder, task, verdict, st = self.review_state()
        def call(*args, **kwargs):
            self.assertTrue(paths.resolve(st['last_context_manifest']).exists())
            return providers.Result(json.dumps({'verdict': 'PASS', 'reason': 'fixture'}),
                                    'fixture', 'fixture-reviewer', 0, 0, 0, 0)
        self.review(card, verdict, st, on_call=call)
        self.assertTrue(paths.resolve(st['last_context_manifest']).exists())

    def author_fixture(self):
        self.spec['research_policy'] = {'topics': ['methods'], 'max_queries': 3,
                                       'pages_per_query': 2, 'min_sources': 2, 'min_domains': 1}
        self.submit()

    def test_handoff_overflow_before_author_counter_changes(self):
        self.author_fixture()
        with intake.runtime(self.spec['id']) as card:
            cfg = runner.load_config()
            task = intake.build_plan(card)[-1]
            task['depends_on'] = []
            source = intake.root(self.spec['id']) / 'sources-0.md.json'
            source.write_text(json.dumps({'sources': [{'url': 'https://example.org/paper', 'content': 'Source content.'}]}), encoding='utf-8')
            st, rt = state.default_state(), Mock()
            st.update(phase='EXECUTE', tasks=[task], request_answer_attempts=1)
            state.save(st)
            real = runner._ContextRouter.preflight
            def preflight(proxy, current, messages):
                base_size = sum(len(message['content']) for message in messages)
                handoff_size = len(json.dumps(context_packets.handoff(current, card), ensure_ascii=False, allow_nan=False))
                self.assertGreater(handoff_size, 512)
                # Without handoff, even the fixed allowance256 fits. Only the
                # handoff must push this otherwise valid packet over the cap.
                proxy.cfg['night']['context_max_chars'] = base_size + 256 + handoff_size // 2
                self.assertLess(base_size + 256, proxy.cfg['night']['context_max_chars'])
                self.assertGreater(base_size + handoff_size + 256, proxy.cfg['night']['context_max_chars'])
                with self.assertRaises(context_packets.ContextError) as failure:
                    real(proxy, current, messages)
                self.assertEqual(failure.exception.code, 'packet_too_large')
                raise failure.exception
            with patch.object(runner, '_require_approval', return_value=True), \
                 patch.object(runner, '_DEADLINE', None), \
                 patch.object(runner._ContextRouter, 'preflight', autospec=True, side_effect=preflight):
                runner.phase_execute(cfg, st, Mock(), rt)
            rt.call.assert_not_called()
            self.assertEqual(st['phase'], 'REPORT')
            self.assertEqual(st['context_failure'], 'packet_too_large')
            self.assertEqual(st['request_answer_attempts'], 1)
            self.assertEqual(json.loads(paths.STATE_FILE.read_text(encoding='utf-8'))['request_answer_attempts'], 1)

    def test_manifest_write_failure_preserves_persisted_author_quota(self):
        self.author_fixture()
        with intake.runtime(self.spec['id']) as card:
            cfg = runner.load_config()
            task = intake.build_plan(card)[-1]
            task['depends_on'] = []
            (intake.root(self.spec['id']) / 'sources-0.md.json').write_text(json.dumps({'sources': [
                {'url': 'https://example.org/paper', 'content': 'Source content.'}]}), encoding='utf-8')
            st, rt = state.default_state(), Mock()
            st.update(phase='EXECUTE', tasks=[task], request_answer_attempts=1)
            state.save(st)
            with patch.object(runner, '_require_approval', return_value=True), \
                 patch.object(runner, '_DEADLINE', None), \
                 patch.object(context_packets, 'save_manifest', side_effect=context_packets.ContextError('manifest_write_failed')):
                runner.phase_execute(cfg, st, Mock(), rt)
            rt.call.assert_not_called()
            self.assertEqual(st['phase'], 'REPORT')
            self.assertEqual(st['request_answer_attempts'], 1)
            self.assertEqual(json.loads(paths.STATE_FILE.read_text(encoding='utf-8'))['request_answer_attempts'], 1)

    def test_approved_command_execution_creates_no_model_manifest(self):
        self.submit()
        with intake.runtime(self.spec['id']) as card:
            cfg = runner.load_config()
            task = intake.build_plan(card)[0]
            st, rt = state.default_state(), Mock()
            st.update(phase='EXECUTE', tasks=[task])
            def command(cmd, cwd, timeout):
                import subprocess
                base = intake.root(self.spec['id'])
                (base / 'sources-0.md').write_text('Actual fixture source', encoding='utf-8')
                (base / 'sources-0.md.json').write_text(json.dumps({'sources': [
                    {'url': 'https://example.org/paper', 'content': 'Source content.'}]}), encoding='utf-8')
                return subprocess.CompletedProcess(cmd, 0, 'fixture', '')
            with patch.object(runner, '_require_approval', return_value=True), \
                 patch.object(runner, '_DEADLINE', None), patch('autonomy.shellutil.run_command', side_effect=command):
                runner.phase_execute(cfg, st, Mock(), rt)
            rt.call.assert_not_called()
            self.assertEqual(st['phase'], 'VERIFY')
            self.assertFalse((paths.WORKSPACE / 'context').exists())

    def test_current_status_includes_all_current_sections_not_old_history(self):
        status = self.root / 'STATUS.md'
        status.write_text('# STATUS\n## Аудит\nAudit current\n## Актуально\nCURRENT_END\n'
                          '## Предыдущее: v6\n' + 'old ' * 20000, encoding='utf-8')
        capture = context_packets.Capture()
        value = capture.read('STATUS.md', 16000, required=True, mode='status_current')
        self.assertIn('CURRENT_END', value)
        self.assertIn('Audit current', value)
        self.assertNotIn('old old', value)
        self.assertGreater(capture.records[0]['omitted_characters'], 0)


if __name__ == '__main__':
    unittest.main()
