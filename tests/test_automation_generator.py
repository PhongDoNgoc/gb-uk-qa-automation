from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automation_generator import (
    _extract_environment_specific_api_paths,
    generate_automation_scripts,
    parse_suite_export_text,
)


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
ENVIRONMENT_SITE_DETAILS_LOCAL_DATA_SOURCE = """<NewDataSet>
<Table1><Environment>DEV</Environment><rootID>301</rootID></Table1>
<Table1><Environment>STAGE</Environment><rootID>415</rootID></Table1>
</NewDataSet>"""

SEGMENT_DETAILS_STEPS_XML = """<steps id="0" last="3">
<step id="1" type="ActionStep">
  <parameterizedString isformatted="true">Precondition:&lt;br&gt;- Logged in ViewPoint Portal</parameterizedString>
  <parameterizedString isformatted="true"></parameterizedString>
  <description />
</step>
<step id="2" type="ValidateStep">
  <parameterizedString isformatted="true">Open Utilities sub-menu and click to Customer Details&lt;br&gt;URL: baseURL/CustomerDetails/CustomerDetail</parameterizedString>
  <parameterizedString isformatted="true">User is navigated to Customer Details page</parameterizedString>
  <description />
</step>
<step id="3" type="ValidateStep">
  <parameterizedString isformatted="true">Verify the SegmentDetails API response status&lt;br&gt;Request URL @environment : baseURL/CustomerDetails/SegmentDetails?SiteId='@siteID' (valid siteID)</parameterizedString>
  <parameterizedString isformatted="true">Status Code should be 200 OK</parameterizedString>
  <description />
</step>
</steps>"""

ENVIRONMENT_SEGMENT_DETAILS_LOCAL_DATA_SOURCE = """<NewDataSet>
<Table1><environment>prod</environment><siteID>851</siteID></Table1>
<Table1><environment>stage</environment><siteID>851</siteID></Table1>
<Table1><environment>dev</environment><siteID>356</siteID></Table1>
</NewDataSet>"""

CONTROL_UNIT_STEPS_XML = """<steps id="0" last="3">
<step id="1" type="ActionStep">
  <parameterizedString isformatted="true">Precondition:&lt;br&gt;- Logged in ViewPoint Portal</parameterizedString>
  <parameterizedString isformatted="true"></parameterizedString>
  <description />
</step>
<step id="2" type="ValidateStep">
  <parameterizedString isformatted="true">Open Utilities sub-menu and click to Unit Details&lt;br&gt;URL: baseURL/UnitDetails/UnitDetail</parameterizedString>
  <parameterizedString isformatted="true">User is navigated to Unit Details page</parameterizedString>
  <description />
</step>
<step id="3" type="ValidateStep">
  <parameterizedString isformatted="true">Verify the GetControlUnit API response status&lt;br&gt;Request URL @environment : baseURL/UnitDetails/GetControlUnit?marketUnitId='@marketunitID' (valid marketunitID)</parameterizedString>
  <parameterizedString isformatted="true">Status Code should be 200 OK</parameterizedString>
  <description />
</step>
</steps>"""

ENVIRONMENT_CONTROL_UNIT_LOCAL_DATA_SOURCE = """<NewDataSet>
<Table1><environment>prod</environment><marketunitID>2</marketunitID></Table1>
<Table1><environment>stage</environment><marketunitID>3</marketunitID></Table1>
<Table1><environment>dev</environment><marketunitID>3008</marketunitID></Table1>
</NewDataSet>"""

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

REFRESH_EXPORT = """Plan ID: 30985
Suite ID: 31681
Test Cases: 1

1. [31866] Unit Details - Verify Refresh in Unit Details page is working
   Step 1 Action: Precondition: - Logged in ViewPoint Portal
   Step 1 Expected:
   Step 2 Action: Open Utilities sub-menu and click to Unit Details URL: baseURL/UnitDetails/UnitDetail
   Step 2 Expected: User is navigated to Unit Details page
   Step 3 Action: Click on Refresh button
   Step 3 Expected: Data on grid should be reloaded and updated
"""


