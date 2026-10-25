"""Git fixture helpers for the guardrail unit tests (stdlib only)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

AI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(AI_DIR))

CONFIG = """test_globs:
  - "**/*.test.*"
  - "tests/**"
  - "**/test_*.py"
default_max_lines: 200
max_lines_ceiling: 400
module_max_lines: 30
module_max_symbols: 4
"""


def sh(cwd: str, *args: str, check: bool = True, env: dict | None = None, input: str | None = None):
    full_env = dict(os.environ, GIT_AUTHOR_NAME="Owner", GIT_AUTHOR_EMAIL="owner@example.com",
                    GIT_COMMITTER_NAME="Owner", GIT_COMMITTER_EMAIL="owner@example.com",
                    GITHUB_ACTIONS="")
    # Hermetic: drop CI context (GITHUB_REPOSITORY, GITHUB_STEP_SUMMARY, ...) so tests
    # behave the same locally and inside GitHub Actions.
    for key in [k for k in full_env if k.startswith(("GITHUB_", "RUNNER_"))]:
        full_env.pop(key)
    if env:
        full_env.update(env)
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, check=check,
                          env=full_env, input=input)


class GitRepo:
    """Temp repo whose `main` already contains scripts/ai + .ai/config.yml."""

    def __init__(self, files: dict | None = None, config: str = CONFIG):
        self.path = tempfile.mkdtemp(prefix="guardrail-test-")
        sh(self.path, "git", "init", "-q", "-b", "main")
        sh(self.path, "git", "config", "core.autocrlf", "false")
        shutil.copytree(AI_DIR, os.path.join(self.path, "scripts", "ai"),
                        ignore=shutil.ignore_patterns("__pycache__", "tests"))
        self.write(".ai/config.yml", config)
        for p, c in (files or {}).items():
            self.write(p, c)
        self.commit("base", all_files=True)
        self.base = self.head()

    def write(self, rel: str, content: str, newline: str | None = "") -> None:
        full = os.path.join(self.path, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(content)

    def delete(self, rel: str) -> None:
        os.remove(os.path.join(self.path, rel))

    def commit(self, msg: str, all_files: bool = True, env: dict | None = None) -> str:
        sh(self.path, "git", "add", "-A")
        sh(self.path, "git", "commit", "-q", "--no-verify", "-m", msg, env=env)
        return self.head()

    def head(self) -> str:
        return sh(self.path, "git", "rev-parse", "HEAD").stdout.strip()

    def run(self, *args: str, check: bool = False, env: dict | None = None, input: str | None = None):
        return sh(self.path, *args, check=check, env=env, input=input)

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
