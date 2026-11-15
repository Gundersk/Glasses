import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from autonomy import opencode_provider as oc, providers, router, state, subscription


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(subscription, "LEDGER", Path(self.tmp.name) / "quota.db")
        p.start()
        self.addCleanup(p.stop)

    def test_shared_run_and_rolling_week_caps(self):
        cfg = {"chatgpt_max_attempts_per_run": 2, "chatgpt_max_attempts_7d": 3}
        self.assertIsNone(subscription.reserve("a", cfg, 100))
        self.assertIsNone(subscription.reserve("a", cfg, 101))
        self.assertEqual(subscription.reserve("a", cfg, 102)["reason"], "run_cap")
        self.assertIsNone(subscription.reserve("b", cfg, 103))
        self.assertEqual(subscription.reserve("c", cfg, 104)["reason"], "local_weekly_cap")
        self.assertIsNone(subscription.reserve("c", cfg, 104 + 7 * 86400))

    def test_quota_shared_between_models_and_requests(self):
        e = providers.ProviderError("quota", "quota")
        e.retry_at = 500
        subscription.defer(e, {}, now=100)
        self.assertEqual(subscription.reserve("other-request", {}, 200)["until"], 560)
        self.assertIsNone(subscription.reserve("other-request", {}, 561))

    def test_weekly_unknown_not_five_hours(self):
        e = providers.ProviderError("quota", "quota")
        e.weekly = True
        wait = subscription.defer(e, {}, 100)
        self.assertGreater(wait["until"] - 100, 6 * 86400)

    def test_unknown_reset_conservative(self):
        e = providers.ProviderError("quota", "quota")
        self.assertEqual(subscription.defer(e, {}, 100)["until"], 18460)

    def test_unfinished_run_keeps_caps_after_midnight(self):
        st = dict(state.default_state(), night_id="20200101", phase="PLAN",
                  budget_used_usd=.7, attempts_by_provider={"kimi_pro": 8})
        f = Path(self.tmp.name) / "STATE.json"
        f.write_text(json.dumps(st), encoding="utf-8")
        with patch.object(state.paths, "STATE_FILE", f), patch.object(state.paths, "ensure_dirs"):
            loaded = state.load()
        self.assertEqual(loaded["night_id"], "20200101")
        self.assertEqual(loaded["budget_used_usd"], .7)
        self.assertEqual(loaded["attempts_by_provider"]["kimi_pro"], 8)


