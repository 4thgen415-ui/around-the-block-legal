#!/usr/bin/env python3
"""Deterministic backstops against fabricated agent output (stdlib only).

Checks a piece of agent-written text (PR body, commit messages, final chat
message) and/or the lines added by a change:
  * claims        - "tests pass", "build succeeded", "CI is green" ... without
                    evidence (a fenced block of command output or a link to a
                    GitHub Actions run)
  * urls          - http(s) URLs that appear nowhere in the repository, are not
                    this repo's GitHub URLs and are not on backstop_allow_hosts
                    (.ai/config.yml) -> likely invented citations
  * citations     - numbered citations like [1] with no matching source line
  * placeholder-id- invented-looking IDs (all-zero UUIDs, user_123, abc123 ...)
                    in text or in added non-test code lines

Modes:
  check_output.py --text-file FILE [--diff BASE]
  check_output.py --diff BASE
  check_output.py --claude-stop        (Claude Code Stop hook; stdin = hook JSON)
  check_output.py --claude-post-tool   (Claude Code PostToolUse hook; stdin = hook JSON)
Exit: 0 clean, 1 findings (CLI), 2 findings (Claude hooks: makes the agent fix them).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
sys.dont_write_bytecode = True  # never leave __pycache__ in the repo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import aiconfig  # noqa: E402
import pathrules  # noqa: E402
import patterns  # noqa: E402

URL_RX = re.compile(r"https?://[^\s)\]>'\"`]+")
DEFAULT_ALLOW_HOSTS = ["localhost", "127.0.0.1", "example.com"]


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def repo_slug() -> str:
    slug = os.environ.get("GITHUB_REPOSITORY", "")
    if slug:
        return slug.lower()
    url = git("remote", "get-url", "origin").stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
    return m.group(1).lower() if m else ""


def url_known(url: str, allow_hosts: list) -> bool:
    url = url.rstrip(".,;:!?")
    host = re.sub(r"^https?://", "", url).split("/")[0].split(":")[0].lower()
    if any(host == h or host.endswith("." + h) for h in allow_hosts):
        return True
    slug = repo_slug()
    if slug and re.match(rf"https?://github\.com/{re.escape(slug)}(/|$)", url, re.I):
        return True
    return git("grep", "-qF", url).returncode == 0


def check_text(text: str, cfg: dict) -> list[str]:
    findings = []
    has_evidence = any(re.search(p, text) for p in patterns.EVIDENCE_PATTERNS)
    for p in patterns.CLAIM_PATTERNS:
        m = re.search(p, text)
        if m and not has_evidence:
            findings.append(f"claim without evidence: '{m.group(0)}' - paste the command output "
                            "(fenced block) or link the CI run")
            break
    allow_hosts = list(cfg.get("backstop_allow_hosts") or []) + DEFAULT_ALLOW_HOSTS
    for url in sorted(set(URL_RX.findall(text))):
        if not url_known(url, allow_hosts):
            findings.append(f"url not found in the repo or allowlist (possible invented citation): {url}")
    cites = set(re.findall(r"(?<![\w\]])\[(\d{1,2})\](?!\()", text))
    for n in sorted(cites):
        if not re.search(rf"^\s*\[{n}\][:\s].*(https?://|\S+\.\w+)", text, re.M):
            findings.append(f"citation [{n}] has no source line")
    for rx, label in patterns.compiled(patterns.PLACEHOLDER_ID_PATTERNS):
        m = rx.search(text)
        if m:
            findings.append(f"{label} in text: '{m.group(0)}'")
    return findings


def check_diff(base: str) -> list[str]:
    mb = git("merge-base", base, "HEAD").stdout.strip()
    if not mb:
        return [f"cannot compute merge-base with {base}"]
    out = git("diff", "-U0", "--no-color", mb, "HEAD").stdout
    findings, current = [], None
    id_rx = patterns.compiled(patterns.PLACEHOLDER_ID_PATTERNS)
    for line in out.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
            if current and (pathrules.classify(current) != "code" or pathrules.is_ignored(current)):
                current = None
        elif current and line.startswith("+") and not line.startswith("+++"):
            for rx, label in id_rx:
                m = rx.search(line)
                if m:
                    findings.append(f"{current}: {label} '{m.group(0)}' in added code - read IDs from data, "
                                    "never invent them (see scripts/ai/helpers)")
    return findings


def last_message_from_hook(payload: dict) -> str:
    msg = payload.get("last_assistant_message")
    if isinstance(msg, str) and msg:
        return msg
    path = payload.get("transcript_path")
    text = ""
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = entry.get("message") or {}
                if entry.get("type") == "assistant" or message.get("role") == "assistant":
                    content = message.get("content")
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                        if any(parts):
                            text = "\n".join(parts)
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text-file")
    ap.add_argument("--diff")
    ap.add_argument("--claude-stop", action="store_true")
    ap.add_argument("--claude-post-tool", action="store_true")
    args = ap.parse_args(argv)
    root = git("rev-parse", "--show-toplevel").stdout.strip()
    if root:
        os.chdir(root)
    cfg = aiconfig.load()
    findings: list[str] = []

    if args.claude_stop or args.claude_post_tool:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError:
            return 0
        if args.claude_stop:
            if payload.get("stop_hook_active"):
                return 0  # already sent back once; never loop forever
            findings = check_text(last_message_from_hook(payload), cfg)
        else:
            ti = payload.get("tool_input") or {}
            path = ti.get("file_path", "")
            rel = os.path.relpath(path, root) if root and os.path.isabs(path) else path
            if rel and pathrules.classify(rel) == "code":
                text = ti.get("content") or ti.get("new_string") or "\n".join(
                    e.get("new_string", "") for e in ti.get("edits") or [])
                for rx, label in patterns.compiled(patterns.PLACEHOLDER_ID_PATTERNS):
                    m = rx.search(text or "")
                    if m:
                        findings.append(f"{rel}: {label} '{m.group(0)}' - do not invent IDs")
        if findings:
            print("Backstop findings (fix before finishing):\n- " + "\n- ".join(findings), file=sys.stderr)
            return 2
        return 0

    if args.text_file:
        with open(args.text_file, encoding="utf-8", errors="replace") as fh:
            findings += check_text(fh.read(), cfg)
    if args.diff:
        findings += check_diff(args.diff)
    if not (args.text_file or args.diff):
        ap.print_usage(sys.stderr)
        return 64
    for f in findings:
        print(f"FAIL {f}")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error title=backstops::{f}")
    print(f"backstops: {'FAILED' if findings else 'OK'} ({len(findings)} finding(s)).")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
