from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apply_service import ApplyService
from config import AppConfig


class FakeClient:
    def __init__(self):
        self.created = 0
        self.updated = 0

    def get_work_item_full(self, _wid):
        return {"id": _wid}

    def get_test_plan(self, _pid):
        return {"id": _pid}

    def get_suite_test_cases(self, _pid, _sid):
        return [{"id": 1, "title": "Existing One"}]

    def resolve_effective_suite_configuration_ids(self, _pid, _sid):
        return [7]

    def get_suite_test_cases_test_api(self, _pid, _sid):
        return [{"id": 1, "point_assignments": [{"configuration_id": 7}]}]

    def get_suite_test_points(self, _pid, _sid):
        return [{"id": 10, "test_case_id": 1, "configuration_id": 7}]

    def get_test_case(self, test_case_id):
        return {"id": test_case_id, "rev": 1}

    def update_work_item(self, _id, _patch):
        self.updated += 1
        return {"id": _id, "rev": 2}

    def create_test_case_work_item(self, **kwargs):
        _ = kwargs
        self.created += 1
        return {"id": 50, "rev": 1}

    def add_test_case_to_suite(self, _pid, _sid, _tcid, configuration_ids=None):
        _ = configuration_ids
        return {"count": 1, "value": []}


class ApplyServiceTests(unittest.TestCase):
    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as td:
            r = Path(td)
            review = {
                "review_status": "READY_FOR_QA_APPROVAL",
                "coverage_matrix": [{"req_id": "REQ-1", "coverage_status": "COVERED"}],
                "overmerge_findings": [],
                "decomposition": {"status": "OK"},
                "test_cases": [{"id": "TC-1", "title": "Existing One", "steps": []}],
            }
            recon = {
                "plan_id": 10,
                "suite_id": 20,
                "approved_for_apply": True,
                "reconciliation": [{"classification": "UPDATE_EXISTING", "matched_azure_case_id": 1, "review_test_case_id": "TC-1"}],
            }
            (r / "123_review.json").write_text(json.dumps(review), encoding="utf-8")
            (r / "123_reconciliation.json").write_text(json.dumps(recon), encoding="utf-8")

            cfg = AppConfig("o", "p", "t", "qa", None, 10, r)
            client = FakeClient()
            service = ApplyService(client, cfg)
            out = service.apply(123, dry_run=True)

            self.assertEqual(out.status, "DRY_RUN_OK")
            self.assertEqual(client.created, 0)
            self.assertEqual(client.updated, 0)


if __name__ == "__main__":
    unittest.main()
