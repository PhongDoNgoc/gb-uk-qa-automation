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
├── requirements.txt
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

Every environment URL must come from your local `.env` or Azure DevOps pipeline variables.

You can copy [.env.example](</C:/Users/lan.le/OneDrive - Endeco-Technologies/Desktop/AI Automated Automation Script/azure-testcase-generator/.env.example>) to `.env` for local setup.

## Hosted vs self-hosted agents

The manually triggered `QA.Regression.Automation/azure-pipelines.yml` routes `PROD` to the Microsoft-hosted `ubuntu-latest` agent, and routes `DEV` and `STAGE` to Linux self-hosted agent `gbvmdsmanagerdne01` in pool `SelfHostedAP-Dev-NE-Swarm`.

Before building, CI fetches the current test cases and parameter rows from Plan `30985`, Suite `31681`, regenerates the C# scripts, and removes generated files for cases no longer in the suite. After a successful build, it updates the automation association fields on those existing Azure Test Cases, runs only generated tests from the selected suite, and publishes TRX results. Helper/unit tests in the same project are not included in the CI run.

This updates the automation association on existing Test Case work items; it does not create new Test Case items or store C# source code in the Test Plans suite. The generated C# exists in the pipeline workspace for that run. This CI pipeline does not use the Azure Test Plans on-demand VSTest flow.

## Azure variable checklist

Create these Azure Pipeline variables before running:

- `VIEWPOINT_USERNAME`
- `VIEWPOINT_PASSWORD`
- `VIEWPOINT_INVALID_USERNAME` (optional; defaults to `VIEWPOINT_USERNAME` if not set)
- `VIEWPOINT_INVALID_PASSWORD` for negative-login scenarios
- `VIEWPOINT_BASE_URL_PROD`
- `VIEWPOINT_BASE_URL_DEV`
- `VIEWPOINT_BASE_URL_STAGE`
- `AZDO_PAT` (secret)

Configure these in Azure DevOps pipeline variables or a variable group. Mark credentials and `AZDO_PAT` as secret. The PAT must be able to read Test Plans and read/write Work Items so CI can fetch cases and update their automated-test association. Set each base URL to its actual environment URL. The pipeline validates the selected environment's URL and credentials before running tests.

The Linux agents need Python 3 with `venv`, .NET 10, passwordless `sudo` for the pipeline to install Chromium's system dependencies, and outbound access to Azure DevOps, PyPI, and the Playwright browser download service. DEV/STAGE also need VPN access to their target environments. The pipeline installs Chromium through Playwright's .NET API, so PowerShell 7 is not required. If the agent account cannot use passwordless `sudo`, an administrator must preinstall Python/venv and the Linux browser dependencies.

## Environment-specific Test Plans parameters

For API tests with IDs that differ by environment, use parameter placeholders in the test step (for example, `rootId='@rootID'`) and a parameter table with separate `Environment` and ID columns. The generator supports request labels in the form `Request URL @environment : baseURL/...`; environment names and parameter column names are matched case-insensitively. If needed, reference `@Environment` in a step to add that parameter column:

| Environment | rootID |
| --- | --- |
| PROD | PROD_ROOT_ID |
| DEV | DEV_ROOT_ID |
| STAGE | STAGE_ROOT_ID |

Replace the example values with actual IDs. Add other ID columns, such as `SiteID`, `MarketUnitID`, or `ControlUnitID`, as needed. Keep the ID cells to the actual ID values; do not append labels such as `- dev` to an ID. Include rows for every environment you want to run. The automation generator includes the rows in the generated test and selects the row matching the pipeline's `targetEnvironment` at runtime.

When using CI, it fetches the latest parameter rows and regenerates the scripts at the start of every run. To generate locally instead, fetch the suite directly from Azure DevOps (not a plain-text suite export, which does not carry the parameter rows) and run `python main.py generate-scripts --plan-id 30985 --suite-id 31681 --project-dir QA.Regression.Automation --overwrite`.

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

Each API status check also attaches a dedicated full-page `API response evidence` screenshot immediately after rendering the panel, so the evidence remains available even if the application later updates its page. Customer Details and Unit Details routes are opened through the Utilities navigation. Unit Details is not considered ready until its heading, Export to Excel control, Refresh control, and at least one grid row are visible; API evidence and Refresh actions wait for that UI readiness check.

## Validation

Run the focused Python tests:

```bash
python -m unittest tests.test_automation_generator tests.test_automation_association tests.test_azure_serialization
```

Run the .NET automation project:

```bash
dotnet test .\QA.Regression.Automation\QA.Regression.Automation.csproj --configuration Release --logger trx
```
