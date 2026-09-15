from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from azure_serialization import parse_existing_steps


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

    suite_namespace = f"{namespace}.Suite{resolved_suite_id}"
    generated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for test_case in source.test_cases:
        class_name = _build_class_name(test_case)
        method_name = _build_method_name(test_case)
        file_name = f"{class_name}.cs"
        target_path = tests_dir / file_name
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
        parsed_cases.append(SuiteTestCase(test_case_id=case_id, title=title, steps=steps))

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
            current_case = SuiteTestCase(test_case_id=int(case_match.group(1)), title=case_match.group(2).strip(), steps=[])
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


def _build_class_name(test_case: SuiteTestCase) -> str:
    return f"Tc{test_case.test_case_id}{_to_pascal_case(test_case.title)}Tests"


def _build_method_name(test_case: SuiteTestCase) -> str:
    return f"Tc{test_case.test_case_id}_{_to_pascal_case(test_case.title)}"


def _to_pascal_case(value: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", value)
    if not parts:
        return "Generated"
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _detect_strategy(test_case: SuiteTestCase) -> str:
    all_text = " ".join(
        [test_case.title] + [step.action for step in test_case.steps] + [step.expected for step in test_case.steps]
    ).lower()
    has_credentials = (
        ("username:" in all_text or "email address:" in all_text or "email:" in all_text)
        and "password:" in all_text
    )
    has_sign_in = "sign in" in all_text or "login" in all_text or "log in" in all_text
    return "login" if has_credentials and has_sign_in else "generic"


def _render_test_file(
    *,
    test_case: SuiteTestCase,
    namespace: str,
    class_name: str,
    method_name: str,
    strategy: str,
) -> str:
    if strategy == "login":
        body = _render_login_body(test_case)
    else:
        body = _render_generic_body(test_case)

    lines = [
        "// <auto-generated />",
        "using System;",
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
    username = ""
    password = ""

    for step in test_case.steps:
        if not login_url:
            login_url = _extract_first_url(step.action)
        if step.expected and login_screen_text == "Log in screen is displayed.":
            if "log in screen" in step.expected.lower() or "sign in" in step.expected.lower():
                login_screen_text = step.expected
        if step.expected:
            quoted_text = _extract_text_after_keyword(step.expected, "Text")
            if quoted_text:
                welcome_text = quoted_text
        step_username, step_password = _extract_credentials(step.action)
        username = username or step_username
        password = password or step_password

    lines = [
        'var baseUrl = Environment.GetEnvironmentVariable("VIEWPOINT_BASE_URL")',
        f'    ?? "{_escape_csharp_string(login_url)}";',
        'var username = Environment.GetEnvironmentVariable("VIEWPOINT_USERNAME")',
        f'    ?? "{_escape_csharp_string(username)}";',
        'var password = Environment.GetEnvironmentVariable("VIEWPOINT_PASSWORD")',
        f'    ?? "{_escape_csharp_string(password)}";',
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

    username, password = _extract_credentials(" ".join(step.action for step in test_case.steps))
    if username:
        lines.extend(
            [
                "",
                'var username = Environment.GetEnvironmentVariable("VIEWPOINT_USERNAME")',
                f'    ?? "{_escape_csharp_string(username)}";',
            ]
        )
    if password:
        lines.extend(
            [
                'var password = Environment.GetEnvironmentVariable("VIEWPOINT_PASSWORD")',
                f'    ?? "{_escape_csharp_string(password)}";',
            ]
        )

    for step in test_case.steps:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"// Step {step.index}: {_escape_csharp_string(step.action)}")
        url = _extract_first_url(step.action)
        if url:
            lines.append(f'await workflowPage.GoToAsync("{_escape_csharp_string(url)}");')

        action_lower = step.action.lower()
        if (
            ("username:" in action_lower or "email address:" in action_lower or "email:" in action_lower)
            and "password:" in action_lower
        ):
            lines.append("await workflowPage.FillCredentialInputsAsync(username, password);")

        click_target = _extract_click_target(step.action)
        if click_target:
            lines.append(f'await workflowPage.ClickButtonAsync("{_escape_csharp_string(click_target)}");')

        expected_texts = _extract_expected_texts(step.expected)
        for expected in expected_texts:
            lines.append(f'await workflowPage.AssertTextVisibleAsync("{_escape_csharp_string(expected)}");')

        if len(lines) > 0 and lines[-1].startswith("// Step"):
            lines.append(f'// TODO: Translate expected result manually: {_escape_csharp_string(step.expected)}')

    return lines


def _extract_first_url(value: str) -> str:
    match = re.search(r"https?://[^\s)]+", value)
    return match.group(0).rstrip(".,") if match else ""


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
    match = re.search(r"click\s+['\"]([^'\"]+)['\"]", value, re.I)
    if match:
        return match.group(1).strip()
    match = re.search(r"click\s+([A-Za-z0-9 _-]+)$", value, re.I)
    return match.group(1).strip() if match else ""


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
