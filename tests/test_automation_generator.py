from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automation_generator import generate_automation_scripts, parse_suite_export_text


SUITE_EXPORT = """Plan ID: 30985
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

NEGATIVE_LOGIN_EXPORT = """Plan ID: 30985
Suite ID: 31681
Test Cases: 1

1. [31988] Verify user cannot log in with wrong credentials
   Step 1 Action: Navigate to https://example.test/
   Step 1 Expected: Log in screen is displayed.
   Step 2 Action: In 'Sign in with your email address' option, input: - Email Address: valid.user@example.com - Password: InvalidPassword123!
   Step 2 Expected:
   Step 3 Action: Click 'Sign in' button
   Step 3 Expected: User cannot be logged in. Text ' The username or password provided in the request are invalid. ' is displayed in Log in screen
"""

GENERIC_URL_EXPORT = """Plan ID: 30985
Suite ID: 31681
Test Cases: 1

1. [32000] Open dashboard page
   Step 1 Action: Navigate to https://example.test/dashboard?tab=summary
   Step 1 Expected: Dashboard page is displayed.
"""


class AutomationGeneratorTests(unittest.TestCase):
    def test_parse_suite_export_text_reads_steps(self):
        source = parse_suite_export_text(SUITE_EXPORT)

        self.assertEqual(source.plan_id, 30985)
        self.assertEqual(source.suite_id, 31681)
        self.assertEqual(len(source.test_cases), 1)
        self.assertEqual(source.test_cases[0].test_case_id, 31682)
        self.assertEqual(len(source.test_cases[0].steps), 3)
        self.assertIn("Navigate to https://example.test/", source.test_cases[0].steps[0].action)

    def test_generate_scripts_writes_login_case_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "QA.Regression.Automation"
            (project_dir / "Tests").mkdir(parents=True)
            suite_file = root / "suite_31681_testcases.txt"
            suite_file.write_text(SUITE_EXPORT, encoding="utf-8")

            result = generate_automation_scripts(
                client=None,
                suite_file=str(suite_file),
                plan_id=None,
                suite_id=None,
                project_dir=str(project_dir),
                namespace="QA.Regression.Automation.Tests.Generated",
                overwrite=False,
            )

            generated = result["generated"]
            self.assertEqual(len(generated), 1)
            generated_file = Path(generated[0]["file_path"])
            self.assertTrue(generated_file.exists())

            content = generated_file.read_text(encoding="utf-8")
            self.assertIn('[Property("TestCaseId", "31682")]', content)
            self.assertIn("LoginPage", content)
            self.assertIn("IsLoginScreenDisplayedAsync", content)
            self.assertIn("GetWelcomeMessageTextAsync", content)
            self.assertIn("var baseUrl = TestEnvironmentSettings.ResolveBaseUrlForEnvironment();", content)
            self.assertIn('var username = TestEnvironmentSettings.RequireEnvironmentVariable("VIEWPOINT_USERNAME");', content)
            self.assertIn('var password = TestEnvironmentSettings.RequireEnvironmentVariable("VIEWPOINT_PASSWORD");', content)
            self.assertNotIn("https://example.test/", content)
            self.assertNotIn("valid.user@example.com", content)
            self.assertNotIn("ValidPassword123!", content)

            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["suite_id"], 31681)
            self.assertEqual(manifest["generated_count"], 1)
            self.assertEqual(manifest["tests"][0]["strategy"], "login-success")

    def test_generate_scripts_writes_negative_login_assertion(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "QA.Regression.Automation"
            (project_dir / "Tests").mkdir(parents=True)
            suite_file = root / "suite_31681_testcases.txt"
            suite_file.write_text(NEGATIVE_LOGIN_EXPORT, encoding="utf-8")

            result = generate_automation_scripts(
                client=None,
                suite_file=str(suite_file),
                plan_id=None,
                suite_id=None,
                project_dir=str(project_dir),
                namespace="QA.Regression.Automation.Tests.Generated",
                overwrite=False,
            )

            generated_file = Path(result["generated"][0]["file_path"])
            content = generated_file.read_text(encoding="utf-8")
            self.assertIn('ResolveOptionalEnvironmentVariable("VIEWPOINT_INVALID_USERNAME")', content)
            self.assertIn('RequireEnvironmentVariable("VIEWPOINT_INVALID_PASSWORD")', content)
            self.assertIn("GetLoginErrorTextAsync", content)
            self.assertIn("The expected login error message was not displayed.", content)
            self.assertNotIn("https://example.test/", content)
            self.assertNotIn("InvalidPassword123!", content)

    def test_generate_scripts_converts_absolute_step_urls_to_relative_environment_urls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "QA.Regression.Automation"
            (project_dir / "Tests").mkdir(parents=True)
            suite_file = root / "suite_31681_testcases.txt"
            suite_file.write_text(GENERIC_URL_EXPORT, encoding="utf-8")

            result = generate_automation_scripts(
                client=None,
                suite_file=str(suite_file),
                plan_id=None,
                suite_id=None,
                project_dir=str(project_dir),
                namespace="QA.Regression.Automation.Tests.Generated",
                overwrite=False,
            )

            generated_file = Path(result["generated"][0]["file_path"])
            content = generated_file.read_text(encoding="utf-8")

            self.assertIn(
                'await workflowPage.GoToAsync(TestEnvironmentSettings.ResolveUrlForEnvironment("/dashboard?tab=summary"));',
                content,
            )
            self.assertNotIn("https://example.test/dashboard?tab=summary", content)


if __name__ == "__main__":
    unittest.main()
