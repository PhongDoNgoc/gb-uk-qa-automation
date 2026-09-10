from __future__ import annotations

import argparse

from azure_client import AzureDevOpsClient
from config import load_config, setup_logging, validate_required
from reconciliation import reconcile_work_item


def main() -> int:
    parser = argparse.ArgumentParser(description="Deprecated wrapper for canonical reconcile command")
    parser.add_argument("--work-item", required=True, type=int)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    setup_logging(debug=args.debug)
    missing = validate_required("AZDO_ORG", "AZDO_PROJECT", "AZDO_PAT")
    if missing:
        print("CONFIG: FAIL")
        for name in missing:
            print(f"- {name}")
        return 1

    print("DEPRECATED: reconcile.py -> python main.py reconcile --work-item <ID>")
    cfg = load_config()
    client = AzureDevOpsClient.from_env()
    out = reconcile_work_item(client, cfg, int(args.work_item))
    print(f"Artifacts: {out['json_path']} | {out['txt_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
