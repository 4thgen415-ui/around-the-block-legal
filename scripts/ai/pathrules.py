#!/usr/bin/env python3
"""Path classification shared by the AI guardrail scripts.

Globs come from .ai/config.yml:
  test_globs       files that count as tests (read-only for agents)
  guardrail_globs  guardrail files agents must not edit
  ignore_globs     generated/vendored files skipped by the linters

CLI:  python3 scripts/ai/pathrules.py classify   (reads paths on stdin)
      prints "<test|guardrail|code> <path>" per line.
      python3 scripts/ai/pathrules.py is-test PATH   (exit 0 if test)
      python3 scripts/ai/pathrules.py is-guardrail PATH
"""
from __future__ import annotations

import functools
import os
import re
import sys
sys.dont_write_bytecode = True  # never leave __pycache__ in the repo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aiconfig  # noqa: E402

DEFAULT_TEST_GLOBS = [
    "**/*.test.*", "**/*.spec.*", "**/__tests__/**", "**/test_*.py",
    "**/*_test.py", "tests/**", "test/**", "e2e/**", "**/tests/**",
    "**/test/**", "**/e2e/**",
]
DEFAULT_GUARDRAIL_GLOBS = [
    "AGENTS.md", "CLAUDE.md", ".ai/config.yml", ".claude/**",
    ".cursor/rules/**", ".github/workflows/**", "scripts/ai/**",
    "docs/ai/**", ".githooks/**",
]
DEFAULT_IGNORE_GLOBS = [
    "**/node_modules/**", "**/dist/**", "**/build/**", "**/.next/**",
    "**/*.min.js", "**/package-lock.json", "**/pnpm-lock.yaml",
    "**/yarn.lock", "**/uv.lock", "**/*.lock", "**/vendor/**",
]


@functools.lru_cache(maxsize=None)
def glob_to_regex(glob: str) -> re.Pattern:
    i, out = 0, []
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(path: str, globs) -> bool:
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return any(glob_to_regex(g).match(path) for g in globs)


@functools.lru_cache(maxsize=None)
def _cfg(config_path: str = aiconfig.DEFAULT_CONFIG) -> dict:
    return aiconfig.load(config_path)


def globs(kind: str, config_path: str = aiconfig.DEFAULT_CONFIG) -> list:
    defaults = {"test": DEFAULT_TEST_GLOBS, "guardrail": DEFAULT_GUARDRAIL_GLOBS,
                "ignore": DEFAULT_IGNORE_GLOBS}[kind]
    return list(_cfg(config_path).get(f"{kind}_globs") or defaults)


def is_test(path: str, config_path: str = aiconfig.DEFAULT_CONFIG) -> bool:
    return matches(path, globs("test", config_path))


def is_guardrail(path: str, config_path: str = aiconfig.DEFAULT_CONFIG) -> bool:
    return matches(path, globs("guardrail", config_path))


def is_ignored(path: str, config_path: str = aiconfig.DEFAULT_CONFIG) -> bool:
    return matches(path, globs("ignore", config_path))


def classify(path: str, config_path: str = aiconfig.DEFAULT_CONFIG) -> str:
    if is_guardrail(path, config_path):
        return "guardrail"
    if is_test(path, config_path):
        return "test"
    return "code"


def main(argv: list[str]) -> int:
    if argv[:1] == ["classify"]:
        for line in sys.stdin:
            p = line.strip()
            if p:
                print(f"{classify(p)} {p}")
        return 0
    if len(argv) == 2 and argv[0] == "is-test":
        return 0 if is_test(argv[1]) else 1
    if len(argv) == 2 and argv[0] == "is-guardrail":
        return 0 if is_guardrail(argv[1]) else 1
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
