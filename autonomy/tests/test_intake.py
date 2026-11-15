"""Задание ментора: только временные файлы/моки, без сети, моделей и рабочего tick."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from autonomy import intake, research, runner, paths, goals, providers, state


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        p = patch.object(paths, "PROJECT_ROOT", self.root)
        p.start()
        self.addCleanup(p.stop)
        for name in intake.CONTEXT_FILES:
            fp = self.root / name
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text("synthetic project context", encoding="utf-8")
        (self.root / "docs/scope.md").write_text(
            "### Этап 1. Анализ\n| 2 | срок | Сравнить готовые решения | Аналитическая записка PDF |\n"
            "### Этап 2. Прототип\n| 3 | срок | Измерить задержку | Код, видео, таблица |\n", encoding="utf-8")
        self.spec = {"id": "MT-2026-11-13-test", "kind": "research", "closes": "roadmap:этап1-шаг2",
                     "instruction": "Подготовить обзор аналогов на русском CPU без CUDA",
                     "requirements": ["Источники, ограничения, рекомендации"],
                     "research_queries": ["Russian streaming ASR CPU official repository"]}

    def submit(self):
        intake.submit(self.spec)
        return intake.load(self.spec["id"])

    def answer(self):
        card = self.submit()
        base = intake.root(self.spec["id"])
        ev = base / "sources-0.md.json"
        ev.write_text(json.dumps({"sources": [{"url": "https://example.org/official",
                                               "content": "A streaming model. CPU is supported."}]}))
        folder = intake.output_dir(card)
        folder.mkdir(parents=True)
        (folder / "response.md").write_text(
            "C1 C2 https://example.org/official\n" + "Синтетический ответ для проверки структуры. " * 15,
            encoding="utf-8")
        claims = [{"id": "C1", "claim": "model", "status": "supported", "quote": "A streaming model.",
                   "source_url": "https://example.org/official", "evidence_file": intake.rel(ev)},
                  {"id": "C2", "claim": "CPU", "status": "supported", "quote": "CPU is supported.",
                   "source_url": "https://example.org/official", "evidence_file": intake.rel(ev)}]
        (folder / "claims.json").write_text(json.dumps(claims))
        (folder / "decision.json").write_text(json.dumps({"roadmap_change": False, "report_change": True,
            "reason": "Уточнить ограничения в отчёте", "owner_actions": []}))
        return folder, claims

    def test_submit_is_no_run_and_binds_scope(self):
        with patch.object(runner, "tick") as tick:
            card = self.submit()
        tick.assert_not_called()
        self.assertIn("Аналитическая записка PDF", card["scope_quote"])
        self.assertFalse((intake.root(self.spec["id"]) / "run/STATE.json").exists())

    def test_duplicate_id_never_overwrites(self):
        self.submit()
        with self.assertRaises(FileExistsError):
            intake.submit(self.spec)

    def test_bad_scope_closed_lg_and_path_rejected(self):
        for update in ({"closes": "roadmap:этап9-шаг8"}, {"closes": "LG-2026-11-01-01"},
                       {"id": "../bad"}, {"context_files": ["../secret.md"]},
                       {"research_queries": ["x & python bad.py"]}, {"budget_usd": float("nan")}):
            with self.subTest(update=update), self.assertRaises((ValueError, TypeError)):
                intake.validate(dict(self.spec, **update))

    def test_changed_context_and_card_invalidate(self):
        self.submit()
        (self.root / "docs/environment.md").write_text("changed")
        with self.assertRaises(ValueError):
            intake.load(self.spec["id"])
        fp = intake.root(self.spec["id"]) / "request.json"
        card = json.loads(fp.read_text(encoding="utf-8"))
        card["spec"]["instruction"] = "silently changed"
        fp.write_text(json.dumps(card), encoding="utf-8")
        with self.assertRaises(ValueError):
            intake.load(self.spec["id"], require_current=False)

    def test_research_requires_actual_collection_and_dependency(self):
        plan = intake.build_plan(self.submit())
        self.assertEqual(plan[0]["execution"], "approved_commands")
        self.assertIn("--fresh", plan[0]["commands"][0])
        self.assertEqual(plan[1]["depends_on"], [plan[0]["id"]])
        self.assertEqual(plan[1]["execution"], "document_only")
        self.assertTrue(any("claims.json" in c.get("file_exists", "") for c in plan[1]["acceptance"]))

    def test_failed_collection_blocks_answer_without_llm(self):
        card = self.submit()
        tasks = intake.build_plan(card)
        tasks[0]["status"] = "failed"
        st = {"phase": "EXECUTE", "tasks": tasks, "task": None}
        rt = Mock()
        with patch.object(runner, "_ACTIVE_REQUEST", card), patch.object(runner, "_require_approval", return_value=True):
            runner.phase_execute({}, st, Mock(), rt)
        self.assertEqual(st["phase"], "REPORT")
        rt.call.assert_not_called()

    def test_collection_stops_after_first_failed_command(self):
        self.spec['research_queries'] = ['first query', 'second query', 'third query']
        self.submit()
        with intake.runtime(self.spec['id']) as card:
            cfg = runner.load_config()
            task = intake.build_plan(card)[0]
            st = state.default_state()
            st['tasks'] = [task]
            rt = Mock()
            failed = subprocess.CompletedProcess('fixture', 1, '', 'schema error')
            with patch.object(runner, '_require_approval', return_value=True), \
                 patch.object(runner, '_DEADLINE', None), \
                 patch('autonomy.shellutil.run_command', return_value=failed) as run, \
                 patch('autonomy.lock.heartbeat'):
                runner.phase_execute(cfg, st, Mock(), rt)
            self.assertEqual(run.call_count, 1)
            rt.call.assert_not_called()
            self.assertNotEqual(st['phase'], 'VERIFY')
            receipt = json.loads(paths.resolve(st['task']['receipt']).read_text(encoding='utf-8'))
            self.assertEqual(len(receipt['commands']), 1)

    def test_quote_check_not_merely_file_exists(self):
        folder, claims = self.answer()
        self.assertTrue(intake.check_response(self.spec["id"])["pass"])
        claims[0]["quote"] = "Invented quote"
        (folder / "claims.json").write_text(json.dumps(claims))
        with self.assertRaises(ValueError):
            intake.check_response(self.spec["id"])

    def test_change_proposal_requires_trigger_and_no_change(self):
        folder, _ = self.answer()
        (folder / "decision.json").write_text(json.dumps({"roadmap_change": True, "report_change": False,
            "reason": "Предложение", "owner_actions": [], "trigger": "prior_art", "options": ["replace"]}))
        with self.assertRaises(ValueError):
            intake.check_response(self.spec["id"])

    def test_runtime_isolated_and_restored_even_on_error(self):
        self.submit()
        old = (paths.WORKSPACE, paths.STATE_FILE, runner.PLAN_FILE, goals.GOALS_FILE)
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            with intake.runtime(self.spec["id"]):
                self.assertNotEqual(paths.STATE_FILE, old[1])
                self.assertEqual(goals.load()["local_goals"][0]["id"], self.spec["id"])
                raise RuntimeError("synthetic")
        self.assertEqual((paths.WORKSPACE, paths.STATE_FILE, runner.PLAN_FILE, goals.GOALS_FILE), old)
        self.assertIsNone(runner._ACTIVE_REQUEST)

    def test_measurement_is_not_run_from_a_text_request(self):
        self.spec["kind"] = "measurement"
        self.submit()
        with self.assertRaises(ValueError):
            with intake.runtime(self.spec["id"]):
                self.fail("must not start")

    def test_request_repair_does_not_replan(self):
        with patch.object(runner, "_ACTIVE_REQUEST", {"spec": self.spec}):
            st, rt = {"phase": "REPAIR"}, Mock()
            runner.phase_repair({}, st, Mock(), rt)
        self.assertEqual(st["phase"], "REPORT")
        rt.call.assert_not_called()

    def test_research_without_pages_fails_instead_of_success_note(self):
        with patch.object(research, "TinyFish") as tf, \
             patch("yaml.safe_load", return_value={}), \
             patch.object(Path, "read_text", return_value="{}"):
            tf.return_value.search.return_value = {"results": []}
            with self.assertRaises(RuntimeError):
                research.refresh("query", "purpose", out="docs/research/notes/test.md", fresh=True)

    def test_context_note_and_source_tampering_not_accepted(self):
        self.submit()
        (intake.root(self.spec["id"]) / "context.md").write_text("changed")
        with self.assertRaises(ValueError):
            intake.load(self.spec["id"])

    def test_document_executor_cannot_write_sources_or_runtime(self):
        self.submit()
        with intake.runtime(self.spec["id"]) as card:
            task = intake.build_plan(card)[-1]
            task["depends_on"] = []
            st = state.default_state()
            st["tasks"] = [task]
            rt = Mock()
            target = intake.root(self.spec["id"]) / "sources-0.md.json"
            original_source = json.dumps({"sources": [{"url": "https://example.org/source", "content": "Saved original source."}]})
            target.write_text(original_source, encoding="utf-8")
            rt.call.return_value = providers.Result(json.dumps({"files": {intake.rel(target): "invented"},
                "commands": []}), "synthetic", "synthetic", 0, 0, 0, 0)
            with patch.object(runner, "_require_approval", return_value=True), \
                 patch.object(runner, "_DEADLINE", None):
                runner.phase_execute(runner.load_config(), st, Mock(), rt)
            self.assertEqual(target.read_text(encoding="utf-8"), original_source)
            self.assertIn("три файла", st["task"]["errors"][-1])

    def test_full_request_phases_offline_and_isolated(self):
        self.submit()
        original_lock = paths.LOCK_FILE
        command_calls, roles = [], []
        with intake.runtime(self.spec["id"]) as card:
            self.assertEqual(paths.LOCK_FILE, original_lock)  # общий запрет конкуренции
            cfg = runner.load_config()
            cfg["night"]["report_interpretation_enabled"] = False
            folder = intake.output_dir(card)
            ev = intake.root(self.spec["id"]) / "sources-0.md.json"
            claims = [{"id": f"C{i}", "claim": "synthetic claim", "status": "supported",
                       "source_url": "https://example.org/official", "quote": q,
                       "evidence_file": intake.rel(ev)} for i, q in enumerate(
                           ("A streaming model.", "CPU is supported."), 1)]

            def call(role, *args, **kwargs):
                roles.append(role)
                if role == "critic":
                    result = {"verdict": "approve", "summary": "synthetic", "objections": [],
                              "defense_value": [], "needs_search": []}
                elif role == "verifier":
                    result = {"verdict": "PASS", "reason": "synthetic"}
                elif role == "executor":
                    result = {"files": {
                        intake.rel(folder / "response.md"): "C1 C2 https://example.org/official\n" + "Test response. " * 30,
                        intake.rel(folder / "claims.json"): json.dumps(claims),
                        intake.rel(folder / "decision.json"): json.dumps({"roadmap_change": False,
                            "report_change": False, "reason": "synthetic", "owner_actions": []})}, "commands": []}
                else:
                    self.fail("unexpected role: " + role)
                return providers.Result(json.dumps(result), "synthetic", "synthetic", 0, 0, 0, 0)

            def command(cmd, cwd, timeout):
                command_calls.append(cmd)
                if "autonomy.research" in cmd:
                    (ev.parent / "sources-0.md").write_text("Synthetic source", encoding="utf-8")
                    ev.write_text(json.dumps({"sources": [{"url": "https://example.org/official",
                        "content": "A streaming model. CPU is supported."}]}))
                else:
                    self.assertIn("autonomy.intake check", cmd)
                    intake.check_response(self.spec["id"])
                return subprocess.CompletedProcess(cmd, 0, "synthetic offline output", "")

            st, rt = state.default_state(), Mock()
            rt.call.side_effect = call
            st["phase"] = "PLAN"
            with patch("requests.post", side_effect=AssertionError("network forbidden")), \
                 patch("autonomy.shellutil.run_command", side_effect=command), \
                 patch.object(runner, "_DEADLINE", None):
                for _ in range(20):
                    if st["phase"] == "DONE":
                        break
                    phase = st["phase"]
                    getattr(runner, "phase_" + phase.lower())(cfg, st, Mock(), rt)
                    state.save(st)
            self.assertEqual(st["phase"], "DONE")
            self.assertEqual([t["status"] for t in st["tasks"]], ["done", "done"])
            self.assertEqual(roles, ["critic", "verifier", "executor", "verifier"])
            self.assertEqual(len(command_calls), 1)  # Only collection uses a shell; answer check is typed/direct.
            response_checks = st["tasks"][-1]["acceptance"]
            self.assertIn({"mentor_response": self.spec["id"]}, response_checks)
            self.assertNotIn("autonomy.runner tick", (paths.WORKSPACE / "digest.md").read_text(encoding="utf-8"))
            facts = json.loads((paths.OUTBOX_DIR / "facts.json").read_text(encoding="utf-8"))
            self.assertIn(self.spec["id"], facts["plan_file"])
            ev.write_text("tampered")
            self.assertIsNone(runner._verified_result(st["tasks"][0], st["tasks"][0]))
        self.assertFalse((self.root / "autonomy/goals.yaml").exists())
        self.assertFalse((self.root / "autonomy/workspace/STATE.json").exists())


if __name__ == "__main__":
    unittest.main()
