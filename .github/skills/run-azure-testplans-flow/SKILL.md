---
name: run-azure-testplans-flow
description: Use this skill when the generated automation is already in the repository and the next task is to run or verify the Azure Pipelines plus Azure Test Plans execution flow end to end.
---

# Run Azure Test Plans Flow

Use this skill when the automation scripts already exist and you need to execute or verify the Azure DevOps side of the flow.

This skill is for the "run it in Azure" phase. If test cases were added or manual steps changed, use `sync-testplan-automation` first.

## When to use

Use this skill when any of the following is true:

- The generated tests were already created and associated to Azure Test Cases
- You need to rerun the normal CI pipeline after a code or variable change
- You need to rerun the Azure Test Plans pipeline from any plan, suite, or configuration
- Azure Test Plans is not picking up the automated tests and you need to verify the Azure-side setup

## Current repository-specific setup

- CI pipeline YAML: `QA.Regression.Automation/azure-pipelines.yml`
- Test Plans pipeline YAML: `QA.Regression.Automation/azure-testplans-run.yml`
- Target environment parameter: `targetEnvironment`
- Agent routing parameters: `agentPoolMode`, `selfHostedPoolName`
- For `DEV` and `STAGE`, `Auto` uses the CI self-hosted Linux agent: pool `SelfHostedAP-Dev-NE-Swarm`, agent `gbvmdsmanagerdne01`.
- The Test Plans pipeline must be authorized to use that pool in Azure DevOps.
- Base URL variables follow: `VIEWPOINT_BASE_URL_<ENVIRONMENT>`
- The checked-in pipeline YAML files do not hardcode a PROD base URL, so Azure DevOps variables must provide `VIEWPOINT_BASE_URL_PROD` and any other environment URLs you use.

## Preconditions

Before using this skill, make sure all of the following are true:

- The latest generated code has been committed and pushed
- The target Azure Test Case is already marked as automated
- Azure pipeline variables exist:
  - `VIEWPOINT_USERNAME`
  - `VIEWPOINT_PASSWORD`
  - `VIEWPOINT_INVALID_USERNAME` (optional; defaults to `VIEWPOINT_USERNAME` if not set)
  - `VIEWPOINT_INVALID_PASSWORD` for negative-login scenarios
  - `VIEWPOINT_BASE_URL_PROD` for production
  - any additional environment URLs you want to run, such as `VIEWPOINT_BASE_URL_DEV` or `VIEWPOINT_BASE_URL_STAGE`
- You know the specific Azure Test Plan ID, suite ID, and configuration ID you want to execute
- If the target environment is private, a reachable self-hosted agent pool exists and is permitted for the pipeline

## Full Azure run flow

### 1) Run the normal CI pipeline

Create or run the pipeline that uses:

- `QA.Regression.Automation/azure-pipelines.yml`

Choose:

- `targetEnvironment = PROD`, `DEV`, `STAGE`, or another configured environment name
- `agentPoolMode = Auto` to use hosted for `PROD` and self-hosted for non-`PROD`
- `agentPoolMode = SelfHosted` if you want even `PROD` to run through your internal pool
- `selfHostedPoolName = your pool name` when self-hosted routing is used

Expected result:

- the build succeeds
- Playwright/NUnit tests are discovered
- the automated login test passes

If CI says no test sources were found, verify that the run is using the current YAML from the latest branch state.

### 2) Run the Azure Test Plans execution pipeline

Create or run the pipeline that uses:

- `QA.Regression.Automation/azure-testplans-run.yml`

Use these values:

- `testPlan = the plan you want to execute`
- `testSuite = the suite you want to execute`
- `testConfiguration = the configuration assigned to that suite`
- `targetEnvironment = PROD`, `DEV`, `STAGE`, or another configured environment name
- `agentPoolMode = Auto`, `Hosted`, or `SelfHosted`
- `selfHostedPoolName = SelfHostedAP-Dev-NE-Swarm` for the CI-matching DEV/STAGE self-hosted agent

Expected result:

- Azure finds the automated test cases in the suite
- the pipeline executes the associated automation
- the result is published back through the Test Plans flow

### 3) Verify from Azure Test Plans

In Azure Test Plans:

- open the plan you selected
- open the suite you selected
- confirm the test case shows as automated
- run the suite or review the automated run result

If the pipeline passed but Test Plans still shows nothing, verify the association fields on the Azure Test Case and confirm the suite uses the exact configuration ID passed to the pipeline.

## Common failures and the correct fix

### Failure: No automated test cases were found matching the specified test plan, test suites, test configuration

This usually means one of these is wrong:

- the test case was not associated
- the case is not in the selected suite
- the pipeline used the wrong configuration ID

Use the exact configuration attached to the suite's test points rather than assuming `1` or reusing a value from another suite.

### Failure: No test sources found matching the given filter

This usually means the CI pipeline is running an older or incorrect YAML version, or the built test assembly path does not match the checked-in configuration.

Use the latest committed pipeline from:

- `QA.Regression.Automation/azure-pipelines.yml`

### Failure: Site cannot be reached from hosted agent

If the target URL is internal-only, Microsoft-hosted agents may fail because they cannot resolve or reach the environment.

Correct options:

- use a public URL, or
- use a self-hosted agent that has network access

### Choosing the right agent mode

- Use `Auto` for the normal split:
  - `PROD` -> hosted
  - `DEV` / `STAGE` / other private environments -> self-hosted
- Use `Hosted` only for environments that are publicly reachable from Azure-hosted agents
- Use `SelfHosted` when you want every environment, including `PROD`, to execute from your own machine or VM

## Quick operator checklist

1. Push latest code
2. Confirm pipeline variables exist
3. Run CI pipeline from `azure-pipelines.yml`
4. Run Test Plans pipeline from `azure-testplans-run.yml`
5. Enter the correct plan, suite, configuration, environment, and agent mode for this run
6. Confirm results in Azure Test Plans

## Example use

Example: the generated test is already passing locally and has been pushed for plan `40001`, suite `40025`, configuration `222`.

1. Run the CI pipeline from `QA.Regression.Automation/azure-pipelines.yml`.
2. After CI passes, run the Test Plans pipeline from `QA.Regression.Automation/azure-testplans-run.yml`.
3. Enter:

   - `testPlan = 40001`
   - `testSuite = 40025`
   - `testConfiguration = 222`
   - `targetEnvironment = STAGE`
   - `agentPoolMode = Auto`
   - `selfHostedPoolName = SelfHostedAP-Dev-NE-Swarm`

4. Review the suite result in Azure Test Plans.
