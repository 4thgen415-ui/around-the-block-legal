#!/usr/bin/env python3
"""auto_revert.py - revert a bad commit on main THROUGH staging (no new branches).

Called by .github/workflows/agent-pr-loop.yml when the post-merge
ai-guardrails run on main fails. Steps:
  1. fetch main + staging from the remote
  2. if staging is behind main (no unique commits) fast-forward it to main
     (plain push, no force); if staging has diverged, stop and report
  3. on staging: git revert --no-edit [-m 1] <bad-sha>, push staging (no force)
  4. open (or reuse) the staging -> main PR so CI + auto-merge land the revert
Never touches main directly and never creates a branch.

Usage: auto_revert.py --bad-sha SHA [--remote origin] [--dry-run] [--no-pr]
Exit: 0 reverted (or dry-run plan printed), 1 refused/failed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
sys.dont_write_bytecode = True  # never leave __pycache__ in the repo


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, check=check)


def git(*args: str, check: bool = True) -> str:
    return run("git", *args, check=check).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bad-sha", required=True)
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-pr", action="store_true")
    a = ap.parse_args(argv)
    r = a.remote
    git("fetch", "--quiet", r, "main", "staging")
    main_ref, staging_ref = f"{r}/main", f"{r}/staging"
    if run("git", "merge-base", "--is-ancestor", a.bad_sha, main_ref, check=False).returncode != 0:
        print(f"auto_revert: {a.bad_sha} is not on {main_ref}; refusing.")
        return 1
    plan = []
    if run("git", "merge-base", "--is-ancestor", main_ref, staging_ref, check=False).returncode != 0:
        unique = git("rev-list", f"{main_ref}..{staging_ref}")
        if unique:
            print("auto_revert: staging has diverged from main with its own commits; refusing to rewrite it. "
                  "Owner/agent must rebase staging first. Unique commits:\n" + unique)
            return 1
        plan.append(f"fast-forward staging to {main_ref}")
    parents = git("rev-list", "--parents", "-n", "1", a.bad_sha).split()
    revert = ["git", "revert", "--no-edit"] + (["-m", "1"] if len(parents) > 2 else []) + [a.bad_sha]
    plan.append(" ".join(revert) + " (on staging)")
    plan.append(f"git push {r} HEAD:staging (no force)")
    if not a.no_pr:
        plan.append("gh pr create --base main --head staging (if none open)")
    print("auto_revert plan:\n  " + "\n  ".join(plan))
    if a.dry_run:
        return 0
    start = main_ref if plan[0].startswith("fast-forward") else staging_ref
    git("checkout", "--quiet", "-B", "staging", start)
    res = run(*revert, check=False)
    if res.returncode != 0:
        run("git", "revert", "--abort", check=False)
        print(f"auto_revert: revert failed (conflict?):\n{res.stdout}\n{res.stderr}")
        return 1
    push = run("git", "push", r, "HEAD:staging", check=False)
    if push.returncode != 0:
        print(f"auto_revert: push to staging failed:\n{push.stderr}")
        return 1
    if not a.no_pr:
        existing = run("gh", "pr", "list", "--base", "main", "--head", "staging", "--state", "open",
                       "--json", "number", "--jq", ".[0].number", check=False).stdout.strip()
        if not existing:
            run("gh", "pr", "create", "--base", "main", "--head", "staging",
                "--title", f"Revert {a.bad_sha[:10]} (post-merge CI failed on main)",
                "--body", f"Automated revert of {a.bad_sha} via staging because ai-guardrails failed on main.",
                check=False)
    print(f"auto_revert: reverted {a.bad_sha} on staging.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
