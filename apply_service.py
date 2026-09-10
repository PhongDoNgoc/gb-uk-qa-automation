from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from azure_client import AzureDevOpsClient, AzureDevOpsError
from config import AppConfig
from models import ApplyResult
from validators import validate_apply_readiness, validate_execution_readiness

logger = logging.getLogger(__name__)

PRIORITY_MAP = {"P0": 1, "P1": 2, "P2": 3, "P3": 4}


class ApplyService:
    def __init__(self, client: AzureDevOpsClient, config: AppConfig):
        self.client = client
        self.config = config

    def apply(self, work_item_id: int, dry_run: bool) -> ApplyResult:
        review = self._load_json(self.config.reviews_dir / f"{work_item_id}_review.json")
        rec = self._load_json(self.config.reviews_dir / f"{work_item_id}_reconciliation.json")

        approved = bool(rec.get("approved_for_apply") or review.get("approved_for_apply"))
        apply_ok, apply_reason = validate_apply_readiness(review, approved)
        if not dry_run and not apply_ok:
            return ApplyResult(
                work_item_id=work_item_id,
                plan_id=int(rec.get("plan_id") or 0),
                suite_id=int(rec.get("suite_id") or 0),
                dry_run=dry_run,
                status="APPLY_BLOCKED",
                failures=[{"phase": "apply_readiness", "error": apply_reason}],
            )

        plan_id = int(rec.get("plan_id") or 0)
        suite_id = int(rec.get("suite_id") or 0)
        if plan_id <= 0 or suite_id <= 0:
            return ApplyResult(
                work_item_id=work_item_id,
                plan_id=plan_id,
                suite_id=suite_id,
                dry_run=dry_run,
                status="APPLY_BLOCKED",
                failures=[{"phase": "artifact", "error": "invalid plan_id/suite_id"}],
            )

        live = self._live_refresh(work_item_id, plan_id, suite_id)
        if not live["ok"]:
            return ApplyResult(
                work_item_id=work_item_id,
                plan_id=plan_id,
                suite_id=suite_id,
                dry_run=dry_run,
                status="APPLY_BLOCKED",
                failures=[{"phase": "live_refresh", "error": live["error"]}],
            )

        rows = rec.get("reconciliation") or []
        to_update = [r for r in rows if r.get("classification") == "UPDATE_EXISTING" and r.get("matched_azure_case_id")]
        to_create = [r for r in rows if r.get("classification") == "CREATE_NEW"]

        summary = {
            "workflow": [
                "live_refresh",
                "revision_check",
                "duplicate_check",
                "update_existing",
                "create_new",
                "add_suite_membership",
                "resolve_default_configuration",
                "ensure_point_assignments",
                "verify_membership",
                "verify_points",
                "log_result",
            ],
            "candidates": {"update": len(to_update), "create": len(to_create)},
            "approved_for_apply": approved,
            "apply_readiness": apply_reason,
        }

        if dry_run:
            self._write_log(work_item_id, plan_id, suite_id, {
                "dry_run": True,
                "summary": summary,
                "actions": {
                    "update_existing": [int(r["matched_azure_case_id"]) for r in to_update],
                    "create_new": [str(r.get("review_test_case_id")) for r in to_create],
                },
            })
            return ApplyResult(
                work_item_id=work_item_id,
                plan_id=plan_id,
                suite_id=suite_id,
                dry_run=True,
                status="DRY_RUN_OK",
                summary=summary,
            )

        updated_ids: list[int] = []
        created_ids: list[int] = []
        skipped_ids: list[int] = []
        failures: list[dict[str, Any]] = []

        review_cases = {str(tc.get("id")): tc for tc in (review.get("test_cases") or [])}
        cfg_ids = self.client.resolve_effective_suite_configuration_ids(plan_id, suite_id)
        if not cfg_ids:
            return ApplyResult(work_item_id, plan_id, suite_id, dry_run, "APPLY_BLOCKED", failures=[{"phase": "config", "error": "no effective configuration"}])

        for row in to_update:
            azure_id = int(row["matched_azure_case_id"])
            tc = review_cases.get(str(row.get("review_test_case_id")))
            if not tc:
                failures.append({"phase": "update_existing", "azure_id": azure_id, "error": "missing review case"})
                continue
            try:
                live_tc = self.client.get_test_case(azure_id)
                patch = [
                    {"op": "test", "path": "/rev", "value": int(live_tc.get("rev") or 0)},
                    {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.Steps", "value": self._steps_xml_from_review(tc.get("steps") or [])},
                ]
                self.client.update_work_item(azure_id, patch)
                updated_ids.append(azure_id)
            except AzureDevOpsError as exc:
                failures.append({"phase": "update_existing", "azure_id": azure_id, "error": str(exc), "status_code": exc.status_code})

        existing_now = self.client.get_suite_test_cases(plan_id, suite_id)
        title_index = {self._norm_title(c.get("title") or ""): int(c.get("id")) for c in existing_now if c.get("id") is not None}

        for row in to_create:
            tc = review_cases.get(str(row.get("review_test_case_id")))
            if not tc:
                failures.append({"phase": "create_new", "review_case": row.get("review_test_case_id"), "error": "missing review case"})
                continue

            title = str(tc.get("title") or "").strip()
            norm = self._norm_title(title)
            if norm in title_index:
                skipped_ids.append(title_index[norm])
                continue
            try:
                created = self.client.create_test_case_work_item(
                    title=title,
                    steps_xml=self._steps_xml_from_review(tc.get("steps") or []),
                    description_html=self._description_html(tc.get("preconditions") or []),
                    priority=PRIORITY_MAP.get(str(tc.get("priority") or "P1"), 2),
                    assigned_to=(os.getenv("AZDO_ASSIGNED_TO") or "").strip() or None,
                )
                created_id = int(created.get("id"))
                self.client.add_test_case_to_suite(plan_id, suite_id, created_id, configuration_ids=cfg_ids)
                created_ids.append(created_id)
            except AzureDevOpsError as exc:
                failures.append({"phase": "create_or_link", "review_case": row.get("review_test_case_id"), "error": str(exc), "status_code": exc.status_code})

        suite_cases = self.client.get_suite_test_cases(plan_id, suite_id)
        member_ids = [int(c.get("id")) for c in suite_cases if c.get("id") is not None]
        test_api_cases = self.client.get_suite_test_cases_test_api(plan_id, suite_id)
        points = self.client.get_suite_test_points(plan_id, suite_id)
        readiness = validate_execution_readiness(member_ids, test_api_cases, points, cfg_ids)

        status = "SUCCESS" if readiness["status"] == "EXECUTION_READY" and not failures else readiness["status"]
        if failures and status == "EXECUTION_READY":
            status = "PARTIAL_SUCCESS"

        self._write_log(work_item_id, plan_id, suite_id, {
            "dry_run": False,
            "summary": summary,
            "updated_ids": updated_ids,
            "created_ids": created_ids,
            "skipped_ids": skipped_ids,
            "failures": failures,
            "execution": readiness,
            "status": status,
        })

        return ApplyResult(
            work_item_id=work_item_id,
            plan_id=plan_id,
            suite_id=suite_id,
            dry_run=False,
            status=status,
            summary=summary,
            created_ids=created_ids,
            updated_ids=updated_ids,
            skipped_ids=skipped_ids,
            failures=failures,
        )

    def _live_refresh(self, work_item_id: int, plan_id: int, suite_id: int) -> dict[str, Any]:
        try:
            self.client.get_work_item_full(work_item_id)
            self.client.get_test_plan(plan_id)
            suite_cases = self.client.get_suite_test_cases(plan_id, suite_id)
            if not isinstance(suite_cases, list):
                return {"ok": False, "error": "suite read invalid"}
            return {"ok": True}
        except AzureDevOpsError as exc:
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _norm_title(value: str) -> str:
        return " ".join((value or "").strip().lower().split())

    @staticmethod
    def _description_html(preconditions: list[str]) -> str:
        if not preconditions:
            return ""
        parts = ["<p><b>Preconditions</b></p>", "<ul>"]
        for p in preconditions:
            parts.append(f"<li>{html.escape(str(p))}</li>")
        parts.append("</ul>")
        return "".join(parts)

    @staticmethod
    def _steps_xml_from_review(steps: list[dict[str, Any]]) -> str:
        out = [f'<steps id="0" last="{len(steps)}">']
        for i, step in enumerate(steps, 1):
            action = html.escape(str(step.get("action") or ""))
            expected = html.escape(str(step.get("expected_result") or ""))
            covers = ", ".join(step.get("covers") or [])
            desc = f"&lt;P&gt;Covers: {html.escape(covers)}&lt;/P&gt;" if covers else ""
            out.append(f'<step id="{i}" type="ActionStep">')
            out.append(f'<parameterizedString isformatted="true">&lt;P&gt;{action}&lt;/P&gt;</parameterizedString>')
            out.append(f'<parameterizedString isformatted="true">&lt;P&gt;{expected}&lt;/P&gt;</parameterizedString>')
            out.append(f"<description>{desc}</description>")
            out.append("</step>")
        out.append("</steps>")
        return "".join(out)

    def _write_log(self, work_item_id: int, plan_id: int, suite_id: int, payload: dict[str, Any]) -> Path:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.config.reviews_dir.mkdir(parents=True, exist_ok=True)
        path = self.config.reviews_dir / f"{work_item_id}_apply_{ts}.json"
        body = {
            "generated_at": datetime.now(UTC).isoformat(),
            "work_item_id": work_item_id,
            "plan_id": plan_id,
            "suite_id": suite_id,
            **payload,
        }
        path.write_text(json.dumps(body, indent=2, ensure_ascii=True), encoding="utf-8")
        logger.info("apply log written to %s", path)
        return path

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(str(path))
        return json.loads(path.read_text(encoding="utf-8"))
