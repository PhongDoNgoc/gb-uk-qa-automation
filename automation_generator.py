from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from azure_serialization import parse_existing_steps, parse_local_data_source_rows

MAX_AUTOMATED_TEST_NAME_LENGTH = 255


@dataclass
class SuiteStep:
    index: int
    action: str
    expected: str


@dataclass
class SuiteTestCase:
    test_case_id: int
    title: str
    steps: list[SuiteStep]
    parameter_values: dict[str, str]
    parameter_rows: list[dict[str, str]]


@dataclass
class SuiteSource:
    plan_id: int | None
    suite_id: int | None
    test_cases: list[SuiteTestCase]


def generate_automation_scripts(
    *,
    client: Any | None,
    suite_file: str | None,
    plan_id: int | None,
    suite_id: int | None,
    project_dir: str | None,
    namespace: str,
    overwrite: bool,
) -> dict[str, Any]:
    source = _load_suite_source(client=client, suite_file=suite_file, plan_id=plan_id, suite_id=suite_id)
    resolved_plan_id = source.plan_id if source.plan_id is not None else plan_id
    resolved_suite_id = source.suite_id if source.suite_id is not None else suite_id

    if resolved_suite_id is None:
        raise ValueError("Suite ID is required. Provide --suite-id or include it in the suite export file.")

    project_path = _resolve_project_dir(project_dir)
    repo_root = Path(__file__).resolve().parent
    tests_dir = project_path / "Tests" / "Generated" / f"Suite{resolved_suite_id}"
    tests_dir.mkdir(parents=True, exist_ok=True)

    if overwrite:
        _delete_stale_generated_test_case_files(
            tests_dir,
            {test_case.test_case_id for test_case in source.test_cases},
        )

    suite_namespace = f"{namespace}.Suite{resolved_suite_id}"
    generated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for test_case in source.test_cases:
        class_name, method_name = _build_test_identifiers(test_case, suite_namespace)
        file_name = f"{class_name}.cs"
        target_path = tests_dir / file_name
        _delete_stale_test_case_files(tests_dir, test_case.test_case_id, target_path, overwrite=overwrite)
        strategy = _detect_strategy(test_case)
        content = _render_test_file(
            test_case=test_case,
            namespace=suite_namespace,
            class_name=class_name,
            method_name=method_name,
            strategy=strategy,
        )
        write_status = _write_file(target_path, content, overwrite=overwrite)

        entry = {
            "test_case_id": test_case.test_case_id,
            "title": test_case.title,
            "strategy": strategy,
            "class_name": class_name,
            "method_name": method_name,
            "fully_qualified_name": f"{suite_namespace}.{class_name}.{method_name}",
            "file_path": _portable_path(target_path, repo_root),
            "steps": [asdict(step) for step in test_case.steps],
            "parameter_values": test_case.parameter_values,
            "parameter_rows": test_case.parameter_rows,
        }

        if write_status == "skipped":
            skipped.append(entry)
        else:
            generated.append(entry)

    manifest = {
        "plan_id": resolved_plan_id,
        "suite_id": resolved_suite_id,
        "project_dir": _portable_path(project_path, repo_root),
        "assembly_name": f"{project_path.name}.dll",
        "namespace": suite_namespace,
        "generated_count": len(generated),
        "skipped_count": len(skipped),
        "tests": generated + skipped,
    }

    manifest_path = tests_dir / "automation-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")

    return {
        "plan_id": resolved_plan_id,
        "suite_id": resolved_suite_id,
        "project_dir": str(project_path),
        "output_dir": str(tests_dir),
        "manifest_path": str(manifest_path),
        "generated": generated,
        "skipped": skipped,
    }


def _load_suite_source(
    *,
    client: Any | None,
    suite_file: str | None,
    plan_id: int | None,
    suite_id: int | None,
) -> SuiteSource:
    if suite_file:
        raw = Path(suite_file).read_text(encoding="utf-8-sig")
        source = parse_suite_export_text(raw)
        if plan_id is not None and source.plan_id is not None and plan_id != source.plan_id:
            raise ValueError(f"Provided --plan-id {plan_id} does not match suite file plan ID {source.plan_id}.")
        if suite_id is not None and source.suite_id is not None and suite_id != source.suite_id:
            raise ValueError(f"Provided --suite-id {suite_id} does not match suite file suite ID {source.suite_id}.")
        return source

    if client is None:
        raise ValueError("Azure DevOps client is required when --suite-file is not provided.")
    if plan_id is None or suite_id is None:
        raise ValueError("Both --plan-id and --suite-id are required when reading test cases from Azure DevOps.")

    suite_cases = client.get_suite_test_cases(int(plan_id), int(suite_id))
    parsed_cases: list[SuiteTestCase] = []
    for suite_case in suite_cases:
        case_id = int(suite_case.get("id"))
        title = str(suite_case.get("title") or f"Test Case {case_id}").strip()
        parsed_steps = parse_existing_steps(suite_case.get("steps"))
        steps = [
            SuiteStep(
                index=index,
                action=str(step.get("text_action") or "").strip(),
                expected=str(step.get("text_expected") or "").strip(),
            )
            for index, step in enumerate(parsed_steps, start=1)
        ]
        parameter_rows = parse_local_data_source_rows(suite_case.get("local_data_source"))
        parsed_cases.append(
            SuiteTestCase(
                test_case_id=case_id,
                title=title,
                steps=steps,
                parameter_values=parameter_rows[0] if parameter_rows else {},
                parameter_rows=parameter_rows,
            )
        )

    if not parsed_cases:
        raise ValueError(f"No test cases were found in Azure Test Plan {plan_id}, Suite {suite_id}.")

    return SuiteSource(plan_id=plan_id, suite_id=suite_id, test_cases=parsed_cases)


