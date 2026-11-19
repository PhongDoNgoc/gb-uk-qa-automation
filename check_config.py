from dotenv import load_dotenv
import os


REQUIRED_VARS = [
    "AZDO_ORG",
    "AZDO_PROJECT",
    "AZDO_PAT",
    "AZDO_ASSIGNED_TO",
    "REPO_PATH",
]

OPTIONAL_VARS = [
    "AZDO_QA_USER",
    "AZDO_PLAN_ID",
    "AZDO_SUITE_ID",
    "AZDO_TEAM",
    "AZDO_QA_USER_ID",
    "AZDO_QA_USER_DESCRIPTOR",
]


def display_value(name: str, value: str | None) -> str:
    if name == "AZDO_PAT":
        return "FOUND" if value else "MISSING"
    return value if value else "MISSING"


def main() -> None:
    # Loads variables from local .env only; no network or git operations.
    load_dotenv()

    for var in REQUIRED_VARS:
        value = os.getenv(var)
        if value is not None:
            value = value.strip()
        print(f"{var}: {display_value(var, value)}")

    print("\nOptional:")
    for var in OPTIONAL_VARS:
        value = os.getenv(var)
        if value is not None:
            value = value.strip()
        print(f"{var}: {display_value(var, value)}")


if __name__ == "__main__":
    main()
