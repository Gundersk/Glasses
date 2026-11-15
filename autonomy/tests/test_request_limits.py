"""Offline checks of shared request budgets; no runner or network."""
import json
import unittest
from unittest.mock import Mock, patch

from autonomy import request_limits as limits, request_research
from autonomy.tests import test_intake


class RequestLimitsTests(unittest.TestCase):
    def setUp(self):
        test_intake.IntakeTests.setUp(self)
        self.card = {"spec": dict(self.spec, time_limit_minutes=15, research_policy={
            "max_queries": 6, "max_plan_revisions": 1, "max_followup_rounds": 1,
            "answer_attempts": 2, "pages_per_query": 2}), "sha256": "fixture"}
        self.st = {}

    def timed(self, lane, elapsed, callback=None):
        with patch.object(limits.time, "monotonic", side_effect=[100, 100 + elapsed]):
            with limits.account(self.card, self.st, lane, callback) as available:
                return available

    def test_revision_counts_initial(self):
        c = limits.snapshot(self.card, self.st)["counts"]["plan_revisions"]
        self.assertEqual(c, {"allowed": 1, "used": 0, "remaining": 1})

    def test_revision_counts_after_revision(self):
        request_research.propose(self.card, {"queries": ["revised query"], "reason": "test"}, "fixture", "plan")
        c = limits.snapshot(self.card, self.st)["counts"]["plan_revisions"]
        self.assertEqual(c, {"allowed": 1, "used": 1, "remaining": 0})

    def test_queries_used_not_planned(self):
        self.card["spec"]["research_queries"] = ["one", "two"]
        self.st["request_sources_attempted"] = 1
        c = limits.snapshot(self.card, self.st)["counts"]["queries"]
        self.assertEqual(c, {"allowed": 6, "used": 1, "remaining": 5, "planned": 2, "unplanned_capacity": 4})
        json.dumps(limits.snapshot(self.card, self.st), allow_nan=False)

    def test_shared_source_clock_followup(self):
        self.assertEqual(self.timed("sources", 200), 600)
        request_research.propose(self.card, {"queries": ["followup"], "reason": "test"}, "fixture", "followup")
        self.assertEqual(self.timed("sources", 100), 400)
        self.assertEqual(limits.remaining(self.card, self.st, "sources"), 300)

    def test_shared_answer_two_attempts(self):
        self.assertEqual(self.timed("answer", 300), 900)
        self.assertEqual(self.timed("answer", 400), 600)
        self.assertEqual(limits.remaining(self.card, self.st, "answer"), 200)

    def test_no_start_at_zero(self):
        self.st["request_work_seconds"] = {"sources": 600}
        with self.assertRaises(limits.TimeBudgetExceeded), limits.account(self.card, self.st, "sources"):
            self.fail("must not start")

    def test_late_result_rejected_and_charged(self):
        with self.assertRaises(limits.TimeBudgetExceeded):
            self.timed("sources", 601)
        self.assertEqual(self.st["request_work_seconds"]["sources"], 601)
        self.assertEqual(limits.remaining(self.card, self.st, "sources"), 0)

    def test_exception_charged_and_saved(self):
        save = Mock()
        with patch.object(limits.time, "monotonic", side_effect=[1, 4]), self.assertRaisesRegex(RuntimeError, "failure"):
            with limits.account(self.card, self.st, "sources", save):
                raise RuntimeError("failure")
        self.assertEqual(self.st["request_work_seconds"]["sources"], 3)
        self.assertEqual(save.call_count, 2)

    def test_wait_excluded_and_deadline_removed(self):
        self.st["subscription_wait_seconds"] = 5
        with patch.object(limits.time, "monotonic", side_effect=[10, 30]), patch.object(limits.time, "time", return_value=100):
            with limits.account(self.card, self.st, "answer"):
                self.assertEqual(self.st["request_model_deadline_ts"], 1000)
                self.st["subscription_wait_seconds"] = 17
        self.assertEqual(self.st["request_work_seconds"]["answer"], 8)
        self.assertNotIn("request_model_deadline_ts", self.st)

    def test_invalid_counters_and_times(self):
        for key, value in (("request_sources_attempted", -1), ("request_sources_attempted", 7),
                           ("request_sources_attempted", True), ("request_answer_attempts", float("nan")),
                           ("request_work_seconds", {"sources": float("nan")}),
                           ("request_work_seconds", {"answer": -1}), ("subscription_wait_seconds", -1)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                limits.snapshot(self.card, {key: value})

    def test_bad_wait_fails_closed_and_charges(self):
        with patch.object(limits.time, "monotonic", side_effect=[0, 10]), self.assertRaises(ValueError):
            with limits.account(self.card, self.st, "sources"):
                self.st["subscription_wait_seconds"] = 11
        self.assertEqual(self.st["request_work_seconds"]["sources"], 10)

    def test_nested_deadline_and_save_failure(self):
        self.st["request_model_deadline_ts"] = 123
        with self.assertRaises(ValueError), limits.account(self.card, self.st, "answer"):
            pass
        self.assertEqual(self.st["request_model_deadline_ts"], 123)
        self.st.clear()
        with self.assertRaises(RuntimeError), limits.account(self.card, self.st, "answer", Mock(side_effect=RuntimeError)):
            pass
        self.assertNotIn("request_model_deadline_ts", self.st)

    def test_policy_required_and_total_bound(self):
        with self.assertRaises(ValueError):
            limits.lane_caps({"spec": {"time_limit_minutes": 15}})
        self.st["request_work_seconds"] = {"sources": 1200, "answer": 200}
        self.assertEqual(limits.remaining(self.card, self.st, "answer"), 100)


if __name__ == "__main__":
    unittest.main()
