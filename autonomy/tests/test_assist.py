import io
import json
import math
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from autonomy import assist, providers


class AssistTests(unittest.TestCase):
    def test_dry_run_no_model(self):
        with patch.object(assist, 'run') as run, patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(assist.main(['digest', '--text', 'sample']), 0)
            self.assertEqual(json.loads(output.getvalue())['status'], 'dry_run')
            run.assert_not_called()

    def test_context_bounded_not_truncated(self):
        for text in ('', 'x' * 10001):
            with self.assertRaises(ValueError):
                assist.messages_for('digest', text)

    def test_secrets_and_global_config_not_sendable_by_path(self):
        with self.assertRaises(ValueError):
            assist.read_input(assist.paths.PROJECT_ROOT / '.env')
        with self.assertRaises(ValueError):
            assist.read_input(assist.paths.PROJECT_ROOT / 'temp/secrets.txt')

    def test_budget_invalid_before_call(self):
        for budget in (math.nan, math.inf, -.1, 1, True):
            with self.assertRaises(ValueError):
                assist.run('digest', 'sample', budget)

    def test_auxiliary_route_never_night_state_save(self):
        result = providers.Result('summary', 'browser_digest', 'deepseek-flash', 0, 0, 0, 1)
        with patch.object(assist, 'Router') as cls, patch.object(assist.state, 'save') as save:
            cls.return_value.call.return_value = result
            value = assist.run('digest', 'sample', browser_only=True)
            cfg = cls.call_args.args[0]
            self.assertEqual(cfg['roles']['context_digest'], ['browser_digest'])
            self.assertEqual(value['status'], 'unverified_auxiliary')
            self.assertFalse(value['native_search_verified'])
            save.assert_not_called()

    def test_scout_never_claims_verified_search(self):
        messages = assist.messages_for('scout', 'Russian streaming ASR')
        self.assertIn('Если поиска нет', messages[0]['content'])
        self.assertIn('независимого чтения', messages[0]['content'])

    def test_real_router_success_uses_compatible_logger(self):
        result = providers.Result('summary', 'browser_digest', 'deepseek-flash', 0, 0, 0, 1)
        with patch.object(providers, 'chat', return_value=result), patch('autonomy.router.events.emit'):
            value = assist.run('digest', 'sample', browser_only=True)
        self.assertEqual(value['text'], 'summary')

    def test_fallback_failure_sanitized_before_logging_and_events(self):
        cfg = assist.runner.load_config()
        cfg['night']['sanitize_provider_errors'] = True
        cfg['roles']['context_digest'] = ['deepseek1017']
        from autonomy.router import Router
        log = Mock()
        with patch.object(providers, 'chat', side_effect=providers.ProviderError('SECRET reflected bearer cookie')), \
             patch('autonomy.router.events.emit') as emit:
            with self.assertRaises(providers.ProviderError) as error:
                Router(cfg, log).call('context_digest', assist.state.default_state(), assist.messages_for('digest', 'sample'))
        self.assertNotIn('SECRET', str(error.exception))
        self.assertNotIn('SECRET', str(log.mock_calls))
        self.assertNotIn('SECRET', str(emit.mock_calls))

    def test_error_redacted(self):
        with patch.object(assist, 'run', side_effect=providers.ProviderError('secret-token')), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(assist.main(['digest', '--text', 'sample', '--execute']), 1)
            self.assertNotIn('secret-token', output.getvalue())

    def test_brief_cooldown_wait_is_explicit(self):
        result = providers.Result('summary', 'browser_digest', 'deepseek-flash', 0, 0, 0, 1)
        available = dict(wait_seconds=20, manual_hold=False, inflight=False, daily_exhausted=False)
        with patch('autonomy.browser_gateway.status', return_value=available), \
             patch.object(assist.time, 'sleep') as sleep, patch.object(assist, 'Router') as cls:
            cls.return_value.call.return_value = result
            assist.run('digest', 'sample', wait_seconds=30)
            sleep.assert_called_once_with(20)
            available['manual_hold'] = True
            sleep.reset_mock()
            assist.run('digest', 'sample', wait_seconds=30)
            sleep.assert_not_called()

    def test_gateway_auth_hold_persists_but_permitted_api_fallback_works(self):
        from autonomy import browser_gateway
        from autonomy.router import Router
        with tempfile.TemporaryDirectory() as folder:
            cfg = assist.runner.load_config()
            cfg['providers']['browser_digest']['ledger_path'] = str(Path(folder) / 'ledger.sqlite3')
            cfg['night']['budget_usd_per_night'] = .05
            cfg['night']['max_calls_per_provider'] = {}
            st = assist.state.default_state()
            real_chat = providers.chat
            def chat(name, pcfg, messages, max_tokens, temperature):
                if name == 'browser_digest':
                    return real_chat(name, pcfg, messages, max_tokens, temperature)
                return providers.Result('fallback', name, pcfg['model'], 100, 20, .0001, 1)
            from autonomy.tests.test_browser_gateway import Response
            response = Response(status=401)
            with patch('autonomy.browser_gateway.requests.post', return_value=response) as post, \
                 patch.object(providers, 'chat', side_effect=chat), \
                 patch('autonomy.router.events.emit'):
                for _ in range(2):
                    result = Router(cfg, Mock()).call('context_digest', st, assist.messages_for('digest', 'sample'))
                    self.assertEqual(result.text, 'fallback')
                self.assertEqual(post.call_count, 1)
            self.assertTrue(browser_gateway.status(cfg['providers']['browser_digest'])['manual_hold'])
            self.assertAlmostEqual(st['budget_used_usd'], .0002)

    def test_budget_zero_never_calls_paid_fallback(self):
        cfg = assist.runner.load_config()
        cfg['night']['budget_usd_per_night'] = 0
        from autonomy.router import Router
        with patch.object(providers, 'chat', side_effect=providers.ProviderError('browser_gateway:unavailable', 'browser_unavailable')) as chat, \
             patch('autonomy.router.events.emit'):
            with self.assertRaises(providers.ProviderError):
                Router(cfg, Mock()).call('context_digest', assist.state.default_state(), assist.messages_for('digest', 'sample'))
            self.assertEqual([c.args[0] for c in chat.call_args_list], ['browser_digest'])


if __name__ == '__main__':
    unittest.main()
