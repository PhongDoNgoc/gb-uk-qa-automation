from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from config import AppConfig
from reconciliation import reconcile_work_item


class FakeClient:
    def list_plan_suites(self, _plan_id):
        return [{"id": 200, "suiteType": "requirementTestSuite", "requirementId": 12345}]

    def resolve_requirement_suite_from_suites(self, _suites, _wid):
        return {"status": "FOUND", "suite_id": 200}

    def get_suite_test_cases(self, _plan_id, _suite_id):
        return [{"id": 3001}, {"id": 3002}]

    def get_test_case(self, tc_id):
        if tc_id == 3001:
            title = "Today: submitted IDC bid data (price and volume per in-horizon SP)"
            steps = '<steps id="0" last="1"><step id="1" type="ActionStep"><parameterizedString>bid price</parameterizedString><parameterizedString>bid volume</parameterizedString></step></steps>'
        else:
            title = "Other"
            steps = '<steps id="0" last="1"><step id="1" type="ActionStep"><parameterizedString>x</parameterizedString><parameterizedString>y</parameterizedString></step></steps>'
        return {"id": tc_id, "rev": 1, "title": title, "state": "Design", "steps": steps}


class ReconciliationTests(unittest.TestCase):
    def test_reconcile_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            reviews = Path(td)
            review_payload = {
                "work_item_id": 12345,
                "plan_status": {"plan_id": 99},
                "approved_for_apply": False,
                "business_scenarios": [{"id": "SCEN-TODAY-BID", "req_ids": ["REQ-1"]}],
                "test_cases": [
                    {
                        "id": "TC-1",
                        "title": "Today: submitted IDC bid data (price and volume per in-horizon SP)",
                        "priority": "P1",
                        "test_type": "Functional",
                        "layer": "End-to-End",
                        "source_requirements": ["REQ-1"],
                        "steps": [{"action": "bid price", "expected_result": "bid volume", "covers": ["REQ-1"]}],
                        "preconditions": [],
                    }
                ],
                "effective_requirements": [{"req_id": "REQ-1"}],
            }
            (reviews / "12345_review.json").write_text(json.dumps(review_payload), encoding="utf-8")

            cfg = AppConfig(org="o", project="p", pat="t", qa_assigned_to="", repo_path=None, plan_id=99, reviews_dir=reviews)
            out = reconcile_work_item(FakeClient(), cfg, 12345)
            self.assertTrue(Path(out["json_path"]).exists())
            payload = out["payload"]
            self.assertEqual(payload["suite_id"], 200)
            self.assertIn("classification_counts", payload)


if __name__ == "__main__":
    unittest.main()
