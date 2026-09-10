from __future__ import annotations

import unittest

from pipeline import run_review_v3


FIXTURE_WORK_ITEM = {
    "id": 999,
    "title": "Sample requirement",
    "description": "<div><b>Primary Flow</b></div><ul><li>User opens screen</li><li>System shows data</li></ul>",
    "acceptance_criteria": "<div><b>If viewing submitted recommendations based on today's delivery date</b></div><ul><li>View bid prices and volumes</li></ul>",
    "business_rules": None,
}

FIXTURE_COMMENTS = [
    {"id": 1, "createdDate": "2026-01-01T00:00:00Z", "text": "<div>UI wording update requested</div>"}
]


class PipelineTests(unittest.TestCase):
    def test_review_v3_returns_counts(self):
        out = run_review_v3(FIXTURE_WORK_ITEM, FIXTURE_COMMENTS, 999)
        self.assertIn("counts", out)
        self.assertGreater(out["counts"]["atomic_statements"], 0)

    def test_review_v3_generates_test_cases(self):
        out = run_review_v3(FIXTURE_WORK_ITEM, FIXTURE_COMMENTS, 999)
        self.assertGreater(len(out.get("test_cases") or []), 0)

    def test_review_v3_has_coverage_matrix(self):
        out = run_review_v3(FIXTURE_WORK_ITEM, FIXTURE_COMMENTS, 999)
        self.assertIn("coverage_matrix", out)


if __name__ == "__main__":
    unittest.main()
