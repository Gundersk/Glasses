"""Регрессии ворот: только моки и временные файлы, без моделей и реального STATE."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from autonomy import critic, runner, verify


def task(**kw):
    value = {"id": "T1", "goal": "Проверяемый артефакт", "goal_id": "E2.3",
             "closes": "roadmap:этап2-шаг3", "status": "pending",
             "acceptance": [{"file_exists": "experiments/result.json"}]}
    value.update(kw)
    return value


def goals():
    return {"global": {}, "stage": {"exit_criteria": [
        {"id": "E2.3", "status": "open", "text": "Результат"}]}}


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = self.root / "night_plan.yaml"
        self.approval = self.root / "night_plan.approval.json"
        self.patches = [patch.object(runner, "PLAN_FILE", self.plan),
                        patch.object(runner, "APPROVAL_FILE", self.approval),
                        patch.object(runner.events, "emit"),
                        patch.object(runner.goals_mod, "load", return_value=goals()),
                        patch.object(critic, "write_note"),
                        patch.object(runner, "_read_ctx", return_value="test context")]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.log = Mock()
        self.cfg = {"night": {}, "sandbox": {"denied_command_patterns": ["forbidden"]}}

    def plan_state(self):
        self.plan.write_text(yaml.safe_dump([task()]), encoding="utf-8")
        return {"night_id": "test", "phase": "PLAN", "tasks": [], "task": None}

    def test_invalid_critic_blocks(self):
        rt = Mock()
        rt.call.return_value.text = "not json"
        verdict = critic.review(rt, {}, {}, self.log, tasks=[task()], materials="ctx")
        self.assertEqual(verdict["verdict"], "block")
        self.assertFalse(verdict["raw_ok"])
        self.assertEqual(rt.call.call_count, 2)

    def test_critic_provider_error_blocks(self):
        rt = Mock()
        rt.call.side_effect = RuntimeError("offline")
        self.assertEqual(critic.review(rt, {}, {}, self.log, tasks=[task()],
                                      materials="ctx")["verdict"], "block")

    def test_approve_with_high_is_revise(self):
        v = critic.normalize({"verdict": "approve", "objections": [
            {"issue": "broken", "severity": "high"}]})
        self.assertEqual(v["verdict"], "revise")

    def test_large_plan_not_silently_truncated(self):
        rt = Mock()
        v = critic.review(rt, {}, {}, self.log,
                          tasks=[task(goal="x" * (critic.MAX_PLAN_CHARS + 1))], materials="ctx")
        self.assertEqual(v["verdict"], "block")
        rt.call.assert_not_called()

    def test_revise_exhausted_does_not_execute(self):
        st = self.plan_state()
        rt = Mock()
        rt.call.return_value.text = yaml.safe_dump([task()])
        rt.call.return_value.model = "test-planner"
        v = {"verdict": "revise", "summary": "high unresolved", "raw_ok": True}
        with patch.object(critic, "review", return_value=v):
            runner.phase_plan(self.cfg, st, self.log, rt)
        self.assertEqual(st["phase"], "REPORT")
        self.assertTrue(st["needs_human"])
        self.assertFalse(self.approval.exists())

    def test_valid_approve_allows_execute(self):
        st = self.plan_state()
        with patch.object(critic, "review", return_value={"verdict": "approve", "raw_ok": True}):
            runner.phase_plan(self.cfg, st, self.log, Mock())
        self.assertEqual(st["phase"], "EXECUTE")
        self.assertTrue(runner._approval_ok())

    def test_old_approval_is_invalid(self):
        self.plan_state()
        self.approval.write_text(json.dumps({"verdict": "approve", "sha256": runner._plan_sha256()}))
        self.assertFalse(runner._approval_ok())

    def test_context_change_invalidates_approval(self):
        self.plan_state()
        runner._save_approval({"verdict": "approve", "raw_ok": True}, 1)
        with patch.object(runner, "_approval_context_sha256", return_value="changed"):
            self.assertFalse(runner._approval_ok())

    def test_mock_approval_not_valid_in_real_mode(self):
        st = self.plan_state()
        with patch.object(runner.env, "get", return_value="1"):
            runner.phase_plan(self.cfg, st, self.log, runner.MockRouter(self.cfg, self.log))
            self.assertTrue(runner._approval_ok())
        with patch.object(runner.env, "get", return_value=None):
            self.assertFalse(runner._approval_ok())

    def test_real_approval_not_valid_in_mock_mode(self):
        self.plan_state()
        with patch.object(runner.env, "get", return_value=None):
            runner._save_approval({"verdict": "approve", "raw_ok": True}, 1)
        with patch.object(runner.env, "get", return_value="1"):
            self.assertFalse(runner._approval_ok())

    def test_json_braces_inside_command_string(self):
        obj = {"files": {}, "commands": ['python -c "print(\'}\')"', 'echo {'],
               "summary": "quotes: \\\""}
        for text in (json.dumps(obj), "```json\n" + json.dumps(obj) + "\n```", "explanation\n" + json.dumps(obj)):
            self.assertEqual(runner.extract_json(text), obj)

    def test_recovered_state_needs_approval(self):
        st = {"phase": "EXECUTE", "task": None, "tasks": [task()]}
        rt = Mock()
        runner.phase_execute(self.cfg, st, self.log, rt)
        self.assertEqual(st["phase"], "PLAN")
        rt.call.assert_not_called()

    def test_recovered_later_phases_cannot_bypass_approval(self):
        for phase in ("VERIFY", "REVIEW", "MANAGER"):
            with self.subTest(phase=phase):
                st = {"phase": phase, "task": {"id": "T1", "verify": {"pass": True}},
                      "tasks": [task()]}
                rt = Mock()
                rt.call.return_value.text = '{"verdict": "PASS"}'
                getattr(runner, "phase_" + phase.lower())(self.cfg, st, self.log, rt)
                self.assertEqual(st["phase"], "REPORT")
                self.assertEqual(st["tasks"][0]["status"], "pending")
                rt.call.assert_not_called()

    def test_recovered_inflight_state_stops_without_reexecution(self):
        for phase in ("EXECUTE", "VERIFY", "REVIEW", "MANAGER", "REPAIR"):
            st = {"phase": phase, "task": {"id": "T1"}, "tasks": [task()]}
            runner._guard_recovered_state(st)
            self.assertEqual(st["phase"], "REPORT")
            self.assertIn("незавершённый STATE", st["needs_human"])

    def test_review_without_bound_verdict_not_done(self):
        self.plan_state()
        runner._save_approval({"verdict": "approve", "raw_ok": True}, 1)
        st = {"phase": "REVIEW", "tasks": [task()],
              "task": {"id": "T1", "verify": {"pass": True}}}
        rt = Mock()
        runner.phase_review(self.cfg, st, self.log, rt)
        self.assertEqual(st["phase"], "REPORT")
        self.assertEqual(st["tasks"][0]["status"], "pending")
        rt.call.assert_not_called()

    def test_replan_returns_to_critic(self):
        st = {"phase": "REPAIR", "task": None, "tasks": [], "night_id": "test"}
        rt = Mock()
        rt.call.return_value.text = json.dumps({"action": "replan", "tasks": [task()]})
        runner.phase_repair(self.cfg, st, self.log, rt)
        self.assertEqual(st["phase"], "PLAN")
        self.assertFalse(self.approval.exists())

    def test_unknown_goal_in_replan_blocks(self):
        st = {"phase": "REPAIR", "task": None, "tasks": [], "night_id": "test"}
        rt = Mock()
        rt.call.return_value.text = json.dumps({"action": "replan", "tasks": [task(goal_id="unknown")]})
        runner.phase_repair(self.cfg, st, self.log, rt)
        self.assertEqual(st["phase"], "REPORT")
        self.assertTrue(st["needs_human"])

    def test_empty_acceptance_rejected_twice(self):
        with self.assertRaises(ValueError):
            runner._validate_tasks([task(acceptance=[])], goals())
        self.assertFalse(verify.run_checks(task(acceptance=[]), self.cfg)["pass"])

    def test_duplicate_or_unsafe_id_rejected(self):
        for tasks in ([task(), task()], [task(id="../T1")]):
            with self.assertRaises(ValueError):
                runner._validate_tasks(tasks, goals())

    def test_acceptance_command_policy_applied(self):
        with patch("autonomy.shellutil.run_command") as cmd:
            result = verify.run_checks(task(acceptance=[{"command": "forbidden action"}]), self.cfg)
        self.assertFalse(result["pass"])
        cmd.assert_not_called()

    def test_scope_violation_stops_before_review(self):
        t = task()
        st = {"tasks": [t], "task": {"id": t["id"]}, "violations": [], "history": []}
        result = {"pass": True, "checks": []}
        diff = {"added": [], "modified": ["AGENTS.md"], "deleted": []}
        with patch.object(verify, "run_checks", return_value=result), \
             patch.object(runner, "_require_approval", return_value=True), \
             patch.object(verify, "write_result", return_value=runner.paths.PROJECT_ROOT / "verify.T1.json"), \
             patch.object(runner, "SNAP_FILE", self.root / "missing.json"), \
             patch.object(runner.manifest, "snapshot", return_value={}), \
             patch.object(runner.manifest, "diff", return_value=diff), \
             patch.object(runner.paths, "writable", return_value=False):
            runner.phase_verify(self.cfg, st, self.log, Mock())
        self.assertFalse(st["task"]["verify"]["pass"])
        self.assertEqual(st["phase"], "REPORT")
        self.assertTrue(st["needs_human"])

    def test_pending_rc_not_presented_as_accepted(self):
        root = self.root / "rc"
        (root / "docs").mkdir(parents=True)
        (root / "docs/roadmap-changes.md").write_text(
            "### RC-2026-11-01-01. Accepted\n- **Статус:** принято\nGOOD\n"
            "### RC-2026-11-01-02. Pending\n- **Статус:** ожидает\nBAD\n", encoding="utf-8")
        with patch.object(runner.paths, "PROJECT_ROOT", root):
            result = runner._rc_tail()
        self.assertIn("GOOD", result)
        self.assertNotIn("BAD", result)


if __name__ == "__main__":
    unittest.main()
