# -*- coding: utf-8 -*-
"""Контракты providers/router на mock-ответах: без сети, моделей и записи в workspace.

Проверяется:
- только content — финальный результат, reasoning_content результатом не является;
- SSE: валидный terminal finish, обрезка (length) без NameError, usage.cost;
- Router: гейты бюджета/cap/rate-limit на каждую физическую попытку, отдельный
  счётчик attempts_by_provider, начальный clamp max_tokens, retries=0 у вызова.

Запуск: .venv\\Scripts\\python.exe -m unittest autonomy.tests.test_provider_contracts -v
"""
import unittest
from unittest.mock import patch

from autonomy import providers, router


class FakeResp:
    """Минимальный ответ requests: status, json, iter_lines, headers, text."""

    def __init__(self, status_code=200, payload=None, lines=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self._lines = lines or []
        self.headers = headers or {}
        self.text = text
        self.encoding = None

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)


def sse(*chunks, done=True):
    """Список SSE-строк из словарей; done=True добавляет терминальный [DONE]."""
    lines = [f"data: {__import__('json').dumps(c)}" for c in chunks]
    if done:
        lines.append("data: [DONE]")
    return lines


def pcfg(**kw):
    cfg = {
        "base_url": "http://example.invalid/v1",
        "model": "test-model",
        "retries": 0,
        "timeout_s": 1,
        "price_in_usd_per_mtok": 1.0,
        "price_out_usd_per_mtok": 2.0,
    }
    cfg.update(kw)
    return cfg


def msg(text="hi"):
    return [{"role": "user", "content": text}]


class Log:
    def warn(self, m):
        pass

    def log(self, m):
        pass

    def error(self, m):
        pass


def night_cfg(**kw):
    cfg = {
        "budget_usd_per_night": 1.0,
        "provider_fail_limit": 2,
        "truncation_retry_cap": 64000,
        "max_calls_per_provider": {},
    }
    cfg.update(kw)
    return cfg


def router_cfg(providers_map, night=None, roles=None, role_limits=None):
    return {
        "night": night_cfg(**(night or {})),
        "providers": providers_map,
        "roles": roles or {"r": list(providers_map)},
        "role_limits": role_limits or {},
    }


class ProviderContentTests(unittest.TestCase):
    def test_only_reasoning_is_error(self):
        body = {
            "choices": [{"message": {"content": "", "reasoning_content": "думал"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20,
                      "completion_tokens_details": {"reasoning_tokens": 20}},
        }
        with patch("autonomy.providers.requests.post", return_value=FakeResp(200, body)):
            with self.assertRaises(providers.ProviderError) as cm:
                providers.chat("p", pcfg(), msg())
        err = cm.exception
        self.assertEqual(err.kind, "empty_reasoning")
        self.assertEqual((err.in_tok, err.out_tok), (10, 20))
        self.assertAlmostEqual(err.cost_usd, (10 * 1.0 + 20 * 2.0) / 1e6)

    def test_content_used_not_reasoning(self):
        body = {
            "choices": [{"message": {"content": "ответ", "reasoning_content": "думал"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4,
                      "completion_tokens_details": {"reasoning_tokens": 2}},
        }
        with patch("autonomy.providers.requests.post", return_value=FakeResp(200, body)):
            res = providers.chat("p", pcfg(), msg())
        self.assertEqual(res.text, "ответ")
        self.assertEqual(res.reasoning_tok, 2)

    def test_usage_cost_zero_is_used(self):
        body = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 1000, "cost": 0.0},
        }
        with patch("autonomy.providers.requests.post", return_value=FakeResp(200, body)):
            res = providers.chat("p", pcfg(), msg())
        self.assertEqual(res.cost_usd, 0.0)

    def test_usage_cost_positive_is_used(self):
        body = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "cost": 0.0042},
        }
        with patch("autonomy.providers.requests.post", return_value=FakeResp(200, body)):
            res = providers.chat("p", pcfg(), msg())
        self.assertEqual(res.cost_usd, 0.0042)

    def test_cost_estimate_when_usage_cost_missing(self):
        body = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 1000},
        }
        with patch("autonomy.providers.requests.post", return_value=FakeResp(200, body)):
            res = providers.chat("p", pcfg(), msg())
        self.assertAlmostEqual(res.cost_usd, (1000 * 1.0 + 1000 * 2.0) / 1e6)

    def test_usage_cost_negative_falls_back_to_estimate(self):
        body = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 1000, "cost": -1},
        }
        with patch("autonomy.providers.requests.post", return_value=FakeResp(200, body)):
            res = providers.chat("p", pcfg(), msg())
        self.assertAlmostEqual(res.cost_usd, 0.003)


