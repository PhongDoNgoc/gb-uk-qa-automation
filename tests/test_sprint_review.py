from __future__ import annotations

import unittest
from pathlib import Path

from config import AppConfig
from reconciliation import run_sprint_review


class FakeClient:
    @staticmethod
    def _identity_matches(candidate, _requested_text, requested_identity):
        req_unique = str(requested_identity.get("unique_name") or "").lower()
        cand_unique = str(candidate.get("unique_name") or "").lower()
        if req_unique and cand_unique:
            return req_unique == cand_unique
        req_display = str(requested_identity.get("display_name") or "").lower()
        cand_display = str(candidate.get("display_name") or "").lower()
        return bool(req_display and cand_display and req_display == cand_display)

    def get_iteration_work_items(self, _sprint, team=None):
        _ = team
        return {
            "iteration": {"path": "Project\\Sprint 1"},
            "work_items": [
                {"id": 1, "title": "PBI", "type": "Product Backlog Item", "state": "Active", "assigned_identity": {"unique_name": "qa@example.com"}},
                {"id": 2, "title": "Task child", "type": "Task", "state": "New", "assigned_identity": {"unique_name": "qa@example.com"}},
            ],
        }

    def get_work_item_full(self, wi_id):
        if wi_id == 2:
            return {"relations": [{"rel": "System.LinkTypes.Hierarchy-Reverse", "url": "https://x/_apis/wit/workItems/1"}]}
        return {"relations": []}

    def get_work_item(self, wi_id):
        return {"id": wi_id, "title": "Parent"}

    def discover_test_plan_for_sprint(self, _sprint, _configured):
        return {"status": "FOUND", "plan_id": 10, "plan_name": "Sprint 1"}

    def list_plan_suites(self, _plan_id):
        return [{"id": 100, "suiteType": "requirementTestSuite", "requirementId": 1}]

    def resolve_requirement_suite_from_suites(self, _suites, wi_id):
        if wi_id == 1:
            return {"status": "FOUND", "suite_id": 100, "ambiguity": False, "candidates": []}
        return {"status": "NOT_FOUND", "suite_id": None, "ambiguity": False, "candidates": []}

    def get_suite_test_case_count(self, _plan_id, _suite_id):
        return 3

    def get_work_item_comments(self, _wi_id):
        return []


class SprintReviewTests(unittest.TestCase):
    def _config(self):
        return AppConfig(org="o", project="p", pat="t", qa_assigned_to="qa@example.com", repo_path=None, plan_id=10, reviews_dir=Path("reviews"))

    def test_default_excludes_child_tasks(self):
        payload = run_sprint_review(
            client=FakeClient(),
            config=self._config(),
            sprint="Sprint 1",
            assigned_to="qa@example.com",
            types=None,
            state=None,
            status=None,
            include_child_tasks=False,
            debug=False,
            json_out=None,
            team=None,
        )
        ids = {int(x["id"]) for x in payload["work_items"]}
        self.assertEqual(ids, {1})

    def test_include_child_tasks_flag(self):
        payload = run_sprint_review(
            client=FakeClient(),
            config=self._config(),
            sprint="Sprint 1",
            assigned_to="qa@example.com",
            types=None,
            state=None,
            status=None,
            include_child_tasks=True,
            debug=False,
            json_out=None,
            team=None,
        )
        ids = {int(x["id"]) for x in payload["work_items"]}
        self.assertEqual(ids, {1, 2})


if __name__ == "__main__":
    unittest.main()
