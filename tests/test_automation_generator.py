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
   Step 1 Action: Navigate to https://viewpointdev.gridbeyond.com/
   Step 1 Expected: Log in screen is displayed.
   Step 2 Action: In 'Sign in with your email address' option, input:- username: test.automation@gridbeyondteam.testinator.com- password: Gridbeyond123@
   Step 2 Expected:
   Step 3 Action: Click 'Sign in'
   Step 3 Expected: User is logged in successfully and navigated to Home screen. Text 'Welcome to your ViewPoint energy portal' is displayed in Home screen.
"""


class AutomationGeneratorTests(unittest.TestCase):
    def test_parse_suite_export_text_reads_steps(self):
        source = parse_suite_export_text(SUITE_EXPORT)

        self.assertEqual(source.plan_id, 30985)
        self.assertEqual(source.suite_id, 31681)
        self.assertEqual(len(source.test_cases), 1)
        self.assertEqual(source.test_cases[0].test_case_id, 31682)
        self.assertEqual(len(source.test_cases[0].steps), 3)
        self.assertIn("Navigate to https://viewpointdev.gridbeyond.com/", source.test_cases[0].steps[0].action)

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
            self.assertIn('?? "test.automation@gridbeyondteam.testinator.com";', content)

            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["suite_id"], 31681)
            self.assertEqual(manifest["generated_count"], 1)
            self.assertEqual(manifest["tests"][0]["strategy"], "login")


if __name__ == "__main__":
    unittest.main()
