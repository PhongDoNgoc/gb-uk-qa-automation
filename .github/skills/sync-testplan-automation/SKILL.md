---
name: sync-testplan-automation
description: Use this skill when Azure Test Plans test cases are added or changed and the repository must regenerate Playwright tests, re-associate them to Azure Test Cases, validate locally, push code, and rerun Azure Pipelines/Test Plans.
---

# Sync Test Plan Automation

Use this skill when manual test cases in Azure Test Plans change and the codebase must be brought back in sync.

This repository keeps the full automation flow in one root:

- Python generator and Azure association logic at the repo root
- Playwright/NUnit test project in `QA.Regression.Automation/`

## When to use

Use this skill when any of the following happens:

- A new Azure Test Case is added to any Azure Test Plan suite you want to automate
- Test steps or expected results change in Azure Test Plans
- The base URL or credentials flow changes
- Azure Test Plans cannot find updated automated tests because code or associations are stale

## Important repository learnings

- Generated automation files live under `QA.Regression.Automation/Tests/Generated/`.
- The preferred one-step command is `generate-scripts --overwrite --associate`.
- The production/public URL variable name is `VIEWPOINT_BASE_URL_PROD`.
- Environment selection is controlled by `TEST_TARGET_ENV`, which maps to `VIEWPOINT_BASE_URL_<ENVIRONMENT>`.
- Pipeline agent routing is controlled by `agentPoolMode`; in `Auto`, `PROD` uses hosted and non-`PROD` environments use the selected self-hosted pool.
- Each suite can use a different Azure Test Plans configuration ID, so verify the suite's actual configuration before running the Test Plans pipeline.
- CI pipeline file: `QA.Regression.Automation/azure-pipelines.yml`
- Test Plans pipeline file: `QA.Regression.Automation/azure-testplans-run.yml`

## Exact commands to run when new test cases are added

Run these commands from the repository root:

```powershell
cd "C:\Users\lan.le\OneDrive - Endeco-Technologies\Desktop\AI Automated Automation Script\azure-testcase-generator"
```

### Fastest one-command flow

```powershell
.\sync-testplan-automation.ps1 -PlanId <PLAN_ID> -SuiteId <SUITE_ID>
```

To also commit and push automatically:

```powershell
.\sync-testplan-automation.ps1 -PlanId <PLAN_ID> -SuiteId <SUITE_ID> -Commit -Push
```

This helper script:

- loads `.env` automatically
- regenerates the suite automation
- overwrites stale automated associations when the generated test name changes
- runs Python validation tests
- runs .NET automation tests

### 1) Regenerate scripts and re-associate to Azure Test Cases

```powershell
python main.py generate-scripts --plan-id <PLAN_ID> --suite-id <SUITE_ID> --overwrite --associate
```

What this does:

- reads the latest test cases from Azure Test Plans
- rewrites generated Playwright/NUnit tests
- updates Azure Test Case automation mapping from the manifest

### 2) Validate locally before pushing

```powershell
python -m unittest tests.test_automation_generator tests.test_automation_association
```

```powershell
dotnet test .\QA.Regression.Automation\QA.Regression.Automation.csproj --configuration Release --filter FullyQualifiedName~Tc31682 --logger trx
```

To choose a non-production environment for a local run:

```powershell
$env:TEST_TARGET_ENV="DEV"
$env:VIEWPOINT_BASE_URL_DEV="https://your-dev-url/"
dotnet test .\QA.Regression.Automation\QA.Regression.Automation.csproj --configuration Release --logger trx
```

If more generated tests were added and you want broader validation:

```powershell
dotnet test .\QA.Regression.Automation\QA.Regression.Automation.csproj --configuration Release --logger trx
```

### 3) Push the generated code

```powershell
git add .
git commit -m "Update generated automation tests"
git push origin main
```

### 4) Rerun Azure Pipelines

After the push:

- CI should run from `QA.Regression.Automation/azure-pipelines.yml`
- Test Plans execution should use `QA.Regression.Automation/azure-testplans-run.yml`

For the Test Plans pipeline, use:

- `testPlan = your target plan ID`
- `testSuite = your target suite ID`
- `testConfiguration = the configuration ID actually assigned to that suite`
- `targetEnvironment = PROD`, `DEV`, `STAGE`, or another environment name you configured
- `agentPoolMode = Auto`, `Hosted`, or `SelfHosted`
- `selfHostedPoolName = your pool name` when self-hosted routing is required

## Required pipeline variables

Use these variables in Azure Pipelines:

- `TEST_TARGET_ENV`
- `VIEWPOINT_USERNAME`
- `VIEWPOINT_PASSWORD`
- `VIEWPOINT_INVALID_USERNAME` (optional; defaults to `VIEWPOINT_USERNAME` if not set)
- `VIEWPOINT_INVALID_PASSWORD` for negative-login scenarios
- at least one matching base URL variable such as `VIEWPOINT_BASE_URL_PROD`
- a usable self-hosted pool if you want to run private environments from Azure Pipelines

Future environments can add more variables such as:

- `VIEWPOINT_BASE_URL_UAT`
- `VIEWPOINT_BASE_URL_DEV`
- `VIEWPOINT_BASE_URL_SIT`

## Troubleshooting

### Pipeline says no automated test cases were found

Check that:

- the test case is in the suite you selected
- the automated association exists in Azure Test Case fields
- the suite test point uses the same configuration ID as the pipeline
- the configuration ID matches the actual suite test point configuration, not a guessed default

### Hosted pipeline cannot reach the site

If the target URL is internal-only, Microsoft-hosted agents may fail on DNS/network access. Either:

- use a public URL, or
- run on an internal/self-hosted agent that can reach the app

### New manual wording breaks generation

If Azure manual steps use different labels such as `Email Address` instead of `username`, update parsing/generation rules in:

- `automation_generator.py`

## Example workflow

Example: Test case `31683` is added to suite `40025` in plan `40001`.

1. Add or update the case in Azure Test Plans.
2. Run:

   ```powershell
   .\sync-testplan-automation.ps1 -PlanId 40001 -SuiteId 40025 -Commit -Push
   ```

3. Validate:

   ```powershell
   This is already included in the helper script unless you explicitly skip it.
   ```

4. Run the Azure pipeline and then the Azure Test Plans pipeline.
