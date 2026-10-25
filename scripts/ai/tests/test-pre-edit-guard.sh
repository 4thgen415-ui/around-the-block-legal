#!/usr/bin/env bash
# Feeds sample Claude Code PreToolUse JSON payloads to scripts/ai/pre-edit-guard.sh
# inside a throwaway git repo and asserts the exit code (0 allow, 2 block).
# Usage: scripts/ai/tests/test-pre-edit-guard.sh   (exit 0 = all cases passed)
set -euo pipefail
src="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'chmod -R u+w "$tmp"; rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q -b staging
mkdir -p scripts src tests .ai
cp -R "$src" scripts/ai
rm -rf scripts/ai/tests
printf 'export const a = 1;\n' > src/app.ts
printf 'test("a", () => {});\n' > tests/app.test.ts
export CLAUDE_PROJECT_DIR="$tmp"
guard="$tmp/scripts/ai/pre-edit-guard.sh"
pass=0
fail=0

check() { # name expected_exit json
  local name="$1" want="$2" json="$3" got=0 err
  err="$(printf '%s' "$json" | "$guard" 2>&1 >/dev/null)" || got=$?
  if [ "$got" -eq "$want" ]; then
    pass=$((pass + 1)); printf 'ok   %-46s exit=%s %s\n' "$name" "$got" "${err:+| ${err%%$'\n'*}}"
  else
    fail=$((fail + 1)); printf 'FAIL %-46s exit=%s want=%s %s\n' "$name" "$got" "$want" "$err"
  fi
}
p() { printf '{"hook_event_name":"PreToolUse","cwd":"%s","tool_name":"%s","tool_input":%s}' "$tmp" "$1" "$2"; }

check "edit app code"                       0 "$(p Edit '{"file_path":"'"$tmp"'/src/app.ts","old_string":"1","new_string":"2"}')"
check "write new app file"                  0 "$(p Write '{"file_path":"'"$tmp"'/src/new.ts","content":"export const b = 2;\n"}')"
check "edit test file (locked)"             2 "$(p Edit '{"file_path":"'"$tmp"'/tests/app.test.ts","old_string":"a","new_string":"b"}')"
check "multiedit test file (locked)"        2 "$(p MultiEdit '{"file_path":"tests/app.test.ts","edits":[{"old_string":"a","new_string":"b"}]}')"
check "create *.spec.ts (locked)"           2 "$(p Write '{"file_path":"'"$tmp"'/src/x.spec.ts","content":"x"}')"
check "edit guardrail AGENTS.md"            2 "$(p Edit '{"file_path":"'"$tmp"'/AGENTS.md","old_string":"a","new_string":"b"}')"
check "edit .claude/settings.json"          2 "$(p Write '{"file_path":"'"$tmp"'/.claude/settings.json","content":"{}"}')"
check "edit workflow"                       2 "$(p Write '{"file_path":"'"$tmp"'/.github/workflows/x.yml","content":"x"}')"
check "path outside repo"                   2 "$(p Write '{"file_path":"/etc/hosts","content":"x"}')"
check "path traversal"                      2 "$(p Write '{"file_path":"'"$tmp"'/src/../../escape.ts","content":"x"}')"
check "adds TODO placeholder"               2 "$(p Edit '{"file_path":"'"$tmp"'/src/app.ts","old_string":"1","new_string":"1 // TODO later"}')"
check "adds '... rest of code' elision"     2 "$(p Write '{"file_path":"'"$tmp"'/src/app.ts","content":"// ... existing code\nexport const a = 1;\n"}')"
check "adds fake id"                        2 "$(p Edit '{"file_path":"'"$tmp"'/src/app.ts","old_string":"1","new_string":"\"user_123\""}')"
check "invalid JSON blocks"                 2 'not json'
check "other tool (Read) ignored"           0 "$(p Read '{"file_path":"'"$tmp"'/tests/app.test.ts"}')"

touch "$(git rev-parse --absolute-git-dir)/ai-tests-unlocked"
check "edit test file after owner unlock"   0 "$(p Edit '{"file_path":"'"$tmp"'/tests/app.test.ts","old_string":"a","new_string":"b"}')"
touch "$(git rev-parse --absolute-git-dir)/ai-guardrails-unlocked"
check "edit AGENTS.md after owner unlock"   0 "$(p Edit '{"file_path":"'"$tmp"'/AGENTS.md","old_string":"a","new_string":"b"}')"

echo "pre-edit-guard: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