def parse_suite_export_text(raw: str) -> SuiteSource:
    plan_id: int | None = None
    suite_id: int | None = None
    test_cases: list[SuiteTestCase] = []

    current_case: SuiteTestCase | None = None
    current_step: SuiteStep | None = None
    current_field: str | None = None

    for raw_line in raw.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            current_field = None
            continue

        plan_match = re.match(r"^Plan ID:\s*(\d+)$", stripped, re.I)
        if plan_match:
            plan_id = int(plan_match.group(1))
            current_field = None
            continue

        suite_match = re.match(r"^Suite ID:\s*(\d+)$", stripped, re.I)
        if suite_match:
            suite_id = int(suite_match.group(1))
            current_field = None
            continue

        case_match = re.match(r"^\d+\.\s*\[(\d+)\]\s*(.+)$", stripped)
        if case_match:
            current_case = SuiteTestCase(
                test_case_id=int(case_match.group(1)),
                title=case_match.group(2).strip(),
                steps=[],
                parameter_values={},
                parameter_rows=[],
            )
            test_cases.append(current_case)
            current_step = None
            current_field = None
            continue

        action_match = re.match(r"^Step\s+(\d+)\s+Action:\s*(.*)$", stripped, re.I)
        if action_match and current_case is not None:
            current_step = _get_or_create_step(current_case, int(action_match.group(1)))
            current_step.action = action_match.group(2).strip()
            current_field = "action"
            continue

        expected_match = re.match(r"^Step\s+(\d+)\s+Expected:\s*(.*)$", stripped, re.I)
        if expected_match and current_case is not None:
            current_step = _get_or_create_step(current_case, int(expected_match.group(1)))
            current_step.expected = expected_match.group(2).strip()
            current_field = "expected"
            continue

        if current_step is not None and current_field is not None:
            existing = getattr(current_step, current_field)
            combined = f"{existing} {stripped}".strip()
            setattr(current_step, current_field, combined)

    if not test_cases:
        raise ValueError("No test cases were found in the supplied suite export file.")

    return SuiteSource(plan_id=plan_id, suite_id=suite_id, test_cases=test_cases)


def _get_or_create_step(test_case: SuiteTestCase, index: int) -> SuiteStep:
    for step in test_case.steps:
        if step.index == index:
            return step
    step = SuiteStep(index=index, action="", expected="")
    test_case.steps.append(step)
    return step


def _resolve_project_dir(project_dir: str | None) -> Path:
    if project_dir:
        resolved = Path(project_dir)
    else:
        resolved = Path(__file__).resolve().parent / "QA.Regression.Automation"
    if not resolved.exists():
        raise FileNotFoundError(f"Automation project directory not found: {resolved}")
    return resolved


def _build_test_identifiers(test_case: SuiteTestCase, namespace: str) -> tuple[str, str]:
    title_suffix = _to_pascal_case(test_case.title)
    class_name = f"Tc{test_case.test_case_id}{title_suffix}Tests"
    method_name = f"Tc{test_case.test_case_id}_{title_suffix}"
    fully_qualified_name = f"{namespace}.{class_name}.{method_name}"
    if len(fully_qualified_name) <= MAX_AUTOMATED_TEST_NAME_LENGTH:
        return class_name, method_name

    class_name = f"Tc{test_case.test_case_id}Tests"
    method_prefix = f"Tc{test_case.test_case_id}_"
    title_suffix_length = (
        MAX_AUTOMATED_TEST_NAME_LENGTH
        - len(namespace)
        - len(class_name)
        - len(method_prefix)
        - 2
    )
    if title_suffix_length < 0:
        raise ValueError(
            f"Namespace is too long to associate generated tests with Azure DevOps "
            f"(maximum automated test name length is {MAX_AUTOMATED_TEST_NAME_LENGTH})."
        )

    method_name = f"{method_prefix}{title_suffix[:title_suffix_length]}"
    return class_name, method_name


