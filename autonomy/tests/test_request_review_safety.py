"""Regression for independent review findings, entirely offline/temp files."""
import json
import os
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from autonomy import intake, paths, request_research as rr, runner, state
from autonomy.tests import test_intake as intake_tests


class ReviewSafetyTests(unittest.TestCase):
    setUp = intake_tests.IntakeTests.setUp
    submit = intake_tests.IntakeTests.submit
    answer = intake_tests.IntakeTests.answer

    def enable(self):
        self.spec["research_policy"] = {
            "topics": ["methods"], "min_sources": 2, "min_domains": 1,
            "max_queries": 3, "pages_per_query": 2,
        }

    def test_seed_normalized_before_first_followup(self):
        self.enable()
        self.spec["research_queries"] = ["foo  bar"]
        card = self.submit()
        self.assertEqual(card["spec"]["research_queries"], ["foo bar"])
        rr.propose(card, {"queries": ["new  source"], "reason": "gap"}, "model", "followup")
        self.assertEqual(rr.read_plan(card)["queries"], ["foo bar", "new source"])

    def test_invalid_proposal_not_published(self):
        self.enable()
        card = self.submit()
        for bad in ({"queries": ["bad & shell"], "reason": "gap"},
                    {"queries": ["one", "two", "three"], "reason": "gap"},
                    {"queries": ["new"], "reason": "gap", "budget_usd": 9}):
            with self.assertRaises(ValueError):
                rr.propose(card, bad, "model", "followup")
            self.assertEqual(rr.plan_files(card), [])

    def test_malformed_review_is_not_success(self):
        for raw in (None, [], {"verdict": None, "reason": "x"},
                    {"verdict": "PASS", "reason": None}, {"verdict": "PASS"},
                    {"verdict": "PASS", "reason": "x", "commands": ["evil"]},
                    {"verdict": "SEARCH", "reason": "gap", "research_queries": ["x & evil"]}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                rr.review_output(raw, True)

    def test_search_schema_requires_explicit_authority(self):
        raw = {"verdict": "SEARCH", "reason": "gap", "research_queries": ["new source"]}
        with self.assertRaises(ValueError):
            rr.review_output(raw, False)
        self.assertEqual(rr.review_output(raw, True)["verdict"], "SEARCH")

    def test_pending_before_journal_stops_plan_recovery(self):
        self.enable()
        card = self.submit()
        rr.begin_update(card)
        st = dict(state.default_state(), phase="PLAN")
        with patch.object(runner, "_ACTIVE_REQUEST", card):
            runner._guard_recovered_state(st)
        self.assertEqual(st["phase"], "REPORT")
        self.assertEqual(rr.plan_files(card), [])

    def test_failure_after_journal_does_not_replay_sources(self):
        self.enable()
        card = self.submit()
        rr.begin_update(card)
        rr.propose(card, {"queries": ["new source"], "reason": "gap"}, "model", "followup")
        st = dict(state.default_state(), phase="PLAN", tasks=[{"id": "collect-sources", "status": "done"}])
        with patch.object(runner, "_ACTIVE_REQUEST", card):
            runner._guard_recovered_state(st)
        self.assertEqual(st["phase"], "REPORT")
        self.assertEqual(st["tasks"][0]["status"], "done")

    def test_state_save_failure_keeps_crash_marker(self):
        self.enable()
        card = self.submit()
        rr.begin_update(card)
        with patch.object(state, "save", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                rr.commit_update(card, {})
        self.assertTrue(rr.pending_update(card).exists())

    def test_commit_clears_marker_only_after_state_save(self):
        self.enable()
        card = self.submit()
        rr.begin_update(card)
        with patch.object(state, "save") as save:
            save.side_effect = lambda st: self.assertTrue(rr.pending_update(card).exists())
            rr.commit_update(card, {"phase": "PLAN"})
        self.assertFalse(rr.pending_update(card).exists())

    def test_strict_plan_write_does_not_silence_disk_failure(self):
        with patch.object(runner, "PLAN_FILE", self.root / "missing/plan.yaml"):
            with self.assertRaises(OSError):
                runner._sync_plan({"tasks": []}, strict=True)

    def test_quote_after_24k_in_second_page_is_in_review_bundle(self):
        folder, _ = self.answer()
        card = intake.load(self.spec["id"])
        ev = intake.root(self.spec["id"]) / "sources-0.md.json"
        ev.write_text(json.dumps({"sources": [
            {"url": "https://example.org/other", "content": "prefix" * 5000},
            {"url": "https://example.org/official", "content": "x" * 25000 + " A streaming model. CPU is supported. Tail context."}
        ]}), encoding="utf-8")
        self.assertNotIn("CPU is supported.", ev.read_text(encoding="utf-8")[:24000])
        bundle = json.loads(rr.evidence_bundle(card))
        self.assertEqual(len(bundle), 2)
        self.assertIn("Tail context", bundle[1]["surrounding_context"])

    def test_missing_quote_blocks_semantic_review(self):
        folder, _ = self.answer()
        card = intake.load(self.spec["id"])
        ev = intake.root(self.spec["id"]) / "sources-0.md.json"
        ev.write_text(json.dumps({"sources": [{"url": "https://example.org/official", "content": "not the cited text"}]}))
        with self.assertRaises(ValueError):
            rr.evidence_bundle(card)

    def test_oversized_quote_never_silently_truncated(self):
        folder, claims = self.answer()
        card = intake.load(self.spec["id"])
        claims[0]["quote"] = "x" * 4001
        (folder / "claims.json").write_text(json.dumps(claims))
        with self.assertRaises(ValueError):
            rr.evidence_bundle(card)

    def test_tracking_and_http_not_distinct_publications(self):
        self.assertEqual(rr.canonical_url("https://www.example.org/paper/?utm_source=x#one"),
                         rr.canonical_url("http://example.org/paper"))

    def test_abrupt_process_exit_at_update_boundaries_is_fail_closed(self):
        self.enable()
        real_project = Path(intake.__file__).resolve().parent.parent
        script = r'''
import json, os, sys
from pathlib import Path
from autonomy import paths, intake, runner, request_research as rr, state
paths.PROJECT_ROOT = Path(sys.argv[1])
card = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
paths.WORKSPACE = Path(sys.argv[2]).parent / "run"
paths.WORKSPACE.mkdir()
paths.STATE_FILE = paths.WORKSPACE / "STATE.json"
runner.PLAN_FILE = paths.WORKSPACE / "night_plan.yaml"
st = state.default_state()
st.update(phase="PLAN", tasks=[{"id":"collect-sources", "status":"done"}])
state.save(st)
rr.begin_update(card)
if sys.argv[3] == "marker": os._exit(77)
rr.propose(card, {"queries":["new evidence"], "reason":"gap"}, "synthetic", "followup")
if sys.argv[3] == "version": os._exit(77)
runner._sync_plan(st, strict=True)
if sys.argv[3] == "plan": os._exit(77)
state.save(st)
os._exit(77)  # after real STATE save, before marker removal
'''
        for checkpoint in ("marker", "version", "plan", "state"):
            with self.subTest(checkpoint=checkpoint):
                self.spec["id"] = "MT-2026-11-13-crash-" + checkpoint
                card = self.submit()
                base = intake.root(self.spec["id"])
                result = subprocess.run(
                    [sys.executable, "-c", script, str(self.root), str(base / "request.json"), checkpoint],
                    cwd=real_project, timeout=15, capture_output=True, encoding="utf-8",
                    env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"))
                self.assertEqual(result.returncode, 77, result.stderr)
                self.assertTrue(rr.pending_update(card).exists())
                st = json.loads((base / "run/STATE.json").read_text(encoding="utf-8"))
                with patch.object(runner, "_ACTIVE_REQUEST", card):
                    runner._guard_recovered_state(st)
                self.assertEqual(st["phase"], "REPORT")
                self.assertEqual(st["tasks"], [{"id": "collect-sources", "status": "done"}])
                self.assertFalse(list(base.glob("sources-*")))


if __name__ == "__main__":
    unittest.main()
