import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import requests

from autonomy import valyu_reader as v


URL = "https://example.org/paper"


class Response:
    def __init__(self, status=200, data=None, headers=None, raw=None):
        self.status_code, self.headers, self.raw = status, headers or {}, raw
        self.data = {"cost": .001, **(data if data is not None else {"success": True, "results": [{"url": URL, "status": "success", "content": "original"}]})}
        self.closed = False

    def iter_content(self, chunk_size):
        raw = self.raw if self.raw is not None else json.dumps(self.data).encode()
        for i in range(0, len(raw), chunk_size):
            yield raw[i:i + chunk_size]

    def close(self):
        self.closed = True


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Path(self.tmp.name) / "ledger.sqlite3"
        env_patch = patch.object(v.env, "get", return_value="private-api-key")
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.real_transport = v._isolated_transport
        transport = patch.object(v, "_isolated_transport", side_effect=v._http_transport)
        transport.start()
        self.addCleanup(transport.stop)

    def call(self, **kw):
        args = {"scope_id": "MT-test", "budget_usd": .1, "ledger_path": self.ledger}
        args.update(kw)
        url = args.pop("url", URL)
        return v.read_page(url, **args)

    def denied(self, code, **kw):
        with self.assertRaises(v.ValyuUnavailable) as cm:
            self.call(**kw)
        self.assertEqual(cm.exception.code, code)

    def test_success_flags_and_auth(self):
        response = Response()
        with patch.object(v.requests, "post", return_value=response) as post:
            result = self.call()
        self.assertEqual(result["page"]["url"], URL)
        self.assertEqual(result["page"]["content"], "original")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0], v._ENDPOINT)
        opts = post.call_args.kwargs
        self.assertEqual(opts["headers"]["x-api-key"], "private-api-key")
        self.assertEqual(opts["json"], {"urls": [URL], "response_length": "short", "extract_effort": "normal", "summary": False, "screenshot": False, "max_age": 0})
        self.assertTrue(opts["stream"])
        self.assertFalse(opts["allow_redirects"])
        self.assertTrue(response.closed)
        self.assertNotIn("private-api-key", repr(result))
        self.assertNotIn(b"private-api-key", self.ledger.read_bytes())

    def test_budget_denied(self):
        with patch.object(v.requests, "post") as post:
            self.denied("budget_denied", budget_usd=0)
            post.assert_not_called()
        self.assertEqual(v.usage("MT-test", self.ledger)["counts"], 0)

    def test_budget_shared_across_calls(self):
        with patch.object(v.requests, "post", return_value=Response()) as post:
            self.call(budget_usd=.01)
            self.denied("budget_denied", budget_usd=.01)
            self.assertEqual(post.call_count, 1)

    def test_scope_quota(self):
        with patch.object(v.requests, "post", return_value=Response()) as post:
            self.call(max_calls=1)
            self.denied("scope_quota", max_calls=1)
            self.assertEqual(post.call_count, 1)

    def test_global_daily_quota(self):
        with patch.object(v.requests, "post", return_value=Response()) as post:
            for i in range(20):
                self.call(scope_id=f"scope-{i}")
            self.denied("daily_quota", scope_id="other")
            self.assertEqual(post.call_count, 20)

    def test_concurrent_one_inflight(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def post(*args, **kwargs):
            entered.set()
            release.wait(5)
            return Response()
        def worker():
            try:
                self.call(budget_usd=.01)
            except Exception as exc:
                errors.append(exc)
        with patch.object(v.requests, "post", side_effect=post) as mock:
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.denied("inflight", budget_usd=.01)
            finally:
                release.set()
                thread.join(5)
            self.assertEqual(mock.call_count, 1)
        self.assertFalse(errors)

    def test_no_retry_and_failure_reserved(self):
        with patch.object(v.requests, "post", side_effect=requests.Timeout("secret body")) as post:
            result = self.call()
            self.assertEqual(post.call_count, 1)
        self.assertEqual(result["attempt"]["error_code"], "unknown_cost")
        self.assertNotIn("secret body", repr(result))
        self.assertEqual(v.usage("MT-test", self.ledger), {"counts": 1, "reserved_usd": .01, "reported_cost_usd": 0, "unknown_cost_attempts": 1, "charge_usd": .01})

    def test_auth_persistent_hold(self):
        with patch.object(v.requests, "post", return_value=Response(401)) as post:
            self.assertEqual(self.call()["attempt"]["http_status"], 401)
            self.denied("circuit_disabled", scope_id="other")
            self.assertEqual(post.call_count, 1)

    def test_rate_limit_hold(self):
        with patch.object(v.requests, "post", return_value=Response(429, headers={"Retry-After": "1"})) as post:
            self.call()
            self.denied("cooldown", scope_id="other")
            self.assertEqual(post.call_count, 1)
        with closing(sqlite3.connect(self.ledger)) as db:
            self.assertGreater(db.execute("SELECT cooldown FROM circuit").fetchone()[0], v.time.time() + 55)

    def test_invalid_and_summary_ignored(self):
        data = {"success": True, "results": [{"url": URL, "status": "ok", "summary": "invented", "content": ""}]}
        with patch.object(v.requests, "post", return_value=Response(data=data)):
            result = self.call()
        self.assertIsNone(result["page"])
        self.assertEqual(result["attempt"]["error_code"], "invalid_content")
        self.assertNotIn("invented", repr(result))

    def test_wrong_url(self):
        data = {"results": [{"url": "https://example.org/other", "status": "success", "content": "text"}]}
        with patch.object(v.requests, "post", return_value=Response(data=data)):
            self.assertEqual(self.call()["attempt"]["error_code"], "url_mismatch")

    def test_missing_key_no_ledger(self):
        with patch.object(v.env, "get", return_value=None), patch.object(v.requests, "post") as post:
            self.denied("missing_key")
            post.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_reported_over_reservation_disables(self):
        data = {"total_deduction_dollars": .02, "results": [{"url": URL, "status": "ok", "content": "text"}]}
        with patch.object(v.requests, "post", return_value=Response(data=data)) as post:
            result = self.call()
            self.denied("circuit_disabled", scope_id="other")
            self.assertEqual(post.call_count, 1)
        self.assertEqual(result["attempt"]["reported_cost_usd"], .02)
        self.assertEqual(result["attempt"]["cost_status"], "reported")
        self.assertEqual(v.usage("MT-test", self.ledger)["reported_cost_usd"], .02)

    def test_private_or_secret_urls_rejected(self):
        urls = ["http://127.0.0.1/", "http://localhost/a", "http://10.0.0.1/a", "https://user:pass@example.org/", "https://example.org/?token=secret", "https://example.org/api_key/secret"]
        with patch.object(v.requests, "post") as post:
            for url in urls:
                with self.subTest(url=url):
                    self.denied("invalid_url", url=url)
            post.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_remote_failure_and_redaction(self):
        with patch.object(v.requests, "post", return_value=Response(data={"success": False, "error": "private detail"})):
            result = self.call()
        self.assertEqual(result["attempt"]["error_code"], "remote_failure")
        self.assertNotIn("private detail", repr(result))

    def test_redirect_and_body_limit(self):
        with patch.object(v.requests, "post", side_effect=[Response(302), Response(raw=b"x" * (256 * 1024 + 1))]):
            self.assertIsNone(self.call()["page"])
            self.assertEqual(self.call()["attempt"]["error_code"], "unknown_cost")

    def test_stale_inflight_never_taken_over(self):
        v.usage("MT-test", self.ledger)
        with closing(sqlite3.connect(self.ledger)) as db:
            db.execute("UPDATE circuit SET owner='stale', lease_until=0")
            db.commit()
        with patch.object(v.requests, "post") as post:
            self.denied("inflight")
            post.assert_not_called()

    def test_challenge_and_data_type(self):
        with patch.object(v.requests, "post", side_effect=[
            Response(data={"results": [{"url": URL, "status": "ok", "content": "CAPTCHA"}]}),
            Response(data={"results": [{"url": URL, "status": "ok", "content": "x", "data_type": "structured"}]})]):
            self.assertEqual(self.call()["attempt"]["error_code"], "challenge")
            self.assertEqual(self.call()["attempt"]["error_code"], "invalid_content")

    def test_charge_mixed_unknown_and_reported(self):
        v.usage("MT-test", self.ledger)
        with closing(sqlite3.connect(self.ledger)) as db:
            db.executemany("INSERT INTO attempts VALUES(?,?,?,?,?)", [("a", "MT-test", "2026-01-01", 1, None), ("b", "MT-test", "2026-01-01", 1, .015)])
            db.commit()
        summary = v.usage("MT-test", self.ledger)
        self.assertAlmostEqual(summary["charge_usd"], .025)
        self.assertEqual(summary["reserved_usd"], .02)
        self.assertEqual(summary["unknown_cost_attempts"], 1)

    def test_close_failure_does_not_prevent_ledger_update(self):
        response = Response()
        response.close = lambda: (_ for _ in ()).throw(RuntimeError("secret"))
        with patch.object(v.requests, "post", return_value=response):
            self.assertEqual(self.call()["attempt"]["outcome"], "success")
        self.assertEqual(v.usage("MT-test", self.ledger)["reported_cost_usd"], .001)

    def test_unknown_cost_disables(self):
        with patch.object(v.requests, "post", return_value=Response(raw=b'{"results":[]}')):
            result = self.call()
        self.assertIsNone(result["page"])
        self.assertEqual(result["attempt"]["error_code"], "unknown_cost")
        self.denied("circuit_disabled", scope_id="other")

    def test_valid_contents_without_usage_keeps_full_reservation(self):
        raw = json.dumps({'success': True, 'results': [{'url': URL, 'status': 'success', 'content': 'retrieved text'}]}).encode()
        with patch.object(v.requests, 'post', return_value=Response(raw=raw)):
            result = self.call()
        self.assertEqual(result['page']['content'], 'retrieved text')
        self.assertEqual(result['attempt']['cost_status'], 'unknown')
        self.assertEqual(v.usage('MT-test', self.ledger)['charge_usd'], .01)
        self.assertEqual(v.usage('MT-test', self.ledger)['unknown_cost_attempts'], 1)

    def test_observed_contents_total_cost_dollars(self):
        self.assertEqual(v._reported({'total_cost_dollars': .00125}), .00125)
        self.assertFalse(v._billing_invalid({'total_cost_dollars': .00125}))
        self.assertTrue(v._billing_invalid({'total_cost_dollars': .00125, 'cost': .05}))
        raw = json.dumps({'success': True, 'total_cost_dollars': .00125,
            'results': [{'url': URL, 'status': 'success', 'content': 'retrieved text'}]}).encode()
        with patch.object(v.requests, 'post', return_value=Response(raw=raw)):
            result = self.call()
        self.assertEqual(result['attempt']['reported_cost_usd'], .00125)
        self.assertEqual(result['attempt']['cost_status'], 'reported')
        self.assertEqual(v.usage('MT-test', self.ledger)['charge_usd'], .01)

    def test_conflicting_billing_fields_are_rejected_with_maximum_known_charge(self):
        for fields, expected in (({'total_deduction_dollars': .00125, 'cost': 'bad'}, .00125),
                                 ({'total_deduction_dollars': .00125, 'cost': .05}, .05)):
            self.assertEqual(v._reported(fields), expected)
            self.assertTrue(v._billing_invalid(fields))
            raw = json.dumps({'success': True, 'results': [{'url': URL, 'status': 'success', 'content': 'text'}], **fields}).encode()
            with patch.object(v.requests, 'post', return_value=Response(raw=raw)):
                result = v._http_transport(URL, 'not-a-real-key', 1, 'fixture')
            self.assertTrue(result['disable'])
            self.assertIsNone(result['page'])
            self.assertEqual(result['cost'], expected)

    def test_worker_timeout_kills_and_drains(self):
        class Proc:
            returncode = None
            def __init__(self):
                self.killed = False
                self.calls = 0
            def communicate(self, input=None, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise v.subprocess.TimeoutExpired("worker", timeout)
                return b"", b""
            def kill(self):
                self.killed = True
        proc = Proc()
        # Bypass the test fixture's in-process transport patch.
        with patch.object(v, "_isolated_transport", self.real_transport), patch.object(v.subprocess, "Popen", return_value=proc):
            result = self.call(timeout_s=1)
            self.assertEqual(result["attempt"]["error_code"], "transport_timeout")
            self.denied("circuit_disabled", scope_id="other")
        self.assertTrue(proc.killed)
        self.assertEqual(proc.calls, 2)
        self.assertEqual(v.usage("MT-test", self.ledger)["unknown_cost_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
