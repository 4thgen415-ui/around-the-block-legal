#!/usr/bin/env bash
# OWNER ONLY: allow edits to guardrails (creates a marker inside .git, never committed).
# Re-lock by deleting the marker: rm "$(git rev-parse --absolute-git-dir)/ai-guardrails-unlocked"
set -euo pipefail
gitdir="$(git rev-parse --absolute-git-dir)"
touch "$gitdir/ai-guardrails-unlocked"
