#!/usr/bin/env bash
# Deterministic TDD gate (docs/ai/TDD.md). Walks every non-merge commit in
# <merge-base(BASE, HEAD)>..HEAD and FAILS if:
#   1. a commit changes test files AND non-test files (mixed commit), or
#   2. a test-only commit comes AFTER the first implementation commit in the
#      range (tests may not change once implementation has started), or
#   3. .ai/config.yml lists test_authors and a test-only commit's author email
#      is not on that list.
# How the owner marks a test-only commit: commit ONLY test files (nothing else)
# before any implementation commit. There is no label or trailer bypass.
#
# Usage: scripts/ai/check-tests-untouched.sh [BASE_REF]   (default: origin/main)
set -euo pipefail

base="${1:-${BASE_REF:-origin/main}}"
root="$(git rev-parse --show-toplevel)"
cd "$root"

if ! git rev-parse --verify --quiet "$base^{commit}" >/dev/null; then
  echo "check-tests-untouched: base ref '$base' not found (fetch it first, e.g. git fetch origin main)." >&2
  exit 2
fi
if ! git cat-file -e "$base:scripts/ai/check-tests-untouched.sh" 2>/dev/null; then
  echo "check-tests-untouched: bootstrap - '$base' does not contain the guardrails yet; this range installs them, so the gate is skipped once."
  exit 0
fi

mb="$(git merge-base "$base" HEAD)"
mapfile -t authors < <(python3 scripts/ai/aiconfig.py get test_authors 2>/dev/null || true)

fail=0
seen_impl=""
checked=0
while IFS= read -r sha; do
  [ -n "$sha" ] || continue
  checked=$((checked + 1))
  tests=0
  other=0
  while IFS=' ' read -r kind path; do
    [ -n "$path" ] || continue
    if [ "$kind" = "test" ]; then tests=$((tests + 1)); else other=$((other + 1)); fi
  done < <(git diff-tree --no-commit-id --name-only -r "$sha" | python3 scripts/ai/pathrules.py classify)
  subject="$(git log -1 --format='%h %s' "$sha")"
  if [ "$tests" -gt 0 ] && [ "$other" -gt 0 ]; then
    echo "FAIL $subject: mixes $tests test file(s) with $other non-test file(s). Split tests into their own commit."
    fail=1
  elif [ "$tests" -gt 0 ]; then
    if [ -n "$seen_impl" ]; then
      echo "FAIL $subject: test-only commit after implementation commit $seen_impl. Tests are read-only once implementation starts."
      fail=1
    elif [ "${#authors[@]}" -gt 0 ]; then
      email="$(git log -1 --format='%ae' "$sha")"
      ok=""
      for a in "${authors[@]}"; do [ "$a" = "$email" ] && ok=1; done
      if [ -z "$ok" ]; then
        echo "FAIL $subject: test-only commit by $email, who is not in test_authors (.ai/config.yml)."
        fail=1
      else
        echo "ok   $subject: owner test-only commit"
      fi
    else
      echo "ok   $subject: test-only commit (before implementation)"
    fi
  elif [ "$other" -gt 0 ]; then
    [ -n "$seen_impl" ] || seen_impl="$(git rev-parse --short "$sha")"
    echo "ok   $subject: implementation commit (no test files)"
  fi
done < <(git rev-list --reverse --no-merges "$mb..HEAD")

if [ "$fail" -ne 0 ]; then
  echo "check-tests-untouched: FAILED (see docs/ai/TDD.md)."
  exit 1
fi
echo "check-tests-untouched: OK ($checked commit(s) checked against $base)."
