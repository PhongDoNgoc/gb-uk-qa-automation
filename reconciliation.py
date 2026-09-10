from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, UTC
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from azure_client import AzureDevOpsClient
from config import AppConfig
from validators import validate_execution_readiness

logger = logging.getLogger(__name__)

DEFAULT_TYPES = ["Product Backlog Item", "User Story", "Bug", "Task"]
ALLOWED_QA_STATUSES = {
    "TEST_PLAN_MISSING",
    "TEST_SUITE_MISSING",
    "INITIAL_TEST_DESIGN_REQUIRED",
    "COVERAGE_REVIEW_REQUIRED",
    "REQUIREMENT_CHANGED",
    "READY",
}

EXCLUSION_NOT_ASSIGNED_TO_QA = "NOT_ASSIGNED_TO_QA"
EXCLUSION_TYPE_EXCLUDED = "TYPE_EXCLUDED"
EXCLUSION_CHILD_TASK_EXCLUDED = "CHILD_TASK_EXCLUDED"
EXCLUSION_AZURE_STATE_FILTERED = "AZURE_STATE_FILTERED"
EXCLUSION_QA_STATUS_FILTERED = "QA_STATUS_FILTERED"


def _parse_state_filter(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    values = {v.strip().lower() for v in raw.split(",") if v.strip()}
    return values or None


def _parse_csv_upper(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {v.strip().upper() for v in raw.split(",") if v.strip()}


def _parse_assignee_input(assigned_to: str) -> tuple[str, dict[str, str]]:
    raw = (assigned_to or "").strip()
    identity = {"id": "", "descriptor": "", "unique_name": "", "display_name": ""}
    if "<" in raw and ">" in raw:
        before = raw.split("<", 1)[0].strip()
        inside = raw.split("<", 1)[1].split(">", 1)[0].strip()
        if "@" in inside:
            identity["unique_name"] = inside
        identity["display_name"] = before
        return raw, identity
    if "@" in raw:
        identity["unique_name"] = raw
        return raw, identity
    identity["display_name"] = raw
    return raw, identity


def _extract_parent_id(relations: list[dict[str, Any]]) -> int | None:
    for rel in relations:
        if str(rel.get("rel") or "") != "System.LinkTypes.Hierarchy-Reverse":
            continue
        url = str(rel.get("url") or "")
        m = re.search(r"/workItems/(\d+)", url)
        if m:
            return int(m.group(1))
    return None


def _build_parent_metadata(client: AzureDevOpsClient, work_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    parent_title_cache: dict[int, str] = {}
    for wi in work_items:
        details = client.get_work_item_full(int(wi.get("id") or 0))
        parent_id = _extract_parent_id(details.get("relations") or [])
        item_type = str(wi.get("type") or "")
        is_child_task = bool(parent_id is not None and item_type.strip().lower() == "task")
        parent_title = ""
        if parent_id is not None:
            if parent_id not in parent_title_cache:
                parent = client.get_work_item(parent_id)
                parent_title_cache[parent_id] = str(parent.get("title") or "")
            parent_title = parent_title_cache[parent_id]
        out.append({
            **wi,
            "parent_id": parent_id,
            "parent_title": parent_title,
            "has_parent": parent_id is not None,
            "is_child_task": is_child_task,
        })
    return out


def run_sprint_review(
    client: AzureDevOpsClient,
    config: AppConfig,
    sprint: str,
    assigned_to: str | None,
    types: str | None,
    state: str | None,
    status: str | None,
    include_child_tasks: bool,
    debug: bool,
    json_out: str | None,
    team: str | None,
) -> dict[str, Any]:
    assignee = assigned_to or config.qa_assigned_to
    if not assignee:
        raise ValueError("missing assignee; pass --assigned-to or set AZDO_ASSIGNED_TO")

    selected_types = [x.strip() for x in (types or ",".join(DEFAULT_TYPES)).split(",") if x.strip()]
    type_set = {t.lower() for t in selected_types}
    state_filter = _parse_state_filter(state)
    status_filter = _parse_csv_upper(status)
    invalid = sorted(x for x in status_filter if x not in ALLOWED_QA_STATUSES)
    if invalid:
        raise ValueError(f"invalid --status values: {invalid}")

    assigned_text, assigned_identity = _parse_assignee_input(assignee)
    iteration_data = client.get_iteration_work_items(sprint, team=team)
    all_items = [x for x in (iteration_data.get("work_items") or []) if isinstance(x, dict)]

    after_assignee: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for wi in all_items:
        candidate = wi.get("assigned_identity") or {}
        if not client._identity_matches(candidate, assigned_text, assigned_identity):
            excluded.append({"id": wi.get("id"), "reason": EXCLUSION_NOT_ASSIGNED_TO_QA})
            continue
        after_assignee.append(wi)

    after_type: list[dict[str, Any]] = []
    for wi in after_assignee:
        if str(wi.get("type") or "").strip().lower() in type_set:
            after_type.append(wi)
        else:
            excluded.append({"id": wi.get("id"), "reason": EXCLUSION_TYPE_EXCLUDED})

    with_parent = _build_parent_metadata(client, after_type)

    after_parent = []
    for wi in with_parent:
        if wi.get("is_child_task") and not include_child_tasks:
            excluded.append({"id": wi.get("id"), "reason": EXCLUSION_CHILD_TASK_EXCLUDED})
            continue
        after_parent.append(wi)

    after_state = []
    for wi in after_parent:
        wi_state = str(wi.get("state") or "").strip().lower()
        if state_filter and wi_state not in state_filter:
            excluded.append({"id": wi.get("id"), "reason": EXCLUSION_AZURE_STATE_FILTERED})
            continue
        after_state.append(wi)

    plan_info = client.discover_test_plan_for_sprint(sprint, config.plan_id)
    plan_id = plan_info.get("plan_id")
    suites = client.list_plan_suites(int(plan_id)) if plan_id else []

    rows: list[dict[str, Any]] = []
    for wi in after_state:
        suite_info = {
            "status": "NOT_FOUND",
            "suite_id": None,
            "ambiguity": False,
            "candidates": [],
        }
        case_count = 0
        if plan_id:
            suite_info = client.resolve_requirement_suite_from_suites(suites, int(wi["id"]))
            if suite_info.get("status") in {"FOUND", "AMBIGUOUS"}:
                case_count = client.get_suite_test_case_count(int(plan_id), int(suite_info["suite_id"]))
        comments = client.get_work_item_comments(int(wi["id"]))
        comment_count = len(comments)
        qa_status = (
            "TEST_PLAN_MISSING"
            if plan_info.get("status") != "FOUND"
            else "TEST_SUITE_MISSING"
            if suite_info.get("status") not in {"FOUND", "AMBIGUOUS"}
            else "INITIAL_TEST_DESIGN_REQUIRED"
            if case_count == 0
            else "COVERAGE_REVIEW_REQUIRED"
            if comment_count > 0
            else "READY"
        )
        row = {
            "id": wi.get("id"),
            "title": wi.get("title") or "",
            "type": wi.get("type") or "",
            "state": wi.get("state") or "",
            "parent_id": wi.get("parent_id"),
            "parent_title": wi.get("parent_title") or "",
            "is_child": bool(wi.get("has_parent")),
            "suite_id": suite_info.get("suite_id"),
            "test_count": case_count,
            "comment_count": comment_count,
            "qa_status": qa_status,
        }
        if status_filter and qa_status not in status_filter:
            excluded.append({"id": wi.get("id"), "reason": EXCLUSION_QA_STATUS_FILTERED})
            continue
        rows.append(row)

    payload = {
        "sprint": sprint,
        "assigned_to": assignee,
        "plan": plan_info,
        "counts": {
            "total_in_sprint": len(all_items),
            "after_assignee": len(after_assignee),
            "after_type": len(after_type),
            "after_parent": len(after_parent),
            "after_state": len(after_state),
            "after_status": len(rows),
        },
        "work_items": rows,
        "excluded": excluded if debug else [],
        "generated_at": datetime.now(UTC).isoformat(),
    }

    if json_out:
        out_path = Path(json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    return payload


def run_review(
    client: AzureDevOpsClient,
    config: AppConfig,
    work_item_id: int,
    sprint_override: str | None = None,
) -> dict[str, Any]:
    from pipeline import run_review_v3

    wi = client.get_work_item_full(work_item_id)
    comments = client.get_work_item_comments(work_item_id)
    review = run_review_v3(wi, comments, work_item_id)

    sprint_name = sprint_override or str(wi.get("iteration_path") or "").split("\\")[-1]
    plan_info = client.discover_test_plan_for_sprint(sprint_name, config.plan_id)
    suite_info = {"status": "NOT_FOUND", "suite_id": None}
    if plan_info.get("status") == "FOUND" and plan_info.get("plan_id"):
        suites = client.list_plan_suites(int(plan_info["plan_id"]))
        suite_info = client.resolve_requirement_suite_from_suites(suites, work_item_id)

    review["generated_at"] = datetime.now(UTC).isoformat()
    review["plan_status"] = plan_info
    review["suite_status"] = suite_info
    review["approved_for_apply"] = bool(review.get("approved_for_apply", False))

    config.reviews_dir.mkdir(parents=True, exist_ok=True)
    json_path = config.reviews_dir / f"{work_item_id}_review.json"
    txt_path = config.reviews_dir / f"{work_item_id}_review.txt"
    json_path.write_text(json.dumps(review, indent=2, ensure_ascii=True), encoding="utf-8")
    txt_path.write_text(_render_review_txt(review), encoding="utf-8")
    return {"payload": review, "json_path": str(json_path), "txt_path": str(txt_path)}


def _render_review_txt(review: dict[str, Any]) -> str:
    c = review.get("counts") or {}
    lines = [
        f"REVIEW - Work Item {review.get('work_item_id')}",
        "",
        f"Review Status: {review.get('review_status')}",
    ]
    for reason in review.get("review_status_reasons") or []:
        lines.append(f"- {reason}")
    lines.extend([
        "",
        "Counts:",
        f"- atomic_statements: {c.get('atomic_statements', 0)}",
        f"- effective_requirements: {c.get('effective_requirements', 0)}",
        f"- business_scenarios: {c.get('business_scenarios', 0)}",
        f"- test_cases: {c.get('test_cases', 0)}",
        f"- covered_reqs: {c.get('covered_reqs', 0)}",
        f"- partial_reqs: {c.get('partial_reqs', 0)}",
        f"- uncovered_reqs: {c.get('uncovered_reqs', 0)}",
    ])
    lines.append("")
    lines.append("Test Cases:")
    for tc in review.get("test_cases") or []:
        lines.append(f"- {tc.get('id')} | {tc.get('title')}")
        for idx, step in enumerate(tc.get("steps") or [], 1):
            action = html.unescape(step.get("action") or "")
            expected = html.unescape(step.get("expected_result") or "")
            lines.append(f"  Step {idx} Action: {action}")
            lines.append(f"  Step {idx} Expected: {expected}")
    return "\n".join(lines)


def _parse_steps_xml(steps_xml: str | None) -> list[dict[str, str]]:
    if not steps_xml:
        return []
    try:
        root = ElementTree.fromstring(steps_xml)
    except ElementTree.ParseError:
        return []
    out: list[dict[str, str]] = []
    for step in root.findall(".//step"):
        nodes = step.findall("parameterizedString")
        action = "".join(nodes[0].itertext()).strip() if len(nodes) > 0 else ""
        expected = "".join(nodes[1].itertext()).strip() if len(nodes) > 1 else ""
        out.append({"action": _norm_text(action), "expected": _norm_text(expected)})
    return out


def _norm_text(value: str) -> str:
    t = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", t).strip().lower()


SCENARIO_SIGNATURES: dict[str, dict[str, list[str]]] = {
    "SCEN-TODAY-BID": {
        "title_keywords": ["bid prices and volumes", "bid data", "submitted idc bid", "recommended bid"],
        "step_keywords": ["bid price", "bid volume"],
    },
    "SCEN-TODAY-OFFER": {
        "title_keywords": ["offer prices and volumes", "offer data", "submitted idc offer", "recommended offer"],
        "step_keywords": ["offer price", "offer volume"],
    },
    "SCEN-TODAY-BID-STATUS": {
        "title_keywords": ["submission status", "status of idc", "status of the submitted"],
        "step_keywords": ["submission status", "displayed status"],
    },
    "SCEN-TODAY-OFFER-STATUS": {
        "title_keywords": ["submission status", "status of idc", "status of the submitted"],
        "step_keywords": ["submission status", "displayed status"],
    },
    "SCEN-HORIZON": {
        "title_keywords": ["2-hour horizon", "upcoming 2-hour", "in-horizon"],
        "step_keywords": ["2-hour horizon", "horizon", "in-horizon"],
    },
    "SCEN-UI-REVIEW": {
        "title_keywords": ["wording, naming", "graph colour", "updated ui design", "ui design"],
        "step_keywords": ["wording", "naming", "colour"],
    },
    "SCEN-PAST-DATE": {
        "title_keywords": ["past delivery date", "historical", "past date"],
        "step_keywords": ["past delivery", "past date", "historical"],
    },
    "SCEN-TABLE-ROW": {
        "title_keywords": ["table row", "table details", "pn initial", "start time of the sp"],
        "step_keywords": ["start time", "pn initial", "table"],
    },
    "SCEN-GATE-CLOSURE": {
        "title_keywords": ["gate closure", "bmu"],
        "step_keywords": ["gate closure", "bmu", "1 hour before", "15 minutes"],
    },
    "SCEN-GRAPH-STATES": {
        "title_keywords": ["graph submission", "sent-to-volue", "submitted-to-epex"],
        "step_keywords": ["sent to volue", "submitted to epex", "graph mw", "real-time"],
    },
    "SCEN-STATUS-POLLING": {
        "title_keywords": ["status refresh", "every 1 minute", "every minute"],
        "step_keywords": ["every minute", "1 minute", "refresh"],
    },
    "SCEN-SEND-CADENCE": {
        "title_keywords": ["cadence", "24/7", "every 5 minutes"],
        "step_keywords": ["24/7", "every 5 min"],
    },
    "SCEN-HISTORICAL-RANGE": {
        "title_keywords": ["historical date-range", "historical range", "date range"],
        "step_keywords": ["date range", "historical"],
    },
    "SCEN-TODAY-DEFAULT": {
        "title_keywords": ["defaults to today", "today default", "today's date"],
        "step_keywords": ["defaults to today", "today's date"],
    },
    "SCEN-PRIMARY-FLOW": {"title_keywords": ["primary submission viewing flow", "primary flow"], "step_keywords": []},
    "SCEN-OTHER": {"title_keywords": [], "step_keywords": []},
}


def _score_match(scenario_id: str, existing: dict[str, Any], steps: list[dict[str, str]]) -> int:
    sig = SCENARIO_SIGNATURES.get(scenario_id, {"title_keywords": [], "step_keywords": []})
    title = (existing.get("title") or "").lower()
    step_text = " | ".join((s.get("action", "") + " " + s.get("expected", "")).lower() for s in steps)
    score = 0
    for kw in sig["title_keywords"]:
        if kw in title:
            score += 3
    for kw in sig["step_keywords"]:
        if kw in step_text:
            score += 1
    return score


def _scenario_id_of(review_case: dict[str, Any], scenarios: dict[str, dict[str, Any]]) -> str:
    reqs = set(review_case.get("source_requirements") or [])
    for sid, scenario in scenarios.items():
        if set(scenario.get("req_ids") or []) == reqs:
            return sid
    return "SCEN-UNKNOWN"


def _find_review_path(reviews_dir: Path, work_item_id: int) -> Path:
    canonical = reviews_dir / f"{work_item_id}_review.json"
    if canonical.exists():
        return canonical
    for candidate in [reviews_dir / f"{work_item_id}_review_v3.json", reviews_dir / f"{work_item_id}_review_v2.json"]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No review artifact for work item {work_item_id}")


def reconcile_work_item(client: AzureDevOpsClient, config: AppConfig, work_item_id: int) -> dict[str, Any]:
    review_path = _find_review_path(config.reviews_dir, work_item_id)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    plan_info = review.get("plan_status") or {}

    plan_id = int(plan_info.get("plan_id") or config.plan_id or 0)
    if plan_id <= 0:
        raise ValueError("missing plan id for reconcile")

    suites = client.list_plan_suites(plan_id)
    suite_info = client.resolve_requirement_suite_from_suites(suites, work_item_id)
    if suite_info.get("status") not in {"FOUND", "AMBIGUOUS"}:
        raise ValueError(f"no requirement suite for {work_item_id}")
    suite_id = int(suite_info.get("suite_id"))

    cases = review.get("test_cases") or []
    scenarios = {s["id"]: s for s in (review.get("business_scenarios") or []) if isinstance(s, dict) and s.get("id")}

    suite_cases = client.get_suite_test_cases(plan_id, suite_id)
    existing_ids = sorted(int(c.get("id")) for c in suite_cases if c.get("id") is not None)

    existing_snapshot: list[dict[str, Any]] = []
    for tc_id in existing_ids:
        tc = client.get_test_case(tc_id)
        existing_snapshot.append({
            "id": tc.get("id"),
            "rev": tc.get("rev"),
            "title": tc.get("title"),
            "state": tc.get("state"),
            "steps": _parse_steps_xml(tc.get("steps")),
        })

    reconciliation: list[dict[str, Any]] = []
    used_existing: set[int] = set()

    for case in cases:
        sid = _scenario_id_of(case, scenarios)
        best_id: int | None = None
        best_score = 0
        for existing in existing_snapshot:
            score = _score_match(sid, existing, existing.get("steps") or [])
            if score > best_score:
                best_score = score
                best_id = int(existing["id"])
        matched = next((e for e in existing_snapshot if int(e["id"]) == int(best_id)) , None) if best_id is not None else None
        if best_score < 3:
            matched = None

        if matched is None:
            classification = "CREATE_NEW"
            note = "No equivalent Azure case for this scenario"
        elif int(matched["id"]) in used_existing:
            classification = "SKIP_DUPLICATE"
            note = f"Coverage merges into update for Azure case {matched['id']}"
        else:
            classification = "UPDATE_EXISTING"
            note = "Equivalent scenario exists but should be updated to match current review"
            used_existing.add(int(matched["id"]))

        reconciliation.append({
            "review_test_case_id": case.get("id"),
            "title": case.get("title"),
            "scenario_id": sid,
            "priority": case.get("priority"),
            "test_type": case.get("test_type"),
            "layer": case.get("layer"),
            "req_ids": case.get("source_requirements") or [],
            "matched_azure_case_id": matched.get("id") if matched else None,
            "matched_azure_title": matched.get("title") if matched else None,
            "match_score": best_score if matched else 0,
            "classification": classification,
            "note": note,
            "current_azure_steps": matched.get("steps") if matched else None,
            "required_steps_review": case.get("steps") or [],
            "preconditions_review": case.get("preconditions") or [],
        })

    counts = {"KEEP_EXISTING": 0, "UPDATE_EXISTING": 0, "CREATE_NEW": 0, "SKIP_DUPLICATE": 0, "CONFLICT": 0}
    for row in reconciliation:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1

    req_total = len(review.get("effective_requirements") or [])
    req_after: set[str] = set()
    for row in reconciliation:
        if row["classification"] in {"KEEP_EXISTING", "UPDATE_EXISTING", "CREATE_NEW", "SKIP_DUPLICATE"}:
            req_after.update(row.get("req_ids") or [])

    out = {
        "generated_at": datetime.now(UTC).isoformat(),
        "target_work_item": work_item_id,
        "plan_id": plan_id,
        "suite_id": suite_id,
        "approved_for_apply": bool(review.get("approved_for_apply", False)),
        "source_review_artifact": review_path.name,
        "existing_azure_case_ids": existing_ids,
        "classification_counts": counts,
        "reconciliation": reconciliation,
        "coverage_projection": {
            "total_review_reqs": req_total,
            "covered_after_apply": len(req_after),
            "remaining_uncovered": max(0, req_total - len(req_after)),
        },
    }

    config.reviews_dir.mkdir(parents=True, exist_ok=True)
    out_json = config.reviews_dir / f"{work_item_id}_reconciliation.json"
    out_txt = config.reviews_dir / f"{work_item_id}_reconciliation.txt"
    out_json.write_text(json.dumps(out, indent=2, ensure_ascii=True), encoding="utf-8")
    lines = [
        f"RECONCILIATION - Work Item {work_item_id}",
        f"Plan: {plan_id}",
        f"Suite: {suite_id}",
        f"Counts: {counts}",
        "",
        "Mapping:",
        "review_case_id | classification | azure_case_id | score | title",
    ]
    for row in reconciliation:
        lines.append(
            f"{row.get('review_test_case_id')} | {row.get('classification')} | {row.get('matched_azure_case_id') or '-'} | "
            f"{row.get('match_score')} | {str(row.get('title') or '')[:90]}"
        )
    out_txt.write_text("\n".join(lines), encoding="utf-8")

    return {"payload": out, "json_path": str(out_json), "txt_path": str(out_txt)}


def set_approval(config: AppConfig, work_item_id: int, approved: bool) -> dict[str, Any]:
    updates: list[str] = []
    for suffix in ["review.json", "reconciliation.json"]:
        path = config.reviews_dir / f"{work_item_id}_{suffix}"
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["approved_for_apply"] = approved
        payload["approval_updated_at"] = datetime.now(UTC).isoformat()
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        updates.append(path.name)
    return {"work_item_id": work_item_id, "approved_for_apply": approved, "updated_files": updates}


def verify_work_item(client: AzureDevOpsClient, config: AppConfig, work_item_id: int) -> dict[str, Any]:
    path = config.reviews_dir / f"{work_item_id}_reconciliation.json"
    if not path.exists():
        raise FileNotFoundError(f"missing reconciliation artifact: {path}")
    rec = json.loads(path.read_text(encoding="utf-8"))
    plan_id = int(rec.get("plan_id") or 0)
    suite_id = int(rec.get("suite_id") or 0)
    if plan_id <= 0 or suite_id <= 0:
        raise ValueError("invalid plan_id/suite_id in reconciliation artifact")

    suite_cases = client.get_suite_test_cases(plan_id, suite_id)
    suite_ids = [int(c.get("id")) for c in suite_cases if c.get("id") is not None]
    test_api_cases = client.get_suite_test_cases_test_api(plan_id, suite_id)
    points = client.get_suite_test_points(plan_id, suite_id)
    cfg_ids = client.resolve_effective_suite_configuration_ids(plan_id, suite_id)

    readiness = validate_execution_readiness(
        membership_ids=suite_ids,
        suite_cases_test_api=test_api_cases,
        suite_points=points,
        required_config_ids=cfg_ids,
    )

    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "work_item_id": work_item_id,
        "plan_id": plan_id,
        "suite_id": suite_id,
        "membership_count": readiness["membership_count"],
        "point_count": readiness["point_count"],
        "missing_points": readiness["missing_point_ids"],
        "missing_point_assignments": readiness["missing_point_assignment_ids"],
        "duplicate_cases": readiness["duplicate_cases"],
        "execution_readiness": readiness["status"],
    }
    out = config.reviews_dir / f"{work_item_id}_verify.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    return {"payload": result, "json_path": str(out)}