class AutomationGeneratorTests(unittest.TestCase):
    def test_export_cases_generate_download_checked_click_for_manual_step_wording(self):
        for case_id in (31855, 31857, 31865):
            for action in (
                "Click 'Export to Excel' button",
                "Click on 'Export to excel' button",
                'Click on "Export to Excel" button.',
                "Click on \u2018Export to Excel\u2019 button",
                "Click on Export to Excel button.",
            ):
                with self.subTest(case_id=case_id, action=action), tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    project_dir = root / "QA.Regression.Automation"
                    project_dir.mkdir()
                    suite_file = root / "suite.txt"
                    suite_file.write_text(
                        REFRESH_EXPORT.replace("[31866]", f"[{case_id}]")
                        .replace("Verify Refresh", "Verify Export")
                        .replace("Click on Refresh button", action),
                        encoding="utf-8",
                    )
                    result = generate_automation_scripts(
                        client=None, suite_file=str(suite_file), plan_id=None, suite_id=None,
                        project_dir=str(project_dir),
                        namespace="QA.Regression.Automation.Tests.Generated", overwrite=False,
                    )
                    content = Path(result["generated"][0]["file_path"]).read_text(encoding="utf-8")
                    self.assertIn('await workflowPage.ClickButtonAsync("Export to Excel");', content)
                    self.assertIn("await loginPage.LoginAsync(username, password);", content)

    def test_export_case_without_translatable_click_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "QA.Regression.Automation"
            project_dir.mkdir()
            suite_file = root / "suite.txt"
            suite_file.write_text(
                REFRESH_EXPORT.replace("Verify Refresh", "Verify Export")
                .replace("Click on Refresh button", "Use the export control"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "31866.*without its download assertion"):
                generate_automation_scripts(
                    client=None, suite_file=str(suite_file), plan_id=None, suite_id=None,
                    project_dir=str(project_dir),
                    namespace="QA.Regression.Automation.Tests.Generated", overwrite=False,
                )

    def test_export_cases_select_environment_specific_parameter_values_before_export(self):
        steps_xml = """<steps id="0" last="5">
<step id="2" type="ActionStep"><parameterizedString isformatted="true">Precondition:&lt;br&gt;- Logged in ViewPoint Portal</parameterizedString><parameterizedString isformatted="true"></parameterizedString><description /></step>
<step id="3" type="ValidateStep"><parameterizedString isformatted="true">Open Utilities sub-menu and click to Payment Availability&lt;br&gt;URL @environment: baseURL/PaymentAvailability/PaymentAvailabilityIndex</parameterizedString><parameterizedString isformatted="true">User is navigated to Payment Availability page</parameterizedString><description /></step>
<step id="4" type="ActionStep"><parameterizedString isformatted="true">In 'Country' selector, select @country</parameterizedString><parameterizedString isformatted="true"></parameterizedString><description /></step>
<step id="5" type="ActionStep"><parameterizedString isformatted="true">In  'Select Issue Type' selector, select @issuetype</parameterizedString><parameterizedString isformatted="true"></parameterizedString><description /></step>
<step id="6" type="ActionStep"><parameterizedString isformatted="true">Select a @date in Select Date selector</parameterizedString><parameterizedString isformatted="true"></parameterizedString><description /></step>
<step id="7" type="ValidateStep"><parameterizedString isformatted="true">Click on 'Export to Excel' button</parameterizedString><parameterizedString isformatted="true">File should be downloaded successfully with correct data</parameterizedString><description /></step>
</steps>"""
        data_source = """<NewDataSet>
<Table1><environment>dev</environment><country></country><issuetype></issuetype><date>Feb-2026</date></Table1>
<Table1><environment>stage</environment><country>GB</country><issuetype>All</issuetype><date>Jan-2026</date></Table1>
</NewDataSet>"""

        class FakeClient:
            def get_suite_test_cases(self, plan_id, suite_id):
                return [{
                    "id": "31857",
                    "title": "Payment Availability - Verify 'Export to Excel' in Payment Availability page is working",
                    "steps": steps_xml,
                    "local_data_source": data_source,
                }]

        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "QA.Regression.Automation"
            project_dir.mkdir()
            result = generate_automation_scripts(
                client=FakeClient(), suite_file=None, plan_id=30985, suite_id=31681,
                project_dir=str(project_dir),
                namespace="QA.Regression.Automation.Tests.Generated", overwrite=False,
            )
            content = Path(result["generated"][0]["file_path"]).read_text(encoding="utf-8")

        self.assertIn(
            'await workflowPage.SelectOptionAsync("Country", TestEnvironmentSettings.ResolveEnvironmentSpecificValue('
            'new Dictionary<string, string> { ["STAGE"] = "GB", }));',
            content,
        )
        self.assertIn('SelectOptionAsync("Select Issue Type", ', content)
        self.assertIn(
            'SelectOptionAsync("Select Date", TestEnvironmentSettings.ResolveEnvironmentSpecificValue('
            'new Dictionary<string, string> { ["DEV"] = "Feb-2026", ["STAGE"] = "Jan-2026", }));',
            content,
        )
        self.assertLess(content.index("SelectOptionAsync(\"Select Date\""), content.index("Export to Excel\");"))

    def test_selector_steps_with_literal_values_and_unparseable_wording(self):
        for action, expected in (
            ("Select 'GB' from the 'Country' dropdown.", 'SelectOptionAsync("Country", "GB");'),
            ("In the Period picker, choose \u201806/2019\u2019", 'SelectOptionAsync("Period", "06/2019");'),
        ):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                project_dir = root / "QA.Regression.Automation"
                project_dir.mkdir()
                suite_file = root / "suite.txt"
                suite_file.write_text(REFRESH_EXPORT.replace("Click on Refresh button", action), encoding="utf-8")
                result = generate_automation_scripts(
                    client=None, suite_file=str(suite_file), plan_id=None, suite_id=None,
                    project_dir=str(project_dir),
                    namespace="QA.Regression.Automation.Tests.Generated", overwrite=False,
                )
                self.assertIn(expected, Path(result["generated"][0]["file_path"]).read_text(encoding="utf-8"))

        for action, error in (
            ("Use the Country selector to select something", "selector step could not be generated"),
            ("In 'Country' selector, select @country", "parameter '@country' has no value"),
        ):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                project_dir = root / "QA.Regression.Automation"
                project_dir.mkdir()
                suite_file = root / "suite.txt"
                suite_file.write_text(REFRESH_EXPORT.replace("Click on Refresh button", action), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, error):
                    generate_automation_scripts(
                        client=None, suite_file=str(suite_file), plan_id=None, suite_id=None,
                        project_dir=str(project_dir),
                        namespace="QA.Regression.Automation.Tests.Generated", overwrite=False,
                    )

    def test_parse_suite_export_text_reads_steps(self):
        source = parse_suite_export_text(SUITE_EXPORT)

        self.assertEqual(source.plan_id, 30985)
        self.assertEqual(source.suite_id, 31681)
        self.assertEqual(len(source.test_cases), 1)
        self.assertEqual(source.test_cases[0].test_case_id, 31682)
        self.assertEqual(len(source.test_cases[0].steps), 3)
        self.assertIn("Navigate to https://example.test/", source.test_cases[0].steps[0].action)

    def test_generate_scripts_removes_stale_generated_cases_from_suite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "QA.Regression.Automation"
            suite_dir = project_dir / "Tests" / "Generated" / "Suite31681"
            suite_dir.mkdir(parents=True)
            stale_file = suite_dir / "Tc99999RemovedTests.cs"
            stale_file.write_text("// <auto-generated />\n", encoding="utf-8")
            hand_written_file = suite_dir / "Tc88888ManualTests.cs"
            hand_written_file.write_text("// maintained manually\n", encoding="utf-8")
            suite_file = root / "suite.txt"
            suite_file.write_text(SUITE_EXPORT, encoding="utf-8")

            generate_automation_scripts(
                client=None,
                suite_file=str(suite_file),
                plan_id=None,
                suite_id=None,
                project_dir=str(project_dir),
                namespace="QA.Regression.Automation.Tests.Generated",
                overwrite=True,
            )

            self.assertFalse(stale_file.exists())
            self.assertTrue(hand_written_file.exists())

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
            self.assertEqual(
                manifest["tests"][0]["fully_qualified_name"],
                "QA.Regression.Automation.Tests.Generated.Suite31681."
                "Tc31682LogInViewPointPortalTests.Tc31682_LogInViewPointPortal",
            )

    def test_generate_scripts_keeps_long_automated_test_names_within_ado_limit(self):
        long_title = "Verify " + "Unit Details data " * 25
        suite_export = f"""Plan ID: 30985
Suite ID: 31681
Test Cases: 1

1. [32123] {long_title}
   Step 1 Action: Open the Unit Details page
   Step 1 Expected: The page is displayed.
"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "QA.Regression.Automation"
            (project_dir / "Tests").mkdir(parents=True)
            suite_file = root / "suite_31681_testcases.txt"
            suite_file.write_text(suite_export, encoding="utf-8")

            result = generate_automation_scripts(
                client=None,
                suite_file=str(suite_file),
                plan_id=None,
                suite_id=None,
                project_dir=str(project_dir),
                namespace="QA.Regression.Automation.Tests.Generated",
                overwrite=False,
            )

            generated_test = result["generated"][0]
            fully_qualified_name = generated_test["fully_qualified_name"]
            generated_file = Path(generated_test["file_path"])
            content = generated_file.read_text(encoding="utf-8")

            self.assertLessEqual(len(fully_qualified_name), 255)
            self.assertIn(generated_test["class_name"], content)
            self.assertIn(generated_test["method_name"], content)
            self.assertIn(long_title.strip(), content)

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

    def test_generate_scripts_selects_api_parameter_values_by_environment(self):
        class FakeClient:
            def get_suite_test_cases(self, plan_id, suite_id):
                return [
                    {
                        "id": "31863",
                        "title": "Customer Details - Verify SiteDetails API in Customer Details page is working",
                        "state": "Design",
                        "steps": SITE_DETAILS_STEPS_XML,
                        "local_data_source": ENVIRONMENT_SITE_DETAILS_LOCAL_DATA_SOURCE,
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

            self.assertIn(
                'TestEnvironmentSettings.ResolveEnvironmentSpecificValue(',
                content,
            )
            self.assertIn(
                '["DEV"] = "/CustomerDetails/SiteDetails?rootId=301",',
                content,
            )
            self.assertIn(
                '["STAGE"] = "/CustomerDetails/SiteDetails?rootId=415",',
                content,
            )
            self.assertEqual(
                result["generated"][0]["parameter_rows"],
                [
                    {"Environment": "DEV", "rootID": "301"},
                    {"Environment": "STAGE", "rootID": "415"},
                ],
            )

    def test_generate_scripts_parses_environment_annotated_request_url(self):
        class FakeClient:
            def get_suite_test_cases(self, plan_id, suite_id):
                return [
                    {
                        "id": "31864",
                        "title": "Customer Details - Verify SegmentDetails API in Customer Details page is working",
                        "state": "Design",
                        "steps": SEGMENT_DETAILS_STEPS_XML,
                        "local_data_source": ENVIRONMENT_SEGMENT_DETAILS_LOCAL_DATA_SOURCE,
                    },
                    {
                        "id": "31868",
                        "title": "Unit Details - Verify GetControlUnit API in Unit Details page is working",
                        "state": "Design",
                        "steps": CONTROL_UNIT_STEPS_XML,
                        "local_data_source": ENVIRONMENT_CONTROL_UNIT_LOCAL_DATA_SOURCE,
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

            generated_by_id = {entry["test_case_id"]: entry for entry in result["generated"]}
            self.assertEqual(set(generated_by_id), {31864, 31868})
            for entry in generated_by_id.values():
                self.assertEqual(entry["strategy"], "authenticated-api-status")
                content = Path(entry["file_path"]).read_text(encoding="utf-8")
                self.assertIn("GoToAndCaptureApiResponseStatusAsync", content)

            segment_content = Path(generated_by_id[31864]["file_path"]).read_text(encoding="utf-8")
            self.assertIn(
                '["DEV"] = "/CustomerDetails/SegmentDetails?SiteId=356",',
                segment_content,
            )
            self.assertIn(
                '["STAGE"] = "/CustomerDetails/SegmentDetails?SiteId=851",',
                segment_content,
            )

            control_unit_content = Path(generated_by_id[31868]["file_path"]).read_text(encoding="utf-8")
            self.assertIn(
                '["DEV"] = "/UnitDetails/GetControlUnit?marketUnitId=3008",',
                control_unit_content,
            )

    def test_environment_parameter_can_also_be_used_in_api_url(self):
        paths = _extract_environment_specific_api_paths(
            "Verify API response status Request URL: "
            "baseURL/UnitDetails/GetControlUnit?environment='@environment'&marketUnitId='@marketunitID'",
            [
                {"environment": "prod", "marketunitID": "2"},
                {"environment": "dev", "marketunitID": "3008"},
            ],
        )

        self.assertEqual(
            paths,
            {
                "PROD": "/UnitDetails/GetControlUnit?environment=prod&marketUnitId=2",
                "DEV": "/UnitDetails/GetControlUnit?environment=dev&marketUnitId=3008",
            },
        )

    def test_generate_scripts_rejects_multiple_parameter_rows_without_environment(self):
        class FakeClient:
            def get_suite_test_cases(self, plan_id, suite_id):
                return [
                    {
                        "id": "31863",
                        "title": "Customer Details - Verify SiteDetails API in Customer Details page is working",
                        "state": "Design",
                        "steps": SITE_DETAILS_STEPS_XML,
                        "local_data_source": (
                            "<NewDataSet>"
                            "<Table1><rootID>301</rootID></Table1>"
                            "<Table1><rootID>415</rootID></Table1>"
                            "</NewDataSet>"
                        ),
                    }
                ]

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "QA.Regression.Automation"
            (project_dir / "Tests").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "Environment"):
                generate_automation_scripts(
                    client=FakeClient(),
                    suite_file=None,
                    plan_id=30985,
                    suite_id=31681,
                    project_dir=str(project_dir),
                    namespace="QA.Regression.Automation.Tests.Generated",
                    overwrite=False,
                )

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

    def test_generate_scripts_logs_in_and_navigates_for_authenticated_generic_case(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "QA.Regression.Automation"
            (project_dir / "Tests").mkdir(parents=True)
            suite_file = root / "suite_31681_testcases.txt"
            suite_file.write_text(REFRESH_EXPORT, encoding="utf-8")

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
            self.assertIn(
                'await workflowPage.GoToAsync(TestEnvironmentSettings.ResolveUrlForEnvironment("/UnitDetails/UnitDetail"));',
                content,
            )
            self.assertIn('await workflowPage.ClickButtonAsync("Refresh");', content)


if __name__ == "__main__":
    unittest.main()
