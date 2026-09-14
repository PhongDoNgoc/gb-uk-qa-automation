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
python main.py generate-scripts --plan-id 30985 --suite-id 31681 --overwrite
```

10. Generate and associate in one step

```bash
python main.py generate-scripts --plan-id 30985 --suite-id 31681 --overwrite --associate
```

11. Execute the generated automation locally

```bash
dotnet test .\QA.Regression.Automation\QA.Regression.Automation.csproj --logger trx
```

12. Push the generated automation mapping back to Azure Test Cases

```bash
python main.py associate-scripts --manifest .\QA.Regression.Automation\Tests\Generated\Suite31681\automation-manifest.json
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

## Pipeline Files

- `.\QA.Regression.Automation\azure-pipelines.yml`: standard CI build and regression execution
- `.\QA.Regression.Automation\azure-testplans-run.yml`: Azure Test Plans-triggered execution using plan, suite, and configuration inputs

## Association Notes

- `generate-scripts --associate` performs generation first, then immediately applies the manifest mapping back to Azure Test Cases.
- `associate-scripts` updates the Azure Test Case work item fields for automated name, storage, type, and automation status.
- By default it refuses to overwrite an existing association. Use `--overwrite-association` only when you intentionally want to replace a prior mapping.
- The default storage name comes from the generated manifest assembly name, for example `QA.Regression.Automation.dll`.

## Safety Notes

- Dry-run mode performs no Azure writes.
- Verify and reconcile are read-only.
- Never log PAT values.
