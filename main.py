from __future__ import annotations

import argparse
import json
import logging

from azure_client import AzureDevOpsClient, AzureDevOpsError
from apply_service import ApplyService
from config import load_config, setup_logging, validate_required
from reconciliation import reconcile_work_item, run_review, run_sprint_review, set_approval, verify_work_item

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Azure DevOps QA Test Case Generator")
    sub = parser.add_subparsers(dest="command", required=True)

    sprint = sub.add_parser("sprint-review", help="List QA work items and status for a sprint")
    sprint.add_argument("--sprint", required=True, help="Sprint name or iteration path")
    sprint.add_argument("--assigned-to", required=False, help="Assigned-to filter")
    sprint.add_argument("--types", required=False, help="Comma-separated work item types")
    sprint.add_argument("--state", required=False, help="Azure Work Item state filter")
    sprint.add_argument("--status", required=False, help="QA status filter")
    sprint.add_argument("--include-child-tasks", action="store_true", help="Include child tasks")
    sprint.add_argument("--debug", action="store_true", help="Include exclusion diagnostics")
    sprint.add_argument("--json-out", required=False, help="Optional output JSON path")
    sprint.add_argument("--team", required=False, help="Optional Azure team name")

    review = sub.add_parser("review", help="Run canonical requirement review")
    review.add_argument("--work-item", required=True, type=int)
    review.add_argument("--sprint", required=False)

    review_v2 = sub.add_parser("review-v2", help="Deprecated alias to review")
    review_v2.add_argument("--work-item", required=True, type=int)
    review_v2.add_argument("--sprint", required=False)

    review_v3 = sub.add_parser("review-v3", help="Deprecated alias to review")
    review_v3.add_argument("--work-item", required=True, type=int)
    review_v3.add_argument("--sprint", required=False)

    reconcile = sub.add_parser("reconcile", help="Build reconciliation plan from latest review")
    reconcile.add_argument("--work-item", required=True, type=int)

    approve = sub.add_parser("approve", help="Mark review/reconciliation approved for apply")
    approve.add_argument("--work-item", required=True, type=int)

    unapprove = sub.add_parser("unapprove", help="Mark review/reconciliation not approved")
    unapprove.add_argument("--work-item", required=True, type=int)

    apply_cmd = sub.add_parser("apply", help="Apply reconciliation plan")
    apply_cmd.add_argument("--work-item", required=True, type=int)
    apply_cmd.add_argument("--dry-run", action="store_true", help="No Azure writes")

    verify = sub.add_parser("verify", help="Read-only execution readiness verification")
    verify.add_argument("--work-item", required=True, type=int)

    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser


def _print_sprint(payload: dict) -> None:
    print("SPRINT REVIEW")
    print(f"Sprint: {payload.get('sprint')}")
    plan = payload.get("plan") or {}
    print(f"Plan: {plan.get('status')} | ID={plan.get('plan_id')} | Name={plan.get('plan_name')}")
    print("ID | Title | Type | State | Suite | Tests | Comments | QA Status")
    for row in payload.get("work_items") or []:
        print(
            f"{row.get('id')} | {row.get('title')} | {row.get('type')} | {row.get('state')} | "
            f"{row.get('suite_id') or 'N/A'} | {row.get('test_count')} | {row.get('comment_count')} | {row.get('qa_status')}"
        )
    counts = payload.get("counts") or {}
    print("Summary:")
    for key in ["total_in_sprint", "after_assignee", "after_type", "after_parent", "after_state", "after_status"]:
        print(f"  {key}: {counts.get(key)}")


def _run() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    setup_logging(debug=bool(getattr(args, "debug", False)))

    config = load_config()

    missing = validate_required("AZDO_ORG", "AZDO_PROJECT", "AZDO_PAT")
    if missing:
        print("CONFIG: FAIL")
        for name in missing:
            print(f"- {name}")
        return 1

    client = AzureDevOpsClient.from_env()

    try:
        if args.command == "sprint-review":
            payload = run_sprint_review(
                client=client,
                config=config,
                sprint=args.sprint,
                assigned_to=args.assigned_to,
                types=args.types,
                state=args.state,
                status=args.status,
                include_child_tasks=args.include_child_tasks,
                debug=args.debug,
                json_out=args.json_out,
                team=args.team,
            )
            _print_sprint(payload)
            if args.json_out:
                print(f"Summary JSON: {args.json_out}")
            return 0

        if args.command in {"review", "review-v2", "review-v3"}:
            if args.command != "review":
                logger.warning("%s is deprecated; using canonical review pipeline", args.command)
                print(f"DEPRECATED: {args.command} -> review")
            result = run_review(client, config, int(args.work_item), args.sprint)
            payload = result["payload"]
            print("REVIEW COMPLETE")
            print(f"Work Item: {args.work_item}")
            print(f"Review Status: {payload.get('review_status')}")
            print(f"Review Files: {result['json_path']} | {result['txt_path']}")
            return 0

        if args.command == "reconcile":
            result = reconcile_work_item(client, config, int(args.work_item))
            payload = result["payload"]
            print("RECONCILE COMPLETE")
            print(f"Work Item: {args.work_item}")
            print(f"Plan: {payload.get('plan_id')}  Suite: {payload.get('suite_id')}")
            print(f"Counts: {payload.get('classification_counts')}")
            print(f"Artifacts: {result['json_path']} | {result['txt_path']}")
            return 0

        if args.command == "approve":
            result = set_approval(config, int(args.work_item), True)
            print("APPROVAL UPDATED")
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return 0

        if args.command == "unapprove":
            result = set_approval(config, int(args.work_item), False)
            print("APPROVAL UPDATED")
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return 0

        if args.command == "apply":
            service = ApplyService(client, config)
            result = service.apply(work_item_id=int(args.work_item), dry_run=bool(args.dry_run))
            print("APPLY RESULT")
            print(f"Work Item: {result.work_item_id}")
            print(f"Plan: {result.plan_id}  Suite: {result.suite_id}")
            print(f"Dry Run: {result.dry_run}")
            print(f"Status: {result.status}")
            print(f"Created: {len(result.created_ids)} Updated: {len(result.updated_ids)} Skipped: {len(result.skipped_ids)}")
            if result.failures:
                print(f"Failures: {len(result.failures)}")
            return 0 if result.status in {"SUCCESS", "DRY_RUN_OK"} else 1

        if args.command == "verify":
            result = verify_work_item(client, config, int(args.work_item))
            payload = result["payload"]
            print("VERIFY COMPLETE")
            print(f"Work Item: {payload.get('work_item_id')}")
            print(f"Plan: {payload.get('plan_id')}  Suite: {payload.get('suite_id')}")
            print(f"Membership count: {payload.get('membership_count')}")
            print(f"Point count: {payload.get('point_count')}")
            print(f"Missing points: {payload.get('missing_points')}")
            print(f"Duplicate cases: {payload.get('duplicate_cases')}")
            print(f"Execution readiness: {payload.get('execution_readiness')}")
            print(f"Artifact: {result['json_path']}")
            return 0

        parser.print_help()
        return 1

    except (AzureDevOpsError, FileNotFoundError, ValueError) as exc:
        logger.error("Command failed: %s", exc)
        print(f"ERROR: {exc}")
        return 1


def main() -> int:
    return _run()


if __name__ == "__main__":
    raise SystemExit(main())
