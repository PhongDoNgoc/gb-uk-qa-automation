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

The `QA.Regression.Automation/azure-testplans-run.yml` pipeline uses the same self-hosted Linux agent for `DEV` and `STAGE`. On Linux it selects automated test points by plan, suite, and configuration through the Azure DevOps Test APIs, runs their associated NUnit methods with `dotnet test`, and writes outcomes and evidence attachments back to the Test Plan. It also publishes TRX files to the pipeline run. The hosted Windows route continues to use the Visual Studio Test task's Test Plan selector.

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

Configure these in Azure DevOps pipeline variables or a variable group. Mark credentials and `AZDO_PAT` as secret. The PAT must have Work Items read/write and Test Management read/write access so CI can fetch cases and update automation associations, and the Linux Test Plans pipeline can select test points and publish results and attachments. Set each base URL to its actual environment URL. The pipeline validates the selected environment's URL and credentials before running tests.

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

Clicking `Export to Excel` must produce a completed, non-empty `.xls` or `.xlsx` download within 120 seconds. The downloaded file is attached as test evidence. A dedicated screenshot also shows an automation-labelled evidence panel with the actual downloaded filename, saved file size, and completion status. This panel is not the browser's Downloads flyout, which Playwright page screenshots cannot capture. A successful click alone does not pass the export check; workbook contents are not validated.

Manual steps such as `Click on 'Export to Excel' button` are translated into this download check. Generation fails explicitly if an export case cannot be translated into an `Export to Excel` click, rather than producing a test that silently omits the export. Successful exports also log the test name, downloaded filename, byte count, and evidence attachment confirmation.

Export targeting includes visible links styled as toolbar buttons and Kendo Excel export controls, ignores hidden duplicates, and waits for normal Playwright click actionability. The log separately confirms the click and the verified download; no forced click or direct API download is used to bypass the UI.

Before clicking, the test waits (up to 120 seconds) until the grid that owns the export control and any Kendo dropdown data sources have finished loading for 1.5 seconds and the control is enabled. Other grids on the page, such as summary tables, are ignored. If the control stays disabled, the test fails with a message that the selected filters probably returned no data. If the application shows a SweetAlert, toast or Kendo notification instead of producing a file, the test fails immediately with that message. A download timeout reports which grids or data sources were still busy.

`Go to` steps fail when the URL returns HTTP 400 or higher. If the step names a menu item, for example `click to Portal Usage Report URL @environment : baseURL/PortalUsageReport`, the test opens the matching menu link instead and logs a warning asking you to correct the Test Case URL.

Selector steps that choose data before exporting are translated into `SelectOptionAsync` calls. Supported wording includes `In 'Country' selector, select @country` and `Select a @date in Select Date selector`; `dropdown`, `filter` and `picker` can replace `selector`, and literal quoted values are also supported. `@parameter` values come from the Test Case parameter table, using the row whose `environment` matches `TEST_TARGET_ENV`. A blank value for the target environment fails the test with a clear message instead of exporting unfiltered data. The control is found by its label, accessible name or nearby label text and may be a native select, a Kendo-style dropdown, a text/date input or a read-only bootstrap month picker (values such as `Jan-2026`, `January-2026`, `01/2026` or `2026-01`). After each selection the test waits for the page's data to settle. An exact option match is preferred; otherwise, a single whole-word match such as `GB` in `United Kingdom (GB)` is accepted. Native select options loaded after the page opens are awaited for up to 30 seconds; if the option is still missing, the error lists the available options. Before each selection the test also waits for the page's own data requests (XHR/fetch) to finish; requests running longer than 30 seconds are treated as polling and ignored. If a selector stays empty because it depends on a previous selection made before the page's data arrived (for example Site after Customer), the previous selection is re-applied every 5 seconds, for up to 90 seconds, and each attempt is logged. Generation fails if a selector step cannot be translated.

API status checks can also contain selector steps, for example `In 'Customer' selector, select @customer` before `Verify the GetAllDiagnosticsSessions API response status`. The test then opens the page, applies the selections, and asserts the API call the page itself makes after the last selection, using the page's method and body (for example a `POST`). It does not send its own `GET`. If the page does not call the API again within 45 seconds, the call made after an earlier selection is used and a warning is logged; if the page never calls the API after the selections, the test fails with a clear message. The evidence panel shows the HTTP method and the selected values. API status checks without selector steps keep requesting the API URL directly with the signed-in session.