class AdapterTests(unittest.TestCase):
    def test_project_config_and_agent_models_agree(self):
        import yaml
        root = oc.paths.PROJECT_ROOT
        cfg = json.loads((root / "opencode.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["model"], "openai/gpt-6.1-terra")
        self.assertFalse(cfg["experimental"]["background_compaction"])
        self.assertFalse(cfg["warming"])
        self.assertEqual(cfg["compaction"]["buffer"], "20%")
        for name in ("reviewer", "implementer", "mentor"):
            front = (root / f".opencode/agents/{name}.md").read_text(encoding="utf-8").split("---")[1]
            self.assertEqual(yaml.safe_load(front)["model"], cfg["agents"][name]["model"])

    def entry(self, cost=None):
        return {"data": [{"providerID": "openai", "id": "gpt", "enabled": True,
                          "cost": cost or [], "limit": {"input": 500000},
                          "variants": [{"id": "test", "body": {"max_output_tokens": 1000}}]}]}

    def pcfg(self):
        return {"model": "gpt", "variant": "test", "max_input_tokens": 64000}

    def test_no_paid_model_fallback(self):
        with patch.object(oc, "_request", return_value=self.entry([{"input": 2}])) as req:
            with self.assertRaises(providers.ProviderError) as e:
                oc.chat("sub", self.pcfg(), [], 1000)
        self.assertEqual(e.exception.kind, "config")
        self.assertEqual(req.call_count, 1)

    def test_context_blocked_not_truncated(self):
        with patch.object(oc, "_request", return_value=self.entry()) as req:
            with self.assertRaises(providers.ProviderError) as e:
                oc.chat("sub", self.pcfg(), [{"content": "я" * 40000}], 1000)
        self.assertEqual(e.exception.kind, "context")
        self.assertEqual(req.call_count, 1)

    def test_output_cap_required(self):
        with patch.object(oc, "_request", return_value=self.entry()):
            with self.assertRaises(providers.ProviderError):
                oc.chat("sub", self.pcfg(), [], 500)

    def fake_request(self, method, route, payload=None, **kwargs):
        if method == "GET":
            return self.entry()
        if route == "/api/session":
            self.assertEqual(payload["permissions"][0]["effect"], "deny")
            return {"data": {"id": "ses_test"}}
        if method == "PUT":
            self.assertLessEqual(len(payload["value"]), 5000)
            return {}
        self.assertTrue(route.endswith("/generate"))
        marker = payload["prompt"].split("exactly ")[1].split(" ")[0]
        return {"data": {"text": '{"ok": true}\n' + marker,
                         "tokens": {"input": 80, "output": 20}, "cost": 0}}

    def test_fresh_tool_free_context_chunks_and_completion(self):
        with patch.object(oc, "_request", side_effect=self.fake_request) as req:
            r = oc.chat("sub", self.pcfg(), [{"content": "x" * 11000}], 1000)
        self.assertEqual(r.text, '{"ok": true}')
        self.assertEqual(sum(c.args[0] == "PUT" for c in req.call_args_list), 3)
        self.assertFalse(any("/prompt" in c.args[1] or "/synthetic" in c.args[1]
                             for c in req.call_args_list))

    def test_missing_completion_marker_not_success(self):
        def fake(method, route, payload=None, **kwargs):
            if route.endswith("/generate"):
                return {"data": {"text": "partial"}}
            return self.fake_request(method, route, payload, **kwargs)
        with patch.object(oc, "_request", side_effect=fake):
            with self.assertRaises(providers.ProviderError) as e:
                oc.chat("sub", self.pcfg(), [], 1000)
        self.assertEqual(e.exception.kind, "truncated_reasoning")

    def test_quota_metadata_is_redacted(self):
        p = SimpleNamespace(stdout=json.dumps({"_tag": "ProviderRequestError", "reason": "rate_limit",
                            "message": "weekly limit SECRET", "retryAfterMs": 10000}), returncode=1)
        with patch.object(oc.shutil, "which", return_value="opencode.exe"), patch.object(oc.subprocess, "run", return_value=p):
            with self.assertRaises(providers.ProviderError) as e:
                oc._request("POST", "/test", {})
        self.assertEqual(e.exception.kind, "quota")
        self.assertTrue(e.exception.weekly)
        self.assertNotIn("SECRET", str(e.exception))
        self.assertGreater(e.exception.retry_at, 0)

    def test_204_and_shell_free_unicode(self):
        p = SimpleNamespace(stdout="", returncode=0)
        with patch.object(oc.shutil, "which", return_value="opencode.exe"), patch.object(oc.subprocess, "run", return_value=p) as run:
            self.assertEqual(oc._request("PUT", "/test", {"value": "я & не команда"}), {})
        self.assertFalse(run.call_args.kwargs["shell"])


class RouterWaitTests(unittest.TestCase):
    setUp = SubscriptionTests.setUp
    def cfg(self, alternatives=False):
        p = {"sub": {"kind": "opencode-chatgpt", "model": "gpt", "max_output_tokens": 1000}}
        if alternatives:
            p["cheap"] = {"model": "other"}
        return {"night": {"subscription_wait_max_s": 21600}, "providers": p,
                "roles": {"critic": list(p)}}

    def run_wait(self, *, weekly=False, alternatives=False, twice=False):
        cfg = self.cfg(alternatives)
        log = SimpleNamespace(warn=lambda *a: None, log=lambda *a: None)
        clock = [100.]
        st = dict(state.default_state(), night_id="test", plan_author_model="not-gpt")
        e = providers.ProviderError("quota", "quota")
        e.weekly = weekly
        if not weekly:
            e.retry_at = 120
        calls = []
        def chat(name, *args, **kw):
            calls.append(name)
            if len(calls) == 1 or twice:
                raise e
            return providers.Result("ok", name, "gpt" if name == "sub" else "other", 1, 1, 0, 1)
        waits = []
        def hook(st, elapsed):
            waits.append(elapsed)
        rt = router.Router(cfg, log, wait_hook=hook)
        with patch.object(router.providers, "chat", side_effect=chat), patch.object(router.events, "emit"), \
             patch.object(router.state_mod, "save"), patch.object(router.time, "time", side_effect=lambda: clock[0]), \
             patch.object(router.time, "sleep", side_effect=lambda n: clock.__setitem__(0, clock[0] + n)):
            try:
                result = rt.call("critic", st, [{"content": "same request"}], 1000)
            except providers.ProviderError:
                result = None
        return st, calls, waits, result

    def test_same_call_resumes_once_after_reset(self):
        st, calls, waits, result = self.run_wait()
        self.assertEqual(calls, ["sub", "sub"])
        self.assertEqual(result.text, "ok")
        self.assertTrue(waits)
        self.assertNotIn("subscription_wait", st)
        self.assertFalse(st.get("disabled_providers"))

    def test_allowed_alternative_before_wait(self):
        st, calls, waits, result = self.run_wait(alternatives=True)
        self.assertEqual(calls, ["sub", "cheap"])
        self.assertFalse(waits)

    def test_unknown_weekly_stops_without_sleep(self):
        st, calls, waits, result = self.run_wait(weekly=True)
        self.assertIsNone(result)
        self.assertFalse(waits)
        self.assertEqual(calls, ["sub"])
        self.assertTrue(st["subscription_blocked"]["weekly"])

    def test_repeated_quota_does_not_loop(self):
        st, calls, waits, result = self.run_wait(twice=True)
        self.assertEqual(calls, ["sub", "sub"])
        self.assertIsNone(result)

    def test_stop_during_wait_never_retries_or_replays_phase(self):
        log = SimpleNamespace(warn=lambda *a: None, log=lambda *a: None)
        st = dict(state.default_state(), plan_author_model="other")
        e = providers.ProviderError("quota", "quota")
        e.retry_at = 120
        def stop(st, elapsed):
            raise subscription.WaitStopped()
        rt = router.Router(self.cfg(), log, wait_hook=stop)
        with patch.object(router.providers, "chat", side_effect=e) as call, \
             patch.object(router.events, "emit"), patch.object(router.state_mod, "save"), \
             patch.object(router.time, "time", return_value=100):
            with self.assertRaises(subscription.WaitStopped):
                rt.call("critic", st, [], 1000)
        self.assertEqual(call.call_count, 1)


if __name__ == "__main__":
    unittest.main()
