"""Протоколы исполнения и отчётность; только временная песочница и synthetic-код."""
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from autonomy import evidence, goals, manifest, report, runner, verify


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.workspace = self.root / "autonomy/workspace"
        self.workspace.mkdir(parents=True)
        for name, val in (("PROJECT_ROOT", self.root), ("WORKSPACE", self.workspace)):
            p = patch.object(evidence.paths, name, val)
            p.start()
            self.addCleanup(p.stop)
        (self.root / "input.txt").write_text("synthetic input", encoding="utf-8")
        self.task = {"id": "T1", "execution": "approved_commands", "seed": 1,
                     "commands": ["synthetic test command"],
                     "inputs": ["input.txt"], "acceptance": [{"file_exists": "output.json"}]}

    def receipt(self, *, fresh=True, rc=0, mock=False):
        directory, rec = evidence.begin(self.task, "sha", mock=mock)
        if fresh:
            (self.root / "output.json").write_text('{"synthetic": true}', encoding="utf-8")
        result = subprocess.CompletedProcess("synthetic", rc, "complete stdout\n", "complete stderr\n")
        evidence.record_command(directory, rec, "synthetic test command", result, time.time_ns())
        return evidence.finish(directory, rec, self.task)

    def test_success_has_full_logs_and_hashes(self):
        rel = self.receipt()
        ok, _ = evidence.validate(rel, self.task, "sha")
        self.assertTrue(ok)
        rec = json.loads(evidence.paths.resolve(rel).read_text(encoding="utf-8"))
        log = evidence.paths.resolve(rec["commands"][0]["stdout"]["path"])
        self.assertEqual(log.read_text(encoding="utf-8"), "complete stdout\n")
        self.assertEqual(len(rec["inputs"][0]["sha256"]), 64)

    def test_old_output_not_evidence(self):
        (self.root / "output.json").write_text("old", encoding="utf-8")
        self.assertFalse(evidence.validate(self.receipt(fresh=False), self.task, "sha")[0])

    def test_failed_command_or_mock_not_measurement(self):
        self.assertFalse(evidence.validate(self.receipt(rc=1), self.task, "sha")[0])
        self.assertFalse(evidence.validate(self.receipt(mock=True), self.task, "sha")[0])

    def test_result_and_input_tampering_rejected(self):
        rel = self.receipt()
        (self.root / "output.json").write_text("changed", encoding="utf-8")
        self.assertFalse(evidence.validate(rel, self.task, "sha")[0])
        rel = self.receipt()
        (self.root / "input.txt").write_text("changed", encoding="utf-8")
        self.assertFalse(evidence.validate(rel, self.task, "sha")[0])

    def test_mismatched_plan_and_missing_receipt_fail(self):
        rel = self.receipt()
        self.assertFalse(evidence.validate(rel, dict(self.task, id="T2"), "sha")[0])
        self.assertFalse(evidence.validate(rel, self.task, "wrong")[0])
        self.assertFalse(evidence.validate(None, self.task, "sha")[0])

    def test_all_file_checks_covered_and_fresh(self):
        for kind, spec in (("number_range", ["metrics.json", "wer", 0, 1]),
                           ("json_eq", ["metrics.json", "ok", True]),
                           ("regex_in_file", ["metrics.json", "wer"])):
            with self.subTest(kind=kind):
                self.task["acceptance"] = [{"file_exists": "output.json"}, {kind: spec}]
                (self.root / "metrics.json").write_text('{"wer": 0.1, "ok": true}')
                self.assertIn("metrics.json", evidence.outputs(self.task))
                self.assertFalse(evidence.validate(self.receipt(), self.task, "sha")[0])

    def test_number_range_only_is_valid_with_fresh_output(self):
        self.task["acceptance"] = [{"number_range": ["output.json", "wer", 0, 1]}]
        self.assertTrue(evidence.validate(self.receipt(), self.task, "sha")[0])

    def test_receipt_cannot_omit_checked_file_or_input(self):
        rel = self.receipt()
        fp = evidence.paths.resolve(rel)
        rec = json.loads(fp.read_text(encoding="utf-8"))
        rec["outputs_after"] = []
        fp.write_text(json.dumps(rec), encoding="utf-8")
        self.assertFalse(evidence.validate(rel, self.task, "sha")[0])
        rel = self.receipt()
        rec = json.loads(evidence.paths.resolve(rel).read_text(encoding="utf-8"))
        rec["inputs"] = []
        evidence.paths.resolve(rel).write_text(json.dumps(rec), encoding="utf-8")
        self.assertFalse(evidence.validate(rel, self.task, "sha")[0])

    def test_incomplete_reordered_or_replaced_commands_fail(self):
        rel = self.receipt()
        for commands in (["synthetic test command", "second"], ["other command"], []):
            with self.subTest(commands=commands):
                self.assertFalse(evidence.validate(rel, dict(self.task, commands=commands), "sha")[0])
        self.task["commands"] = ["first", "second"]
        directory, rec = evidence.begin(self.task, "sha")
        (self.root / "output.json").write_text("fresh")
        for cmd in reversed(self.task["commands"]):
            evidence.record_command(directory, rec, cmd,
                                    subprocess.CompletedProcess(cmd, 0, "", ""), time.time_ns())
        rel = evidence.finish(directory, rec, self.task)
        self.assertFalse(evidence.validate(rel, self.task, "sha")[0])

    def test_secrets_redacted(self):
        with patch.dict(os.environ, {"TEST_API_KEY": "synthetic-test-secret"}):
            value = evidence.redact("synthetic-test-secret Bearer abcdefghijk")
        self.assertNotIn("synthetic-test-secret", value)
        self.assertNotIn("abcdefghijk", value)

    def test_verdicts_versioned_not_overwritten(self):
        a = verify.write_result("T1", {"pass": False})
        b = verify.write_result("T1", {"pass": True})
        self.assertNotEqual(a, b)
        self.assertFalse(json.loads(a.read_text(encoding="utf-8"))["pass"])
        self.assertTrue(json.loads(b.read_text(encoding="utf-8"))["pass"])

    def test_report_does_not_trust_unbound_old_verify(self):
        (self.workspace / "verify.T1.json").write_text('{"pass": true}', encoding="utf-8")
        facts = report.night_facts({"tasks": [{"id": "T1", "status": "pending"}]})
        self.assertIsNone(facts["tasks"][0]["verify_pass"])

    def test_interpretation_disabled_no_llm_call(self):
        rt = Mock()
        result = report.interpret({"night": {"report_interpretation_enabled": False}}, {}, rt, Mock(), {})
        self.assertEqual(result, ("", []))
        rt.call.assert_not_called()

    def test_model_cannot_close_stage_goal_by_file(self):
        g = {"stage": {"exit_criteria": [{"id": "E", "status": "open", "evidence": ["input.txt"]}]}}
        applied, rejected = goals.apply_updates(g, [{"id": "E", "status": "done"}])
        self.assertFalse(applied)
        self.assertTrue(rejected)
        self.assertEqual(goals.target(g, "E")["status"], "open")

    def test_manifest_watches_top_level_contract(self):
        fp = self.root / "AGENTS.md"
        fp.write_text("before", encoding="utf-8")
        cfg = {"sandbox": {"allowed_write_paths": ["experiments/**"]}}
        before = manifest.snapshot(cfg)
        fp.write_text("after", encoding="utf-8")
        self.assertIn("AGENTS.md", manifest.diff(before, manifest.snapshot(cfg))["modified"])

    def test_manifest_ignores_only_workspace_heartbeat_lock(self):
        heartbeat = self.workspace / ".lock"
        other_lock = self.workspace / "nested" / ".lock"
        other_lock.parent.mkdir()
        contract = self.root / "AGENTS.md"
        for fp in (heartbeat, other_lock, contract):
            fp.write_text("before", encoding="utf-8")
        cfg = {"sandbox": {"allowed_write_paths": ["autonomy/workspace/**"]}}
        before = manifest.snapshot(cfg)
        for fp in (heartbeat, other_lock, contract):
            fp.write_text("after", encoding="utf-8")
        after = manifest.snapshot(cfg)
        self.assertNotIn("autonomy/workspace/.lock", before)
        self.assertNotIn("autonomy/workspace/.lock", after)
        self.assertEqual(manifest.diff(before, after), {
            "added": [], "modified": ["AGENTS.md", "autonomy/workspace/nested/.lock"],
            "deleted": [],
        })

    def test_measurement_cannot_be_only_model_written_json(self):
        t = {"id": "T", "goal": "m", "closes": "roadmap:этап2-шаг3", "kind": "measurement",
             "acceptance": [{"file_exists": "output.json"}]}
        with self.assertRaises(ValueError):
            runner._validate_tasks([t])

    def test_approved_commands_execute_without_executor_llm(self):
        # Настоящий короткий subprocess в Temp, но НЕ ASR и НЕ ночной tick.
        t = dict(self.task, status="pending", kind="measurement", max_iter=1,
                 commands=["python -c \"from pathlib import Path; Path('output.json').write_text('synthetic executed', encoding='utf-8')\""])
        st = {"tasks": [t], "task": None, "violations": [], "history": []}
        cfg = {"night": {}, "sandbox": {"allowed_write_paths": ["output.json", "autonomy/workspace/**"],
                                       "denied_command_patterns": []}}
        rt = Mock()
        rt.call.side_effect = AssertionError("executor LLM must not be called")
        with patch.object(runner, "_approval_ok", return_value=True), \
             patch.object(runner, "_plan_sha256", return_value="sha"), \
             patch.object(runner, "_read_ctx", return_value="test context"), \
             patch.object(runner, "SNAP_FILE", self.workspace / "snapshot_before.json"), \
             patch.object(runner.lock, "heartbeat"), \
             patch.object(runner.events, "emit"), \
             patch.object(runner.env, "get", return_value=None):
            runner.phase_execute(cfg, st, Mock(), rt)
            self.assertEqual(st["phase"], "VERIFY")
            runner.phase_verify(cfg, st, Mock(), rt)
        self.assertTrue(st["task"]["verify"]["pass"])
        self.assertTrue(evidence.paths.resolve(st["task"]["verify_file"]).is_file())
        rt.call.assert_not_called()

    def test_timeout_after_success_recorded_and_rejected(self):
        self.task.update(status="pending", commands=["first", "second"], max_iter=1)
        st = {"tasks": [self.task], "task": None, "violations": [], "history": []}
        cfg = {"night": {}, "sandbox": {"allowed_write_paths": ["output.json", "autonomy/workspace/**"],
                                       "denied_command_patterns": []}}

        def run(cmd, *args, **kw):
            if cmd == "first":
                (self.root / "output.json").write_text("fresh")
                return subprocess.CompletedProcess(cmd, 0, "first done", "")
            raise subprocess.TimeoutExpired(cmd, kw["timeout"], output=b"partial stdout", stderr=b"partial stderr")

        with patch.object(runner, "_approval_ok", return_value=True), \
             patch.object(runner, "_plan_sha256", return_value="sha"), \
             patch.object(runner, "_read_ctx", return_value="test context"), \
             patch.object(runner, "SNAP_FILE", self.workspace / "snapshot_before.json"), \
             patch.object(runner.lock, "heartbeat"), \
             patch.object(runner.events, "emit"), \
             patch.object(runner.env, "get", return_value=None), \
             patch("autonomy.shellutil.run_command", side_effect=run):
            runner.phase_execute(cfg, st, Mock(), Mock())
        rel = st["task"]["receipt"]
        rec = json.loads(evidence.paths.resolve(rel).read_text(encoding="utf-8"))
        self.assertEqual(len(rec["commands"]), 2)
        self.assertEqual(rec["commands"][1]["status"], "timeout")
        self.assertEqual(evidence.paths.resolve(rec["commands"][1]["stdout"]["path"]).read_text(),
                         "partial stdout")
        self.assertFalse(evidence.validate(rel, self.task, "sha")[0])
        self.assertNotEqual(st.get("phase"), "VERIFY")

    def test_review_rechecks_bound_verdict_and_artifacts(self):
        self.task.update(status="pending")
        st = {"tasks": [self.task], "task": {"id": "T1"}, "violations": [], "history": []}
        (self.root / "output.json").write_text("fresh")
        with patch.object(runner, "_require_approval", return_value=True), \
             patch.object(runner, "SNAP_FILE", self.workspace / "missing.json"), \
             patch.object(runner.events, "emit"), \
             patch.object(runner.env, "get", return_value=None):
            # Для этой регрессии проверяется привязка; receipt независимо проверен выше.
            self.task.pop("execution")
            runner.phase_verify({"sandbox": {"allowed_write_paths": ["output.json", "autonomy/workspace/**"]}}, st, Mock(), Mock())
            self.assertIsNotNone(runner._verified_result(self.task, st["task"]))
            (self.root / "output.json").write_text("changed after verify")
            rt = Mock()
            runner.phase_review({}, st, Mock(), rt)
        self.assertEqual(st["phase"], "REPORT")
        self.assertEqual(self.task["status"], "pending")
        rt.call.assert_not_called()

    def test_bound_verify_review_manager_happy_path(self):
        # Продолжение в том же процессе, не восстановление STATE и не ночной tick.
        self.task.pop("execution")
        self.task.update(status="pending", goal_id="E")
        st = {"tasks": [self.task], "task": {"id": "T1"}, "violations": [],
              "history": [], "night_id": "synthetic"}
        (self.root / "output.json").write_text("fresh")
        rt = Mock()
        rt.call.return_value.text = '{"verdict": "PASS", "reason": "synthetic evidence accepted"}'
        g = {"stage": {"exit_criteria": [{"id": "E", "status": "open"}]}}
        with patch.object(runner, "_require_approval", return_value=True), \
             patch.object(runner, "SNAP_FILE", self.workspace / "missing.json"), \
             patch.object(runner, "_sync_plan"), \
             patch.object(runner.events, "emit"), \
             patch.object(runner.env, "get", return_value=None), \
             patch.object(runner.goals_mod, "load", return_value=g), \
             patch.object(runner.goals_mod, "save"), \
             patch.object(runner.goals_mod, "record_evidence", return_value=1) as record:
            runner.phase_verify({"sandbox": {"allowed_write_paths": ["output.json", "autonomy/workspace/**"]}}, st, Mock(), rt)
            runner.phase_review({}, st, Mock(), rt)
            self.assertEqual(st["phase"], "MANAGER")
            self.assertEqual(self.task["status"], "done")
            self.assertIsNotNone(runner._verified_result(self.task, self.task))
            rt.call.return_value.text = '{}'
            runner.phase_manager({}, st, Mock(), rt)
        self.assertEqual(st["phase"], "EXECUTE")
        record.assert_called_once()

    def test_changed_versioned_verdict_rejected(self):
        self.task.pop("execution")
        st = {"tasks": [self.task], "task": {"id": "T1"}, "violations": [], "history": []}
        (self.root / "output.json").write_text("fresh")
        with patch.object(runner, "_require_approval", return_value=True), \
             patch.object(runner, "SNAP_FILE", self.workspace / "missing.json"), \
             patch.object(runner.events, "emit"), \
             patch.object(runner.env, "get", return_value=None):
            runner.phase_verify({"sandbox": {"allowed_write_paths": ["output.json", "autonomy/workspace/**"]}}, st, Mock(), Mock())
            fp = evidence.paths.resolve(st["task"]["verify_file"])
            fp.write_text('{"pass": true}', encoding="utf-8")
            self.assertIsNone(runner._verified_result(self.task, st["task"]))


if __name__ == "__main__":
    unittest.main()
