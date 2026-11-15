"""Offline tests of bounded, auditable request research."""
import copy
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from autonomy import intake, request_research as rr, runner, paths, providers, state
from autonomy.tests import test_intake


class ResearchTests(unittest.TestCase):
    setUp = test_intake.IntakeTests.setUp
    submit = test_intake.IntakeTests.submit

    def setUp(self):
        test_intake.IntakeTests.setUp(self)
        self.spec['research_policy'] = {'topics': ['models', 'limits'], 'min_sources': 2,
                                        'min_domains': 2, 'max_queries': 3}

    def proposal(self, queries):
        return {'queries': queries, 'reason': 'synthetic coverage gap'}

    def test_policy_unknown_field(self):
        with self.assertRaises(ValueError):
            rr.validate_policy(dict(self.spec['research_policy'], surprise=1), self.spec['research_queries'])

    def test_policy_bool_not_integer(self):
        for key in ('max_queries', 'pages_per_query', 'max_plan_revisions', 'max_followup_rounds',
                    'answer_attempts', 'min_sources', 'min_domains'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                rr.validate_policy(dict(self.spec['research_policy'], **{key: True}), self.spec['research_queries'])

    def test_policy_infeasible_caps(self):
        for changes in ({'max_queries': 1, 'pages_per_query': 1, 'min_sources': 2},
                        {'min_sources': 2, 'min_domains': 3}, {'max_queries': 0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                rr.validate_policy(dict(self.spec['research_policy'], **changes), self.spec['research_queries'])

    def test_query_injection_and_duplicates(self):
        for queries in (['valid & del file'], ['valid\nother'], ['Good Query', ' good   query '],
                        ['valid " quoted']):
            with self.subTest(queries=queries), self.assertRaises(ValueError):
                rr.query_list(queries, 3)

    def test_proposal_cannot_increase_authorization(self):
        card = self.submit()
        for key, value in (('max_queries', 6), ('budget_usd', 100), ('requirements', [])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                rr.propose(card, dict(self.proposal(['new query']), **{key: value}), 'model', 'plan')
        self.assertEqual(rr.plan_files(card), [])

    def test_chain_tampering_rejected(self):
        card = self.submit()
        rr.propose(card, self.proposal(['revised query']), 'model', 'plan')
        fp = rr.plan_files(card)[0]
        obj = json.loads(fp.read_text(encoding='utf-8'))
        obj['queries'] = ['tampered query']
        fp.write_text(json.dumps(obj), encoding='utf-8')
        with self.assertRaises(ValueError):
            rr.read_plan(card)

    def test_repeated_plan_revision_rejected(self):
        card = self.submit()
        rr.propose(card, self.proposal(['revised query']), 'model', 'plan')
        with self.assertRaises(ValueError):
            rr.propose(card, self.proposal(['another query']), 'model', 'plan')
        self.assertEqual(len(rr.plan_files(card)), 1)

    def test_followup_append_only_and_round_cap(self):
        card = self.submit()
        original = card['spec']['research_queries'][:]
        result = rr.propose(card, self.proposal(['new query']), 'model', 'followup')
        self.assertEqual(result['queries'], original + ['new query'])
        with self.assertRaises(ValueError):
            rr.propose(card, self.proposal(['another query']), 'model', 'followup')
        self.assertEqual(rr.read_plan(card)['queries'], original + ['new query'])

    def test_followup_query_cap(self):
        card = self.submit()
        with self.assertRaises(ValueError):
            rr.propose(card, self.proposal(['one', 'two', 'three']), 'model', 'followup')
        self.assertEqual(rr.plan_files(card), [])

    def test_exhausted_answer_budget_blocks_followup_before_collection(self):
        card = self.submit()
        st = {'request_answer_attempts': 2, 'phase': 'REVIEW', 'tasks': []}
        with patch.object(runner, '_ACTIVE_REQUEST', card), patch.object(runner, '_DEADLINE', None):
            self.assertTrue(runner._request_followup(st, {'id': 'answer-mentor'},
                {'verdict': 'SEARCH', 'reason': 'gap', 'research_queries': ['new']}, 'model', Mock()))
        self.assertEqual(st['phase'], 'REPORT')
        self.assertIn('answer attempt budget exhausted', st['needs_human'])
        self.assertEqual(rr.plan_files(card), [])

    def test_rebuild_preserves_completed_task_and_hash(self):
        card = self.submit()
        done = intake.build_plan(card)[0]
        done['status'] = 'done'
        done['receipt'] = {'synthetic': 'immutable'}
        old = copy.deepcopy(done)
        old_hash = runner._plan_sha256([done])
        rr.propose(card, self.proposal(['new query']), 'model', 'followup')
        rebuilt = rr.rebuild(card, [done])
        self.assertEqual(rebuilt[0], old)
        self.assertEqual(runner._plan_sha256([rebuilt[0]]), old_hash)
        self.assertTrue(set(old['commands']).isdisjoint(rebuilt[1]['commands']))
        self.assertEqual(len(rebuilt[1]['commands']), 1)
        self.assertIn(rebuilt[1]['id'], rebuilt[2]['depends_on'])

    def coverage(self):
        card = self.submit()
        claims = [{'id': 'C1', 'status': 'supported', 'source_url': 'https://a.example/one'},
                  {'id': 'C2', 'status': 'supported', 'source_url': 'https://b.example/two'}]
        decision = {'coverage': [{'topic': 'models', 'claim_ids': ['C1']},
                                 {'topic': 'limits', 'claim_ids': ['C2']}]}
        return card, claims, decision

    def test_two_claims_one_url_is_insufficient(self):
        card, claims, decision = self.coverage()
        claims[1]['source_url'] = claims[0]['source_url']
        with self.assertRaises(ValueError):
            rr.check_coverage(card, claims, decision)

    def test_all_topics_distinct_sources_and_domains(self):
        card, claims, decision = self.coverage()
        result = rr.check_coverage(card, claims, decision)
        self.assertEqual((result['distinct_sources'], result['distinct_domains'], result['coverage_topics']), (2, 2, 2))

    def test_unknown_claim_and_topic_rejected(self):
        card, claims, decision = self.coverage()
        for key, value in (('topic', 'unknown'), ('claim_ids', ['unknown'])):
            d = copy.deepcopy(decision)
            d['coverage'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                rr.check_coverage(card, claims, d)

    def run_phases(self, *, legacy=False, revise=False, search=False, exhausted=False, answer_search=False,
                   forced_complete=False):
        if legacy:
            self.spec.pop('research_policy')
        self.submit()
        calls, roles = [], []
        with intake.runtime(self.spec['id']) as card:
            original = copy.deepcopy(card)
            cfg = runner.load_config()
            cfg['night']['report_interpretation_enabled'] = False
            base, folder = intake.root(self.spec['id']), intake.output_dir(card)
            critics = 0
            verifiers = 0

            def call(role, *args, **kwargs):
                nonlocal critics, verifiers
                roles.append(role)
                if role == 'critic':
                    critics += 1
                    verdict = 'revise' if revise and critics == 1 else 'approve'
                    result = {'verdict': verdict, 'summary': 'synthetic', 'objections': [],
                              'defense_value': [], 'needs_search': []}
                elif role == 'planner':
                    result = self.proposal(['revised official search'])
                elif role == 'verifier':
                    verifiers += 1
                    if search and (verifiers == 1 or exhausted and verifiers == 2 or answer_search and verifiers == 3):
                        result = {'verdict': 'SEARCH', 'reason': 'coverage gap',
                                  'research_queries': ['independent second source' if verifiers == 1 else 'third source']}
                    else:
                        result = {'verdict': 'PARTIAL' if (exhausted or answer_search) and verifiers >= 3 and not forced_complete else 'PASS',
                                  'reason': 'synthetic'}
                elif role == 'executor':
                    forced = bool(st.get('request_force_partial'))
                    partial = forced and not forced_complete
                    if forced:
                        context = args[1][1]['content']
                        for text in ('ЧАСТИЧНЫЙ РЕЗУЛЬТАТ', 'decision.completion_status=partial', 'limitations', 'gap'):
                            self.assertIn(text, context)
                    claims = [{'id': f'C{i+1}', 'claim': 'synthetic', 'status': 'supported',
                               'source_url': f'https://source{i}.example/page', 'quote': f'Quote {i}',
                               'evidence_file': intake.rel(base / f'sources-{i}.md.json')} for i in range(2)]
                    decision = {'roadmap_change': False, 'report_change': False, 'reason': 'synthetic',
                                'owner_actions': [], 'coverage': [{'topic': 'models', 'claim_ids': ['C1']},
                                {'topic': 'limits', 'claim_ids': [] if partial else ['C2']}]}
                    if partial:
                        decision.update(completion_status='partial', limitations=['Further search forbidden'])
                        decision['coverage'][1]['gap'] = 'Further search forbidden by followup cap'
                    result = {'files': {
                        intake.rel(folder / 'response.md'): ('ЧАСТИЧНЫЙ РЕЗУЛЬТАТ\n' if partial else '') + 'C1 C2 https://source0.example/page https://source1.example/page\n' + 'Synthetic response. ' * 30,
                        intake.rel(folder / 'claims.json'): json.dumps(claims),
                        intake.rel(folder / 'decision.json'): json.dumps(decision)}, 'commands': []}
                else:
                    self.fail('unexpected role: ' + role)
                return providers.Result(json.dumps(result), 'synthetic', 'synthetic', 0, 0, 0, 0)

            def command(cmd, cwd, timeout):
                calls.append(cmd)
                if 'autonomy.research' in cmd:
                    i = sum('autonomy.research' in c for c in calls) - 1
                    (base / f'sources-{i}.md').write_text('Synthetic source', encoding='utf-8')
                    (base / f'sources-{i}.md.json').write_text(json.dumps({'sources': [
                        {'url': f'https://source{i}.example/page', 'content': f'Quote {i}'}]}), encoding='utf-8')
                else:
                    self.assertIn('autonomy.intake check', cmd)
                    intake.check_response(self.spec['id'])
                return subprocess.CompletedProcess(cmd, 0, 'offline', '')

            st, rt = state.default_state(), Mock()
            rt.call.side_effect = call
            st['phase'] = 'PLAN'
            with patch('requests.post', side_effect=AssertionError('network forbidden')), \
                 patch('autonomy.shellutil.run_command', side_effect=command), \
                 patch.object(runner, '_DEADLINE', None):
                for _ in range(25):
                    if st['phase'] == 'DONE' or (legacy and st['phase'] == 'REPORT') or (revise and not legacy and st['phase'] == 'EXECUTE'):
                        break
                    reviewing_complete = (forced_complete and st['phase'] == 'REVIEW'
                                          and st['task']['id'] == 'answer-mentor')
                    if reviewing_complete:
                        self.assertTrue(st.get('request_force_partial'))
                        self.assertEqual(intake.check_response(self.spec['id'])['completion_status'], 'complete')
                    getattr(runner, 'phase_' + st['phase'].lower())(cfg, st, Mock(), rt)
                    state.save(st)
                    if reviewing_complete:
                        break
            self.assertEqual(intake.load(self.spec['id']), original)
            if forced_complete:
                self.assertEqual(st['phase'], 'EXECUTE')
                self.assertEqual(st['tasks'][-1]['status'], 'pending')
                self.assertNotEqual(st.get('request_outcome'), 'complete')
                self.assertEqual(st['request_answer_attempts'], 1)
                self.assertTrue(st.get('request_force_partial'))
                self.assertEqual(roles[-2:], ['executor', 'verifier'])
                return st, roles
            if legacy:
                self.assertEqual(st['phase'], 'REPORT')
                self.assertNotIn('planner', roles)
            elif revise:
                self.assertEqual(st['phase'], 'EXECUTE', st.get('needs_human'))
                self.assertEqual(roles[:3], ['critic', 'planner', 'critic'])
                self.assertEqual(rr.read_plan(card)['queries'], ['revised official search'])
            if search:
                self.assertEqual(st['phase'], 'DONE', st.get('needs_human'))
                expected_roles = ['critic', 'verifier', 'critic', 'verifier', 'executor', 'verifier']
                if answer_search:
                    expected_roles += ['executor', 'verifier']
                self.assertEqual(roles, expected_roles)
                self.assertEqual(len([c for c in calls if 'autonomy.research' in c]), 2)
                self.assertEqual([t['status'] for t in st['tasks']], ['done', 'done', 'partial' if exhausted or answer_search else 'done'])
                self.assertEqual(st['request_answer_attempts'], 2 if answer_search else 1)
                if exhausted or answer_search:
                    self.assertEqual(st['request_outcome'], 'partial')
                    self.assertEqual(len(rr.plan_files(card)), 1)
                    facts = json.loads((paths.OUTBOX_DIR / 'facts.json').read_text(encoding='utf-8'))
                    self.assertEqual(facts['request_outcome'], 'partial')
                first = st['tasks'][0]
                self.assertTrue(runner._verified_result(first, first)['pass'])
                (base / 'sources-0.md.json').write_text('tampered', encoding='utf-8')
                self.assertIsNone(runner._verified_result(first, first))
            return st, roles

    def test_legacy_revise_fail_closed(self):
        self.run_phases(legacy=True, revise=True)

    def test_policy_plan_revise_typed_proposal_approved(self):
        self.run_phases(revise=True)

    def test_offline_search_recritic_new_collection_and_answer(self):
        self.run_phases(search=True)

    def test_followup_cap_collection_forces_partial(self):
        self.run_phases(search=True, exhausted=True)

    def test_followup_cap_answer_retries_partial(self):
        self.run_phases(search=True, answer_search=True)

    def test_forced_partial_rejects_valid_complete_even_with_review_pass(self):
        self.run_phases(search=True, exhausted=True, forced_complete=True)

    def test_exhausted_cap_rejects_valid_failed_collection_verdict(self):
        card = self.submit()
        rr.propose(card, self.proposal(['new query']), 'model', 'followup')
        task = {'id': 'collect-sources-r1', 'execution': 'approved_commands', 'status': 'pending'}
        st = {'phase': 'REVIEW', 'tasks': [task], 'task': {'id': task['id']}, 'violations': []}
        before = [p.read_bytes() for p in rr.plan_files(card)]
        with patch.object(runner, '_ACTIVE_REQUEST', card), patch.object(runner, '_DEADLINE', None), \
             patch.object(runner, '_verified_result', return_value={'pass': False}) as verified, \
             patch.object(runner.request_limits, 'remaining', return_value=100), \
             patch('autonomy.shellutil.run_command', side_effect=AssertionError('search forbidden')) as command:
            runner._request_followup(st, task, {'verdict': 'SEARCH', 'reason': 'gap',
                                     'research_queries': ['another query']}, 'model', Mock())
        verified.assert_called_once_with(task, st['task'])
        command.assert_not_called()
        self.assertEqual(st['phase'], 'REPORT')
        self.assertEqual(task['status'], 'pending')
        self.assertNotIn('request_force_partial', st)
        self.assertEqual([p.read_bytes() for p in rr.plan_files(card)], before)
        self.assertFalse(rr.pending_update(card).exists())

    def test_exhausted_cap_remains_fail_closed_for_unsafe_state(self):
        card = self.submit()
        rr.propose(card, self.proposal(['new query']), 'model', 'followup')
        for fault in ('receipt', 'previous', 'violation', 'task', 'attempts', 'iterations', 'time'):
            with self.subTest(fault=fault):
                task = {'id': 'answer-mentor', 'execution': 'document_only', 'max_iter': 2}
                previous = {'id': 'collect-sources', 'status': 'done'}
                st = {'phase': 'REVIEW', 'tasks': [previous, task],
                      'task': {'id': task['id'], 'iter': 1}, 'violations': []}
                if fault == 'violation':
                    st['violations'] = [{'kind': 'write_scope'}]
                if fault == 'task':
                    task['execution'] = 'approved_commands'
                if fault == 'attempts':
                    st['request_answer_attempts'] = 2
                if fault == 'iterations':
                    st['task']['iter'] = 2
                def verified(t, current):
                    if fault == 'receipt' and t is task or fault == 'previous' and t is previous:
                        return None
                    return {'pass': True}
                with patch.object(runner, '_ACTIVE_REQUEST', card), patch.object(runner, '_DEADLINE', None), \
                     patch.object(runner, '_verified_result', side_effect=verified), \
                     patch.object(runner.request_limits, 'remaining', return_value=0 if fault == 'time' else 100):
                    runner._request_followup(st, task, {'verdict': 'SEARCH', 'reason': 'gap',
                                             'research_queries': ['another query']}, 'model', Mock())
                self.assertEqual(st['phase'], 'REPORT')
                self.assertNotIn('request_force_partial', st)
                self.assertEqual(len(rr.plan_files(card)), 1)


if __name__ == '__main__':
    unittest.main()
