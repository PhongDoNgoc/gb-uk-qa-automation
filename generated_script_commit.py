from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


def commit_generated_suite(
    *,
    suite_id: int,
    project_dir: str,
    environ: Mapping[str, str] | None = None,
) -> bool:
    environment = dict(os.environ if environ is None else environ)

    source_branch = environment.get("BUILD_SOURCEBRANCH", "").strip()
    if not source_branch.startswith("refs/heads/") or len(source_branch) <= len("refs/heads/"):
        raise ValueError(
            f"Cannot commit generated scripts for source ref '{source_branch or '<missing>'}'; "
            "run the pipeline from a branch."
        )

    project_path = Path(project_dir).resolve()
    root_result = _run_git(["rev-parse", "--show-toplevel"], cwd=project_path)
    repository_root = Path(root_result.stdout.strip()).resolve()
    suite_path = (project_path / "Tests" / "Generated" / f"Suite{int(suite_id)}").resolve()
    try:
        relative_suite_path = suite_path.relative_to(repository_root)
    except ValueError as exc:
        raise ValueError(f"Generated suite directory '{suite_path}' is outside repository '{repository_root}'.") from exc
    if not suite_path.is_dir():
        raise FileNotFoundError(f"Generated suite directory was not found: {suite_path}")

    remote = _run_git(["remote", "get-url", "origin"], cwd=repository_root).stdout.strip()
    remote_host = urlparse(remote).hostname
    if remote_host is None and remote.casefold().startswith("git@github.com:"):
        remote_host = "github.com"
    if (remote_host or "").casefold() != "github.com":
        raise ValueError(f"Refusing to push generated scripts to a non-GitHub origin: {remote}")

    pathspec = relative_suite_path.as_posix()
    _run_git(["add", "--all", "--", pathspec], cwd=repository_root, env=environment)
    changed = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", pathspec],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if changed.returncode == 0:
        print(f"Generated scripts for suite {suite_id} are unchanged; no commit is needed.", flush=True)
        return False
    if changed.returncode != 1:
        raise ValueError(f"Could not inspect staged generated-script changes: {changed.stderr.strip()}")

    auth_check = subprocess.run(
        ["git", "config", "--get-urlmatch", "http.extraheader", remote],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if auth_check.returncode != 0 or not auth_check.stdout.strip():
        raise ValueError(
            "GitHub checkout credentials are not persisted for this job. "
            "Add 'checkout: self' with 'persistCredentials: true' and ensure the GitHub service connection "
            "has permission to push to the source branch."
        )

    _run_git(["config", "user.name", "Azure Pipelines Automation"], cwd=repository_root)
    _run_git(
        ["config", "user.email", "azure-pipelines@users.noreply.github.com"],
        cwd=repository_root,
    )
    _run_git(
        [
            "commit",
            "-m",
            f"Update generated automation for Test Plan suite {suite_id}",
            "--only",
            "--",
            pathspec,
        ],
        cwd=repository_root,
        env=environment,
    )
    branch = source_branch.removeprefix("refs/heads/")
    _run_git(["push", "origin", f"HEAD:refs/heads/{branch}"], cwd=repository_root, env=environment)
    print(f"Committed and pushed generated scripts for suite {suite_id} to branch {branch}.", flush=True)
    return True

def _run_git(
    arguments: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        raise ValueError(f"Git command 'git {' '.join(arguments)}' failed: {details}")
    return result
