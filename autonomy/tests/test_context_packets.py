import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autonomy import context_packets as cp, paths


class PacketsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.p1 = patch.object(paths, "PROJECT_ROOT", self.root)
        self.p2 = patch.object(paths, "WORKSPACE", self.root / "workspace")
        self.p1.start(); self.p2.start()
        self.addCleanup(self.p1.stop); self.addCleanup(self.p2.stop)
        self.capture = cp.Capture()
        self.st = {"night_id": "night", "phase": "DONE", "task": {"id": "x", "goal": "goal"}, "tasks": [], "request_outcome": "blocked"}

    def put(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")
        return p

    def error(self, code, fn, *args, **kwargs):
        with self.assertRaises(cp.ContextError) as e:
            fn(*args, **kwargs)
        self.assertEqual(e.exception.code, code)

    def manifest(self, **kw):
        rel = cp.save_manifest("author", [{"role": "user", "content": "пароль prompt"}], self.capture, self.st, **kw)
        return json.loads((self.root / rel).read_text(encoding="utf-8"))

    def test_required_never_slices(self):
        self.put("x.json", '{"tail":"important"}')
        self.error("required_component_too_large", self.capture.read, "x.json", 5, True)
        self.assertEqual(self.capture.records[0]["included_characters"], 0)
        self.assertEqual(self.capture.records[0]["omitted_characters"], 20)

    def test_optional_hash_and_omissions(self):
        self.put("тест.txt", "абвгде")
        self.assertIn("4 characters", self.capture.read("тест.txt", 2))
        r = self.capture.records[0]
        self.assertEqual(r["sha256"], hashlib.sha256("абвгде".encode()).hexdigest())
        self.assertEqual((r["included_characters"], r["omitted_characters"]), (2, 4))

    def test_status_keeps_current_and_body_words(self):
        text = "# STATUS\n## Текущее\nИстория внутри текста\n## Аудит\nвсе\n## Предыдущее: старое\nстарое"
        self.put("STATUS.md", text)
        out = self.capture.read("STATUS.md", 100, True, "status_current")
        self.assertIn("## Аудит\nвсе", out)
        self.assertNotIn("## Предыдущее", out)
        self.assertTrue(self.capture.records[0]["omitted_history"])

    def test_status_large_fails_even_optional(self):
        self.put("s", "# S\n## Актуально\n123456789\n## История\nold")
        self.error("current_status_too_large", self.capture.read, "s", 5, False, "status_current")

    def test_secrets_and_outside(self):
        for p in ("temp/a", ".env.test", "docs/credentials.json", "secrets/x", "../outside"):
            self.error("path_denied", self.capture.read, p)

    def test_symlink(self):
        self.put("target", "data")
        try:
            (self.root / "link").symlink_to(self.root / "target")
        except OSError:
            self.skipTest("symlink unavailable")
        self.error("path_denied", self.capture.read, "link")

    def test_manifest_hash_sizes_and_no_prompt(self):
        m = self.manifest()
        messages = [{"role": "user", "content": "пароль prompt"}]
        data = json.dumps(messages, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        self.assertEqual(m["packet_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(m["utf8_bytes"], len(data))
        self.assertEqual(m["characters"], len(messages[0]["content"]))
        self.assertNotIn("пароль prompt", json.dumps(m, ensure_ascii=False))

    def test_rejected_cap_persisted(self):
        self.error("packet_too_large", self.manifest, max_chars=1)
        m = json.loads((self.root / self.st["last_context_manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(m["status"], "rejected")

    def test_rejection_code_no_raise(self):
        m = self.manifest(rejection_code="required_component_too_large")
        self.assertEqual(m["rejection_code"], "required_component_too_large")
        self.assertEqual(m["status"], "rejected")

    def test_done_is_not_acceptance(self):
        h = cp.handoff(self.st)
        self.assertEqual(h["runtime"]["request_outcome"], "blocked")
        self.assertIn("does not imply", h["warning"])
        self.assertFalse(h["permissions"]["new_search_authorized_by_this_packet"])

    def test_policy_and_no_new_authorization(self):
        card = {"spec": {"id": "a", "instruction": "i", "requirements": ["r"], "research_policy": {"max_queries": 3, "answer_attempts": 2}, "budget_usd": .5}}
        self.st["request_sources_attempted"] = 2
        h = cp.handoff(self.st, card)
        self.assertEqual(h["constraints"]["max_queries"], 3)
        self.assertEqual(h["runtime"]["request_sources_attempted"], 2)
        self.assertFalse(h["permissions"]["run_started_by_this_packet"])

    def test_json_restore_and_secrets(self):
        self.st.update(last_error="secret error", needs_human="secret reason", api_key="secret key")
        h = cp.handoff(self.st)
        self.assertEqual(h, cp.handoff(json.loads(json.dumps(self.st))))
        self.assertNotIn("secret", json.dumps(h))

    def test_manifest_write_failure(self):
        self.put("workspace", "file")
        self.error("manifest_write_failed", self.manifest)

    def test_missing_and_invalid(self):
        self.assertIn("missing", self.capture.read("missing"))
        self.error("required_component_missing", self.capture.read, "missing", required=True)
        self.error("invalid_limit", self.capture.read, "missing", limit=True)
        (self.root / "bad").write_bytes(b"\xff")
        self.error("invalid_utf8", self.capture.read, "bad")

    def test_handoff_and_task_bounds(self):
        self.st["tasks"] = [{}] * 101
        self.error("invalid_tasks", cp.handoff, self.st)
        self.st["tasks"] = []
        self.st["task"]["goal"] = "x" * 17000
        self.error("handoff_too_large", cp.handoff, self.st)

    def test_file_size_limit(self):
        (self.root / "huge").write_bytes(b"a" * 2_000_001)
        self.error("file_too_large", self.capture.read, "huge")


if __name__ == "__main__":
    unittest.main()
