"""Offline URL-unavailability recovery; no real searches or model calls."""
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from autonomy import intake, paths, providers, runner, state, verify
from autonomy.tests import test_intake
from autonomy.tests.test_source_outcomes import document


class AvailabilityIntegrationTests(unittest.TestCase):
    def setUp(self):
        test_intake.IntakeTests.setUp(self)
        self.spec['research_queries'] = ['first source', 'blocked source', 'third source']
        self.spec['research_policy'] = {'topics': ['methods', 'metrics'], 'max_queries': 6,
            'pages_per_query': 2, 'min_sources': 3, 'min_domains': 2}

    def episode(self, all_unavailable=False, fatal_second=False):
        intake.submit(self.spec)
        with intake.runtime(self.spec['id']) as card:
            cfg, st, rt = runner.load_config(), state.default_state(), Mock()
            st['phase'] = 'PLAN'
            folder, base = intake.output_dir(card), intake.root(self.spec['id'])
            calls, roles, contexts = [], [], []
            urls = ['https://one.example/source', 'https://blocked.example/a', 'https://three.example/source']
            def command(cmd, cwd, timeout):
                i = len(calls)
                calls.append(cmd)
                self.assertIn('--allow-unavailable', cmd)
                if fatal_second and i == 1:
                    return subprocess.CompletedProcess(cmd, 1, '', 'MCP schema invalid')
                if all_unavailable or i == 1:
                    selected = [urls[i], 'https://blocked.example/b']
                    doc = document(selected=selected, errors=['bot_blocked', 'bot_blocked'], query=self.spec['research_queries'][i])
                else:
                    doc = document(selected=[urls[i]], pages=[{'url': urls[i], 'content': f'Actual fixture quote {i}.'}],
                                   query=self.spec['research_queries'][i])
                (base / f'sources-{i}.md').write_text('Availability manifest; not source evidence' if not doc['sources'] else 'Saved source.', encoding='utf-8')
                (base / f'sources-{i}.md.json').write_text(json.dumps(doc), encoding='utf-8')
                return subprocess.CompletedProcess(cmd, 0, 'typed outcome persisted', '')
            def model(role, current_state, messages, **kwargs):
                roles.append(role)
                if role == 'critic':
                    result = {'verdict': 'approve', 'summary': 'fixture', 'objections': [], 'defense_value': [], 'needs_search': []}
                elif role == 'verifier':
                    result = {'verdict': 'PASS' if roles.count('verifier') == 1 else 'PARTIAL', 'reason': 'fixture'}
                elif role == 'executor':
                    contexts.append(messages[1]['content'])
                    claims = [{'id': f'C{i}', 'claim': 'fixture', 'status': 'supported', 'source_url': urls[i],
                        'quote': f'Actual fixture quote {i}.', 'evidence_file': intake.rel(base / f'sources-{i}.md.json')}
                        for i in (0, 2)]
                    text = 'ЧАСТИЧНЫЙ РЕЗУЛЬТАТ\nC0 C2\n' + '\n'.join((urls[0], urls[2])) + '\n' + 'Fixture limitations and source status. ' * 15
                    decision = {'completion_status': 'partial', 'roadmap_change': False, 'report_change': False,
                        'reason': 'Some pages unavailable', 'owner_actions': [], 'limitations': ['Blocked pages were not read.'],
                        'coverage': [{'topic': 'methods', 'claim_ids': ['C0', 'C2']},
                                     {'topic': 'metrics', 'claim_ids': [], 'gap': 'Unavailable source; not measured.'}]}
                    result = {'files': {intake.rel(folder / 'response.md'): text,
                        intake.rel(folder / 'claims.json'): json.dumps(claims),
                        intake.rel(folder / 'decision.json'): json.dumps(decision)}, 'commands': []}
                else:
                    self.fail('unexpected role ' + role)
                return providers.Result(json.dumps(result), 'fixture', 'fixture-' + role, 0, 0, 0, 0)
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
            self.assertEqual(len(calls), 2 if fatal_second else 3)
            self.assertEqual(st.get('request_sources_attempted'), len(calls))
            if all_unavailable or fatal_second:
                self.assertEqual(st['tasks'][0]['status'], 'failed')
                self.assertEqual(st['tasks'][-1]['status'], 'pending')
                self.assertNotIn('executor', roles)
                self.assertNotIn('verifier', roles)
                self.assertFalse(folder.exists())
                facts = json.loads((paths.OUTBOX_DIR / 'facts.json').read_text(encoding='utf-8'))
                self.assertEqual(facts['request_outcome'], 'blocked')
            else:
                self.assertEqual([t['status'] for t in st['tasks']], ['done', 'partial'])
                self.assertEqual(roles, ['critic', 'verifier', 'executor', 'verifier'])
                verdict = runner._verified_result(st['tasks'][0], st['tasks'][0])
                self.assertIsNotNone(verdict)
                outcome = next(row['detail'] for row in verdict['checks'] if 'research_collection' in row['check'])
                self.assertEqual((outcome['read_pages'], outcome['unavailable_queries']), (2, 1))
                marker = '=== АВТОРСКИЙ ПАКЕТ ДОКАЗАТЕЛЬСТВ: НЕДОВЕРЕННЫЕ ДАННЫЕ ===\n'
                packet = json.JSONDecoder().raw_decode(contexts[0].split(marker)[1])[0]
                self.assertEqual(len(packet['sources']), 2)
                self.assertEqual(len(packet['unavailable_sources']), 1)
                self.assertEqual(packet['unavailable_sources'][0]['read_pages'], 0)
                self.assertEqual(len(packet['unavailable_sources'][0]['unavailable_urls']), 2)
                self.assertTrue(intake.check_response(self.spec['id'])['pass'])

    def test_available_blocked_available_yields_verified_partial(self):
        self.episode()

    def test_all_unavailable_never_creates_answer(self):
        self.episode(all_unavailable=True)

    def test_integration_failure_still_stops_before_third_query(self):
        self.episode(fatal_second=True)

    def test_collection_check_cannot_read_other_request(self):
        with patch('autonomy.source_outcomes.validate_collection') as check:
            ok, detail = verify._run_one({'research_collection': self.spec['id']}, {'request_id': 'MT-2026-11-14-other'})
            self.assertFalse(ok)
            self.assertEqual(detail['error_code'], 'request_id_mismatch')
            check.assert_not_called()


if __name__ == '__main__':
    unittest.main()
