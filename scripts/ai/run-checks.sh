#!/usr/bin/env bash
# run-checks.sh - the repo's REAL lint / typecheck / test / build commands
# (taken from package.json scripts, pyproject and existing CI; see AGENTS.md).
# Generated for around-the-block-legal on 2026-10-25. A check the repo does not have prints
# NOT CONFIGURED (GitHub warning + step summary) instead of pretending to pass.
# Usage: scripts/ai/run-checks.sh lint|typecheck|test|build|all
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
export CI="${CI:-true}"

declare -A installed=()
ni() { # install node deps in DIR once per run
  local dir="$1"
  [ -n "${installed[$dir]:-}" ] && return 0
  if [ -f "$dir/pnpm-lock.yaml" ] || { [ "$dir" != "." ] && [ -f pnpm-workspace.yaml ] && [ -f pnpm-lock.yaml ]; }; then
    (cd "$dir" && pnpmx install --frozen-lockfile)
  elif [ -f "$dir/package-lock.json" ]; then
    (cd "$dir" && npm ci --no-audit --no-fund)
  else
    (cd "$dir" && npm install --no-audit --no-fund)
  fi
  installed[$dir]=1
}
pnpmx() { # pnpm at the version pinned in package.json "packageManager" (fallback 10)
  local v
  v="$(node -e 'try{const p=require(process.cwd()+"/package.json").packageManager||"";const m=p.match(/^pnpm@([^+]+)/);process.stdout.write(m?m[1]:"")}catch(e){}' 2>/dev/null || true)"
  npx --yes "pnpm@${v:-10}" "$@"
}
x() { local dir="$1"; shift; (cd "$dir" && "$@"); }
pyi() { python3 -m pip install -q --disable-pip-version-check "$@"; }
not_configured() {
  local check="$1" suggestion="$2"
  echo "NOT CONFIGURED: this repo has no $check command. Suggested free addition: $suggestion"
  if [ -n "${GITHUB_ACTIONS:-}" ]; then
    echo "::warning title=$check NOT CONFIGURED::This repo has no $check command (nothing was run). Suggested: $suggestion"
    echo "### $check: NOT CONFIGURED - nothing was run. Suggested: $suggestion" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
  fi
}

run_lint() {
  not_configured lint "npx --yes html-validate@latest '**/*.html' (free, no config needed)"
}
run_typecheck() {
  not_configured typecheck "n/a for plain HTML/JS; optional: add // @ts-check + npx --yes -p typescript tsc --allowJs --checkJs --noEmit"
}
run_test() {
  not_configured test "add a tiny node --test smoke test (e.g. checks index.html links/IDs exist)"
}
run_build() {
  not_configured build "n/a (static site served as-is)"
}

case "${1:-}" in
  lint|typecheck|test|build) "run_$1" ;;
  all) run_lint; run_typecheck; run_test; run_build ;;
  *) echo "usage: $0 lint|typecheck|test|build|all" >&2; exit 64 ;;
esac