def _to_pascal_case(value: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", value)
    if not parts:
        return "Generated"
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _detect_strategy(test_case: SuiteTestCase) -> str:
    all_text = " ".join(
        [test_case.title] + [step.action for step in test_case.steps] + [step.expected for step in test_case.steps]
    ).lower()
    if _is_authenticated_api_status_case(test_case):
        return "authenticated-api-status"
    if re.search(r"\bexport\b", test_case.title, re.I):
        return "generic"
    has_credentials = (
        ("username:" in all_text or "email address:" in all_text or "email:" in all_text)
        and "password:" in all_text
    )
    has_sign_in = "sign in" in all_text or "login" in all_text or "log in" in all_text
    if has_credentials and has_sign_in:
        return "login-failure" if _is_negative_login_case(test_case) else "login-success"
    return "generic"


def _render_test_file(
    *,
    test_case: SuiteTestCase,
    namespace: str,
    class_name: str,
    method_name: str,
    strategy: str,
) -> str:
    if strategy in {"login-success", "login-failure"}:
        body = _render_login_body(test_case)
    elif strategy == "authenticated-api-status":
        body = _render_authenticated_api_status_body(test_case)
    else:
        body = _render_generic_body(test_case)

    is_excel_export = re.search(r"\bexport\b", test_case.title, re.I) or any(
        re.search(r"\bexport\s+to\s+excel\b", step.action, re.I) for step in test_case.steps
    )
    if is_excel_export and 'await workflowPage.ClickButtonAsync("Export to Excel");' not in body:
        raise ValueError(
            f"Test case {test_case.test_case_id}: export action could not be generated. "
            "Use a step such as: Click on 'Export to Excel' button. "
            "Refusing to generate an export test without its download assertion."
        )

    lines = [
        "// <auto-generated />",
        "using System;",
        "using System.Collections.Generic;",
        "using System.Threading.Tasks;",
        "using NUnit.Framework;",
        "using QA.Regression.Automation.Pages;",
        "using QA.Regression.Automation.Utilities;",
        "",
        f"namespace {namespace};",
        "",
        "[TestFixture]",
        f"public class {class_name} : BaseTest",
        "{",
        "    [Test]",
        f'    [Property("TestCaseId", "{test_case.test_case_id}")]',
        f'    [Description("ADO #{test_case.test_case_id} - {_escape_csharp_string(test_case.title)}")]',
        f"    public async Task {method_name}()",
        "    {",
    ]
    lines.extend([f"        {line}" if line else "" for line in body])
    lines.extend(["    }", "}"])
    return "\n".join(lines) + "\n"


def _render_login_body(test_case: SuiteTestCase) -> list[str]:
    login_url = ""
    login_screen_text = "Log in screen is displayed."
    welcome_text = "Welcome to your ViewPoint energy portal"
    error_text = ""
    is_negative_case = _is_negative_login_case(test_case)

    for step in test_case.steps:
        if not login_url:
            login_url = _extract_first_url(step.action)
        if step.expected and login_screen_text == "Log in screen is displayed." and not _is_negative_login_expected(step.expected):
            if "log in screen" in step.expected.lower() or "sign in" in step.expected.lower():
                login_screen_text = step.expected
        if step.expected:
            quoted_text = _extract_text_after_keyword(step.expected, "Text")
            if quoted_text:
                if _is_negative_login_expected(step.expected):
                    error_text = quoted_text
                else:
                    welcome_text = quoted_text
            elif _is_negative_login_expected(step.expected):
                error_text = _normalize_negative_login_expected(step.expected)

    if is_negative_case:
        if not error_text:
            error_text = "The username or password provided in the request are invalid."
        lines = [
            f"var baseUrl = {_build_resolved_url_expression(login_url)};",
            'var username = TestEnvironmentSettings.ResolveOptionalEnvironmentVariable("VIEWPOINT_INVALID_USERNAME")',
            '    ?? TestEnvironmentSettings.RequireEnvironmentVariable("VIEWPOINT_USERNAME");',
            'var password = TestEnvironmentSettings.RequireEnvironmentVariable("VIEWPOINT_INVALID_PASSWORD");',
            "var loginPage = new LoginPage(Page);",
            "",
            "await loginPage.GoToAsync(baseUrl);",
            "Assert.That(await loginPage.IsLoginScreenDisplayedAsync(), Is.True,",
            f'    "{_escape_csharp_string(login_screen_text)}");',
            "",
            "await loginPage.LoginAsync(username, password);",
            "Assert.That(await loginPage.GetLoginErrorTextAsync(",
            f'    "{_escape_csharp_string(error_text)}"), Does.Contain(',
            f'    "{_escape_csharp_string(error_text)}"),',
            '    "The expected login error message was not displayed.");',
        ]
    else:
        lines = [
            f"var baseUrl = {_build_resolved_url_expression(login_url)};",
            'var username = TestEnvironmentSettings.RequireEnvironmentVariable("VIEWPOINT_USERNAME");',
            'var password = TestEnvironmentSettings.RequireEnvironmentVariable("VIEWPOINT_PASSWORD");',
            "var loginPage = new LoginPage(Page);",
            "",
            "await loginPage.GoToAsync(baseUrl);",
            "Assert.That(await loginPage.IsLoginScreenDisplayedAsync(), Is.True,",
            f'    "{_escape_csharp_string(login_screen_text)}");',
            "",
            "await loginPage.LoginAsync(username, password);",
            "Assert.That(await loginPage.GetWelcomeMessageTextAsync(), Does.Contain(",
            f'    "{_escape_csharp_string(welcome_text)}"),',
            '    "The expected home page welcome message was not displayed after sign in.");',
        ]
    return lines


def _render_generic_body(test_case: SuiteTestCase) -> list[str]:
    lines = ["var workflowPage = new GeneratedWorkflowPage(Page);"]
    requires_authenticated_session = _has_logged_in_precondition(test_case)

    username, password = _extract_credentials(" ".join(step.action for step in test_case.steps))
    if username:
        lines.extend(
            [
                "",
                'var username = TestEnvironmentSettings.RequireEnvironmentVariable("VIEWPOINT_USERNAME");',
            ]
        )
    if password:
        lines.extend(
            [
                'var password = TestEnvironmentSettings.RequireEnvironmentVariable("VIEWPOINT_PASSWORD");',
            ]
        )

    if requires_authenticated_session:
        lines = [
            "var baseUrl = TestEnvironmentSettings.ResolveBaseUrlForEnvironment();",
            'var username = TestEnvironmentSettings.RequireEnvironmentVariable("VIEWPOINT_USERNAME");',
            'var password = TestEnvironmentSettings.RequireEnvironmentVariable("VIEWPOINT_PASSWORD");',
            "var loginPage = new LoginPage(Page);",
            "var workflowPage = new GeneratedWorkflowPage(Page);",
            "",
            "await loginPage.GoToAsync(baseUrl);",
            "Assert.That(await loginPage.IsLoginScreenDisplayedAsync(), Is.True,",
            '    "Log in screen is displayed.");',
            "",
            "await loginPage.LoginAsync(username, password);",
            "Assert.That(await loginPage.GetWelcomeMessageTextAsync(), Does.Contain(",
            '    "Welcome to your ViewPoint energy portal"),',
            '    "The expected home page welcome message was not displayed after sign in.");',
        ]

    for step in test_case.steps:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"// Step {step.index}: {_escape_csharp_string(_sanitize_action_text_for_comment(step.action))}")
        url = _extract_first_url(step.action)
        menu_item = _extract_navigation_menu_item(step.action)
        menu_argument = f', "{_escape_csharp_string(menu_item)}"' if menu_item else ""
        if url:
            lines.append(f"await workflowPage.GoToAsync({_build_resolved_url_expression(url)}{menu_argument});")
        else:
            baseurl_reference = _extract_baseurl_reference(
                step.action,
                label="URL",
                keep_query=True,
                parameter_values=test_case.parameter_values,
            )
            if baseurl_reference:
                lines.append(
                    f'await workflowPage.GoToAsync(TestEnvironmentSettings.ResolveUrlForEnvironment("{_escape_csharp_string(baseurl_reference)}"){menu_argument});'
                )

        action_lower = step.action.lower()
        if (
            ("username:" in action_lower or "email address:" in action_lower or "email:" in action_lower)
            and "password:" in action_lower
        ):
            lines.append("await workflowPage.FillCredentialInputsAsync(username, password);")

        click_target = _extract_click_target(step.action)
        selection = _extract_selection(step.action)
        if selection:
            label, value = selection
            lines.append(
                f'await workflowPage.SelectOptionAsync("{_escape_csharp_string(label)}", '
                f"{_build_selection_value_expression(test_case, step.index, label, value)});"
            )
        elif _looks_like_selection_step(step.action):
            raise ValueError(
                f"Test case {test_case.test_case_id} step {step.index}: selector step could not be generated: "
                f"'{step.action}'. Use a step such as: In 'Country' selector, select @country."
            )
        elif click_target:
            lines.append(f'await workflowPage.ClickButtonAsync("{_escape_csharp_string(click_target)}");')

        expected_texts = _extract_expected_texts(step.expected)
        for expected in expected_texts:
            lines.append(f'await workflowPage.AssertTextVisibleAsync("{_escape_csharp_string(expected)}");')

        if len(lines) > 0 and lines[-1].startswith("// Step"):
            lines.append(f'// TODO: Translate expected result manually: {_escape_csharp_string(step.expected)}')

    return lines


