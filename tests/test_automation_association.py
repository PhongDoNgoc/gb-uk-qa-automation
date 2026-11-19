from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automation_association import associate_generated_tests, validate_generated_suite
from automation_generator import generate_automation_scripts


class FakeClient:
    def __init__(self, existing: dict[int, dict[str, str]] | None = None):
        self.existing = existing or {}
        self.calls: list[dict[str, str | int]] = []

    def get_test_case(self, test_case_id: int):
        values = self.existing.get(test_case_id, {})
        return {
            "id": test_case_id,
            "automated_test_name": values.get("automated_test_name", ""),
            "automated_test_storage": values.get("automated_test_storage", ""),
            "automated_test_type": values.get("automated_test_type", ""),
        }

    def associate_automated_test(
        self,
        test_case_id: int,
        *,
        automated_test_name: str,
        automated_test_storage: str,
        automated_test_type: str = "NUnit",
        automated_test_id: str | None = None,
    ):
        self.calls.append(
            {
                "test_case_id": test_case_id,
                "automated_test_name": automated_test_name,
                "automated_test_storage": automated_test_storage,
                "automated_test_type": automated_test_type,
                "automated_test_id": automated_test_id or "",
            }
        )
        return {"id": test_case_id}


class AutomationAssociationTests(unittest.TestCase):
    def test_validate_committed_suite_checks_paths_ids_and_complete_file_set(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = root / "automation-manifest.json"
            source = root / "Tc31682.cs"
            source.write_text("// reviewed source", encoding="utf-8")
            manifest = {
                "plan_id": 30985,
                "suite_id": 31681,
                "tests": [{
                    "test_case_id": 31682,
                    "file_path": r"QA.Regression.Automation\Tests\Generated\Suite31681\Tc31682.cs",
                    "fully_qualified_name": "QA.Regression.Automation.Tests.Generated.Suite31681.Class.Method",
                }],
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            def validate(plan_id=30985):
                return validate_generated_suite(
                    manifest_path=str(manifest_path), plan_id=plan_id, suite_id=31681,
                )
            self.assertEqual(validate(), 1)
            self.assertEqual(source.read_text(encoding="utf-8"), "// reviewed source")
            with self.assertRaisesRegex(ValueError, "does not match"):
                validate(plan_id=40001)
            extra = root / "Tc999.cs"
            extra.write_text("// stale", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "files do not match"):
                validate()
            extra.unlink()
            source.unlink()
            with self.assertRaisesRegex(FileNotFoundError, "Committed script"):
                validate()
            manifest_path.unlink()
            with self.assertRaisesRegex(FileNotFoundError, "commit/push"):
                validate()

    def test_validate_committed_suite_rejects_duplicate_cases_and_wrong_namespace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Tc1.cs").write_text("// generated", encoding="utf-8")
            path = root / "automation-manifest.json"
            entry = {
                "test_case_id": 1, "file_path": "Tc1.cs",
                "fully_qualified_name": "QA.Regression.Automation.Tests.Generated.Suite31681.Class.Method",
            }
            manifest = {"plan_id": 30985, "suite_id": 31681, "tests": [entry, entry]}
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate Test Case"):
                validate_generated_suite(manifest_path=str(path), plan_id=30985, suite_id=31681)
            manifest["tests"] = [{**entry, "fully_qualified_name": "Other.Class.Method"}]
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside the selected"):
                validate_generated_suite(manifest_path=str(path), plan_id=30985, suite_id=31681)

    def test_associate_generated_tests_updates_manifest_entries(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path = Path(td) / "automation-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "plan_id": 30985,
                        "suite_id": 31681,
                        "assembly_name": "QA.Regression.Automation.dll",
                        "tests": [
                            {
                                "test_case_id": 31682,
                                "fully_qualified_name": "QA.Regression.Automation.Tests.Generated.Suite31681.Tc31682LogInViewPointPortalTests.Tc31682_LogInViewPointPortal",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            client = FakeClient()
            result = associate_generated_tests(
                client=client,
                manifest_path=str(manifest_path),
                test_storage=None,
                test_type="NUnit",
                overwrite=False,
            )

            self.assertEqual(len(result["updated"]), 1)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(client.calls[0]["test_case_id"], 31682)
            self.assertEqual(client.calls[0]["automated_test_storage"], "QA.Regression.Automation.dll")

    def test_associate_generated_tests_refuses_to_replace_without_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path = Path(td) / "automation-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "assembly_name": "QA.Regression.Automation.dll",
                        "tests": [{"test_case_id": 31682, "fully_qualified_name": "New.Name"}],
                    }
                ),
                encoding="utf-8",
            )

            client = FakeClient(
                {
                    31682: {
                        "automated_test_name": "Old.Name",
                        "automated_test_storage": "Old.dll",
                        "automated_test_type": "NUnit",
                    }
                }
            )

            with self.assertRaisesRegex(ValueError, "overwrite-association"):
                associate_generated_tests(
                    client=client,
                    manifest_path=str(manifest_path),
                    test_storage=None,
                    test_type="NUnit",
                    overwrite=False,
                )

    def test_associate_generated_tests_skips_matching_association(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path = Path(td) / "automation-manifest.json"
            fully_qualified_name = "QA.Regression.Automation.Tests.Generated.Suite31681.Class.Method"
            manifest_path.write_text(
                json.dumps(
                    {
                        "assembly_name": "QA.Regression.Automation.dll",
                        "tests": [{"test_case_id": 31682, "fully_qualified_name": fully_qualified_name}],
                    }
                ),
                encoding="utf-8",
            )

            client = FakeClient(
                {
                    31682: {
                        "automated_test_name": fully_qualified_name,
                        "automated_test_storage": "QA.Regression.Automation.dll",
                        "automated_test_type": "NUnit",
                    }
                }
            )

            result = associate_generated_tests(
                client=client,
                manifest_path=str(manifest_path),
                test_storage=None,
                test_type="NUnit",
                overwrite=False,
            )

            self.assertEqual(len(result["updated"]), 0)
            self.assertEqual(len(result["skipped"]), 1)
            self.assertEqual(client.calls, [])

    def test_generated_manifest_can_be_associated_end_to_end(self):
        suite_export = """Plan ID: 30985
Suite ID: 31681
Test Cases: 1

1. [31682] Log in ViewPoint Portal
   Step 1 Action: Navigate to https://example.test/
   Step 1 Expected: Log in screen is displayed.
   Step 2 Action: In 'Sign in with your email address' option, input: - Email Address: valid.user@example.com - Password: ValidPassword123!
   Step 2 Expected:
   Step 3 Action: Click 'Sign in' button
   Step 3 Expected: User is logged in successfully and navigated to Home screen. Text 'Welcome to your ViewPoint energy portal' is displayed in Home screen.
"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "QA.Regression.Automation"
            (project_dir / "Tests").mkdir(parents=True)
            suite_file = root / "suite_31681_testcases.txt"
            suite_file.write_text(suite_export, encoding="utf-8")

            generation = generate_automation_scripts(
                client=None,
                suite_file=str(suite_file),
                plan_id=None,
                suite_id=None,
                project_dir=str(project_dir),
                namespace="QA.Regression.Automation.Tests.Generated",
                overwrite=False,
            )

            client = FakeClient()
            association = associate_generated_tests(
                client=client,
                manifest_path=generation["manifest_path"],
                test_storage=None,
                test_type="NUnit",
                overwrite=False,
            )

            self.assertEqual(len(association["updated"]), 1)
            self.assertEqual(client.calls[0]["automated_test_storage"], "QA.Regression.Automation.dll")
            self.assertIn("Suite31681", str(client.calls[0]["automated_test_name"]))


if __name__ == "__main__":
    unittest.main()
