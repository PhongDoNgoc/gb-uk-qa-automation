# Azure DevOps QA Test Case Generator

## Canonical Workflow

1. Sprint review

```bash
python main.py sprint-review --sprint "Sprint 115"
```

2. Build review artifact

```bash
python main.py review --work-item 12345
```

3. Build reconciliation artifact

```bash
python main.py reconcile --work-item 12345
```

4. Approve for apply

```bash
python main.py approve --work-item 12345
```

5. Apply dry run

```bash
python main.py apply --work-item 12345 --dry-run
```

6. Apply real run

```bash
python main.py apply --work-item 12345
```

7. Verify execution readiness

```bash
python main.py verify --work-item 12345
```

8. Generate Playwright automation scripts from an exported suite file

```bash
python main.py generate-scripts --suite-file .\samples\suite_31681_testcases.txt
```

9. Generate Playwright automation scripts directly from Azure Test Plans

```bash
python main.py generate-scripts --plan-id <PLAN_ID> --suite-id <SUITE_ID> --overwrite
```

10. Generate and associate in one step

```bash
python main.py generate-scripts --plan-id <PLAN_ID> --suite-id <SUITE_ID> --overwrite --associate
```

11. Run the repeatable suite-update flow with one command

```powershell
.\update-azure-test-suite.ps1 -PlanId <PLAN_ID> -SuiteId <SUITE_ID>
```

To generate, validate, commit, and push in one run:

```powershell
.\update-azure-test-suite.ps1 -PlanId <PLAN_ID> -SuiteId <SUITE_ID> -Commit -Push
```

12. Execute the generated automation locally

```bash
dotnet test .\QA.Regression.Automation\QA.Regression.Automation.csproj --logger trx
```

13. Push the generated automation mapping back to Azure Test Cases

```bash
python main.py associate-scripts --manifest .\QA.Regression.Automation\Tests\Generated\Suite31681\automation-manifest.json
```

14. Optionally choose the target application environment before a local test run

```powershell
$env:TEST_TARGET_ENV="DEV"
$env:VIEWPOINT_BASE_URL_DEV="https://your-dev-url/"
dotnet test .\QA.Regression.Automation\QA.Regression.Automation.csproj --logger trx
```

## Sprint Review Options

- `--state` comma-separated Azure states
- `--status` comma-separated QA status filter
- `--include-child-tasks` include child tasks in output
- `--debug` verbose diagnostics
- `--json-out` write JSON summary

Example:

```bash
python main.py sprint-review --sprint "Sprint 115" --state Active --status READY --include-child-tasks --debug --json-out reviews/sprint_115_summary.json
```

## Command Compatibility

- `review-v2` and `review-v3` are deprecated aliases to `review`.
- Legacy `reconcile.py` is a compatibility wrapper to `main.py reconcile`.

## Architecture

- `main.py`: CLI parsing and command dispatch only
- `azure_client.py`: Azure REST client and endpoint wrappers
- `pipeline.py`: requirement parsing, atomic decomposition, scenario grouping, and test generation
- `automation_generator.py`: suite export parsing plus Playwright/NUnit test generation
- `reconciliation.py`: review orchestration, reconcile output, sprint-review projection, verify output, and approval metadata
- `apply_service.py`: unified apply flow with dry-run and execution readiness verification
- `validators.py`: apply and execution readiness validation
- `models.py`: typed dataclasses used across the system
- `config.py`: environment loading and logging setup

## Integrated Folder Structure

The unified layout now keeps both the Azure DevOps generator and the Playwright automation project under one root:

```text
azure-testcase-generator/
├── main.py
├── automation_generator.py
├── automation_association.py
├── azure_client.py
├── pipeline.py
├── tests/
├── samples/
│   └── suite_31681_testcases.txt
└── QA.Regression.Automation/
    ├── QA.Regression.Automation.csproj
    ├── azure-pipelines.yml
    ├── azure-testplans-run.yml
    ├── Pages/
    ├── Tests/
    └── Utilities/
```

## Automation Script Flow

The repository now supports a full manual-to-automation handoff flow that matches the implementation plan:

1. Build or curate test cases in Azure Test Plans.
2. Export a suite to text, or read the suite directly from Azure DevOps.
3. Run `generate-scripts` to create NUnit + Playwright tests under `.\QA.Regression.Automation\Tests\Generated`.
4. Optionally add `--associate` to update the Azure Test Case automation fields in the same run.
5. Review the generated `automation-manifest.json` for the ADO test case to automated test mapping.
6. If you did not use `--associate`, run `associate-scripts` to stamp the Azure Test Case automation fields from the manifest.
7. Run the tests locally with `dotnet test`.
8. Publish and execute them in Azure DevOps through the pipeline in `.\QA.Regression.Automation\azure-pipelines.yml`.

## Easiest Repeatable Flow

