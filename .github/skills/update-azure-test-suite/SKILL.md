---
name: update-azure-test-suite
description: 'Use when the user asks to sync Azure DevOps test suites with local source code after test cases are added, removed, or updated, or test steps, expected results, titles, or test data change. Fetch the latest suite and regenerate Playwright/NUnit C# scripts locally without committing, pushing, associating tests, or running pipelines.'
argument-hint: 'Optional Azure Test Plan ID and suite ID; defaults to plan 30985 and suite 31681'
---

# Update Azure Test Suite Locally

Synchronize the selected Azure Test Plans suite with generated scripts in the local project. This is an on-demand workflow, not a background monitor: Azure changes are fetched when the user invokes this skill or asks Copilot to sync.

## Scope

- Default to plan `30985`, suite `31681`, unless the user selects another plan or suite. For multiple suites, process each explicitly selected pair.
- Fetch cases directly from Azure DevOps, including parameter rows; do not use a cached manifest or plain-text suite export as the source.
- Handle added cases, updated titles/steps/expected results, changed test data, and removed suite cases.
- Write only the selected suite's generated C# files and manifest under `QA.Regression.Automation\Tests\Generated\Suite<SUITE_ID>`.
- Use the existing generator in `main.py` and `automation_generator.py`; do not duplicate generation logic.
- Never commit, push, stash, restore, run pipelines, update Azure Test Case associations, or execute application/browser tests as part of this skill.
- Do not use `sync-testplan-automation.ps1`: that helper also associates tests and can execute tests or push code.

## Procedure

1. Locate the `azure-testcase-generator` project root containing `main.py` and `QA.Regression.Automation`. Run subsequent commands there using Windows paths. Do not hardcode a user's absolute directory.
2. Inspect the working tree and selected generated suite. Preserve unrelated changes. If the selected generated files contain user edits that regeneration would overwrite, ask before proceeding; do not discard them or reset the working tree.
3. Check that Python and .NET are available. Configuration is loaded by the CLI from the environment or local `.env`: `AZDO_ORG`, `AZDO_PROJECT`, and `AZDO_PAT` are required. Never print credentials or `.env` contents. If configuration is missing, ask the user to configure it locally; do not request a PAT in chat.
4. Run the existing focused generator and association-helper tests (these tests do not update Azure):

   ```powershell
   python -m unittest -b tests.test_automation_generator tests.test_automation_association
   if ($LASTEXITCODE -ne 0) { throw 'Generator validation failed.' }
   ```

   Install `requirements.txt` only if execution fails because dependencies are missing, using the selected Python environment:

   ```powershell
   python -m pip install -r requirements.txt
   if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
   ```

5. Fetch the latest suite and regenerate locally. Substitute the selected IDs:

   ```powershell
   python main.py generate-scripts --plan-id 30985 --suite-id 31681 --project-dir QA.Regression.Automation --overwrite
   if ($LASTEXITCODE -ne 0) { throw 'Local suite generation failed.' }
   ```

   Do not add `--associate` or `--overwrite-association`. `--overwrite` refreshes generated files and removes stale generated files for cases no longer in the suite. Generated filenames use `Tc<test-case-id>.cs` to avoid long Windows paths; descriptive C# class and method names remain intact.

6. Verify the selected suite's `automation-manifest.json`: confirm its plan/suite IDs, enumerate its `tests` entries, and check every referenced file exists. Confirm the local generated C# file count matches the manifest's test count. `generated_count` reports newly written files, not the total suite size; unchanged files may be reported as skipped. Do not assume the suite always has 27 cases.
7. Build the project without executing tests:

   ```powershell
   dotnet build .\QA.Regression.Automation\QA.Regression.Automation.csproj --configuration Release
   if ($LASTEXITCODE -ne 0) { throw 'Generated test project build failed.' }
   ```

8. Inspect the final diff and report the selected IDs, local output folder, total case/file count, generated/skipped counts, and validation result. Explain any stale-file removal or filename migration. State that changes are local and were not committed or pushed.

   Remind the user to review and commit/push both C# scripts (including removals/renames) and `automation-manifest.json` themselves. Pipelines execute the checked-in scripts and use the committed manifest for Azure associations; they do not regenerate scripts. Manifests omit raw steps and parameter data; review generated source for sensitive values before committing.

## Failure Handling

- Stop and report fetch, parsing, generation, missing-file, or build errors explicitly. Do not claim synchronization succeeded after a partial generation.
- If authentication fails, direct the user to check local Azure credentials and read permissions for the selected plan, suite, work items, and parameter data.
- If generation fails on unsupported manual wording or ambiguous test data, identify the affected case and ask for clarification. Do not silently omit cases, invent test data, or make unrelated generator changes.

## Example Invocation

Ask Copilot: "Sync my Azure test suite changes into my local project using update-azure-test-suite."

For a different suite: "Update local test scripts from plan 40001, suite 40025."
