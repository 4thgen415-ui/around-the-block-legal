#!/usr/bin/env bash
# Install the AI guardrail git hooks for this clone (local only; idempotent).
# Uses core.hooksPath so the hooks stay versioned in scripts/ai/hooks/.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
chmod +x scripts/ai/hooks/* scripts/ai/*.sh
git config core.hooksPath scripts/ai/hooks
echo "install-hooks: core.hooksPath=scripts/ai/hooks (pre-commit active)."
