from __future__ import annotations

import argparse
import logging

from automation_association import associate_generated_tests
from automation_generator import generate_automation_scripts
from azure_client import AzureDevOpsClient, AzureDevOpsError
from config import load_config, setup_logging, validate_required

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Azure DevOps QA Test Case Generator")
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate-scripts", help="Generate Playwright C# scripts from Azure Test Cases")
    generate.add_argument("--suite-file", required=False, help="Path to exported suite text file")
    generate.add_argument("--plan-id", required=False, type=int, help="Azure Test Plan ID")
    generate.add_argument("--suite-id", required=False, type=int, help="Azure Test Suite ID")
    generate.add_argument("--project-dir", required=False, help="Path to QA.Regression.Automation project")
    generate.add_argument(
        "--namespace",
        required=False,
        default="QA.Regression.Automation.Tests.Generated",
        help="Base namespace for generated tests",
    )
    generate.add_argument("--overwrite", action="store_true", help="Overwrite existing generated files")
    generate.add_argument("--associate", action="store_true", help="Associate generated tests back to Azure Test Cases")
    generate.add_argument("--test-storage", required=False, help="Override test storage/assembly name for association")
    generate.add_argument("--test-type", required=False, default="NUnit", help="Automated test type label for association")
    generate.add_argument(
        "--overwrite-association",
        action="store_true",
        help="Replace an existing Azure Test Case automation association when using --associate",
    )

    associate = sub.add_parser("associate-scripts", help="Associate generated automation back to Azure Test Cases")
    associate.add_argument("--manifest", required=True, help="Path to automation-manifest.json")
    associate.add_argument("--test-storage", required=False, help="Override test storage/assembly name")
    associate.add_argument("--test-type", required=False, default="NUnit", help="Automated test type label")
    associate.add_argument(
        "--overwrite-association",
        action="store_true",
        help="Replace an existing Azure Test Case automation association",
    )

    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser


def _build_azure_client_or_fail() -> AzureDevOpsClient | None:
    missing = validate_required("AZDO_ORG", "AZDO_PROJECT", "AZDO_PAT")
    if missing:
        print("CONFIG: FAIL")
        for name in missing:
            print(f"- {name}")
        return None
    return AzureDevOpsClient.from_env()


def _run() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    setup_logging(debug=bool(getattr(args, "debug", False)))
    load_config()

    try:
        if args.command == "generate-scripts":
            requires_azure = not bool(args.suite_file) or bool(args.associate)
            client = _build_azure_client_or_fail() if requires_azure else None
            if requires_azure and client is None:
                return 1

            result = generate_automation_scripts(
                client=client,
                suite_file=args.suite_file,
                plan_id=args.plan_id,
                suite_id=args.suite_id,
                project_dir=args.project_dir,
                namespace=args.namespace,
                overwrite=bool(args.overwrite),
            )
            print("SCRIPT GENERATION COMPLETE")
            print(f"Plan: {result.get('plan_id') or 'N/A'}  Suite: {result['suite_id']}")
            print(f"Project: {result['project_dir']}")
            print(f"Output: {result['output_dir']}")
            print(f"Generated: {len(result['generated'])}  Skipped: {len(result['skipped'])}")
            print(f"Manifest: {result['manifest_path']}")

            if args.associate:
                association = associate_generated_tests(
                    client=client,
                    manifest_path=result["manifest_path"],
                    test_storage=args.test_storage,
                    test_type=args.test_type,
                    overwrite=bool(args.overwrite_association),
                )
                print("ASSOCIATION COMPLETE")
                print(f"Storage: {association['test_storage']}  Type: {association['test_type']}")
                print(f"Associated: {len(association['updated'])}  Skipped: {len(association['skipped'])}")
            return 0

        if args.command == "associate-scripts":
            client = _build_azure_client_or_fail()
            if client is None:
                return 1
            result = associate_generated_tests(
                client=client,
                manifest_path=args.manifest,
                test_storage=args.test_storage,
                test_type=args.test_type,
                overwrite=bool(args.overwrite_association),
            )
            print("ASSOCIATION COMPLETE")
            print(f"Plan: {result.get('plan_id') or 'N/A'}  Suite: {result.get('suite_id') or 'N/A'}")
            print(f"Storage: {result['test_storage']}  Type: {result['test_type']}")
            print(f"Associated: {len(result['updated'])}  Skipped: {len(result['skipped'])}")
            return 0

        parser.print_help()
        return 1

    except (AzureDevOpsError, FileNotFoundError, ValueError) as exc:
        logger.error("Command failed: %s", exc)
        print(f"ERROR: {exc}")
        return 1


def main() -> int:
    return _run()


if __name__ == "__main__":
    raise SystemExit(main())
