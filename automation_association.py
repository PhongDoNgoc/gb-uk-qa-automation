from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def associate_generated_tests(
    *,
    client: Any,
    manifest_path: str,
    test_storage: str | None,
    test_type: str,
    overwrite: bool,
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)

    storage_name = (test_storage or manifest.get("assembly_name") or "").strip()
    if not storage_name:
        raise ValueError("Test storage could not be resolved. Provide --test-storage or ensure the manifest has assembly_name.")

    normalized_type = test_type.strip() or "NUnit"
    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for test_entry in manifest.get("tests") or []:
        test_case_id = int(test_entry["test_case_id"])
        automated_test_name = str(test_entry.get("fully_qualified_name") or "").strip()
        if not automated_test_name:
            raise ValueError(f"Manifest entry for test case {test_case_id} is missing fully_qualified_name.")

        current = client.get_test_case(test_case_id)
        current_name = str(current.get("automated_test_name") or "").strip()
        current_storage = str(current.get("automated_test_storage") or "").strip()
        current_type = str(current.get("automated_test_type") or "").strip()

        if (
            current_name == automated_test_name
            and current_storage == storage_name
            and current_type == normalized_type
        ):
            skipped.append(
                {
                    "test_case_id": test_case_id,
                    "status": "already-associated",
                    "fully_qualified_name": automated_test_name,
                    "test_storage": storage_name,
                    "test_type": normalized_type,
                }
            )
            continue

        has_conflict = bool(current_name or current_storage or current_type)
        if has_conflict and not overwrite:
            raise ValueError(
                f"Test case {test_case_id} is already associated with "
                f"{current_name or '<unknown>'} in {current_storage or '<unknown>'}. "
                "Use --overwrite-association to replace it."
            )

        client.associate_automated_test(
            test_case_id,
            automated_test_name=automated_test_name,
            automated_test_storage=storage_name,
            automated_test_type=normalized_type,
        )
        updated.append(
            {
                "test_case_id": test_case_id,
                "status": "associated",
                "fully_qualified_name": automated_test_name,
                "test_storage": storage_name,
                "test_type": normalized_type,
            }
        )

    return {
        "manifest_path": str(Path(manifest_path)),
        "suite_id": manifest.get("suite_id"),
        "plan_id": manifest.get("plan_id"),
        "test_storage": storage_name,
        "test_type": normalized_type,
        "updated": updated,
        "skipped": skipped,
    }


def _load_manifest(path: str) -> dict[str, Any]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Automation manifest is not a JSON object.")
    if not isinstance(manifest.get("tests"), list) or not manifest["tests"]:
        raise ValueError("Automation manifest does not contain any generated tests.")
    return manifest
