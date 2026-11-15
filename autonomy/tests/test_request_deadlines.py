import unittest
from types import SimpleNamespace
from unittest.mock import patch

from autonomy import opencode_provider as oc, providers, router


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        self.patches = [patch.object(router.time, 'time', side_effect=lambda: self.clock[0]),
                        patch.object(router.events, 'emit'), patch.object(router.state_mod, 'save')]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.log = SimpleNamespace(warn=lambda *a: None, log=lambda *a: None)

    def make_router(self, names=('a', 'b'), hook=None):
        cfg = {'night': {}, 'roles': {'executor': list(names)},
               'providers': {n: {'model': n, 'timeout_s': 300} for n in names}}
        return router.Router(cfg, self.log, hook)

    def result(self):
        return providers.Result('ok', 'a', 'a', 12, 7, .25, 1)

    def test_expired_no_reserve_or_chat(self):
        r = self.make_router(('a',))
        r.cfg['providers']['a']['kind'] = 'opencode-chatgpt'
        with patch.object(router.subscription, 'reserve') as reserve, patch.object(providers, 'chat') as chat:
            with self.assertRaises(providers.ProviderError) as e:
                r.call('executor', {'request_model_deadline_ts': 100}, [])
        self.assertEqual(e.exception.kind, 'time_budget')
        reserve.assert_not_called(); chat.assert_not_called()

    def test_fallback_cap_decreases(self):
        r = self.make_router()
        seen = []
        def chat(name, cfg, *args, **kwargs):
            seen.append(cfg['timeout_s'])
            if name == 'a':
                self.clock[0] += 4
                raise providers.ProviderError('failed')
            return self.result()
        with patch.object(providers, 'chat', side_effect=chat):
            r.call('executor', {'request_model_deadline_ts': 110}, [])
        self.assertEqual(seen, [10, 6])

    def test_late_answer_charged_once(self):
        r = self.make_router()
        st = {'request_model_deadline_ts': 101}
        def chat(*a, **kw):
            self.clock[0] = 101
            return self.result()
        with patch.object(providers, 'chat', side_effect=chat) as c:
            with self.assertRaises(providers.ProviderError) as e:
                r.call('executor', st, [])
        self.assertEqual((e.exception.kind, e.exception.in_tok, e.exception.out_tok), ('time_budget', 12, 7))
        self.assertEqual(st['budget_used_usd'], .25)
        self.assertEqual(c.call_count, 1)
        self.assertFalse(st.get('disabled_providers'))

    def test_failure_at_deadline_no_retry(self):
        r = self.make_router()
        def chat(*a, **kw):
            self.clock[0] = 101
            raise providers.ProviderError('truncated', 'truncated', .1, 2, 3)
        st = {'request_model_deadline_ts': 101}
        with patch.object(providers, 'chat', side_effect=chat) as c:
            with self.assertRaises(providers.ProviderError) as e:
                r.call('executor', st, [])
        self.assertEqual(e.exception.kind, 'time_budget')
        self.assertEqual(st['budget_used_usd'], .1)
        self.assertEqual(c.call_count, 1)

    def test_five_hour_wait_extends_deadline(self):
        hooks = []
        r = self.make_router(('a',), lambda st, elapsed: hooks.append(elapsed))
        r.cfg['providers']['a']['kind'] = 'opencode-chatgpt'
        blocked = {'reason': 'quota', 'until': 18100., 'weekly': False}
        st = {'request_model_deadline_ts': 110}
        def sleep(seconds): self.clock[0] += seconds
        with patch.object(router.subscription, 'reserve', side_effect=[blocked, None]), \
             patch.object(router.time, 'sleep', side_effect=sleep), \
             patch.object(providers, 'chat', return_value=self.result()):
            r.call('executor', st, [])
        self.assertEqual(st['subscription_wait_seconds'], 18000)
        self.assertEqual(st['request_model_deadline_ts'], 18110)
        self.assertEqual(sum(hooks), 18000)

    def entry(self):
        return {'data': [{'providerID': 'openai', 'id': 'gpt', 'enabled': True, 'cost': [],
                          'limit': {'input': 100000}, 'variants': [{'id': 'v', 'body': {'max_output_tokens': 1000}}]}]}

    def test_chunks_share_deadline_and_expire_before_generate(self):
        calls = []
        def request(method, route, payload=None, timeout=30):
            calls.append((method, route, timeout))
            self.clock[0] += 2
            if method == 'GET': return self.entry()
            if route == '/api/session': return {'data': {'id': 's'}}
            return {}
        with patch.object(oc, '_request', side_effect=request):
            with self.assertRaises(providers.ProviderError) as e:
                oc.chat('a', {'model': 'gpt', 'variant': 'v', '_deadline_ts': 106},
                        [{'content': 'x' * 11000}], 1000)
        self.assertEqual(e.exception.kind, 'time_budget')
        self.assertEqual([c[2] for c in calls], [6, 4, 2])
        self.assertFalse(any(c[1].endswith('/generate') for c in calls))

    def test_expired_adapter_does_not_request(self):
        with patch.object(oc, '_request') as req:
            with self.assertRaises(providers.ProviderError) as e:
                oc.chat('a', {'model': 'gpt', 'variant': 'v', '_deadline_ts': 100}, [], 1000)
        self.assertEqual(e.exception.kind, 'time_budget')
        req.assert_not_called()

    def test_late_generate_preserves_usage(self):
        def request(method, route, payload=None, timeout=30):
            if method == 'GET': return self.entry()
            if route == '/api/session': return {'data': {'id': 's'}}
            if method == 'PUT': return {}
            self.clock[0] = 110
            return {'data': {'tokens': {'input': 4, 'output': 5}, 'cost': .3}}
        with patch.object(oc, '_request', side_effect=request):
            with self.assertRaises(providers.ProviderError) as e:
                oc.chat('a', {'model': 'gpt', 'variant': 'v', '_deadline_ts': 110}, [], 1000)
        self.assertEqual((e.exception.kind, e.exception.cost_usd, e.exception.in_tok, e.exception.out_tok),
                         ('time_budget', .3, 4, 5))
