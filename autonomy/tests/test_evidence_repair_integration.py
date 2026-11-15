"""Bounded author repair, typed verification and evidence delivery; offline only."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from autonomy import intake, paths, providers, runner, state, verify
from autonomy.claim_validation import ClaimValidationError, validate_claims
from autonomy.tests import test_intake


class EvidenceRepairIntegrationTests(unittest.TestCase):
    submit = test_intake.IntakeTests.submit

    def setUp(self):
        test_intake.IntakeTests.setUp(self)
        self.spec['research_policy'] = {'topics': ['methods'], 'max_queries': 1,
            'pages_per_query': 2, 'min_sources': 2, 'min_domains': 1, 'answer_attempts': 2}

    def test_full_two_error_repair_no_extra_verifier_or_search(self):
        intake.submit(self.spec)
        with intake.runtime(self.spec['id']) as card:
            cfg = runner.load_config()
            st, rt = state.default_state(), Mock()
            st['phase'] = 'PLAN'
            roles, executor_contexts, commands = [], [], []
            source = intake.root(self.spec['id']) / 'sources-0.md.json'
            folder = intake.output_dir(card)
            url = 'https://example.org/official'
            good = [{'id': f'C{i}', 'claim': 'fixture', 'status': 'supported',
                     'source_url': url, 'quote': q, 'evidence_file': intake.rel(source)}
                    for i, q in enumerate(('A streaming model.', 'CPU is supported.'), 1)]
            good[0]['source_url'] = 'https://example.org/other'
            def model(role, current_state, messages, **kwargs):
                roles.append(role)
                if role == 'critic':
                    value = {'verdict': 'approve', 'summary': 'fixture', 'objections': [],
                             'defense_value': [], 'needs_search': []}
                elif role == 'verifier':
                    value = {'verdict': 'PASS', 'reason': 'fixture semantic review'}
                elif role == 'executor':
                    executor_contexts.append(messages[1]['content'])
                    claims = json.loads(json.dumps(good))
                    if len(executor_contexts) == 1:
                        claims[0]['quote'] = 'Invented quotation'
                        claims[1]['source_url'] = 'https://example.org/absent'
                    value = {'files': {
                        intake.rel(folder / 'response.md'): f'C1 C2 {url} https://example.org/other https://example.org/absent\n' + 'Fixture response. ' * 35,
                        intake.rel(folder / 'claims.json'): json.dumps(claims),
                        intake.rel(folder / 'decision.json'): json.dumps({'completion_status': 'complete',
                            'roadmap_change': False, 'report_change': False, 'reason': 'fixture',
                            'owner_actions': [], 'coverage': [{'topic': 'methods', 'claim_ids': ['C1', 'C2']}]})},
                        'commands': []}
                else:
                    self.fail('unexpected role ' + role)
                return providers.Result(json.dumps(value), 'fixture', 'fixture-' + role, 0, 0, 0, 0)
            def command(cmd, cwd, timeout):
                commands.append(cmd)
                self.assertIn('autonomy.research', cmd)
                source.with_suffix('').write_text('Saved source fixture', encoding='utf-8')
                source.write_text(json.dumps({'sources': [
                    {'url': 'https://example.org/other', 'content': 'Unrelated source. ' * 2200 + ' A streaming model.'},
                    {'url': url, 'content': 'Unrelated body. ' * 3500 + ' A streaming model. CPU is supported.'}
                ]}), encoding='utf-8')
                return subprocess.CompletedProcess(cmd, 0, 'fixture', '')
            rt.call.side_effect = model
            with patch('requests.post', side_effect=AssertionError('network forbidden')), \
                 patch('autonomy.shellutil.run_command', side_effect=command), \
                 patch.object(runner, '_DEADLINE', None):
                for _ in range(30):
                    if st['phase'] == 'DONE':
                        break
                    getattr(runner, 'phase_' + st['phase'].lower())(cfg, st, Mock(), rt)
                    state.save(st)
            self.assertEqual(st['phase'], 'DONE')
            self.assertEqual([t['status'] for t in st['tasks']], ['done', 'done'])
            self.assertEqual(roles, ['critic', 'verifier', 'executor', 'executor', 'verifier'])
            self.assertEqual(len(commands), 1)
            self.assertEqual(st['request_answer_attempts'], 2)
            repair = executor_contexts[1].split('=== ПОЛНАЯ АДРЕСНАЯ ДИАГНОСТИКА ПРЕДЫДУЩЕГО ОТВЕТА ===\n')[1]
            feedback = json.JSONDecoder().raw_decode(repair)[0]
            errors = feedback['failed_checks'][0]['detail']['errors']
            self.assertEqual([e['claim_id'] for e in errors], ['C1', 'C2'])
            self.assertIn('quote_missing', errors[0]['codes'])
            self.assertIn('url_missing_in_evidence', errors[1]['codes'])
            for context in executor_contexts:
                packet = json.JSONDecoder().raw_decode(context.split('=== АВТОРСКИЙ ПАКЕТ ДОКАЗАТЕЛЬСТВ: НЕДОВЕРЕННЫЕ ДАННЫЕ ===\n')[1])[0]
                self.assertEqual(len(packet['sources']), 2)
                visible = json.dumps(packet, ensure_ascii=False)
                self.assertIn('CPU is supported.', visible)
                self.assertTrue(packet['sources'][1]['omitted_characters'])
            self.assertIsNotNone(runner._verified_result(st['tasks'][0], st['tasks'][0]))
            self.assertTrue(intake.check_response(self.spec['id'])['pass'])

    def test_typed_check_returns_all_diagnostics_no_shell(self):
        self.spec.pop('research_policy')
        folder, claims = test_intake.IntakeTests.answer(self)
        claims[0]['quote'] = 'absent'
        claims[1]['source_url'] = 'https://absent.example/source'
        (folder / 'claims.json').write_text(json.dumps(claims), encoding='utf-8')
        with patch('autonomy.shellutil.run_command') as shell:
            ok, detail = verify._run_one({'mentor_response': self.spec['id']}, {'request_id': self.spec['id']})
        self.assertFalse(ok)
        self.assertEqual([e['claim_id'] for e in detail['errors']], ['C1', 'C2'])
        shell.assert_not_called()

    def test_bad_packet_stops_before_author_attempt(self):
        intake.submit(self.spec)
        with intake.runtime(self.spec['id']) as card:
            task = intake.build_plan(card)[-1]
            task['depends_on'] = []
            st, rt = state.default_state(), Mock()
            st.update(phase='EXECUTE', tasks=[task])
            with patch.object(runner, '_require_approval', return_value=True), \
                 patch.object(runner, '_DEADLINE', None):
                runner.phase_execute(runner.load_config(), st, Mock(), rt)
            self.assertEqual(st['phase'], 'REPORT')
            self.assertNotIn('request_answer_attempts', st)
            rt.call.assert_not_called()

    def test_large_feedback_not_clipped_to_note_error_limit(self):
        intake.submit(self.spec)
        with intake.runtime(self.spec['id']) as card:
            task = intake.build_plan(card)[-1]
            errors = [{'claim_id': f'C{i:02}', 'codes': ['quote_missing'],
                       'source_url': 'https://example.org/' + 'x' * 200} for i in range(30)]
            verdict = {'pass': False, 'checks': [{'check': {'mentor_response': self.spec['id']},
                                                 'ok': False, 'detail': {'errors': errors}}]}
            st = state.default_state()
            st.update(phase='REVIEW', tasks=[task], task={'id': task['id'], 'iter': 1, 'errors': [], 'verify': verdict})
            rt = Mock()
            with patch.object(runner, '_require_approval', return_value=True), \
                 patch.object(runner, '_verified_result', return_value=verdict):
                runner.phase_review(runner.load_config(), st, Mock(), rt)
            actual = st['task']['validation_feedback']['failed_checks'][0]['detail']['errors']
            self.assertEqual(actual, errors)
            self.assertGreater(len(json.dumps(actual)), 3000)
            self.assertEqual(st['phase'], 'EXECUTE')
            rt.call.assert_not_called()

    def test_validator_rejects_nonlist_even_if_claim_dict_valid(self):
        self.spec.pop('research_policy')
        _, claims = test_intake.IntakeTests.answer(self)
        card = intake.load(self.spec['id'])
        with self.assertRaises(ClaimValidationError):
            validate_claims(card, claims[0], 'C1 C2 https://example.org/official')

    def test_typed_check_refuses_other_or_unknown_card_before_read(self):
        for cfg in ({}, {'request_id': 'MT-2026-11-13-other'}):
            with patch.object(intake, 'check_response') as check:
                ok, detail = verify._run_one({'mentor_response': self.spec['id']}, cfg)
                self.assertFalse(ok)
                self.assertIn('request_id_mismatch', detail['errors'][0]['codes'])
                check.assert_not_called()

    def test_roadmap_options_string_is_not_an_alternative_list(self):
        self.spec.pop('research_policy')
        folder, _ = test_intake.IntakeTests.answer(self)
        decision = {'roadmap_change': True, 'report_change': False, 'reason': 'fixture',
                    'owner_actions': [], 'trigger': 'prior_art', 'options': 'xxxno_changeyyy'}
        (folder / 'decision.json').write_text(json.dumps(decision), encoding='utf-8')
        with self.assertRaises(ValueError):
            intake.check_response(self.spec['id'])

    def test_malformed_prior_claims_do_not_block_base_packet(self):
        intake.submit(self.spec)
        with intake.runtime(self.spec['id']) as card:
            task = intake.build_plan(card)[-1]
            source = intake.root(self.spec['id']) / 'sources-0.md.json'
            source.write_text(json.dumps({'sources': [{'url': 'https://example.org/source',
                                                       'content': 'Saved base packet on CPU.'}]}), encoding='utf-8')
            folder = intake.output_dir(card)
            folder.mkdir(parents=True)
            for prior in ([None], [{}] * 31, {'not': 'a list'}):
                (folder / 'claims.json').write_text(json.dumps(prior), encoding='utf-8')
                context = runner._request_author_inputs(task, runner.load_config(), 1)
                self.assertIn('Saved base packet on CPU.', context)

    def test_oversized_review_bundle_reports_all_ids_and_size(self):
        from autonomy import request_research
        self.spec.pop('research_policy')
        folder, claims = test_intake.IntakeTests.answer(self)
        card = intake.load(self.spec['id'])
        quote = 'q' * 4000
        source = paths.resolve(claims[0]['evidence_file'])
        source.write_text(json.dumps({'sources': [{'url': claims[0]['source_url'],
                                                 'content': 'x' * 1000 + quote + 'y' * 1000}]}), encoding='utf-8')
        many = [dict(claims[0], id=f'C{i:02}', quote=quote) for i in range(30)]
        (folder / 'claims.json').write_text(json.dumps(many), encoding='utf-8')
        (folder / 'response.md').write_text(' '.join(c['id'] for c in many) + '\n' + claims[0]['source_url'], encoding='utf-8')
        with self.assertRaises(ClaimValidationError) as error:
            request_research.evidence_bundle(card)
        report = error.exception.diagnostics
        self.assertGreater(report['package_characters'], report['limit_characters'])
        self.assertEqual([e['claim_id'] for e in report['errors']], [c['id'] for c in many])

    def test_review_packet_failure_replaces_stale_feedback(self):
        intake.submit(self.spec)
        with intake.runtime(self.spec['id']) as card:
            folder = intake.output_dir(card)
            folder.mkdir(parents=True)
            for name, content in [('response.md', 'Fixture answer.'), ('claims.json', '[]'), ('decision.json', '{}')]:
                (folder / name).write_text(content, encoding='utf-8')
            task = intake.build_plan(card)[-1]
            verdict = {'pass': True, 'checks': []}
            st = state.default_state()
            st.update(phase='REVIEW', tasks=[task], task={'id': task['id'], 'iter': 1, 'errors': [],
                'verify': verdict, 'validation_feedback': {'obsolete': 'previous errors'}})
            rt = Mock()
            with patch.object(runner, '_require_approval', return_value=True), \
                 patch.object(runner, '_verified_result', return_value=verdict), \
                 patch('autonomy.request_research.evidence_bundle', side_effect=ValueError('fixture unreadable')):
                runner.phase_review(runner.load_config(), st, Mock(), rt)
            self.assertEqual(st['phase'], 'EXECUTE')
            self.assertNotIn('obsolete', st['task']['validation_feedback'])
            self.assertEqual(st['task']['validation_feedback']['errors'][0]['codes'], ['review_evidence_unavailable'])
            rt.call.assert_not_called()

    def test_redirected_response_path_rejected_before_output_read(self):
        self.spec.pop('research_policy')
        folder, _ = test_intake.IntakeTests.answer(self)
        target = folder / 'response.md'
        original = Path.resolve
        for destination in (self.root / 'docs/other.md', self.root.parent / 'outside.md'):
            def resolve(path, *args, **kwargs):
                return destination if path == target else original(path, *args, **kwargs)
            with patch.object(Path, 'resolve', autospec=True, side_effect=resolve):
                with self.assertRaisesRegex(ValueError, 'output path redirected'):
                    intake.check_response(self.spec['id'])


if __name__ == '__main__':
    unittest.main()
