import os
import sys

from dotenv import load_dotenv

from azure_client import AzureDevOpsClient, AzureDevOpsError


REQUIRED_VARS = [
    "AZDO_ORG",
    "AZDO_PROJECT",
    "AZDO_PAT",
    "AZDO_PLAN_ID",
    "AZDO_SUITE_ID",
    "REPO_PATH",
]


def read_env_value(name: str) -> str:
    return (os.getenv(name) or "").strip()


def validate_config() -> list[str]:
    missing: list[str] = []
    for name in REQUIRED_VARS:
        if not read_env_value(name):
            missing.append(name)
    return missing


def print_work_item_summary(work_item: dict) -> None:
    has_description = "FOUND" if work_item.get("description") else "MISSING"
    has_ac = "FOUND" if work_item.get("acceptance_criteria") else "MISSING"

    print("WORK ITEM:")
    print(f"ID: {work_item.get('id')}")
    print(f"Title: {work_item.get('title') or ''}")
    print(f"Type: {work_item.get('work_item_type') or ''}")
    print(f"State: {work_item.get('state') or ''}")
    print(f"Description: {has_description}")
    print(f"Acceptance Criteria: {has_ac}")


def main() -> int:
    load_dotenv()

    missing = validate_config()
    if missing:
        print("CONFIG: FAIL")
        print("Missing variables:")
        for name in missing:
            print(f"- {name}")
        return 1

    print("CONFIG: PASS")

    plan_id_raw = read_env_value("AZDO_PLAN_ID")
    suite_id_raw = read_env_value("AZDO_SUITE_ID")

    try:
        plan_id = int(plan_id_raw)
        suite_id = int(suite_id_raw)
    except ValueError:
        print("AZURE DEVOPS CONNECTION: FAIL")
        print("Invalid Plan ID or Suite ID format (must be integers).")
        return 1

    client = AzureDevOpsClient.from_env()

    try:
        work_item = client.get_work_item(16017)
        print("AZURE DEVOPS CONNECTION: PASS")
    except AzureDevOpsError as exc:
        print("AZURE DEVOPS CONNECTION: FAIL")
        if exc.status_code == 401:
            print("Error: 401 Unauthorized")
        elif exc.status_code == 403:
            print("Error: 403 Forbidden")
        elif exc.status_code == 404:
            print("Error: 404 Work Item not found")
        else:
            print(f"Error: {exc}")
        return 1

    print()
    print_work_item_summary(work_item)

    try:
        test_cases = client.get_suite_test_cases(plan_id, suite_id)
    except AzureDevOpsError as exc:
        print()
        print("TEST SUITE:")
        print(f"Plan ID: {plan_id}")
        print(f"Suite ID: {suite_id}")
        if exc.status_code == 404:
            print("Error: invalid Plan ID or Suite ID (404 Not Found)")
        elif exc.status_code == 403:
            print("Error: 403 Forbidden while reading test suite")
        elif exc.status_code == 401:
            print("Error: 401 Unauthorized while reading test suite")
        else:
            print(f"Error: {exc}")
        return 1

    print()
    print("TEST SUITE:")
    print(f"Plan ID: {plan_id}")
    print(f"Suite ID: {suite_id}")
    print(f"Test Cases: {len(test_cases)}")
    print()
    print("Sample:")
    for tc in test_cases[:10]:
        print(f"{tc['id']} - {tc['title']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
