#!/usr/bin/env bash
# ship.sh - the SHIP gate (AGENTS.md "Work modes: SANDBOX (default) and SHIP").
# Run only when the owner says "push this", "ship it" or "deploy". SANDBOX, the
# default, never runs this; it uses one quick check of under ~1 minute instead.
# Exits non-zero when anything fails; nothing merges to main until it passes.
# Usage: scripts/ai/ship.sh [BASE]   full suite + every guardrail check vs BASE (default origin/main)
#        scripts/ai/ship.sh --suite  full suite only (lint, typecheck, test, build)
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 2
export AI_MODE=ship
if [ "${1:-}" = "--suite" ]; then
  exec scripts/ai/run-checks.sh all
fi
base="${1:-origin/main}"
failed=()
step() {
  local name="$1"; shift
  echo "=== $name"
  if "$@"; then echo "--- PASS $name"; else echo "--- FAIL $name"; failed+=("$name"); fi
}
step "full suite (lint, typecheck, test, build)" scripts/ai/run-checks.sh all
# Guardrail self-tests build fixture repos with their own hooks; run them in the
# default mode so a fixture commit does not start this repo's full suite.
step "guardrail unit tests" env -u AI_MODE python3 -m unittest discover -s scripts/ai/tests -p 'test_*.py'
step "pre-edit guard tests" env -u AI_MODE scripts/ai/tests/test-pre-edit-guard.sh
step "honest-empty helper tests" npx --yes tsx --test scripts/ai/tests/honestEmpty.check.mjs
step "review rules" scripts/ai/review-rules.sh --diff "$base"
step "tests untouched" scripts/ai/check-tests-untouched.sh "$base"
step "editlint" python3 scripts/ai/editlint.py --base "$base"
step "module lint" python3 scripts/ai/module_lint.py --base "$base"
step "backstops" python3 scripts/ai/backstops/check_output.py --diff "$base"
echo
if [ "${#failed[@]}" -gt 0 ]; then
  echo "SHIP BLOCKED: ${failed[*]}"
  exit 1
fi
echo "SHIP CHECKS PASSED (base $base)"