def _render_authenticated_api_status_body(test_case: SuiteTestCase) -> list[str]:
    has_environment_rows = _has_environment_parameter_rows(test_case.parameter_rows)
    if len(test_case.parameter_rows) > 1 and not has_environment_rows:
        raise ValueError(
            f"Test case {test_case.test_case_id} has multiple parameter rows but no 'Environment' column."
        )

    page_path = ""
    api_path_fragment = ""
    api_path_values_by_environment: dict[str, str] = {}
    expected_status_code = 200

    for step in test_case.steps:
        if not page_path:
            page_path = _extract_baseurl_reference(
                step.action,
                label="URL",
                keep_query=True,
                parameter_values=test_case.parameter_values,
            )

        if not api_path_fragment:
            api_path_fragment = _extract_baseurl_reference(
                step.action,
                label="Request URL",
                keep_query=True,
                parameter_values=test_case.parameter_values,
            )
            if api_path_fragment and has_environment_rows:
                api_path_values_by_environment = _extract_environment_specific_api_paths(
                    step.action,
                    test_case.parameter_rows,
                )
        if step.expected:
            parsed_status_code = _extract_expected_status_code(step.expected)
            if parsed_status_code is not None:
                expected_status_code = parsed_status_code

    if not page_path:
        raise ValueError(
            f"Test case {test_case.test_case_id} looks like an API status check but does not contain a page URL."
        )
    if not api_path_fragment:
        raise ValueError(
            f"Test case {test_case.test_case_id} looks like an API status check but does not contain a request URL."
        )

    api_display_name = _extract_api_display_name(test_case, api_path_fragment)
    lines = [
        "var baseUrl = TestEnvironmentSettings.ResolveBaseUrlForEnvironment();",
        f'var targetPageUrl = TestEnvironmentSettings.ResolveUrlForEnvironment("{_escape_csharp_string(page_path)}");',
    ]
    if api_path_values_by_environment:
        lines.extend(
            [
                "var apiPathFragment = TestEnvironmentSettings.ResolveEnvironmentSpecificValue(",
                "    new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)",
                "    {",
                *[
                    f'        ["{_escape_csharp_string(environment)}"] = "{_escape_csharp_string(path)}",'
                    for environment, path in sorted(api_path_values_by_environment.items())
                ],
                "    });",
            ]
        )
    else:
        lines.append(f'var apiPathFragment = "{_escape_csharp_string(api_path_fragment)}";')
    lines.extend(
        [
            f"const int expectedStatusCode = {expected_status_code};",
            'var username = TestEnvironmentSettings.RequireEnvironmentVariable("VIEWPOINT_USERNAME");',
            'var password = TestEnvironmentSettings.RequireEnvironmentVariable("VIEWPOINT_PASSWORD");',
            "var loginPage = new LoginPage(Page);",
            "var workflowPage = new GeneratedWorkflowPage(Page);",
            "",
            "await loginPage.GoToAsync(baseUrl);",
            "Assert.That(await loginPage.IsLoginScreenDisplayedAsync(), Is.True,",
            '    "Log in screen is displayed.");',
            "",
            "await loginPage.LoginAsync(username, password);",
            "Assert.That(await loginPage.GetWelcomeMessageTextAsync(), Does.Contain(",
            '    "Welcome to your ViewPoint energy portal"),',
            '    "The expected home page welcome message was not displayed after sign in.");',
            "",
            "var actualStatusCode = await workflowPage.GoToAndCaptureApiResponseStatusAsync(targetPageUrl, apiPathFragment);",
            "Assert.That(actualStatusCode, Is.EqualTo(expectedStatusCode),",
            f'    "Expected {api_display_name} to return HTTP status {expected_status_code} after sign in.");',
        ]
    )
    return lines