class ProviderStreamTests(unittest.TestCase):
    def test_truncated_sse_without_nameerror(self):
        lines = sse(
            {"choices": [{"delta": {"content": "abc"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "length"}]},
            {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 7,
                                      "cost": 0.5,
                                      "completion_tokens_details": {"reasoning_tokens": 7}}},
        )
        with patch("autonomy.providers.requests.post",
                   return_value=FakeResp(200, lines=lines)):
            with self.assertRaises(providers.ProviderError) as cm:
                providers.chat("p", pcfg(stream=True), msg(), max_tokens=100)
        err = cm.exception
        self.assertEqual(err.kind, "truncated")
        self.assertIn("max_tokens=100", str(err))
        self.assertEqual((err.in_tok, err.out_tok), (5, 7))
        self.assertEqual(err.cost_usd, 0.5)

    def test_unfinished_sse_is_not_success(self):
        lines = sse(
            {"choices": [{"delta": {"content": "abc"}, "finish_reason": None}]},
            done=False,
        )
        with patch("autonomy.providers.requests.post",
                   return_value=FakeResp(200, lines=lines)):
            with self.assertRaises(providers.ProviderError) as cm:
                providers.chat("p", pcfg(stream=True), msg(), max_tokens=100)
        self.assertEqual(cm.exception.kind, "stream_incomplete")

    def test_sse_terminal_finish_is_success(self):
        lines = sse(
            {"choices": [{"delta": {"content": "го"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "тово"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2,
                                      "cost": 0.0}},
        )
        with patch("autonomy.providers.requests.post",
                   return_value=FakeResp(200, lines=lines)):
            res = providers.chat("p", pcfg(stream=True), msg(), max_tokens=100)
        self.assertEqual(res.text, "готово")
        self.assertEqual(res.finish, "stop")
        self.assertEqual(res.cost_usd, 0.0)

    def test_sse_only_reasoning_is_error(self):
        lines = sse(
            {"choices": [{"delta": {"reasoning_content": "думал"},
                          "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 9,
                                      "completion_tokens_details": {"reasoning_tokens": 9}}},
        )
        with patch("autonomy.providers.requests.post",
                   return_value=FakeResp(200, lines=lines)):
            with self.assertRaises(providers.ProviderError) as cm:
                providers.chat("p", pcfg(stream=True), msg(), max_tokens=100)
        self.assertEqual(cm.exception.kind, "empty_reasoning")


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.emit_patch = patch(
            "autonomy.router.events.emit",
            side_effect=lambda t, **kw: self.events.append((t, kw)))
        self.emit_patch.start()
        self.addCleanup(self.emit_patch.stop)

    def _st(self, **kw):
        st = {"budget_used_usd": 0.0, "calls_by_provider": {}, "provider_fails": {}}
        st.update(kw)
        return st

    def test_only_failed_attempt_counted_separately(self):
        err = providers.ProviderError("boom", "provider", 0.02, 11, 12)
        cfg = router_cfg({"p": pcfg()})
        st = self._st()
        with patch("autonomy.router.providers.chat", side_effect=err) as chat:
            with self.assertRaises(providers.ProviderError):
                router.Router(cfg, Log()).call("r", st, msg())
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(st["attempts_by_provider"], {"p": 1})
        self.assertEqual(st.get("calls_by_provider"), {})
        self.assertAlmostEqual(st["budget_used_usd"], 0.02)
        fails = [kw for t, kw in self.events if t == "model_fail"]
        self.assertEqual(len(fails), 1)
        self.assertEqual(fails[0]["cost_usd"], 0.02)
        self.assertEqual((fails[0]["in_tok"], fails[0]["out_tok"]), (11, 12))
        self.assertEqual(fails[0]["attempt"], 1)

    def test_call_cap_counts_failed_attempts(self):
        cfg = router_cfg({"p": pcfg()},
                         night={"max_calls_per_provider": {"p": 1},
                                "provider_fail_limit": 9})
        st = self._st()
        err = providers.ProviderError("boom", "provider", 0.0, 1, 1)
        r = router.Router(cfg, Log())
        with patch("autonomy.router.providers.chat", side_effect=err) as chat:
            with self.assertRaises(providers.ProviderError):
                r.call("r", st, msg())
            # Неудачная попытка уже израсходовала cap — второй вызов не идёт.
            with self.assertRaises(providers.ProviderError):
                r.call("r", st, msg())
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(st["attempts_by_provider"]["p"], 1)

    def test_call_cap_blocks_truncation_retry(self):
        cfg = router_cfg({"p": pcfg()},
                         night={"max_calls_per_provider": {"p": 1},
                                "truncation_retry_cap": 64000})
        st = self._st()
        err = providers.ProviderError("trunc", "truncated", 0.0, 1, 100)
        with patch("autonomy.router.providers.chat", side_effect=err) as chat:
            with self.assertRaises(providers.ProviderError):
                router.Router(cfg, Log()).call("r", st, msg(), max_tokens=100)
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(st["attempts_by_provider"]["p"], 1)

    def test_call_cap_blocks_first_call_when_exhausted(self):
        cfg = router_cfg({"p": pcfg()},
                         night={"max_calls_per_provider": {"p": 1}})
        st = self._st(attempts_by_provider={"p": 1})
        with patch("autonomy.router.providers.chat") as chat:
            with self.assertRaises(providers.ProviderError):
                router.Router(cfg, Log()).call("r", st, msg())
        chat.assert_not_called()

    def test_budget_after_truncation_blocks_second_call(self):
        cfg = router_cfg({"p": pcfg(price_out_usd_per_mtok=1.0)},
                         night={"budget_usd_per_night": 1.0})
        st = self._st()
        err = providers.ProviderError("trunc", "truncated", 0.99995, 1, 100)
        with patch("autonomy.router.providers.chat", side_effect=err) as chat:
            with self.assertRaises(providers.ProviderError):
                router.Router(cfg, Log()).call("r", st, msg(), max_tokens=100)
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(st["attempts_by_provider"]["p"], 1)

    def test_truncation_retry_allowed_and_counted(self):
        cfg = router_cfg({"p": pcfg()}, night={"budget_usd_per_night": 1.0})
        st = self._st()
        err = providers.ProviderError("trunc", "truncated", 0.001, 1, 100)
        res = providers.Result("ok", "p", "test-model", 1, 2, 0.0005, 0.1, "stop")
        with patch("autonomy.router.providers.chat",
                   side_effect=[err, res]) as chat:
            got = router.Router(cfg, Log()).call("r", st, msg(), max_tokens=100)
        self.assertEqual(got.text, "ok")
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(chat.call_args_list[0].kwargs["max_tokens"], 100)
        self.assertEqual(chat.call_args_list[1].kwargs["max_tokens"], 200)
        self.assertEqual(st["attempts_by_provider"]["p"], 2)
        self.assertEqual(st["calls_by_provider"]["p"], 1)
        self.assertAlmostEqual(st["budget_used_usd"], 0.0015)

    def test_initial_max_tokens_clamped_to_provider_cap(self):
        cfg = router_cfg({"p": pcfg(max_output_tokens=64)},
                         role_limits={"r": {"max_tokens": 4096}})
        st = self._st()
        res = providers.Result("ok", "p", "m", 1, 1, 0.0, 0.1, "stop")
        with patch("autonomy.router.providers.chat", return_value=res) as chat:
            router.Router(cfg, Log()).call("r", st, msg(), max_tokens=4096)
        self.assertEqual(chat.call_args.kwargs["max_tokens"], 64)

    def test_initial_max_tokens_clamped_to_retry_cap(self):
        cfg = router_cfg({"p": pcfg()}, night={"truncation_retry_cap": 100})
        st = self._st()
        res = providers.Result("ok", "p", "m", 1, 1, 0.0, 0.1, "stop")
        with patch("autonomy.router.providers.chat", return_value=res) as chat:
            router.Router(cfg, Log()).call("r", st, msg(), max_tokens=4096)
        self.assertEqual(chat.call_args.kwargs["max_tokens"], 100)

    def test_router_forces_zero_retries_without_mutating_config(self):
        cfg = router_cfg({"p": pcfg(retries=2)})
        st = self._st()
        res = providers.Result("ok", "p", "m", 1, 1, 0.0, 0.1, "stop")
        with patch("autonomy.router.providers.chat", return_value=res) as chat:
            router.Router(cfg, Log()).call("r", st, msg())
        self.assertEqual(chat.call_args.args[1]["retries"], 0)
        self.assertEqual(cfg["providers"]["p"]["retries"], 2)


class IndependenceTests(unittest.TestCase):
    """Независимость проверяющих ролей: сравнивается model ID, а не алиас."""

    def setUp(self):
        self.events = []
        self.emit_patch = patch(
            "autonomy.router.events.emit",
            side_effect=lambda t, **kw: self.events.append((t, kw)))
        self.emit_patch.start()
        self.addCleanup(self.emit_patch.stop)

    def _st(self, **kw):
        st = {"budget_used_usd": 0.0, "calls_by_provider": {}, "provider_fails": {}}
        st.update(kw)
        return st

    def _cfg(self, providers_map, roles):
        return router_cfg(providers_map, roles=roles)

    def _skips(self):
        return [kw for t, kw in self.events if t == "model_skip"]

    def test_verifier_fallback_skips_executor_model(self):
        cfg = self._cfg(
            {"exec": pcfg(model="m-exec"), "other": pcfg(model="m-other")},
            {"executor": ["exec"], "verifier": ["exec", "other"]})
        st = self._st(last_model_by_role={"executor": "m-exec"})
        res = providers.Result("ok", "other", "m-other", 1, 1, 0.0, 0.1, "stop")
        with patch("autonomy.router.providers.chat", return_value=res) as chat:
            got = router.Router(cfg, Log()).call("verifier", st, msg())
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(chat.call_args.args[0], "other")
        self.assertEqual(got.model, "m-other")
        self.assertEqual(st["last_model_by_role"]["verifier"], "m-other")
        skips = self._skips()
        self.assertEqual(len(skips), 1)
        self.assertEqual(skips[0]["provider"], "exec")
        self.assertEqual(skips[0]["model"], "m-exec")
        self.assertEqual(skips[0]["reason"], "independence")

    def test_critic_skips_author_model(self):
        cfg = self._cfg(
            {"plan": pcfg(model="m-plan"), "other": pcfg(model="m-other")},
            {"planner": ["plan"], "critic": ["plan", "other"]})
        # Автор плана пришёл от mentor и совпал с моделью planner-лестницы.
        st = self._st(plan_author_model="m-plan")
        res = providers.Result("ok", "other", "m-other", 1, 1, 0.0, 0.1, "stop")
        with patch("autonomy.router.providers.chat", return_value=res) as chat:
            router.Router(cfg, Log()).call("critic", st, msg())
        self.assertEqual(chat.call_args.args[0], "other")
        skips = self._skips()
        self.assertEqual([s["provider"] for s in skips], ["plan"])
        self.assertEqual(st["last_model_by_role"]["critic"], "m-other")

    def test_same_model_under_other_alias_is_skipped(self):
        cfg = self._cfg(
            {"a": pcfg(model="m-plan"), "b": pcfg(model="m-plan")},
            {"planner": ["a"], "critic": ["a", "b"]})
        st = self._st(plan_author_model="m-plan")
        with patch("autonomy.router.providers.chat") as chat:
            with self.assertRaises(providers.ProviderError) as cm:
                router.Router(cfg, Log()).call("critic", st, msg())
        self.assertEqual(cm.exception.kind, "ladder")
        chat.assert_not_called()
        # Оба алиаса одной модели пропущены, но ни один не отключён глобально.
        self.assertEqual([s["provider"] for s in self._skips()], ["a", "b"])
        self.assertFalse(st.get("disabled_providers"))
        self.assertEqual(st["attempts_by_provider"], {})

    def test_missing_author_excludes_whole_planner_ladder(self):
        cfg = self._cfg(
            {"plan": pcfg(model="m-plan"), "other": pcfg(model="m-other")},
            {"planner": ["plan"], "critic": ["plan", "other"]})
        # План загружен извне: plan_author_model и last_model_by_role пусты.
        st = self._st()
        res = providers.Result("ok", "other", "m-other", 1, 1, 0.0, 0.1, "stop")
        with patch("autonomy.router.providers.chat", return_value=res) as chat:
            router.Router(cfg, Log()).call("critic", st, msg())
        self.assertEqual(chat.call_args.args[0], "other")
        skips = self._skips()
        self.assertEqual([s["provider"] for s in skips], ["plan"])


if __name__ == "__main__":
    unittest.main()