For future suite updates, the fastest local command is:

```powershell
.\update-azure-test-suite.ps1 -PlanId <PLAN_ID> -SuiteId <SUITE_ID>
```

This script:

- loads values from `.env` if present
- regenerates the suite automation
- overwrites existing Azure automated associations when they changed
- runs the Python validation tests
- runs the .NET automation tests

Optional flags:

- `-TargetEnvironment PROD|DEV|STAGE`
- `-Commit`
- `-Push`
- `-SkipPythonTests`
- `-SkipDotNetTests`

Example:

```powershell
.\update-azure-test-suite.ps1 -PlanId 30985 -SuiteId 31681 -Commit -Push
```

## Pipeline Files

- `.\QA.Regression.Automation\azure-pipelines.yml`: standard CI build and regression execution
- `.\QA.Regression.Automation\azure-testplans-run.yml`: Azure Test Plans-triggered execution using plan, suite, and configuration inputs

## Environment Selection

Generated tests now resolve URLs from a selected target environment instead of being locked to a single hard-coded base URL.

- Select the environment with `TEST_TARGET_ENV`
- Provide the matching URL variable as `VIEWPOINT_BASE_URL_<ENVIRONMENT_NAME>`
- If `TEST_TARGET_ENV` is not set, tests default to `PROD`

Examples:

- `TEST_TARGET_ENV=PROD` uses `VIEWPOINT_BASE_URL_PROD`
- `TEST_TARGET_ENV=DEV` uses `VIEWPOINT_BASE_URL_DEV`
- `TEST_TARGET_ENV=STAGE` uses `VIEWPOINT_BASE_URL_STAGE`

The CI and Test Plans YAML files now expose `targetEnvironment` as a pipeline parameter, so the same pipelines can run against different environments without editing code.

You can copy [.env.example](</C:/Users/lan.le/OneDrive - Endeco-Technologies/Desktop/AI Automated Automation Script/azure-testcase-generator/.env.example>) to `.env` for local setup and fill in the environment URLs you use.

## Hosted vs Self-Hosted Agent Selection

The pipelines now also expose:

- `agentPoolMode`
- `selfHostedPoolName`

Supported modes:

- `Auto`: use Microsoft-hosted agents for `PROD`, use the self-hosted pool for non-`PROD` environments
- `Hosted`: always use Microsoft-hosted `windows-latest`
- `SelfHosted`: always use the selected self-hosted pool

Default behavior:

- `PROD` + `Auto` -> hosted agent
- `DEV` + `Auto` -> self-hosted pool
- `STAGE` + `Auto` -> self-hosted pool

If you later want to run `PROD` on your self-hosted pool as well, choose:

- `agentPoolMode = SelfHosted`

Use `Hosted` only when the target environment is reachable from Azure-hosted agents.

## Azure Variable Checklist

Create these Azure Pipeline variables before running across multiple environments:

- `VIEWPOINT_USERNAME`
- `VIEWPOINT_PASSWORD`
- `VIEWPOINT_BASE_URL_PROD`
- `VIEWPOINT_BASE_URL_DEV`
- `VIEWPOINT_BASE_URL_STAGE`

Optional later:

- `VIEWPOINT_BASE_URL_UAT`
- `VIEWPOINT_BASE_URL_SIT`

Recommended run settings:

- PROD: `targetEnvironment = PROD`, `agentPoolMode = Auto`
- DEV: `targetEnvironment = DEV`, `agentPoolMode = Auto`, `selfHostedPoolName = your pool`
- STAGE: `targetEnvironment = STAGE`, `agentPoolMode = Auto`, `selfHostedPoolName = your pool`

If your self-hosted pool is not ready yet, do not run DEV or STAGE from Azure Pipelines because the hosted agent will not be able to reach those private environments.

## Running Different Plans, Suites, and Configurations

The repository flow is no longer tied to a single Azure Test Plan or suite.

- For generation, pass any `--plan-id` and `--suite-id` values to `generate-scripts`
- For Azure Test Plans execution, supply the desired `testPlan`, `testSuite`, `testConfiguration`, `targetEnvironment`, and agent mode when running `.\QA.Regression.Automation\azure-testplans-run.yml`

Example:

```bash
python main.py generate-scripts --plan-id 40001 --suite-id 40025 --overwrite --associate
```

## Association Notes

- `generate-scripts --associate` performs generation first, then immediately applies the manifest mapping back to Azure Test Cases.
- `associate-scripts` updates the Azure Test Case work item fields for automated name, storage, type, and automation status.
- By default it refuses to overwrite an existing association. Use `--overwrite-association` only when you intentionally want to replace a prior mapping.
- The default storage name comes from the generated manifest assembly name, for example `QA.Regression.Automation.dll`.

## Safety Notes

- Dry-run mode performs no Azure writes.
- Verify and reconcile are read-only.
- Never log PAT values.
