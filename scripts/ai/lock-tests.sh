#!/usr/bin/env bash
# Make every tracked test file read-only (chmod a-w) for the implementation phase
# and remove the owner's unlock marker. Undo with scripts/ai/unlock-tests.sh.
# Test files = test_globs in .ai/config.yml (see scripts/ai/pathrules.py).
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
gitdir="$(git rev-parse --absolute-git-dir)"
count=0
while IFS= read -r -d '' f; do
  if python3 scripts/ai/pathrules.py is-test "$f" && [ -f "$f" ]; then
    chmod a-w -- "$f"
    count=$((count + 1))
  fi
done < <(git ls-files -z)
rm -f "$gitdir/ai-tests-unlocked"
touch "$gitdir/ai-tests-locked"
echo "lock-tests: $count test file(s) are now read-only; agent edits to tests are blocked."
