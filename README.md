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
- `reconciliation.py`: review orchestration, reconcile output, sprint-review projection, verify output, and approval metadata
- `apply_service.py`: unified apply flow with dry-run and execution readiness verification
- `validators.py`: apply and execution readiness validation
- `models.py`: typed dataclasses used across the system
- `config.py`: environment loading and logging setup

## Safety Notes

- Dry-run mode performs no Azure writes.
- Verify and reconcile are read-only.
- Never log PAT values.
