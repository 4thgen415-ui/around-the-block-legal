#!/usr/bin/env bash
# OWNER ONLY: restore write permission on test files so you can write the next
# failing tests (docs/ai/TDD.md step 1). Re-lock with scripts/ai/lock-tests.sh
# before handing the task to an agent.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
gitdir="$(git rev-parse --absolute-git-dir)"
count=0
while IFS= read -r -d '' f; do
  if python3 scripts/ai/pathrules.py is-test "$f" && [ -f "$f" ]; then
    chmod u+w -- "$f"
    count=$((count + 1))
  fi
done < <(git ls-files -z)
rm -f "$gitdir/ai-tests-locked"
touch "$gitdir/ai-tests-unlocked"
echo "unlock-tests: $count test file(s) writable. Run scripts/ai/lock-tests.sh when the test-only commit is done."
