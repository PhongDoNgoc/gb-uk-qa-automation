from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from generated_script_commit import commit_generated_suite


class GeneratedScriptCommitTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = Path(self.temp_dir.name)
        self.project = self.repository / "QA.Regression.Automation"
        self.suite = self.project / "Tests" / "Generated" / "Suite31681"
        self.suite.mkdir(parents=True)
        self._git("init", "-q")
        self._git("remote", "add", "origin", "https://github.com/example/repo.git")
        self._git(
            "config",
            "http.https://github.com/.extraheader",
            "AUTHORIZATION: basic persisted-checkout-credential",
        )
        self._git("config", "user.name", "Test User")
        self._git("config", "user.email", "test@example.com")
        (self.suite / "Tc1.cs").write_text("class Tc1 {}", encoding="utf-8")
        self._git("add", "--all")
        self._git("commit", "-q", "-m", "baseline")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.repository, check=True,
            capture_output=True, text=True,
        )

    def _environment(self, **overrides: str) -> dict[str, str]:
        return {
            "BUILD_SOURCEBRANCH": "refs/heads/main",
            **overrides,
        }

    def test_commits_only_changed_suite_files_and_pushes_to_triggering_branch(self):
        (self.suite / "Tc1.cs").write_text("class Tc1 { int Updated => 1; }", encoding="utf-8")
        unrelated = self.project / "Tests" / "LoginPageTests.cs"
        unrelated.write_text("uncommitted unrelated change", encoding="utf-8")
        self._git("add", "--", str(unrelated.relative_to(self.repository)))
        calls = []
        real_run = subprocess.run

        def run_git(command, **kwargs):
            calls.append((command, kwargs))
            if command[:2] == ["git", "push"]:
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            return real_run(command, **kwargs)

        with patch("generated_script_commit.subprocess.run", side_effect=run_git):
            committed = commit_generated_suite(
                suite_id=31681,
                project_dir=str(self.project),
                environ=self._environment(),
            )

        self.assertTrue(committed)
        self.assertEqual(self._git("log", "-1", "--format=%s").stdout.strip(),
                         "Update generated automation for Test Plan suite 31681")
        staged = self._git("diff", "--cached", "--name-only").stdout.splitlines()
        self.assertEqual(staged, ["QA.Regression.Automation/Tests/LoginPageTests.cs"])
        committed_files = self._git("show", "--format=", "--name-only", "HEAD").stdout.splitlines()
        self.assertEqual(committed_files, ["QA.Regression.Automation/Tests/Generated/Suite31681/Tc1.cs"])
        self.assertIn("uncommitted unrelated change", unrelated.read_text(encoding="utf-8"))
        push_command, push_kwargs = next((command, kwargs) for command, kwargs in calls if command[:2] == ["git", "push"])
        self.assertEqual(push_command[-2:], ["origin", "HEAD:refs/heads/main"])
        self.assertNotIn("GITHUB_PUSH_TOKEN", push_kwargs.get("env", {}))
        self.assertEqual(push_kwargs["env"]["BUILD_SOURCEBRANCH"], "refs/heads/main")

    def test_skips_empty_commit_when_generated_scripts_are_unchanged(self):
        with patch("generated_script_commit.subprocess.run", wraps=subprocess.run) as run:
            committed = commit_generated_suite(
                suite_id=31681, project_dir=str(self.project), environ=self._environment())

        self.assertFalse(committed)
        self.assertFalse(any(call.args[0][:2] == ["git", "push"] for call in run.call_args_list))

    def test_requires_source_branch(self):
        with self.assertRaisesRegex(ValueError, "source ref"):
            commit_generated_suite(suite_id=31681, project_dir=str(self.project), environ={})

    def test_requires_persisted_checkout_credentials_when_changes_exist(self):
        (self.suite / "Tc1.cs").write_text("class Tc1 { int Updated => 1; }", encoding="utf-8")
        self._git("config", "--unset-all", "http.https://github.com/.extraheader")
        with self.assertRaisesRegex(ValueError, "checkout credentials are not persisted"):
            commit_generated_suite(
                suite_id=31681,
                project_dir=str(self.project),
                environ=self._environment(),
            )

    def test_does_not_push_to_non_github_remote(self):
        self._git("remote", "set-url", "origin", "https://example.invalid/repo.git")
        with self.assertRaisesRegex(ValueError, "non-GitHub origin"):
            commit_generated_suite(
                suite_id=31681, project_dir=str(self.project), environ=self._environment())


if __name__ == "__main__":
    unittest.main()
