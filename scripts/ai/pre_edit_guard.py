#!/usr/bin/env python3
"""Claude Code PreToolUse guard for Edit|Write|MultiEdit (wired in .claude/settings.json).

Reads the hook JSON on stdin. Exit codes (Claude Code contract):
  0 = allow, 2 = block (stderr is shown to the agent).
Blocks:
  * edits to test files (test_globs in .ai/config.yml) unless the owner ran
    scripts/ai/unlock-tests.sh (marker: <git-dir>/ai-tests-unlocked)
  * edits to guardrail files (guardrail_globs) unless the owner ran
    scripts/ai/unlock-guardrails.sh (marker: <git-dir>/ai-guardrails-unlocked)
  * writes that ADD placeholder text (TODO, '...rest of code', lorem ipsum, ...)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
sys.dont_write_bytecode = True  # never leave __pycache__ in the repo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pathrules  # noqa: E402
import patterns  # noqa: E402


def git_dir(root: str) -> str:
    try:
        out = subprocess.run(["git", "-C", root, "rev-parse", "--absolute-git-dir"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return os.path.join(root, ".git")


def collect_text(tool_name: str, tool_input: dict, abs_path: str):
    """Return (new_text, old_text) for the proposed change."""
    if tool_name == "Write":
        old = ""
        if os.path.isfile(abs_path):
            with open(abs_path, encoding="utf-8", errors="replace") as fh:
                old = fh.read()
        return tool_input.get("content", "") or "", old
    if tool_name == "Edit":
        return tool_input.get("new_string", "") or "", tool_input.get("old_string", "") or ""
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits") or []
        return ("\n".join(e.get("new_string", "") or "" for e in edits),
                "\n".join(e.get("old_string", "") or "" for e in edits))
    return "", ""


def decide(payload: dict, root: str) -> tuple[int, str]:
    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        return 0, ""
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    if not file_path:
        return 0, ""
    abs_path = file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
    rel = os.path.relpath(os.path.realpath(abs_path), os.path.realpath(root))
    if rel.startswith(".."):
        return 2, f"BLOCKED: {file_path} is outside the repository."
    cfg = os.path.join(root, ".ai", "config.yml")
    gdir = git_dir(root)
    if pathrules.is_guardrail(rel, cfg) and not os.path.exists(os.path.join(gdir, "ai-guardrails-unlocked")):
        return 2, (f"BLOCKED: {rel} is a guardrail file (guardrail_globs in .ai/config.yml). "
                   "Agents never edit guardrails. Ask the owner.")
    if pathrules.is_test(rel, cfg) and not os.path.exists(os.path.join(gdir, "ai-tests-unlocked")):
        return 2, (f"BLOCKED: {rel} is a test file. Tests are read-only during implementation "
                   "(docs/ai/TDD.md). Change the implementation, not the test.")
    new_text, old_text = collect_text(tool_name, tool_input, abs_path)
    found = patterns.find_new_placeholders(new_text, old_text)
    if found:
        return 2, (f"BLOCKED: the edit to {rel} adds placeholder text ({', '.join(sorted(set(found)))}). "
                   "Write the complete, real implementation; never elide code or leave TODOs.")
    return 0, ""


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        print(f"BLOCKED: pre-edit guard could not parse hook input ({exc}).", file=sys.stderr)
        return 2
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    code, msg = decide(payload, root)
    if msg:
        print(msg, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
