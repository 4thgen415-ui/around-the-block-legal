#!/usr/bin/env bash
# review-rules.sh - review feedback encoded as deterministic detection rules.
#
# Usage:
#   scripts/ai/review-rules.sh --all            report every hit in tracked files (legacy audit)
#   scripts/ai/review-rules.sh --diff BASE      only lines ADDED since merge-base(BASE, HEAD)  [CI]
#   scripts/ai/review-rules.sh --staged         only lines added in the staged change   [pre-commit]
# Exit: 1 if any ERROR-severity hit is found in the selected lines, else 0.
# In --all mode hits are reported but the exit code is still 1 on errors, so use
# it as an audit, not a gate. Guardrail files and ignore_globs are skipped.
# Add a rule: append one `rule` line below (see scripts/ai/README.md).
set -euo pipefail

mode="${1:---all}"
base="${2:-origin/main}"
root="$(git rev-parse --show-toplevel)"
cd "$root"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
errors=0
warnings=0

# ---------------------------------------------------------------------------
# Line selection: for --diff/--staged, build "path:line" of added lines.
# ---------------------------------------------------------------------------
diff_added() {
  awk '
    /^\+\+\+ / { f = substr($0, 5); sub(/^b\//, "", f); next }
    /^@@ / {
      split($3, a, ","); start = substr(a[1], 2); n = (a[2] == "" ? 1 : a[2])
      for (i = 0; i < n; i++) print f ":" (start + i)
    }'
}
case "$mode" in
  --diff)
    mb="$(git merge-base "$base" HEAD)"
    git diff -U0 --no-color "$mb" HEAD | diff_added > "$work/added"
    grep_src=(git grep -nIE)
    grep_rev=(HEAD)
    ;;
  --staged)
    git diff --cached -U0 --no-color | diff_added > "$work/added"
    grep_src=(git grep --cached -nIE)
    grep_rev=()
    ;;
  --all)
    : > "$work/added"
    grep_src=(git grep -nIE)
    grep_rev=()
    ;;
  *) echo "usage: $0 --all | --diff BASE | --staged" >&2; exit 64 ;;
esac

# ---------------------------------------------------------------------------
# rule ID SEVERITY FILE_REGEX PATTERN MESSAGE
#   FILE_REGEX  regex (Python re / ERE subset) searched in the repo-relative path
#   PATTERN     grep -E regex matched against the line content
# ---------------------------------------------------------------------------
rule() {
  local id="$1" sev="$2" fre="$3" pat="$4" msg="$5"
  local hits="$work/hits.$id"
  # shellcheck disable=SC2068
  "${grep_src[@]}" -e "$pat" ${grep_rev[@]} -- . > "$hits.raw" 2>/dev/null || true
  # git grep on a revision prefixes "HEAD:"; strip it.
  sed -e 's/^HEAD://' "$hits.raw" | FRE="$fre" python3 -c '
import os, re, sys
rx = re.compile(os.environ["FRE"])
for line in sys.stdin:
    if rx.search(line.split(":", 1)[0]):
        sys.stdout.write(line)' > "$hits.f" || true
  : > "$hits"
  if [ -s "$hits.f" ]; then
    cut -d: -f1 "$hits.f" | sort -u | python3 scripts/ai/pathrules.py classify > "$work/cls"
    python3 - "$hits.f" "$work/cls" "$work/added" "$mode" > "$hits" <<'PY'
import os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, "scripts/ai")
import pathrules
hits, cls, added, mode = sys.argv[1:5]
kind = {}
for line in open(cls, encoding="utf-8"):
    k, _, p = line.rstrip("\n").partition(" ")
    kind[p] = k
want = set(open(added, encoding="utf-8").read().split()) if mode != "--all" else None
for line in open(hits, encoding="utf-8", errors="replace"):
    path, ln, _ = line.split(":", 2)
    if kind.get(path) == "guardrail" or pathrules.is_ignored(path):
        continue
    if want is not None and f"{path}:{ln}" not in want:
        continue
    sys.stdout.write(line)
