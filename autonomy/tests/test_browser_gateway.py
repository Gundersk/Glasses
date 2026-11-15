import datetime as dt
import email.utils
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
import yaml

from autonomy import browser_gateway as g
from autonomy.providers import ProviderError


class Response:
    def __init__(self, status=200, data=None, headers=None, raw=None):
        self.status_code, self.data, self.headers = status, data, headers or {}
        self.raw = raw
        self.closed = False

    def iter_content(self, chunk_size):
        raw = self.raw if self.raw is not None else json.dumps(self.data).encode()
        for i in range(0, len(raw), chunk_size):
            yield raw[i:i + chunk_size]

    def close(self):
        self.closed = True


def ok(text="hello", finish="stop"):
    return Response(data={"choices": [{"message": {"content": text}, "finish_reason": finish}]})


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {"kind": "browser-session", "model": "kimi", "ledger_path": str(Path(self.tmp.name) / "ledger.sqlite3")}
        self.env = patch.object(g.env, "get", side_effect=lambda name, default=None: default)
        self.env.start()
        self.addCleanup(self.env.stop)

    def call(self, cfg=None, messages=None):
        return g.chat("browser", cfg or self.cfg, messages or [{"role": "user", "content": "hi"}])

    def assert_unavailable(self, cfg=None):
        with self.assertRaises(ProviderError) as e:
            self.call(cfg)
        self.assertEqual(e.exception.kind, "browser_unavailable")

    def test_success_one_post(self):
        with patch.object(g.requests, "post", return_value=ok()) as post:
            result = self.call()
        self.assertEqual((result.text, result.model, result.cost_usd), ("hello", "Kimi-K2.6", 0))
        self.assertEqual(post.call_count, 1)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertTrue(post.call_args.kwargs["stream"])
        self.assertFalse(post.call_args.kwargs["json"]["stream"])
        self.assertTrue(post.return_value.closed)
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 4000)

    def test_upstream_mapping_keeps_alias_counts(self):
        policy = {"group_daily_cap": 30, "cooldown_s": 60, "models": {
            "kimi": {"daily_cap": 6, "max_output_tokens": 4000,
                     "upstream_model": "Kimi-K2.6"}}}
        policy_file = Path(self.tmp.name) / "policy.yaml"
        policy_file.write_text(yaml.safe_dump(policy), encoding="utf-8")
        cfg = {**self.cfg, "policy_file": str(policy_file)}
        with patch.object(g.requests, "post", return_value=ok()) as post:
            result = self.call(cfg)
        self.assertEqual(post.call_args.kwargs["json"]["model"], "Kimi-K2.6")
        self.assertEqual(result.model, "Kimi-K2.6")
        self.assertEqual(g.status(cfg)["counts"], {"kimi": 1})

    def test_invalid_upstream_mapping(self):
        policy = {"group_daily_cap": 30, "cooldown_s": 60, "models": {
            "kimi": {"daily_cap": 6, "max_output_tokens": 4000, "upstream_model": " "}}}
        path = Path(self.tmp.name) / "policy.yaml"
        path.write_text(yaml.safe_dump(policy), encoding="utf-8")
        with patch.object(g.requests, "post") as post:
            with self.assertRaises(ProviderError):
                self.call({**self.cfg, "policy_file": str(path)})
            post.assert_not_called()

    def test_context_reject_no_quota(self):
        with self.assertRaises(ProviderError):
            self.call(messages=[{"role": "user", "content": "x" * 50000}])
        self.assertEqual(g.status(self.cfg)["counts"], {})

    def test_unknown_model(self):
        with self.assertRaises(ProviderError) as e:
            self.call({**self.cfg, "model": "unknown"})
        self.assertEqual(e.exception.kind, "config")

    def test_group_cooldown_and_persistent_counts(self):
        with patch.object(g.requests, "post", return_value=ok()) as post:
            self.call()
            self.assert_unavailable({**self.cfg, "model": "qwen-max"})
            self.assertEqual(post.call_count, 1)
        self.assertEqual(g.status(dict(self.cfg))["counts"], {"kimi": 1})

    def test_singleflight_concurrent(self):
        entered, release = threading.Event(), threading.Event()
        def post(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return ok()
        errors = []
        def worker():
            try:
                self.call()
            except Exception as e:
                errors.append(e)
        with patch.object(g.requests, "post", side_effect=post) as mock:
            t = threading.Thread(target=worker)
            t.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assert_unavailable({**self.cfg, "model": "qwen-max"})
            finally:
                release.set()
                t.join(5)
            self.assertEqual(mock.call_count, 1)
        self.assertFalse(errors)

    def test_captcha_hold_all(self):
        with patch.object(g.requests, "post", return_value=ok("Please verify you're human")):
            self.assert_unavailable()
        self.assertTrue(g.status(self.cfg)["hold"])
        self.assert_unavailable({**self.cfg, "model": "qwen-max"})
        g.clear_hold(self.cfg)
        self.assertFalse(g.status(self.cfg)["hold"])

    def test_auth_hold(self):
        with patch.object(g.requests, "post", return_value=Response(401)):
            self.assert_unavailable()
        self.assertTrue(g.status(self.cfg)["hold"])

    def test_retry_after_seconds(self):
        before = time.time()
        with patch.object(g.requests, "post", return_value=Response(429, headers={"Retry-After": "3600"})):
            self.assert_unavailable()
        self.assertGreaterEqual(g.status(self.cfg)["next_at"], before + 3600)

    def test_retry_after_date(self):
        date = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=4000), usegmt=True)
        with patch.object(g.requests, "post", return_value=Response(429, headers={"Retry-After": date})):
            self.assert_unavailable()
        self.assertGreater(g.status(self.cfg)["next_at"], time.time() + 3900)

    def test_timeout_cooldown(self):
        with patch.object(g.requests, "post", side_effect=requests.Timeout("secret")):
            self.assert_unavailable()
        self.assertGreaterEqual(g.status(self.cfg)["next_at"], time.time() + 295)
        self.assertTrue(g.status(self.cfg)["manual_hold"])

    def test_server_error(self):
        with patch.object(g.requests, "post", return_value=Response(503)):
            with self.assertRaises(ProviderError) as error:
                self.call()
        self.assertEqual(str(error.exception), "browser_gateway:http_503")
        self.assertGreaterEqual(g.status(self.cfg)["next_at"], time.time() + 295)

    def test_bad_json_redacted(self):
        with patch.object(g.requests, "post", return_value=Response(raw=b"SECRET cookie")):
            with self.assertRaises(ProviderError) as e:
                self.call()
        self.assertNotIn("SECRET", str(e.exception))
        self.assertGreaterEqual(g.status(self.cfg)["next_at"], time.time() + 295)

    def test_truncated(self):
        with patch.object(g.requests, "post", return_value=ok("partial", "length")):
            self.assert_unavailable()

    def test_stale_lease_preserves_counts(self):
        g.clear_hold(self.cfg)
        day = dt.datetime.now(dt.timezone.utc).date().isoformat()
        db = sqlite3.connect(self.cfg["ledger_path"])
        try:
            db.execute("INSERT INTO counts VALUES (?,?,?)", (day, "kimi", 2))
            db.execute("UPDATE state SET owner='stale', lease_until=1, next_at=0")
            db.commit()
        finally:
            db.close()
        with patch.object(g.requests, "post", return_value=ok()):
            self.assert_unavailable()
            self.assertTrue(g.status(self.cfg)["inflight"])
            g.clear_hold(self.cfg)
            self.assertEqual(g.status(self.cfg)["counts"]["kimi"], 2)
            self.call()
        self.assertEqual(g.status(self.cfg)["counts"]["kimi"], 3)

    def test_expired_lease_no_takeover_during_slow_request(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def post(*args, **kwargs):
            entered.set()
            release.wait(5)
            return ok()
        def run():
            try:
                self.call()
            except Exception as e:
                errors.append(e)
        with patch.object(g.requests, "post", side_effect=post) as mock:
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(ProviderError):
                    g.clear_hold(self.cfg)
                db = sqlite3.connect(self.cfg["ledger_path"])
                try:
                    db.execute("UPDATE state SET lease_until=1,next_at=0")
                    db.commit()
                finally:
                    db.close()
                self.assert_unavailable({**self.cfg, "model": "qwen-max"})
                self.assertEqual(mock.call_count, 1)
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(errors)

    def test_challenge_html_503_and_json_400(self):
        for code, raw in [(503, b'<html>cf-please-wait SECRET</html>'),
                          (400, b'{"error":"captcha required SECRET"}')]:
            with self.subTest(code=code):
                cfg = {**self.cfg, "ledger_path": str(Path(self.tmp.name) / f"{code}.sqlite3")}
                response = Response(code, raw=raw)
                with patch.object(g.requests, "post", return_value=response):
                    with self.assertRaises(ProviderError) as error:
                        self.call(cfg)
                self.assertNotIn("SECRET", str(error.exception))
                self.assertTrue(g.status(cfg)["manual_hold"])
                self.assertTrue(response.closed)

    def test_oversize_body_rejected_and_closed(self):
        response = Response(raw=b"SECRET" + b"x" * (128 * 1024))
        with patch.object(g.requests, "post", return_value=response):
            with self.assertRaises(ProviderError) as error:
                self.call()
        self.assertNotIn("SECRET", str(error.exception))
        self.assertTrue(response.closed)
        self.assertTrue(g.status(self.cfg)["manual_hold"])

    def test_oversize_text_rejected(self):
        response = ok("x" * 32001)
        with patch.object(g.requests, "post", return_value=response):
            self.assert_unavailable()
        self.assertTrue(response.closed)
        self.assertFalse(g.status(self.cfg)["manual_hold"])

    def test_broken_stream_hold_closed_redacted(self):
        response = Response()
        def broken(chunk_size):
            yield b"part"
            raise requests.ConnectionError("SECRET")
        response.iter_content = broken
        with patch.object(g.requests, "post", return_value=response):
            with self.assertRaises(ProviderError) as error:
                self.call()
        self.assertNotIn("SECRET", str(error.exception))
        self.assertTrue(response.closed)
        self.assertTrue(g.status(self.cfg)["manual_hold"])

    def test_absolute_deadline_during_stream(self):
        response = Response()
        closed, finished = threading.Event(), threading.Event()
        def close():
            response.closed = True
            closed.set()
        response.close = close
        def slow(chunk_size):
            time.sleep(.3)
            yield b"{}"
        response.iter_content = slow
        original = g._finish
        def finish(*args, **kwargs):
            try:
                return original(*args, **kwargs)
            finally:
                finished.set()
        with patch.object(g.requests, "post", return_value=response), patch.object(g, "_finish", side_effect=finish):
            self.assert_unavailable({**self.cfg, "_deadline_ts": time.time() + .15})
            self.assertTrue(closed.wait(2))
            self.assertTrue(finished.wait(2))
        self.assertTrue(response.closed)
        self.assertTrue(g.status(self.cfg)["manual_hold"])

    def test_watchdog_blocked_transport_hold_and_late_result(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def post(*args, **kwargs):
            entered.set()
            release.wait(5)
            return ok()
        original = g._finish
        def finish(*args, **kwargs):
            try:
                return original(*args, **kwargs)
            finally:
                finished.set()
        with patch.object(g.requests, "post", side_effect=post), patch.object(g, "_finish", side_effect=finish):
            start = time.monotonic()
            try:
                with self.assertRaises(ProviderError) as error:
                    self.call({**self.cfg, "timeout_s": .05})
                self.assertLess(time.monotonic() - start, 1)
                self.assertTrue(entered.is_set())
                self.assertEqual(str(error.exception), "browser_gateway:deadline_expired")
                state = g.status(self.cfg)
                self.assertTrue(state["manual_hold"])
                self.assertTrue(state["inflight"])
            finally:
                release.set()
                self.assertTrue(finished.wait(3))
        state = g.status(self.cfg)
        self.assertTrue(state["manual_hold"])
        self.assertFalse(state["inflight"])

    def test_mark_uncertain_write_error_fail_closed(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def post(*args, **kwargs):
            entered.set()
            release.wait(5)
            return ok()
        original = g._finish
        def finish(*args, **kwargs):
            try:
                return original(*args, **kwargs)
            finally:
                finished.set()
        with patch.object(g.requests, "post", side_effect=post), patch.object(g, "_finish", side_effect=finish):
            try:
                with patch.object(g, "_mark_uncertain", side_effect=ProviderError("browser_gateway:ledger_error", kind="browser_unavailable")):
                    with self.assertRaises(ProviderError) as error:
                        self.call({**self.cfg, "timeout_s": .05})
                self.assertEqual(str(error.exception), "browser_gateway:ledger_error")
                self.assertTrue(entered.is_set())
                self.assertTrue(g.status(self.cfg)["inflight"])
                self.assert_unavailable()
            finally:
                release.set()
                self.assertTrue(finished.wait(3))
        self.assertTrue(g.status(self.cfg)["manual_hold"])

    def test_mark_uncertain_storage_error_is_sanitized(self):
        with patch.object(g, "_connect", side_effect=OSError("secret storage path")):
            with self.assertRaises(ProviderError) as error:
                g._mark_uncertain(self.cfg)
        self.assertEqual(str(error.exception), "browser_gateway:ledger_error")

    def test_daily_cap_persists_across_calls(self):
        g.clear_hold(self.cfg)
        day = dt.datetime.now(dt.timezone.utc).date().isoformat()
        db = sqlite3.connect(self.cfg["ledger_path"])
        try:
            db.execute("INSERT INTO counts VALUES (?,?,?)", (day, "kimi", 6))
            db.commit()
        finally:
            db.close()
        with patch.object(g.requests, "post") as post:
            self.assert_unavailable(dict(self.cfg))
            post.assert_not_called()
        self.assertTrue(g.status(self.cfg)["daily_exhausted"])

    def test_status_missing_ledger(self):
        with patch.object(g.requests, "post") as post:
            state = g.status(self.cfg)
            post.assert_not_called()
        self.assertEqual((state["wait_seconds"], state["manual_hold"], state["inflight"], state["daily_exhausted"]), (0, False, False, False))
        self.assertFalse(Path(self.cfg["ledger_path"]).exists())

    def test_tools_rejected_before_reservation(self):
        with self.assertRaises(ProviderError):
            self.call(messages=[{"role": "assistant", "content": "hi", "tool_calls": []}])
        self.assertEqual(g.status(self.cfg)["counts"], {})

    def test_corrupt_ledger_fail_closed(self):
        Path(self.cfg["ledger_path"]).write_text("bad", encoding="utf-8")
        with patch.object(g.requests, "post") as post:
            self.assert_unavailable()
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