def _has_environment_parameter_rows(parameter_rows: list[dict[str, str]]) -> bool:
    return any(
        any(name.casefold() == "environment" for name in row)
        for row in parameter_rows
    )


def _extract_environment_specific_api_paths(
    action: str,
    parameter_rows: list[dict[str, str]],
) -> dict[str, str]:
    template = _extract_baseurl_reference(
        action,
        label="Request URL",
        keep_query=True,
        preserve_unresolved_parameters=True,
    )
    if not template:
        raise ValueError("Environment parameter rows require a valid 'Request URL' in the test case.")

    placeholders = {
        match.casefold()
        for match in re.findall(r"@([A-Za-z0-9_]+)", template)
    }
    paths_by_environment: dict[str, str] = {}
    for row in parameter_rows:
        environment_value = _get_case_insensitive_value(row, "Environment")
        if not environment_value:
            raise ValueError("Environment parameter rows must include a non-empty 'Environment' value.")

        environment = re.sub(r"[^A-Za-z0-9]+", "_", environment_value.strip()).strip("_").upper()
        if not environment:
            raise ValueError(f"Invalid environment value '{environment_value}' in parameter data.")
        if environment in paths_by_environment:
            raise ValueError(f"Duplicate '{environment}' environment row in test case parameter data.")

        values = dict(row)
        available_names = {name.casefold() for name in values}
        missing_names = sorted(placeholders - available_names)
        if missing_names:
            raise ValueError(
                f"Environment '{environment}' parameter row is missing values for: {', '.join(missing_names)}."
            )

        resolved_path = _replace_parameter_placeholders(template, values)
        unresolved_names = re.findall(r"@([A-Za-z0-9_]+)", resolved_path)
        if unresolved_names:
            raise ValueError(
                f"Environment '{environment}' parameter row did not resolve: {', '.join(unresolved_names)}."
            )
        paths_by_environment[environment] = resolved_path

    if not paths_by_environment:
        raise ValueError("No environment parameter rows were found for the API request URL.")
    return paths_by_environment