PY
  fi
  local n
  n="$(wc -l < "$hits" | tr -d ' ')"
  if [ "$n" -gt 0 ]; then
    if [ "$sev" = "error" ]; then errors=$((errors + n)); else warnings=$((warnings + n)); fi
    echo "[$sev] $id ($n): $msg"
    head -n 25 "$hits" | cut -c1-220 | sed 's/^/    /'
    [ "$n" -le 25 ] || echo "    ... $((n - 25)) more"
    if [ -n "${GITHUB_ACTIONS:-}" ]; then
      local level=warning
      [ "$sev" = "error" ] && level=error
      head -n 50 "$hits" | while IFS=: read -r f l _; do
        echo "::$level file=$f,line=$l,title=review-rules/$id::$msg"
      done
    fi
  fi
}

CODE='\.(ts|tsx|js|jsx|mjs|cjs|py|vue|svelte|html|css)$'
JS='\.(ts|tsx|js|jsx|mjs|cjs)$'
TESTS='(\.test\.|\.spec\.|__tests__/|(^|/)tests?/|(^|/)e2e/|(^|/)test_[^/]*\.py$|_test\.py$)'
PRODCFG='(wrangler\.(toml|json|jsonc)|\.env\.production|(^|/)prod[^/]*\.(json|ya?ml|toml)|app\.json|eas\.json|capacitor\.config\.(ts|json))$'

rule placeholder         error "$CODE"  '(^|[^A-Za-z0-9_])(TODO|FIXME|TBD)([^A-Za-z0-9_]|$)|[Ll]orem [Ii]psum|\.\.\. ?(the )?rest of (the )?(code|file|implementation)|(//|#) ?\.\.\. ?(existing|unchanged|other) code' \
  "placeholder text (TODO/FIXME/lorem ipsum/elided code). Write the real thing."
rule console-log         error "$JS"    '(^|[^A-Za-z0-9_.])console\.(log|debug)\(' \
  "console.log/debug left in. Use the app's logger or remove it."
rule debugger            error "$JS"    '^[[:space:]]*debugger;?[[:space:]]*$' \
  "debugger statement."
rule py-breakpoint       error '\.py$'  '(^|[^A-Za-z0-9_])breakpoint\(\)|^[[:space:]]*import pdb|pdb\.set_trace\(' \
  "Python debugger call left in."
rule focused-test        error "$TESTS" '(^|[^A-Za-z0-9_])(describe|it|test|context)\.only\(|(^|[^A-Za-z0-9_])f(it|describe)\(' \
  ".only / fit / fdescribe focuses the suite and silently skips other tests."
rule skipped-test        warning "$TESTS" '(^|[^A-Za-z0-9_])(describe|it|test)\.skip\(|@pytest\.mark\.skip|unittest\.skip' \
  "skipped test. Agents must not skip tests; owner decisions only."
rule stripe-live-secret  error '.'      'sk_live_[0-9A-Za-z]{10,}|rk_live_[0-9A-Za-z]{10,}' \
  "Stripe/Clerk live secret key committed. Rotate it and move it to a secret store."
rule test-key-in-prod    error "$PRODCFG" '(pk|sk)_test_[0-9A-Za-z]{10,}' \
  "test publishable/secret key (pk_test_/sk_test_) in production config."
rule webhook-secret      error '.'      'whsec_[0-9A-Za-z]{20,}' \
  "webhook signing secret committed."
rule cloud-key           error '.'      'AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|gh[pousr]_[0-9A-Za-z]{36}|xox[baprs]-[0-9A-Za-z-]{10,}|-----BEGIN ([A-Z]+ )?PRIVATE KEY-----' \
  "cloud/API credential or private key committed."
rule ts-suppression      warning "$JS"  '@ts-ignore|@ts-nocheck|eslint-disable' \
  "type/lint suppression added; fix the cause instead."

echo "review-rules ($mode): $errors error(s), $warnings warning(s)."
[ "$errors" -eq 0 ]
