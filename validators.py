from __future__ import annotations

from typing import Any


def collect_missing_point_assignments(
    suite_cases_test_api: list[dict[str, Any]],
    expected_test_case_ids: list[int],
    required_config_ids: list[int],
) -> list[int]:
    by_id = {int(item.get("id")): item for item in suite_cases_test_api if str(item.get("id") or "").isdigit()}
    required = set(int(c) for c in required_config_ids)
    missing: list[int] = []
    for tc_id in expected_test_case_ids:
        row = by_id.get(int(tc_id))
        if not row:
            missing.append(int(tc_id))
            continue
        cfgs = {
            int(pa.get("configuration_id"))
            for pa in (row.get("point_assignments") or [])
            if str(pa.get("configuration_id") or "").isdigit()
        }
        if not required.issubset(cfgs):
            missing.append(int(tc_id))
    return sorted(missing)


def validate_execution_readiness(
    membership_ids: list[int],
    suite_cases_test_api: list[dict[str, Any]],
    suite_points: list[dict[str, Any]],
    required_config_ids: list[int],
) -> dict[str, Any]:
    ordered_membership = [int(x) for x in membership_ids]
    expected = sorted(set(ordered_membership))
    missing_assignments = collect_missing_point_assignments(
        suite_cases_test_api=suite_cases_test_api,
        expected_test_case_ids=expected,
        required_config_ids=required_config_ids,
    )
    point_case_ids = {
        int(p.get("test_case_id"))
        for p in suite_points
        if str(p.get("test_case_id") or "").isdigit()
    }
    missing_points = sorted(tc_id for tc_id in expected if tc_id not in point_case_ids)
    counts: dict[int, int] = {}
    for case_id in ordered_membership:
        counts[case_id] = counts.get(case_id, 0) + 1
    duplicate_cases = sorted(case_id for case_id, count in counts.items() if count > 1)

    status = "EXECUTION_READY"
    if missing_assignments or missing_points:
        status = "MEMBERSHIP_OK_POINTS_MISSING"

    return {
        "membership_count": len(expected),
        "point_count": len(suite_points),
        "missing_point_assignment_ids": missing_assignments,
        "missing_point_ids": missing_points,
        "duplicate_cases": duplicate_cases,
        "status": status,
    }


def validate_apply_readiness(review_payload: dict[str, Any], approved_for_apply: bool) -> tuple[bool, str]:
    if not approved_for_apply:
        return False, "approved_for_apply=false"
    status = str(review_payload.get("review_status") or "")
    if status and status != "READY_FOR_QA_APPROVAL":
        return False, f"review_status={status}; expected READY_FOR_QA_APPROVAL"

    matrix = review_payload.get("coverage_matrix") or []
    for entry in matrix:
        if entry.get("coverage_status") not in {"", "COVERED"}:
            return False, f"coverage incomplete for {entry.get('req_id')}"

    overmerge = review_payload.get("overmerge_findings") or []
    if overmerge:
        return False, "OVERMERGED_SCENARIO present"

    decomp = review_payload.get("decomposition") or {}
    if decomp and decomp.get("status") not in {None, "", "OK"}:
        return False, f"decomposition_status={decomp.get('status')}"

    return True, "OK"