The request URL may be written as `Request URL: baseURL/...` or `Request URL @environment = baseURL/...`. If the step continues with `In API payload, input:` followed by `key : value` pairs, the test sends those fields as a form `POST`, the same way the page does, with the signed-in session and the `X-Requested-With: XMLHttpRequest` header. Example: `sort: blank page : 1 pageSize : 50 filter: blank Period : @period CountryId : @countryid`. `blank` or `empty` sends an empty value. `@parameter` values are resolved per environment, and other values are sent exactly as written. If the Test Case also has selector steps, the test opens the page and applies the selections, then posts the payload. Without a payload, the test sends a `GET` to the URL, including any query string. The evidence panel shows the method and the payload that was sent.

Several selectors can be set in one step: `Select Country = @country, Energy Service = @energyservice, Period = @period, Select Issue Type = @issuetype in the selectors`. Each `Label = value` pair becomes its own `SelectOptionAsync` call, in the order written.

The slow Summary Payment Availability endpoint (`/PaymentAvailability/GetSummaryPaymentAvailability`) has a 5-minute request/response timeout, for both direct API requests and watched page calls. Its `SummaryTablePayment` grid also waits up to 5 minutes for initial records and each filter, filter-clear, or pagination reload. These are maximum waits, not fixed delays: checks continue as soon as the response arrives or the grid is ready. Other endpoints and grids retain their existing timeouts.

Display-only grid steps such as `Verify the view Summary Table feature` with `Summary Table should be displayed` check that the correct grid has finished loading and shows records, then attach `Grid feature evidence`. No column filters or pagination clicks are performed unless explicitly listed in the expected result. This applies to the updated Payment Availability view cases 31856 and 31858; selector steps are applied only when present in the Test Case.

Grid feature steps such as `Verify the view Summary Table feature`, with the expected result `Summary Table should be displayed and functioning correctly (filter by Root Name, Site Name, Segment Name, pagination)`, become `VerifyGridFeatureAsync`. The test uses the grid under the matching heading; if there is none (for example the page heading `Payment Availability`), it uses the first grid that has the listed columns. The grid must show at least one record. For each listed column, the test filters by a value taken from the first row, checks that every row shown contains it, and then clears the filter. For `pagination`, it opens the next page and checks that the page number advances; if every record fits on one page, it only checks that the pager is shown. A `Grid feature evidence` screenshot shows each result. The test fails if a column is missing, the grid has no records, or a filter or page change has no effect.

Each executed UI test attaches:

- a Playwright trace `.zip`
- a screenshot `.png`

Failed tests label the image as `Failure screenshot`. Passed tests label it as `Test screenshot`.

For generated API status checks, the screenshot also includes an on-page evidence panel showing:

- the authenticated request URL
- the returned HTTP status code (for example `200`)
- a preview of the API response body

Each API status check also attaches a dedicated full-page `API response evidence` screenshot immediately after rendering the panel, so the evidence remains available even if the application later updates its page. Customer Details uses direct URL navigation and evidence capture waits for both the Energy Services and Customer Details sections and at least two populated tables to be visible. Unit Details is opened through the Utilities navigation, falling back to its direct URL if the menu link is unavailable. It is not considered ready until its heading, Export to Excel control, Refresh control, and at least one grid row are visible; API evidence and Refresh actions wait for that UI readiness check.

Both `Verify ... API status` and `Verify ... API response status` are recognised when the case has a logged-in precondition, a `Request URL`, and an expected status code. Collector Run cases 31870 and 31871 keep the Collector Scheduling portal page open and display the standard API evidence panel there; the API request is sent separately, not opened as a raw JSON page. The returned HTTP status is asserted.

## Validation

Run the focused Python tests:

```bash
python -m unittest tests.test_automation_generator tests.test_automation_association tests.test_azure_serialization
```

Run the .NET automation project:

```bash
dotnet test .\QA.Regression.Automation\QA.Regression.Automation.csproj --configuration Release --logger trx
```