def _get_case_insensitive_value(values: dict[str, str], name: str) -> str | None:
    return next(
        (value for key, value in values.items() if key.casefold() == name.casefold()),
        None,
    )


def _extract_first_url(value: str) -> str:
    match = re.search(r"https?://[^\s)]+", value)
    return match.group(0).rstrip(".,") if match else ""


def _sanitize_action_text_for_comment(action: str) -> str:
    return re.sub(
        r"https?://[^\s)]+",
        lambda match: _extract_relative_url(match.group(0)),
        action,
    )


def _build_resolved_url_expression(source_url: str) -> str:
    relative_url = _extract_relative_url(source_url)
    if relative_url in ("", "/"):
        return "TestEnvironmentSettings.ResolveBaseUrlForEnvironment()"

    return f'TestEnvironmentSettings.ResolveUrlForEnvironment("{_escape_csharp_string(relative_url)}")'


def _extract_relative_url(source_url: str) -> str:
    if not source_url:
        return "/"

    parsed = urlsplit(source_url)
    if not parsed.scheme or not parsed.netloc:
        return source_url

    path = parsed.path or "/"
    return urlunsplit(("", "", path, parsed.query, parsed.fragment))


def _extract_baseurl_reference(
    value: str,
    *,
    label: str,
    keep_query: bool,
    parameter_values: dict[str, str] | None = None,
    preserve_unresolved_parameters: bool = False,
) -> str:
    match = re.search(
        rf"{re.escape(label)}(?:\s*@environment)?\s*:\s*(baseurl/.+)$",
        value,
        re.I,
    )
    if not match:
        return ""

    normalized = match.group(1).strip()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("baseURL", "baseurl").replace("'", "")
    normalized = _replace_parameter_placeholders(normalized, parameter_values or {})
    normalized = re.sub(r"\(.*?\)$", "", normalized).strip()
    normalized = re.sub(r"^baseurl", "", normalized, flags=re.I).strip()

    if not normalized:
        return ""

    if not normalized.startswith("/"):
        normalized = f"/{normalized}"

    normalized = _normalize_embedded_absolute_reference(normalized)

    if not keep_query or ("@" in normalized and not preserve_unresolved_parameters):
        normalized = normalized.split("?", 1)[0]

    return normalized


def _replace_parameter_placeholders(value: str, parameter_values: dict[str, str]) -> str:
    if not parameter_values:
        return value

    resolved = value
    for name, replacement in parameter_values.items():
        resolved = re.sub(rf"@{re.escape(name)}\b", replacement, resolved, flags=re.I)
    return resolved


def _normalize_embedded_absolute_reference(value: str) -> str:
    match = re.match(r"^/https?://([^/]+)(/.*)?$", value, re.I)
    if not match:
        return value

    host_segment = _normalize_embedded_host_segment(match.group(1))
    path_segment = match.group(2) or "/"
    return f"/{host_segment}{path_segment}"


def _normalize_embedded_host_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", value).strip()
    lowered = cleaned.lower().replace(" ", "")
    if lowered.endswith("details") and len(lowered) > len("details"):
        prefix = lowered[: -len("details")]
        return f"{_to_pascal_case(prefix)}Details"
    return _to_pascal_case(cleaned)


