from __future__ import annotations

import base64
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any
from unittest.mock import Mock, patch

from azure_client import AzureConfig, AzureDevOpsClient, AzureDevOpsError
from test_plan_runner import TestAttachment, TestExecution, _read_trx, execute_test_case, run_test_plan


class FakeAzureClient:
    def __init__(
        self,
        *,
        points: list[dict[str, Any]],
        cases: dict[int, dict[str, Any]],
        existing_results: list[dict[str, Any]] | None = None,
    ):
        self.points = points
        self.cases = cases
        self.existing_results = existing_results or []
        self.created_run: dict[str, Any] | None = None
        self.added_results: list[dict[str, Any]] = []
        self.updated_results: list[dict[str, Any]] = []
        self.attachments: list[dict[str, Any]] = []
        self.completed_runs: list[int] = []

    def get_suite_test_points(self, plan_id: int, suite_id: int) -> list[dict[str, Any]]:
        return self.points

    def get_test_case(self, test_case_id: int) -> dict[str, Any]:
        return self.cases[test_case_id]

    def create_test_run(self, **kwargs: Any) -> dict[str, Any]:
        self.created_run = kwargs
        return {"id": 456}

    def get_test_run_results(self, run_id: int) -> list[dict[str, Any]]:
        return self.existing_results

    def update_test_run_results(self, run_id: int, results: list[dict[str, Any]]) -> None:
        self.updated_results.extend(results)

    def add_test_run_results(self, run_id: int, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.added_results.extend(results)
        return [
            {"id": 700 + index, "testPoint": result["testPoint"]}
            for index, result in enumerate(results)
        ]

    def add_test_result_attachment(self, **kwargs: Any) -> dict[str, Any]:
        self.attachments.append(kwargs)
        return {"id": len(self.attachments)}

    def complete_test_run(self, run_id: int, *, error_message: str = "") -> None:
        self.completed_runs.append(run_id)


def _automated_case(test_case_id: int) -> dict[str, Any]:
    return {
        "id": test_case_id,
        "title": f"Case {test_case_id}",
        "automation_status": "Automated",
        "automated_test_name": f"Tests.Suite.Case{test_case_id}.Run",
        "automated_test_storage": "QA.Regression.Automation.dll",
        "automated_test_type": "NUnit",
        "priority": 2,
    }


def _execution(outcome: str = "Passed", attachments: list[TestAttachment] | None = None) -> TestExecution:
    now = datetime.now(timezone.utc).isoformat()
    return TestExecution(
        outcome=outcome,
        started_date=now,
        completed_date=now,
        duration_in_ms=25,
        error_message="Assertion failed" if outcome != "Passed" else "",
        stack_trace="stack" if outcome != "Passed" else "",
        attachments=attachments or [],
    )


class TestPlanRunnerTests(unittest.TestCase):
    def test_runs_only_automated_points_for_selected_configuration_and_updates_test_plan(self):
        client = FakeAzureClient(
            points=[
                {"id": 101, "test_case_id": 1, "configuration_id": 188},
                {"id": 102, "test_case_id": 2, "configuration_id": 188},
                {"id": 103, "test_case_id": 3, "configuration_id": 189},
            ],
            cases={
                1: _automated_case(1),
                2: {"id": 2, "title": "Manual case", "automation_status": "Not Automated"},
                3: _automated_case(3),
            },
            existing_results=[{"id": 501, "testPoint": {"id": 101}}],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "test.csproj"
            project.write_text("<Project />", encoding="utf-8")
            result = run_test_plan(
                client=client,
                plan_id=30985,
                suite_id=31681,
                configuration_id=188,
                test_project=str(project),
                build_configuration="Release",
                results_directory=str(root / "results"),
                execute_case=lambda *_args, **_kwargs: _execution(),
            )

        self.assertEqual(client.created_run["point_ids"], [101])
        self.assertEqual(client.updated_results[0]["id"], 501)
        self.assertEqual(client.updated_results[0]["outcome"], "Passed")
        self.assertEqual(client.completed_runs, [456])
        self.assertEqual(result["passed_case_count"], 1)
        self.assertEqual(result["skipped_point_count"], 1)

    def test_adds_results_and_uploads_test_attachments(self):
        client = FakeAzureClient(
            points=[{"id": 101, "test_case_id": 1, "configuration_id": 188}],
            cases={1: _automated_case(1)},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "test.csproj"
            project.write_text("<Project />", encoding="utf-8")
            evidence = root / "evidence.png"
            evidence.write_bytes(b"evidence")
            result = run_test_plan(
                client=client,
                plan_id=30985,
                suite_id=31681,
                configuration_id=188,
                test_project=str(project),
                build_configuration="Release",
                results_directory=str(root / "results"),
                execute_case=lambda *_args, **_kwargs: _execution(
                    "Failed",
                    [TestAttachment(path=evidence, comment="Failure screenshot")],
                ),
            )

        self.assertEqual(client.added_results[0]["outcome"], "Failed")
        self.assertEqual(client.attachments[0]["result_id"], 700)
        self.assertEqual(
            base64.b64decode(client.attachments[0]["stream"]),
            b"evidence",
        )
        self.assertEqual(client.completed_runs, [456])
        self.assertEqual(result["failed_test_case_ids"], [1])

    def test_rejects_automated_case_without_association(self):
        client = FakeAzureClient(
            points=[{"id": 101, "test_case_id": 1, "configuration_id": 188}],
            cases={
                1: {
                    "id": 1,
                    "title": "Missing association",
                    "automation_status": "Automated",
                    "automated_test_name": "",
                    "automated_test_storage": "",
                }
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "test.csproj"
            project.write_text("<Project />", encoding="utf-8")
            with self.assertRaisesRegex(AzureDevOpsError, "no associated test name or storage"):
                run_test_plan(
                    client=client,
                    plan_id=30985,
                    suite_id=31681,
                    configuration_id=188,
                    test_project=str(project),
                    build_configuration="Release",
                    results_directory=str(root / "results"),
                )
        self.assertIsNone(client.created_run)

    def test_reads_trx_outcome_and_attachments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            attachment = root / "screenshot.png"
            attachment.write_bytes(b"image")
            trx = root / "results.trx"
            trx.write_text(
                """<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <Results>
    <UnitTestResult testName="Tests.Suite.Case1.Run" outcome="Passed"
      startTime="2026-10-28T08:00:00Z" endTime="2026-10-28T08:00:01Z" duration="00:00:01.000">
      <Output><ResultFiles><ResultFile path="screenshot.png" /></ResultFiles></Output>
    </UnitTestResult>
  </Results>
</TestRun>""",
                encoding="utf-8",
            )
            execution = _read_trx(trx, 0)

        self.assertEqual(execution.outcome, "Passed")
        self.assertEqual(execution.attachments[0].path.name, "screenshot.png")
        self.assertEqual(execution.duration_in_ms, 1000)

    @patch("test_plan_runner.subprocess.run")
    def test_executes_the_associated_fully_qualified_test_name(self, subprocess_run):
        fully_qualified_name = "Tests.Suite.Case1.Run"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "QA.Regression.Automation.csproj"
            project.write_text("<Project />", encoding="utf-8")
            results = root / "results"

            def create_trx(command, **_kwargs):
                result_directory = Path(command[command.index("--results-directory") + 1])
                result_directory.mkdir(parents=True, exist_ok=True)
                trx_name = command[command.index("--logger") + 1].split("LogFileName=", 1)[1]
                (result_directory / trx_name).write_text(
                    """<TestRun>
  <Results>
    <UnitTestResult testName="Tests.Suite.Case1.Run" outcome="Passed"
      startTime="2026-10-28T08:00:00Z" endTime="2026-10-28T08:00:01Z" duration="00:00:01.000" />
  </Results>
</TestRun>""",
                    encoding="utf-8",
                )
                return CompletedProcess(command, 0, stdout="", stderr="")

            subprocess_run.side_effect = create_trx
            execution = execute_test_case(
                {
                    "test_case_id": 1,
                    "fully_qualified_name": fully_qualified_name,
                },
                test_project=project,
                build_configuration="Release",
                results_directory=results,
            )

        command = subprocess_run.call_args.args[0]
        filter_index = command.index("--filter")
        self.assertEqual(command[filter_index + 1], f"FullyQualifiedName={fully_qualified_name}")
        self.assertEqual(execution.outcome, "Passed")


class AzureClientResponseTests(unittest.TestCase):
    @patch("azure_client.requests.get")
    def test_reports_route_and_content_type_for_non_json_responses(self, get):
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/html"}
        response.json.side_effect = ValueError("invalid JSON")
        get.return_value = response
        client = AzureDevOpsClient(AzureConfig(org="example", project="project", pat="token"))

        with self.assertRaisesRegex(
            AzureDevOpsError,
            r"GET /_apis/test/Plans/1/suites/2/points \(HTTP 200, content type text/html\)",
        ):
            client._get("/_apis/test/Plans/1/suites/2/points")


if __name__ == "__main__":
    unittest.main()
