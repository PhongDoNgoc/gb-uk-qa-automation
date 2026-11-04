from __future__ import annotations

import base64
import logging
import os
import platform
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from azure_client import AzureDevOpsError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TestAttachment:
    path: Path
    comment: str


@dataclass
class TestExecution:
    outcome: str
    started_date: str
    completed_date: str
    duration_in_ms: float
    error_message: str = ""
    stack_trace: str = ""
    attachments: list[TestAttachment] = field(default_factory=list)


TestCaseExecutor = Callable[..., TestExecution]


def run_test_plan(
    *,
    client: Any,
    plan_id: int,
    suite_id: int,
    configuration_id: int,
    test_project: str,
    build_configuration: str,
    results_directory: str,
    execute_case: TestCaseExecutor | None = None,
) -> dict[str, Any]:
    project_path = Path(test_project).resolve()
    if not project_path.is_file():
        raise FileNotFoundError(f"Test project was not found: {project_path}")

    cases, skipped_points = _select_automated_cases(
        client=client,
        plan_id=plan_id,
        suite_id=suite_id,
        configuration_id=configuration_id,
    )
    print(
        f"Selected {len(cases)} automated test case(s) for plan {plan_id}, suite {suite_id}, "
        f"configuration {configuration_id}; {skipped_points} non-automated test point(s) skipped.",
        flush=True,
    )
    point_ids = [int(point["id"]) for case in cases for point in case["points"]]
    results_path = Path(results_directory).resolve()
    results_path.mkdir(parents=True, exist_ok=True)

    build_number = os.getenv("BUILD_BUILDNUMBER", "").strip()
    target_environment = os.getenv("TEST_TARGET_ENV", "").strip().upper() or "UNSPECIFIED"
    run_name = f"Automated {target_environment} Test Plan {plan_id} Suite {suite_id}"
    if build_number:
        run_name = f"{run_name} - Build {build_number}"

    run = client.create_test_run(
        plan_id=plan_id,
        point_ids=point_ids,
        configuration_ids=[configuration_id],
        name=run_name,
        comment=f"Executed by Azure Pipelines build {build_number or 'unknown'}.",
    )
    try:
        run_id = int(run.get("id"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise AzureDevOpsError("Azure DevOps did not return a valid test run ID.") from exc

    executor = execute_case or execute_test_case
    executions: dict[int, TestExecution] = {}
    try:
        for case in cases:
            test_case_id = int(case["test_case_id"])
            print(f"Running Test Case {test_case_id}: {case['title']}", flush=True)
            executions[test_case_id] = executor(
                case,
                test_project=project_path,
                build_configuration=build_configuration,
                results_directory=results_path,
            )
            execution = executions[test_case_id]
            print(
                f"Test Case {test_case_id}: {execution.outcome}"
                + (f" - {execution.error_message}" if execution.error_message else ""),
                flush=True,
            )

        result_ids = _publish_results(
            client=client,
            run_id=run_id,
            plan_id=plan_id,
            suite_id=suite_id,
            configuration_id=configuration_id,
            cases=cases,
            executions=executions,
        )
        _publish_attachments(
            client=client,
            run_id=run_id,
            cases=cases,
            executions=executions,
            result_ids=result_ids,
        )
    except Exception as exc:
        try:
            client.complete_test_run(run_id, error_message=str(exc))
        except AzureDevOpsError as completion_error:
            raise AzureDevOpsError(
                f"Test run {run_id} failed and could not be completed: {completion_error}"
            ) from exc
        raise
    else:
        client.complete_test_run(run_id)

    failed_cases = [
        test_case_id
        for test_case_id, execution in executions.items()
        if execution.outcome != "Passed"
    ]
    passed_cases = len(executions) - len(failed_cases)
    print(
        f"Azure Test Plan run {run_id} completed: "
        f"{passed_cases} passed, {len(failed_cases)} failed, "
        f"{skipped_points} non-automated test point(s) skipped.",
        flush=True,
    )
    return {
        "run_id": run_id,
        "selected_case_count": len(cases),
        "selected_point_count": len(point_ids),
        "passed_case_count": passed_cases,
        "failed_case_count": len(failed_cases),
        "failed_test_case_ids": failed_cases,
        "skipped_point_count": skipped_points,
    }


def _select_automated_cases(
    *,
    client: Any,
    plan_id: int,
    suite_id: int,
    configuration_id: int,
) -> tuple[list[dict[str, Any]], int]:
    points = client.get_suite_test_points(plan_id, suite_id)
    selected_points = [
        point
        for point in points
        if point.get("configuration_id") == int(configuration_id)
    ]
    if not selected_points:
        raise ValueError(
            f"No test points were found for plan {plan_id}, suite {suite_id}, "
            f"configuration {configuration_id}."
        )

    case_details: dict[int, dict[str, Any]] = {}
    cases_by_id: dict[int, dict[str, Any]] = {}
    skipped_points = 0
    seen_point_ids: set[int] = set()
    for point in selected_points:
        point_id = point.get("id")
        test_case_id = point.get("test_case_id")
        if not isinstance(point_id, int) or not isinstance(test_case_id, int):
            raise AzureDevOpsError("Azure DevOps returned a test point without a valid point or test case ID.")
        if point_id in seen_point_ids:
            continue
        seen_point_ids.add(point_id)

        if test_case_id not in case_details:
            case_details[test_case_id] = client.get_test_case(test_case_id)
        details = case_details[test_case_id]
        if str(details.get("automation_status") or "").strip().casefold() != "automated":
            skipped_points += 1
            continue

        fully_qualified_name = str(details.get("automated_test_name") or "").strip()
        storage = str(details.get("automated_test_storage") or "").strip()
        if not fully_qualified_name or not storage:
            raise AzureDevOpsError(
                f"Test Case {test_case_id} is marked Automated but has no associated test name or storage."
            )

        case = cases_by_id.get(test_case_id)
        if case is None:
            case = {
                "test_case_id": test_case_id,
                "title": str(details.get("title") or f"Test Case {test_case_id}"),
                "fully_qualified_name": fully_qualified_name,
                "automated_test_storage": storage,
                "automated_test_type": str(details.get("automated_test_type") or "NUnit").strip(),
                "priority": details.get("priority"),
                "points": [],
            }
            cases_by_id[test_case_id] = case
        elif (
            case["fully_qualified_name"] != fully_qualified_name
            or case["automated_test_storage"] != storage
        ):
            raise AzureDevOpsError(
                f"Test Case {test_case_id} has conflicting automated test associations."
            )
        case["points"].append(point)

    cases = list(cases_by_id.values())
    if not cases:
        raise ValueError(
            f"No automated test points were found for plan {plan_id}, suite {suite_id}, "
            f"configuration {configuration_id}."
        )
    return cases, skipped_points


def execute_test_case(
    case: dict[str, Any],
    *,
    test_project: Path,
    build_configuration: str,
    results_directory: Path,
) -> TestExecution:
    test_case_id = int(case["test_case_id"])
    case_results = results_directory / f"case-{test_case_id}"
    case_results.mkdir(parents=True, exist_ok=True)
    trx_name = f"test-case-{test_case_id}.trx"
    command = [
        "dotnet",
        "test",
        str(test_project),
        "--no-build",
        "--configuration",
        build_configuration,
        "--filter",
        f"FullyQualifiedName={case['fully_qualified_name']}",
        "--logger",
        f"trx;LogFileName={trx_name}",
        "--results-directory",
        str(case_results),
    ]
    started = datetime.now(timezone.utc)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
            env=os.environ.copy(),
        )
    except OSError as exc:
        finished = datetime.now(timezone.utc)
        return TestExecution(
            outcome="Error",
            started_date=started.isoformat(),
            completed_date=finished.isoformat(),
            duration_in_ms=(finished - started).total_seconds() * 1000,
            error_message=f"Could not start dotnet test: {exc}",
        )

    trx_files = list(case_results.rglob(trx_name))
    if len(trx_files) != 1:
        finished = datetime.now(timezone.utc)
        output = "\n".join(part for part in (completed.stderr, completed.stdout) if part).strip()
        return TestExecution(
            outcome="Error",
            started_date=started.isoformat(),
            completed_date=finished.isoformat(),
            duration_in_ms=(finished - started).total_seconds() * 1000,
            error_message=(
                f"Expected one TRX file for Test Case {test_case_id}, found {len(trx_files)}. "
                f"dotnet exit code: {completed.returncode}. {output[-1000:]}"
            )[:1000],
        )

    test_work_directory = test_project.parent / "bin" / build_configuration / "net10.0"
    try:
        execution = _read_trx(
            trx_files[0],
            completed.returncode,
            search_roots=[test_work_directory],
        )
    except (ET.ParseError, OSError) as exc:
        finished = datetime.now(timezone.utc)
        return TestExecution(
            outcome="Error",
            started_date=started.isoformat(),
            completed_date=finished.isoformat(),
            duration_in_ms=(finished - started).total_seconds() * 1000,
            error_message=f"Could not read test results for Test Case {test_case_id}: {exc}"[:1000],
        )
    return execution


def _read_trx(
    trx_path: Path,
    process_exit_code: int,
    *,
    search_roots: list[Path] | None = None,
) -> TestExecution:
    root = ET.parse(trx_path).getroot()
    deployment_root = next(
        (element.get("runDeploymentRoot") for element in root.iter()
         if _local_name(element.tag) == "Deployment"),
        None,
    )
    test_results = [element for element in root.iter() if _local_name(element.tag) == "UnitTestResult"]
    if not test_results:
        now = datetime.now(timezone.utc).isoformat()
        return TestExecution(
            outcome="Error",
            started_date=now,
            completed_date=now,
            duration_in_ms=0,
            error_message="The test filter matched no tests or the TRX file contains no test results.",
        )

    outcomes = [str(result.get("outcome") or "").casefold() for result in test_results]
    if any(outcome in {"failed", "error", "timeout", "aborted"} for outcome in outcomes):
        outcome = "Failed" if "failed" in outcomes else "Error"
    elif all(outcome == "passed" for outcome in outcomes):
        outcome = "Passed"
    elif any(outcome in {"notexecuted", "skipped"} for outcome in outcomes):
        outcome = "NotExecuted"
    else:
        outcome = "Error"

    if process_exit_code != 0 and outcome == "Passed":
        outcome = "Error"

    messages: list[str] = []
    stack_traces: list[str] = []
    attachments: list[TestAttachment] = []
    seen_attachments: set[Path] = set()
    start_times: list[datetime] = []
    end_times: list[datetime] = []
    duration_in_ms = 0.0
    for result in test_results:
        start_time = _parse_datetime(result.get("startTime"))
        end_time = _parse_datetime(result.get("endTime"))
        if start_time:
            start_times.append(start_time)
        if end_time:
            end_times.append(end_time)
        duration_in_ms += _parse_duration_ms(result.get("duration"))

        for element in result.iter():
            local_name = _local_name(element.tag)
            if local_name == "Message" and element.text:
                messages.append(element.text.strip())
            elif local_name == "StackTrace" and element.text:
                stack_traces.append(element.text.strip())
            elif local_name == "ResultFile":
                attachment_path = str(element.get("path") or "").strip()
                if not attachment_path:
                    continue
                path = Path(attachment_path.replace("\\", "/"))
                candidates = (
                    [path]
                    if path.is_absolute()
                    else [trx_path.parent / path, Path.cwd() / path, *[root / path for root in search_roots or []]]
                )
                if not path.is_absolute() and deployment_root and result.get("executionId"):
                    candidates.insert(
                        0,
                        trx_path.parent / deployment_root / "In" / result.get("executionId") / path,
                    )
                found = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
                if found is None:
                    logger.warning("TRX references a missing test attachment: %s", attachment_path)
                elif found not in seen_attachments:
                    seen_attachments.add(found)
                    attachments.append(TestAttachment(path=found, comment=found.name))

    now = datetime.now(timezone.utc)
    started = min(start_times) if start_times else now
    completed = max(end_times) if end_times else now
    if completed < started:
        completed = started
    error_message = "\n".join(message for message in messages if message)[:1000]
    stack_trace = "\n".join(trace for trace in stack_traces if trace)[:1000]
    if outcome != "Passed" and not error_message:
        trx_outcomes = ", ".join(sorted({str(value) for value in outcomes if value})) or "unspecified"
        error_message = f"Test outcome was {trx_outcomes}; dotnet test exit code {process_exit_code}."

    return TestExecution(
        outcome=outcome,
        started_date=started.isoformat(),
        completed_date=completed.isoformat(),
        duration_in_ms=duration_in_ms,
        error_message=error_message,
        stack_trace=stack_trace,
        attachments=attachments,
    )


def _publish_results(
    *,
    client: Any,
    run_id: int,
    plan_id: int,
    suite_id: int,
    configuration_id: int,
    cases: list[dict[str, Any]],
    executions: dict[int, TestExecution],
) -> dict[int, int]:
    existing_results = client.get_test_run_results(run_id)
    existing_by_point: dict[int, dict[str, Any]] = {}
    for result in existing_results:
        point_id = _reference_id(result.get("testPoint"))
        if point_id is not None:
            existing_by_point[point_id] = result

    to_add: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []
    point_case: dict[int, int] = {}
    for case in cases:
        test_case_id = int(case["test_case_id"])
        execution = executions[test_case_id]
        for point in case["points"]:
            point_id = int(point["id"])
            point_case[point_id] = test_case_id
            result = _build_result_payload(
                case=case,
                point=point,
                execution=execution,
                plan_id=plan_id,
                suite_id=suite_id,
                configuration_id=configuration_id,
            )
            existing = existing_by_point.get(point_id)
            if existing is None:
                to_add.append(result)
            else:
                result["id"] = int(existing["id"])
                to_update.append(result)

    result_ids: dict[int, int] = {}
    for point_id, result in existing_by_point.items():
        if point_id in point_case:
            try:
                result_ids[point_id] = int(result["id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise AzureDevOpsError(f"Existing result for test point {point_id} has no valid result ID.") from exc

    if to_update:
        client.update_test_run_results(run_id, to_update)
    if to_add:
        added_results = client.add_test_run_results(run_id, to_add)
        for index, result in enumerate(added_results):
            point_id = _reference_id(result.get("testPoint"))
            if point_id is None and index < len(to_add):
                point_id = _reference_id(to_add[index].get("testPoint"))
            if point_id is None:
                continue
            try:
                result_ids[point_id] = int(result["id"])
            except (KeyError, TypeError, ValueError):
                continue

    missing_point_ids = sorted(set(point_case) - set(result_ids))
    if missing_point_ids:
        raise AzureDevOpsError(
            "Azure DevOps did not return result IDs for test point(s): "
            + ", ".join(str(point_id) for point_id in missing_point_ids)
        )
    return result_ids


def _build_result_payload(
    *,
    case: dict[str, Any],
    point: dict[str, Any],
    execution: TestExecution,
    plan_id: int,
    suite_id: int,
    configuration_id: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "testCaseTitle": case["title"],
        "testCase": {"id": str(case["test_case_id"])},
        "testPoint": {"id": str(point["id"])},
        "testPlan": {"id": str(plan_id)},
        "testSuite": {"id": str(suite_id)},
        "configuration": {"id": str(configuration_id)},
        "automatedTestName": case["fully_qualified_name"],
        "automatedTestStorage": case["automated_test_storage"],
        "automatedTestType": case["automated_test_type"],
        "outcome": execution.outcome,
        "state": "Completed",
        "startedDate": execution.started_date,
        "completedDate": execution.completed_date,
        "durationInMs": execution.duration_in_ms,
        "computerName": os.getenv("AGENT_NAME") or platform.node(),
    }
    if case.get("priority") is not None:
        payload["priority"] = case["priority"]
    if execution.error_message:
        payload["errorMessage"] = execution.error_message[:1000]
    if execution.stack_trace:
        payload["stackTrace"] = execution.stack_trace[:1000]
    return payload


def _publish_attachments(
    *,
    client: Any,
    run_id: int,
    cases: list[dict[str, Any]],
    executions: dict[int, TestExecution],
    result_ids: dict[int, int],
) -> None:
    for case in cases:
        test_case_id = int(case["test_case_id"])
        for point in case["points"]:
            point_id = int(point["id"])
            result_id = result_ids[point_id]
            for attachment in executions[test_case_id].attachments:
                encoded = base64.b64encode(attachment.path.read_bytes()).decode("ascii")
                client.add_test_result_attachment(
                    run_id=run_id,
                    result_id=result_id,
                    file_name=attachment.path.name,
                    stream=encoded,
                    comment=attachment.comment,
                )


def _reference_id(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    raw_id = value.get("id")
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_duration_ms(value: str | None) -> float:
    if not value:
        return 0
    try:
        hours, minutes, seconds = value.split(":")
        duration = timedelta(hours=int(hours), minutes=int(minutes), seconds=float(seconds))
    except (TypeError, ValueError):
        return 0
    return duration.total_seconds() * 1000
