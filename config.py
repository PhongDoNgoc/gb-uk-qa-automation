from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class AppConfig:
    org: str
    project: str
    pat: str
    qa_assigned_to: str
    repo_path: Path | None
    plan_id: int | None
    reviews_dir: Path


def load_config() -> AppConfig:
    load_dotenv()
    plan_raw = (os.getenv("AZDO_PLAN_ID") or "").strip()
    repo_raw = (os.getenv("REPO_PATH") or "").strip()
    return AppConfig(
        org=(os.getenv("AZDO_ORG") or "").strip(),
        project=(os.getenv("AZDO_PROJECT") or "").strip(),
        pat=(os.getenv("AZDO_PAT") or "").strip(),
        qa_assigned_to=(os.getenv("AZDO_ASSIGNED_TO") or os.getenv("AZDO_QA_USER") or "").strip(),
        repo_path=Path(repo_raw) if repo_raw else None,
        plan_id=int(plan_raw) if plan_raw.isdigit() else None,
        reviews_dir=Path("reviews"),
    )


def validate_required(*names: str) -> list[str]:
    missing: list[str] = []
    for name in names:
        if not (os.getenv(name) or "").strip():
            missing.append(name)
    return missing


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
