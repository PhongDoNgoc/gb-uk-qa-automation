# Azure Test Plans Automation Generator

This repository is focused on this flow:

- read existing manual test cases from Azure Test Plans
- generate Playwright/NUnit automation scripts
- support login flows and logged-in page API status checks
- associate the generated automated tests back to those Azure test cases
- validate locally
- run from Azure Pipelines and Azure Test Plans


## Main commands

### Generate scripts from an exported suite file

```bash
python main.py generate-scripts --suite-file .\samples\suite_31681_testcases.txt
```

### Generate scripts directly from Azure Test Plans

```bash
python main.py generate-scripts --plan-id <PLAN_ID> --suite-id <SUITE_ID> --overwrite
```

### Generate and associate in one step

```bash
python main.py generate-scripts --plan-id <PLAN_ID> --suite-id <SUITE_ID> --overwrite --associate --overwrite-association
```

### Associate from an existing manifest

```bash
python main.py associate-scripts --manifest .\QA.Regression.Automation\Tests\Generated\Suite31681\automation-manifest.json
```

## Easiest repeatable flow

Run this from the repository root:

```powershell
.\sync-testplan-automation.ps1 -PlanId <PLAN_ID> -SuiteId <SUITE_ID>
```

To also commit and push automatically:

```powershell
.\sync-testplan-automation.ps1 -PlanId <PLAN_ID> -SuiteId <SUITE_ID> -Commit -Push
```

If PowerShell blocks local scripts, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\sync-testplan-automation.ps1 -PlanId <PLAN_ID> -SuiteId <SUITE_ID> -Commit -Push
```

For your current default suite, you can copy-paste this exact block:

```powershell
cd "C:\Users\lan.le\OneDrive - Endeco-Technologies\Desktop\AI Automated Automation Script\azure-testcase-generator"
powershell -ExecutionPolicy Bypass -File .\sync-testplan-automation.ps1 -PlanId 30985 -SuiteId 31681 -Commit -Push
```

## What the helper script does

- loads values from `.env` if present
- regenerates the suite automation
- overwrites stale automated associations when the generated test name changes
- runs the Python validation tests
- runs the .NET automation tests
- optionally commits and pushes

Optional flags:

- `-TargetEnvironment PROD|DEV|STAGE`
- `-Commit`
- `-Push`
- `-SkipPythonTests`
- `-SkipDotNetTests`

Example:

```powershell
.\sync-testplan-automation.ps1 -PlanId 30985 -SuiteId 31681 -Commit -Push
```

## Project structure

```text
azure-testcase-generator/
├── main.py
├── automation_generator.py
├── automation_association.py
├── azure_client.py
├── azure_serialization.py
├── config.py
├── sync-testplan-automation.ps1
├── tests/
│   ├── test_automation_association.py
│   ├── test_automation_generator.py
│   └── test_azure_serialization.py
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

## Environment selection

Generated tests resolve URLs from a selected target environment.

- `TEST_TARGET_ENV=PROD` uses `VIEWPOINT_BASE_URL_PROD`
- `TEST_TARGET_ENV=DEV` uses `VIEWPOINT_BASE_URL_DEV`
- `TEST_TARGET_ENV=STAGE` uses `VIEWPOINT_BASE_URL_STAGE`

The Azure pipeline YAML files do not provide a built-in PROD URL anymore, so every environment URL, including `VIEWPOINT_BASE_URL_PROD`, must come from your local `.env` or Azure DevOps pipeline variables.

You can copy [.env.example](</C:/Users/lan.le/OneDrive - Endeco-Technologies/Desktop/AI Automated Automation Script/azure-testcase-generator/.env.example>) to `.env` for local setup.

## Hosted vs self-hosted agents

The pipeline YAML files support:

- `targetEnvironment`
- `agentPoolMode`
- `selfHostedPoolName`

Supported modes:

- `Auto`: hosted for `PROD`, self-hosted for non-`PROD`
- `Hosted`: always use Microsoft-hosted `windows-latest`
- `SelfHosted`: always use the selected self-hosted pool

## Azure variable checklist

Create these Azure Pipeline variables before running across multiple environments:

- `VIEWPOINT_USERNAME`
- `VIEWPOINT_PASSWORD`
- `VIEWPOINT_INVALID_USERNAME` (optional; defaults to `VIEWPOINT_USERNAME` if not set)
- `VIEWPOINT_INVALID_PASSWORD` for negative-login scenarios
- `VIEWPOINT_BASE_URL_PROD`
- `VIEWPOINT_BASE_URL_DEV`
- `VIEWPOINT_BASE_URL_STAGE`

These variables should be configured in Azure DevOps pipeline variables or a variable group. The checked-in YAML files no longer supply a default PROD URL.
If you store them as secret variables in Azure DevOps, the pipeline YAML now maps them explicitly into the `VSTest` task environment so the NUnit test process can read them.
The pipeline also includes a preflight validation step that checks the required variable names before starting `VSTest`, so missing configuration fails fast with a clearer error.

Optional later:

- `VIEWPOINT_BASE_URL_UAT`
- `VIEWPOINT_BASE_URL_SIT`

## Test evidence

Each executed UI test attaches:

- a Playwright trace `.zip`
- a screenshot `.png`

Failed tests label the image as `Failure screenshot`. Passed tests label it as `Test screenshot`.

For generated API status checks, the screenshot also includes an on-page evidence panel showing:

- the authenticated request URL
- the returned HTTP status code (for example `200`)
- a preview of the API response body

## Validation

Run the focused Python tests:

```bash
python -m unittest tests.test_automation_generator tests.test_automation_association tests.test_azure_serialization
```

Run the .NET automation project:

```bash
dotnet test .\QA.Regression.Automation\QA.Regression.Automation.csproj --configuration Release --logger trx
```