def _extract_credentials(value: str) -> tuple[str, str]:
    username_match = re.search(
        r"(?:username|email\s*address|email):\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})",
        value,
        re.I,
    )
    password_match = re.search(r"password:\s*([^\s]+)", value, re.I)
    username = username_match.group(1).strip(".,;") if username_match else ""
    password = password_match.group(1).strip(".,;") if password_match else ""
    return username, password


def _extract_click_target(value: str) -> str:
    match = re.search(r"click\s+(?:on\s+)?['\"\u2018\u2019\u201c\u201d]([^'\"\u2018\u2019\u201c\u201d]+)['\"\u2018\u2019\u201c\u201d]", value, re.I)
    if match:
        target = match.group(1).strip()
    else:
        match = re.search(r"click\s+(?:on\s+)?([A-Za-z0-9 _-]+?)(?:\s+button)?[.!]?\s*$", value, re.I)
        target = match.group(1).strip() if match else ""
    if re.fullmatch(r"export\s+to\s+excel", target, re.I):
        return "Export to Excel"
    return target


def _extract_navigation_menu_item(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    match = re.search(
        r"\bclick\s+(?:on\s+|to\s+)+(?:the\s+)?['\"\u2018\u2019\u201c\u201d]?(?P<item>[A-Za-z0-9 &/_-]+?)"
        r"['\"\u2018\u2019\u201c\u201d]?\s+(?:page\s+|menu\s+|link\s+)?(?:URL|link)\b",
        text,
        re.I,
    )
    return match.group("item").strip() if match else ""


_QUOTE = "'\"\u2018\u2019\u201c\u201d"
_SELECTOR_NOUN = r"(?:selector|dropdown|drop-down|drop\s+down|filter|picker)"
_SELECTION_PATTERNS = (
    re.compile(
        rf"\bin\s+(?:the\s+)?(?:[{_QUOTE}](?P<quoted_label>[^{_QUOTE}]+)[{_QUOTE}]|(?P<label>[A-Za-z0-9 /_-]+?))"
        rf"\s+{_SELECTOR_NOUN}\s*,?\s*(?:select|choose)\s+(?:an?\s+|the\s+)?(?P<value>.+?)\s*[.!]?\s*$",
        re.I,
    ),
    re.compile(
        rf"\b(?:select|choose)\s+(?:an?\s+|the\s+)?(?P<value>.+?)\s+(?:in|from)\s+(?:the\s+)?"
        rf"(?:[{_QUOTE}](?P<quoted_label>[^{_QUOTE}]+)[{_QUOTE}]|(?P<label>[A-Za-z0-9 /_-]+?))"
        rf"\s+{_SELECTOR_NOUN}\s*[.!]?\s*$",
        re.I,
    ),
)


def _extract_selection(value: str) -> tuple[str, str] | None:
    text = re.sub(r"\s+", " ", value).strip()
    for pattern in _SELECTION_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        label = (match.group("quoted_label") or match.group("label") or "").strip()
        selected = match.group("value").strip().strip(_QUOTE).strip()
        if label and selected:
            return label, selected
    return None


def _looks_like_selection_step(value: str) -> bool:
    return (
        re.search(r"\b(?:select|choose)\b", value, re.I) is not None
        and re.search(rf"\b{_SELECTOR_NOUN}\b", value, re.I) is not None
    )


def _build_selection_value_expression(test_case: SuiteTestCase, step_index: int, label: str, value: str) -> str:
    parameter = re.fullmatch(r"@([A-Za-z0-9_]+)", value)
    if not parameter:
        return f'"{_escape_csharp_string(value)}"'

    name = parameter.group(1)
    context = f"Test case {test_case.test_case_id} step {step_index} ('{label}' selector)"
    if not _has_environment_parameter_rows(test_case.parameter_rows):
        resolved = _get_case_insensitive_value(test_case.parameter_values, name)
        if not resolved:
            raise ValueError(f"{context}: parameter '@{name}' has no value in the test case parameter data.")
        return f'"{_escape_csharp_string(resolved)}"'

    values_by_environment: dict[str, str] = {}
    for row in test_case.parameter_rows:
        environment_value = _get_case_insensitive_value(row, "Environment") or ""
        environment = re.sub(r"[^A-Za-z0-9]+", "_", environment_value.strip()).strip("_").upper()
        if not environment:
            raise ValueError(f"{context}: parameter rows must include a non-empty 'Environment' value.")
        resolved = (_get_case_insensitive_value(row, name) or "").strip()
        if resolved:
            values_by_environment[environment] = resolved

    if not values_by_environment:
        raise ValueError(f"{context}: parameter '@{name}' has no value for any environment in the test case parameter data.")

    entries = " ".join(
        f'["{_escape_csharp_string(environment)}"] = "{_escape_csharp_string(resolved)}",'
        for environment, resolved in sorted(values_by_environment.items())
    )
    return (
        "TestEnvironmentSettings.ResolveEnvironmentSpecificValue("
        f"new Dictionary<string, string> {{ {entries} }})"
    )


def _extract_expected_texts(value: str) -> list[str]:
    texts: list[str] = []
    quoted = re.findall(r"['\"]([^'\"]{2,})['\"]", value)
    texts.extend(text.strip() for text in quoted if text.strip())

    after_text = _extract_text_after_keyword(value, "Text")
    if after_text and after_text not in texts:
        texts.append(after_text)

    return texts


def _extract_text_after_keyword(value: str, keyword: str) -> str:
    match = re.search(rf"{re.escape(keyword)}\s+['\"]([^'\"]+)['\"]", value, re.I)
    return match.group(1).strip() if match else ""


def _escape_csharp_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _extract_expected_status_code(value: str) -> int | None:
    match = re.search(r"status\s+code\s+should\s+be\s+(\d{3})", value, re.I)
    if not match:
        return None
    return int(match.group(1))


def _extract_api_display_name(test_case: SuiteTestCase, api_path_fragment: str) -> str:
    title_match = re.search(r"verify\s+(.+?)\s+api", test_case.title, re.I)
    if title_match:
        return title_match.group(1).strip()

    path_segment = api_path_fragment.strip("/").split("/")[-1]
    return path_segment or "the API"


def _delete_stale_test_case_files(tests_dir: Path, test_case_id: int, target_path: Path, *, overwrite: bool) -> None:
    stale_paths = [path for path in tests_dir.glob(f"Tc{test_case_id}*.cs") if path.resolve() != target_path.resolve()]
    if not stale_paths:
        return
    if not overwrite:
        stale_list = ", ".join(str(path.name) for path in stale_paths)
        raise FileExistsError(
            f"Refusing to replace stale generated files without --overwrite for test case {test_case_id}: {stale_list}"
        )
    for stale_path in stale_paths:
        stale_path.unlink()


def _delete_stale_generated_test_case_files(tests_dir: Path, current_test_case_ids: set[int]) -> None:
    for generated_path in tests_dir.glob("Tc*.cs"):
        match = re.match(r"^Tc(\d+)", generated_path.name)
        if not match or int(match.group(1)) in current_test_case_ids:
            continue
        if generated_path.read_text(encoding="utf-8").startswith("// <auto-generated />"):
            generated_path.unlink()


def _is_negative_login_case(test_case: SuiteTestCase) -> bool:
    return any(_is_negative_login_expected(step.expected) for step in test_case.steps) or (
        "cannot log in" in test_case.title.lower()
        or "cannot login" in test_case.title.lower()
        or "wrong credential" in test_case.title.lower()
        or "invalid credential" in test_case.title.lower()
    )


def _is_authenticated_api_status_case(test_case: SuiteTestCase) -> bool:
    all_text = " ".join(
        [test_case.title] + [step.action for step in test_case.steps] + [step.expected for step in test_case.steps]
    ).lower()
    return (
        "precondition:" in all_text
        and "logged in viewpoint portal" in all_text
        and "response status" in all_text
        and "status code should be" in all_text
        and re.search(r"\brequest\s+url(?:\s*@environment)?\s*:", all_text) is not None
    )


def _has_logged_in_precondition(test_case: SuiteTestCase) -> bool:
    all_text = " ".join(
        [step.action for step in test_case.steps] + [step.expected for step in test_case.steps]
    ).lower()
    return "precondition:" in all_text and "logged in viewpoint portal" in all_text


def _is_negative_login_expected(value: str) -> bool:
    lowered = (value or "").lower()
    return (
        "cannot be logged in" in lowered
        or "cannot log in" in lowered
        or "cannot login" in lowered
        or "invalid" in lowered
        or "error" in lowered
    )


def _normalize_negative_login_expected(value: str) -> str:
    lowered = re.sub(r"\s+", " ", (value or "")).strip()
    marker = "text"
    index = lowered.lower().find(marker)
    if index >= 0:
        lowered = lowered[index + len(marker):].strip(" :.-")
    lowered = re.sub(r"^['\"]+|['\"]+$", "", lowered).strip()
    if " is displayed" in lowered.lower():
        lowered = re.sub(r"\s+is displayed.*$", "", lowered, flags=re.I).strip()
    return lowered or "The username or password provided in the request are invalid."


def _write_file(path: Path, content: str, *, overwrite: bool) -> str:
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == content:
            return "skipped"
        if not overwrite:
            raise FileExistsError(
                f"Refusing to overwrite existing generated file without --overwrite: {path}"
            )
    path.write_text(content, encoding="utf-8")
    return "generated"


def _portable_path(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)
