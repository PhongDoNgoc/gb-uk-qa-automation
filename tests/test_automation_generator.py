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

API_STATUS_EXPORT = """Plan ID: 30985
Suite ID: 31681
Test Cases: 1

1. [31861] Customer Details - Verify EnergyServiceDetails API in Customer Details page is working
   Step 1 Action: Precondition: - Logged in ViewPoint Portal
   Step 1 Expected:
   Step 2 Action: Open Utilities sub-menu and click to Customer Details URL: baseURL/CustomerDetails/CustomerDetail
   Step 2 Expected: User is navigated to Customer Details page
   Step 3 Action: Verify the EnergyServiceDetailsAPI response status Request URL: baseURL/ CustomerDetails/ EnergyServiceDetails
   Step 3 Expected: Status Code should be 200 OK
"""

SITE_DETAILS_STEPS_XML = """<steps id="0" last="4">
<step id="2" type="ActionStep">
  <parameterizedString isformatted="true">Precondition:&lt;br&gt;- Logged in ViewPoint Portal</parameterizedString>
  <parameterizedString isformatted="true"></parameterizedString>
  <description />
</step>
<step id="3" type="ValidateStep">
  <parameterizedString isformatted="true">Open Utilities sub-menu and click to Customer Details&lt;br&gt;URL: baseURL/CustomerDetails/CustomerDetail</parameterizedString>
  <parameterizedString isformatted="true">User is navigated to Customer Details page</parameterizedString>
  <description />
</step>
<step id="4" type="ValidateStep">
  <parameterizedString isformatted="true">Verify the SiteDetails API response status&lt;br&gt;Request URL: baseURL/CustomerDetails/SiteDetails?rootId='@rootID' (valid rootID)</parameterizedString>
  <parameterizedString isformatted="true">Status Code should be 200 OK</parameterizedString>
  <description />
</step>
</steps>"""

SITE_DETAILS_LOCAL_DATA_SOURCE = """<NewDataSet><Table1><rootID>165</rootID></Table1></NewDataSet>"""

CUSTOMER_DETAIL_EXPORT = """Plan ID: 30985
Suite ID: 31681
Test Cases: 1

1. [31869] Unit Details - Verify GetCustomerDetail API in Unit Details page is working
   Step 1 Action: Precondition: - Logged in ViewPoint Portal
   Step 1 Expected:
   Step 2 Action: Open Utilities sub-menu and click to Unit Details URL: baseURL/UnitDetails/UnitDetail
   Step 2 Expected: User is navigated to Unit Details page
   Step 3 Action: Verify the GetCustomerDetail API response status Request URL: baseURL/http://unitdetails/GetCustomerDetail?controlUnitId='controlUnitID'&marketUnitId='marketUnitID' (valid controlunitID and valid marketunitID)
   Step 3 Expected: Status Code should be 200 OK
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

    def test_generate_scripts_writes_authenticated_api_status_case(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "QA.Regression.Automation"
            (project_dir / "Tests").mkdir(parents=True)
            suite_file = root / "suite_31681_testcases.txt"
            suite_file.write_text(API_STATUS_EXPORT, encoding="utf-8")

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

            self.assertIn("var loginPage = new LoginPage(Page);", content)
            self.assertIn('var targetPageUrl = TestEnvironmentSettings.ResolveUrlForEnvironment("/CustomerDetails/CustomerDetail");', content)
            self.assertIn('var apiPathFragment = "/CustomerDetails/EnergyServiceDetails";', content)
            self.assertIn("const int expectedStatusCode = 200;", content)
            self.assertIn(
                "var actualStatusCode = await workflowPage.GoToAndCaptureApiResponseStatusAsync(targetPageUrl, apiPathFragment);",
                content,
            )
            self.assertIn('Expected EnergyServiceDetails to return HTTP status 200 after sign in.', content)
            self.assertEqual(result["generated"][0]["strategy"], "authenticated-api-status")

    def test_generate_scripts_substitutes_parameter_values_into_api_request_url(self):
        class FakeClient:
            def get_suite_test_cases(self, plan_id, suite_id):
                return [
                    {
                        "id": "31863",
                        "title": "Customer Details - Verify SiteDetails API in Customer Details page is working",
                        "state": "Design",
                        "steps": SITE_DETAILS_STEPS_XML,
                        "local_data_source": SITE_DETAILS_LOCAL_DATA_SOURCE,
                    }
                ]

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "QA.Regression.Automation"
            (project_dir / "Tests").mkdir(parents=True)

            result = generate_automation_scripts(
                client=FakeClient(),
                suite_file=None,
                plan_id=30985,
                suite_id=31681,
                project_dir=str(project_dir),
                namespace="QA.Regression.Automation.Tests.Generated",
                overwrite=False,
            )

            generated_file = Path(result["generated"][0]["file_path"])
            content = generated_file.read_text(encoding="utf-8")

            self.assertIn('var apiPathFragment = "/CustomerDetails/SiteDetails?rootId=165";', content)
            self.assertEqual(result["generated"][0]["parameter_values"], {"rootID": "165"})

    def test_generate_scripts_normalizes_embedded_absolute_request_url(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "QA.Regression.Automation"
            (project_dir / "Tests").mkdir(parents=True)
            suite_file = root / "suite_31681_testcases.txt"
            suite_file.write_text(CUSTOMER_DETAIL_EXPORT, encoding="utf-8")

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
                'var apiPathFragment = "/UnitDetails/GetCustomerDetail?controlUnitId=controlUnitID&marketUnitId=marketUnitID";',
                content,
            )


if __name__ == "__main__":
    unittest.main()
